"""
MiniMax MCP 多模态增强打标脚本 v2.0
核心升级：
1. 视频全量抽帧（1秒1帧）
2. 音频分离与语音转文字（Whisper STT）
3. 多模态融合分析（画面+语音文本）
4. 科技点讲解精准识别
"""
import os
import base64
import requests
import json
import pandas as pd
from PIL import Image
import io
import argparse
import glob
from datetime import datetime
import time
import logging
from typing import Optional, Tuple, Dict, Any, List
import random
import subprocess
import re

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('minimax_mcp_multimodal_labeling.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 加载 .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 导入抽帧逻辑
try:
    from extract_frames import extract_frames
except ImportError:
    def extract_frames(v, d, **kwargs): 
        logger.warning("⚠️ extract_frames 未找到")

# 导入MCP客户端
try:
    from minimax_mcp_client import MiniMaxMCPClient
    USE_MCP = True
    logger.info("✅ MCP客户端可用")
except ImportError:
    USE_MCP = False
    logger.warning("⚠️ MCP客户端未找到，将使用直接API调用")

# ---------------- 配置读取 ----------------
MINIMAX_API_KEY = os.getenv("MIN_MAX_API_KEY", "").strip()
MINIMAX_MODEL = os.getenv("MODEL_NAME", "MiniMax-M2.7").strip()
MINIMAX_VISION_API_URL = "https://api.minimaxi.com/v1/chat/completions"

# 图片压缩配置
IMAGE_MAX_SIZE = int(os.getenv("IMAGE_MAX_SIZE", "1024"))
IMAGE_QUALITY = int(os.getenv("IMAGE_QUALITY", "85"))

CACHE_FILE = 'minimax_mcp_multimodal_cache.json'
MEDIA_TYPE_CACHE = 'media_type_cache.json'  # 媒体类型预标记缓存

# 采样配置
SAMPLE_IDS_FILE = 'minimax_mcp_understand_full_results.xlsx'
MATERIALS_DIR = 'downloaded_materials'


def scan_and_classify_materials(materials_dir: str, force_rescan: bool = False) -> Dict[str, str]:
    """
    扫描素材文件夹，检测每个文件夹内是否存在 .mp4 文件，预标记媒体类型。

    规则:
      - 文件夹下有 *.mp4  -> 'video'
      - 文件夹下有 *.jpg/png  -> 'image'
      - 其他                    -> 'unknown'

    结果会缓存到 MEDIA_TYPE_CACHE 文件，避免重复扫描。
    使用 --force-rescan 可强制重建缓存。
    """
    # 尝试加载缓存
    if not force_rescan and os.path.exists(MEDIA_TYPE_CACHE):
        try:
            with open(MEDIA_TYPE_CACHE, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            logger.info(f"📂 已加载媒体类型缓存: {len(cached)} 个素材")
            return cached
        except Exception as e:
            logger.warning(f"⚠️  加载媒体类型缓存失败，将重新扫描: {e}")

    logger.info(f"🔍 扫描素材文件夹: {materials_dir}")
    media_types: Dict[str, str] = {}

    if not os.path.exists(materials_dir):
        logger.error(f"❌ 素材文件夹不存在: {materials_dir}")
        return media_types

    video_count = image_count = unknown_count = 0

    for folder_name in os.listdir(materials_dir):
        folder_path = os.path.join(materials_dir, folder_name)
        if not os.path.isdir(folder_path):
            continue
        has_video = bool(glob.glob(os.path.join(folder_path, '*.mp4')))
        has_image = bool(
            glob.glob(os.path.join(folder_path, '*.jpg')) +
            glob.glob(os.path.join(folder_path, '*.png'))
        )
        if has_video:
            media_types[folder_name] = 'video'
            video_count += 1
        elif has_image:
            media_types[folder_name] = 'image'
            image_count += 1
        else:
            media_types[folder_name] = 'unknown'
            unknown_count += 1

    # 保存缓存
    try:
        with open(MEDIA_TYPE_CACHE, 'w', encoding='utf-8') as f:
            json.dump(media_types, f, ensure_ascii=False, indent=4)
        logger.info(f"💾 媒体类型缓存已保存: {MEDIA_TYPE_CACHE}")
    except Exception as e:
        logger.warning(f"⚠️  保存媒体类型缓存失败: {e}")

    total = video_count + image_count + unknown_count
    logger.info(f"✅ 扫描完成: 总计 {total} 个文件夹 | 🎬 视频: {video_count} | 🖼️  图片: {image_count} | ❓ 未知: {unknown_count}")
    return media_types


def filter_and_limit_samples(all_ids: List[str], media_types: Dict[str, str],
                             target_type: Optional[str], limit: Optional[int]) -> List[str]:
    """
    从样本ID列表中按媒体类型筛选并限制数量。

    Args:
        all_ids:     Excel 中读出的所有 ID
        media_types: scan_and_classify_materials 返回的字典
        target_type: 'image' / 'video' / None(全部)
        limit:       最多处理多少个，None 表示不限制
    """
    if target_type:
        filtered = [mid for mid in all_ids if media_types.get(mid) == target_type]
        logger.info(f"📋 筛选类型 [{target_type}]: {len(filtered)} 个")
    else:
        filtered = all_ids
        logger.info(f"📋 不筛选类型，全部 {len(filtered)} 个")

    if limit and limit > 0:
        before = len(filtered)
        filtered = filtered[:limit]
        logger.info(f"📊 数量限制: {limit}, 实际待处理 {len(filtered)} 个 (共 {before} 个符合条件)")

    return filtered


def extract_audio_from_video(video_path: str, output_audio_path: str) -> bool:
    """
    从视频中提取音频轨道
    
    Args:
        video_path: 视频文件路径
        output_audio_path: 输出音频文件路径（.wav格式）
        
    Returns:
        bool: 是否成功
    """
    try:
        logger.info(f"🎵 开始提取音频: {os.path.basename(video_path)}")
        
        # 使用ffmpeg提取音频
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-vn',  # 禁用视频
            '-acodec', 'pcm_s16le',  # 音频编码：PCM 16位
            '-ar', '16000',  # 采样率：16kHz（Whisper推荐）
            '-ac', '1',  # 单声道
            '-y',  # 覆盖输出文件
            output_audio_path
        ]
        
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=300  # 5分钟超时
        )
        
        if result.returncode == 0 and os.path.exists(output_audio_path):
            audio_size = os.path.getsize(output_audio_path)
            logger.info(f"✅ 音频提取成功: {audio_size/1024/1024:.1f}MB")
            return True
        else:
            logger.error(f"❌ 音频提取失败: {result.stderr.decode('utf-8', errors='ignore')[:200]}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error(f"❌ 音频提取超时（>5分钟）: {video_path}")
        return False
    except FileNotFoundError:
        logger.error(f"❌ ffmpeg 未安装，请先安装 ffmpeg")
        return False
    except Exception as e:
        logger.error(f"❌ 音频提取异常: {e}", exc_info=True)
        return False


def transcribe_audio_whisper(audio_path: str, api_key: Optional[str] = None) -> Optional[str]:
    """
    使用 Whisper API 进行语音转文字
    
    Args:
        audio_path: 音频文件路径
        api_key: OpenAI API Key（如果为None，尝试使用本地Whisper）
        
    Returns:
        str: 转录文本
    """
    try:
        logger.info(f"🎤 开始语音识别: {os.path.basename(audio_path)}")
        
        # 方案1: 使用 OpenAI Whisper API（需要API Key）
        if api_key:
            return transcribe_with_openai_api(audio_path, api_key)
        
        # 方案2: 使用本地 Whisper 模型（免费，但需要安装）
        else:
            return transcribe_with_local_whisper(audio_path)
            
    except Exception as e:
        logger.error(f"❌ 语音识别异常: {e}", exc_info=True)
        return None


def transcribe_with_openai_api(audio_path: str, api_key: str) -> Optional[str]:
    """使用 OpenAI Whisper API 转录"""
    try:
        url = "https://api.openai.com/v1/audio/transcriptions"
        headers = {
            "Authorization": f"Bearer {api_key}"
        }
        
        with open(audio_path, 'rb') as f:
            files = {
                'file': ('audio.wav', f, 'audio/wav'),
                'model': (None, 'whisper-1'),
                'language': (None, 'zh')  # 中文
            }
            
            resp = requests.post(url, headers=headers, files=files, timeout=120)
            
            if resp.status_code == 200:
                data = resp.json()
                text = data.get('text', '')
                logger.info(f"✅ Whisper API 转录成功，文本长度: {len(text)}字符")
                return text
            else:
                logger.error(f"❌ Whisper API 错误 ({resp.status_code}): {resp.text[:200]}")
                return None
                
    except Exception as e:
        logger.error(f"❌ OpenAI Whisper API 调用失败: {e}")
        return None


def transcribe_with_local_whisper(audio_path: str) -> Optional[str]:
    """使用本地 Whisper 模型转录（免费）"""
    try:
        import whisper
        
        logger.info("🔧 加载本地 Whisper 模型（base版本）...")
        model = whisper.load_model("base")
        
        logger.info("🎤 开始转录...")
        result = model.transcribe(
            audio_path,
            language='zh',  # 中文
            fp16=False  # 使用CPU
        )
        
        text = result.get('text', '').strip()
        logger.info(f"✅ 本地 Whisper 转录成功，文本长度: {len(text)}字符")
        return text
        
    except ImportError:
        logger.warning("⚠️  本地 Whisper 未安装，运行: pip install openai-whisper")
        return None
    except Exception as e:
        logger.error(f"❌ 本地 Whisper 转录失败: {e}")
        return None


def analyze_with_mcp(image_path: str, prompt: str, max_retries: int = 3) -> Optional[str]:
    """使用MCP Server进行视觉分析（支持Token Plan）"""
    try:
        logger.info(f"🔌 使用MCP Server分析: {os.path.basename(image_path)}")
        
        with MiniMaxMCPClient(MINIMAX_API_KEY) as client:
            result = client.understand_image(image_path, prompt)
            
            if result:
                # 检测 API 1008 余额不足错误
                if '1008' in result or 'insufficient balance' in result.lower():
                    logger.error(f"❌ MiniMax余额不足 (Error 1008)！请充值后重试。")
                    logger.error(f"   原始响应: {result}")
                    raise RuntimeError("API_BALANCE_INSUFFICIENT")
                # 检测其他 API 错误
                if result.startswith('Failed to') or 'API Error' in result:
                    logger.error(f"❌ MCP返回API错误: {result}")
                    return None
                logger.info(f"✅ MCP分析成功，返回内容长度: {len(result)}")
                return result
            else:
                logger.error("❌ MCP分析返回None")
                return None
                
    except RuntimeError as e:
        raise  # 余额不足，向上抛出终止任务
    except Exception as e:
        logger.error(f"❌ MCP分析异常: {e}")
        return None


def analyze_with_direct_api(frame_paths: List[str], prompt: str, max_retries: int = 3) -> Optional[str]:
    """使用直接API调用进行视觉分析（需要Pay-as-you-go）"""
    # 编码所有图片
    encoded_images = []
    for path in frame_paths:
        encoded = encode_image(path, max_size=IMAGE_MAX_SIZE, quality=IMAGE_QUALITY)
        if encoded:
            encoded_images.append(encoded)
    
    if not encoded_images:
        logger.error("❌ 所有图片编码失败")
        return None
    
    # 构建内容（图片 + 文本）
    content = []
    
    # 添加图片
    for encoded in encoded_images:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{encoded}"
            }
        })
    
    content.append({
        "type": "text",
        "text": prompt
    })
    
    # 构建请求
    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": MINIMAX_MODEL,
        "max_tokens": 2048,
        "messages": [
            {
                "role": "user",
                "content": content
            }
        ]
    }
    
    # 发送请求（带重试）
    for attempt in range(max_retries):
        try:
            resp = requests.post(MINIMAX_VISION_API_URL, headers=headers, json=payload, timeout=120)
            
            if resp.status_code == 200:
                data = resp.json()
                if "choices" in data and len(data["choices"]) > 0:
                    text_content = data["choices"][0].get("message", {}).get("content", "")
                    if text_content.strip():
                        logger.info(f"✅ 视觉分析成功，返回内容长度: {len(text_content)}")
                        return text_content
            
            elif resp.status_code == 529:
                wait_time = 10 * (2 ** attempt)
                logger.warning(f"⚠️  API服务过载(529)，等待{wait_time}s后重试...")
                time.sleep(wait_time)
                continue
            
            else:
                logger.error(f"❌ API错误({resp.status_code}): {resp.text[:200]}")
                return None
                
        except Exception as e:
            logger.error(f"❌ 请求异常: {e}")
            return None
    
    return None


