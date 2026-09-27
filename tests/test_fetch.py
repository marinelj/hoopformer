"""Tests for the raw-response cache and fetcher.

Offline tests use real files on disk. Tests that need NBA data either read the
local cache (skipped with a reason if it isn't there yet) or are marked
``network`` and hit stats.nba.com; run those on your Mac with
``uv run pytest -m network``.
"""

import hashlib
import json
from pathlib import Path

import pytest

from hoopformer.fetch import (
    BOX_SCORE,
    PLAY_BY_PLAY,
    SCHEDULE,
    FetchError,
    ensure_json,
    fetch_game,
    final_regular_season_game_ids,
    raw_path,
    store_raw,
)

NBA_BLOCK_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>The official site of the NBA | NBA.com</title>
"""


def test_raw_path_groups_files_by_endpoint(tmp_path):
    path = raw_path(tmp_path, PLAY_BY_PLAY, "0022500001")
    print("raw path:", path)
    assert path == tmp_path / "raw" / "playbyplayv3" / "0022500001.json"


def test_store_raw_writes_exact_bytes_and_a_matching_manifest_record(tmp_path):
    manifest = tmp_path / "manifest.jsonl"
    text = '{"game": {"gameId": "0022500001", "actions": [{"actionNumber": 1}]}}'

    path = store_raw(tmp_path, manifest, PLAY_BY_PLAY, "0022500001", text, "https://stats.nba.com/stats/playbyplayv3?GameID=0022500001")

    records = [json.loads(line) for line in manifest.read_text().splitlines()]
    print("stored:", path, "| manifest:", records)
    assert path.read_bytes() == text.encode("utf-8")
    assert len(records) == 1
    assert records[0]["path"] == "raw/playbyplayv3/0022500001.json"
    assert records[0]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert records[0]["bytes"] == len(text.encode("utf-8"))


def test_store_raw_appends_one_record_per_file(tmp_path):
    manifest = tmp_path / "manifest.jsonl"
    store_raw(tmp_path, manifest, PLAY_BY_PLAY, "0022500001", '{"a": 1}', "u1")
    store_raw(tmp_path, manifest, BOX_SCORE, "0022500001", '{"b": 2}', "u2")
    paths = [json.loads(line)["path"] for line in manifest.read_text().splitlines()]
    print("manifest paths:", paths)
    assert paths == ["raw/playbyplayv3/0022500001.json", "raw/boxscoretraditionalv3/0022500001.json"]


def test_store_raw_refuses_the_nba_block_page_and_leaves_no_trace(tmp_path):
    manifest = tmp_path / "manifest.jsonl"
    with pytest.raises(FetchError) as error:
        store_raw(tmp_path, manifest, PLAY_BY_PLAY, "0022500001", NBA_BLOCK_PAGE, "u")
    print("error:", error.value)
    assert "not JSON" in str(error.value)
    assert not raw_path(tmp_path, PLAY_BY_PLAY, "0022500001").exists()
    assert not manifest.exists()


def test_ensure_json_returns_the_parsed_document():
    assert ensure_json('{"resultSets": []}', "label") == {"resultSets": []}


def test_final_regular_season_game_ids_on_the_cached_2025_26_schedule():
    schedule_path = raw_path(Path("data"), SCHEDULE, "2025-26")
    if not schedule_path.exists():
        pytest.skip("no cached schedule yet: run `uv run hoopformer fetch --season 2025-26 --limit 20`")
    game_ids = final_regular_season_game_ids(json.loads(schedule_path.read_text()))
    print("games:", len(game_ids), "| first:", game_ids[0], "| last:", game_ids[-1])
    assert len(game_ids) == 1230, "a completed NBA regular season has 1,230 games"
    assert len(set(game_ids)) == len(game_ids)
    assert all(game_id.startswith("002") for game_id in game_ids)


@pytest.mark.network
def test_fetch_game_downloads_play_by_play_and_box_score(tmp_path):
    manifest = tmp_path / "manifest.jsonl"
    downloaded = fetch_game("0022500001", tmp_path, manifest, delay=1.0)

    pbp = json.loads(raw_path(tmp_path, PLAY_BY_PLAY, "0022500001").read_text())
    box = json.loads(raw_path(tmp_path, BOX_SCORE, "0022500001").read_text())
    actions = pbp["game"]["actions"]
    home = box["boxScoreTraditional"]["homeTeam"]
    print("actions:", len(actions), "| home team:", home["teamTricode"], "| players:", len(home["players"]))
    assert downloaded
    assert len(actions) > 300, "a full NBA game has several hundred play-by-play actions"
    assert len(home["players"]) >= 8
    assert len(manifest.read_text().splitlines()) == 2
    assert fetch_game("0022500001", tmp_path, manifest) is False, "second call must come from the cache"
