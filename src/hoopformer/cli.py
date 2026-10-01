"""Command-line entry point: ``uv run hoopformer <command>``."""

from __future__ import annotations

import argparse
from pathlib import Path

from hoopformer.dataset import build_dataset, cached_seasons
from hoopformer.evaluate import LockedSplitError, cached_baselines, evaluate, score
from hoopformer.fetch import fetch_season
from hoopformer.rapm import choose_lambda, ratings, season_rows


def model_path(data_dir: Path, season: str) -> Path:
    return data_dir / "derived" / f"action_model_{season}.json"


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

    actions = commands.add_parser("actions", help="fit the game's action model on a season and check its realism")
    actions.add_argument("--season", default="2025-26")
    actions.add_argument("--games", type=int, default=1000, help="simulated games for the realism check")
    actions.add_argument("--data-dir", type=Path, default=Path("data"))

    play = commands.add_parser("play", help="simulate one game between two teams (e.g. --home OKC --away HOU)")
    play.add_argument("--home", required=True, help="team tricode")
    play.add_argument("--away", required=True, help="team tricode")
    play.add_argument("--seed", type=int, default=0, help="the same seed replays the same game")
    play.add_argument("--season", default="2025-26")
    play.add_argument("--play-by-play", action="store_true", help="print every event")
    play.add_argument("--data-dir", type=Path, default=Path("data"))

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
    if args.command == "actions":
        from hoopformer.game.actions import season_counts
        from hoopformer.game.model import fit_action_model
        from hoopformer.game.realism import compare, real_per_team_game, simulate_league, simulated_per_team_game

        players, teams, extras = season_counts(args.data_dir, args.season)
        model = fit_action_model(players, teams, extras, args.season)
        path = model_path(args.data_dir, args.season)
        model.save(path)
        print(f"{len(model.players)} players, {len(model.teams)} teams -> {path}")
        table = compare(real_per_team_game(extras), simulated_per_team_game(simulate_league(model, args.games, seed=1)))
        print(f"realism, per team per game, real season vs {args.games} simulated games:")
        print(table[["statistic", "real", "simulated", "difference", "tolerance", "ok"]].to_string(index=False, float_format=lambda v: f"{v:.4f}"))
        if not table.ok.all():
            exit_code = 1
    if args.command == "play":
        from hoopformer.game.engine import Game
        from hoopformer.game.model import ActionModel

        path = model_path(args.data_dir, args.season)
        if not path.exists():
            print(f"no action model at {path}: run `uv run hoopformer actions --season {args.season}` first")
            return 1
        model = ActionModel.load(path)
        by_code = {team.tricode: team.team_id for team in model.teams.values()}
        unknown = [code for code in (args.home, args.away) if code not in by_code]
        if unknown:
            print(f"unknown team {unknown}; choose from {' '.join(sorted(by_code))}")
            return 1
        result = Game(model, by_code[args.home], by_code[args.away], seed=args.seed).play()
        if args.play_by_play:
            for event in result.events:
                minutes, seconds = divmod(int(event.clock), 60)
                print(f"Q{event.period} {minutes:2d}:{seconds:02d}  {event.team}  {event.text}  ({event.home_score}-{event.away_score})")
        for side in (result.away, result.home):
            print(f"\n{side.name} {side.points}")
            print(result.box_score(side).to_string(index=False))
        overtime = f" after {result.periods - 4} overtime(s)" if result.periods > 4 else ""
        print(f"\nFinal{overtime}: {result.away.tricode} {result.away.points} @ {result.home.tricode} {result.home.points} (seed {args.seed})")
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