def encode_image(path: str, max_size: int = 1024, quality: int = 85) -> Optional[str]:
    """处理并编码图片"""
    try:
        if not os.path.exists(path):
            return None
        
        img = Image.open(path)
        img.load()
        
        if img.mode in ('RGBA', 'P', 'LA'):
            img = img.convert('RGB')
        
        if max(img.size) > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=quality, optimize=True)
        encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
        
        return encoded
        
    except Exception as e:
        logger.error(f"❌ 图片编码失败 {path}: {e}")
        return None


def analyze_frames_with_vision(frame_paths: List[str], transcript: Optional[str], 
                                prompt: str, max_retries: int = 3) -> Optional[str]:
    """
    使用视觉模型分析多帧图片（结合语音文本）
    支持两种模式：
    1. MCP Server模式（支持Token Plan）
    2. 直接API模式（需要Pay-as-you-go）
    """
    if not frame_paths:
        return None
    
    # 限制最多分析10帧（避免token超限）
    if len(frame_paths) > 10:
        # 均匀采样
        step = len(frame_paths) // 10
        frame_paths = frame_paths[::step][:10]
        logger.info(f"📸 采样10帧进行分析")
    
    # 如果有语音文本，添加到提示词中
    enhanced_prompt = prompt
    if transcript:
        enhanced_prompt = f"""【语音转录内容】
{transcript[:2000]}

【视觉分析任务】
{prompt}

注意：请结合语音内容和画面，特别关注：
1. 语音中是否提到产品科技点（如中底缓震、外底抓地力、支撑性等）
2. 画面中是否有对应的科技点展示或讲解
3. 语音与画面是否匹配（讲解科技点时是否有对应的产品展示）"""
    
    # 模式1: 使用MCP Server（支持Token Plan）
    if USE_MCP:
        return analyze_with_mcp(frame_paths[0], enhanced_prompt, max_retries)
    
    # 模式2: 直接API调用（需要Pay-as-you-go）
    else:
        return analyze_with_direct_api(frame_paths, enhanced_prompt, max_retries)


