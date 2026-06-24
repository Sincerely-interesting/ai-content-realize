#!/usr/bin/env python3
"""
得物平台引力任务素材 — Gemma-4 / MINICPM 批量归档脚本
=====================================================
从 /Volumes/得物平台/引力任务素材/ 随机抽取 N 个素材文件夹，
支持按素材类型过滤（图片 / 视频 / 全部），
使用视觉模型分析每个文件夹的图片，
按 material_reference_content.md 的分镜头脚本格式，
为每个素材生成一份 Markdown 归档报告。

支持的模型提供商：
  - custom_minmax : google/gemma-4-26b-a4b (默认)
  - minicpm       : minicpm-v-4 (快速，~3秒/素材)
  - minmax        : MiniMax-M2.7
  - minmax_mcp    : MiniMax MCP (understand_image)
  - kimi          : kimi-k2.6
  - paddle        : qwen2.5-vl-32b-instruct

素材类型判断规则：
  image — 文件夹内无 .mp4 文件（纯图片素材）
  video — 文件夹内含有 .mp4 文件（视频素材，使用 ffmpeg 按 1fps 抽帧后分析）
  all   — 不过滤，两种都处理

视频处理流程：
  .mp4  →  ffmpeg 1fps 抽帧  →  临时 JPEG  →  pick MAX_IMAGES 帧  →  vision API

依赖：ffmpeg（brew install ffmpeg）

依赖环境变量（~/.zshrc）：
  CUSTOM_MINMAX_API_KEY  — Custom MiniMax API 鉴权 Token
  CUSTOM_MINMAX_URL      — Custom MiniMax 推理端点 base_url
  MINICPM_API_KEY        — MINICPM API 鉴权 Token
  MINICPM_BASE_URL       — MINICPM 推理端点 (默认: https://llm-center.ali.modelbest.cn/llm/v1)
  MINICPM_INSTRUCT_MODEL_ID — MINICPM 模型名称 (默认: minicpm-v-4)

用法：
  # 使用默认的 Gemma-4
  python3 gemma_dewu_archiver.py --media-type image --sample 1000
  
  # 使用 MINICPM（速度更快）
  python3 gemma_dewu_archiver.py --provider minicpm --media-type image --sample 1000
  
  python3 gemma_dewu_archiver.py --media-type video  --sample 500
  python3 gemma_dewu_archiver.py --media-type all    --sample 1000 --test
"""

import os
import sys
import json
import base64
import random
import shutil
import asyncio
import argparse
import textwrap
import threading
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

# Force line-buffered stdout so logs appear immediately when redirected to a file
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

from openai import AsyncOpenAI
from tqdm import tqdm

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
SOURCE_DIR   = Path("/Volumes/得物平台/引力任务素材")
BASE_OUT_DIR = Path(__file__).parent / "dewu_material_archives"
SAMPLE_SIZE  = 1000          # default folders to process
MAX_IMAGES   = 0             # 0 = no limit, send ALL images in the folder
CONCURRENCY  = 1             # parallel API calls — keep at 1 for heavy vision requests (prevents 502)
REQUEST_GAP  = 5             # seconds to sleep between successful requests (gives GPU time to breathe)
MAX_RETRIES  = 5             # max retries with exponential backoff
TIMEOUT_SEC  = 180           # per-request timeout (reasoning model needs more time)
BACKOFF_BASE = 10            # exponential backoff base seconds: 10, 20, 40, 80, 160
MINMAX_QUOTA_WAIT   = 5 * 3600   # seconds to pause after MiniMax quota exhaustion (5-hour rolling window)
QUOTA_ERROR_SIGNALS = ("insufficient balance", "1008", "余额不足",
                        "quota exceeded", "balance", "rate limit")  # substrings that indicate quota error

IMG_EXTS   = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXT  = ".mp4"
VIDEO_FPS  = 1     # frames per second to extract from .mp4
FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"

