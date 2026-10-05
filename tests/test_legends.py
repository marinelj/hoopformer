"""Tests for the classic teams: real career totals (stats.nba.com) turned into engine rates."""

from pathlib import Path

import pytest

from hoopformer.game.engine import Game
from hoopformer.game.legends import LEGEND_ID, NINETIES, TWO_THOUSANDS, cached, season_totals, with_legends

DATA = Path("data")
pytestmark = pytest.mark.skipif(not cached(DATA), reason="classic players not cached: run `uv run hoopformer fetch --legends`")


def test_season_totals_are_the_famous_seasons():
    jordan, stockton = season_totals(DATA, 893, "1995-96"), season_totals(DATA, 304, "1993-94")
    print("Jordan 1995-96:", jordan["PTS"], "points in", jordan["GP"], "games; Stockton 1993-94:", stockton["AST"], "assists")
    assert jordan["TEAM_ABBREVIATION"] == "CHI" and round(jordan["PTS"] / jordan["GP"], 1) == 30.4
    assert round(stockton["AST"] / stockton["GP"], 1) == 12.6


def test_classic_players_keep_their_style(fitted):
    model, _ = fitted
    m = with_legends(model, DATA)
    p = {m.players[LEGEND_ID + pid].name: m.players[LEGEND_ID + pid] for pid in (893, 304, 23, 406, 397)}
    for name, prof in p.items():
        print(f"{name:18s} rim {prof.events['rim']:.3f} mid {prof.events['mid']:.3f} three {prof.events['three']:.3f} "
              f"| makes {prof.make['rim']:.2f}/{prof.make['mid']:.2f}/{prof.make['three']:.2f} | assist {prof.assist:.2f} dreb {prof.dreb:.2f}")
    assert p["Shaquille O'Neal"].events["three"] < 0.001 and p["Shaquille O'Neal"].events["rim"] > p["Shaquille O'Neal"].events["mid"]
    assert p["Reggie Miller"].events["three"] > 1.4 * p["Michael Jordan"].events["three"], "Miller took 1.6x the threes per minute"
    assert p["John Stockton"].assist > 2 * p["Michael Jordan"].assist, "Stockton passed"
    rodman, shaq = p["Dennis Rodman"], p["Shaquille O'Neal"]
    assert rodman.oreb > 1.4 * shaq.oreb and rodman.dreb > 1.1 * shaq.dreb, "Rodman out-rebounded even Shaq, most of all on the offensive glass"


def test_the_90s_and_the_2000s_play_a_real_game(fitted):
    model, _ = fitted
    m = with_legends(model, DATA)
    scores = [Game(m, NINETIES, TWO_THOUSANDS, seed=seed).play() for seed in range(60)]
    home = sum(r.home.points for r in scores) / 60
    away = sum(r.away.points for r in scores) / 60
    wins = sum(r.home.points > r.away.points for r in scores)
    print(f"1990s All-Stars {home:.1f} - 2000s All-Stars {away:.1f}, the 90s win {wins} of 60")
    assert 95 < home < 135 and 95 < away < 135 and 10 < wins < 50, "a close game between two great teams"