def get_multimodal_label(video_path: str, frames_dir: str, transcript: Optional[str]) -> Tuple[str, str, Dict]:
    """
    多模态融合打标（画面+语音）
    
    Returns:
        (label, reason, info_dict)
    """
    info = {
        'frames_count': 0,
        'has_audio': transcript is not None,
        'transcript_length': len(transcript) if transcript else 0,
        'transcript_preview': transcript[:100] if transcript else ''
    }
    
    # 获取所有帧
    frames = sorted(glob.glob(os.path.join(frames_dir, '*.jpg')))
    info['frames_count'] = len(frames)
    
    if not frames:
        return "其他", "未找到视频帧", info
    
    # 构建打标提示词
    labeling_prompt = """你是一位专业的时尚与运动产品分析师。请分析视频帧和语音内容，将其归类为以下精准标签之一。

### 标签分类及判定标准：

1. **性能测试**（必须同时满足以下两个条件，缺一不可）
   
   **条件A：必须存在视频文件(.mp4) + 连续运动的帧**
   - 连续运动帧判定标准：
     * 多帧之间存在明显的位置变化、姿态变化、动作连贯性
     * 人物在实际运动场景中：起跳、奔跑、急停、变向、投篮等动态过程
     * 画面有动态模糊、动作连贯性等运动特征
   - 排除：静态摆拍、单纯行走展示、只有单帧变化
   
   **条件B：必须存在科技点讲解或展示**
   - 中底缓震科技：
     * 国际品牌：Nike ZoomX、Nike React、Nike Air Max、Adidas Boost、Adidas Lightstrike、New Balance Fresh Foam、ASICS Gel、Saucony PWRRUN、Brooks DNA Loft
     * 国产品牌：李宁䨻(bèng)科技、安踏氮科技、特步XTEP ACE(PISA超临界发泡)、361° QUIKFOAM、匹克态极(TAICHI)、必迈bmai发泡
     * 工艺：超临界发泡、珠粒发泡、板材发泡、氮气发泡
   - 外底科技：
     * 橡胶材质：Nike TUFF RB、Adidas AHAR+/Continental马牌、ASICS AASICSGRIP、李宁TUFF OS、安踏C202大底
     * 户外/徒步：Vibram黄金大底、Salmon Contagrip、Merrell Vibram
     * 设计：抓地力纹路、耐磨分区、排水凹槽、耳齿设计
   - 鞋面科技：
     * 编织技术：Nike Flyknit、Adidas Primeknit、李宁䨻丝、安踏A-FLASHFOAM
     * 防水透气：GORE-TEX、eVent、各家防水膜
     * 支撑包裹：Flywire飞线、TPU支撑架、 heel counter后跟稳定
   - 其他科技：
     * 碳板：全掌碳板、半掌碳板、碳纤维板推进系统
     * 稳定科技：抗扭转片、足弓支撑、后跟稳定器、四指侧向稳定
   - 视觉标记：文字标注、箭头指示、分解图、特写镜头、科技点放大展示
   - 语音标记：讲解科技名词、性能测试描述、对比评测、数据展示
   
   ⚠️ 必须同时满足条件A和条件B才能判定为【性能测试】，否则跳过此分类！

2. **明星穿搭**：识别到知名明星，街拍、活动现场或综艺片场

3. **穿搭精选 (核心)-穿搭种草**：全身图，清晰识别头部+躯干+脚部

4. **穿搭精选 (次要)-穿搭种草**：半身图，识别头部+躯干，无脚部

5. **单品展示 (剔除出穿搭)-上脚**：仅识别膝盖以下及脚部

6. **创意静物**：无人物，艺术置景（艺术风格迁移）或AI渲染效果

7. **静物展示**：无人物，纯底、平铺

8. **其他**：不属于以上分类

### 输出格式要求：
请直接输出 JSON 格式，包含 'label' 和 'reason' 字段。
示例：{"label": "性能测试", "reason": "视频展示运动员在跑道奔跑（连续运动帧），画面中框选了中底ZoomX科技并讲解能量回馈"}

请重点分析：
- 帧与帧之间是否存在连续运动（位置变化、姿态变化、动作连贯性）
- 是否有科技点讲解或展示（科技名词、特写、文字标注）
- 两个条件是否同时满足（运动帧 + 科技点）
- 如果不同步满足，请不要判定为性能测试"""
    
    # 调用视觉分析
    result = analyze_frames_with_vision(frames, transcript, labeling_prompt)
    
    if result:
        # 解析JSON
        try:
            # 尝试直接解析
            parsed = json.loads(result)
            label = parsed.get('label', '其他')
            reason = parsed.get('reason', '')
            return label, reason, info
        except:
            # 尝试从文本中提取JSON
            try:
                start = result.find('{')
                end = result.rfind('}') + 1
                if start != -1 and end > start:
                    json_str = result[start:end]
                    parsed = json.loads(json_str)
                    label = parsed.get('label', '其他')
                    reason = parsed.get('reason', '')
                    return label, reason, info
            except:
                pass
        
        # 关键词匹配（严格双条件）
        has_motion = any(kw in result for kw in ['连续运动', '动作连贯', '位置变化', '姿态变化', '动态过程', '奔跑', '起跳', '急停'])
        has_tech = any(kw in result for kw in ['ZoomX', 'React', 'Boost', '䨻', '氮科技', 'TUFF RB', 'AHAR', 'Flyknit', '碳板', '科技点', '中底', '外底', '超临界'])
        if '性能测试' in result or (has_motion and has_tech):
            return "性能测试", result[:300], info
        elif '明星' in result:
            return "明星穿搭", result[:300], info
        elif '全身' in result:
            return "穿搭精选 (核心)-穿搭种草", result[:300], info
    
    return "其他", "视觉分析失败", info


