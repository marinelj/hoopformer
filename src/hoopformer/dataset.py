"""One row per possession: the input for the transformer (docs/TRANSFORMER_GUIDE.md §2).

Each row holds what is known when a possession starts (the ten players, the
period, the clock, the score margin, who's at home) and what happened (the
points scored, 0-4 where 4 means 4 or more). The lineup is the one on the
floor when the possession ended, the same rule RAPM uses.

Splits are chronological and fixed here, in one place: every model and every
baseline uses the same ones.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from hoopformer.fetch import BOX_SCORE, PLAY_BY_PLAY, SCHEDULE, final_regular_season_game_ids, game_dates, raw_path
from hoopformer.lineups import LineupError, clock_seconds, reconstruct_game
from hoopformer.possessions import game_possessions, scoring_events, stint_at_actions

SPLITS = {
    "2016-17": "train", "2017-18": "train", "2018-19": "train", "2019-20": "train",
    "2020-21": "train", "2021-22": "train", "2022-23": "train", "2023-24": "train",
    "2024-25": "validation",
    "2025-26": "test",
}
MAX_POINTS = 4  # the top class means "4 or more"
KEY = ["game_id", "possession"]  # identifies one row; predictions are joined on it
COLUMNS = (["game_id", "season", "split", "game_date", "possession", "period", "seconds_left", "start_margin", "offense_is_home"]
           + [f"off_{i}" for i in range(5)] + [f"def_{i}" for i in range(5)] + ["points"])


@dataclass
class BuildReport:
    games: int = 0
    rows: int = 0
    missing: list[str] = field(default_factory=list)   # finished games not downloaded
    failed: dict[str, str] = field(default_factory=dict)  # game id -> lineup error


def running_scores(actions: list[dict], home_id: int, away_id: int) -> dict[int, list[int]]:
    """Each team's score after every action, from the same scoring rules that give possession points."""
    running = {}
    for team, scores in scoring_events(actions, home_id, away_id).items():
        points_at = dict(scores)
        total, totals = 0, []
        for index in range(len(actions)):
            total += points_at.get(index, 0)
            totals.append(total)
        running[team] = totals
    return running


def possession_rows(pbp: dict, box: dict, season: str, game_date: str) -> list[dict]:
    """The dataset rows for one game, in game order."""
    home_id, away_id = box["homeTeamId"], box["awayTeamId"]
    actions = pbp["game"]["actions"]
    stints = reconstruct_game(pbp, box)
    stint_at = stint_at_actions(actions, stints)
    possessions, _ = game_possessions(actions, home_id, away_id)

    running = running_scores(actions, home_id, away_id)

    rows = []
    for number, possession in enumerate(possessions):
        offense = possession.team
        defense = away_id if offense == home_id else home_id
        stint = stints[stint_at[possession.end]]
        offense_five, defense_five = (stint.home, stint.away) if offense == home_id else (stint.away, stint.home)
        start = actions[possession.start]
        row = {
            "game_id": box["gameId"],
            "season": season,
            "split": SPLITS.get(season, "unassigned"),
            "game_date": game_date,
            "possession": number,
            "period": start["period"],
            "seconds_left": clock_seconds(start["clock"]),
            "start_margin": running[offense][possession.start] - running[defense][possession.start],
            "offense_is_home": offense == home_id,
            "points": min(possession.points, MAX_POINTS),
        }
        row.update({f"off_{i}": player for i, player in enumerate(sorted(offense_five))})
        row.update({f"def_{i}": player for i, player in enumerate(sorted(defense_five))})
        rows.append(row)
    return rows


def build_dataset(data_dir: Path, seasons: list[str], log=print) -> tuple[pd.DataFrame, BuildReport]:
    """Rows for every downloaded, finished regular-season game of the given seasons."""
    report = BuildReport()
    rows: list[dict] = []
    for season in seasons:
        schedule = json.loads(raw_path(data_dir, SCHEDULE, season).read_text(encoding="utf-8"))
        dates = game_dates(data_dir, season)
        season_rows = 0
        for game_id in final_regular_season_game_ids(schedule):
            pbp_path, box_path = raw_path(data_dir, PLAY_BY_PLAY, game_id), raw_path(data_dir, BOX_SCORE, game_id)
            if not (pbp_path.exists() and box_path.exists()):
                report.missing.append(game_id)
                continue
            pbp = json.loads(pbp_path.read_text(encoding="utf-8"))
            box = json.loads(box_path.read_text(encoding="utf-8"))["boxScoreTraditional"]
            try:
                game = possession_rows(pbp, box, season, dates[game_id])
            except LineupError as exc:
                report.failed[game_id] = str(exc)
                continue
            rows.extend(game)
            season_rows += len(game)
            report.games += 1
        log(f"{season}: {season_rows} possessions")
    report.rows = len(rows)
    frame = pd.DataFrame(rows, columns=COLUMNS)
    return frame, report


def cached_seasons(data_dir: Path) -> list[str]:
    """Seasons whose schedule is downloaded, oldest first."""
    return sorted(path.stem for path in (data_dir / "raw" / SCHEDULE).glob("*.json"))
