"""CLI for searching similar samples from a local material folder."""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import httpx

from multimodal_label_eval.helpers import synthesize_sample_query
from multimodal_label_knowledge.rule_assets import KnowledgeBundle, load_knowledge_bundle
from multimodal_label_store import LanceStore, StoreConfig, StorePaths
from multimodal_label_store.backfill_from_cache import (
    LegacyCacheEntry,
    build_label_maps,
    build_sample_memory_record,
    derive_observation,
)

from .models import SearchFilters
from .retriever import RetrievalRepository

logger = logging.getLogger(__name__)

DEFAULT_CACHE_FILES = [
    "minimax_mcp_multimodal_cache.json",
    "minimax_mcp_label_cache.json",
    "minimax_label_cache.json",
]
PROMPT_LABEL_PRIORITY = [
    "性能测评",
    "明星穿搭",
    "穿搭精选 (核心)-穿搭种草",
    "穿搭精选 (次要)-穿搭种草",
    "单品展示 (剔除出穿搭)-上脚",
    "创意静物",
    "静物展示",
    "其他",
]


@dataclass(frozen=True)
class FolderSummary:
    folder_path: Path
    asset_id: str
    media_type: str
    image_files: list[Path]
    video_files: list[Path]
    sampled_images: list[Path]
    file_count: int
    frame_count: int
    has_audio: bool


@dataclass(frozen=True)
class QueryProbe:
    asset_id: str
    source: str
    query_text: str
    filters: SearchFilters
    sample_row: dict[str, Any]
    observation_row: dict[str, Any]
    label_id: Optional[str]
    label_display_name: Optional[str]


