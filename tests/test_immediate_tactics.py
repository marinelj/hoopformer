"""Current-chance changes using cached NBA rates, actual HTTP and the shared court. No mocks."""

import json
import os
import shutil
import subprocess
import threading
import urllib.request
from copy import deepcopy
from pathlib import Path

import pytest

from hoopformer.game.levers import lever_limits
from hoopformer.game.replay import event_row
from hoopformer.game.server import Courtside, LiveGame, serve

SGA = 1628983


@pytest.fixture(scope="module")
def setup(fitted):
    model, _ = fitted
    codes = {t.tricode: t.team_id for t in model.teams.values()}
    return model, lever_limits(Path("data"), "2025-26"), codes


def post(base, route, body):
    req = urllib.request.Request(base + route, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.load(res)


def test_http_replaces_only_the_unseen_chance_and_keeps_timeout_and_calls(setup):
    model, limits, _ = setup
    courtside = Courtside(model, limits, "OKC", "BOS", use="rules")
    httpd = serve(courtside, port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/api/new?seed=7") as res:
            client = json.load(res)
        assert client["immediate_tactics"]
        live = courtside.live
        pending = live.pending[0]
        at, shown = pending["state"]["game_seconds"] + pending["seconds"] * .4, pending["shown"]
        prefix = deepcopy(client["events"][:shown])
        post(base, "/api/call", {"raw": {"team": {"pace": 1}}, "words": "打快一点"})
        post(base, "/api/trash", {"text": "你防不住我们！"})
        timeout = post(base, "/api/timeout", {"at": at, "shown": shown})
        assert timeout["called"] and timeout["left"] == 14 and timeout["replace_from"] == shown
        client["events"] = client["events"][:timeout["replace_from"]] + [e for e in timeout["events"] if e["kind"] not in ("coach", "reply")]
        assert sum(e["kind"] == "timeout" and e["zone"] == "coach" for e in client["events"]) == 1
        for key in ("iso", "pnr", "five_out"):
            response = post(base, "/api/tactics", {"at": at, "shown": shown, "raw": {"play": key, "focus": SGA,
                             "roles": {"scorer": SGA}, "team": {"attack_rim": .7}}, "words": key})
            assert response["effective_at"] == at and response["replace_from"] >= shown
            client["events"] = client["events"][:response["replace_from"]] + [e for e in response["events"] if e["kind"] not in ("coach", "reply")]
            assert client["events"][:shown] == prefix, "scores and events already seen cannot change"
            assert response["chance"]["tactics"]["off"]["play"] == key
            assert live.game.home.timeouts == 14
            assert live.game.home.tactics["pace"] > 0, "the earlier sideline call survives the reroll"
            assert sum(e["kind"] == "timeout" and e["zone"] == "coach" for e in client["events"]) == 1
        print("Actual HTTP immediate changes:", at, "prefix", shown, "plays iso → pnr → five_out; timeout 15 →", live.game.home.timeouts)
        print("Current chance:", response["chance"], "| remaining real events:", [(e["kind"], e["actor"]) for e in response["events"]])
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_current_chance_outcome_really_uses_the_new_tactic(setup):
    model, limits, codes = setup
    baseline, coached, changed = 0, 0, 0
    games = 0
    for seed in range(120):
        live = LiveGame(model, limits, codes["OKC"], codes["BOS"], seed, use="rules")
        pending = live.pending[0]
        if pending["state"]["offense"].tricode != "OKC":
            continue
        original = [event_row(e) for e in live.game.events if e.kind in ("shot", "turnover", "free_throws")]
        response = live.tactics({"play": "iso", "focus": SGA, "roles": {"scorer": SGA},
                                "players": [{"person_id": SGA, "aggression": 1, "shot_preference": {"zone": "rim", "value": 1}}]},
                               "亚历山大单打，冲击篮下", pending["state"]["game_seconds"] + pending["seconds"] / 2, pending["shown"])
        new = [e for e in response["events"] if e["kind"] in ("shot", "turnover", "free_throws")]
        baseline += bool(original and original[0]["actor"] == SGA)
        coached += bool(new and new[0]["actor"] == SGA)
        changed += original != new
        games += 1
    print("Actual unfinished OKC chances:", games, "| SGA first actor before:", baseline, "after isolation:", coached, "| outcomes changed:", changed)
    assert games > 40 and coached > baseline + games * .15 and changed > games * .4


def test_replaying_an_unchanged_tactic_keeps_rng_scores_and_box_statistics(setup):
    model, limits, codes = setup
    for seed in (4, 7, 12):
        live = LiveGame(model, limits, codes["OKC"], codes["BOS"], seed, use="rules")
        original = [event_row(e) for e in live.game.events]
        stats = {side.tricode: {pid: dict(a.stats) for pid, a in side.athletes.items()} for side in (live.game.home, live.game.away)}
        pending = live.pending[0]
        response = live.tactics({}, "自由进攻", pending["state"]["game_seconds"] + pending["seconds"] * .3, pending["shown"])
        actual = [event_row(e) for e in live.game.events if e.kind not in ("coach", "reply")]
        assert actual == original
        assert stats == {side.tricode: {pid: dict(a.stats) for pid, a in side.athletes.items()} for side in (live.game.home, live.game.away)}
        assert response["replace_from"] == pending["shown"]
        print("Same real chance replayed unchanged:", seed, "| score", live.game.home.points, live.game.away.points, "| events", len(actual))


def test_replaced_outcome_preserves_every_player_and_ball_at_the_pause(setup):
    node = os.environ.get("HOOPFORMER_NODE") or shutil.which("node")
    if not node:
        pytest.skip("Node required for shared court")
    model, limits, codes = setup
    cases = []
    for seed in range(6):
        live = LiveGame(model, limits, codes["OKC"], codes["BOS"], seed, use="rules")
        old = live.data()
        pending = live.pending[0]
        at = pending["state"]["game_seconds"] + pending["seconds"] * .75
        response = live.tactics({"play": "iso", "scheme": "zone23", "focus": SGA, "roles": {"scorer": SGA},
                                "team": {"protect_paint": .7, "attack_rim": .7}}, "单打和二三联防", at, pending["shown"])
        cases.append({"game": old, "at": at, "response": response})
    script = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),core=require('./clients/core/court.js');
for(const {game:G,at,response} of JSON.parse(fs.readFileSync(0,'utf8'))){
 const r=core.createCourt(G);r.rebuild();const old=r.planAt(at),pos=r.positionsIn(old,at),ball=r.ballAt(at,old,pos);
 r.restartAt(at,true); // the timeout itself establishes the original frozen shape
 r.setTactic(old.offKey==='home'?'offense':'defense',old.offKey==='home'?'iso':'zone23');
 r.fillRoles(old.off,old.def);assert.equal(r.restartAt(at,true),true,'same timeout must accept a new tactic');
 G.events.splice(response.replace_from);G.events[response.chance.index].tactics=response.chance.tactics;
 G.events.push(...response.events.filter(e=>!['coach','reply'].includes(e.kind)));r.rebuild();
 const p=r.planAt(at),now=r.positionsIn(p,at),newBall=r.ballAt(at,p,now);
 for(const id of Object.keys(pos))assert.ok(Math.hypot(now[id].x-pos[id].x,now[id].y-pos[id].y)<1e-6,'paused player jumped '+id);
 assert.ok(Math.hypot(newBall.x-ball.x,newBall.y-ball.y)<1e-6,'paused ball jumped');
 assert.equal(p.t0,at);assert.equal(p.offKey==='home'?p.play:p.scheme,p.offKey==='home'?'iso':'zone23');
 console.log('Actual current chance / preserved positions:',G.seed,at,p.play,p.scheme,Object.keys(now).length);
}
"""
    subprocess.run([node, "-e", script], input=json.dumps(cases), text=True, check=True)


def test_second_chances_and_finished_plays_never_rescore_observed_baskets(setup):
    model, limits, codes = setup
    checked = 0
    for seed in range(30):
        live = LiveGame(model, limits, codes["OKC"], codes["BOS"], seed, use="rules")
        for step in range(100):
            second = next((p for p in live.pending if not p["first"]), None)
            if second:
                at, shown = second["state"]["game_seconds"] + second["seconds"] / 2, second["shown"]
                prefix = [event_row(e) for e in live.game.events[:second["event"]]]
                response = live.tactics({"scheme": "zone23", "team": {"protect_paint": .7}}, "二三联防", at, shown)
                assert [event_row(e) for e in live.game.events[:second["event"]]][:-1] == prefix[:-1]
                assert response["replace_from"] == shown
                assert sum(e.value for e in live.game.events if e.team == "OKC" and e.kind in ("shot", "free_throws")) == live.game.home.points
                assert sum(a.stats["PTS"] for a in live.game.home.athletes.values()) == live.game.home.points
                checked += 1
                break
            live.next()
        if checked >= 5:
            break
    assert checked >= 5
    live = LiveGame(model, limits, codes["OKC"], codes["BOS"], 7, use="rules")
    past = [event_row(e) for e in live.game.events]
    response = live.tactics({"play": "iso", "focus": SGA}, "单打", live.game.game_seconds, len(past))
    assert "replace_from" not in response
    assert [event_row(e) for e in live.game.events[:len(past)]] == past
    print("Already observed baskets and box totals preserved in", checked, "actual offensive-rebound chances and at a finished play.")


def test_late_intentional_foul_continues_without_changing_completed_scores(setup):
    model, limits, codes = setup
    for seed in range(20):
        live = LiveGame(model, limits, codes["OKC"], codes["BOS"], seed, use="rules")
        while not live.game.done:
            g = live.game
            if g.period >= 4 and 3 < g.clock <= 60 and g.offense is g.away and 0 < g.away.points - g.home.points <= 8:
                live.call({"late_foul": True}, "最后时刻主动犯规", None)
                live.next()
                pending = next(p for p in live.pending if p["intentional"])
                prefix = [event_row(e) for e in g.events[:pending["event"]]]
                before = (g.home.points, g.away.points)
                response = live.tactics({}, "继续当前防守", pending["state"]["game_seconds"] + 1, pending["shown"])
                assert [event_row(e) for e in g.events[:pending["event"]]][:-1] == prefix[:-1]
                assert any(e["kind"] == "foul" and e["zone"] == "intentional" for e in response["events"])
                assert (g.home.points, g.away.points) == before
                print("Real late-game intentional foul resumed:", seed, g.period, g.clock, before)
                return
            live.next()
    pytest.fail("no actual close late-game intentional-foul situation found")


def test_invalid_tactic_cannot_truncate_the_unseen_chance(setup):
    model, limits, codes = setup
    live = LiveGame(model, limits, codes["OKC"], codes["BOS"], 7, use="rules")
    original = [event_row(e) for e in live.game.events]
    pending = live.pending[0]
    with pytest.raises(ValueError):
        live.tactics({"roles": ["invalid"]}, "bad roles", 1, pending["shown"])
    with pytest.raises(ValueError):
        live.tactics({}, "bad time", float("nan"), pending["shown"])
    assert [event_row(e) for e in live.game.events] == original
    print("Invalid role/time requests leave all", len(original), "actual events intact.")
