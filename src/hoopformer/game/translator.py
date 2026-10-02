"""The translator: a coach's free words in, levers out.

Two translators share one output format (see `SYSTEM`):
- `ask_qwen`: an LLM (Qwen, through Alibaba Cloud Model Studio's OpenAI-compatible
  API) with JSON output. One call per instruction, never one per decision.
- `ask_rules`: keyword rules, no network. It's the baseline the LLM has to beat
  (the same idea as B0-B2 for the transformer) and the fallback when the API is down.

Either way the output goes through `levers.validate`, which clamps every value and
sends anything that doesn't fit to `unmapped`. Unmapped phrases are logged: the
most frequent ones decide which lever gets built next.

The API key comes from the environment (DASHSCOPE_API_KEY) or a git-ignored .env
file. It is never printed, logged or written anywhere.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from hoopformer.game.engine import Game, Side
from hoopformer.game.levers import PLAYER_LEVERS, TEAM_LEVERS, Instruction, validate
from hoopformer.lineups import plain

DEFAULT_MODEL = "qwen3.8-max"  # Qwen's most capable model (Qwen3.8-Max, August 2026)
DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"  # Model Studio, international (Singapore)
PHRASES = Path(__file__).parent / "coach_phrases.json"                  # 50 phrases the rules were written against
HOLDOUT_PHRASES = Path(__file__).parent / "coach_phrases_holdout.json"  # 30 written afterwards, never used to tune

SYSTEM = f"""You turn a basketball coach's words into engine levers for a simulated NBA game.
Reply with one JSON object and nothing else, with these keys (leave out what the coach didn't ask for):

"team": object, team levers, each a number from -1 to 1 (1 = as far as the most extreme real NBA team goes):
  pace (+ play fast, - slow down), three_point_rate (+ more threes, - fewer), attack_rim (+ drive, get to the rim and the line),
  ball_security (+ fewer turnovers), crash_glass (+ chase offensive rebounds, - get back in transition),
  pressure (+ pressure the ball, trap, press), protect_paint (+ pack the paint / zone, - run shooters off the line),
  foul_caution (+ stop fouling, - get physical)
"players": list of objects for the coach's own players: {{"person_id": id, "aggression": -1..1, "shot_preference": {{"zone": "rim"|"mid"|"three", "value": -1..1}},
  "foul_caution": -1..1, "rest_minutes": minutes on the bench (0 = until the coach says otherwise), "confidence": -1..1 (praise +, criticism -)}}
"focus": person_id of one own player to run the offense through
"double_team": person_id of one opponent to double-team
"late_foul": true to foul on purpose when trailing late
"timeout": true to call a timeout now
"substitutions": list of {{"in": person_id, "out": person_id}} for the coach's own players
"team_confidence": -1..1 when the coach praises (+) or criticizes (-) the whole team
"duration": "game" (default), "quarter", or "possessions" with "possessions": N
"reply": one short sentence from the player addressed (or a leader on the floor) acknowledging the instruction,
  in a player's voice. Never promise a result ("we'll win", "I'll score"); only acknowledge what they'll try.
"replier": person_id of who replies
"unmapped": list of the coach's phrases that none of these levers can express (quote them), e.g. "box out", "switch everything",
  "make every shot". For an impossible request, map the closest real lever if one fits and still list the phrase.

Rules: use only person_ids from the lists you are given. "Him/her/you" means the player the coach is addressing.
Typical strengths: a plain request 0.5, an emphatic one ("every time", "all game", "!!") 0.8-1.
Team levers: {", ".join(TEAM_LEVERS)}. Player levers: {", ".join(PLAYER_LEVERS)}, rest_minutes, confidence."""


def load_env(path: Path = Path(".env")) -> None:
    """Read KEY=value lines from a git-ignored .env file into the environment (without overriding)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def context_for(game: Game, side: Side, addressed: int | None) -> dict:
    """What the translator needs to know: who's who, the score, the time and what's already in force."""
    other = game.other(side)
    minutes, seconds = divmod(int(game.clock), 60)

    def players(team: Side, own: bool) -> list[dict]:
        rows = []
        for pid, athlete in team.athletes.items():
            row = {"person_id": pid, "name": athlete.profile.name, "on_floor": pid in team.lineup, "points": athlete.stats["PTS"]}
            if own:
                row.update(fouls=athlete.stats["PF"], energy=round(athlete.energy, 2))
            rows.append(row)
        return rows

    return {
        "you_coach": side.name, "opponent": other.name,
        "score": {"us": side.points, "them": other.points}, "period": game.period, "clock": f"{minutes}:{seconds:02d}",
        "addressed_to": ({"person_id": addressed, "name": side.athletes[addressed].profile.name} if addressed else "the whole team"),
        "your_players": players(side, True), "opponents": players(other, False),
        "in_force": [{"lever": d.lever, "value": d.value, "player": d.player, "words": d.words} for d in side.directives],
    }