def process_image_material(image_paths: List[str]) -> Tuple[str, str, Dict]:
    """
    处理图片素材：全量图片视觉打标
    策略：逐张分析所有图片，汇总后进行综合判定（排除法）
    Returns:
        (label, reason, info_dict)
    """
    total_images = len(image_paths)
    logger.info(f"🖼️  开始处理图片素材: 共 {total_images} 张图片")
    info = {'frames_count': total_images, 'has_audio': False, 'transcript_length': 0, 'transcript_preview': '', 'individual_results': []}
    
    # === 阶段1: 逐张分析所有图片 ===
    descriptions = []
    for idx, img_path in enumerate(image_paths, 1):
        logger.info(f"   📸 [{idx}/{total_images}] 分析: {os.path.basename(img_path)}")
        
        # 单图分析提示词
        single_prompt = """你是一位专业的时尚与运动产品分析师。请详细描述这张图片的内容，包括：
1. 是否有人物出现？如果有，能看清哪些部位（头部、躯干、腿部、脚部）？
2. 人物是否在进行运动行为（跑步、跳跃等）？还是静态展示？
3. 是否有产品科技点的展示（特写镜头、文字标注、箭头指示）？
4. 背景场景是什么（运动场地、街拍、纯底、艺术布景）？
5. 是否识别到知名明星？
6. 整体画面风格（写真、评测、产品展示、静物）？

请直接输出描述性文字，不需要分类标签。"""
        
        if USE_MCP:
            desc = analyze_with_mcp(img_path, single_prompt)
        else:
            desc = analyze_with_direct_api([img_path], single_prompt)
        
        if desc:
            descriptions.append(f"【图片{idx}】{desc}")
            info['individual_results'].append({'file': os.path.basename(img_path), 'description': desc[:200]})
            logger.info(f"   ✅ 分析完成")
        else:
            logger.warning(f"   ⚠️  分析失败")
    
    if not descriptions:
        return "其他", "所有图片分析失败", info
    
    # === 阶段2: 综合所有描述进行排除法判定 ===
    logger.info(f"🧠 综合 {len(descriptions)} 张图片进行排除法判定...")
    
    all_descriptions = "\n\n".join(descriptions)
    
    meta_prompt = f"""你是一位专业的时尚与运动产品分析师。以下是同一素材文件夹中 {total_images} 张图片的详细描述，请综合所有信息进行分类。

### 所有图片描述：
{all_descriptions}

### 标签分类及判定标准（请严格按照排除法顺序判断）：

**排除法判定逻辑：**

Step 1 - 是否有人物？
  - 如果**所有图片都无人物** → 跳到 Step 5（静物类）
  - 如果有人物 → 继续 Step 2

Step 2 - 是否识别到知名明星？
  - 是 → **【明星穿搭】**"

Step 3 - 【性能测试】判定：
  ⚠️ 注意：纯图片素材（非视频）**不可能**满足【性能测试】的「连续运动帧」条件，因此图片文件夹永远跳过此分类！
  如果是视频素材，必须同时满足两个条件（缺一不可）：
  条件A：连续运动帧判定
    - 多帧之间存在明显的位置变化、姿态变化、动作连贯性
    - 人物在实际运动场景中的动态过程：起跳、奔跑、急停、变向、投篮
    - 排除：静态摆拍、单纯行走展示
  条件B：科技点讲解或展示
    - 中底缓震：ZoomX、React、Boost、䨻(bèng)科技、氮科技、Fresh Foam、态极(TAICHI)、QUIKFOAM、超临界发泡
    - 外底科技：TUFF RB、AHAR+、Vibram黄金大底、Continental马牌、抓地力纹路
    - 鞋面科技：Flyknit、Primeknit、GORE-TEX、䨻丝、防水透气膜
    - 其他科技：全掌碳板、抗扭转片、足弓支撑、后跟稳定器
    - 视觉标记：文字标注、箭头指示、特写镜头
    - 语音标记：讲解科技名词、性能测试描述、数据对比
  - **两个条件同时满足** → **【性能测试】**
  - 只满足其中一个 → 不判定为性能测试，跳到Step 4

Step 4 - 人物穿搭展示（按覆盖范围判定）：
  - 如果**有任意图片**能看清**头部+躯干+脚部**（全身图） → **【穿搭精选 (核心)-穿搭种草】**”
  - 如果**有任意图片**能看清**头部+躯干**但无脚部（半身图） → **【穿搭精选 (次要)-穿搭种草】**”
  - 如果**所有人物图片**都只能看清**膝盖以下及脚部** → **【单品展示 (剔除出穿搭)-上脚】**”

Step 5 - 无人物图片（静物类）：
  - 艺术置景、AI渲染效果、风格化 → **【创意静物】**”
  - 纯底、平铺、无艺术处理 → **【静物展示】**”

Step 6 - 不属于以上任何分类 → **【其他】**”

### 输出格式要求：
请直接输出 JSON 格式，包含 'label' 和 'reason' 字段。
示例：{{"label": "穿搭精选 (核心)-穿搭种草", "reason": "图1为全身穿搭展示（头部到脚部可见），图2为脚部特写，综合判定为穿搭精选核心"}}"""
    
    # 调用MCP进行综合判定
    if USE_MCP:
        # 综合判定只需选一张图作为载体（因为prompt已包含所有信息）
        final_result = analyze_with_mcp(image_paths[0], meta_prompt)
    else:
        final_result = analyze_with_direct_api([image_paths[0]], meta_prompt)
    
    if final_result:
        # 解析JSON
        try:
            parsed = json.loads(final_result)
            label = parsed.get('label', '其他')
            reason = parsed.get('reason', '')
            return label, reason, info
        except:
            try:
                start = final_result.find('{')
                end = final_result.rfind('}') + 1
                if start != -1 and end > start:
                    parsed = json.loads(final_result[start:end])
                    label = parsed.get('label', '其他')
                    reason = parsed.get('reason', '')
                    return label, reason, info
            except:
                pass
        # 关键词匹配兜底（图片素材不可能满足连续运动帧，跳过性能测试）
        # 注意：纯图片文件夹永远不会是“性能测试”，因为无法判定连续运动
        if '明星' in final_result:
            return "明星穿搭", final_result[:300], info
        elif '核心' in final_result or '全身' in final_result:
            return "穿搭精选 (核心)-穿搭种草", final_result[:300], info
        elif '次要' in final_result or '半身' in final_result:
            return "穿搭精选 (次要)-穿搭种草", final_result[:300], info
        elif '上脚' in final_result or '单品展示' in final_result:
            return "单品展示 (剔除出穿搭)-上脚", final_result[:300], info
        elif '创意静物' in final_result:
            return "创意静物", final_result[:300], info
        elif '静物展示' in final_result or '平铺' in final_result:
            return "静物展示", final_result[:300], info
        # 返回原始文本作为reason
        return "其他", final_result[:300], info
    
    return "其他", "视觉分析失败", info


