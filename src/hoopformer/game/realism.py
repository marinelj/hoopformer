"""Check that simulated games look like real NBA games, statistic by statistic.

A simulated league is compared with the real season the model learned from:
points, possessions, shot mix, shooting percentages, free throws, rebounds,
assists, steals, blocks, turnovers, fouls and home wins, per team per game.
Each statistic has a tolerance; the realism tests require all of them to pass.
"""

from __future__ import annotations

import random

import pandas as pd

from hoopformer.game.engine import Game, GameResult
from hoopformer.game.model import ActionModel

# statistic -> (how it's computed from per-team-game totals, tolerance, "relative" or "absolute")
CHECKS = {
    "points": (lambda t: t["points"], 0.03, "relative"),
    "possessions": (lambda t: t["possessions"], 0.03, "relative"),
    "FGA": (lambda t: t["FGA"], 0.04, "relative"),
    "3PA share": (lambda t: t["3PA"] / t["FGA"], 0.02, "absolute"),
    "FG%": (lambda t: t["FGM"] / t["FGA"], 0.015, "absolute"),
    "3P%": (lambda t: t["3PM"] / t["3PA"], 0.015, "absolute"),
    "FTA": (lambda t: t["FTA"], 0.08, "relative"),
    "FT%": (lambda t: t["FTM"] / t["FTA"], 0.015, "absolute"),
    "OREB": (lambda t: t["OREB"], 0.08, "relative"),
    "DREB": (lambda t: t["DREB"], 0.05, "relative"),
    "AST": (lambda t: t["AST"], 0.08, "relative"),
    "STL": (lambda t: t["STL"], 0.10, "relative"),
    "BLK": (lambda t: t["BLK"], 0.10, "relative"),
    "TOV": (lambda t: t["TOV"], 0.08, "relative"),
    "PF": (lambda t: t["PF"], 0.10, "relative"),
    "home win share": (lambda t: t["home_wins"], 0.05, "absolute"),
}
REAL_NAMES = {"points": "points", "FGA": "fieldGoalsAttempted", "FGM": "fieldGoalsMade", "3PA": "threePointersAttempted",
              "3PM": "threePointersMade", "FTA": "freeThrowsAttempted", "FTM": "freeThrowsMade",
              "OREB": "reboundsOffensive", "DREB": "reboundsDefensive", "AST": "assists", "STL": "steals",
              "BLK": "blocks", "TOV": "turnovers", "PF": "foulsPersonal"}


def real_per_team_game(extras: dict) -> dict[str, float]:
    """The real season's averages per team per game, from the box scores the model was fitted on."""
    team_games = 2 * extras["games"]
    totals = {ours: extras["team_totals"][real] / team_games for ours, real in REAL_NAMES.items()}
    totals["possessions"] = extras["possessions"] / team_games
    totals["home_wins"] = extras["home_wins"] / extras["games"]
    return totals


def simulated_per_team_game(results: list[GameResult]) -> dict[str, float]:
    """The same averages from simulated games, plus team turnovers (they're not in player box scores)."""
    totals = {key: 0.0 for key in list(REAL_NAMES) + ["possessions"]}
    for result in results:
        for side in (result.home, result.away):
            totals["points"] += side.points
            totals["possessions"] += side.possessions
            for key in REAL_NAMES:
                if key != "points":
                    totals[key] += sum(a.stats[key] for a in side.athletes.values())
            totals["TOV"] += side.team_turnovers
    per_team_game = {key: value / (2 * len(results)) for key, value in totals.items()}
    per_team_game["home_wins"] = sum(r.home.points > r.away.points for r in results) / len(results)
    return per_team_game


def simulate_league(model: ActionModel, games: int, seed: int = 0) -> list[GameResult]:
    """`games` games between random pairs of teams, each with its own seed derived from `seed`."""
    rng = random.Random(seed)
    team_ids = sorted(model.teams)
    results = []
    for _ in range(games):
        home, away = rng.sample(team_ids, 2)
        results.append(Game(model, home, away, seed=rng.randrange(1 << 30)).play())
    return results


def compare(real: dict[str, float], simulated: dict[str, float]) -> pd.DataFrame:
    """One line per statistic: real, simulated, difference, tolerance, and whether it passes."""
    lines = []
    for name, (compute, tolerance, kind) in CHECKS.items():
        r, s = compute(real), compute(simulated)
        difference = (s - r) / r if kind == "relative" else s - r
        lines.append({"statistic": name, "real": r, "simulated": s, "difference": difference,
                      "tolerance": tolerance, "kind": kind, "ok": abs(difference) <= tolerance})
    return pd.DataFrame(lines)


# --- rotations: substitutions, timeouts, stint lengths and minutes ----------------------------------

TIERS = ((33.0, "33+ mpg"), (28.0, "28-33 mpg"), (20.0, "20-28 mpg"), (0.0, "under 20 mpg"))


