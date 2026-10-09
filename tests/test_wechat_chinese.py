"""Chinese client checks using the real cached NBA rates and a full engine game; no mocked APIs."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from hoopformer.game.engine import Game
from hoopformer.game.legends import with_legends
from hoopformer.game.replay import replay_data
from hoopformer.game.levers import lever_limits
from hoopformer.game.server import LiveGame


@pytest.fixture(scope="module")
def chinese_game(fitted):
    model, extras = fitted
    model = with_legends(model, Path("data"))
    codes = {team.tricode: team.team_id for team in model.teams.values()}
    result = Game(model, codes["90S"], codes["00S"], seed=7).play()
    data = replay_data(result, model)
    print("Chinese client real source:", extras["games"], "NBA games; seeded engine events:", len(data["events"]), "final:", data["final"])
    return data


def run_js(game, checks):
    node = os.environ.get("HOOPFORMER_NODE") or shutil.which("node")
    if not node:
        pytest.skip("Node.js required to check the real WeChat JavaScript client")
    script = """
const assert = require('node:assert/strict');
const fs = require('node:fs');
const G = JSON.parse(fs.readFileSync(0, 'utf8'));
const zh = require('./clients/wechat/utils/chinese.js');
const rules = require('./clients/core/court.js').createCourt(G);
const by = rules.playerById;
const ours = G.home.players.slice(0,5).map(p=>p.id), theirs=G.away.players.slice(0,5).map(p=>p.id);
rules.fillRoles(ours,theirs);
""" + checks
    result = subprocess.run([node, "-e", script], input=json.dumps(game), text=True, capture_output=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    assert result.returncode == 0, result.stderr


def test_player_names_preserve_real_identity(chinese_game):
    run_js(chinese_game, """
let translated=0;
for (const player of Object.values(by)) {
  const name=zh.playerName(player.name);
  if (zh.NAMES[player.name]) { assert.equal(name,zh.NAMES[player.name]); translated++; }
  else assert.equal(name,player.name);
}
assert.ok(translated>=20);
console.log('Real classic players translated:',translated,'/',Object.keys(by).length,zh.playerName('Michael Jordan'));
""")


def test_team_names_are_chinese(chinese_game):
    run_js(chinese_game, """
for (const team of [G.home,G.away]) assert.match(zh.teamName(team.tricode),/[\u3400-\u9fff]/);
console.log('Real matchup:',zh.teamName(G.home.tricode),'vs',zh.teamName(G.away.tricode));
""")


def test_all_existing_tactics_roles_and_calls_have_chinese_labels(chinese_game):
    run_js(chinese_game, """
let labels=0;
for (const catalog of [rules.PLAYS,rules.SCHEMES]) for (const [key,tactic] of Object.entries(catalog)) {
  assert.match(zh.label(tactic.name),/[\u3400-\u9fff]/);
  const roles=rules.completeRoles(tactic,{},ours,theirs);
  for (const [role,label] of rules.roleList(tactic,theirs)) { assert.match(zh.label(label),/[\u3400-\u9fff]/); labels++; }
  const phase=catalog===rules.PLAYS?'offense':'defense';
  for (const id of ['team',...ours]) for (const call of rules.callList(phase,id,ours,theirs,rules.controlsOf(tactic,roles))) {
    const before=JSON.stringify(call.raw), translated={...call,label:zh.label(call.label)};
    assert.match(translated.label,/[\u3400-\u9fff]/);
    assert.equal(JSON.stringify(translated.raw),before,'translation must not alter engine levers');
    labels++;
  }
}
for (const kind of Object.keys(rules.STYLE)) assert.match(zh.label(kind),/[\u3400-\u9fff]/);
console.log('Real lineup catalog labels checked:',labels,'; archetypes:',Object.keys(rules.STYLE).length);
""")


def test_helper_uses_the_real_role_holder(chinese_game):
    run_js(chinese_game, r"""
