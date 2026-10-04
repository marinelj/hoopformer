"""Tests for the live game server: a real server on a free local port, real HTTP, the real engine.

Coaching here uses the keyword rules, so the tests need no API key and no network
beyond this computer.
"""

import json
import threading
import urllib.request
from pathlib import Path

import pytest

from hoopformer.game.levers import measure_limits
from hoopformer.game.server import Courtside, serve

DATA = Path("data")
SGA = 1628983


@pytest.fixture(scope="module")
def server(fitted):
    model, _ = fitted
    courtside = Courtside(model, measure_limits(DATA, "2025-26"), "OKC", "BOS", use="rules")
    httpd = serve(courtside, port=0)  # port 0: any free port
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", courtside
    httpd.shutdown()
    httpd.server_close()


def get(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.status, response.read().decode("utf-8")


def post(url, body):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def test_the_page_is_a_live_game_with_the_tip_off_in_it(server):
    base, courtside = server
    status, page = get(f"{base}/?home=OKC&away=BOS&seed=5")
    data = json.loads(page.split('<script id="game-data" type="application/json">')[1].split("</script>")[0].replace("<\\/", "</"))
    print(status, data["home"]["tricode"], data["away"]["tricode"], len(data["events"]), "events at the start")
    assert status == 200 and data["live"] is True and data["done"] is False and data["seed"] == 5
    assert data["events"][0]["kind"] == "period_start" and len(data["events"]) >= 2


def test_possessions_arrive_one_at_a_time_until_the_final_buzzer(server):
    base, courtside = server
    get(f"{base}/?seed=6")
    steps, events, last_t = 0, [], 0.0
    while True:
        status, body = get(f"{base}/api/next")
        data = json.loads(body)
        steps += 1
        events += data["events"]
        assert all(e["t"] >= last_t for e in data["events"]), "events come in time order"
        last_t = data["events"][-1]["t"] if data["events"] else last_t
        if data["done"]:
            break
        assert steps < 400
    result = courtside.live.game.result()
    print(steps, "requests,", len(events), "events, final", data["final"])
    assert data["final"] == {"home": result.home.points, "away": result.away.points} and data["final"]["home"] != data["final"]["away"]
    assert json.loads(get(f"{base}/api/next")[1])["events"] == [], "after the buzzer there's nothing more"


def test_words_change_the_game_from_the_next_possession(server):
    base, courtside = server
    get(f"{base}/?seed=7")
    for _ in range(10):
        get(f"{base}/api/next")
    data = post(f"{base}/api/say", {"text": "Be more aggressive, look for your shot.", "to": SGA})
    print(data["levers"], "|", data["source"], "|", data["reply"])
    assert data["source"] == "rules" and "aggression +0.6" in data["levers"] and data["replier"] == SGA
    assert courtside.live.game.home.player_tactics[SGA] == {"aggression": 0.6}
    sga_row = next(p for p in data["monitor"]["players"] if p["id"] == SGA)
    print("monitor, SGA's share of chances:", round(sga_row["before"], 3), "->", round(sga_row["after"], 3))
    assert sga_row["after"] > sga_row["before"] and data["monitor"]["directives"][0]["words"]
    team = post(f"{base}/api/say", {"text": "Push the pace!", "to": None})
    assert courtside.live.game.home.tactics == {"pace": 0.6} and "pace +0.6" in team["levers"]


def test_timeout_and_the_tactics_panel(server):
    base, courtside = server
    get(f"{base}/?seed=8")
    for _ in range(5):
        get(f"{base}/api/next")
    timeout = post(f"{base}/api/timeout", {})
    assert timeout["called"] and [e["kind"] for e in timeout["events"]] == ["timeout"]
    game = courtside.live.game
    bench = next(pid for pid in game.home.athletes if pid not in game.home.lineup)
    out = game.home.lineup[0]
    plan = post(f"{base}/api/tactics", {"raw": {"team": {"pressure": 0.8}, "substitutions": [{"in": bench, "out": out}]}, "words": "press"})
    print(plan["levers"])
    assert game.home.tactics == {"pressure": 0.8} and bench in game.home.lineup
    post(f"{base}/api/tactics", {"raw": {"team": {"protect_paint": 0.7}}, "words": "zone"})
    assert game.home.tactics == {"protect_paint": 0.7}, "a new plan replaces the old one"
    print(game.home.timeouts, "timeouts left")
    assert game.home.timeouts == 6


def test_calls_from_the_list_need_no_language_model_and_stack(server):
    base, courtside = server
    get(f"{base}/?seed=9")
    for _ in range(6):
        get(f"{base}/api/next")
    game = courtside.live.game
    team = post(f"{base}/api/call", {"raw": {"team": {"pace": 1}}, "words": "Push the pace", "to": None})
    again = post(f"{base}/api/call", {"raw": {"team": {"pace": 1}}, "words": "Push the pace", "to": None})
    print(team["levers"], "|", team["reply"], "||", again["levers"])
    assert game.home.tactics == {"pace": 0.7} and team["reply"] == "Pushing it, coach." and not team["unmapped"]
    slower = post(f"{base}/api/call", {"raw": {"team": {"pace": -1}}, "words": "Slow it down", "to": None})
    print(slower["levers"], "|", slower["reply"])
    assert game.home.tactics == {"pace": 0.35} and slower["reply"] == "Slowing it down."
    player = post(f"{base}/api/call", {"raw": {"players": [{"person_id": SGA, "shot_preference": {"zone": "rim", "value": 1}}]},
                                       "words": "Get to the rim", "to": SGA})
    assert game.home.player_tactics[SGA] == {"shot_preference": {"zone": "rim", "value": 0.35}} and player["replier"] == SGA
    threes = post(f"{base}/api/call", {"raw": {"team": {"three_point_rate": 1}}, "words": "Let it fly from three", "to": None})
    print(threes["levers"])
    assert threes["levers"].startswith("three_point_rate +0.35 (fading: pace +0.24)"), "the note says which older call faded"
    assert team["levers"] == "pace +0.35 · energy use x1.00 → x1.07", "and what the call costs in legs"
    shown = {(d["lever"], d["player_id"]) for d in threes["monitor"]["directives"]}
    print("in force:", shown)
    assert shown == {("pace", None), ("shot_preference", SGA), ("three_point_rate", None)}, "the page reads each call's player to show where it stands"
    before = game.home.timeouts
    timeout = post(f"{base}/api/call", {"raw": {"timeout": True}, "words": "Timeout!", "to": None})
    assert game.home.timeouts == before - 1 and "timeout" in [e["kind"] for e in timeout["events"]]


def test_bad_requests_are_refused(server):
    base, _ = server
    with pytest.raises(urllib.error.HTTPError) as error:
        get(f"{base}/?home=XXX")
    assert error.value.code == 400
    with pytest.raises(urllib.error.HTTPError) as error:
        get(f"{base}/api/nothing")
    assert error.value.code == 404
