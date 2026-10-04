"""Coach a live game in the browser: a small web server on this computer.

`hoopformer serve` starts it on 127.0.0.1 (nothing outside this Mac can reach it).
The page is Courtside in live mode. It asks for the next possession only when it
has shown the last one, so the game is never more than one possession ahead of
what the coach sees, and whatever the coach says applies from the next possession.

The coach's words go to the server, which calls the translator (the language
model). The API key stays here: the browser never sees it.

Routes:
- GET  /            a new game (query: home, away, seed), as the live page
- GET  /api/next    play the next possession; returns its events
- POST /api/say     {"text", "to"}: translate the words and apply them
- POST /api/timeout call a timeout for the coach's team
- POST /api/tactics {"raw", "words"}: apply the tactics panel's plan (no language model needed)
- POST /api/call    {"raw", "words", "to"}: a call picked from a talk row's list (one step on each lever it names)
"""

from __future__ import annotations

import json
import random
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from hoopformer.game.engine import Game
from hoopformer.game import levers
from hoopformer.game.levers import validate
from hoopformer.game.model import ActionModel
from hoopformer.game.replay import event_row, replay_data, replay_html
from hoopformer.game.translator import RULE_REPLIES, translate

CALL_REPLIES = {**RULE_REPLIES, "rest_minutes": "Okay, taking a breather.", "team_confidence": "Appreciate it, coach!"}
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
            rows.append((abs(ra["after"] - rb["after"]) * 0.5, f"{name}'s chances: {rb['label']} {pct(rb['after'])} → {pct(ra['after'])}"))
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
                 unmapped_log: Path | None = None, boost: float = levers.BOOST):
        self.model, self.use, self.unmapped_log = model, use, unmapped_log
        self.game = Game(model, home, away, seed=seed, limits=limits, boost=boost)  # game mode: calls are felt
        self.lock = threading.Lock()
        self.game.step()  # the tip-off and first possession, so the page opens with players on the floor

    def names(self) -> dict[int, str]:
        return {pid: a.profile.name for side in (self.game.home, self.game.away) for pid, a in side.athletes.items()}

    def page(self) -> str:
        with self.lock:
            data = replay_data(self.game.result(), self.model)
            monitor = self.game.monitor(self.game.home)
        return replay_html({**data, "live": True, "done": self.game.done, "monitor": monitor})

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

    def say(self, text: str, to: int | None) -> dict:
        game = self.game
        addressed = to if to in game.home.athletes else None
        # Outside the lock: the language model takes a few seconds and the game keeps playing meanwhile.
        instruction = translate(text, game, game.home, addressed, use=self.use, unmapped_log=self.unmapped_log)
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
            named = [*(raw.get("team") or {}).items(), *((k, v) for entry in raw.get("players") or [] for k, v in entry.items() if k != "person_id"),
                      *((k, raw[k]) for k in ("focus", "double_team", "late_foul", "timeout", "team_confidence") if raw.get(k))]
            first, value = named[0] if named else (None, None)
            value = value["value"] if isinstance(value, dict) else value
            negative = isinstance(value, (int, float)) and value < 0
            reply = ((PLAYER_REPLIES[first][negative] if addressed is not None and first in PLAYER_REPLIES else None)
                     or (BACKING_OFF.get(first) if negative else None) or CALL_REPLIES.get(first, "Got it, coach."))
            replier = addressed if addressed in side.lineup else (side.lineup[0] if side.lineup else None)
            instruction = validate({**raw, "reply": reply, "replier": replier}, words, set(side.athletes), set(game.away.athletes), addressed, "call")
            def tiring():  # how fast the players this call covers tire, on average (1 = normal)
                who = [addressed] if addressed in side.lineup else side.lineup
                return sum(game.effort(side, p) for p in who) / max(1, len(who))

            before, tired_before = {(d.lever, d.player): d.value for d in side.directives}, tiring()
            events, changes = self.measured(lambda: game.nudge(side, instruction))
            after = {(d.lever, d.player): d.value for d in side.directives}
            moved = {(k, None) for k in instruction.team} | {(k, pid) for pid, values in instruction.players.items() for k in values}
            names, faded = self.names(), []
            for (lever, pid), value in before.items():  # the older calls this one faded, so the coach sees it
                if (lever, pid) in moved or levers.kind(lever, pid) is None or after.get((lever, pid)) == value:
                    continue
                who = f"{names.get(pid, pid)} " if pid else ""
                now = after.get((lever, pid))
                faded.append(f"{who}{lever} {levers.signed(now['value'] if isinstance(now, dict) else now)}" if now is not None else f"{who}{lever} forgotten")
            described = instruction.describe(names) + (f" (fading: {', '.join(faded)})" if faded else "")
            if abs(tiring() - tired_before) > 0.005:  # the call's price in legs
                described += f" · energy use x{tired_before:.2f} → x{tiring():.2f}"
            return {**self.status(events), "levers": described, "reply": instruction.reply, "impact": changes,
                    "replier": instruction.replier, "unmapped": instruction.unmapped}

    def timeout(self) -> dict:
        with self.lock:
            start = len(self.game.events)
            called = self.game.call_timeout(self.game.home, "coach")
            return {**self.status(self.game.events[start:]), "called": called}

    def tactics(self, raw: dict, words: str) -> dict:
        game, side = self.game, self.game.home
        with self.lock:
            # the panel holds the whole plan: drop the previous plan's directives before applying this one
            side.directives = [d for d in side.directives if not d.words.startswith(TACTICS)]
            game._refresh(side)
            instruction = validate(raw, TACTICS + words, set(side.athletes), set(game.away.athletes), None, "tactics panel")
            events, changes = self.measured(lambda: game.instruct(side, instruction))
            return {**self.status(events), "levers": instruction.describe(self.names()), "unmapped": instruction.unmapped, "impact": changes}


