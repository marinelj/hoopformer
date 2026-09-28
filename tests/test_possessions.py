"""Tests for points and possessions per stint, on real cached games."""

import glob
import json
from pathlib import Path

import pytest

from hoopformer.fetch import BOX_SCORE, PLAY_BY_PLAY, raw_path
from hoopformer.lineups import reconstruct_game
from hoopformer.possessions import (
    action_team,
    audit_points,
    is_final_free_throw,
    is_missed,
    keeps_ball,
    possession_ends,
    stint_totals,
)

DATA = Path("data")
OKC, HOU = 1610612760, 1610612745


def load(game_id: str) -> tuple[dict, dict]:
    pbp_path, box_path = raw_path(DATA, PLAY_BY_PLAY, game_id), raw_path(DATA, BOX_SCORE, game_id)
    if not (pbp_path.exists() and box_path.exists()):
        pytest.skip(f"game {game_id} not cached: run `uv run hoopformer fetch --season 2025-26 --limit 240`")
    return json.loads(pbp_path.read_text()), json.loads(box_path.read_text())["boxScoreTraditional"]


def cached_games() -> list[str]:
    games = sorted(Path(p).stem for p in glob.glob(str(DATA / "raw" / PLAY_BY_PLAY / "*.json")))
    return [g for g in games if raw_path(DATA, BOX_SCORE, g).exists()]


def test_action_team_reads_team_rows_from_person_id():
    teams = {OKC, HOU}
    assert action_team({"teamId": OKC, "personId": 1628983}, teams) == OKC
    assert action_team({"teamId": 0, "personId": HOU}, teams) == HOU, "team rebound / shot-clock turnover"
    assert action_team({"teamId": 0, "personId": 0}, teams) is None, "period start"


def test_free_throw_classification():
    assert is_final_free_throw("Free Throw 2 of 2") and is_final_free_throw("Free Throw 1 of 1")
    assert not is_final_free_throw("Free Throw 1 of 2") and not is_final_free_throw("Free Throw Technical")
    assert keeps_ball("Free Throw Technical") and keeps_ball("Free Throw Flagrant 2 of 2") and keeps_ball("Free Throw Clear Path 2 of 2")
    assert not keeps_ball("Free Throw 2 of 2")
    assert is_missed({"description": "MISS Towns Free Throw 2 of 3"})
    assert not is_missed({"description": "Towns Free Throw 1 of 3 (1 PTS)"})


def test_possession_ends_on_the_double_overtime_opener():
    pbp, box = load("0022500001")
    ends = possession_ends(pbp["game"]["actions"], {OKC, HOU})
    okc, hou = sum(t == OKC for _, t in ends), sum(t == HOU for _, t in ends)
    print(f"OKC possessions {okc}, HOU possessions {hou}")
    assert abs(okc - hou) <= 6, "a 6-period game: at most one extra possession per period"
    assert 100 < okc < 130, "a double-overtime game runs about 100 + 2 x 10 possessions"


def test_possessions_alternate_between_teams_almost_always():
    games = cached_games()
    if not games:
        pytest.skip("no cached games")
    total = slips = 0
    for game_id in games:
        pbp, box = load(game_id)
        actions = pbp["game"]["actions"]
        ends = possession_ends(actions, {box["homeTeamId"], box["awayTeamId"]})
        total += len(ends)
        slips += sum(1 for (i1, t1), (i2, t2) in zip(ends, ends[1:])
                     if actions[i1]["period"] == actions[i2]["period"] and t1 == t2)
    print(f"{len(games)} games, {total} possession ends, {slips} same-team repeats ({slips / total:.3%})")
    assert slips / total < 0.005, "known limit: a lone free throw where the fouled team keeps the ball"


def test_stint_totals_add_up_to_the_final_score_on_the_opener():
    pbp, box = load("0022500001")
    totals = stint_totals(pbp, box, reconstruct_game(pbp, box))
    home = sum(t.home_points for t in totals)
    away = sum(t.away_points for t in totals)
    print(f"home {home} (official {box['homeTeam']['statistics']['points']}), away {away} (official {box['awayTeam']['statistics']['points']})")
    assert (home, away) == (box["homeTeam"]["statistics"]["points"], box["awayTeam"]["statistics"]["points"])
    assert all(t.home_points >= 0 and t.away_points >= 0 for t in totals)


def test_stale_scores_on_period_rows_are_ignored():
    pbp, box = load("0022500232")  # its end-of-period rows carry a 60-55 score from another moment
    assert audit_points(stint_totals(pbp, box, reconstruct_game(pbp, box)), box) == []


def test_audit_points_reports_missing_points():
    pbp, box = load("0022500001")
    totals = stint_totals(pbp, box, reconstruct_game(pbp, box))
    scoring = next(i for i, t in enumerate(totals) if t.home_points and t.away_points)
    problems = audit_points(totals[:scoring] + totals[scoring + 1:], box)
    print("after dropping a stint where both teams scored:", problems)
    assert len(problems) == 2


def test_every_cached_game_adds_up_to_its_final_score():
    games = cached_games()
    if not games:
        pytest.skip("no cached games")
    failures = {}
    for game_id in games:
        pbp, box = load(game_id)
        problems = audit_points(stint_totals(pbp, box, reconstruct_game(pbp, box)), box)
        if problems:
            failures[game_id] = problems
    print(f"{len(games) - len(failures)}/{len(games)} games add up to the final score")
    for game_id, problems in failures.items():
        print("  ", game_id, problems)
    assert not failures
