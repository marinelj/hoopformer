"""Levers: what a coach's words can change in the engine, and how far.

The coach only ever speaks; the translator (translator.py) turns the words into
lever values from -1 to 1, and the engine (engine.py) turns each value into a
multiplier on the rates it plays with. How far a lever reaches is measured from
real games, not invented: +1 moves a team as far from the league average as the
most extreme real team of the season went, and a player as far as their own
games swing from their season average (10th to 90th percentile). So "shoot more
threes" can make a team shoot like the season's most three-happy team, and no
further.

Each lever:
- team offense: pace, three_point_rate, attack_rim, ball_security, crash_glass
- team defense: pressure, protect_paint, foul_caution, plus double_team (an opponent) and late_foul
- one player: aggression, shot_preference (rim, mid or three), foul_caution, rest, and on defense
  pressure, protect_paint and box_out (a player's defensive call counts for a fifth of the team's)
- the whole roster: focus (run the offense through one player)
- morale: confidence (praise; makes, misses, turnovers, steals and blocks move it too)

Every call has a price. Most cost energy (EFFORT): tired players go to the bench sooner, so the stars
play less. Confidence makes a player shoot more but a little worse, as real players do (hot_hand).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from hoopformer.fetch import BOX_SCORE, SCHEDULE, final_regular_season_game_ids, raw_path

TEAM_LEVERS = ("pace", "three_point_rate", "attack_rim", "ball_security", "crash_glass", "pressure", "protect_paint", "foul_caution")
OFFENSE_LEVERS = ("pace", "three_point_rate", "attack_rim", "ball_security", "crash_glass")
DEFENSE_LEVERS = ("pressure", "protect_paint", "foul_caution")
PLAYER_LEVERS = ("aggression", "shot_preference", "foul_caution", "pressure", "protect_paint", "box_out")
ZONES = ("rim", "mid", "three")
MIN_GAME_MINUTES = 20  # a player's game counts for the swing limits only with this many minutes
MIN_GAMES = 30
FOCUS = 0.6           # "run it through X" is a strong aggression push for X...
FOCUS_OTHERS = -0.15  # ...and a small step back for the other four
DOUBLE_TEAM_TOUCHES = 0.75  # assumed (no tracking data): a doubled player gets 25% fewer touches,
DOUBLE_TEAM_TURNOVERS = 1.25  # turns it over 25% more on the touches they get,
DOUBLE_TEAM_OPEN_THREES = 1.03  # and their teammates make 3% more of their threes
CAUTION_CONTEST = 0.02  # assumed: a defense that never fouls concedes 2% more makes at the rim
# Side effects, so no lever is a free win (assumed until the transformer can measure them):
LEAK_OUT = 0.04         # crashing the glass at +1: after a defensive rebound the other team makes 4% more on the break
PRESSURE_BEATEN = 0.03  # pressing at +1: the other team makes 3% more at the rim when it breaks the pressure,
PRESSURE_FOULS = 0.5    # and the defense fouls as if at half its foul_caution limit
SAFE_PLAY = 0.3         # protecting the ball at +1 attacks the rim less, as if attack_rim were -0.3
# Energy: what each call costs in legs. A lever at +1 (first number) or -1 (second) changes how fast the
# players it covers tire on the floor: 0.4 means 40% faster, -0.1 means 10% slower. Assumed: no public data
# measures effort. Real shooting doesn't drop late in a stint (engine.py), so the price is paid in minutes:
# tired players go to the bench sooner.
EFFORT = {
    "pace": (0.2, -0.1),           # running costs legs, walking it up saves them
    "pressure": (0.4, -0.1),       # a full-court press is the most tiring call there is
    "crash_glass": (0.15, 0.05),   # five to the glass, or sprinting back
    "attack_rim": (0.1, 0.0),      # driving into bodies
    "protect_paint": (-0.1, 0.1),  # a zone saves legs; chasing shooters off the line costs them
    "foul_caution": (-0.05, 0.1),  # hands back is easy, physical defense is not
    "aggression": (0.2, -0.05),    # carrying the offense
    "box_out": (0.1, 0.1),         # fighting for the rebound, or leaking out for the break
}
DOUBLE_TEAM_EFFORT = 0.1  # rotating behind a double team
ONE_OF_FIVE = 0.2      # a player's defensive call counts for a fifth of the team's: five players told = one team call
PLAYER_STEALS = 0.5    # assumed: a player told to pressure his man gets up to 50% more of the team's steals
PLAYER_BLOCKS = 0.5    # and one told to protect the rim, up to 50% more of its blocks

# Confidence, from 0 to 1 (0.5 is normal), measured with actions.hot_hand on 2025-26: after making his last
# two shots a player takes 6.0% more of his team's shots and makes 1.2% fewer of them than usual (harder
# shots); after missing two, 5.4% fewer shots and 0.7% more makes. Confidence remembers his last few shots,
# the latest most: each shot keeps half of his lead over 0.5 and adds or takes 0.1, so two makes give 0.65
# and two misses 0.35.
CONFIDENCE_KEEP = 0.5
CONFIDENCE_SHOT = 0.1
CONFIDENCE_USAGE = 0.4     # his share of chances x (1 + 0.4 x (confidence - 0.5)): 0.65 -> x1.06, 0.35 -> x0.94
CONFIDENCE_QUALITY = 0.08  # his makes x (1 - 0.08 x (confidence - 0.5)): 0.65 -> x0.988, 0.35 -> x1.012
CONFIDENCE_PLAY = 0.05     # assumed: a turnover costs this much, a steal or a block earns it

# Game mode. The measured limits make a faithful simulation, where one call moves a stat by a few percent:
# true to the NBA, but too small to feel in a game. The live app plays with every coached effect stretched
# BOOST times further from "no change": the lever limits, the side effects (so each call keeps its price),
# how much confidence changes who shoots, and (half as much) the energy costs. How well a confident player
# shoots stays as measured. Simulations, tests and the realism checks use boost 1.
BOOST = 5.0
CREDIT_FLOOR = 0.5  # a play a call made likelier is put down to it at least half the time, so the coach sees it pay off
# Game mode only: tired legs. Real players don't shoot worse late in a normal stint (engine.py), because coaches
# sub them out first; but boosted calls tire players far faster, so in the game a player below FATIGUE_START
# energy pays for it: at empty he makes 15% fewer shots and turns it over 40% more (assumed). That is what
# makes a tiring call a trade-off and not a free win.
FATIGUE_START = 0.6
FATIGUE_MAKES = 0.15
FATIGUE_TURNOVERS = 0.4


def boosted(limits: dict, boost: float) -> dict:
    """Lever limits stretched `boost` times further from 1 (never below 0.2)."""
    return {lever: [max(0.2, 1 - (1 - low) * boost), 1 + (high - 1) * boost] for lever, (low, high) in limits.items()}


# Calls from the page's list are nudges, not switches:
STEP = 0.35  # each call moves its lever this far: the same call three times reaches the limit, the opposite call takes one back
FADE = 0.7   # and the other calls of the same kind keep 70% of their strength: players hold on to the latest message best


def signed(v: float) -> str:
    """A lever value for people: +0.35, +0.7, -1."""
    return f"{v:+.2f}".rstrip("0").rstrip(".")


def kind(lever: str, player: int | None) -> tuple | None:
    """Which calls compete for the players' attention: the team's offense, the team's defense,
    or one player's offense or defense. None for calls that don't fade (focus, double team, rest)."""
    if lever in OFFENSE_LEVERS or lever in ("aggression", "shot_preference"):
        return (player, "offense")
    if lever in DEFENSE_LEVERS or lever == "box_out":
        return (player, "defense")
    return None


def possessions(stats: dict) -> float:
    """The standard box-score estimate of a team's possessions."""
    return stats["fieldGoalsAttempted"] - stats["reboundsOffensive"] + stats["turnovers"] + 0.44 * stats["freeThrowsAttempted"]


