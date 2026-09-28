"""RAPM: regularized adjusted plus-minus, the baseline Hoopformer has to beat.

Every stint gives two rows, one per team on offense: "these five attackers
against these five defenders scored this many points per 100 possessions".
A linear model explains each row as

    league average + home bonus + sum(offense ratings of the 5 attackers)
                                + sum(defense ratings of the 5 defenders)

and ridge regression fits one offense and one defense number per player. The
ridge penalty (lambda) pulls every rating toward zero, and pulls hardest on
players with little court time, so a lucky 20-minute sample can't crown
anyone. Lambda is picked by fitting on earlier games and scoring on later ones.

Rows are weighted by possessions, so a 10-possession stint counts ten times
more than a 1-possession one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.linear_model import Ridge

from hoopformer.fetch import BOX_SCORE, PLAY_BY_PLAY, SCHEDULE, final_regular_season_game_ids, raw_path
from hoopformer.lineups import reconstruct_game, team_rosters
from hoopformer.possessions import stint_totals

LAMBDAS = (100.0, 300.0, 1_000.0, 3_000.0, 10_000.0, 30_000.0)


@dataclass(frozen=True)
class Row:
    game_id: str
    offense: tuple[int, ...]
    defense: tuple[int, ...]
    offense_is_home: bool
    points: int
    possessions: int


def game_rows(pbp: dict, box: dict) -> list[Row]:
    """Two rows per stint with possessions: home on offense, away on offense."""
    rows = []
    for totals in stint_totals(pbp, box, reconstruct_game(pbp, box)):
        stint = totals.stint
        if totals.home_possessions:
            rows.append(Row(stint.game_id, stint.home, stint.away, True, totals.home_points, totals.home_possessions))
        if totals.away_possessions:
            rows.append(Row(stint.game_id, stint.away, stint.home, False, totals.away_points, totals.away_possessions))
    return rows


def game_dates(data_dir: Path, season: str) -> dict[str, str]:
    """Game id -> date (YYYY-MM-DD) from the cached schedule, for chronological splits."""
    schedule = json.loads(raw_path(data_dir, SCHEDULE, season).read_text())
    return {game["gameId"]: game["gameDateEst"][:10]
            for day in schedule["leagueSchedule"]["gameDates"] for game in day["games"]}


def season_rows(data_dir: Path, season: str) -> tuple[list[Row], dict[int, str], dict[str, str]]:
    """Rows for every cached, finished regular-season game, player names, and game dates."""
    schedule = json.loads(raw_path(data_dir, SCHEDULE, season).read_text())
    dates = game_dates(data_dir, season)
    rows: list[Row] = []
    names: dict[int, str] = {}
    for game_id in final_regular_season_game_ids(schedule):
        pbp_path, box_path = raw_path(data_dir, PLAY_BY_PLAY, game_id), raw_path(data_dir, BOX_SCORE, game_id)
        if not (pbp_path.exists() and box_path.exists()):
            continue
        pbp = json.loads(pbp_path.read_text())
        box = json.loads(box_path.read_text())["boxScoreTraditional"]
        for roster in team_rosters(box).values():
            for player in roster:
                names[player["personId"]] = f"{player['firstName']} {player['familyName']}"
        rows.extend(game_rows(pbp, box))
    return rows, names, dates


def design_matrix(rows: list[Row], players: list[int]) -> tuple[sparse.csr_matrix, np.ndarray, np.ndarray]:
    """X (offense columns, then defense columns, then a home flag), y (points per 100), weights."""
    column = {player: i for i, player in enumerate(players)}
    n = len(players)
    data, indices, indptr = [], [], [0]
    for row in rows:
        cols = [column[p] for p in row.offense] + [n + column[p] for p in row.defense]
        if row.offense_is_home:
            cols.append(2 * n)
        indices.extend(cols)
        data.extend([1.0] * len(cols))
        indptr.append(len(indices))
    x = sparse.csr_matrix((data, indices, indptr), shape=(len(rows), 2 * n + 1))
    y = np.array([100.0 * row.points / row.possessions for row in rows])
    weights = np.array([float(row.possessions) for row in rows])
    return x, y, weights


def fit(rows: list[Row], players: list[int], lam: float) -> Ridge:
    x, y, weights = design_matrix(rows, players)
    model = Ridge(alpha=lam, fit_intercept=True, solver="sparse_cg", max_iter=10_000, tol=1e-6)
    return model.fit(x, y, sample_weight=weights)


def weighted_mse(model: Ridge | None, rows: list[Row], players: list[int], league_average: float) -> float:
    """Possession-weighted squared error in points per 100. model=None predicts the league average."""
    x, y, weights = design_matrix(rows, players)
    predictions = np.full(len(y), league_average) if model is None else model.predict(x)
    return float(np.average((y - predictions) ** 2, weights=weights))


def choose_lambda(rows: list[Row], dates: dict[str, str], holdout: float = 0.2,
                  lambdas: tuple[float, ...] = LAMBDAS) -> tuple[float, pd.DataFrame]:
    """Fit on the earliest games, score on the latest `holdout` share, return the best lambda and the table."""
    ordered = sorted({row.game_id for row in rows}, key=lambda g: (dates.get(g, ""), g))
    cutoff = set(ordered[: int(len(ordered) * (1 - holdout))])
    train = [r for r in rows if r.game_id in cutoff]
    test = [r for r in rows if r.game_id not in cutoff]
    players = sorted({p for r in rows for p in r.offense + r.defense})
    league_average = 100.0 * sum(r.points for r in train) / sum(r.possessions for r in train)
    results = [{"lambda": "league average only", "test_mse": weighted_mse(None, test, players, league_average)}]
    for lam in lambdas:
        results.append({"lambda": lam, "test_mse": weighted_mse(fit(train, players, lam), test, players, league_average)})
    table = pd.DataFrame(results)
    best = table.iloc[1:].sort_values("test_mse").iloc[0]["lambda"]
    return float(best), table


def ratings(rows: list[Row], names: dict[int, str], lam: float) -> pd.DataFrame:
    """One line per player: offense, defense (positive = prevents points) and total, per 100 possessions."""
    players = sorted({p for r in rows for p in r.offense + r.defense})
    model = fit(rows, players, lam)
    n = len(players)
    possessions = {p: 0 for p in players}
    for row in rows:
        for p in row.offense + row.defense:
            possessions[p] += row.possessions
    table = pd.DataFrame({
        "personId": players,
        "name": [names.get(p, str(p)) for p in players],
        "possessions": [possessions[p] for p in players],
        "offense": model.coef_[:n],
        "defense": -model.coef_[n:2 * n],
    })
    table["rapm"] = table["offense"] + table["defense"]
    table.attrs["league_average"] = 100.0 * sum(r.points for r in rows) / sum(r.possessions for r in rows)
    table.attrs["home_bonus"] = float(model.coef_[2 * n])
    return table.sort_values("rapm", ascending=False, ignore_index=True)
