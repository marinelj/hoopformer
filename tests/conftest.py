"""Fixtures shared by the game tests: the action model fitted on the real 2025-26 season."""

from pathlib import Path

import pytest

from hoopformer.fetch import SCHEDULE, raw_path
from hoopformer.game.actions import season_counts
from hoopformer.game.model import fit_action_model

DATA = Path("data")


@pytest.fixture(scope="session")
def fitted():
    """(model, extras), fitted once per test run on every cached 2025-26 game."""
    if not raw_path(DATA, SCHEDULE, "2025-26").exists():
        pytest.skip("2025-26 not downloaded")
    players, teams, extras = season_counts(DATA, "2025-26", log=print)
    if extras["games"] < 300:
        pytest.skip("need at least 300 cached 2025-26 games")
    return fit_action_model(players, teams, extras, "2025-26"), extras
