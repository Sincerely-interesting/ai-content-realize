"""Secondary bad-case filter for batch folder-search results."""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from .folder_search_batch_cli import (
    build_error_rows,
    default_output_dir,
    utcnow_iso,
    write_xlsx,
)
from .folder_search_cli import _extract_reason, _fmt_score, _load_dotenv_if_present, _truncate

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch_result_json", help="Path to batch_search_results.json")
    parser.add_argument("--output-dir")
    parser.add_argument("--score-threshold", type=float, default=0.68)
    parser.add_argument("--same-label-gap-threshold", type=float, default=0.05)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    _load_dotenv_if_present()

    payload = json.loads(Path(args.batch_result_json).read_text(encoding="utf-8"))
    reviews = build_batch_bad_case_reviews(
        payload=payload,
        score_threshold=args.score_threshold,
        same_label_gap_threshold=args.same_label_gap_threshold,
    )

    output_dir = Path(args.output_dir) if args.output_dir else default_filter_output_dir(Path(args.batch_result_json))
    output_dir.mkdir(parents=True, exist_ok=True)

    result_payload = {
        "meta": {
            "source_batch_result": str(Path(args.batch_result_json)),
            "generated_at": utcnow_iso(),
            "score_threshold": args.score_threshold,
            "same_label_gap_threshold": args.same_label_gap_threshold,
            "review_count": len(reviews),
            "signal_summary": summarize_signals(reviews),
        },
        "reviews": reviews,
        "source_meta": payload.get("meta", {}),
        "errors": payload.get("errors", []),
    }

    json_path = output_dir / "batch_bad_case_reviews.json"
    markdown_path = output_dir / "batch_bad_case_reviews.md"
    excel_path = output_dir / "batch_bad_case_reviews.xlsx"

    json_path.write_text(
        json.dumps(result_payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    markdown_path.write_text(render_bad_case_markdown(result_payload), encoding="utf-8")
    write_bad_case_excel(excel_path, result_payload)

    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "json": str(json_path),
                "markdown": str(markdown_path),
                "excel": str(excel_path),
                "review_count": len(reviews),
                "signal_summary": summarize_signals(reviews),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_batch_bad_case_reviews(
    *,
    payload: Mapping[str, Any],
    score_threshold: float,
    same_label_gap_threshold: float,
) -> list[dict[str, Any]]:
    results = payload.get("results", [])
    if not isinstance(results, list):
        return []

    reviews: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, Mapping):
            continue
        review = build_one_review(
            item=item,
            score_threshold=score_threshold,
            same_label_gap_threshold=same_label_gap_threshold,
        )
        if review is not None:
            reviews.append(review)
    return reviews


def build_one_review(
    *,
    item: Mapping[str, Any],
    score_threshold: float,
    same_label_gap_threshold: float,
) -> dict[str, Any] | None:
    folder = item.get("folder", {})
    probe = item.get("query_probe", {})
    search = item.get("search_execution", {})
    explanations = item.get("explanations", {})

    if not isinstance(folder, Mapping) or not isinstance(probe, Mapping) or not isinstance(search, Mapping):
        return None

    asset_id = str(folder.get("asset_id", "") or "")
    query_source = str(probe.get("source", "") or "")
    query_label_id = str(probe.get("label_id", "") or "")
    query_label_display_name = str(probe.get("label_display_name", "") or "")
    query_text = str(probe.get("query_text", "") or "")
    hits = search.get("results", [])
    if not isinstance(hits, list):
        hits = []

    top1 = hits[0] if hits else {}
    top1_asset_id = str(top1.get("asset_id", "") or "")
    top1_label_id = str(
        top1.get("resolved_label_id")
        or top1.get("semantic_label_id")
        or top1.get("label_id")
        or ""
    )
    top1_label_display_name = str(
        top1.get("resolved_label_display_name")
        or top1.get("semantic_label_display_name")
        or top1.get("label_display_name")
        or top1_label_id
    )
    top1_score = as_float(top1.get("score", top1.get("_rerank_score", top1.get("_hybrid_score"))))
    self_rank = rank_of_asset(hits, asset_id)
    corpus_backed_self = query_source in {"lance_sample_memory", "lance_asset"}

    triggered_signals: list[str] = []
    if corpus_backed_self and top1_asset_id and top1_asset_id != asset_id:
        triggered_signals.append("top1_not_self")
    if top1_score is not None and top1_score < score_threshold:
        triggered_signals.append("top1_score_low")
    if query_source == "heuristic_probe":
        triggered_signals.append("heuristic_probe")

    same_label_conflict = detect_same_label_conflict(
        asset_id=asset_id,
        hits=hits,
        query_label_id=query_label_id,
        same_label_gap_threshold=same_label_gap_threshold,
    )
    if same_label_conflict:
        triggered_signals.append("same_label_conflict")

    if not triggered_signals:
        return None

    primary_bad_case_type = classify_primary_bad_case_type(triggered_signals)
    suggested_action = suggested_action_for_signals(triggered_signals)
    top_same_label_hits = collect_top_same_label_hits(hits, query_label_id)
    explanation = explanations.get(top1_asset_id, {}) if isinstance(explanations, Mapping) else {}
    sample_memory = explanation.get("sample_memory") if isinstance(explanation, Mapping) else None
    top1_reason = ""
    if isinstance(sample_memory, Mapping):
        top1_reason = _truncate(_extract_reason(str(sample_memory.get("decision_trace_text", "") or "")), 400)

    review = {
        "review_id": asset_id,
        "asset_id": asset_id,
        "folder_path": folder.get("folder_path", ""),
        "media_type": folder.get("media_type", ""),
        "query_source": query_source,
        "query_label_id": query_label_id or None,
        "query_label_display_name": query_label_display_name or None,
        "query_text": query_text,
        "filters": probe.get("filters", {}),
        "search_mode": search.get("mode", ""),
        "top1_asset_id": top1_asset_id or None,
        "top1_label_id": top1_label_id or None,
        "top1_label_display_name": top1_label_display_name or None,
        "top1_score": top1_score,
        "self_rank": self_rank,
        "primary_bad_case_type": primary_bad_case_type,
        "triggered_signals": triggered_signals,
        "same_label_candidate_count": len(top_same_label_hits),
        "same_label_gap": compute_same_label_gap(top_same_label_hits),
        "top_same_label_asset_ids": [str(hit.get("asset_id", "") or "") for hit in top_same_label_hits[:5]],
        "suggested_action": suggested_action,
        "top1_reason_preview": top1_reason,
        "report_markdown": render_review_markdown(
            asset_id=asset_id,
            folder_path=str(folder.get("folder_path", "") or ""),
            primary_bad_case_type=primary_bad_case_type,
            triggered_signals=triggered_signals,
            query_source=query_source,
            query_label_display_name=query_label_display_name,
            query_text=query_text,
            top1_asset_id=top1_asset_id,
            top1_label_display_name=top1_label_display_name,
            top1_score=top1_score,
            self_rank=self_rank,
            suggested_action=suggested_action,
            top_same_label_hits=top_same_label_hits,
        ),
        "topk_hits": simplify_hits(hits),
    }
    return review


def detect_same_label_conflict(
    *,
    asset_id: str,
    hits: Sequence[Mapping[str, Any]],
    query_label_id: str,
    same_label_gap_threshold: float,
) -> bool:
    if not query_label_id:
        return False
    same_label_hits = collect_top_same_label_hits(hits, query_label_id)
    if len(same_label_hits) < 2:
        return False

    if rank_of_asset(same_label_hits, asset_id) not in {None, 1}:
        return True
    gap = compute_same_label_gap(same_label_hits)
    return gap is not None and gap <= same_label_gap_threshold


def collect_top_same_label_hits(
    hits: Sequence[Mapping[str, Any]],
    query_label_id: str,
) -> list[Mapping[str, Any]]:
    same_label_hits: list[Mapping[str, Any]] = []
    for hit in hits:
        label_id = str(
            hit.get("resolved_label_id")
            or hit.get("semantic_label_id")
            or hit.get("label_id")
            or ""
        )
        if label_id == query_label_id:
            same_label_hits.append(hit)
    return same_label_hits


def compute_same_label_gap(hits: Sequence[Mapping[str, Any]]) -> float | None:
    if len(hits) < 2:
        return None
    first = as_float(hits[0].get("score", hits[0].get("_rerank_score", hits[0].get("_hybrid_score"))))
    second = as_float(hits[1].get("score", hits[1].get("_rerank_score", hits[1].get("_hybrid_score"))))
    if first is None or second is None:
        return None
    return first - second


def simplify_hits(hits: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    simplified: list[dict[str, Any]] = []
    for index, hit in enumerate(hits, start=1):
        simplified.append(
            {
                "rank": index,
                "asset_id": hit.get("asset_id"),
                "label_id": hit.get("resolved_label_id") or hit.get("semantic_label_id") or hit.get("label_id"),
                "label_display_name": hit.get("resolved_label_display_name")
                or hit.get("semantic_label_display_name")
                or hit.get("label_display_name"),
                "score": as_float(hit.get("score", hit.get("_rerank_score", hit.get("_hybrid_score")))),
            }
        )
    return simplified


def classify_primary_bad_case_type(triggered_signals: Sequence[str]) -> str:
    priority = [
        "heuristic_probe",
        "top1_not_self",
        "same_label_conflict",
        "top1_score_low",
    ]
    for signal in priority:
        if signal in triggered_signals:
            return signal
    return triggered_signals[0] if triggered_signals else "unknown"


def suggested_action_for_signals(triggered_signals: Sequence[str]) -> str:
    actions: list[str] = []
    if "heuristic_probe" in triggered_signals:
        actions.append("优先补真实素材分析结果，避免继续依赖 heuristic query。")
    if "top1_not_self" in triggered_signals:
        actions.append("补更强区分度的 query 模板或新增该样本的 gold sample。")
    if "same_label_conflict" in triggered_signals:
        actions.append("针对同标签近邻补实体词、场景词、局部结构词，压缩同标签歧义。")
    if "top1_score_low" in triggered_signals:
        actions.append("人工回看该样本，并优先做 bad case 定向增广或人工确认。")
    return " ".join(actions)


def render_review_markdown(
    *,
    asset_id: str,
    folder_path: str,
    primary_bad_case_type: str,
    triggered_signals: Sequence[str],
    query_source: str,
    query_label_display_name: str,
    query_text: str,
    top1_asset_id: str,
    top1_label_display_name: str,
    top1_score: float | None,
    self_rank: int | None,
    suggested_action: str,
    top_same_label_hits: Sequence[Mapping[str, Any]],
) -> str:
    payload = {
        "asset_id": asset_id,
        "folder_path": folder_path,
        "query_source": query_source,
        "query_label_display_name": query_label_display_name,
        "query_text": query_text,
        "top1_asset_id": top1_asset_id,
        "top1_label_display_name": top1_label_display_name,
        "top1_score": top1_score,
        "self_rank": self_rank,
        "top_same_label_asset_ids": [str(hit.get("asset_id", "") or "") for hit in top_same_label_hits[:5]],
    }
    return "\n".join(
        [
            f"- primary_bad_case_type: `{primary_bad_case_type}`",
            f"- triggered_signals: `{', '.join(triggered_signals)}`",
            f"- suggested_action: {suggested_action}",
            "- payload:",
            "```json",
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            "```",
        ]
    )


def render_bad_case_markdown(payload: Mapping[str, Any]) -> str:
    meta = payload.get("meta", {})
    reviews = payload.get("reviews", [])
    lines = [
        "# Batch Bad Case Review Report",
        "",
        f"- source_batch_result: `{meta.get('source_batch_result', '')}`",
        f"- generated_at: `{meta.get('generated_at', '')}`",
        f"- score_threshold: `{meta.get('score_threshold', '')}`",
        f"- same_label_gap_threshold: `{meta.get('same_label_gap_threshold', '')}`",
        f"- review_count: `{meta.get('review_count', 0)}`",
        "",
        "## Signal Summary",
        "",
    ]
    signal_summary = meta.get("signal_summary", {})
    if isinstance(signal_summary, Mapping):
        for key, value in signal_summary.items():
            lines.append(f"- `{key}`: {value}")

    if not isinstance(reviews, list) or not reviews:
        lines.extend(["", "No bad cases detected.", ""])
        return "\n".join(lines)

    lines.extend([
        "",
        "## Summary",
        "",
        "| asset_id | primary_bad_case_type | triggered_signals | query_source | query_label | top1_asset | top1_label | top1_score | self_rank |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for review in reviews:
        lines.append(
            "| {asset_id} | {primary} | {signals} | {query_source} | {query_label} | {top1_asset} | {top1_label} | {top1_score} | {self_rank} |".format(
                asset_id=review.get("asset_id", ""),
                primary=review.get("primary_bad_case_type", ""),
                signals=",".join(str(item) for item in review.get("triggered_signals", [])),
                query_source=review.get("query_source", ""),
                query_label=review.get("query_label_display_name", ""),
                top1_asset=review.get("top1_asset_id", ""),
                top1_label=review.get("top1_label_display_name", ""),
                top1_score=_fmt_score(review.get("top1_score")),
                self_rank=review.get("self_rank", ""),
            )
        )

    for review in reviews:
        lines.extend(["", f"## {review.get('asset_id', '')}", "", str(review.get("report_markdown", "")), ""])
    return "\n".join(lines) + "\n"


def summarize_signals(reviews: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for review in reviews:
        for signal in review.get("triggered_signals", []) if isinstance(review.get("triggered_signals", []), list) else []:
            counter[str(signal)] += 1
    return dict(sorted(counter.items()))


def write_bad_case_excel(path: Path, payload: Mapping[str, Any]) -> None:
    sheets = [
        ("reviews", build_review_rows(payload)),
        ("summary", build_summary_rows(payload)),
        ("errors", build_error_rows(payload)),
    ]
    write_xlsx(path, sheets)


def build_review_rows(payload: Mapping[str, Any]) -> list[list[object]]:
    rows: list[list[object]] = [[
        "asset_id",
        "folder_path",
        "primary_bad_case_type",
        "triggered_signals",
        "query_source",
        "query_label_id",
        "query_label_display_name",
        "query_text",
        "top1_asset_id",
        "top1_label_display_name",
        "top1_score",
        "self_rank",
        "same_label_candidate_count",
        "same_label_gap",
        "suggested_action",
        "top1_reason_preview",
    ]]
    reviews = payload.get("reviews", [])
    if not isinstance(reviews, list):
        return rows
    for review in reviews:
        rows.append([
            review.get("asset_id", ""),
            review.get("folder_path", ""),
            review.get("primary_bad_case_type", ""),
            ",".join(str(item) for item in review.get("triggered_signals", [])),
            review.get("query_source", ""),
            review.get("query_label_id", ""),
            review.get("query_label_display_name", ""),
            review.get("query_text", ""),
            review.get("top1_asset_id", ""),
            review.get("top1_label_display_name", ""),
            _fmt_score(review.get("top1_score")),
            review.get("self_rank", ""),
            review.get("same_label_candidate_count", 0),
            review.get("same_label_gap", ""),
            review.get("suggested_action", ""),
            review.get("top1_reason_preview", ""),
        ])
    return rows


def build_summary_rows(payload: Mapping[str, Any]) -> list[list[object]]:
    rows: list[list[object]] = [["metric", "value"]]
    meta = payload.get("meta", {})
    if isinstance(meta, Mapping):
        rows.append(["source_batch_result", meta.get("source_batch_result", "")])
        rows.append(["generated_at", meta.get("generated_at", "")])
        rows.append(["score_threshold", meta.get("score_threshold", "")])
        rows.append(["same_label_gap_threshold", meta.get("same_label_gap_threshold", "")])
        rows.append(["review_count", meta.get("review_count", 0)])
        signal_summary = meta.get("signal_summary", {})
        if isinstance(signal_summary, Mapping):
            for key, value in signal_summary.items():
                rows.append([f"signal:{key}", value])
    return rows


def rank_of_asset(hits: Sequence[Mapping[str, Any]], asset_id: str) -> int | None:
    for index, hit in enumerate(hits, start=1):
        if str(hit.get("asset_id", "") or "") == asset_id:
            return index
    return None


def as_float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def default_filter_output_dir(batch_result_json: Path) -> Path:
    batch_stem = batch_result_json.parent.name or "batch_result"
    return Path("data/batch_bad_case_reviews") / batch_stem


if __name__ == "__main__":
    raise SystemExit(main())
