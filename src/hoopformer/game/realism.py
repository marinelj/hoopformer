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