for (const catalog of [rules.PLAYS,rules.SCHEMES]) for (const [key,tactic] of Object.entries(catalog)) {
  const roles=rules.completeRoles(tactic,{},ours,theirs), helper=zh.tacticText(key,roles,by);
  assert.match(helper.name,/[\u3400-\u9fff]/); assert.match(helper.say,/[\u3400-\u9fff]/);
  assert.ok(!helper.say.includes('{')&&!helper.say.includes('undefined'));
  for (const match of zh.TACTICS[key][1].matchAll(/\{\s*(\w+)\s*\}/g)) assert.ok(helper.say.includes(zh.playerName(by[roles[match[1]]].name)));
}
console.log('All',Object.keys(zh.TACTICS).length,'tactic helpers use real assigned players.');
""")


def test_period_labels_follow_actual_events(chinese_game):
    run_js(chinese_game, """
const periods=[...new Set(G.events.map(e=>e.period))];
for (const period of periods) assert.equal(zh.periodLabel(period),period<=4?'第'+period+'节':'加时'+(period-4));
console.log('Real game periods:',periods.map(zh.periodLabel));
""")


def test_chinese_play_by_play_keeps_scores_and_free_throw_counts(chinese_game):
    run_js(chinese_game, """
const kinds=new Set(); let shots=0,freeThrows=0;
for (const event of G.events) {
  if (!event.text) continue;
  const text=zh.eventText(event,by); assert.match(text,/[\u3400-\u9fff]/); kinds.add(event.kind);
  if (event.kind==='shot') { assert.ok(text.includes(event.value?'得'+event.value+'分':'未中')); shots++; }
  if (event.kind==='free_throws') { assert.ok(text.includes('罚球'+event.attempts+'次，命中'+event.value+'次')); freeThrows++; }
}
assert.ok(shots>100&&freeThrows>10);
console.log('Real-rate game narration:',[...kinds],'; shots:',shots,'free throw trips:',freeThrows);
console.log(G.events.filter(e=>e.kind==='shot').slice(0,3).map(e=>zh.eventText(e,by)));
""")


def test_chinese_spoken_calls_use_the_existing_live_catalog(chinese_game):
    run_js(chinese_game, """
const calls=rules.callList('offense','team',ours,theirs,rules.controlsOf(rules.PLAYS.free,rules.tactic.roles)).map(call=>({...call,label:zh.label(call.label)}));
const faster=zh.matchingCall('打快一点。',calls), alias=zh.matchingCall('加快节奏',calls);
assert.ok(faster); assert.deepEqual(alias.raw,faster.raw); assert.equal(faster.raw.team.pace,1);
assert.equal(zh.matchingCall('包夹所有人，每次都进球',calls),null);
const defense=rules.callList('defense','team',ours,theirs,rules.controlsOf(rules.SCHEMES.man,rules.tactic.roles)).map(call=>({...call,label:zh.label(call.label)}));
assert.equal(zh.matchingCall('打快一点',defense),null,'offensive calls must not appear on defense');
console.log('Chinese command:',faster.label,'raw:',faster.raw,'; impossible or unavailable commands remain unmatched.');
""")


def test_chinese_commands_change_the_real_engine(fitted):
    model, _ = fitted
    model = with_legends(model, Path("data"))
    codes = {team.tricode: team.team_id for team in model.teams.values()}
    live = LiveGame(model, lever_limits(Path("data"), "2025-26"), codes["90S"], codes["00S"], seed=8, use="rules")
    result = live.call({"team": {"pace": 1}}, "打快一点", None)
    print("Chinese team call:", result["levers"], "| actual pace:", live.game.home.tactics["pace"])
    assert live.game.home.tactics["pace"] == 0.35
    recipient = live.game.home.lineup[0]
    before = next(p["after"] for p in live.game.monitor(live.game.home)["players"] if p["id"] == recipient)
    result = live.call({"players": [{"person_id": recipient, "aggression": 1}]}, "大胆进攻，找机会出手", recipient)
    after = next(p["after"] for p in live.game.monitor(live.game.home)["players"] if p["id"] == recipient)
    print("Chinese player call:", recipient, result["levers"], "| chance share:", before, "->", after)
    assert live.game.home.player_tactics[recipient]["aggression"] == 0.35 and after > before
    assert any(e.text == "大胆进攻，找机会出手" and e.other == recipient for e in live.game.events if e.kind == "coach")


def test_real_deployment_account_and_voice_plugin_are_consistent():
    root = Path("clients/wechat")
    project = json.loads((root / "project.config.json").read_text())
    app = json.loads((root / "app.json").read_text())
    voice_example = json.loads((root / "app.voice.example.json").read_text())
    print("Deployment target:", project["appid"], project["projectname"], "| voice:", app.get("plugins"))
    assert project["appid"] == "wxc261b766e2ee99f3", "never upload this version to the tourist account or a different Mini Program"
    assert app["plugins"]["WechatSI"] == voice_example["plugins"]["WechatSI"]
    assert app["plugins"]["WechatSI"]["provider"] == "wx069ba97219f66d99"
    assert app["permission"]["scope.record"]["desc"] and app["window"]["navigationBarTitleText"] == "场边教练"


def test_calls_strip_has_no_english_for_real_classic_tactics(fitted):
    model, _ = fitted
    model = with_legends(model, Path("data"))
    codes = {team.tricode: team.team_id for team in model.teams.values()}
    live = LiveGame(model, lever_limits(Path("data"), "2025-26"), codes["90S"], codes["00S"], seed=7, use="rules")
    live.tactics({"play": "pop", "roles": {"handler": 90000056, "screener": 90000165}, "focus": 90000056,
                  "team": {"three_point_rate": .3}}, "挡拆外弹")
    live.game.play()
    run_js(live.data(), r"""
