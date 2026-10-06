"""Tests for player archetypes: each player's kind, read from his own numbers (real 2025-26 data and real
career totals for the classic teams)."""

from collections import Counter
from pathlib import Path

import pytest

from hoopformer.game.archetypes import ARCHETYPES, archetypes
from hoopformer.game.legends import LEGEND_ID, TEAMS, cached, with_legends

DATA = Path("data")
KLAY = 202691


def test_archetypes_basketball_fans_would_give_come_out_of_the_data(fitted):
    """Jordan is a two-way scoring dominator, Iverson a high-volume isolation guard, LeBron an all-around point
    forward, Malone a pick-and-roll post bruiser and Klay Thompson a 3-and-D wing: from their numbers alone."""
    if not cached(DATA):
        pytest.skip("classic players not cached: run `uv run hoopformer fetch --legends`")
    model, _ = fitted
    m = with_legends(model, DATA)
    kinds = archetypes(m)
    for _, (code, _, roster) in TEAMS.items():
        print(code, "; ".join(f"{name}: {kinds[LEGEND_ID + pid]}" for pid, name, _ in roster))
    print("Klay Thompson 2025-26:", kinds.get(KLAY))
    expected = {893: "Two-Way Scoring Dominator", 947: "High-Volume Isolation Guard", 2544: "All-Around Point Forward",
                252: "Pick-and-Roll Post Bruiser", 406: "Dominant Post Scorer", 304: "Floor General", 23: "Rebounding Specialist",
                397: "Movement Shooter", 1717: "Stretch Big"}
    for pid, kind in expected.items():
        assert kinds[LEGEND_ID + pid] == kind, (m.players[LEGEND_ID + pid].name, kinds[LEGEND_ID + pid])
    assert kinds[KLAY] == "3-and-D Wing"


def test_every_player_has_one_of_the_archetypes_and_they_are_spread(fitted):
    model, _ = fitted
    kinds = archetypes(model)
    count = Counter(kinds.values())
    print(len(kinds), "players:", dict(count.most_common()))
    assert set(kinds.values()) <= set(ARCHETYPES)
    assert len(count) >= 12, "the league has many kinds of players"
    assert count.most_common(1)[0][1] < 0.5 * len(kinds), "no archetype swallows the league"