def ask_qwen(words: str, context: dict, model: str | None = None, timeout: float = 30.0) -> tuple[dict, str]:
    """One call to Qwen with JSON output. Returns (raw output, model name)."""
    key = os.environ.get("DASHSCOPE_API_KEY")
    if not key:
        raise RuntimeError("DASHSCOPE_API_KEY is not set (put it in your shell profile or a git-ignored .env)")
    model = model or os.environ.get("QWEN_MODEL", DEFAULT_MODEL)
    base_url = os.environ.get("QWEN_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": json.dumps({"context": context, "coach_says": words}, ensure_ascii=False)}],
        "response_format": {"type": "json_object"},
        "enable_thinking": False,  # strict JSON and a fast answer; thinking mode isn't needed for this
        "temperature": 0.1,
    }
    response = requests.post(f"{base_url}/chat/completions", json=body, timeout=timeout,
                             headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    if response.status_code != 200:
        raise RuntimeError(f"Qwen API {response.status_code}: {response.text[:300]}")
    text = response.json()["choices"][0]["message"]["content"]
    return json.loads(text), model


# --- the rules baseline -----------------------------------------------------------------------------

def name_parts(name: str) -> list[str]:
    words = [w for w in plain(name).casefold().replace("-", " ").split() if w not in ("jr.", "sr.", "ii", "iii", "iv")]
    return [plain(name).casefold()] + words[-1:] + words[:1]


def find_players(text: str, players: list[dict]) -> list[int]:
    """Players named in the text, in order of appearance: full name, then family name, then first name."""
    text = plain(text).casefold()
    found = []
    for player in players:
        for part in name_parts(player["name"]):
            match = re.search(rf"\b{re.escape(part)}\b", text)
            if match:
                same = [p for p in players if part in name_parts(p["name"])]
                if len(same) == 1 or part == name_parts(player["name"])[0]:
                    found.append((match.start(), player["person_id"]))
                    break
    return [pid for _, pid in sorted(found)]


RULES = [  # (pattern, what it sets); team levers as "team.<lever>", the addressed player's as "player.<lever>"
    (r"\btime ?out\b", {"timeout": True}),
    (r"push the pace|play fast|speed (it )?up|get out and run|run every chance|push it|run the floor", {"team.pace": 0.6}),
    (r"slow (it )?down|milk the clock|burn (the )?clock|take (our|your) time|walk it up|use the (shot )?clock", {"team.pace": -0.6}),
    (r"(stop|quit|no more|fewer|less) (settling for |taking |shooting )?(threes|3s|jumpers)", {"team.three_point_rate": -0.6}),
    (r"let it fly|(more|need|shoot|take) (more )?threes|from three|from deep|three[- ]point shots", {"team.three_point_rate": 0.6}),
    (r"attack the (rim|basket|paint)|get to the (rim|line|basket|free[- ]throw line)|keep attacking|drive", {"team.attack_rim": 0.6}),
    (r"take care of the ball|value (the ball|every possession)|no (more )?turnovers|protect the ball|careful with the ball", {"team.ball_security": 0.6}),
    (r"crash the (offensive )?(glass|boards)|offensive rebound", {"team.crash_glass": 0.6}),
    (r"don'?t crash|get back (on defense|in transition)|transition defense", {"team.crash_glass": -0.6}),
    (r"\bpress\b|pressure|full court|\btrap\b|get physical|turn them over", {"team.pressure": 0.6}),
    (r"pack the paint|protect the (rim|paint)|nothing easy at the rim|\bzone\b|2-3", {"team.protect_paint": 0.6}),
    (r"off the (three[- ]point )?(line|arc)|no open threes|close ?out", {"team.protect_paint": -0.6}),
    (r"stop fouling|no (more )?(stupid |cheap )?fouls|but no fouls|don'?t reach|hands back|foul trouble", {"foul_caution": 0.6}),
    (r"(start )?foul(ing)? (if|when) we'?re (down|behind)|if we'?re down late, start fouling|foul on purpose", {"late_foul": True}),
    (r"great job|keep it up|proud of|nice (job|work)|good job|unstoppable", {"confidence": 0.5}),
    (r"be (more )?aggressive|look for your shot|take over|keep shooting|hunt", {"player.aggression": 0.6}),
    (r"stop forcing|don'?t force|find the open man|pass more|share the ball", {"player.aggression": -0.6}),
]


def ask_rules(words: str, context: dict) -> dict:
    """The keyword baseline: the same output format as the LLM, from regular expressions."""
    text = plain(words).casefold()
    own, opponents = context["your_players"], context["opponents"]
    addressed = context["addressed_to"]["person_id"] if isinstance(context["addressed_to"], dict) else None
    raw: dict = {"team": {}, "players": [], "unmapped": []}
    player: dict = {}
    for pattern, sets in RULES:
        if not re.search(pattern, text):
            continue
        for key, value in sets.items():
            if key.startswith("team."):
                raw["team"][key[5:]] = value
            elif key == "foul_caution":
                if addressed:
                    player["foul_caution"] = value
                else:
                    raw["team"]["foul_caution"] = value
            elif key == "confidence":
                if addressed:
                    player["confidence"] = value
                else:
                    raw["team_confidence"] = value
            elif key.startswith("player."):
                if addressed:
                    player[key[7:]] = value
            else:
                raw[key] = value
    for zone, pattern in (("three", r"corner|three|open shot"), ("rim", r"downhill|the rim|the basket|the paint"), ("mid", r"midrange|mid-range|pull-?up|elbow")):
        if addressed and re.search(pattern, text):
            player["shot_preference"] = {"zone": zone, "value": 0.6}
            break
    named_own, named_opp = find_players(words, own), find_players(words, opponents)
    if re.search(r"\bdouble\b", text) and named_opp:
        raw["double_team"] = named_opp[0]
    if re.search(r"run (everything|it|the offense) through|get the ball to|\bfeed\b", text) and named_own:
        raw["focus"] = named_own[0]
    sub = re.search(r"(put|bring) (in )?(.+?) in for (.+)|(.+?) in for (.+)", words, re.IGNORECASE)
    if sub and len(named_own) >= 2:
        raw["substitutions"] = [{"in": named_own[0], "out": named_own[1]}]
    elif re.search(r"\b(sit|rest|bench)\b|sit down|take a seat|get some rest", text):
        target = named_own[0] if named_own else addressed
        if target:
            raw["players"].append({"person_id": target, "rest_minutes": 0})
            if "quarter" in text:
                raw["duration"] = "quarter"
    if player and addressed:
        raw["players"].append({"person_id": addressed, **player})
    if not (raw["team"] or raw["players"] or set(raw) - {"team", "players", "unmapped"}):
        raw["unmapped"] = [words]
    first = next((key for key in [*raw["team"], *player, *(k for k in RULE_REPLIES if raw.get(k))] if key in RULE_REPLIES), None)
    raw["reply"] = RULE_REPLIES.get(first, "Got it, coach." if addressed else "Heard you, coach!")
    on_floor = [p["person_id"] for p in own if p["on_floor"]]
    raw["replier"] = addressed or (on_floor[sum(map(ord, words)) % len(on_floor)] if on_floor else None)
    return raw


RULE_REPLIES = {  # what a player answers, by the first lever the rules set: an acknowledgement, never a promise
    "pace": "Pushing it, coach.", "three_point_rate": "Letting it fly.", "attack_rim": "Attacking the rim.",
    "ball_security": "Strong with the ball. Got it.", "crash_glass": "Crashing the glass.", "pressure": "Turning up the pressure.",
    "protect_paint": "Walling up the paint.", "foul_caution": "Hands back. No cheap ones.", "aggression": "Say less. Attacking.",
    "shot_preference": "I'll look for that shot.", "confidence": "Appreciate it, coach!", "timeout": "Bringing it in.",
    "late_foul": "Got it: we foul if we're down late.", "double_team": "We'll send two.", "focus": "We'll go through them.",
    "substitutions": "On it, coach.",
}


# --- the translator the game uses -----------------------------------------------------------------

def translate(words: str, game: Game, side: Side, addressed: int | None = None, use: str = "auto",
              unmapped_log: Path | None = None) -> Instruction:
    """Words -> a validated Instruction. use: "qwen", "rules", or "auto" (Qwen when a key is set, else rules)."""
    context = context_for(game, side, addressed)
    if use == "qwen" or (use == "auto" and os.environ.get("DASHSCOPE_API_KEY")):
        try:
            raw, source = ask_qwen(words, context)
        except (requests.RequestException, RuntimeError, json.JSONDecodeError, KeyError) as exc:
            if use == "qwen":
                raise
            raw, source = ask_rules(words, context), f"rules (Qwen failed: {type(exc).__name__})"
    else:
        raw, source = ask_rules(words, context), "rules"
    own = set(side.athletes)
    instruction = validate(raw, words, own, set(game.other(side).athletes), addressed, source)
    if unmapped_log and instruction.unmapped:
        log_unmapped(unmapped_log, instruction)
    return instruction


def log_unmapped(path: Path, instruction: Instruction) -> None:
    """Append what couldn't be mapped; counting these phrases tells us which lever to build next."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "words": instruction.words,
              "unmapped": instruction.unmapped, "source": instruction.source}
    with path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(record, ensure_ascii=False) + "\n")


# --- grading against the test phrases ---------------------------------------------------------------

def grade(instruction: Instruction, expect: dict, names: dict[str, int], addressed: int | None) -> list[str]:
    """What's wrong with a translation, given the expected levers ([] means it passes).

    Keys: a team lever with "+" or "-"; "player.<lever>" for the player addressed; "focus",
    "double_team", "rest" with a name; "substitution" with [in, out]; "timeout", "late_foul",
    "unmapped" with true; "confidence" with "+" or "-"; "levers": 0 for no levers at all.
    """
    problems = []

    def sign_ok(value, want) -> bool:
        return value is not None and abs(value) >= 0.2 and (value > 0) == (want == "+")

    for key, want in expect.items():
        if key in TEAM_LEVERS:
            ok = sign_ok(instruction.team.get(key), want)
        elif key.startswith("player."):
            value = instruction.players.get(addressed, {}).get(key[7:])
            if key == "player.shot_preference":
                ok = isinstance(value, dict) and value["zone"] == want and value["value"] > 0
            else:
                ok = sign_ok(value, want)
        elif key in ("focus", "double_team"):
            ok = getattr(instruction, key) == names[want]
        elif key == "rest":
            ok = names[want] in instruction.rest
        elif key == "substitution":
            ok = (names[want[0]], names[want[1]]) in instruction.substitutions
        elif key in ("timeout", "late_foul"):
            ok = bool(getattr(instruction, key)) == want
        elif key == "unmapped":
            ok = bool(instruction.unmapped) == want
        elif key == "confidence":
            values = list(instruction.confidence.values())
            ok = any(sign_ok(v, want) for v in values)
        elif key == "levers":
            ok = instruction.lever_count == want
        else:
            raise ValueError(f"unknown expectation {key!r}")
        if not ok:
            problems.append(f"{key}: wanted {want!r}")
    return problems


def check_phrases(game: Game, side: Side, use: str, path: Path = PHRASES, log=print, pause: float = 0.0) -> tuple[int, int, list[dict]]:
    """Run every test phrase in a file through a translator. Returns (passed, total, rows)."""
    phrases = json.loads(path.read_text(encoding="utf-8"))
    names = {a.profile.name: pid for team in (game.home, game.away) for pid, a in team.athletes.items()}
    rows, passed = [], 0
    for phrase in phrases:
        addressed = names[phrase["to"]] if phrase.get("to") else None
        started = time.time()
        instruction = translate(phrase["text"], game, side, addressed, use=use)
        problems = grade(instruction, phrase["expect"], names, addressed)
        passed += not problems
        rows.append({"text": phrase["text"], "to": phrase.get("to"), "ok": not problems, "problems": problems,
                     "seconds": round(time.time() - started, 2), "reply": instruction.reply, "unmapped": instruction.unmapped})
        log(f"{'ok  ' if not problems else 'FAIL'} {phrase['text'][:60]:60s} {'; '.join(problems)}")
        time.sleep(pause)
    return passed, len(phrases), rows
