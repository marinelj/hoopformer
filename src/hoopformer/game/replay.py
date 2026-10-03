"""Turn a played game into plain data that a replay page can animate.

Times are game seconds since tip-off (overtimes included), so a page can play
the game back at any speed. Team colours are used for jerseys only; no logos.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from hoopformer.game.engine import Event, GameResult, Side
from hoopformer.game.model import ActionModel
from hoopformer.lineups import period_length, period_start

TEAM_COLORS = {
    "ATL": ("#E03A3E", "#C1D32F"), "BOS": ("#007A33", "#BA9653"), "BKN": ("#1A1A1A", "#FFFFFF"),
    "CHA": ("#1D1160", "#00788C"), "CHI": ("#CE1141", "#1A1A1A"), "CLE": ("#860038", "#FDBB30"),
    "DAL": ("#00538C", "#B8C4CA"), "DEN": ("#0E2240", "#FEC524"), "DET": ("#C8102E", "#1D42BA"),
    "GSW": ("#1D428A", "#FFC72C"), "HOU": ("#CE1141", "#C4CED4"), "IND": ("#002D62", "#FDBB30"),
    "LAC": ("#C8102E", "#1D428A"), "LAL": ("#552583", "#FDB927"), "MEM": ("#5D76A9", "#12173F"),
    "MIA": ("#98002E", "#F9A01B"), "MIL": ("#00471B", "#EEE1C6"), "MIN": ("#0C2340", "#78BE20"),
    "NOP": ("#0C2340", "#C8102E"), "NYK": ("#006BB6", "#F58426"), "OKC": ("#007AC1", "#EF3B24"),
    "ORL": ("#0077C0", "#C4CED4"), "PHI": ("#006BB6", "#ED174C"), "PHX": ("#1D1160", "#E56020"),
    "POR": ("#E03A3E", "#1A1A1A"), "SAC": ("#5A2D81", "#63727A"), "SAS": ("#C4CED4", "#1A1A1A"),
    "TOR": ("#CE1141", "#1A1A1A"), "UTA": ("#002B5C", "#F9A01B"), "WAS": ("#002B5C", "#E31837"),
}


def game_seconds(period: int, clock: float) -> float:
    """Seconds since tip-off at a period and clock (seconds left)."""
    return period_start(period) + period_length(period) - clock


def team_data(side: Side, coach: str) -> dict:
    primary, secondary = TEAM_COLORS.get(side.tricode, ("#555555", "#DDDDDD"))
    players = []
    for pid, athlete in side.athletes.items():
        profile = athlete.profile
        players.append({"id": pid, "name": profile.name, "minutesShare": round(side.share[pid], 3),
                        "handler": round(profile.assist, 4), "big": round(profile.dreb, 4)})
    return {"tricode": side.tricode, "name": side.name, "primary": primary, "secondary": secondary,
            "coach": coach, "players": players}


def event_row(event: Event) -> dict:
    """One event as plain data, with its time in game seconds."""
    row = asdict(event)
    row["t"] = round(game_seconds(event.period, event.clock), 1)
    row["home_lineup"] = list(event.home_lineup)
    row["away_lineup"] = list(event.away_lineup)
    return row


def replay_data(result: GameResult, model: ActionModel, home_coach: str = "You", away_coach: str = "AI coach") -> dict:
    """Everything a replay page needs: teams, rosters, colours, and every event with its time and lineups."""
    events = [event_row(event) for event in result.events]
    return {
        "season": model.season if "rates" in model.season else f"{model.season} player rates",
        "seed": result.seed,
        "periods": result.periods,
        "home": team_data(result.home, home_coach),
        "away": team_data(result.away, away_coach),
        "final": {"home": result.home.points, "away": result.away.points},
        "events": events,
    }


TEMPLATE = Path(__file__).parent / "web" / "courtside.html"


def replay_html(data: dict) -> str:
    """The Courtside page with one game's data embedded, ready to open in a browser."""
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.read_text(encoding="utf-8").replace("__GAME_DATA__", payload)
