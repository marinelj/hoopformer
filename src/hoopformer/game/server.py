"""Coach a live game in the browser: a small web server on this computer.

`hoopformer serve` starts it on 127.0.0.1 (nothing outside this Mac can reach it).
The page is Courtside in live mode. It asks for the next possession only when it
has shown the last one, so the game is never more than one possession ahead of
what the coach sees, and whatever the coach says applies from the next possession.

The coach's words go to the server, which calls the translator (the language
model). The API key stays here: the browser never sees it.

Routes:
- GET  /            a new game (query: home, away, seed), as the live page (the web client)
- GET  /api/new     a new game the same way, as data (the WeChat client draws it itself)
- GET  /api/next    play the next possession; returns its events
- POST /api/say     {"text", "to"}: translate the words and apply them
- POST /api/tactics {"raw", "words"}: the coach's tactic: a set play or a defensive scheme, its levers and who
  plays which role (no language model needed)
- POST /api/timeout  the coach's timeout (COACH_TIMEOUTS a game): the page stops at once; in the engine everyone on
  the floor gets a breather before the next possession
- POST /api/call    {"raw", "words", "to"}: a call picked from a talk row's list (one step on each lever it names)
- POST /api/trash   {"text", "from", "to"}: one of our players (or the whole team, from null) talks trash to his man
  (or their whole team, to null); they answer, rattled or fired up, and their confidence moves a little
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from hoopformer.game.engine import TIMEOUTS, Game
from hoopformer.game import levers
from hoopformer.game.levers import validate
from hoopformer.game.model import ActionModel
from hoopformer.game.replay import event_row, replay_data, replay_html
from hoopformer.game.translator import RULE_REPLIES, translate

CALL_REPLIES = {**RULE_REPLIES, "rest_minutes": "Okay, taking a breather.", "team_confidence": "Appreciate it, coach!"}
SET_PLAYS = ("pnr", "pop", "iso", "post", "five_out", "motion", "triangle",  # set plays the court acts out
             "elevator", "horns", "spain", "floppy", "hammer")
SCHEMES = ("drop", "blitz", "zone23", "press", "box1", "switch", "zone131", "tri2")  # defensive schemes (man to man is none)
STOPPABLE = ("double_team",)  # calls that one pick ends at once (they don't fade)
PLAYER_REPLIES = {  # one defender's calls, (+, -)
    "pressure": ("I'll pick him up full court.", "Giving him a little space."),
    "protect_paint": ("Nothing easy at the rim.", "Staying home on my shooter."),
    "box_out": ("Boxing out, every time.", "I'll leak out for the break."),
}
BACKING_OFF = {  # the same levers called the other way
    "pace": "Slowing it down.", "three_point_rate": "Fewer threes, got it.", "attack_rim": "Staying out of the crowd.",
    "ball_security": "Taking more chances.", "crash_glass": "Getting back on D.", "pressure": "Sitting back, no gambling.",
    "protect_paint": "Running them off the line.", "foul_caution": "Getting physical.", "aggression": "Moving it, finding the open man.",
}

TACTICS = "Tactics: "  # how the tactics panel's directives are marked, so a new plan replaces the old one
COACH_TIMEOUTS = 15    # the human coach's timeouts a game (the scripted coaches keep the NBA's 7 and never spend these)
TRASH_BACK = {  # an opponent's answer to trash talk: (rattled, fired up)
    True: ["Man, just play.", "Whatever.", "Get out of my face.", "You talk too much.", "Not now.", "Shut up and guard me."],
    False: ["Keep talking. Watch this.", "You just woke me up.", "Bad idea.", "Say that again after this bucket.",
            "Oh, now I'm locked in.", "Let's go then!"],
}


def impact(before: dict, after: dict, top: int = 3) -> list[str]:
    """The biggest changes between two monitors (before and after a call), in words: what the coach just did."""
    def pct(v):
        return f"{100 * v:.1f}%"

    rows, tiring = [], []  # (how big, text); (who, before, after)
    for key, whose in (("offense", "our chances"), ("defense", "their chances")):
        for b, a in zip(before[key], after[key]):
            if b.get("unit") != "s":
                rows.append((abs(a["after"] - b["after"]), f"{whose}: {b['label']} {pct(b['after'])} → {pct(a['after'])}"))
    for b, a in zip(before["players"], after["players"]):
        if b["id"] != a["id"]:
            continue
        name = b["name"].split()[-1] if not b["name"].endswith(("Jr.", "III", "II")) else b["name"].split()[-2]
        rows.append((abs(a["after"] - b["after"]), f"{name} takes {pct(b['after'])} → {pct(a['after'])} of our chances"))
        for rb, ra in zip(b["offense"], a["offense"]):
            rows.append((abs(ra["after"] - rb["after"]), f"{name}, {rb['label']}: {pct(rb['after'])} → {pct(ra['after'])} of our chances"))
        for rb, ra in zip(b["defense"], a["defense"]):
            rows.append((abs(ra["after"] - rb["after"]) * 0.5, f"{name}'s share {rb['label']} {pct(rb['after'])} → {pct(ra['after'])}"))
        if abs(a["effort"] - b["effort"]) > 0.005:
            tiring.append((name, b["effort"], a["effort"]))
    if len(tiring) > 1 and len({(round(x, 2), round(y, 2)) for _, x, y in tiring}) == 1:  # a team call: one line for all five
        tiring = [("the team", tiring[0][1], tiring[0][2])]
    rows += [(abs(y - x) * 0.05, f"{name} tires ×{x:.2f} → ×{y:.2f}") for name, x, y in tiring]
    rows = sorted((r for r in rows if r[0] >= 0.004), key=lambda r: -r[0])
    return [text for _, text in rows[:top]]


class LiveGame:
    """One game being coached. Steps and instructions take turns through a lock."""

    def __init__(self, model: ActionModel, limits: dict, home: int, away: int, seed: int, use: str = "auto",
                 unmapped_log: Path | None = None, boost: float = levers.BOOST, half_life: float | None = levers.CALL_HALF_LIFE):
        self.model, self.use, self.unmapped_log = model, use, unmapped_log
        self.game_id = uuid.uuid4().hex
        # game mode: calls are felt, and wear off unless repeated
        self.game = Game(model, home, away, seed=seed, limits=limits, boost=boost, half_life=half_life,
                         min_first_seconds=levers.MIN_FIRST_SECONDS if boost != 1 else 0.0,
                         min_second_seconds=levers.MIN_SECOND_SECONDS if boost != 1 else 0.0)
        self.game.home.human, self.game.home.timeouts = True, COACH_TIMEOUTS
        self.lock = threading.Lock()
        self.game.step()  # the tip-off and first possession, so the page opens with players on the floor

    def names(self) -> dict[int, str]:
        return {pid: a.profile.name for side in (self.game.home, self.game.away) for pid, a in side.athletes.items()}

    def data(self, debug: bool = False) -> dict:
        """What a client starts from: the teams and players (with their archetypes), the events so far, the monitor.
        debug: the web page shows the engine's numbers and the explanations too."""
        with self.lock:
            data = replay_data(self.game.result(), self.model)
            monitor = self.game.monitor(self.game.home)
        timeouts = {"home": COACH_TIMEOUTS, "away": TIMEOUTS}   # each team's timeouts at tip-off
        return {**data, "game_id": self.game_id, "live": True, "done": self.game.done, "monitor": monitor, "timeouts": timeouts, "debug": debug}

    def page(self, debug: bool = False) -> str:
        return replay_html(self.data(debug))

    def status(self, events: list) -> dict:
        game = self.game
        return {"events": [event_row(e) for e in events], "done": game.done, "periods": game.period,
                "final": {"home": game.home.points, "away": game.away.points},
                "monitor": game.monitor(game.home)}  # what the coach's directives change, for the page's monitor

    def measured(self, apply) -> tuple[list, list[str]]:
        """Apply an instruction (apply() returns its events) and say what it changed most in the next chance."""
        game = self.game
        if game.done:
            return [], []
        before = game.monitor(game.home)
        events = apply()
        return events, impact(before, game.monitor(game.home))

    def next(self) -> dict:
        with self.lock:
            return self.status(self.game.step())

    def say(self, text: str, to: int | None, provider: str | None = None) -> dict:
        game = self.game
        addressed = to if to in game.home.athletes else None
        # Outside the lock: the language model takes a few seconds and the game keeps playing meanwhile.
        instruction = translate(text, game, game.home, addressed, use=provider or self.use, unmapped_log=self.unmapped_log)
        if "failed:" in instruction.source:
            print(f"language model call failed, used the keyword rules instead: {instruction.source}", flush=True)
        with self.lock:
            events, changes = self.measured(lambda: game.instruct(game.home, instruction))
            return {**self.status(events), "levers": instruction.describe(self.names()), "reply": instruction.reply, "impact": changes,
                    "replier": instruction.replier, "source": instruction.source, "unmapped": instruction.unmapped}

    def call(self, raw: dict, words: str, to: int | None) -> dict:
        """A call picked from the page's list. It is already levers, so no language model is needed; each lever's
        sign says which way it goes, and the engine moves it one step (Game.nudge)."""
        game, side = self.game, self.game.home
        addressed = to if to in side.athletes else None
        with self.lock:
            stop = [k for k in raw.get("stop") or [] if k in STOPPABLE]   # "Man to man" ends the double team
            named = [*(raw.get("team") or {}).items(), *((k, v) for entry in raw.get("players") or [] for k, v in entry.items() if k != "person_id"),
                      *((k, raw[k]) for k in ("focus", "double_team", "late_foul", "team_confidence") if raw.get(k))]
            first, value = named[0] if named else (None, None)
            value = value["value"] if isinstance(value, dict) else value
            negative = isinstance(value, (int, float)) and value < 0
            if stop and first is None:
                reply = "Man to man. Got it."
            elif addressed is not None and first in PLAYER_REPLIES:
                reply = PLAYER_REPLIES[first][negative]
            else:
                reply = (BACKING_OFF.get(first) if negative else None) or CALL_REPLIES.get(first, "Got it, coach.")
            replier = addressed if addressed in side.lineup else (side.lineup[0] if side.lineup else None)
            instruction = validate({**raw, "reply": reply, "replier": replier}, words, set(side.athletes), set(game.away.athletes), addressed, "call")
            def tiring():  # how fast the players this call covers tire, on average (1 = normal)
                who = [addressed] if addressed in side.lineup else side.lineup
                return sum(game.effort(side, p) for p in who) / max(1, len(who))

            def apply():
                if stop:
                    side.directives = [d for d in side.directives if not (d.lever in stop and d.player is None)]
                    game._refresh(side)
                return game.nudge(side, instruction)

            before, tired_before = {(d.lever, d.player): d.value for d in side.directives}, tiring()
            events, changes = self.measured(apply)
            after = {(d.lever, d.player): d.value for d in side.directives}
            moved = {(k, None) for k in instruction.team} | {(k, pid) for pid, values in instruction.players.items() for k in values}
            names, faded = self.names(), []
            for (lever, pid), value in before.items():  # the older calls this one faded, so the coach sees it
                if (lever, pid) in moved or levers.kind(lever, pid) is None or after.get((lever, pid)) == value:
                    continue
                who = f"{names.get(pid, pid)} " if pid else ""
                now = after.get((lever, pid))
                faded.append(f"{who}{lever} {levers.signed(now['value'] if isinstance(now, dict) else now)}" if now is not None else f"{who}{lever} forgotten")
            described = ("double team off" if stop and instruction.lever_count == 0 else instruction.describe(names)) + (f" (fading: {', '.join(faded)})" if faded else "")
            if abs(tiring() - tired_before) > 0.005:  # the call's price in legs
                described += f" · energy use x{tired_before:.2f} → x{tiring():.2f}"
            return {**self.status(events), "levers": described, "reply": instruction.reply, "impact": changes,
                    "replier": instruction.replier, "unmapped": instruction.unmapped}

    def timeout(self) -> dict:
        """The coach's timeout. The page has already stopped; the engine, a possession ahead, gives everyone on the
        floor a breather (Game.call_timeout), so it shows from the next possession, like every call."""
        game = self.game
        with self.lock:
            if game.done or game.home.timeouts <= 0:
                return {**self.status([]), "called": False, "left": game.home.timeouts, "impact": []}
            start = len(game.events)
            events, changes = self.measured(lambda: game.events[start:] if game.call_timeout(game.home, "coach") else [])
            return {**self.status(events), "called": bool(events), "left": game.home.timeouts, "impact": changes}

    def trash(self, text: str, talker: int | None, target: int | None) -> dict:
        """Trash talk from one of our players to his man, or from the whole team to theirs (no language model:
        what is said doesn't matter, who says it to whom does). The one it reached answers."""
        game = self.game
        with self.lock:
            talker = talker if talker in game.home.lineup else None
            done = game.trash_talk(game.home, talker, target)
            names = self.names()

            def last(pid):
                return names[pid].split()[-1]

            reached = done["players"]
            if not reached:
                return {**self.status([]), "reply": None, "replier": None, "rattled": False, "effect": []}
            replier = max(reached, key=lambda r: r["share"][0])["id"]   # his man, or their main scorer for the team
            reply = game.talk_rng.choice(TRASH_BACK[done["rattled"]])
            how = "rattled" if done["rattled"] else "fired up"
            if len(reached) == 1:   # his share of their chances moves with his confidence
                r = reached[0]
                effect = [f"{last(r['id'])} {how}: confidence {r['confidence'][0]:.2f} → {r['confidence'][1]:.2f}, "
                          f"takes {100 * r['share'][0]:.1f}% → {100 * r['share'][1]:.1f}% of their chances"]
            else:   # all five move together, so their shares hardly do
                was, now = (sum(r["confidence"][k] for r in reached) / len(reached) for k in (0, 1))
                effect = [f"{game.away.tricode} {how}: confidence {was:.2f} → {now:.2f} on average, all five"]
            return {**self.status([]), "reply": reply, "replier": replier, "rattled": done["rattled"], "effect": effect,
                    "reached": [r["id"] for r in reached]}

    def tactics(self, raw: dict, words: str) -> dict:
        game, side = self.game, self.game.home
        with self.lock:
            # the panel holds the whole plan: drop the previous plan's directives before applying this one
            side.directives = [d for d in side.directives if not d.words.startswith(TACTICS)]
            game._refresh(side)
            side.play = raw.get("play") if raw.get("play") in SET_PLAYS else None   # what the court acts out
            side.scheme = raw.get("scheme") if raw.get("scheme") in SCHEMES else None
            side.roles = {role: pid for role, pid in (raw.get("roles") or {}).items() if pid in side.athletes}
            if raw.get("stop"):   # man to man: no double team either
                side.directives = [d for d in side.directives if d.lever not in raw["stop"] or d.player is not None]
                game._refresh(side)
            instruction = validate(raw, TACTICS + words, set(side.athletes), set(game.away.athletes), None, "tactic")
            instruction.fades = False   # the tactic holds until the coach changes it
            events, changes = self.measured(lambda: game.instruct(side, instruction))
            return {**self.status(events), "levers": instruction.describe(self.names()), "unmapped": instruction.unmapped, "impact": changes}


