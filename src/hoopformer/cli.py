"""Command-line entry point: ``uv run hoopformer <command>``."""

from __future__ import annotations

import argparse
from pathlib import Path

from hoopformer.dataset import build_dataset, cached_seasons
from hoopformer.evaluate import LockedSplitError, cached_baselines, evaluate, score
from hoopformer.fetch import fetch_rosters, fetch_season
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
    fetch.add_argument("--rosters", action="store_true", help="fetch the 30 current team rosters instead of games")
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
    actions.add_argument("--games", type=int, default=2000, help="simulated games for the realism check")
    actions.add_argument("--data-dir", type=Path, default=Path("data"))

    play = commands.add_parser("play", help="simulate one game between two teams (e.g. --home OKC --away HOU)")
    play.add_argument("--home", required=True, help="team tricode")
    play.add_argument("--away", required=True, help="team tricode")
    play.add_argument("--seed", type=int, default=0, help="the same seed replays the same game")
    play.add_argument("--season", default="2025-26")
    play.add_argument("--play-by-play", action="store_true", help="print every event")
    play.add_argument("--data-dir", type=Path, default=Path("data"))
    play.add_argument("--replay", type=Path, help="also write a Courtside replay page (HTML) here")
    play.add_argument("--rosters", help="play with this season's cached rosters, e.g. 2026-27 (fetch --rosters first)")
    play.add_argument("--say", action="append", default=[], metavar="WHEN WORDS",
                      help='the home coach speaks, e.g. "Q2 6:00 Push the pace" or "Q4 3:00 Shai Gilgeous-Alexander: take over"; repeatable')
    play.add_argument("--use", choices=("auto", "qwen", "openai", "rules"), default="auto",
                      help="translator for --say (auto: the first LLM with a key set, else rules)")

    talk = commands.add_parser("coach", help="translate a coach's words into levers (Qwen or OpenAI, or keyword rules without a key)")
    talk.add_argument("words", nargs="?", help='e.g. "Push the pace and run their shooters off the line"')
    talk.add_argument("--to", help='the player you\'re talking to, e.g. "Shai Gilgeous-Alexander" (default: the whole team)')
    talk.add_argument("--home", default="OKC", help="your team")
    talk.add_argument("--away", default="BOS")
    talk.add_argument("--season", default="2025-26")
    talk.add_argument("--use", choices=("auto", "qwen", "openai", "rules"), default="auto")
    talk.add_argument("--check", action="store_true", help="grade the translator on the 50 test phrases and the 30 held-out ones")
    talk.add_argument("--data-dir", type=Path, default=Path("data"))

    args = parser.parse_args(argv)
    exit_code = 0
    if args.command == "fetch" and args.rosters:
        for season in args.season:
            report = fetch_rosters(season, args.data_dir, args.manifest, delay=args.delay)
            print(f"{season} rosters: {report.fetched} fetched, {len(report.failed)} failed {' '.join(report.failed)}")
            exit_code = 1 if report.failed else exit_code
    elif args.command == "fetch":
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
        if args.rosters:
            from hoopformer.game.rosters import season_rosters, with_rosters

            rosters = season_rosters(args.data_dir, args.rosters)
            if len(rosters) < 30:
                print(f"only {len(rosters)} {args.rosters} rosters cached: run `uv run hoopformer fetch --rosters --season {args.rosters}`")
                return 1
            model = with_rosters(model, rosters, args.rosters)
        by_code = {team.tricode: team.team_id for team in model.teams.values()}
        unknown = [code for code in (args.home, args.away) if code not in by_code]
        if unknown:
            print(f"unknown team {unknown}; choose from {' '.join(sorted(by_code))}")
            return 1
        if args.say:
            result = coached_game(model, by_code[args.home], by_code[args.away], args)
        else:
            result = Game(model, by_code[args.home], by_code[args.away], seed=args.seed).play()
        if args.play_by_play:
            for event in (e for e in result.events if e.kind != "chance"):
                minutes, seconds = divmod(int(event.clock), 60)
                print(f"Q{event.period} {minutes:2d}:{seconds:02d}  {event.team}  {event.text}  ({event.home_score}-{event.away_score})")
        for side in (result.away, result.home):
            print(f"\n{side.name} {side.points}")
            print(result.box_score(side).to_string(index=False))
        if args.replay:
            from hoopformer.game.replay import replay_data, replay_html

            args.replay.parent.mkdir(parents=True, exist_ok=True)
            args.replay.write_text(replay_html(replay_data(result, model)), encoding="utf-8")
            print(f"replay page: {args.replay}")
        overtime = f" after {result.periods - 4} overtime(s)" if result.periods > 4 else ""
        print(f"\nFinal{overtime}: {result.away.tricode} {result.away.points} @ {result.home.tricode} {result.home.points} (seed {args.seed})")
    if args.command == "coach":
        exit_code = coach_command(args)
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