@dataclass(frozen=True)
class SearchExecution:
    mode: str
    results: list[dict[str, Any]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder_path", help="Local material folder path")
    parser.add_argument("--service-url", default="http://127.0.0.1:8000")
    parser.add_argument("--root", default="data/lance")
    parser.add_argument("--snapshot-root", default="data/snapshots")
    parser.add_argument("--embedding-dim", type=int, default=1536)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--lock-label", action="store_true")
    parser.add_argument("--prefer-live-analysis", action="store_true")
    parser.add_argument("--use-minimax", action="store_true")
    parser.add_argument("--minimax-api-key")
    parser.add_argument("--minimax-api-host", default="https://api.minimaxi.com")
    parser.add_argument("--cache-files", nargs="*", default=DEFAULT_CACHE_FILES)
    parser.add_argument("--explain-top-n", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _configure_logging(args.verbose)
    _load_dotenv_if_present()

    config = StoreConfig(
        embedding_dim=args.embedding_dim,
        paths=StorePaths(root=Path(args.root), snapshot_root=Path(args.snapshot_root)),
    )
    store = LanceStore(config)
    store.ensure_all_tables()
    bundle = load_knowledge_bundle()
    cache_payload = load_cache_payload(args.cache_files)
    payload = run_folder_search(
        folder_path=Path(args.folder_path),
        service_url=args.service_url,
        config=config,
        store=store,
        bundle=bundle,
        top_k=args.top_k,
        explain_top_n=args.explain_top_n,
        lock_label=args.lock_label,
        prefer_live_analysis=args.prefer_live_analysis,
        use_minimax=args.use_minimax,
        minimax_api_key=args.minimax_api_key or os.getenv("MIN_MAX_API_KEY", "").strip(),
        minimax_api_host=args.minimax_api_host,
        cache_files=args.cache_files,
        cache_payload=cache_payload,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(render_text_report(payload))
    return 0


def run_folder_search(
    *,
    folder_path: Path,
    service_url: str,
    config: StoreConfig,
    store: LanceStore,
    bundle: KnowledgeBundle,
    top_k: int,
    explain_top_n: int,
    lock_label: bool,
    prefer_live_analysis: bool,
    use_minimax: bool,
    minimax_api_key: str,
    minimax_api_host: str,
    cache_files: Sequence[str],
    cache_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    folder = summarize_folder(folder_path)
    probe = build_query_probe(
        folder=folder,
        store=store,
        config=config,
        bundle=bundle,
        cache_files=cache_files,
        cache_payload=cache_payload,
        use_minimax=use_minimax,
        prefer_live_analysis=prefer_live_analysis,
        minimax_api_key=minimax_api_key,
        minimax_api_host=minimax_api_host,
        lock_label=lock_label,
    )
    execution = execute_search(
        service_url=service_url,
        config=config,
        query_text=probe.query_text,
        filters=probe.filters,
        top_k=top_k,
    )
    explanations = fetch_explanations(
        service_url=service_url,
        config=config,
        asset_ids=[str(row.get("asset_id", "") or "") for row in execution.results[:explain_top_n]],
    )
    return render_payload(
        folder=folder,
        probe=probe,
        execution=execution,
        explanations=explanations,
    )


def summarize_folder(folder_path: Path) -> FolderSummary:
    if not folder_path.exists():
        raise FileNotFoundError(f"Folder not found: {folder_path}")
    if not folder_path.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {folder_path}")

    image_files = _sorted_globs(
        folder_path,
        patterns=["*.jpg", "*.jpeg", "*.png", "*.webp", "*.bmp"],
    )
    video_files = _sorted_globs(
        folder_path,
        patterns=["*.mp4", "*.mov", "*.m4v", "*.avi", "*.mkv"],
    )
    sampled_images, is_video_folder = collect_media_files(folder_path)
    media_type = "video" if video_files or is_video_folder else "image"

    return FolderSummary(
        folder_path=folder_path,
        asset_id=folder_path.name,
        media_type=media_type,
        image_files=image_files,
        video_files=video_files,
        sampled_images=sampled_images,
        file_count=max(1, len(image_files) + len(video_files)),
        frame_count=max(len(image_files), len(sampled_images)),
        has_audio=bool(video_files),
    )


def build_query_probe(
    *,
    folder: FolderSummary,
    store: LanceStore,
    config: StoreConfig,
    bundle: KnowledgeBundle,
    cache_files: Sequence[str],
    cache_payload: Mapping[str, Any] | None,
    use_minimax: bool,
    prefer_live_analysis: bool,
    minimax_api_key: str,
    minimax_api_host: str,
    lock_label: bool,
) -> QueryProbe:
    if not prefer_live_analysis:
        probe = _probe_from_lance(folder=folder, store=store)
        if probe:
            return _with_filters(probe, lock_label=lock_label)

        probe = _probe_from_cache(
            folder=folder,
            config=config,
            bundle=bundle,
            cache_files=cache_files,
            cache_payload=cache_payload,
        )
        if probe:
            return _with_filters(probe, lock_label=lock_label)

    if use_minimax:
        probe = _probe_from_minimax(
            folder=folder,
            config=config,
            bundle=bundle,
            minimax_api_key=minimax_api_key,
            minimax_api_host=minimax_api_host,
        )
        return _with_filters(probe, lock_label=lock_label)

    probe = _probe_from_heuristic(folder=folder, config=config)
    return _with_filters(probe, lock_label=lock_label)


def _probe_from_lance(folder: FolderSummary, store: LanceStore) -> QueryProbe | None:
    sample_row = next(
        (row for row in store.load_rows("sample_memories") if str(row.get("asset_id", "")) == folder.asset_id),
        None,
    )
    observation_row = next(
        (row for row in store.load_rows("observations") if str(row.get("asset_id", "")) == folder.asset_id),
        None,
    )
    if sample_row and observation_row:
        query_text = synthesize_sample_query(sample_row, observation_row)
        return QueryProbe(
            asset_id=folder.asset_id,
            source="lance_sample_memory",
            query_text=query_text,
            filters=SearchFilters(),
            sample_row=sample_row,
            observation_row=observation_row,
            label_id=_resolved_label_id(sample_row),
            label_display_name=_resolved_label_display_name(sample_row),
        )

    asset_row = next(
        (row for row in store.load_rows("assets") if str(row.get("asset_id", "")) == folder.asset_id),
        None,
    )
    if not asset_row or not observation_row:
        return None

    sample_like = {
        "asset_id": folder.asset_id,
        "label_id": asset_row.get("final_label_id"),
        "label_display_name": asset_row.get("final_label_display_name"),
        "semantic_label_id": asset_row.get("semantic_label_id"),
        "semantic_label_display_name": asset_row.get("semantic_label_display_name"),
        "decision_trace_text": f"reason={asset_row.get('final_reason', '')}",
        "rule_hits": [],
        "rule_misses": [],
        "evidence_positive": [],
        "evidence_negative": [],
        "normalized_summary": "",
    }
    query_text = synthesize_sample_query(sample_like, observation_row)
    return QueryProbe(
        asset_id=folder.asset_id,
        source="lance_asset",
        query_text=query_text,
        filters=SearchFilters(),
        sample_row=sample_like,
        observation_row=observation_row,
        label_id=_resolved_label_id(sample_like),
        label_display_name=_resolved_label_display_name(sample_like),
    )


def _probe_from_cache(
    *,
    folder: FolderSummary,
    config: StoreConfig,
    bundle: KnowledgeBundle,
    cache_files: Sequence[str],
    cache_payload: Mapping[str, Any] | None,
) -> QueryProbe | None:
    payload = cache_payload or load_cache_payload(cache_files)
    cache_row = payload.get(folder.asset_id)
    if not isinstance(cache_row, Mapping):
        return None

    display_to_id, _ = build_label_maps(bundle)
    label_display_name = str(cache_row.get("label", "") or "其他")
    label_id = display_to_id.get(label_display_name, "other")
    reason = str(cache_row.get("reason", "") or "")
    info = cache_row.get("info", {})
    if not isinstance(info, Mapping):
        info = {}
    entry = LegacyCacheEntry(
        asset_id=folder.asset_id,
        label_display_name=label_display_name,
        reason=reason,
        info={
            "frames_count": int(info.get("frames_count", folder.frame_count) or folder.frame_count),
            "has_audio": bool(info.get("has_audio", folder.has_audio)),
            "transcript_length": int(info.get("transcript_length", 0) or 0),
            "transcript_preview": str(info.get("transcript_preview", "") or ""),
            "individual_results": list(info.get("individual_results", [])) if isinstance(info.get("individual_results"), list) else [],
        },
        cache_time=None,
        media_type=folder.media_type,
    )
    observation_row = derive_observation(entry, label_id, config)
    sample_row = build_sample_memory_record(
        entry=entry,
        label_id=label_id,
        observation=observation_row,
        quality_score=0.7,
        config=config,
    )
    query_text = synthesize_sample_query(sample_row, observation_row)
    return QueryProbe(
        asset_id=folder.asset_id,
        source="cache_record",
        query_text=query_text,
        filters=SearchFilters(),
        sample_row=sample_row,
        observation_row=observation_row,
        label_id=_resolved_label_id(sample_row),
        label_display_name=_resolved_label_display_name(sample_row),
    )


def _probe_from_minimax(
    *,
    folder: FolderSummary,
    config: StoreConfig,
    bundle: KnowledgeBundle,
    minimax_api_key: str,
    minimax_api_host: str,
) -> QueryProbe:
    if not minimax_api_key:
        raise RuntimeError("MiniMax API key missing. Use --minimax-api-key or set MIN_MAX_API_KEY.")

    label_display_name, reason = analyze_folder_with_minimax(
        folder=folder,
        api_key=minimax_api_key,
        api_host=minimax_api_host,
    )
    display_to_id, _ = build_label_maps(bundle)
    label_id = display_to_id.get(label_display_name, "other")
    entry = LegacyCacheEntry(
        asset_id=folder.asset_id,
        label_display_name=label_display_name,
        reason=reason,
        info={
            "frames_count": folder.frame_count,
            "has_audio": folder.has_audio,
            "transcript_length": 0,
            "transcript_preview": "",
            "individual_results": [],
        },
        cache_time=None,
        media_type=folder.media_type,
    )
    observation_row = derive_observation(entry, label_id, config)
    sample_row = build_sample_memory_record(
        entry=entry,
        label_id=label_id,
        observation=observation_row,
        quality_score=0.75,
        config=config,
    )
    query_text = synthesize_sample_query(sample_row, observation_row)
    return QueryProbe(
        asset_id=folder.asset_id,
        source="minimax_live",
        query_text=query_text,
        filters=SearchFilters(),
        sample_row=sample_row,
        observation_row=observation_row,
        label_id=_resolved_label_id(sample_row),
        label_display_name=_resolved_label_display_name(sample_row),
    )


def _probe_from_heuristic(folder: FolderSummary, config: StoreConfig) -> QueryProbe:
    reason = build_heuristic_reason(folder)
    label_id, label_display_name = heuristic_label_guess(folder)
    entry = LegacyCacheEntry(
        asset_id=folder.asset_id,
        label_display_name=label_display_name,
        reason=reason,
        info={
            "frames_count": folder.frame_count,
            "has_audio": folder.has_audio,
            "transcript_length": 0,
            "transcript_preview": "",
            "individual_results": [],
        },
        cache_time=None,
        media_type=folder.media_type,
    )
    observation_row = derive_observation(entry, label_id, config)
    sample_row = build_sample_memory_record(
        entry=entry,
        label_id=label_id,
        observation=observation_row,
        quality_score=0.55,
        config=config,
    )
    query_text = synthesize_sample_query(sample_row, observation_row)
    if label_id == "other":
        query_text = " ".join(
            [
                folder.media_type,
                f"folder={folder.asset_id}",
                f"file_count={folder.file_count}",
                f"sampled_frames={len(folder.sampled_images)}",
                reason[:120],
            ]
        ).strip()
    return QueryProbe(
        asset_id=folder.asset_id,
        source="heuristic_probe",
        query_text=query_text,
        filters=SearchFilters(),
        sample_row=sample_row,
        observation_row=observation_row,
        label_id=_resolved_label_id(sample_row),
        label_display_name=_resolved_label_display_name(sample_row),
    )


def _with_filters(probe: QueryProbe, *, lock_label: bool) -> QueryProbe:
    observation = probe.observation_row
    label_id = probe.label_id
    filters = SearchFilters(
        media_type=observation.get("media_type") if observation.get("media_type") in {"image", "video"} else None,
        has_person=bool(observation.get("has_person")) if "has_person" in observation else None,
        has_celebrity_signal=(
            True if observation.get("has_celebrity_signal") and label_id == "celebrity_outfit" else None
        ),
        scene_type=(
            str(observation.get("scene_type"))
            if str(observation.get("scene_type", "") or "") not in {"", "unknown"}
            else None
        ),
        label_id=label_id if lock_label and label_id not in {None, "", "other"} else None,
    )
    return QueryProbe(
        asset_id=probe.asset_id,
        source=probe.source,
        query_text=probe.query_text,
        filters=filters,
        sample_row=probe.sample_row,
        observation_row=probe.observation_row,
        label_id=probe.label_id,
        label_display_name=probe.label_display_name,
    )


def execute_search(
    *,
    service_url: str,
    config: StoreConfig,
    query_text: str,
    filters: SearchFilters,
    top_k: int,
) -> SearchExecution:
    payload = {
        "query_text": query_text,
        "filters": filters.model_dump(exclude_none=True),
        "top_k": top_k,
    }
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                service_url.rstrip("/") + "/api/v1/search/similar-samples",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list):
                raise RuntimeError("Search API returned non-list payload.")
            return SearchExecution(mode="service_http", results=[dict(item) for item in data if isinstance(item, Mapping)])
    except Exception as exc:
        logger.warning("Search service unavailable, fallback to direct repository: %s", exc)

    repo = RetrievalRepository(config=config)
    rows = repo.search_similar_samples(query_text, filters, top_k=top_k)
    return SearchExecution(mode="repository_fallback", results=rows)


def fetch_explanations(
    *,
    service_url: str,
    config: StoreConfig,
    asset_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    cleaned_asset_ids = [asset_id for asset_id in asset_ids if asset_id]
    if not cleaned_asset_ids:
        return {}

    explanations: dict[str, dict[str, Any]] = {}
    try:
        with httpx.Client(timeout=20.0) as client:
            for asset_id in cleaned_asset_ids:
                response = client.post(
                    service_url.rstrip("/") + "/api/v1/search/explain",
                    json={"asset_id": asset_id},
                )
                response.raise_for_status()
                body = response.json()
                if isinstance(body, Mapping):
                    explanations[asset_id] = dict(body)
            return explanations
    except Exception as exc:
        logger.warning("Explain API unavailable, fallback to direct repository: %s", exc)

    repo = RetrievalRepository(config=config)
    for asset_id in cleaned_asset_ids:
        explanations[asset_id] = repo.explain_asset(asset_id)
    return explanations


def render_payload(
    *,
    folder: FolderSummary,
    probe: QueryProbe,
    execution: SearchExecution,
    explanations: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "folder": {
            "folder_path": str(folder.folder_path),
            "asset_id": folder.asset_id,
            "media_type": folder.media_type,
            "image_count": len(folder.image_files),
            "video_count": len(folder.video_files),
            "sampled_image_count": len(folder.sampled_images),
        },
        "query_probe": {
            "source": probe.source,
            "label_id": probe.label_id,
            "label_display_name": probe.label_display_name,
            "query_text": probe.query_text,
            "filters": probe.filters.model_dump(exclude_none=True),
            "observation_summary": {
                "has_person": probe.observation_row.get("has_person"),
                "body_parts_visible": probe.observation_row.get("body_parts_visible"),
                "is_full_body": probe.observation_row.get("is_full_body"),
                "is_foot_only": probe.observation_row.get("is_foot_only"),
                "has_celebrity_signal": probe.observation_row.get("has_celebrity_signal"),
                "celebrity_name_hint": probe.observation_row.get("celebrity_name_hint"),
                "scene_type": probe.observation_row.get("scene_type"),
                "still_life_style": probe.observation_row.get("still_life_style"),
            },
        },
        "search_execution": {
            "mode": execution.mode,
            "results": execution.results,
        },
        "explanations": explanations,
    }


def render_text_report(payload: Mapping[str, Any]) -> str:
    folder = payload["folder"]
    probe = payload["query_probe"]
    search = payload["search_execution"]
    explanations = payload["explanations"]

    lines = [
        f"Folder: {folder['folder_path']}",
        f"Asset ID: {folder['asset_id']} | media_type={folder['media_type']} | sampled_images={folder['sampled_image_count']}",
        f"Query source: {probe['source']} | label={probe['label_display_name']} ({probe['label_id']})",
        f"Filters: {json.dumps(probe['filters'], ensure_ascii=False)}",
        "Query text:",
        f"  {probe['query_text']}",
        f"Search mode: {search['mode']}",
        "Results:",
    ]

    results = search.get("results", [])
    if not isinstance(results, list) or not results:
        lines.append("  <empty>")
    else:
        for idx, item in enumerate(results, start=1):
            asset_id = item.get("asset_id")
            label_name = item.get("label_display_name") or item.get("resolved_label_display_name") or item.get("label_id")
            score = item.get("score")
            if score is None:
                score = item.get("_rerank_score", item.get("_hybrid_score"))
            lines.append(
                f"  {idx}. asset_id={asset_id} | label={label_name} | score={_fmt_score(score)}"
            )
            metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else item
            retrieval_channels = metadata.get("retrieval_channels", []) if isinstance(metadata, Mapping) else []
            if retrieval_channels:
                lines.append(f"     channels={','.join(str(channel) for channel in retrieval_channels)}")
            text = item.get("text") or item.get("decision_trace_text") or item.get("normalized_summary") or ""
            if text:
                lines.append(f"     text={_truncate(str(text), 160)}")

            explanation = explanations.get(str(asset_id), {})
            sample_memory = explanation.get("sample_memory") if isinstance(explanation, Mapping) else None
            observation = explanation.get("observation") if isinstance(explanation, Mapping) else None
            if isinstance(observation, Mapping):
                obs_bits = []
                if observation.get("has_person") is not None:
                    obs_bits.append(f"has_person={observation.get('has_person')}")
                if observation.get("body_parts_visible"):
                    obs_bits.append(f"body_parts={observation.get('body_parts_visible')}")
                if observation.get("celebrity_name_hint"):
                    obs_bits.append(f"celebrity={observation.get('celebrity_name_hint')}")
                if observation.get("scene_type") not in {None, "", "unknown"}:
                    obs_bits.append(f"scene={observation.get('scene_type')}")
                if obs_bits:
                    lines.append(f"     observation={' | '.join(obs_bits)}")
            if isinstance(sample_memory, Mapping) and sample_memory.get("decision_trace_text"):
                lines.append(
                    f"     reason={_truncate(_extract_reason(str(sample_memory.get('decision_trace_text', ''))), 160)}"
                )
    return "\n".join(lines)


def load_cache_payload(cache_files: Sequence[str]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for cache_file in cache_files:
        path = Path(cache_file)
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Skip unreadable cache file %s: %s", path, exc)
            continue
        if isinstance(payload, Mapping):
            for key, value in payload.items():
                merged[str(key)] = value
    return merged


def build_heuristic_reason(folder: FolderSummary) -> str:
    sampled = len(folder.sampled_images)
    if folder.media_type == "video":
        return (
            f"素材文件夹包含视频文件，当前抽样到 {sampled} 张代表帧，"
            "可先按视频语义与时序样本检索近邻。"
        )
    if sampled >= 8:
        return (
            f"素材文件夹包含 {sampled} 张代表图片，疑似为一组图文穿搭或静物素材，"
            "可先按整组图片风格检索相似样本。"
        )
    return (
        f"素材文件夹当前包含 {folder.file_count} 个文件，"
        "暂未命中缓存或线上分析结果，先按基础媒体属性检索近邻。"
    )


def heuristic_label_guess(folder: FolderSummary) -> tuple[str, str]:
    if folder.media_type == "video":
        return "performance_test", "性能测评"
    if len(folder.sampled_images) >= 8:
        return "outfit_core", "穿搭精选 (核心)-穿搭种草"
    return "other", "其他"


def collect_media_files(path: Path, max_frames: int = 12) -> tuple[list[Path], bool]:
    is_video_folder = bool(_sorted_globs(path, ["*.mp4", "*.mov", "*.m4v", "*.avi", "*.mkv"]))
    subdirs_priority = [
        "minimax_mcp_multimodal_frames",
        "gemini_frames",
        "minimax_frames",
        "minimax_mcp_frames",
        "frames",
    ]
    for subdir in subdirs_priority:
        subdir_path = path / subdir
        if subdir_path.exists():
            imgs = _sorted_globs(subdir_path, ["*.jpg", "*.jpeg", "*.png"])
            if imgs:
                return _sample_frames(imgs, max_frames=max_frames, is_video=is_video_folder), is_video_folder

    root_images = _sorted_globs(path, ["*.jpg", "*.jpeg", "*.png"])
    if root_images:
        return _sample_frames(root_images, max_frames=max_frames, is_video=is_video_folder), is_video_folder

    return [], is_video_folder


def _sample_frames(imgs: Sequence[Path], *, max_frames: int, is_video: bool) -> list[Path]:
    ordered = list(sorted(imgs))
    if not ordered:
        return []

    if is_video:
        target = min(max_frames, 20)
        if len(ordered) <= target:
            return ordered
        segment_size = max(1, len(ordered) // 3)
        front = ordered[:5]
        mid = ordered[segment_size : segment_size + 10]
        end = ordered[segment_size * 2 : segment_size * 2 + 5]
        return front + mid + end

    target = min(max_frames, 12)
    if len(ordered) <= target:
        return ordered
    segment_size = max(1, len(ordered) // 3)
    front = ordered[:3]
    mid = ordered[segment_size : segment_size + 6]
    end = ordered[segment_size * 2 : segment_size * 2 + 3]
    return front + mid + end


def analyze_folder_with_minimax(
    *,
    folder: FolderSummary,
    api_key: str,
    api_host: str,
) -> tuple[str, str]:
    from minimax_mcp_client import MiniMaxMCPClient

    sampled_images = folder.sampled_images
    if not sampled_images:
        raise RuntimeError("No images available for MiniMax analysis. Prepare extracted frames or root images first.")

    prompt = _build_minimax_prompt(folder.media_type == "video")
    frame_labels: list[str] = []
    frame_reasons: list[str] = []
    with MiniMaxMCPClient(api_key, api_host=api_host) as client:
        for idx, image_path in enumerate(sampled_images, start=1):
            logger.info("Analyze frame %s/%s: %s", idx, len(sampled_images), image_path.name)
            result = client.understand_image(str(image_path), prompt)
            if not result:
                continue
            label, reason = _parse_vlm_result(result)
            frame_labels.append(label)
            frame_reasons.append(f"[frame={idx}] {reason}")
            if idx < len(sampled_images):
                time.sleep(1.0)

    if not frame_labels:
        raise RuntimeError("MiniMax analysis returned no usable frames.")
    final_label = _combine_frame_labels(frame_labels)
    final_reason = next(
        (reason for label, reason in zip(frame_labels, frame_reasons) if label == final_label),
        frame_reasons[0],
    )
    return final_label, f"[多帧综合: {' | '.join(frame_labels)}]\n{final_reason}"


def _build_minimax_prompt(is_video_folder: bool) -> str:
    media_type_hint = (
        "【重要】这是视频素材文件夹（有.mp4文件），可能是性能测评。"
        if is_video_folder
        else "【重要】这是图片素材文件夹（无视频），不可能是性能测评。"
    )
    return (
        f"{media_type_hint}\n\n"
        "你是一位专业的时尚与运动产品分析师。请分析以下图片，将其归类为以下精准标签之一："
        "性能测评、明星穿搭、穿搭精选 (核心)-穿搭种草、穿搭精选 (次要)-穿搭种草、"
        "单品展示 (剔除出穿搭)-上脚、创意静物、静物展示、其他。\n"
        "输出 JSON，包含 label 和 reason 两个字段。"
    )


def _parse_vlm_result(result: str) -> tuple[str, str]:
    try:
        start = result.find("{")
        end = result.rfind("}") + 1
        if start >= 0 and end > start:
            payload = json.loads(result[start:end])
            return str(payload.get("label", "其他") or "其他"), str(payload.get("reason", "") or "")
    except Exception:
        pass

    for keyword, label in [
        ("性能测评", "性能测评"),
        ("性能测试", "性能测评"),
        ("明星穿搭", "明星穿搭"),
        ("穿搭精选 (核心)", "穿搭精选 (核心)-穿搭种草"),
        ("穿搭精选 (次要)", "穿搭精选 (次要)-穿搭种草"),
        ("单品展示", "单品展示 (剔除出穿搭)-上脚"),
        ("创意静物", "创意静物"),
        ("静物展示", "静物展示"),
    ]:
        if keyword in result:
            return label, result[:500]
    return "其他", result[:500]


def _combine_frame_labels(frame_labels: Sequence[str]) -> str:
    counts: dict[str, int] = {}
    for item in frame_labels:
        counts[item] = counts.get(item, 0) + 1
    if counts.get("性能测评", 0) >= 3:
        return "性能测评"
    if "明星穿搭" in counts:
        return "明星穿搭"
    for label in PROMPT_LABEL_PRIORITY:
        if label == "性能测评":
            continue
        if label in counts:
            return label
    return "其他"


def _resolved_label_id(row: Mapping[str, Any]) -> Optional[str]:
    for key in ("semantic_label_id", "label_id", "final_label_id"):
        value = row.get(key)
        if value:
            return str(value)
    return None


def _resolved_label_display_name(row: Mapping[str, Any]) -> Optional[str]:
    for key in ("semantic_label_display_name", "label_display_name", "final_label_display_name"):
        value = row.get(key)
        if value:
            return str(value)
    return None


def _sorted_globs(root: Path, patterns: Sequence[str]) -> list[Path]:
    files: list[Path] = []
    for pattern in patterns:
        files.extend(Path(path) for path in glob.glob(str(root / pattern)))
    return sorted(dict.fromkeys(files))


def _extract_reason(trace_text: str) -> str:
    if "reason=" not in trace_text:
        return trace_text
    return trace_text.split("reason=", 1)[1].strip()


def _truncate(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def _fmt_score(value: object) -> str:
    try:
        if isinstance(value, (int, float, str)):
            return f"{float(value):.4f}"
        return "n/a"
    except (TypeError, ValueError):
        return "n/a"


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def _load_dotenv_if_present() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except ImportError:
        return
    load_dotenv()


if __name__ == "__main__":
    raise SystemExit(main())