rules.rebuild();
let strips=0;
for (const key of Object.keys(rules.PLAYS)) {
  rules.setTactic('offense',key);rules.fillRoles(ours,theirs);
  for(const plan of rules.plans()) {
    if(!plan.tac)continue;
    for(const [who,what] of rules.callsText(plan)) {
      const text=zh.label(who)+'：'+zh.label(what);
      assert.ok(!/[A-Za-z]/.test(text),text);strips++;
    }
  }
}
const screenshot=zh.label('90S offense')+'：'+zh.label('pick-and-pop Payton–Olajuwon · through Payton');
assert.ok(!/[A-Za-z]/.test(screenshot),screenshot);
console.log('Real classic strips:',strips,'; screenshot wording:',screenshot);
assert.ok(strips>20,'must test actual coached possessions, not an empty call strip');
""")


def test_audio_cues_follow_actual_game_events_and_held_ball(chinese_game):
    run_js(chinese_game, r"""
const {eventSound,dribbleBeat}=require('./clients/wechat/utils/sound.js');
const seen=new Set();
for(const e of G.events) {
 const cue=eventSound(e);if(cue){seen.add(cue);assert.ok(fs.existsSync('./clients/wechat/assets/'+cue+'.wav'));}
 if(e.kind==='shot')assert.equal(cue,e.value?'swish':'rim');
 if(e.kind==='period_end')assert.equal(cue,'buzzer');
}
rules.rebuild();let held=0,air=0,beats=new Set();
for(const plan of rules.plans())for(let t=plan.t0;t<plan.t1;t+=0.1){
 const ball=rules.ballAt(t,plan,rules.positionsIn(plan,t));
 const beat=dribbleBeat(t,ball,true,null);
 if(ball.holder!=null){held++;assert.ok(Number.isInteger(beat));beats.add(beat);}else{air++;assert.equal(beat,null);}
 assert.equal(dribbleBeat(t,ball,false,null),null,'pause is silent');
 assert.equal(dribbleBeat(t,ball,true,{shooter:plan.off[0]}),null,'free throws have no dribble');
}
assert.ok(held>100&&air>100&&beats.size>50);assert.equal(dribbleBeat(0,null,true,null),null);
console.log('Real game audio cues:',[...seen],'; held-ball frames',held,'; airborne frames',air,'; bounce beats',beats.size);
""")


def test_packaged_audio_has_audible_pcm_without_clipping():
    import math
    import struct
    import wave

    for name in ("dribble", "swish", "rim", "whistle", "buzzer"):
        with wave.open(str(Path("clients/wechat/assets") / f"{name}.wav")) as audio:
            assert audio.getsampwidth() == 2 and audio.getnchannels() == 1
            rate, count = audio.getframerate(), audio.getnframes()
            samples = struct.unpack(f"<{count}h", audio.readframes(count))
        peak = max(abs(value) for value in samples)
        rms = math.sqrt(sum(value ** 2 for value in samples) / count) / 32768
        print("Actual audio asset:", name, "seconds", round(count / rate, 3), "peak", peak, "RMS", round(rms, 4))
        assert .08 <= count / rate <= 2 and 500 < peak < 32767 and rms > .008