def measure_limits(data_dir: Path, season: str) -> dict[str, list[float]]:
    """How far real teams and players moved from the league average: (lowest, highest) ratio per lever."""
    schedule = json.loads(raw_path(data_dir, SCHEDULE, season).read_text(encoding="utf-8"))
    teams: dict[int, dict[str, float]] = {}
    player_games: dict[int, list[tuple[float, float]]] = {}  # per player: (usage per minute, share of shots that are threes)
    for game_id in final_regular_season_game_ids(schedule):
        path = raw_path(data_dir, BOX_SCORE, game_id)
        if not path.exists():
            continue
        box = json.loads(path.read_text(encoding="utf-8"))["boxScoreTraditional"]
        for side, other in (("homeTeam", "awayTeam"), ("awayTeam", "homeTeam")):
            mine, theirs = box[side]["statistics"], box[other]["statistics"]
            totals = teams.setdefault(box[side]["teamId"], {})
            for key, value in (("games", 1), ("poss", possessions(mine)), ("fga", mine["fieldGoalsAttempted"]),
                               ("tpa", mine["threePointersAttempted"]), ("fta", mine["freeThrowsAttempted"]),
                               ("tov", mine["turnovers"]), ("oreb", mine["reboundsOffensive"]), ("opp_dreb", theirs["reboundsDefensive"]),
                               ("pf", mine["foulsPersonal"]), ("opp_poss", possessions(theirs)), ("opp_tov", theirs["turnovers"]),
                               ("opp_fga", theirs["fieldGoalsAttempted"]), ("opp_tpa", theirs["threePointersAttempted"])):
                totals[key] = totals.get(key, 0) + value
            for player in box[side]["players"]:
                stats = player["statistics"]
                minutes = sum(float(x) * f for x, f in zip(stats["minutes"].split(":"), (1, 1 / 60))) if stats["minutes"] else 0.0
                if minutes >= MIN_GAME_MINUTES and stats["fieldGoalsAttempted"]:
                    usage = (stats["fieldGoalsAttempted"] + 0.44 * stats["freeThrowsAttempted"] + stats["turnovers"]) / minutes
                    player_games.setdefault(player["personId"], []).append((usage, stats["threePointersAttempted"] / stats["fieldGoalsAttempted"]))
    rates = {
        "pace": lambda t: t["poss"] / t["games"],
        "three_point_rate": lambda t: t["tpa"] / t["fga"],
        "attack_rim": lambda t: t["fta"] / t["fga"],
        "ball_security": lambda t: t["tov"] / t["poss"],
        "crash_glass": lambda t: t["oreb"] / (t["oreb"] + t["opp_dreb"]),
        "pressure": lambda t: t["opp_tov"] / t["opp_poss"],
        "protect_paint": lambda t: t["opp_tpa"] / t["opp_fga"],
        "foul_caution": lambda t: t["pf"] / t["opp_poss"],
    }
    limits = {}
    for lever, rate in rates.items():
        values = np.array([rate(t) for t in teams.values()])
        ratios = values / values.mean()
        limits[lever] = [float(ratios.min()), float(ratios.max())]
    for name, column in (("aggression", 0), ("shot_preference", 1)):
        swings = []
        for games in player_games.values():
            if len(games) >= MIN_GAMES:
                values = np.array([g[column] for g in games])
                if values.mean() > 0.05:
                    swings.extend(values / values.mean())
        limits[name] = [float(np.percentile(swings, 10)), float(np.percentile(swings, 90))]
    return limits


