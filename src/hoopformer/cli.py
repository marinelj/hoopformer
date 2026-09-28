"""Command-line entry point: ``uv run hoopformer <command>``."""

from __future__ import annotations

import argparse
from pathlib import Path

from hoopformer.fetch import fetch_season


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hoopformer")
    commands = parser.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser("fetch", help="cache raw NBA Stats responses for one or more seasons")
    fetch.add_argument("--season", required=True, nargs="+", help="e.g. 2025-26 2024-25, fetched in that order")
    fetch.add_argument("--limit", type=int, help="only the first N games (for a quick test)")
    fetch.add_argument("--delay", type=float, default=1.0, help="seconds to wait between requests")
    fetch.add_argument("--refresh-schedule", action="store_true", help="re-download the schedule")
    fetch.add_argument("--data-dir", type=Path, default=Path("data"))
    fetch.add_argument("--manifest", type=Path, default=Path("manifests/raw.jsonl"))

    args = parser.parse_args(argv)
    exit_code = 0
    if args.command == "fetch":
        for season in args.season:
            report = fetch_season(
                season, args.data_dir, args.manifest, limit=args.limit,
                delay=args.delay, refresh_schedule=args.refresh_schedule,
            )
            print(f"{season} done: {report.fetched} fetched, {report.cached} already cached, {len(report.failed)} failed")
            if report.failed:
                print(f"{season} failed game ids (re-run the same command to retry):", " ".join(report.failed))
                exit_code = 1
    return exit_code
