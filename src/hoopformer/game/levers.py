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
- one player: aggression, shot_preference (rim, mid or three), foul_caution, rest
- the whole roster: focus (run the offense through one player)
- morale: confidence (memory only: it changes how players talk, not how they play)
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
PLAYER_LEVERS = ("aggression", "shot_preference", "foul_caution")
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

        parts = [f"{k} {v:+.1f}" for k, v in self.team.items()]
        for pid, values in self.players.items():
            for lever, value in values.items():
                shown = f"{value['zone']} {value['value']:+.1f}" if isinstance(value, dict) else f"{value:+.1f}"
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
            elif lever in ("aggression", "foul_caution"):
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