def process_video_material(video_path: str, folder_path: str, 
                          whisper_api_key: Optional[str] = None) -> Tuple[str, str, Dict]:
    """
    处理视频素材：抽帧 + 音频提取 + 语音识别 + 多模态打标
    
    Returns:
        (label, reason, info_dict)
    """
    logger.info(f"🎬 开始处理视频: {os.path.basename(video_path)}")
    
    # 步骤1: 全量抽帧（1秒1帧）
    frames_dir = os.path.join(folder_path, 'minimax_mcp_multimodal_frames')
    os.makedirs(frames_dir, exist_ok=True)
    
    logger.info("📸 步骤1: 全量抽帧（1秒1帧）...")
    extract_frames(video_path, frames_dir, fps_interval=1)
    
    frames = glob.glob(os.path.join(frames_dir, '*.jpg'))
    if not frames:
        logger.error("❌ 抽帧失败")
        return "其他", "视频抽帧失败", {'frames_count': 0}
    
    logger.info(f"✅ 抽帧成功，共 {len(frames)} 帧")
    
    # 步骤2: 提取音频
    audio_path = os.path.join(folder_path, 'extracted_audio.wav')
    
    logger.info("🎵 步骤2: 提取音频轨道...")
    if extract_audio_from_video(video_path, audio_path):
        # 步骤3: 语音转文字
        logger.info("🎤 步骤3: 语音识别（STT）...")
        transcript = transcribe_audio_whisper(audio_path, api_key=whisper_api_key)
        
        if transcript:
            logger.info(f"✅ 语音识别成功，文本长度: {len(transcript)}字符")
            logger.info(f"📝 转录预览: {transcript[:150]}...")
        else:
            logger.warning("⚠️  语音识别失败，将仅使用画面分析")
            transcript = None
    else:
        logger.warning("⚠️  音频提取失败，将仅使用画面分析")
        transcript = None
    
    # 步骤4: 多模态融合打标
    logger.info("🧠 步骤4: 多模态融合打标...")
    label, reason, info = get_multimodal_label(video_path, frames_dir, transcript)
    
    return label, reason, info


