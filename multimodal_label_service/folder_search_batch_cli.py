"""Batch CLI for searching similar samples from a parent folder of materials."""

from __future__ import annotations

import argparse
import json
import logging
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from xml.sax.saxutils import escape as xml_escape

from multimodal_label_knowledge.rule_assets import load_knowledge_bundle
from multimodal_label_store import LanceStore, StoreConfig, StorePaths

from .folder_search_cli import (
    DEFAULT_CACHE_FILES,
    _configure_logging,
    _extract_reason,
    _fmt_score,
    _load_dotenv_if_present,
    _truncate,
    load_cache_payload,
    render_text_report,
    run_folder_search,
)

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parent_dir", help="Parent directory containing material folders")
    parser.add_argument("--output-dir")
    parser.add_argument("--folder-ids-file")
    parser.add_argument("--service-url", default="http://127.0.0.1:8000")
    parser.add_argument("--root", default="data/lance")
    parser.add_argument("--snapshot-root", default="data/snapshots")
    parser.add_argument("--embedding-dim", type=int, default=1536)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--lock-label", action="store_true")
    parser.add_argument("--prefer-live-analysis", action="store_true")
    parser.add_argument("--use-minimax", action="store_true")
    parser.add_argument("--minimax-api-key")
    parser.add_argument("--minimax-api-host", default="https://api.minimaxi.com")
    parser.add_argument("--cache-files", nargs="*", default=DEFAULT_CACHE_FILES)
    parser.add_argument("--explain-top-n", type=int, default=3)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _configure_logging(args.verbose)
    _load_dotenv_if_present()

    started_at = utcnow_iso()
    config = StoreConfig(
        embedding_dim=args.embedding_dim,
        paths=StorePaths(root=Path(args.root), snapshot_root=Path(args.snapshot_root)),
    )
    store = LanceStore(config)
    store.ensure_all_tables()
    bundle = load_knowledge_bundle()
    cache_payload = load_cache_payload(args.cache_files)

    parent_dir = Path(args.parent_dir)
    folders = discover_folders(
        parent_dir=parent_dir,
        folder_ids_file=Path(args.folder_ids_file) if args.folder_ids_file else None,
        limit=args.limit or None,
    )
    if not folders:
        raise RuntimeError(f"No material folders found under {parent_dir}")

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, folder_path in enumerate(folders, start=1):
        logger.info("Process folder %s/%s: %s", index, len(folders), folder_path.name)
        try:
            payload = run_folder_search(
                folder_path=folder_path,
                service_url=args.service_url,
                config=config,
                store=store,
                bundle=bundle,
                top_k=args.top_k,
                explain_top_n=args.explain_top_n,
                lock_label=args.lock_label,
                prefer_live_analysis=args.prefer_live_analysis,
                use_minimax=args.use_minimax,
                minimax_api_key=args.minimax_api_key or "",
                minimax_api_host=args.minimax_api_host,
                cache_files=args.cache_files,
                cache_payload=cache_payload,
            )
            results.append(payload)
        except Exception as exc:
            logger.exception("Folder search failed: %s", folder_path)
            errors.append(
                {
                    "folder_path": str(folder_path),
                    "asset_id": folder_path.name,
                    "error": str(exc),
                }
            )

    completed_at = utcnow_iso()
    output_dir = Path(args.output_dir) if args.output_dir else default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    batch_payload = {
        "meta": {
            "parent_dir": str(parent_dir),
            "started_at": started_at,
            "completed_at": completed_at,
            "top_k": args.top_k,
            "folder_count": len(folders),
            "success_count": len(results),
            "error_count": len(errors),
            "service_url": args.service_url,
        },
        "results": results,
        "errors": errors,
    }

    json_path = output_dir / "batch_search_results.json"
    markdown_path = output_dir / "batch_search_results.md"
    excel_path = output_dir / "batch_search_results.xlsx"

    json_path.write_text(
        json.dumps(batch_payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    markdown_path.write_text(render_batch_markdown(batch_payload), encoding="utf-8")
    write_batch_excel(excel_path, batch_payload)

    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "json": str(json_path),
                "markdown": str(markdown_path),
                "excel": str(excel_path),
                "success_count": len(results),
                "error_count": len(errors),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def discover_folders(
    *,
    parent_dir: Path,
    folder_ids_file: Path | None,
    limit: int | None,
) -> list[Path]:
    if not parent_dir.exists():
        raise FileNotFoundError(f"Parent directory not found: {parent_dir}")
    if not parent_dir.is_dir():
        raise NotADirectoryError(f"Parent path is not a directory: {parent_dir}")

    if folder_ids_file:
        folder_ids = [
            line.strip()
            for line in folder_ids_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        folders = [parent_dir / folder_id for folder_id in folder_ids if (parent_dir / folder_id).is_dir()]
    else:
        folders = sorted(child for child in parent_dir.iterdir() if child.is_dir())

    if limit and limit > 0:
        folders = folders[:limit]
    return folders


def default_output_dir() -> Path:
    return Path("data/batch_search") / datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def render_batch_markdown(payload: Mapping[str, Any]) -> str:
    meta = payload.get("meta", {})
    results = payload.get("results", [])
    errors = payload.get("errors", [])

    lines = [
        "# Batch Folder Search Report",
        "",
        f"- parent_dir: `{meta.get('parent_dir', '')}`",
        f"- started_at: `{meta.get('started_at', '')}`",
        f"- completed_at: `{meta.get('completed_at', '')}`",
        f"- folder_count: `{meta.get('folder_count', 0)}`",
        f"- success_count: `{meta.get('success_count', 0)}`",
        f"- error_count: `{meta.get('error_count', 0)}`",
        "",
        "## Summary",
        "",
        "| asset_id | media_type | query_source | label | top1_asset | top1_label | top1_score | search_mode |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for item in results if isinstance(results, list) else []:
        folder = item.get("folder", {})
        probe = item.get("query_probe", {})
        search = item.get("search_execution", {})
        hits = search.get("results", [])
        top1 = hits[0] if isinstance(hits, list) and hits else {}
        top1_label = top1.get("label_display_name") or top1.get("resolved_label_display_name") or top1.get("label_id") or ""
        top1_score = top1.get("score", top1.get("_rerank_score", top1.get("_hybrid_score")))
        lines.append(
            "| {asset_id} | {media_type} | {query_source} | {label} | {top1_asset} | {top1_label} | {top1_score} | {search_mode} |".format(
                asset_id=folder.get("asset_id", ""),
                media_type=folder.get("media_type", ""),
                query_source=probe.get("source", ""),
                label=probe.get("label_display_name", ""),
                top1_asset=top1.get("asset_id", ""),
                top1_label=top1_label,
                top1_score=_fmt_score(top1_score),
                search_mode=search.get("mode", ""),
            )
        )

    for item in results if isinstance(results, list) else []:
        lines.extend(["", f"## {item.get('folder', {}).get('asset_id', '')}", ""])
        lines.append("```text")
        lines.append(render_text_report(item))
        lines.append("```")

    if isinstance(errors, list) and errors:
        lines.extend(["", "## Errors", ""])
        for error in errors:
            lines.append(
                f"- `{error.get('asset_id', '')}` `{error.get('folder_path', '')}`: {error.get('error', '')}"
            )
    return "\n".join(lines) + "\n"


def write_batch_excel(path: Path, payload: Mapping[str, Any]) -> None:
    summary_rows = build_summary_rows(payload)
    hit_rows = build_hit_rows(payload)
    error_rows = build_error_rows(payload)
    sheets = [
        ("summary", summary_rows),
        ("hits", hit_rows),
        ("errors", error_rows),
    ]
    write_xlsx(path, sheets)


def build_summary_rows(payload: Mapping[str, Any]) -> list[list[object]]:
    rows: list[list[object]] = [[
        "asset_id",
        "folder_path",
        "media_type",
        "image_count",
        "video_count",
        "sampled_image_count",
        "query_source",
        "query_label_id",
        "query_label_display_name",
        "query_text",
        "filters_json",
        "search_mode",
        "top1_asset_id",
        "top1_label",
        "top1_score",
        "top1_reason",
    ]]
    for item in payload.get("results", []) if isinstance(payload.get("results", []), list) else []:
        folder = item.get("folder", {})
        probe = item.get("query_probe", {})
        search = item.get("search_execution", {})
        explanations = item.get("explanations", {})
        hits = search.get("results", [])
        top1 = hits[0] if isinstance(hits, list) and hits else {}
        top1_asset_id = str(top1.get("asset_id", "") or "")
        explanation = explanations.get(top1_asset_id, {}) if isinstance(explanations, Mapping) else {}
        sample_memory = explanation.get("sample_memory") if isinstance(explanation, Mapping) else None
        top1_reason = ""
        if isinstance(sample_memory, Mapping):
            top1_reason = _truncate(_extract_reason(str(sample_memory.get("decision_trace_text", "") or "")), 500)
        rows.append([
            folder.get("asset_id", ""),
            folder.get("folder_path", ""),
            folder.get("media_type", ""),
            folder.get("image_count", 0),
            folder.get("video_count", 0),
            folder.get("sampled_image_count", 0),
            probe.get("source", ""),
            probe.get("label_id", ""),
            probe.get("label_display_name", ""),
            probe.get("query_text", ""),
            json.dumps(probe.get("filters", {}), ensure_ascii=False, default=str),
            search.get("mode", ""),
            top1_asset_id,
            top1.get("label_display_name") or top1.get("resolved_label_display_name") or top1.get("label_id") or "",
            _fmt_score(top1.get("score", top1.get("_rerank_score", top1.get("_hybrid_score")))),
            top1_reason,
        ])
    return rows


def build_hit_rows(payload: Mapping[str, Any]) -> list[list[object]]:
    rows: list[list[object]] = [[
        "asset_id",
        "query_source",
        "rank",
        "hit_asset_id",
        "hit_label",
        "score",
        "retrieval_channels",
        "text_preview",
        "observation_summary",
        "reason_preview",
    ]]
    for item in payload.get("results", []) if isinstance(payload.get("results", []), list) else []:
        folder = item.get("folder", {})
        probe = item.get("query_probe", {})
        search = item.get("search_execution", {})
        explanations = item.get("explanations", {})
        hits = search.get("results", [])
        if not isinstance(hits, list):
            continue
        for index, hit in enumerate(hits, start=1):
            hit_asset_id = str(hit.get("asset_id", "") or "")
            metadata = hit.get("metadata") if isinstance(hit.get("metadata"), Mapping) else hit
            channels = metadata.get("retrieval_channels", []) if isinstance(metadata, Mapping) else []
            explanation = explanations.get(hit_asset_id, {}) if isinstance(explanations, Mapping) else {}
            observation = explanation.get("observation") if isinstance(explanation, Mapping) else None
            sample_memory = explanation.get("sample_memory") if isinstance(explanation, Mapping) else None
            observation_summary = ""
            if isinstance(observation, Mapping):
                observation_summary = json.dumps(
                    {
                        "has_person": observation.get("has_person"),
                        "body_parts_visible": observation.get("body_parts_visible"),
                        "celebrity_name_hint": observation.get("celebrity_name_hint"),
                        "scene_type": observation.get("scene_type"),
                    },
                    ensure_ascii=False,
                    default=str,
                )
            reason_preview = ""
            if isinstance(sample_memory, Mapping):
                reason_preview = _truncate(_extract_reason(str(sample_memory.get("decision_trace_text", "") or "")), 400)
            rows.append([
                folder.get("asset_id", ""),
                probe.get("source", ""),
                index,
                hit_asset_id,
                hit.get("label_display_name") or hit.get("resolved_label_display_name") or hit.get("label_id") or "",
                _fmt_score(hit.get("score", hit.get("_rerank_score", hit.get("_hybrid_score")))),
                ",".join(str(channel) for channel in channels),
                _truncate(str(hit.get("text") or hit.get("decision_trace_text") or hit.get("normalized_summary") or ""), 300),
                observation_summary,
                reason_preview,
            ])
    return rows


def build_error_rows(payload: Mapping[str, Any]) -> list[list[object]]:
    rows: list[list[object]] = [["asset_id", "folder_path", "error"]]
    for item in payload.get("errors", []) if isinstance(payload.get("errors", []), list) else []:
        rows.append([
            item.get("asset_id", ""),
            item.get("folder_path", ""),
            item.get("error", ""),
        ])
    return rows


def write_xlsx(path: Path, sheets: Sequence[tuple[str, Sequence[Sequence[object]]]]) -> None:
    normalized_sheets = [
        (sanitize_sheet_name(name, index), [list(row) for row in rows])
        for index, (name, rows) in enumerate(sheets, start=1)
    ]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", build_content_types(len(normalized_sheets)))
        zf.writestr("_rels/.rels", build_root_rels())
        zf.writestr("xl/workbook.xml", build_workbook_xml([name for name, _ in normalized_sheets]))
        zf.writestr("xl/_rels/workbook.xml.rels", build_workbook_rels(len(normalized_sheets)))
        zf.writestr("xl/styles.xml", build_styles_xml())
        zf.writestr("docProps/core.xml", build_core_xml())
        zf.writestr("docProps/app.xml", build_app_xml([name for name, _ in normalized_sheets]))
        for index, (_, rows) in enumerate(normalized_sheets, start=1):
            zf.writestr(f"xl/worksheets/sheet{index}.xml", build_sheet_xml(rows))


def sanitize_sheet_name(name: str, index: int) -> str:
    cleaned = name.strip() or f"sheet{index}"
    for char in "\\/*?:[]":
        cleaned = cleaned.replace(char, "_")
    return cleaned[:31]


def build_content_types(sheet_count: int) -> str:
    overrides = [
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>',
    ]
    for index in range(1, sheet_count + 1):
        overrides.append(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        + "".join(overrides)
        + "</Types>"
    )


def build_root_rels() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
        "</Relationships>"
    )


def build_workbook_xml(sheet_names: Sequence[str]) -> str:
    sheets_xml = "".join(
        f'<sheet name="{xml_escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(sheet_names, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheets_xml}</sheets>"
        "</workbook>"
    )


def build_workbook_rels(sheet_count: int) -> str:
    relationships = []
    for index in range(1, sheet_count + 1):
        relationships.append(
            f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
        )
    relationships.append(
        f'<Relationship Id="rId{sheet_count + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(relationships)
        + "</Relationships>"
    )


def build_styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )


def build_core_xml() -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<dc:creator>Codex</dc:creator>'
        '<cp:lastModifiedBy>Codex</cp:lastModifiedBy>'
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>'
        "</cp:coreProperties>"
    )


def build_app_xml(sheet_names: Sequence[str]) -> str:
    titles = "".join(f"<vt:lpstr>{xml_escape(name)}</vt:lpstr>" for name in sheet_names)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        '<Application>Codex</Application>'
        f'<TitlesOfParts><vt:vector size="{len(sheet_names)}" baseType="lpstr">{titles}</vt:vector></TitlesOfParts>'
        "</Properties>"
    )


def build_sheet_xml(rows: Sequence[Sequence[object]]) -> str:
    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row, start=1):
            ref = f"{column_letter(column_index)}{row_index}"
            cells.append(build_cell_xml(ref, value))
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData>'
        "</worksheet>"
    )


def build_cell_xml(ref: str, value: object) -> str:
    if value is None:
        return f'<c r="{ref}"/>'
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"><v>{1 if value else 0}</v></c>'
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"><v>{value}</v></c>'
    text = xml_escape(str(value))
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def column_letter(index: int) -> str:
    result = ""
    current = index
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        result = chr(65 + remainder) + result
    return result


def utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    raise SystemExit(main())