class Courtside:
    """What the server knows: the model, the lever limits, and the game being played."""

    def __init__(self, model: ActionModel, limits: dict, home: str, away: str, use: str = "auto",
                 unmapped_log: Path | None = None, boost: float = levers.BOOST):
        self.model, self.limits, self.use, self.unmapped_log, self.boost = model, limits, use, unmapped_log, boost
        self.by_code = {team.tricode: team.team_id for team in model.teams.values()}
        self.home, self.away = home, away
        self.live: LiveGame | None = None

    def new_game(self, home: str | None = None, away: str | None = None, seed: int | None = None) -> LiveGame:
        home, away = (home or self.home).upper(), (away or self.away).upper()
        if home not in self.by_code or away not in self.by_code or home == away:
            raise ValueError(f"unknown or identical teams {home} and {away}")
        seed = random.randrange(1 << 30) if seed is None else seed
        self.live = LiveGame(self.model, self.limits, self.by_code[home], self.by_code[away], seed, self.use, self.unmapped_log, self.boost)
        return self.live


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
            if url.path == "/":
                query = {key: values[0] for key, values in parse_qs(url.query).items()}
                try:
                    live = courtside.new_game(query.get("home"), query.get("away"),
                                              int(query["seed"]) if query.get("seed", "").isdigit() else None)
                except ValueError as exc:
                    self.reply(400, str(exc), "text/plain")
                    return
                self.reply(200, live.page(), "text/html")
            elif url.path == "/api/next" and courtside.live:
                self.answer(courtside.live.next)
            elif url.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
            else:
                self.reply(404, json.dumps({"error": "not found"}))

        def do_POST(self) -> None:
            url = urlparse(self.path)
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            live = courtside.live
            if live is None:
                self.reply(409, json.dumps({"error": "no game: open the page first"}))
            elif url.path == "/api/say":
                self.answer(lambda: live.say(str(body.get("text", "")).strip()[:500], body.get("to")))
            elif url.path == "/api/call":
                self.answer(lambda: live.call(body.get("raw") or {}, str(body.get("words", ""))[:200], body.get("to")))
            elif url.path == "/api/timeout":
                self.answer(live.timeout)
            elif url.path == "/api/tactics":
                self.answer(lambda: live.tactics(body.get("raw") or {}, str(body.get("words", ""))[:300]))
            else:
                self.reply(404, json.dumps({"error": "not found"}))

        def log_message(self, format: str, *args) -> None:  # keep the terminal quiet
            pass

    return Handler


def serve(courtside: Courtside, port: int = 8000) -> ThreadingHTTPServer:
    """A server for this computer only (127.0.0.1). Call serve_forever() on it, or shutdown() to stop."""
    return ThreadingHTTPServer(("127.0.0.1", port), handler_for(courtside))
