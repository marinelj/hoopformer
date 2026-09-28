"""Tests for the RAPM baseline, on real cached games."""

import json
from pathlib import Path

import numpy as np
import pytest

from hoopformer.fetch import BOX_SCORE, PLAY_BY_PLAY, SCHEDULE, raw_path
from hoopformer.rapm import (
    LAMBDAS,
    choose_lambda,
    design_matrix,
    fit,
    game_dates,
    game_rows,
    ratings,
    season_rows,
    weighted_mse,
)

DATA = Path("data")
SGA = 1628983


def load(game_id: str) -> tuple[dict, dict]:
    pbp_path, box_path = raw_path(DATA, PLAY_BY_PLAY, game_id), raw_path(DATA, BOX_SCORE, game_id)
    if not (pbp_path.exists() and box_path.exists()):
        pytest.skip(f"game {game_id} not cached")
    return json.loads(pbp_path.read_text()), json.loads(box_path.read_text())["boxScoreTraditional"]


@pytest.fixture(scope="module")
def season():
    if not raw_path(DATA, SCHEDULE, "2025-26").exists():
        pytest.skip("2025-26 schedule not cached")
    rows, names, dates = season_rows(DATA, "2025-26")
    if len({r.game_id for r in rows}) < 100:
        pytest.skip("need at least 100 cached 2025-26 games")
    return rows, names, dates


def test_game_rows_keep_every_point_of_the_opener():
    pbp, box = load("0022500001")
    rows = game_rows(pbp, box)
    home_points = sum(r.points for r in rows if r.offense_is_home)
    away_points = sum(r.points for r in rows if not r.offense_is_home)
    print(f"{len(rows)} rows, home {home_points}, away {away_points}")
    assert (home_points, away_points) == (box["homeTeam"]["statistics"]["points"], box["awayTeam"]["statistics"]["points"])
    assert all(len(r.offense) == 5 and len(r.defense) == 5 and not set(r.offense) & set(r.defense) for r in rows)
    assert all(r.possessions > 0 for r in rows)


def test_game_dates_come_from_the_schedule():
    if not raw_path(DATA, SCHEDULE, "2025-26").exists():
        pytest.skip("2025-26 schedule not cached")
    assert game_dates(DATA, "2025-26")["0022500001"] == "2025-10-21"


def test_season_rows_match_the_league_scoring_rate(season):
    rows, names, _ = season
    rating = 100 * sum(r.points for r in rows) / sum(r.possessions for r in rows)
    print(f"{len(rows)} rows, league offensive rating {rating:.1f}")
    assert 105 < rating < 125, "NBA teams score roughly 110-120 points per 100 possessions"
    assert names[SGA] == "Shai Gilgeous-Alexander"


def test_design_matrix_puts_five_attackers_five_defenders_and_a_home_flag_in_each_row(season):
    rows = season[0][:500]
    players = sorted({p for r in rows for p in r.offense + r.defense})
    x, y, weights = design_matrix(rows, players)
    nonzeros = np.diff(x.indptr)
    print("shape", x.shape, "| nonzeros per row:", sorted(set(nonzeros)))
    assert x.shape == (500, 2 * len(players) + 1)
    assert set(nonzeros) <= {10, 11}
    assert (x[:, -1].toarray().ravel() == [float(r.offense_is_home) for r in rows]).all()
    assert y[0] == pytest.approx(100 * rows[0].points / rows[0].possessions)
    assert list(weights[:3]) == [r.possessions for r in rows[:3]]


def test_a_bigger_lambda_shrinks_the_ratings(season):
    rows = season[0]
    players = sorted({p for r in rows for p in r.offense + r.defense})
    norms = [np.linalg.norm(fit(rows, players, lam).coef_[:-1]) for lam in (300.0, 3_000.0, 30_000.0)]
    print("rating vector size at lambda 300 / 3,000 / 30,000:", [round(n, 2) for n in norms])
    assert norms[0] > norms[1] > norms[2]


def test_weighted_mse_of_the_league_average_is_the_weighted_variance(season):
    rows = season[0]
    players = sorted({p for r in rows for p in r.offense + r.defense})
    _, y, w = design_matrix(rows, players)
    average = float(np.average(y, weights=w))
    assert weighted_mse(None, rows, players, average) == pytest.approx(float(np.average((y - average) ** 2, weights=w)))


def test_choose_lambda_scores_every_candidate_on_later_games(season):
    rows, _, dates = season
    best, table = choose_lambda(rows, dates)
    print(table.to_string(index=False), "\nbest:", best)
    assert best in LAMBDAS
    assert len(table) == len(LAMBDAS) + 1 and table.iloc[0]["lambda"] == "league average only"


def test_ratings_split_into_offense_and_defense(season):
    rows, names, _ = season
    table = ratings(rows, names, 3_000.0)
    regulars = table[table.possessions >= 1500]
    print(regulars.head(10).round(2).to_string(index=False))
    assert np.allclose(table["rapm"], table["offense"] + table["defense"])
    assert table["rapm"].is_monotonic_decreasing
    assert 105 < table.attrs["league_average"] < 125
    assert table.loc[table.personId == SGA, "rapm"].item() > 0, "smell test: the reigning MVP helps their team"


def test_cli_rapm_writes_the_ratings_csv(season, capsys):
    from hoopformer.cli import main

    assert main(["rapm", "--season", "2025-26", "--top", "3"]) == 0
    output = capsys.readouterr().out
    print(output)
    assert "lambda" in output and (DATA / "derived" / "rapm_2025-26.csv").exists()