def main():
    """主函数"""
    if not MINIMAX_API_KEY:
        logger.error("❌ 请先在 .env 中设置 MIN_MAX_API_KEY")
        return
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='MiniMax MCP 多模态增强打标')
    parser.add_argument('--whisper-api-key', type=str, help='OpenAI Whisper API Key（可选，默认使用本地Whisper）')
    parser.add_argument('--media-type', type=str, choices=['image', 'video', 'all'],
                        default='all', help='媒体类型筛选: image(图片) / video(视频) / all(全部), 默认 all')
    parser.add_argument('--limit', type=int, default=None,
                        help='指定处理数量上限，不填则全部处理')
    parser.add_argument('--force-rescan', action='store_true',
                        help='强制重新扫描媒体类型（忽略现有缓存）')
    parser.add_argument('--id-list', type=str, default=None,
                        help='指定打标素材ID集合，一行一个ID的文本文件（指定后忽略 --media-type 和 --limit）')
    args = parser.parse_args()
    
    logger.info("=" * 80)
    logger.info("🚀 MiniMax MCP 多模态增强打标任务 v2.0")
    logger.info(f"📦 视觉模型: {MINIMAX_MODEL}")
    logger.info(f"🎤 语音识别: {'OpenAI Whisper API' if args.whisper_api_key else '本地Whisper模型'}")
    if args.id_list:
        logger.info(f"📋 模式: 指定 ID 集合文件 ({args.id_list})")
    else:
        logger.info(f"🎯 媒体类型: {args.media_type}")
        if args.limit:
            logger.info(f"🔢 数量限制: {args.limit} 个")
        else:
            logger.info("🔢 数量限制: 不限制")
    logger.info("=" * 80)

    # 步骤1: 预标记媒体类型
    logger.info("\n📂 步骤1: 预标记媒体类型")
    media_types = scan_and_classify_materials(MATERIALS_DIR, force_rescan=args.force_rescan)

    # 步骤2: 确定样本ID列表
    if args.id_list:
        # 模式A: 从指定文件加载ID集合
        logger.info(f"\n📖 步骤2: 从 ID 集合文件加载 ({args.id_list})")
        if not os.path.exists(args.id_list):
            logger.error(f"❌ ID 集合文件不存在: {args.id_list}")
            return
        with open(args.id_list, 'r', encoding='utf-8') as f:
            all_ids = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        sample_ids = all_ids
        logger.info(f"   ✅ 共读入 {len(sample_ids)} 个指定ID（不筛选类型 / 不限制数量）")
    else:
        # 模式B: 从 Excel 读全量 + 筛选类型 + 限制数量
        logger.info(f"\n📖 步骤2: 读取样本列表 ({SAMPLE_IDS_FILE})")
        try:
            df_samples = pd.read_excel(SAMPLE_IDS_FILE)
            all_ids = df_samples['dynamiclink'].astype(str).tolist()
            logger.info(f"   ✅ 共读入 {len(all_ids)} 个样本ID")
        except Exception as e:
            logger.error(f"❌ 读取样本文件失败: {e}")
            return

        logger.info(f"\n🔍 步骤3: 筛选素材")
        target_type = None if args.media_type == 'all' else args.media_type
        sample_ids = filter_and_limit_samples(all_ids, media_types, target_type, args.limit)
    
    # 加载缓存
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            logger.info(f"💾 加载缓存: {len(cache)} 条记录")
        except:
            cache = {}
    
    # 过滤未处理的
    unprocessed = [mid for mid in sample_ids if mid not in cache]
    logger.info(f"\n📋 待处理: {len(unprocessed)} 个，已处理: {len(sample_ids) - len(unprocessed)} 个")
    
    if not unprocessed:
        logger.info("✅ 所有样本已处理完成")
        return
    
    materials_dir = MATERIALS_DIR
    stats = {'success': 0, 'failed': 0, 'video_count': 0, 'audio_count': 0}
    
    for idx, mid in enumerate(unprocessed, 1):
        path = os.path.join(materials_dir, mid)
        logger.info(f"\n{'='*80}")
        logger.info(f"📝 [{idx}/{len(unprocessed)}] 处理素材: {mid}")
        
        # 查找媒体文件
        vids = glob.glob(os.path.join(path, '*.mp4'))
        imgs = glob.glob(os.path.join(path, '*.jpg')) + glob.glob(os.path.join(path, '*.png'))
        
        label, reason, info = "其他", "无有效媒体", {}
        
        try:
            if vids:
                # 视频处理：抽帧 + 音频 + STT + 多模态打标
                stats['video_count'] += 1
                label, reason, info = process_video_material(
                    vids[0], path, 
                    whisper_api_key=args.whisper_api_key
                )
                
                if info.get('has_audio'):
                    stats['audio_count'] += 1
                    
            elif imgs:
                # 图片处理：全量图片综合分析（排除法判定）
                logger.info(f"🖼️  图片素材: 共 {len(imgs)} 张，逐张分析后综合判定")
                label, reason, info = process_image_material(imgs)
                
            else:
                logger.warning(f"⚠️  未找到媒体文件")
                
        except RuntimeError as e:
            if "API_BALANCE_INSUFFICIENT" in str(e):
                logger.error("\n" + "="*80)
                logger.error("🚨 MiniMax Token Plan 余额不足，任务中止！")
                logger.error("   请前往 https://platform.minimaxi.com 充值后重新运行脚本。")
                logger.error("   已缓存的结果不会丢失，充值后可续跑。")
                logger.error("="*80)
                break  # 中止循环，不要继续浪费
            label, reason = "其他", f"处理异常: {str(e)}"
        except Exception as e:
            logger.error(f"💥 处理异常: {e}", exc_info=True)
            label, reason = "其他", f"处理异常: {str(e)}"
        
        # 更新统计（成功 = 分析实际执行且有意义的结果，而非错误占位）
        failure_reasons = {"视觉分析失败", "无有效媒体", "视频抽帧失败", "处理异常"}
        if reason in failure_reasons or reason.startswith("处理异常"):
            stats['failed'] += 1
        else:
            stats['success'] += 1
        
        # 保存缓存
        cache[mid] = {
            'label': label,
            'reason': reason,
            'info': info,
            'time': datetime.now().isoformat()
        }
        
        # 定期保存
        if idx % 5 == 0:
            try:
                with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                    json.dump(cache, f, ensure_ascii=False, indent=4)
                logger.info(f"💾 缓存已保存 ({len(cache)}条)")
            except Exception as e:
                logger.warning(f"⚠️  缓存保存失败: {e}")
        
        # 进度报告
        if idx % 10 == 0:
            logger.info(f"\n{'='*80}")
            logger.info(f"📈 进度报告 [{idx}/{len(unprocessed)}]")
            logger.info(f"✅ 成功: {stats['success']} | ❌ 失败: {stats['failed']}")
            logger.info(f"🎬 视频数: {stats['video_count']} | 🎵 音频转录: {stats['audio_count']}")
            logger.info(f"{'='*80}")
    
    # 最终保存
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=4)
        logger.info(f"\n💾 缓存最终保存 ({len(cache)}条)")
    except Exception as e:
        logger.error(f"❌ 缓存保存失败: {e}")
    
    # 导出结果
    results = []
    for mid, data in cache.items():
        info = data.get('info', {})
        results.append({
            'daterange': datetime.now().strftime('%Y-%m-%d'),
            'dynamiclink': mid,
            '制作组类型（细分标签）': data['label'],
            '判定依据': data['reason'],
            '是否视频': info.get('frames_count', 0) > 0,
            '帧数': info.get('frames_count', 0),
            '是否有音频': info.get('has_audio', False),
            '语音文本长度': info.get('transcript_length', 0),
            '语音文本预览': info.get('transcript_preview', '')[:100]
        })
    
    if results:
        output_file = 'minimax_mcp_multimodal_results.xlsx'
        df = pd.DataFrame(results)
        df.to_excel(output_file, index=False)
        logger.info(f"\n✅ 结果导出成功: {output_file}")
    
    # 最终统计
    logger.info("\n" + "=" * 80)
    logger.info("🎯 多模态打标任务完成")
    logger.info("=" * 80)
    logger.info(f"📊 总样本数: {len(all_ids)}")
    logger.info(f"🔄 本次处理: {len(unprocessed)}")
    logger.info(f"✅ 成功: {stats['success']} | ❌ 失败: {stats['failed']}")
    logger.info(f"🎬 视频数: {stats['video_count']}")
    logger.info(f"🎵 音频转录: {stats['audio_count']}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