class Courtside:
    """What the server knows: the model, the lever limits, and the game being played."""

    def __init__(self, model: ActionModel, limits: dict, home: str, away: str, use: str = "auto",
                 unmapped_log: Path | None = None, boost: float = levers.BOOST, half_life: float | None = levers.CALL_HALF_LIFE,
                 debug: bool = False):
        self.model, self.limits, self.use, self.unmapped_log = model, limits, use, unmapped_log
        self.boost, self.half_life, self.debug = boost, half_life, debug
        self.by_code = {team.tricode: team.team_id for team in model.teams.values()}
        self.home, self.away = home, away
        self.live: LiveGame | None = None
        self.games = OrderedDict()
        self.games_lock = threading.Lock()

    def new_game(self, home: str | None = None, away: str | None = None, seed: int | None = None) -> LiveGame:
        home, away = (home or self.home).upper(), (away or self.away).upper()
        if home not in self.by_code or away not in self.by_code or home == away:
            raise ValueError(f"unknown or identical teams {home} and {away}")
        seed = random.randrange(1 << 30) if seed is None else seed
        live = LiveGame(self.model, self.limits, self.by_code[home], self.by_code[away], seed, self.use, self.unmapped_log,
                        self.boost, self.half_life)
        with self.games_lock:
            self.live = live  # legacy clients without a game id still use the latest game
            self.games[live.game_id] = (time.monotonic(), live)
            while len(self.games) > 32:
                self.games.popitem(last=False)
        return live

    def find_game(self, game_id: str | None) -> LiveGame | None:
        """A browser or phone keeps its own game; unknown ids never fall back to another player."""
        with self.games_lock:
            if not game_id:
                return self.live
            cached = self.games.get(game_id)
            if cached is None:
                return None
            seen, live = cached
            if time.monotonic() - seen > 7200:
                del self.games[game_id]
                return None
            self.games[game_id] = (time.monotonic(), live)
            self.games.move_to_end(game_id)
            return live