def coached_game(model, home: int, away: int, args):
    """Play a game in which the home coach speaks at the given times (--say)."""
    import re

    from hoopformer.game.engine import Game
    from hoopformer.game.levers import lever_limits
    from hoopformer.game.replay import game_seconds
    from hoopformer.game.translator import load_env, translate

    load_env()
    game = Game(model, home, away, seed=args.seed, limits=lever_limits(args.data_dir, model.season[:7]))
    names = {a.profile.name.casefold(): pid for pid, a in game.home.athletes.items()}
    pending = []
    for said in args.say:
        match = re.match(r"^Q(\d)\s+(\d{1,2}):(\d\d)\s+(.+)$", said.strip())
        if not match:
            raise SystemExit(f'--say needs "Q<period> <m:ss> words", got {said!r}')
        period, minutes, seconds, words = int(match[1]), int(match[2]), int(match[3]), match[4]
        name, colon, rest = words.partition(":")
        addressed = names.get(name.strip().casefold()) if colon else None
        pending.append((game_seconds(period, 60 * minutes + seconds), rest.strip() if addressed else words, addressed))
    pending.sort()
    while not game.done:
        while pending and pending[0][0] <= game.game_seconds and game.period_open:
            _, words, addressed = pending.pop(0)
            instruction = translate(words, game, game.home, addressed, use=args.use,
                                    unmapped_log=args.data_dir / "derived" / "unmapped.jsonl")
            game.instruct(game.home, instruction)
            names = {pid: a.profile.name for team in (game.home, game.away) for pid, a in team.athletes.items()}
            print(f"Q{game.period} {int(game.clock) // 60}:{int(game.clock) % 60:02d} coach: {words!r} -> "
                  f"{instruction.describe(names)} [{instruction.source}]")
            if instruction.reply:
                print(f"   {model.players[instruction.replier].name if instruction.replier else 'team'}: {instruction.reply}")
        game.step()
    return game.result()


def coach_command(args) -> int:
    """`hoopformer coach`: translate one instruction, or grade a translator on the test phrases."""
    import json
    from dataclasses import asdict

    from hoopformer.game.engine import Game
    from hoopformer.game.levers import lever_limits
    from hoopformer.game.model import ActionModel
    from hoopformer.game.translator import HOLDOUT_PHRASES, PHRASES, check_phrases, load_env, translate

    load_env()
    path = model_path(args.data_dir, args.season)
    if not path.exists():
        print(f"no action model at {path}: run `uv run hoopformer actions --season {args.season}` first")
        return 1
    model = ActionModel.load(path)
    by_code = {team.tricode: team.team_id for team in model.teams.values()}
    game = Game(model, by_code[args.home], by_code[args.away], seed=1, limits=lever_limits(args.data_dir, args.season))
    for _ in range(60):  # into the second quarter, so there's a score and some fouls to talk about
        game.step()
    if args.check:
        for label, phrases in (("test phrases", PHRASES), ("held-out phrases", HOLDOUT_PHRASES)):
            passed, total, _ = check_phrases(game, game.home, args.use, phrases)
            print(f"{label}: {passed}/{total}\n")
        return 0
    if not args.words:
        print('say something, e.g. uv run hoopformer coach "Push the pace and run their shooters off the line"')
        return 1
    addressed = None
    if args.to:
        addressed = next((pid for pid, a in game.home.athletes.items() if a.profile.name.casefold() == args.to.casefold()), None)
        if addressed is None:
            print(f"{args.to!r} isn't on {args.home}: " + ", ".join(a.profile.name for a in game.home.athletes.values()))
            return 1
    instruction = translate(args.words, game, game.home, addressed, use=args.use,
                            unmapped_log=args.data_dir / "derived" / "unmapped.jsonl")
    print(json.dumps(asdict(instruction), indent=1, ensure_ascii=False, default=str))
    return 0
