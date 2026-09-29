"""Fetch raw NBA Stats responses and cache them on disk.

Every response we keep is written unchanged under ``data/raw/`` and recorded in
a manifest with its SHA-256. Any later result can then be traced back to the
exact bytes it was computed from, and re-running a fetch never re-downloads a
game we already have.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests
from nba_api.stats.endpoints import boxscoretraditionalv3, playbyplayv3, scheduleleaguev2
from nba_api.stats.library.http import NBAStatsHTTP

SCHEDULE = "scheduleleaguev2"
PLAY_BY_PLAY = "playbyplayv3"
BOX_SCORE = "boxscoretraditionalv3"

REGULAR_SEASON_PREFIX = "002"  # game ids: 001 preseason, 002 regular season, 004 playoffs
FINAL_STATUS = 3  # schedule gameStatus: 1 scheduled, 2 live, 3 final


class FetchError(RuntimeError):
    """The NBA returned something we must not cache: a timeout, a block page, or bad JSON."""


@dataclass
class SeasonFetchReport:
    season: str
    fetched: int = 0
    cached: int = 0
    failed: list[str] = field(default_factory=list)


def raw_path(data_dir: Path, endpoint: str, key: str) -> Path:
    """Where the raw response for one endpoint call lives, e.g. raw/playbyplayv3/0022500001.json."""
    return data_dir / "raw" / endpoint / f"{key}.json"


def ensure_json(text: str, label: str) -> dict:
    """Parse a response, rejecting anything that isn't JSON.

    stats.nba.com answers suspected bots with HTTP 200 and its homepage HTML, so
    a 200 status alone proves nothing.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise FetchError(f"{label}: response is not JSON, starts with {text[:60]!r}") from exc


def store_raw(data_dir: Path, manifest_path: Path, endpoint: str, key: str, text: str, url: str) -> Path:
    """Write one validated response to disk and append its fingerprint to the manifest."""
    ensure_json(text, f"{endpoint} {key}")
    path = raw_path(data_dir, endpoint, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = text.encode("utf-8")
    partial = path.with_suffix(".json.partial")
    partial.write_bytes(body)
    os.replace(partial, path)  # atomic: a killed download never leaves a half-written file
    record = {
        "path": path.relative_to(data_dir).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("a", encoding="utf-8") as manifest:
        manifest.write(json.dumps(record, sort_keys=True) + "\n")
    return path


def request_with_retries(call: Callable[[], object], label: str, retries: int, backoff: float) -> tuple[str, str]:
    """Run one nba_api endpoint call, retrying timeouts and block pages with growing waits.

    Each attempt starts a fresh HTTP session: stats.nba.com stalls requests that
    reuse an older session (see nba_api issue #633).
    """
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        NBAStatsHTTP.set_session(requests.Session())
        try:
            response = call().nba_response
            text = response.get_response()
            ensure_json(text, label)
            return text, response.get_url()
        except (requests.RequestException, FetchError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(backoff * 3**attempt)
    raise FetchError(f"{label}: failed after {retries + 1} attempts: {last_error}")


def fetch_schedule(
    season: str, data_dir: Path, manifest_path: Path, refresh: bool = False,
    timeout: int = 60, retries: int = 3, backoff: float = 5.0,
) -> Path:
    """Cache a season's full schedule. Use refresh=True for a season still in progress."""
    path = raw_path(data_dir, SCHEDULE, season)
    if path.exists() and not refresh:
        return path
    text, url = request_with_retries(
        lambda: scheduleleaguev2.ScheduleLeagueV2(season=season, timeout=timeout),
        f"{SCHEDULE} {season}", retries, backoff,
    )
    return store_raw(data_dir, manifest_path, SCHEDULE, season, text, url)


def final_regular_season_game_ids(schedule: dict) -> list[str]:
    """Ids of regular-season games that have finished, in id order."""
    games = [game for day in schedule["leagueSchedule"]["gameDates"] for game in day["games"]]
    return sorted(
        game["gameId"] for game in games
        if game["gameId"].startswith(REGULAR_SEASON_PREFIX) and game["gameStatus"] == FINAL_STATUS
    )


def game_dates(data_dir: Path, season: str) -> dict[str, str]:
    """Game id -> date (YYYY-MM-DD) from a cached schedule."""
    schedule = json.loads(raw_path(data_dir, SCHEDULE, season).read_text(encoding="utf-8"))
    return {game["gameId"]: game["gameDateEst"][:10]
            for day in schedule["leagueSchedule"]["gameDates"] for game in day["games"]}


def fetch_game(
    game_id: str, data_dir: Path, manifest_path: Path, delay: float = 1.0,
    timeout: int = 60, retries: int = 3, backoff: float = 5.0,
) -> bool:
    """Cache play-by-play and box score for one game. Returns True if anything was downloaded."""
    calls = {
        PLAY_BY_PLAY: lambda: playbyplayv3.PlayByPlayV3(game_id=game_id, timeout=timeout),
        BOX_SCORE: lambda: boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=game_id, timeout=timeout),
    }
    downloaded = False
    for endpoint, call in calls.items():
        if raw_path(data_dir, endpoint, game_id).exists():
            continue
        text, url = request_with_retries(call, f"{endpoint} {game_id}", retries, backoff)
        store_raw(data_dir, manifest_path, endpoint, game_id, text, url)
        downloaded = True
        time.sleep(delay)
    return downloaded


def fetch_season(
    season: str, data_dir: Path, manifest_path: Path, limit: int | None = None,
    delay: float = 1.0, refresh_schedule: bool = False, log: Callable[[str], None] = print,
) -> SeasonFetchReport:
    """Cache every finished regular-season game of a season. Safe to stop and re-run."""
    schedule_path = fetch_schedule(season, data_dir, manifest_path, refresh=refresh_schedule)
    game_ids = final_regular_season_game_ids(json.loads(schedule_path.read_text(encoding="utf-8")))
    if limit is not None:
        game_ids = game_ids[:limit]
    report = SeasonFetchReport(season)
    for index, game_id in enumerate(game_ids, start=1):
        try:
            if fetch_game(game_id, data_dir, manifest_path, delay=delay):
                report.fetched += 1
                status = "fetched"
            else:
                report.cached += 1
                status = "cached"
        except FetchError as exc:
            report.failed.append(game_id)
            status = f"FAILED ({exc})"
        log(f"{season} {index}/{len(game_ids)} {game_id} {status}")
    return report