# Provider configuration — resolved at startup via --provider flag
# custom_minmax : private LM-Studio server (CUSTOM_MINMAX_URL / CUSTOM_MINMAX_API_KEY)
# minmax        : official MiniMax cloud API (MINMAX_API_KEY)
PROVIDER_CONFIGS = {
    "custom_minmax": {
        "api_key_env": "CUSTOM_MINMAX_API_KEY",
        "base_url":    lambda: os.environ.get("CUSTOM_MINMAX_URL", "").strip().rstrip("/"),
        "model":       "google/gemma-4-26b-a4b",
    },
    "minmax": {
        "api_key_env": "MINMAX_API_KEY",
        "base_url":    lambda: "https://api.minimaxi.com/v1",
        "model":       "MiniMax-M2.7",
    },
    "minmax_mcp": {
        "api_key_env": "MINMAX_API_KEY",
        "base_url":    lambda: "https://api.minimaxi.com/v1",   # for text synthesis step
        "model":       "MiniMax-M2.7",
    },
    "kimi": {
        "api_key_env": "KIMI_API_KEY",
        "base_url":    lambda: "https://api.moonshot.cn/v1",
        "model":       "kimi-k2.6",
    },
    "kimi_coding": {
        "api_key_env": "KIMI_API_KEY",
        "base_url":    lambda: "https://api.kimi.com/coding/v1",
        "model":       "kimi-k2.6",
    },
    "paddle": {
        "api_key_env": "PADDLE_API_KEY",
        "base_url":    lambda: "https://aistudio.baidu.com/llm/lmapi/v3",
        "model":       "qwen2.5-vl-32b-instruct",
    },
    "minicpm": {
        "api_key_env": "MINICPM_API_KEY",
        "base_url":    lambda: os.environ.get("MINICPM_BASE_URL", "https://llm-center.ali.modelbest.cn/llm/v1").strip().rstrip("/"),
        "model":       os.environ.get("MINICPM_INSTRUCT_MODEL_ID", "minicpm-v-4"),
    }
}

# Mutable globals — overwritten by configure_provider() before use
API_PROVIDER = ""
API_KEY      = ""
API_BASE_URL = ""
API_MODEL    = ""


def configure_provider(provider: str):
    """Set module-level API globals based on the chosen provider."""
    global API_PROVIDER, API_KEY, API_BASE_URL, API_MODEL
    cfg          = PROVIDER_CONFIGS[provider]
    API_PROVIDER = provider
    API_KEY      = os.environ.get(cfg["api_key_env"], "").strip()
    API_BASE_URL = cfg["base_url"]()
    API_MODEL    = cfg["model"]


# ──────────────────────────────────────────────
# MiniMax MCP 图片理解
# ──────────────────────────────────────────────
class QuotaExhaustedError(Exception):
    """Raised when MiniMax reports balance / quota exhaustion (error 1008)."""