def tier(minutes_per_game: float) -> str:
    return next(name for floor, name in TIERS if minutes_per_game >= floor)


def on_court_intervals(timeline: list[tuple[float, tuple[int, ...]]], end: float) -> dict[int, list[list[float]]]:
    """Each player's continuous spells on the floor, from (time, the ten on the floor) moments in time order.

    A player still on the floor when a period ends and the next one starts is one spell, as in real box scores.
    """
    spells: dict[int, list[list[float]]] = {}
    on: dict[int, float] = {}
    for t, floor in timeline:
        now = set(floor)
        for pid in [p for p in on if p not in now]:
            spells.setdefault(pid, []).append([on.pop(pid), t])
        for pid in now - set(on):
            on[pid] = t
    for pid, start in on.items():
        spells.setdefault(pid, []).append([start, end])
    return spells


def rotation_summary(spells_per_game: list[dict[int, list[list[float]]]], entries: list[int], timeouts: list[int],
                     model: ActionModel) -> dict:
    """Substitutions and timeouts per team-game, average stint by minutes tier, and each player's minutes per game."""
    stints: dict[str, list[float]] = {name: [] for _, name in TIERS}
    minutes: dict[int, list[float]] = {}
    for spells in spells_per_game:
        for pid, intervals in spells.items():
            profile = model.players.get(pid)
            if profile is None:
                continue
            stints[tier(profile.minutes_per_game)] += [(b - a) / 60 for a, b in intervals]
            minutes.setdefault(pid, []).append(sum(b - a for a, b in intervals) / 60)
    return {
        "subs per team-game": sum(entries) / len(entries),
        "timeouts per team-game": sum(timeouts) / len(timeouts),
        "stint minutes": {name: sum(v) / len(v) for name, v in stints.items() if v},
        "minutes per game": {pid: sum(v) / len(v) for pid, v in minutes.items()},
    }


def simulated_rotations(results: list[GameResult], model: ActionModel) -> dict:
    from hoopformer.game.replay import game_seconds

    spells_per_game, entries, timeouts = [], [], []
    for result in results:
        timeline = [(game_seconds(e.period, e.clock), e.home_lineup + e.away_lineup) for e in result.events if e.home_lineup]
        end = game_seconds(result.periods, 0.0)
        spells = on_court_intervals(timeline, end)
        # every player who appeared, including those who never left the bench (0 minutes) counts for the average
        for side in (result.home, result.away):
            for pid in side.athletes:
                spells.setdefault(pid, [])
            starts_of_halves = sum(1 for e in result.events if e.kind == "sub" and e.team == side.tricode and e.zone == "starters")
            entries.append(sum(1 for e in result.events if e.kind == "sub" and e.team == side.tricode) - starts_of_halves)
            timeouts.append(sum(1 for e in result.events if e.kind == "timeout" and e.team == side.tricode))
        spells_per_game.append({pid: v for pid, v in spells.items() if v})
    return rotation_summary(spells_per_game, entries, timeouts, model)


def real_rotations(data_dir, season: str, model: ActionModel, games: int | None = None) -> dict:
    """The same numbers from real games: rebuilt lineups for stints and minutes, play-by-play for timeouts."""
    import json

    from hoopformer.fetch import BOX_SCORE, PLAY_BY_PLAY, SCHEDULE, final_regular_season_game_ids, raw_path
    from hoopformer.lineups import LineupError, reconstruct_game

    schedule = json.loads(raw_path(data_dir, SCHEDULE, season).read_text(encoding="utf-8"))
    game_ids = [g for g in final_regular_season_game_ids(schedule) if raw_path(data_dir, PLAY_BY_PLAY, g).exists()][:games]
    spells_per_game, entries, timeouts = [], [], []
    for game_id in game_ids:
        pbp = json.loads(raw_path(data_dir, PLAY_BY_PLAY, game_id).read_text(encoding="utf-8"))
        box = json.loads(raw_path(data_dir, BOX_SCORE, game_id).read_text(encoding="utf-8"))["boxScoreTraditional"]
        try:
            stints = reconstruct_game(pbp, box)
        except LineupError:
            continue
        timeline = [(s.start, s.home + s.away) for s in stints]
        spells_per_game.append(on_court_intervals(timeline, stints[-1].end))
        for side in ("home", "away"):
            fives = [(s.period, getattr(s, side)) for s in stints]
            entries.append(sum(len(set(b) - set(a)) for (pa, a), (pb, b) in zip(fives, fives[1:]) if pa == pb))
        for team in (box["homeTeamId"], box["awayTeamId"]):
            # a timeout's team id is in personId; coach's challenges aren't timeouts
            timeouts.append(sum(1 for a in pbp["game"]["actions"]
                                if a["actionType"] == "Timeout" and a.get("subType") == "Regular" and a.get("personId") == team))
    return rotation_summary(spells_per_game, entries, timeouts, model)
