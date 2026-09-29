"""Command-line entry point: ``uv run hoopformer <command>``."""

from __future__ import annotations

import argparse
from pathlib import Path

from hoopformer.dataset import build_dataset, cached_seasons
from hoopformer.evaluate import LockedSplitError, cached_baselines, evaluate, score
from hoopformer.fetch import fetch_season
from hoopformer.rapm import choose_lambda, ratings, season_rows


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

    rapm = commands.add_parser("rapm", help="fit RAPM on a season's cached games and write the ratings")
    rapm.add_argument("--season", required=True, help="e.g. 2025-26")
    rapm.add_argument("--top", type=int, default=15, help="how many players to print from each end")
    rapm.add_argument("--min-possessions", type=int, default=1500, help="only print players with this many")
    rapm.add_argument("--data-dir", type=Path, default=Path("data"))

    dataset = commands.add_parser("dataset", help="build the possession-level dataset for the transformer")
    dataset.add_argument("--season", nargs="+", help="default: every season with a downloaded schedule")
    dataset.add_argument("--out", type=Path, default=Path("data/derived/possessions.parquet"))
    dataset.add_argument("--data-dir", type=Path, default=Path("data"))

    grade = commands.add_parser("evaluate", help="score a predictions file next to the baselines")
    grade.add_argument("--predictions", type=Path, required=True, help="Parquet with game_id, possession, p0..p4")
    grade.add_argument("--split", choices=("validation", "test"), default="validation")
    grade.add_argument("--final", action="store_true", help="required for the test split, after pre-registration")
    grade.add_argument("--name", default="your model", help="the model's name in the report")
    grade.add_argument("--dataset", type=Path, default=Path("data/derived/possessions.parquet"))
    grade.add_argument("--data-dir", type=Path, default=Path("data"))

    bar = commands.add_parser("baselines", help="fit (once) and print baselines B0-B2 on the validation split")
    bar.add_argument("--dataset", type=Path, default=Path("data/derived/possessions.parquet"))
    bar.add_argument("--data-dir", type=Path, default=Path("data"))

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
    if args.command == "rapm":
        rows, names, dates = season_rows(args.data_dir, args.season)
        print(f"{args.season}: {len(rows)} stint rows from {len({r.game_id for r in rows})} games")
        lam, table = choose_lambda(rows, dates)
        print("error on the latest 20% of games (points per 100, squared):")
        print(table.to_string(index=False))
        result = ratings(rows, names, lam)
        out = args.data_dir / "derived" / f"rapm_{args.season}.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        result.to_csv(out, index=False)
        print(f"lambda {lam:g} | league average {result.attrs['league_average']:.1f} | home bonus {result.attrs['home_bonus']:+.2f} | wrote {out}")
        shown = result[result.possessions >= args.min_possessions].round(2)
        print(shown.head(args.top).to_string(index=False))
        print("...")
        print(shown.tail(args.top).to_string(index=False))
    if args.command == "dataset":
        seasons = args.season or cached_seasons(args.data_dir)
        frame, report = build_dataset(args.data_dir, seasons)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(args.out, index=False)
        print(f"{report.rows} possessions from {report.games} games -> {args.out}")
        print("rows per split:", frame["split"].value_counts().to_dict())
        if report.missing:
            print(f"{len(report.missing)} finished games not downloaded (run `hoopformer fetch` to add them)")
        if report.failed:
            print(f"{len(report.failed)} games failed lineup reconstruction:")
            for game_id, error in report.failed.items():
                print("  ", game_id, error)
            exit_code = 1
    if args.command == "baselines":
        import pandas as pd

        dataset = pd.read_parquet(args.dataset)
        baselines = cached_baselines(dataset, "validation", args.data_dir / "derived")
        labels = dataset[dataset["split"] == "validation"]["points"].to_numpy()
        print(score(baselines, labels).to_string(index=False, float_format=lambda v: f"{v:.5f}"))
    if args.command == "evaluate":
        import pandas as pd

        try:
            report = evaluate(pd.read_parquet(args.predictions), pd.read_parquet(args.dataset), args.split,
                              args.data_dir / "derived", model_name=args.name, final=args.final)
        except (LockedSplitError, ValueError) as exc:
            print(f"not scored: {exc}")
            return 1
        print(report.to_string(index=False, float_format=lambda v: f"{v:.5f}"))
    return exit_code
