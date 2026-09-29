"""Tests for the possession-level dataset, on real cached games."""

import json
from pathlib import Path

import pandas as pd
import pytest

from hoopformer.dataset import (
    COLUMNS,
    MAX_POINTS,
    SPLITS,
    build_dataset,
    cached_seasons,
    possession_rows,
    running_scores,
)
from hoopformer.fetch import BOX_SCORE, PLAY_BY_PLAY, SCHEDULE, raw_path
from hoopformer.lineups import reconstruct_game
from hoopformer.possessions import stint_totals

DATA = Path("data")
OKC, HOU = 1610612760, 1610612745


def load(game_id: str) -> tuple[dict, dict]:
    pbp_path, box_path = raw_path(DATA, PLAY_BY_PLAY, game_id), raw_path(DATA, BOX_SCORE, game_id)
    if not (pbp_path.exists() and box_path.exists()):
        pytest.skip(f"game {game_id} not cached")
    return json.loads(pbp_path.read_text()), json.loads(box_path.read_text())["boxScoreTraditional"]


def test_splits_are_chronological_and_the_test_season_is_last():
    order = sorted(SPLITS)
    print({season: SPLITS[season] for season in order})
    assert [SPLITS[s] for s in order] == ["train"] * 8 + ["validation", "test"]


def test_running_scores_end_at_the_final_score():
    pbp, box = load("0022500001")
    running = running_scores(pbp["game"]["actions"], OKC, HOU)
    print("final running scores:", running[OKC][-1], running[HOU][-1])
    assert (running[OKC][-1], running[HOU][-1]) == (box["homeTeam"]["statistics"]["points"], box["awayTeam"]["statistics"]["points"])
    assert all(a <= b for a, b in zip(running[OKC], running[OKC][1:])), "a score never goes down"


def test_possession_rows_of_the_opener():
    pbp, box = load("0022500001")
    rows = pd.DataFrame(possession_rows(pbp, box, "2025-26", "2025-10-21"))
    print(rows.head(4)[["period", "seconds_left", "start_margin", "offense_is_home", "points"]].to_string())
    first, second, third = rows.iloc[0], rows.iloc[1], rows.iloc[2]
    assert (first.period, first.seconds_left, first.start_margin, bool(first.offense_is_home)) == (1, 720.0, 0, False), "Houston wins the tip"
    assert (second.points, third.start_margin) == (3, -3), "OKC scores 3, so Houston starts its next possession down 3"
    assert rows.points.between(0, MAX_POINTS).all()
    assert list(rows.possession) == list(range(len(rows))), "possessions are numbered 0, 1, 2, ... within a game"
    for _, row in rows.iterrows():
        offense = [row[f"off_{i}"] for i in range(5)]
        defense = [row[f"def_{i}"] for i in range(5)]
        assert offense == sorted(offense) and defense == sorted(defense) and not set(offense) & set(defense)


def test_possession_rows_agree_with_the_stint_totals_rapm_uses():
    pbp, box = load("0022500001")
    rows = pd.DataFrame(possession_rows(pbp, box, "2025-26", "2025-10-21"))
    totals = stint_totals(pbp, box, reconstruct_game(pbp, box))
    home = rows[rows.offense_is_home]
    print(f"OKC rows {len(home)}, points {home.points.sum()} | stint totals {sum(t.home_possessions for t in totals)}, {sum(t.home_points for t in totals)}")
    assert len(home) == sum(t.home_possessions for t in totals)
    assert len(rows) - len(home) == sum(t.away_possessions for t in totals)
    assert home.points.sum() == sum(t.home_points for t in totals), "no possession in the opener scored more than 4"


def test_cached_seasons_lists_downloaded_schedules():
    seasons = cached_seasons(DATA)
    print("cached seasons:", seasons)
    if not seasons:
        pytest.skip("no schedules downloaded")
    assert seasons == sorted(seasons) and all((DATA / "raw" / SCHEDULE / f"{s}.json").exists() for s in seasons)


def test_build_dataset_on_every_cached_game():
    seasons = cached_seasons(DATA)
    if not seasons:
        pytest.skip("no schedules downloaded")
    frame, report = build_dataset(DATA, seasons, log=print)
    shares = frame.points.value_counts(normalize=True).sort_index()
    print(f"{report.games} games, {report.rows} rows, {len(report.missing)} not downloaded, failed: {report.failed}")
    print("points shares:", shares.round(4).to_dict())
    assert list(frame.columns) == COLUMNS
    assert not report.failed
    assert 180 < report.rows / report.games < 230, "an NBA game has about 200 possessions"
    assert 0.45 < shares[0] < 0.53 and 0.28 < shares[2] < 0.36, "about half of possessions score nothing"
    assert set(frame.split) <= {"train", "validation", "test"}


def test_cli_dataset_writes_parquet(tmp_path):
    if not cached_seasons(DATA):
        pytest.skip("no schedules downloaded")
    from hoopformer.cli import main

    out = tmp_path / "possessions.parquet"
    assert main(["dataset", "--season", "2025-26", "--out", str(out)]) == 0
    frame = pd.read_parquet(out)
    print(frame.shape, frame.dtypes.to_dict())
    assert list(frame.columns) == COLUMNS and len(frame) > 0