class MCPImageUnderstand:
    """
    Persistent minimax-coding-plan-mcp subprocess.
    Provides blocking understand(image_path, prompt) → str.
    Call via asyncio loop.run_in_executor for async usage.
    """

    def __init__(self, api_key: str):
        self.api_key  = api_key
        self._proc    = None
        self._lock    = threading.Lock()
        self._msg_id  = 0

    def start(self):
        import time as _t
        self._proc = subprocess.Popen(
            ["uvx", "minimax-coding-plan-mcp", "-y"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                **os.environ,
                "MINIMAX_API_KEY":  self.api_key,
                "MINIMAX_API_HOST": "https://api.minimaxi.com",
            },
            text=True,
            bufsize=1,
        )
        _t.sleep(4)   # wait for MCP server to boot
        self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "dewu-archiver", "version": "1.0"},
        })
        self._read_resp(timeout=20)
        print("[MCP] MiniMax understand_image MCP 就绪")

    def stop(self):
        if self._proc:
            self._proc.terminate()
            try:    self._proc.wait(timeout=5)
            except: self._proc.kill()
            self._proc = None

    def _rpc(self, method: str, params: dict):
        self._msg_id += 1
        req = json.dumps({
            "jsonrpc": "2.0",
            "id": self._msg_id,
            "method": method,
            "params": params,
        }) + "\n"
        self._proc.stdin.write(req)
        self._proc.stdin.flush()

    def _read_resp(self, timeout: int = 120):
        import time as _t
        deadline = _t.time() + timeout
        while _t.time() < deadline:
            try:
                line = self._proc.stdout.readline()
                if line and line.strip():
                    return json.loads(line.strip())
            except (json.JSONDecodeError, OSError):
                pass
            _t.sleep(0.05)
        return None

    def understand(self, image_path: str, prompt: str) -> str:
        """
        Blocking call to understand_image.
        Raises QuotaExhaustedError when API signals balance/quota failure.
        """
        with self._lock:
            self._rpc("tools/call", {
                "name": "understand_image",
                "arguments": {"prompt": prompt, "image_source": image_path},
            })
            resp = self._read_resp(timeout=120)

        if resp is None:
            raise RuntimeError("MCP understand_image: 超时，无响应")

        # Check for protocol-level error
        if "error" in resp:
            err = resp["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            for sig in QUOTA_ERROR_SIGNALS:
                if sig.lower() in msg.lower():
                    raise QuotaExhaustedError(msg)
            raise RuntimeError(f"MCP error: {msg}")

        # Extract text from result content
        result  = resp.get("result", {})
        content = result.get("content", []) if isinstance(result, dict) else []
        if isinstance(content, list):
            text = "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
        else:
            text = str(content)

        # Check for application-level quota signal embedded in text
        for sig in QUOTA_ERROR_SIGNALS:
            if sig.lower() in text.lower():
                raise QuotaExhaustedError(text[:200])

        return text

# ──────────────────────────────────────────────
# Prompt
# ──────────────────────────────────────────────
SYSTEM_PROMPT = textwrap.dedent("""\
你是一位专业的电商内容策划师，擅长解读产品图片并输出结构化的分镜头脚本。
请根据用户提供的产品素材图，生成一份完整的分镜头脚本归档报告。
输出必须使用中文，格式严格遵循用户要求的 Markdown 结构。
""")

USER_PROMPT_TEMPLATE = textwrap.dedent("""\
请根据以下 {n_images} 张{source_desc}，为素材ID「{material_id}」生成一份分镜头脚本归档报告。

**输出格式要求（严格遵循）**：

# 分镜头脚本

## 场景1：[根据图片内容命名场景]

### 故事脚本：
[描述该场景的故事情节、画面内容、传达的氛围和品牌调性]

### 运镜技巧：
[描述适合该场景的镜头运动方式，如推镜、拉镜、固定镜头、环绕等]

### 人物动作与特征：
[描述该场景中的人物（如有）动作、姿态、服饰特征，或产品展示方式]

---

（如有多个场景，继续按上述格式追加 场景2、场景3...）

**要求**：
- 场景数量：根据图片数量合理划分，通常 3-6 个场景
- 每个场景必须对应实际观察到的图片内容，不得凭空捏造
- 风格专业，适合电商广告内容策划使用
- 末尾追加一个「## 素材综合标签」章节，列出 3-5 个最适合的内容标签（如：明星穿搭、静物展示、场景种草等）
""")


# ──────────────────────────────────────────────
# Media-type classification
# ──────────────────────────────────────────────
def classify_folder(folder: Path) -> str:
    """
    Returns 'image', 'video', or 'empty'.
    Rule: any .mp4 present → 'video', otherwise → 'image'.
    """
    files = [p.suffix.lower() for p in folder.iterdir()]
    if not files:
        return "empty"
    if VIDEO_EXT in files:
        return "video"
    return "image"


def filter_folders_by_type(
    folders: list[Path], media_type: str, target: int = 0,
    exclude_ids=None,  # type: set[str] | None
) -> list[Path]:
    """
    Filter folder list by media_type: 'image' | 'video' | 'all'.
    Uses lazy evaluation: shuffles folders and stops as soon as `target`
    NEW (not in exclude_ids) matches are found.
    target=0 means scan everything.
    exclude_ids: set of material_id strings to skip (already archived).
    """
    exclude_ids = exclude_ids or set()

    if media_type == "all":
        print(f"[INFO] Media filter: all (no filtering)")
        result = [f for f in folders if f.name not in exclude_ids]
        return result

    need = target if target > 0 else len(folders)
    shuffled = folders.copy()
    random.seed(42)
    random.shuffle(shuffled)

    matched: list[Path] = []
    scanned = 0
    print(f"[INFO] Lazy-classifying folders "
          f"(type={media_type}, need={need}, skip={len(exclude_ids)} done) ...")
    for folder in shuffled:
        scanned += 1
        if folder.name in exclude_ids:
            continue   # already archived — skip without classifying
        if classify_folder(folder) == media_type:
            matched.append(folder)
        if len(matched) >= need:
            break
        if scanned % 500 == 0:
            print(f"[INFO]   scanned={scanned}  matched={len(matched)}")

    print(f"[INFO] Scanned {scanned} folders, matched {len(matched)} [{media_type}]")
    return matched


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def encode_image(image_path: Path) -> str:
    """Base64-encode a JPEG/PNG for the vision API."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def get_mime(path: Path) -> str:
    ext = path.suffix.lower()
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "gif": "image/gif", "webp": "image/webp"}.get(ext.lstrip("."), "image/jpeg")


def pick_evenly(paths: list[Path], max_count: int) -> list[Path]:
    """Select up to max_count paths, evenly spread across the list."""
    if len(paths) <= max_count:
        return paths
    step = len(paths) / max_count
    return [paths[int(i * step)] for i in range(max_count)]


def pick_images(folder: Path, max_count: int) -> list[Path]:
    """Return all images from folder. If max_count > 0, spread-sample to that many."""
    imgs = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMG_EXTS)
    if max_count <= 0:
        return imgs  # no limit: return everything
    return pick_evenly(imgs, max_count)


def extract_video_frames(video_path: Path, temp_dir: Path) -> list[Path]:
    """
    Use ffmpeg to extract 1 frame/sec from video into temp_dir.
    Returns sorted list of extracted JPEG frame paths.
    Raises RuntimeError if ffmpeg fails.
    """
    out_pattern = str(temp_dir / "frame_%04d.jpg")
    cmd = [
        FFMPEG_BIN,
        "-i", str(video_path),
        "-vf", f"fps={VIDEO_FPS}",
        "-q:v", "2",          # JPEG quality: 2 = high
        out_pattern,
        "-y",
        "-loglevel", "error", # suppress progress noise
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed (exit={result.returncode}): {result.stderr.strip()[:300]}"
        )
    frames = sorted(temp_dir.glob("frame_*.jpg"))
    if not frames:
        raise RuntimeError(f"ffmpeg produced no frames from {video_path.name}")
    return frames


def build_messages(
    material_id: str, images: list[Path], is_video: bool = False
) -> list[dict]:
    """Build vision messages compatible with selected provider."""
    source_desc = (
        f"视频逐帧截图（{VIDEO_FPS}fps 抽帧）" if is_video else "产品素材图片"
    )
    content = [
        {
            "type": "text",
            "text": USER_PROMPT_TEMPLATE.format(
                n_images=len(images),
                material_id=material_id,
                source_desc=source_desc,
            ),
        }
    ]
    for img_path in images:
        # For Paddle provider, use file:// URL format with proper macOS escaping
        # Paddle API expects URLs that it can retrieve, not local file paths
        if API_PROVIDER == "paddle":
            # Convert local path to file:// URL with proper URL encoding for macOS
            import urllib.parse
            file_url = f"file://{urllib.parse.quote(str(img_path.absolute()))}"
            content.append({
                "type": "image_url",
                "image_url": {"url": file_url},
            })
        else:
            # Standard OpenAI-compatible format for other providers
            b64 = encode_image(img_path)
            mime = get_mime(img_path)
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            })
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def build_report(
    material_id: str,
    images: list[Path],
    llm_output: str,
    media_type: str = "image",
    output_dir: Path = BASE_OUT_DIR,
    video_name: str = "",
    total_frames: int = 0,
) -> str:
    """Wrap LLM output with metadata header."""
    ts = datetime.now().isoformat(timespec="seconds")
    img_list = "\n".join(f"{i+1}. `{p.name}`" for i, p in enumerate(images))
    type_label = {"image": "图片素材", "video": "视频素材", "all": "混合素材"}.get(media_type, media_type)
    video_meta = ""
    if video_name:
        video_meta = (
            f"\n- **原视频文件**: {video_name}"
            f"\n- **总抽帧数**: {total_frames} 帧（{VIDEO_FPS}fps）"
            f"\n- **送入模型帧数**: {len(images)} 帧"
        )
    return f"""# 素材归档报告

## 基本信息
- **素材ID**: {material_id}
- **素材类型**: {type_label}
- **归档时间**: {ts}{video_meta}
- **分析图片数**: {len(images)} 张
- **模型**: {API_MODEL}

---

{llm_output.strip()}

---

## 素材文件清单
{img_list}

---
*本报告由 google/gemma-4-26b-a4b 视觉模型自动生成*
*生成时间: {ts}*
"""


# ──────────────────────────────────────────────
# OpenAI async client (module-level, reused across calls)
# ──────────────────────────────────────────────
def make_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=API_KEY,
        base_url=API_BASE_URL,   # e.g. http://82.158.225.15:1234/v1
        timeout=TIMEOUT_SEC,
        max_retries=0,           # we handle retries manually
    )


# ──────────────────────────────────────────────
# Core async worker
# ──────────────────────────────────────────────
async def call_api(client: AsyncOpenAI, messages: list[dict]) -> str:
    import openai
    import math

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = await client.chat.completions.create(
                model=API_MODEL,
                messages=messages,
                max_completion_tokens=8000,  # no image cap → more content expected
                temperature=0.4,
                top_p=0.8,
            )
            # gemma-4 may put output in content or reasoning_content
            content = resp.choices[0].message.content or ""
            if not content.strip():
                content = getattr(resp.choices[0].message, "reasoning_content", "") or ""
            return content

        except openai.AuthenticationError as e:
            # Fatal — wrong key, no point retrying
            raise ValueError(
                f"API 鉴权失败 (401)：请检查 CUSTOM_MINMAX_API_KEY 是否正确\n{e}"
            )

        except (openai.APITimeoutError, openai.APIConnectionError) as e:
            # Timeout / network drop — exponential backoff
            wait = BACKOFF_BASE * (2 ** (attempt - 1))  # 10 20 40 80 160 s
            if attempt == MAX_RETRIES:
                raise RuntimeError(
                    f"Request timed out after {MAX_RETRIES} retries: {e}"
                ) from e
            print(
                f"\n[RETRY {attempt}/{MAX_RETRIES}] Timeout/conn error — "
                f"waiting {wait}s before retry ...  ({type(e).__name__})"
            )
            await asyncio.sleep(wait)

        except openai.RateLimitError:
            # Rate limited — linear backoff (server tells us to slow down)
            wait = BACKOFF_BASE * attempt   # 10 20 30 40 50 s
            if attempt == MAX_RETRIES:
                raise
            print(f"\n[RETRY {attempt}/{MAX_RETRIES}] Rate limited — waiting {wait}s ...")
            await asyncio.sleep(wait)

        except openai.APIStatusError as e:
            # 5xx server errors — exponential backoff
            wait = BACKOFF_BASE * (2 ** (attempt - 1))
            if e.status_code in (502, 503, 504, 500) and attempt < MAX_RETRIES:
                print(
                    f"\n[RETRY {attempt}/{MAX_RETRIES}] HTTP {e.status_code} — "
                    f"waiting {wait}s before retry ..."
                )
                await asyncio.sleep(wait)
            else:
                raise

    raise RuntimeError(f"超过最大重试次数 ({MAX_RETRIES})仍失败")


async def analyze_folder_minmax_mcp(
    mcp: MCPImageUnderstand,
    openai_client: AsyncOpenAI,
    material_id: str,
    image_paths: list,
    is_video: bool,
) -> str:
    """
    MiniMax MCP two-step vision pipeline:
      1. understand_image per frame/image  → per-image text description
      2. Synthesize all descriptions into a structured report via MiniMax-M2.7 text API

    Quota exhaustion (error 1008) triggers a 5-hour wait then retry.
    """
    loop = asyncio.get_event_loop()
    IMG_PROMPT = (
        "请详细描述这张图片的内容，包括："
        "人物（如有）的服装/动作/表情，产品外观/细节/材质，场景/背景/光线，以及整体氛围和风格调性。"
    )

    descriptions = []
    for i, img_path in enumerate(image_paths, 1):
        label = f"「图{i}/{len(image_paths)}」"
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                desc = await loop.run_in_executor(
                    None, mcp.understand, str(img_path), IMG_PROMPT
                )
                descriptions.append(f"{label}\n{desc}")
                await asyncio.sleep(1)   # small gap between MCP calls
                break

            except QuotaExhaustedError:
                hrs = MINMAX_QUOTA_WAIT // 3600
                print(
                    f"\n[QUOTA] MiniMax 五小时滚动窗口额度耗尽——等待 {hrs} 小时后自动继续。"
                    f"""当前：{label}尝试{attempt}/{MAX_RETRIES}"""
                )
                await asyncio.sleep(MINMAX_QUOTA_WAIT)
                # fall through to retry the same image

            except Exception as e:
                wait = BACKOFF_BASE * (2 ** (attempt - 1))
                if attempt == MAX_RETRIES:
                    descriptions.append(f"{label}（分析失败: {e}）")
                    break
                print(f"\n[RETRY {attempt}/{MAX_RETRIES}] MCP 错误 {label}: {e} —— {wait}s 后重试...")
                await asyncio.sleep(wait)

    # Step 2: synthesise into structured report via MiniMax-M2.7 text API
    combined     = "\n\n".join(descriptions)
    source_desc  = "视频逐帧截图（1fps抒帧）" if is_video else "产品素材图片"
    n            = len(image_paths)
    user_msg = (
        USER_PROMPT_TEMPLATE.format(
            n_images=n, source_desc=source_desc, material_id=material_id
        )
        + "\n\n以下是每张图片的AI视觉分析描述，请据此生成分镜头脚本归档报告：\n\n"
        + combined
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_msg},
    ]
    return await call_api(openai_client, messages)


async def process_folder(
    semaphore: asyncio.Semaphore,
    client: AsyncOpenAI,
    folder: Path,
    pbar: tqdm,
    media_type: str = "image",
    output_dir: Path = BASE_OUT_DIR,
    mcp=None,   # MCPImageUnderstand | None  (only for minmax_mcp provider)
) -> tuple[str, bool, str]:
    """Returns (material_id, success, message)."""
    material_id = folder.name
    out_path = output_dir / f"{material_id}_report.md"

    # Resume: skip already done
    if out_path.exists():
        pbar.update(1)
        return material_id, True, "skipped (already exists)"

    async with semaphore:
        try:
            # ── Determine whether this folder is a video folder ──────────
            mp4_files = sorted(
                p for p in folder.iterdir() if p.suffix.lower() == VIDEO_EXT
            )
            is_video = bool(mp4_files)

            # ── Image acquisition ────────────────────────────────────────
            video_name   = ""
            total_frames = 0
            llm_output   = None
            messages     = None

            if is_video:
                # Extract 1fps frames into a temp directory, then pick evenly
                video_path = mp4_files[0]     # use first .mp4 if multiple
                video_name = video_path.name
                with tempfile.TemporaryDirectory(prefix="dewu_frames_") as tmp:
                    tmp_path = Path(tmp)
                    all_frames = extract_video_frames(video_path, tmp_path)
                    total_frames = len(all_frames)
                    # MAX_IMAGES=0 means send all frames
                    picked = pick_evenly(all_frames, MAX_IMAGES) if MAX_IMAGES > 0 else all_frames
                    if mcp is not None:
                        # MCP uses real file paths — call INSIDE the temp dir context
                        llm_output = await analyze_folder_minmax_mcp(
                            mcp, client, material_id, picked, is_video=True
                        )
                    else:
                        # Must base64-encode NOW while tmp dir still exists
                        messages = build_messages(material_id, picked, is_video=True)
            else:
                images = pick_images(folder, MAX_IMAGES)
                if not images:
                    pbar.update(1)
                    return material_id, False, "no images found"
                picked = images
                if mcp is not None:
                    llm_output = await analyze_folder_minmax_mcp(
                        mcp, client, material_id, picked, is_video=False
                    )
                else:
                    messages = build_messages(material_id, picked, is_video=False)

            if not picked:
                pbar.update(1)
                return material_id, False, "no frames/images found"

            # Non-MCP path: call OpenAI-compatible chat completions with base64 images
            if llm_output is None:
                llm_output = await call_api(client, messages)
            report = build_report(
                material_id, picked, llm_output,
                media_type, output_dir,
                video_name=video_name,
                total_frames=total_frames,
            )

            out_path.write_text(report, encoding="utf-8")
            pbar.update(1)
            src_info = (
                f"{total_frames} frames→{len(picked)} sent"
                if is_video else f"{len(picked)} images"
            )
            # Brief cool-down so the GPU has time to breathe before the next request
            if REQUEST_GAP > 0:
                await asyncio.sleep(REQUEST_GAP)
            return material_id, True, src_info

        except ValueError as e:
            # Auth error — fatal, abort everything
            pbar.update(1)
            raise
        except Exception as e:
            # Non-fatal: save error marker and continue
            err_path = output_dir / f"{material_id}_error.txt"
            err_path.write_text(str(e), encoding="utf-8")
            pbar.update(1)
            return material_id, False, str(e)


# ──────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────
def validate_env(provider: str = "custom_minmax", check_ffmpeg: bool = False):
    cfg = PROVIDER_CONFIGS[provider]
    errors = []
    if not API_BASE_URL:
        errors.append(f"{cfg['api_key_env']} or base URL is not set")
    if not API_KEY:
        errors.append(f"{cfg['api_key_env']} is not set")
    if not SOURCE_DIR.exists():
        errors.append(f"Source dir not mounted: {SOURCE_DIR}")
    if check_ffmpeg and not shutil.which("ffmpeg"):
        errors.append(
            "ffmpeg not found — required for video mode. Install: brew install ffmpeg"
        )
    if provider == "minmax_mcp" and not shutil.which("uvx"):
        errors.append(
            "uvx not found — required for minmax_mcp. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
        )
    if errors:
        print("[ERROR] Missing configuration:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print(f"[OK] API base  : {API_BASE_URL}")
    print(f"[OK] Model     : {API_MODEL}")
    print(f"[OK] Source dir: {SOURCE_DIR}")
    if check_ffmpeg:
        print(f"[OK] ffmpeg    : {shutil.which('ffmpeg')}")


async def test_api_connection():
    """Verify API is reachable before batch processing."""
    print("\n[TEST] Verifying API connectivity...")
    client = make_client()
    try:
        messages = [{"role": "user", "content": "Reply with OK only."}]
        result = await call_api(client, messages)
        print(f"[OK]  API response: {result.strip()[:80]}")
        return True
    except ValueError as e:
        print(f"[FAIL] {e}")
        return False
    except Exception as e:
        print(f"[FAIL] Connection error: {type(e).__name__}: {e}")
        return False
    finally:
        await client.close()


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
async def main(sample_size: int, concurrency: int, test_mode: bool, media_type: str, provider: str):
    configure_provider(provider)
    needs_ffmpeg = media_type in ("video", "all")
    validate_env(provider=provider, check_ffmpeg=needs_ffmpeg)

    # All reports go to the flat archive root regardless of media type
    output_dir = BASE_OUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    # API connectivity check
    ok = await test_api_connection()
    if not ok:
        print("\n[ABORT] API is not reachable. Please check your API credentials and try again.")
        sys.exit(1)

    # Collect all material folders
    print(f"\n[INFO] Scanning {SOURCE_DIR} ...")
    all_folders = [p for p in SOURCE_DIR.iterdir() if p.is_dir()]
    print(f"[INFO] Total folders found: {len(all_folders)}")

    # Collect ALL already-archived material IDs across the entire archive tree
    # (flat dir + any subdirs like image/, video/)
    done_ids: set = {
        p.stem.replace("_report", "")
        for p in BASE_OUT_DIR.rglob("*_report.md")
    }
    print(f"[INFO] Already archived: {len(done_ids)} folders (across all subdirs)")

    # Filter by media type — lazy: stop once we have enough NEW matches
    # For test mode, we only need 3; otherwise need sample_size
    need = 3 if test_mode else sample_size
    if media_type != "all":
        all_folders = filter_folders_by_type(
            all_folders, media_type, target=need, exclude_ids=done_ids
        )
    else:
        print(f"[INFO] Media filter: all (no filtering)")
        all_folders = [f for f in all_folders if f.name not in done_ids]

    # Sample from type-filtered pool (already shuffled in lazy mode)
    if len(all_folders) <= need:
        selected = all_folders
    else:
        # all_folders already shuffled with seed=42 in lazy mode;
        # for 'all' mode apply shuffle here
        if media_type == "all":
            random.seed(42)
            random.shuffle(all_folders)
        selected = all_folders[:sample_size]
    print(f"[INFO] Using {len(selected)} folders from {len(all_folders)} matched")

    if test_mode:
        selected = selected[:3]
        print(f"[TEST] Test mode — processing first 3 folders only")

    # Check already done
    already_done = sum(1 for f in selected
                       if (output_dir / f"{f.name}_report.md").exists())
    print(f"[INFO] Already done: {already_done} / {len(selected)}")
    print(f"[INFO] Media type  : {media_type}")
    print(f"[INFO] Output dir  : {output_dir}")
    print(f"[INFO] Concurrency : {concurrency}")
    print()

    # Process
    semaphore = asyncio.Semaphore(concurrency)
    results = {"success": 0, "skipped": 0, "failed": 0}
    client = make_client()

    # Start MCP subprocess for minmax_mcp provider
    mcp = None
    if provider == "minmax_mcp":
        mcp = MCPImageUnderstand(api_key=API_KEY)
        mcp.start()

    try:
        with tqdm(total=len(selected), unit="folder", desc=f"Archiving [{media_type}]") as pbar:
            tasks = [
                process_folder(semaphore, client, folder, pbar, media_type, output_dir, mcp=mcp)
                for folder in selected
            ]
            for coro in asyncio.as_completed(tasks):
                try:
                    material_id, success, msg = await coro
                    if "skipped" in msg:
                        results["skipped"] += 1
                    elif success:
                        results["success"] += 1
                    else:
                        results["failed"] += 1
                        tqdm.write(f"[WARN] {material_id}: {msg}")
                except ValueError as e:
                    # Auth error — abort
                    tqdm.write(f"\n[FATAL] {e}")
                    tqdm.write("[ABORT] Stopping due to authentication error.")
                    break
    finally:
        await client.close()
        if mcp is not None:
            mcp.stop()

    # Summary
    print(f"\n{'='*50}")
    print(f"  Done!  Success={results['success']}  "
          f"Skipped={results['skipped']}  Failed={results['failed']}")
    print(f"  Reports saved to: {output_dir}")
    print(f"{'='*50}")


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="得物素材批量归档 (multi-provider vision)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        示例：
          # 私有 CUSTOM_MINMAX 服务器（默认）
          python3 gemma_dewu_archiver.py --media-type image --sample 1000

          # 官方 MiniMax 云端 API
          python3 gemma_dewu_archiver.py --provider minmax --media-type image --sample 500

          # MiniMax MCP：understand_image + 入平容文本合成
          python3 gemma_dewu_archiver.py --provider minmax_mcp --media-type image --sample 500

          # 飞桨千帆 Qwen2.5-VL 视觉模型
          python3 gemma_dewu_archiver.py --provider paddle --media-type image --sample 500

          # MINICPM 视觉模型（快速，~3秒/素材）
          python3 gemma_dewu_archiver.py --provider minicpm --media-type image --sample 500

          # 快速测试（3 个图片素材）
          python3 gemma_dewu_archiver.py --media-type image --test
        """),
    )
    parser.add_argument(
        "--provider",
        choices=["custom_minmax", "minmax", "minmax_mcp", "kimi", "kimi_coding", "paddle", "minicpm"],
        default="custom_minmax",
        help="API provider: custom_minmax=私有服务器, minmax=MiniMax直连, minmax_mcp=MiniMax+understand_image MCP, kimi=kimi-k2.6(moonshot), kimi_coding=kimi-k2.6(coding端点), paddle=飞桨千帆(qwen2.5-vl), minicpm=MINICPM视觉模型 (default: custom_minmax)",
    )
    parser.add_argument(
        "--media-type",
        choices=["image", "video", "all"],
        default="image",
        help="素材类型过滤：image=纯图片, video=含mp4, all=全部 (default: image)",
    )
    parser.add_argument("--sample",      type=int,  default=SAMPLE_SIZE,
                        help=f"Number of folders to process (default: {SAMPLE_SIZE})")
    parser.add_argument("--concurrency", type=int,  default=CONCURRENCY,
                        help=f"Parallel API calls (default: {CONCURRENCY})")
    parser.add_argument("--test",        action="store_true",
                        help="Test mode: process only 3 folders")
    args = parser.parse_args()

    asyncio.run(main(args.sample, args.concurrency, args.test, args.media_type, args.provider))