def lever_limits(data_dir: Path, season: str) -> dict[str, list[float]]:
    """The measured limits, cached in data/derived/lever_limits_<season>.json."""
    path = data_dir / "derived" / f"lever_limits_{season}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    limits = measure_limits(data_dir, season)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(limits, indent=1), encoding="utf-8")
    return limits


def multiplier(value: float, limits: list[float]) -> float:
    """A lever value in [-1, 1] as a multiplier: +1 reaches the highest real ratio, -1 the lowest, 0 changes nothing."""
    low, high = limits
    value = max(-1.0, min(1.0, value))
    return 1 + value * (high - 1) if value >= 0 else 1 + value * (1 - low)


# --- instructions and memory --------------------------------------------------------------------------

@dataclass
class Instruction:
    """One coach instruction after translation and validation: everything the engine needs, nothing else."""
    words: str
    addressed: int | None = None      # the player the coach was talking to; None for the whole team
    team: dict[str, float] = field(default_factory=dict)            # team lever -> value
    players: dict[int, dict] = field(default_factory=dict)          # person id -> {lever: value}; shot_preference is {"zone", "value"}
    focus: int | None = None
    double_team: int | None = None
    late_foul: bool | None = None
    timeout: bool = False
    substitutions: list[tuple[int, int]] = field(default_factory=list)  # (coming in, going out)
    rest: dict[int, float | None] = field(default_factory=dict)         # person id -> minutes on the bench (None: until told)
    confidence: dict[int | str, float] = field(default_factory=dict)    # person id or "team" -> change, -1 to 1
    duration: str = "game"            # "game", "quarter" or "possessions"
    possessions: int | None = None    # with duration "possessions"
    reply: str = ""
    replier: int | None = None
    unmapped: list[str] = field(default_factory=list)
    source: str = ""                  # which translator: "qwen3.8-max", "rules", ...

    def describe(self, names: dict[int, str]) -> str:
        """One line for logs: every lever this instruction sets."""
        def name(pid: int) -> str:
            return names.get(pid, str(pid))

        parts = [f"{k} {signed(v)}" for k, v in self.team.items()]
        for pid, values in self.players.items():
            for lever, value in values.items():
                shown = f"{value['zone']} {signed(value['value'])}" if isinstance(value, dict) else signed(value)
                parts.append(f"{name(pid)} {lever} {shown}")
        parts += [f"focus {name(self.focus)}"] if self.focus is not None else []
        parts += [f"double {name(self.double_team)}"] if self.double_team is not None else []
        parts += ["foul late"] if self.late_foul else []
        parts += ["timeout"] if self.timeout else []
        parts += [f"{name(inn)} in for {name(out)}" for inn, out in self.substitutions]
        parts += [f"rest {name(pid)}" + (f" {m:.0f} min" if m else "") for pid, m in self.rest.items()]
        parts += [f"unmapped {self.unmapped}"] if self.unmapped else []
        return ", ".join(parts) or "nothing to change"

    @property
    def lever_count(self) -> int:
        return (len(self.team) + sum(len(v) for v in self.players.values()) + (self.focus is not None)
                + (self.double_team is not None) + (self.late_foul is not None) + self.timeout
                + len(self.substitutions) + len(self.rest))


