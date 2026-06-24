"""Unified production CLI for ai-content-realize."""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-content-realize",
        description="Unified entrypoint for material download, labeling, archiving, and cache sync.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    download = subparsers.add_parser("download", help="Download materials from local Excel files.")
    download.add_argument("--sample", type=int, default=0, help="Number of materials to download (0 = all)")
    download.add_argument("--all", action="store_true", help="Download all discovered materials")
    download.add_argument("--output", default="downloaded_materials", help="Output directory")
    download.add_argument("--workers", type=int, default=5, help="Concurrent download workers")
    download.set_defaults(handler=handle_download)

    label = subparsers.add_parser("label", help="Run Gemini-based material labeling.")
    label.add_argument("--materials-dir", default="downloaded_materials", help="Directory containing material folders")
    label.add_argument("--output-file", default="gemini_labeled_results.xlsx", help="Excel output file")
    label.add_argument("--delay", type=float, default=1.0, help="Delay between API calls")
    label.add_argument("--batch-size", type=int, default=5, help="Materials processed per batch")
    label.add_argument("--batch-delay", type=float, default=20.0, help="Delay between batches")
    label.set_defaults(handler=handle_label)

    archive = subparsers.add_parser("archive", help="Generate archive reports with the multi-provider archiver.")
    archive.add_argument(
        "--provider",
        choices=["custom_minmax", "minmax", "minmax_mcp", "kimi", "kimi_coding", "paddle", "minicpm"],
        default="custom_minmax",
        help="Vision provider to use",
    )
    archive.add_argument(
        "--media-type",
        choices=["image", "video", "all"],
        default="image",
        help="Which material type to process",
    )
    archive.add_argument("--sample", type=int, default=1000, help="Number of folders to process")
    archive.add_argument("--concurrency", type=int, default=1, help="Concurrent API calls")
    archive.add_argument("--test", action="store_true", help="Process only a small test sample")
    archive.set_defaults(handler=handle_archive)

    sync_cache = subparsers.add_parser("sync-cache", help="Monitor a cache file and sync exported Excel to SMB.")
    sync_cache.add_argument("--cache-file", default="labeling_200_cache.json", help="Cache JSON file path")
    sync_cache.add_argument("--smb-path", default=r"\\192.168.2.242\大数据中心", help="SMB share path")
    sync_cache.add_argument(
        "--smb-filename",
        default="minimax_mcp_multimodal_results_latest.xlsx",
        help="Target filename on the SMB share",
    )
    sync_cache.add_argument("--local-excel-dir", default="excel_exports", help="Local Excel export directory")
    sync_cache.add_argument("--poll-interval", type=int, default=60, help="Polling interval in seconds")
    sync_cache.add_argument("--log-file", default="cache_sync.log", help="Log file path")
    sync_cache.set_defaults(handler=handle_sync_cache)

    doctor = subparsers.add_parser("doctor", help="Run dependency diagnostics.")
    doctor.set_defaults(handler=handle_doctor)

    return parser


def run_module(module_name: str, args: Sequence[str]) -> int:
    cmd = [sys.executable, "-m", module_name, *args]
    completed = subprocess.run(cmd)
    return completed.returncode


def handle_download(args: argparse.Namespace) -> int:
    cmd_args = [
        "--sample", str(args.sample),
        "--output", args.output,
        "--workers", str(args.workers),
    ]
    if args.all:
        cmd_args.append("--all")
    return run_module("download_materials_improved", cmd_args)


def handle_label(args: argparse.Namespace) -> int:
    cmd_args = [
        "--materials_dir", args.materials_dir,
        "--output_file", args.output_file,
        "--delay", str(args.delay),
        "--batch_size", str(args.batch_size),
        "--batch_delay", str(args.batch_delay),
    ]
    return run_module("gemini_label_materials", cmd_args)


def handle_archive(args: argparse.Namespace) -> int:
    cmd_args = [
        "--provider", args.provider,
        "--media-type", args.media_type,
        "--sample", str(args.sample),
        "--concurrency", str(args.concurrency),
    ]
    if args.test:
        cmd_args.append("--test")
    return run_module("gemma_dewu_archiver", cmd_args)


def handle_sync_cache(args: argparse.Namespace) -> int:
    cmd_args = [
        "--cache-file", args.cache_file,
        "--smb-path", args.smb_path,
        "--smb-filename", args.smb_filename,
        "--local-excel-dir", args.local_excel_dir,
        "--poll-interval", str(args.poll_interval),
        "--log-file", args.log_file,
    ]
    return run_module("cache_sync_to_smb", cmd_args)


def handle_doctor(_: argparse.Namespace) -> int:
    return run_module("check_multimodal_deps", [])


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
