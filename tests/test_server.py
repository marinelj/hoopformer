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


def test_a_tactic_with_roles_and_substitutions(server):
    base, courtside = server
    get(f"{base}/?seed=8")
    for _ in range(5):
        get(f"{base}/api/next")
    game = courtside.live.game
    bench = next(pid for pid in game.home.athletes if pid not in game.home.lineup)
    out = next(pid for pid in game.home.lineup if pid != SGA)
    swap = post(f"{base}/api/call", {"raw": {"substitutions": [{"in": bench, "out": out}]}, "words": "sub", "to": None})
    print(swap["levers"])
    assert bench in game.home.lineup and out not in game.home.lineup, "a substitution between possessions"
    screener = next(pid for pid in game.home.lineup if pid != SGA)
    plan = post(f"{base}/api/tactics", {"raw": {"team": {"attack_rim": 0.4}, "focus": SGA, "play": "pnr", "scheme": "zone23",
                                                "roles": {"handler": SGA, "screener": screener}}, "words": "Pick-and-roll"})
    print(plan["levers"], "|", plan["impact"])
    assert game.home.play == "pnr" and game.home.scheme == "zone23" and game.home.roles == {"handler": SGA, "screener": screener}
    events = [e for _ in range(6) for e in json.loads(get(f"{base}/api/next")[1])["events"] if e["kind"] == "chance"]
    ours = [e["tactics"]["off"] for e in events if e["team"] == "OKC" and e["tactics"]]
    theirs = [e["tactics"]["def"] for e in events if e["team"] == "BOS" and e["tactics"]]
    print("OKC chances carry:", ours[:1], "| BOS chances face:", theirs[:1])
    assert ours and all(o["play"] == "pnr" and o["roles"].get("handler") in (SGA, None) for o in ours), "the court sees the play and its roles"
    assert theirs and all(d["scheme"] == "zone23" for d in theirs), "and the scheme"
    post(f"{base}/api/tactics", {"raw": {"team": {"protect_paint": 0.7}}, "words": "zone"})
    assert game.home.tactics == {"protect_paint": 0.7} and game.home.play is None, "a new tactic replaces the old one"


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
    assert team["levers"] == "pace +0.35 · energy use x1.00 → x1.21", "and what the call costs in legs (boosted in the live game)"
    print("impact of a press:", post(f"{base}/api/call", {"raw": {"team": {"pressure": 1}}, "words": "Press", "to": None})["impact"])
    assert courtside.live.game.boost == 5.0 and team["impact"], "the live game is the boosted one, and every call says what it changed"
    shown = {(d["lever"], d["player_id"]) for d in threes["monitor"]["directives"]}
    print("in force:", shown)
    assert shown == {("pace", None), ("shot_preference", SGA), ("three_point_rate", None)}, "the page reads each call's player to show where it stands"
    tatum = next(pid for pid, a in game.away.athletes.items() if a.profile.name == "Jayson Tatum")
    post(f"{base}/api/call", {"raw": {"double_team": tatum}, "words": "Double-team Tatum", "to": None})
    assert game.home.double_team == tatum
    straight = post(f"{base}/api/call", {"raw": {"stop": ["double_team"]}, "words": "Man to man", "to": None})
    print(straight["levers"], "|", straight["reply"], "|", straight["impact"])
    assert game.home.double_team is None and straight["levers"].startswith("double team off") and straight["reply"] == "Man to man. Got it."
    before = game.home.timeouts
    timeout = post(f"{base}/api/call", {"raw": {"timeout": True}, "words": "Timeout!", "to": None})
    assert game.home.timeouts == before - 1 and "timeout" in [e["kind"] for e in timeout["events"]]



def test_trash_talk_reaches_his_man_who_answers(server):
    base, courtside = server
    get(f"{base}/?home=OKC&away=BOS&seed=11")
    game = courtside.live.game
    tatum = next(pid for pid, a in game.away.athletes.items() if a.profile.name == "Jayson Tatum")
    before = game.away.athletes[tatum].confidence
    talk = post(f"{base}/api/trash", {"text": "You can't guard me", "from": SGA, "to": tatum})
    print(talk["reply"], "|", talk["rattled"], "|", talk["effect"])
    assert talk["replier"] == tatum and talk["reached"] == [tatum] and talk["reply"]
    assert game.away.athletes[tatum].confidence == pytest.approx(before + (-0.05 if talk["rattled"] else 0.05))
    assert talk["effect"][0].startswith("Tatum rattled: confidence" if talk["rattled"] else "Tatum fired up: confidence")
    team = post(f"{base}/api/trash", {"text": "Nobody over there can play", "from": None, "to": None})
    print(team["reply"], "|", team["effect"])
    assert len(team["reached"]) == 5 and team["replier"] in team["reached"] and team["effect"][0].startswith("BOS ")



def test_the_coach_has_fifteen_timeouts_and_each_is_a_breather(server):
    base, courtside = server
    get(f"{base}/?home=OKC&away=BOS&seed=12")
    game = courtside.live.game
    assert game.home.timeouts == 15 and game.home.human and not game.away.human
    for _ in range(6):
        get(f"{base}/api/next")
    legs = {pid: game.home.athletes[pid].energy for pid in game.home.lineup}
    first = post(f"{base}/api/timeout", {})
    print("timeout:", first["called"], first["left"], "left |", [(e["kind"], e["zone"], e["text"]) for e in first["events"]])
    print("energy:", {pid: f"{legs[pid]:.3f} -> {game.home.athletes[pid].energy:.3f}" for pid in legs})
    assert first["called"] and first["left"] == 14 and [(e["kind"], e["zone"]) for e in first["events"]] == [("timeout", "coach")]
    assert all(game.home.athletes[pid].energy >= legs[pid] for pid in legs) and any(game.home.athletes[pid].energy > legs[pid] for pid in legs)
    game.home.timeouts = 1
    assert post(f"{base}/api/timeout", {})["left"] == 0
    out = post(f"{base}/api/timeout", {})
    assert not out["called"] and out["events"] == [], "none left: nothing happens"


def test_bad_requests_are_refused(server):
    base, _ = server
    with pytest.raises(urllib.error.HTTPError) as error:
        get(f"{base}/?home=XXX")
    assert error.value.code == 400
    with pytest.raises(urllib.error.HTTPError) as error:
        get(f"{base}/api/nothing")
    assert error.value.code == 404