@dataclass
class Directive:
    """One lever change in a team's or an athlete's memory, with the coach's own words."""
    lever: str
    value: object
    words: str
    player: int | None   # None for a team directive
    since: float         # game seconds
    until: float | None  # game seconds when it lapses; None for the rest of the game


def clamp(value) -> float:
    return max(-1.0, min(1.0, float(value)))


def validate(raw: dict, words: str, own: set[int], opponents: set[int], addressed: int | None, source: str) -> Instruction:
    """Turn a translator's raw output into an Instruction the engine can trust.

    Values are clamped to [-1, 1], players must be on the right team, and anything
    that doesn't fit the schema goes to `unmapped` instead of being dropped silently.
    """
    out = Instruction(words=words, addressed=addressed if addressed in own else None, source=source)
    unmapped = [str(u) for u in raw.get("unmapped") or [] if str(u).strip()]

    def number(value, label):
        try:
            return clamp(value)
        except (TypeError, ValueError):
            unmapped.append(f"{label}: {value!r}")
            return None

    for lever, value in (raw.get("team") or {}).items():
        if value is None:
            continue
        if lever not in TEAM_LEVERS:
            unmapped.append(f"team.{lever}")
            continue
        v = number(value, lever)
        if v is not None and v != 0:
            out.team[lever] = v
    for entry in raw.get("players") or []:
        pid = entry.get("person_id", addressed) if isinstance(entry, dict) else None
        if pid not in own:
            unmapped.append(f"player {pid!r}: not on your team")
            continue
        levers = {}
        for lever, value in entry.items():
            if lever in ("person_id",) or value is None:
                continue
            if lever == "shot_preference":
                zone = value.get("zone") if isinstance(value, dict) else None
                v = number(value.get("value", 0.5) if isinstance(value, dict) else 0, "shot_preference")
                if zone in ZONES and v:
                    levers[lever] = {"zone": zone, "value": v}
                else:
                    unmapped.append(f"shot_preference: {value!r}")
            elif lever in PLAYER_LEVERS:
                v = number(value, lever)
                if v:
                    levers[lever] = v
            elif lever == "rest_minutes":
                out.rest[pid] = None if value in (0, "until told") else max(1.0, min(24.0, float(value)))
            elif lever == "confidence":
                v = number(value, lever)
                if v:
                    out.confidence[pid] = v
            else:
                unmapped.append(f"player.{lever}")
        if levers:
            out.players[pid] = levers
    for key, allowed, attr in (("focus", own, "focus"), ("double_team", opponents, "double_team")):
        value = raw.get(key)
        if value is not None:
            if value in allowed:
                setattr(out, attr, value)
            else:
                unmapped.append(f"{key}: {value!r} isn't a valid player")
    if raw.get("late_foul") is not None:
        out.late_foul = bool(raw["late_foul"])
    out.timeout = bool(raw.get("timeout"))
    for sub in raw.get("substitutions") or []:
        inn, outp = (sub.get("in"), sub.get("out")) if isinstance(sub, dict) else (None, None)
        if inn in own and outp in own and inn != outp:
            out.substitutions.append((inn, outp))
        else:
            unmapped.append(f"substitution {sub!r}")
    if raw.get("team_confidence") is not None:
        v = number(raw["team_confidence"], "team_confidence")
        if v:
            out.confidence["team"] = v
    duration = raw.get("duration") or "game"
    out.duration = duration if duration in ("game", "quarter", "possessions") else "game"
    if out.duration == "possessions":
        out.possessions = max(1, min(20, int(raw.get("possessions") or 5)))
    out.reply = str(raw.get("reply") or "")[:200]
    replier = raw.get("replier")
    out.replier = replier if replier in own else (addressed if addressed in own else None)
    out.unmapped = unmapped
    return out
