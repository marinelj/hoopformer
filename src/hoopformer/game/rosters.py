"""This season's rosters with last season's player rates.

Before a season starts, the best guess of how a player plays is how they
played last season, wherever they play now. So the game takes the action
model fitted on last season and moves every player to their current team.
Players with no minutes last season (rookies, players back from injury or
from abroad) start as league-average role players: shrinkage with no data
gives exactly the league rates, and they get NEWCOMER_MINUTES a game until
real games say otherwise.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from hoopformer.fetch import ROSTER
from hoopformer.game.model import ActionModel, PlayerProfile

NEWCOMER_MINUTES = 10.0
NEWCOMER_GAMES = 10  # enough that the minutes aren't scaled down again (engine.SETTLED_GAMES)


def season_rosters(data_dir: Path, season: str) -> dict[int, list[dict]]:
    """Team id -> players on the cached roster: person id, name, and whether they're a rookie."""
    rosters = {}
    for path in sorted((data_dir / "raw" / ROSTER).glob(f"{season}_*.json")):
        table = next(t for t in json.loads(path.read_text(encoding="utf-8"))["resultSets"] if t["name"] == "CommonTeamRoster")
        rows = [dict(zip(table["headers"], row)) for row in table["rowSet"]]
        team_id = int(path.stem.split("_")[1])
        rosters[team_id] = [{"person_id": row["PLAYER_ID"], "name": row["PLAYER"], "rookie": row["EXP"] == "R"} for row in rows]
    return rosters


def newcomer(model: ActionModel, person_id: int, name: str, team_id: int) -> PlayerProfile:
    """A player with no minutes last season: the league's average rates."""
    league = model.league
    return PlayerProfile(
        person_id=person_id, name=name, team_id=team_id, games=NEWCOMER_GAMES, minutes_per_game=NEWCOMER_MINUTES,
        events=dict(league.event_rate), make=dict(league.make), assisted=dict(league.assisted), ft_pct=league.ft_pct,
        assist=league.assist_rate, oreb=league.oreb_rate, dreb=league.dreb_rate, steal=league.steal_rate,
        block=league.block_rate, foul=league.foul_rate,
    )


def with_rosters(model: ActionModel, rosters: dict[int, list[dict]], season: str) -> ActionModel:
    """The model with every rostered player on their current team, and nobody else."""
    players = {}
    for team_id, roster in rosters.items():
        for player in roster:
            pid = player["person_id"]
            known = model.players.get(pid)
            players[pid] = replace(known, team_id=team_id) if known else newcomer(model, pid, player["name"], team_id)
    return replace(model, season=f"{model.season} rates, {season} rosters", players=players)