def handler_for(courtside: Courtside) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status: int, body: str, kind: str = "application/json") -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", f"{kind}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def answer(self, work) -> None:
            try:
                self.reply(200, json.dumps(work()))
            except Exception as exc:  # the page shows the message; the server keeps running
                self.reply(500, json.dumps({"error": f"{type(exc).__name__}: {exc}"}))

        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path in ("/", "/api/new"):
                query = {key: values[0] for key, values in parse_qs(url.query).items()}
                try:
                    live = courtside.new_game(query.get("home"), query.get("away"),
                                              int(query["seed"]) if query.get("seed", "").isdigit() else None)
                except ValueError as exc:
                    self.reply(400, str(exc), "text/plain")
                    return
                if url.path == "/":
                    self.reply(200, live.page(courtside.debug), "text/html")
                else:
                    self.reply(200, json.dumps(live.data(courtside.debug)))
            elif url.path == "/api/next":
                live = courtside.find_game(parse_qs(url.query).get("game_id", [None])[0])
                if live is None:
                    self.reply(409, json.dumps({"error": "比赛已失效，请重新开始。", "code": "GAME_EXPIRED"}))
                else:
                    self.answer(live.next)
            elif url.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
            else:
                self.reply(404, json.dumps({"error": "not found"}))

        def do_POST(self) -> None:
            url = urlparse(self.path)
            try:
                size = int(self.headers.get("Content-Length") or 0)
                if size < 0 or size > 65536:
                    raise ValueError("invalid body size")
                body = json.loads(self.rfile.read(size) or b"{}")
                if not isinstance(body, dict) or ("raw" in body and not isinstance(body["raw"], dict)):
                    raise ValueError("expected a JSON object")
            except (ValueError, TypeError):
                self.reply(400, json.dumps({"error": "指令格式不正确，请重新选择。"}))
                return
            live = courtside.find_game(parse_qs(url.query).get("game_id", [None])[0])
            if live is None:
                self.reply(409, json.dumps({"error": "比赛已失效，请重新开始。", "code": "GAME_EXPIRED"}))
            elif url.path == "/api/say":
                text, to = str(body.get("text", "")).strip()[:500], body.get("to")
                if body.get("provider") == "qwen":
                    if not os.environ.get("DASHSCOPE_API_KEY"):
                        self.reply(503, json.dumps({"error": "云端千问尚未配置，请设置 DASHSCOPE_API_KEY。", "code": "QWEN_NOT_CONFIGURED"}))
                        return
                    key = os.environ["DASHSCOPE_API_KEY"]
                    if not key.isascii() or any(char.isspace() for char in key):
                        self.reply(503, json.dumps({"error": "千问密钥格式不正确，请重新复制控制台 API Key。", "code": "QWEN_INVALID_KEY"}))
                        return
                    try:
                        self.reply(200, json.dumps(live.say(text, to, provider="qwen")))
                    except requests.Timeout:
                        self.reply(503, json.dumps({"error": "千问响应超时，请重试。", "code": "QWEN_TIMEOUT"}))
                    except requests.ConnectionError:
                        self.reply(503, json.dumps({"error": "云端连接千问失败，请重试。", "code": "QWEN_UNREACHABLE"}))
                    except (requests.RequestException, RuntimeError, ValueError, KeyError, TypeError):
                        self.reply(503, json.dumps({"error": "千问调用失败，请检查云端密钥、模型权限与额度。", "code": "QWEN_CALL_FAILED"}))
                else:
                    self.answer(lambda: live.say(text, to))
            elif url.path == "/api/call":
                self.answer(lambda: live.call(body.get("raw") or {}, str(body.get("words", ""))[:200], body.get("to")))
            elif url.path == "/api/tactics":
                self.answer(lambda: live.tactics(body.get("raw") or {}, str(body.get("words", ""))[:300]))
            elif url.path == "/api/timeout":
                self.answer(live.timeout)
            elif url.path == "/api/trash":
                self.answer(lambda: live.trash(str(body.get("text", "")).strip()[:300], body.get("from"), body.get("to")))
            else:
                self.reply(404, json.dumps({"error": "not found"}))

        def log_message(self, format: str, *args) -> None:  # keep the terminal quiet
            pass

    return Handler


def serve(courtside: Courtside, port: int = 8000, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """A server for this computer only (127.0.0.1), or for the local network too (host 0.0.0.0: a phone running the
    WeChat client). Call serve_forever() on it, or shutdown() to stop."""
    return ThreadingHTTPServer((host, port), handler_for(courtside))
