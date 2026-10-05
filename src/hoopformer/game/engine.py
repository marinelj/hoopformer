"""Play an NBA game possession by possession, with real players' rates.

One loop and one seeded random generator: the same seed replays the same game,
which makes games testable and shareable. Each possession is one or more
chances (see actions.py); each chance picks who acts and what they do, in
proportion to the five players' rates and adjusted for the defense and home
court, then resolves makes, assists, blocks, rebounds, steals and fouls.

The game moves one possession at a time (`Game.step`), so a live app can stop
between possessions to let a coach talk, call a timeout or substitute. Between
possessions each team's scripted coach (coach.py) decides timeouts and
substitutions, from fatigue, fouls, minutes and the score.

A human coach's words arrive as an Instruction (levers.py, translator.py);
`Game.instruct` stores them as directives in the team's and the athletes'
memory, and from the next possession on they change the rates the engine
plays with, never further than real teams and players go.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass, field

import pandas as pd

from hoopformer.game import coach, levers
from hoopformer.game.actions import EVENTS, ZONES
from hoopformer.game.levers import Directive, Instruction
from hoopformer.game.model import ActionModel, PlayerProfile, TeamDefense

PERIOD_SECONDS = 720.0
OVERTIME_SECONDS = 300.0
FOUL_OUT = 6
ROSTER_SIZE = 13
TIMEOUTS = 7
MAX_SHARE = 0.9  # no one plays more than 90% of the game
SETTLED_GAMES = 10  # minutes per game from fewer games are scaled down (expected_minutes)
POINTS = {"rim": 2, "mid": 2, "three": 3}
BOX_COLUMNS = ["MIN", "PTS", "FGM", "FGA", "3PM", "3PA", "FTM", "FTA", "OREB", "DREB", "REB", "AST", "STL", "BLK", "TOV", "PF"]

# Fatigue. Energy runs from 1 (fresh) down while a player is on the floor and back up on the bench.
# Real 2025-26 stints (measured from the rebuilt lineups, see docs/GAME_DESIGN.md) last about 5 minutes
# for players averaging under 20 minutes and 9 minutes for those over 35, and regulars rest about 4
# minutes, so a player's energy reaches coach.TIRED after `stint_seconds` and recovers in about 4 minutes.
# Real shooting doesn't drop late in a stint (made/expected 0.98-1.01 at every stint length), so
# fatigue changes who plays, not how well they shoot.
TIRED = coach.TIRED
REST_SECONDS = 240.0
BREAK_SECONDS = {"quarter": 130.0, "half": 900.0}  # real time off the floor between periods
LATE_FOUL_SECONDS = 60.0  # "foul when we're down late": the last minute, trailing by 1 to LATE_FOUL_MARGIN
LATE_FOUL_MARGIN = 8
COACH_SUB_SECONDS = 240.0  # a coach's substitution sticks this long before the assistant may undo it
QUICK_SECONDS = 8.0  # a first chance this short beat the defense down the floor


def stint_seconds(minutes_per_game: float) -> float:
    """How long a player plays from fresh to tired: real stints, 2.5 minutes plus 0.17 per minute per game (6 to 10)."""
    return 60 * max(6.0, min(10.0, 2.5 + 0.17 * minutes_per_game))


@dataclass
class Athlete:
    profile: PlayerProfile
    seconds: float = 0.0
    stats: Counter = field(default_factory=Counter)
    energy: float = 1.0
    confidence: float = 0.5  # 0 to 1: moves with his shots, turnovers, steals, blocks and the coach's praise
    boost: float = 1.0       # the game's boost (levers.BOOST in the live app): how strongly confidence shows

    @property
    def fouled_out(self) -> bool:
        return self.stats["PF"] >= FOUL_OUT

    def run(self, seconds: float, on_floor: bool, effort: float = 1.0) -> None:
        """Time passes: on the floor it tires the player (faster under tiring calls) and counts as minutes,
        on the bench it rests them."""
        if on_floor:
            self.seconds += seconds
            self.energy = max(0.0, self.energy - effort * seconds * (1 - TIRED) / stint_seconds(self.profile.minutes_per_game))
        else:
            self.rest(seconds)

    def rest(self, seconds: float) -> None:
        self.energy = min(1.0, self.energy + seconds * (1 - TIRED) / REST_SECONDS)

    def feel(self, change: float) -> None:
        self.confidence = min(1.0, max(0.0, self.confidence + change))

    def shot_taken(self, made: bool) -> None:
        """Confidence remembers his last few shots, the latest most (levers.CONFIDENCE_*, measured)."""
        lead = (self.confidence - 0.5) * levers.CONFIDENCE_KEEP
        self.confidence = min(1.0, max(0.0, 0.5 + lead + (levers.CONFIDENCE_SHOT if made else -levers.CONFIDENCE_SHOT)))

    @property
    def usage(self) -> float:
        """Confident players take more of the shots (measured: x1.06 after two makes, x0.94 after two misses)."""
        return 1.0 + levers.CONFIDENCE_USAGE * self.boost * (self.confidence - 0.5)


@dataclass
class Side:
    team_id: int
    tricode: str
    name: str
    is_home: bool
    defense: TeamDefense
    athletes: dict[int, Athlete]
    share: dict[int, float]  # each player's target share of game time (they sum to 5)
    lineup: list[int] = field(default_factory=list)
    points: int = 0
    possessions: int = 0
    team_turnovers: int = 0
    timeouts: int = TIMEOUTS
    last_change: float = -1e9  # game seconds of the last substitution
    held_out: set[int] = field(default_factory=set)  # players the coach told to sit
    pinned: set[int] = field(default_factory=set)    # players the coach put in; the assistant leaves them be
    directives: list[Directive] = field(default_factory=list)  # the coach's instructions still in force
    tactics: dict[str, float] = field(default_factory=dict)    # team lever -> value, from the directives
    player_tactics: dict[int, dict] = field(default_factory=dict)  # person id -> {lever: value}
    focus: int | None = None        # run the offense through this player
    double_team: int | None = None  # an opponent this defense doubles
    late_foul: bool = False


@dataclass
class Event:
    period: int
    clock: float  # seconds left in the period
    team: str
    text: str
    home_score: int
    away_score: int
    kind: str = ""          # period_start, period_end, chance, shot, block, rebound, turnover, foul, free_throws, sub, timeout
    actor: int | None = None  # who did it (shooter, rebounder, fouler, player coming in...)
    other: int | None = None  # the second player involved (passer, thief, blocked shooter, fouled player, player going out,
                              # on a chance: the player the defense is doubling)
    zone: str | None = None   # shot zone; "offensive"/"defensive" for rebounds; foul type; "first"/"second" chance; timeout reason
    value: int = 0            # points on a shot; free throws made
    attempts: int = 0         # free throws attempted
    home_lineup: tuple[int, ...] = ()
    away_lineup: tuple[int, ...] = ()
    tactics: dict | None = None  # on a chance: the calls both coaches have in force ({"off": ..., "def": ...}), if any
    credit: dict | None = None   # a play put down to a coach's call: {"team", "call", "good"} (good: it paid off; else it backfired)


@dataclass
class GameResult:
    seed: int
    home: Side
    away: Side
    periods: int
    events: list[Event]

    @property
    def winner(self) -> Side:
        return self.home if self.home.points > self.away.points else self.away

    def box_score(self, side: Side) -> pd.DataFrame:
        rows = []
        for athlete in side.athletes.values():
            stats = athlete.stats
            row = {"PLAYER": athlete.profile.name, "MIN": round(athlete.seconds / 60, 1)}
            row.update({column: stats[column] for column in BOX_COLUMNS[1:]})
            row["REB"] = stats["OREB"] + stats["DREB"]
            rows.append(row)
        return pd.DataFrame(rows).sort_values("MIN", ascending=False, ignore_index=True)


def expected_minutes(p: PlayerProfile) -> float:
    """Minutes per game, scaled down for players with few games: two 35-minute cameos aren't a starter."""
    return p.minutes_per_game * min(1.0, p.games / SETTLED_GAMES)


def minute_shares(profiles: list[PlayerProfile]) -> dict[int, float]:
    """Each player's target share of game time, summing to 5 (five players on the floor).

    Like a real coach: the regulars get their real minutes per game, most minutes
    first, until the 240 team minutes are used up; the end of the bench gets what
    is left, which is often nothing.
    """
    expected = expected_minutes
    shares, left = {}, 240.0
    for profile in sorted(profiles, key=expected, reverse=True):
        minutes = min(expected(profile), MAX_SHARE * 48, left)
        shares[profile.person_id] = minutes / 48
        left -= minutes
    if left > 0:  # a short roster: spread the rest evenly
        for pid in shares:
            shares[pid] = min(MAX_SHARE, shares[pid] + left / 48 / len(shares))
    return shares


def default_roster(model: ActionModel, team_id: int, size: int = ROSTER_SIZE) -> list[int]:
    """The team's 13 players with the biggest roles (minutes per game), so a star who missed games still makes it."""
    players = [p for p in model.players.values() if p.team_id == team_id]
    players.sort(key=expected_minutes, reverse=True)
    return [p.person_id for p in players[:size]]


class Game:
    def __init__(self, model: ActionModel, home_team_id: int, away_team_id: int, seed: int,
                 home_roster: list[int] | None = None, away_roster: list[int] | None = None,
                 limits: dict[str, list[float]] | None = None, boost: float = 1.0, half_life: float | None = None,
                 min_first_seconds: float = 0.0):
        self.model = model
        self.league = model.league
        self.boost = boost  # 1 for a faithful simulation; levers.BOOST in the live game, so calls are felt
        self.half_life = half_life  # game seconds for a call to lose half its strength (live game); None: calls never fade
        self.min_first_seconds = min_first_seconds  # live game: levers.MIN_FIRST_SECONDS, so the court can show every possession
        # how far each lever reaches (levers.lever_limits), stretched by the boost; needed only for instructions
        self.limits = levers.boosted(limits, boost) if limits and boost != 1 else limits
        self.credit_rng = random.Random(seed + 7919)  # its own numbers, so crediting plays never changes the game
        self.seed = seed
        self.rng = random.Random(seed)
        self.home = self._side(home_team_id, True, home_roster or default_roster(model, home_team_id))
        self.away = self._side(away_team_id, False, away_roster or default_roster(model, away_team_id))
        self.events: list[Event] = []
        self.period = 1
        self.clock = PERIOD_SECONDS
        self.game_seconds = 0.0
        self.period_open = False  # between "Start of period" and "End of period"
        self.done = False
        self.run = (None, 0)  # (side that scored, points) since the other side last scored
        self.timeout_windows: set[tuple[int, int]] = set()  # (period, mark) breaks already taken, see coach.py
        self.leak_out: tuple[Side, float, str] | None = None  # a fast break earned: (team, make factor, "crash" or "leak")
        self.break_bonus = 1.0  # make-rate factor for the chance being played
        self.break_cause = None  # "crash" (the other team crashed the glass) or "leak" (one of ours leaked out)
        self.quick = False  # the chance being played is a first chance of under QUICK_SECONDS (for crediting the pace)
        self.mean_first_seconds = sum(model.league.first_chance_seconds) / len(model.league.first_chance_seconds)
        self.tip_winner = self.home if self.rng.random() < 0.5 else self.away
        self.offense = self.tip_winner
        league = self.league
        # Fouls with no free throws (reach-ins, loose balls before the bonus): whatever is left of the
        # league's foul rate after the fouls that the engine already creates on free-throw trips and and-ones.
        fouls_per_chance = 5 * league.foul_rate
        trip_fouls = 5 * league.event_rate["free_throws"]
        and_one_fouls = sum(5 * league.event_rate[z] * league.make[z] * league.and_one[z] for z in ZONES)
        self.silent_foul_rate = max(0.0, fouls_per_chance - trip_fouls - and_one_fouls)

    def _side(self, team_id: int, is_home: bool, roster: list[int]) -> Side:
        defense = self.model.teams[team_id]
        athletes = {pid: Athlete(self.model.players[pid], boost=self.boost) for pid in roster}
        share = minute_shares([athletes[pid].profile for pid in roster])
        side = Side(team_id, defense.tricode, defense.name, is_home, defense, athletes, share)
        side.lineup = coach.starters(side)
        return side

    def other(self, side: Side) -> Side:
        return self.away if side is self.home else self.home

    # --- bookkeeping -------------------------------------------------------------------------------

    def _log(self, side: Side, text: str, kind: str = "", actor: int | None = None, other: int | None = None,
             zone: str | None = None, value: int = 0, attempts: int = 0, tactics: dict | None = None, credit: dict | None = None) -> None:
        self.events.append(Event(self.period, round(self.clock, 1), side.tricode, text, self.home.points, self.away.points,
                                 kind, actor, other, zone, value, attempts,
                                 tuple(self.home.lineup), tuple(self.away.lineup), tactics, credit))

    def _name(self, side: Side, pid: int) -> str:
        return side.athletes[pid].profile.name

    def _pick(self, side: Side, players: list[int], weight) -> int:
        return self.rng.choices(players, [weight(side.athletes[p].profile) for p in players])[0]

    def _score(self, side: Side, points: int) -> None:
        side.points += points
        team, run = self.run
        self.run = (side, run + points) if team is side else (side, points)

    # --- coaching actions (the scripted coaches use these; so will human coaches) --------------------

    def substitute(self, side: Side, new_lineup: list[int], reason: str = "") -> None:
        """Change a team's five. Players keep their slot, so an incoming player takes the leaving player's place."""
        leaving = [p for p in side.lineup if p not in new_lineup]
        entering = [p for p in new_lineup if p not in side.lineup]
        if len(set(new_lineup)) != 5 or any(p not in side.athletes or side.athletes[p].fouled_out for p in entering):
            raise ValueError(f"not a valid five for {side.tricode}: {new_lineup}")
        if not leaving:
            return
        lineup = list(side.lineup)
        for out, inn in zip(leaving, entering):
            lineup[lineup.index(out)] = inn
            side.lineup = lineup
            self._log(side, f"SUB: {self._name(side, inn)} for {self._name(side, out)}", "sub", inn, out, reason or None)
        side.last_change = self.game_seconds

    def call_timeout(self, side: Side, reason: str) -> bool:
        """Stop play: everyone on the floor gets a short breather, then the coach may substitute."""
        if side.timeouts <= 0:
            return False
        side.timeouts -= 1
        self._log(side, f"{side.tricode} timeout ({coach.TIMEOUT_REASONS[reason]})", "timeout", zone=reason)
        for team in (self.home, self.away):
            for pid in team.lineup:
                team.athletes[pid].rest(coach.TIMEOUT_REST_SECONDS)
        return True

    def instruct(self, side: Side, instruction: Instruction) -> list[Event]:
        """Apply a coach's instruction: timeouts and substitutions now, levers from the next possession."""
        if self.limits is None:
            raise ValueError("this game has no lever limits: pass limits=levers.lever_limits(...)")
        start, now = len(self.events), self.game_seconds
        until = {"game": None, "quarter": now + self.clock,
                 "possessions": now + (instruction.possessions or 5) * 2 * 14.0}[instruction.duration]
        self._log(side, instruction.words, "coach", other=instruction.addressed, zone=instruction.source)

        def remember(lever, value, player=None, lapse=until):
            side.directives = [d for d in side.directives if not (d.lever == lever and d.player == player)]
            side.directives.append(Directive(lever, value, instruction.words, player, now, lapse))

        for lever, value in instruction.team.items():
            remember(lever, value)
        for pid, values in instruction.players.items():
            for lever, value in values.items():
                remember(lever, value, pid)
        for lever in ("focus", "double_team", "late_foul"):
            value = getattr(instruction, lever)
            if value is not None:
                remember(lever, value)
        for pid, minutes in instruction.rest.items():  # no minutes given: sit for as long as the instruction lasts
            remember("rest", minutes, pid, until if minutes is None else now + 60 * minutes)
        for pid, change in instruction.confidence.items():
            for athlete in (side.athletes.values() if pid == "team" else [side.athletes[pid]]):
                athlete.confidence = min(1.0, max(0.0, athlete.confidence + 0.15 * change))
        self._refresh(side)
        if instruction.reply:
            self._log(side, instruction.reply, "reply", instruction.replier)
        if instruction.timeout:
            self.call_timeout(side, "coach")
        for inn, out in instruction.substitutions:
            if out in side.lineup and inn not in side.lineup and not side.athletes[inn].fouled_out:
                remember("play", True, inn, now + COACH_SUB_SECONDS)
                remember("rest", COACH_SUB_SECONDS / 60, out, now + COACH_SUB_SECONDS)
                self._refresh(side)
                self.substitute(side, [inn if pid == out else pid for pid in side.lineup], "coach's call")
        if any(pid in side.held_out for pid in side.lineup):
            coach.rotate(self, side, stopped=True)
        return self.events[start:]

    def effort(self, side: Side, pid: int) -> float:
        """How fast a player tires on the floor under his coach's calls: 1 is normal, 1.4 is 40% faster."""
        def cost(lever, value):
            plus, minus = levers.EFFORT.get(lever, (0.0, 0.0))
            return value * plus if value > 0 else -value * minus

        mine = {k: v for k, v in side.player_tactics.get(pid, {}).items() if not isinstance(v, dict)}
        if side.focus is not None:  # running the offense through one player is his aggression
            mine["aggression"] = mine.get("aggression", 0.0) + (levers.FOCUS if pid == side.focus else levers.FOCUS_OTHERS)
        total = sum(cost(k, v) for k, v in side.tactics.items()) + sum(cost(k, v) for k, v in mine.items())
        total += levers.DOUBLE_TEAM_EFFORT if side.double_team is not None else 0.0
        return max(0.4, 1.0 + total * (1 + (self.boost - 1) / 2))

    def nudge(self, side: Side, instruction: Instruction) -> list[Event]:
        """A call from the page's list: each lever it names moves one STEP from where it stands, so the same call
        again pushes further and the opposite call pulls back. The side's other calls of the same kind fade."""
        def strength(value):
            return value["value"] if isinstance(value, dict) else value

        def step(old, value):
            return round(levers.clamp(old + (levers.STEP if strength(value) > 0 else -levers.STEP)), 2)

        def forget(lever, player):
            side.directives = [d for d in side.directives if not (d.lever == lever and d.player == player)]

        now = {(d.lever, d.player): d.value for d in side.directives}
        moved = set()
        for lever, value in list(instruction.team.items()):
            instruction.team[lever] = step(now.get((lever, None), 0.0), value)
            moved.add((lever, None))
        for pid, values in instruction.players.items():
            for lever, value in list(values.items()):
                old = now.get((lever, pid), 0.0)
                if lever == "shot_preference":  # a new zone replaces the old one
                    old = old["value"] if old and old["zone"] == value["zone"] else 0.0
                    values[lever] = {"zone": value["zone"], "value": step(old, value)}
                else:
                    values[lever] = step(old, value)
                moved.add((lever, pid))
        kinds = {levers.kind(lever, player) for lever, player in moved} - {None}
        for d in side.directives:
            if (d.lever, d.player) not in moved and levers.kind(d.lever, d.player) in kinds:
                faded = round(strength(d.value) * levers.FADE, 2)
                d.value = {**d.value, "value": faded} if isinstance(d.value, dict) else faded
        side.directives = [d for d in side.directives if levers.kind(d.lever, d.player) is None or abs(strength(d.value)) >= levers.FORGOTTEN]
        for lever, value in list(instruction.team.items()):  # back to where it started: nothing left to remember
            if value == 0:
                del instruction.team[lever]
                forget(lever, None)
        for pid, values in instruction.players.items():
            for lever, value in list(values.items()):
                if strength(value) == 0:
                    del values[lever]
                    forget(lever, pid)
        return self.instruct(side, instruction)

    def _refresh(self, side: Side) -> None:
        """Rebuild a team's tactics from the directives still in force."""
        now = self.game_seconds
        side.directives = [d for d in side.directives if d.until is None or d.until > now]
        side.tactics, side.player_tactics = {}, {}
        side.focus, side.double_team, side.late_foul = None, None, False
        side.held_out, side.pinned = set(), set()
        for d in side.directives:
            if d.player is None and d.lever in levers.TEAM_LEVERS:
                side.tactics[d.lever] = d.value
            elif d.lever in ("focus", "double_team", "late_foul"):
                setattr(side, d.lever, d.value)
            elif d.lever == "rest":
                side.held_out.add(d.player)
            elif d.lever == "play":
                side.pinned.add(d.player)
            elif d.player is not None:
                side.player_tactics.setdefault(d.player, {})[d.lever] = d.value

    def memory(self, side: Side, pid: int, recent: int = 10) -> dict:
        """What an athlete remembers: energy, fouls, confidence, the coach's directives and their last actions."""
        athlete = side.athletes[pid]
        mine = [e for e in self.events if pid in (e.actor, e.other) and e.kind != "chance"]
        return {"name": athlete.profile.name, "energy": round(athlete.energy, 2), "fouls": athlete.stats["PF"],
                "confidence": round(athlete.confidence, 2),
                "directives": [d for d in side.directives if d.player in (None, pid)],
                "recent": [e.text for e in mine[-recent:]]}

    def _defense(self, dfn: Side, lever: str) -> float:
        """A defensive lever's value: the team's call plus a fifth of each call to a player on the floor."""
        players = sum(dfn.player_tactics.get(p, {}).get(lever, 0.0) for p in dfn.lineup) if dfn.player_tactics else 0.0
        return levers.clamp(dfn.tactics.get(lever, 0.0) + levers.ONE_OF_FIVE * players)

    def _defense_lever(self, dfn: Side, lever: str, invert: bool = False) -> float:
        """The multiplier for a defensive lever (1 when nobody was told anything)."""
        value = self._defense(dfn, lever)
        return levers.multiplier(-value if invert else value, self.limits[lever]) if value else 1.0

    def _lever(self, side: Side, lever: str, invert: bool = False) -> float:
        """A team lever's multiplier for this side (1 when the coach hasn't touched it)."""
        value = side.tactics.get(lever, 0.0)
        return levers.multiplier(-value if invert else value, self.limits[lever]) if value else 1.0

    # --- one chance --------------------------------------------------------------------------------

    def _chance(self, off: Side, dfn: Side) -> bool:
        """Play one chance. Returns True if the offense keeps the ball (offensive rebound)."""
        league = self.league
        silent = self.silent_foul_rate
        if dfn.directives:
            pressing = levers.PRESSURE_FOULS * max(0.0, self._defense(dfn, "pressure"))
            silent *= self._defense_lever(dfn, "foul_caution", invert=True) * levers.multiplier(pressing, self.limits["foul_caution"])
        if self.rng.random() < silent:
            fouler = self._fouler(dfn)
            dfn.athletes[fouler].stats["PF"] += 1
            self._log(dfn, f"{self._name(dfn, fouler)} personal foul", "foul", fouler, zone="personal", credit=self._foul_credit(dfn, fouler))
        choices, weights = self.chance_weights(off, dfn)
        pid, event = self.rng.choices(choices, weights)[0]
        if event in ZONES:
            return self._shot(off, dfn, pid, event)
        if event == "turnover":
            self._turnover(off, dfn, pid)
            return False
        shots = 3 if self.rng.random() < league.three_shot_trip_share else 2
        fouler = self._fouler(dfn)
        dfn.athletes[fouler].stats["PF"] += 1
        self._log(dfn, f"{self._name(dfn, fouler)} shooting foul on {self._name(off, pid)}", "foul", fouler, pid, "shooting",
                  credit=self._foul_credit(dfn, fouler))
        return self._free_throws(off, dfn, pid, shots)

    def chance_weights(self, off: Side, dfn: Side, use_levers: bool = True) -> tuple[list, list]:
        """Every way the next chance can end, (player or None, event), with its weight.

        With use_levers=False the coaches' directives are ignored: the monitor compares the two.
        """
        league = self.league
        turnover_factor = dfn.defense.turnover_factor * (league.home_turnover_factor if off.is_home else league.away_turnover_factor)
        free_throw_factor = dfn.defense.free_throw_factor * (league.home_free_throw_factor if off.is_home else league.away_free_throw_factor)
        coached = use_levers and bool(off.directives or dfn.directives)
        if coached:  # the coaches' levers: shot mix, getting to the line, ball security, pressure, the defense's shape
            paint = self._defense_lever(dfn, "protect_paint")  # packing the paint concedes threes
            team_zones = {"rim": self._lever(off, "attack_rim") / paint, "mid": 1.0, "three": self._lever(off, "three_point_rate") * paint}
            safe = levers.multiplier(-levers.SAFE_PLAY * off.tactics.get("ball_security", 0.0), self.limits["attack_rim"])
            team_zones["rim"] *= safe
            free_throw_factor *= self._lever(off, "attack_rim") * safe * self._defense_lever(dfn, "foul_caution", invert=True)
            turnover_factor *= self._lever(off, "ball_security", invert=True) * self._defense_lever(dfn, "pressure")
        choices, weights = [], []
        for pid in off.lineup:
            profile, usage = off.athletes[pid].profile, off.athletes[pid].usage
            if coached:
                event_weights = self._player_weights(off, dfn, pid, team_zones, turnover_factor, free_throw_factor)
            for event in EVENTS:
                if coached:
                    weight = event_weights[event]
                else:
                    weight = profile.events[event]
                    if event == "turnover":
                        weight *= turnover_factor
                    elif event == "free_throws":
                        weight *= free_throw_factor
                choices.append((pid, event))
                weights.append(weight * usage)
        choices.append((None, "turnover"))
        weights.append(league.team_turnover_rate * turnover_factor)
        return choices, weights

    def _calls(self, off: Side, dfn: Side) -> dict | None:
        """What both coaches have in force for this chance, so the page can show it and act it out."""
        if not (off.directives or dfn.directives):
            return None
        calls = {"off": {k: v for k, v in off.tactics.items() if k in levers.OFFENSE_LEVERS},
                 "def": {k: v for k, v in dfn.tactics.items() if k in levers.DEFENSE_LEVERS}}
        if off.focus in off.lineup:
            calls["off"]["focus"] = off.focus
        players = {pid: {k: v for k, v in values.items() if k in ("aggression", "shot_preference")}
                   for pid, values in off.player_tactics.items() if pid in off.lineup}
        if any(players.values()):
            calls["off"]["players"] = {pid: v for pid, v in players.items() if v}
        if dfn.double_team in off.lineup:
            calls["def"]["double_team"] = dfn.double_team
        return calls if calls["off"] or calls["def"] else None

    def monitor(self, side: Side) -> dict:
        """What the coach's directives change in the engine right now.

        The odds of the next chance at each end, with the current lineups, with and without the
        directives in force; for each player on the floor, his share of our chances and each way they end with him,
        his share of the team's steals, blocks, defensive rebounds and fouls, his energy, how fast he tires,
        and his confidence; the opponents' energy and confidence; and every directive with the coach's words
        and how long it has left.
        """
        other = self.other(side)

        def outcomes(off: Side, dfn: Side, use: bool) -> list[tuple]:
            choices, weights = self.chance_weights(off, dfn, use_levers=use)
            total = sum(weights)
            return [(pid, event, w / total) for (pid, event), w in zip(choices, weights)]

        def rows(off: Side, dfn: Side) -> tuple[list[dict], list, list]:
            before, after = outcomes(off, dfn, False), outcomes(off, dfn, True)
            table = [{"label": label, "before": sum(p for _, e, p in before if e == event), "after": sum(p for _, e, p in after if e == event)}
                     for event, label in (("rim", "a shot at the rim"), ("mid", "a midrange shot"), ("three", "a three"),
                                          ("free_throws", "drawing a shooting foul"), ("turnover", "a turnover"))]
            return table, before, after

        offense, before, after = rows(side, other)
        own = sum(side.athletes[p].profile.oreb for p in side.lineup)
        theirs = sum(other.athletes[p].profile.dreb for p in other.lineup)
        crash = self._lever(side, "crash_glass") if side.directives else 1.0
        offense.append({"label": "an offensive rebound, after a miss", "before": own / (own + theirs), "after": own * crash / (own * crash + theirs)})
        pace = self._lever(side, "pace") if "pace" in side.tactics else 1.0
        offense.append({"label": "seconds per first chance", "before": self.mean_first_seconds, "after": self.mean_first_seconds / pace, "unit": "s"})
        defense, their_before, their_after = rows(other, side)
        def mix(outs: list, pid: int) -> dict:  # how our chances end with him, as shares of all our chances
            return {e: p for q, e, p in outs if q == pid}

        def shares(weight) -> dict:  # each defender's share of a team total
            weights = {p: weight(p) for p in side.lineup}
            total = sum(weights.values()) or 1.0
            return {p: w / total for p, w in weights.items()}

        def profile(p):
            return side.athletes[p].profile

        own_defense = [  # (label, without calls, with calls)
            ("of our steals", shares(lambda p: profile(p).steal), shares(lambda p: profile(p).steal * self._told(side, p, "pressure", levers.PLAYER_STEALS))),
            ("of our blocks", shares(lambda p: profile(p).block), shares(lambda p: profile(p).block * self._told(side, p, "protect_paint", levers.PLAYER_BLOCKS))),
            ("of our defensive rebounds", shares(lambda p: profile(p).dreb), shares(lambda p: profile(p).dreb * self._box_out(side, p))),
            ("of our fouls", shares(lambda p: profile(p).foul), shares(lambda p: self._foul_weight(side, p))),
        ]
        players = []
        for pid in side.lineup:
            athlete, mine_before, mine_after = side.athletes[pid], mix(before, pid), mix(after, pid)
            players.append({
                "name": athlete.profile.name, "id": pid,
                "before": sum(p for q, _, p in before if q == pid), "after": sum(p for q, _, p in after if q == pid),
                "energy": self.legs(athlete) if self.boost != 1 else athlete.energy, "tired": athlete.energy <= coach.TIRED + 0.1,
                "confidence": athlete.confidence, "usage": athlete.usage, "effort": self.effort(side, pid),
                "offense": [{"label": label, "before": mine_before.get(event, 0.0), "after": mine_after.get(event, 0.0)} for event, label in
                            (("rim", "a shot at the rim"), ("mid", "a midrange shot"), ("three", "a three"),
                             ("free_throws", "drawing a shooting foul"), ("turnover", "a turnover"))],
                "defense": [{"label": label, "before": plain[pid], "after": coached[pid]} for label, plain, coached in own_defense],
            })
        if side.double_team in other.lineup:
            doubled = side.double_team
            defense.append({"label": f"{other.athletes[doubled].profile.name} acting (doubled)",
                            "before": sum(p for q, _, p in their_before if q == doubled), "after": sum(p for q, _, p in their_after if q == doubled)})
        names = {pid: a.profile.name for team in (side, other) for pid, a in team.athletes.items()}
        def shown(d):  # names for players, two decimals for strengths
            if d.lever in ("focus", "double_team"):
                return names.get(d.value, d.value)
            if isinstance(d.value, dict):
                return {**d.value, "value": round(d.value["value"], 2)}
            return round(d.value, 2) if isinstance(d.value, float) else d.value

        def fades_in(d):  # game seconds until a fading call is forgotten
            strength = abs(d.value["value"] if isinstance(d.value, dict) else d.value) if levers.kind(d.lever, d.player) else 0
            return self.half_life * math.log2(strength / levers.FORGOTTEN) if self.half_life and strength > levers.FORGOTTEN else None

        directives = [{"lever": d.lever, "value": shown(d), "player": names.get(d.player), "player_id": d.player, "words": d.words,
                       "left": None if d.until is None else max(0.0, d.until - self.game_seconds), "fades_in": fades_in(d)}
                      for d in side.directives]
        opponents = [{"id": pid, "energy": self.legs(other.athletes[pid]) if self.boost != 1 else other.athletes[pid].energy,
                      "tired": other.athletes[pid].energy <= coach.TIRED + 0.1, "confidence": other.athletes[pid].confidence} for pid in other.lineup]
        return {"offense": offense, "defense": defense, "players": players, "opponents": opponents, "directives": directives}

    def _player_weights(self, off: Side, dfn: Side, pid: int, team_zones: dict, turnover_factor: float,
                        free_throw_factor: float) -> dict[str, float]:
        """One player's event weights under both coaches' levers.

        The shot mix is renormalized, so "more threes" means fewer twos, not more shots; usage
        (aggression, focus, a double team) scales all of a player's events against the other four.
        """
        profile = off.athletes[pid].profile
        mine = off.player_tactics.get(pid, {})
        zones = dict(team_zones)
        preference = mine.get("shot_preference")
        if preference:
            zones[preference["zone"]] *= levers.multiplier(preference["value"], self.limits["shot_preference"])
        before = sum(profile.events[z] for z in ZONES)
        after = sum(profile.events[z] * zones[z] for z in ZONES)
        aggression = mine.get("aggression", 0.0)
        if off.focus is not None:
            aggression += levers.FOCUS if pid == off.focus else levers.FOCUS_OTHERS
        usage = levers.multiplier(aggression, self.limits["aggression"]) if aggression else 1.0
        doubled = dfn.double_team == pid
        if doubled:
            usage *= max(0.3, 1 - (1 - levers.DOUBLE_TEAM_TOUCHES) * self.boost)
        weights = {z: profile.events[z] * zones[z] * before / after for z in ZONES}
        weights["turnover"] = profile.events["turnover"] * turnover_factor * (1 + (levers.DOUBLE_TEAM_TURNOVERS - 1) * self.boost if doubled else 1.0)
        weights["free_throws"] = profile.events["free_throws"] * free_throw_factor
        return {event: weight * usage for event, weight in weights.items()}

    def _fouler(self, dfn: Side) -> int:
        """Who commits a foul: by foul rate, less often for a player told to be careful."""
        if not dfn.player_tactics:
            return self._pick(dfn, dfn.lineup, lambda p: p.foul)
        return self.rng.choices(dfn.lineup, [self._foul_weight(dfn, p) for p in dfn.lineup])[0]

    def _foul_weight(self, dfn: Side, pid: int) -> float:
        caution = dfn.player_tactics.get(pid, {}).get("foul_caution", 0.0)
        return dfn.athletes[pid].profile.foul * (levers.multiplier(-caution, self.limits["foul_caution"]) if caution else 1.0)

    def _shot(self, off: Side, dfn: Side, pid: int, zone: str) -> bool:
        league, shooter = self.league, off.athletes[pid]
        home_factor = league.home_make_factor if off.is_home else league.away_make_factor
        chance = shooter.profile.make[zone] * dfn.defense.make_factor[zone] * home_factor
        chance *= self.break_bonus
        if dfn.directives:
            if zone == "three" and dfn.double_team in off.lineup and dfn.double_team != pid:
                chance *= 1 + (levers.DOUBLE_TEAM_OPEN_THREES - 1) * self.boost
            if zone == "rim":  # hands back concedes easier finishes, physical defense contests them
                chance *= 1 + levers.CAUTION_CONTEST * self.boost * self._defense(dfn, "foul_caution")
                chance *= 1 + levers.PRESSURE_BEATEN * self.boost * max(0.0, self._defense(dfn, "pressure"))
        chance *= 1 - levers.CONFIDENCE_QUALITY * (shooter.confidence - 0.5)  # confident players take harder shots (never boosted)
        legs = self.legs(shooter)
        chance *= legs  # game mode: a shot goes in at its chance times his energy
        chance = min(0.98, max(0.02, chance))
        shooter.stats["FGA"] += 1
        if zone == "three":
            shooter.stats["3PA"] += 1
        label = {"rim": "at the rim", "mid": "midrange", "three": "3PT"}[zone]
        made = self.rng.random() < chance
        shooter.shot_taken(made)
        if made:
            points = POINTS[zone]
            shooter.stats["FGM"] += 1
            shooter.stats["3PM"] += zone == "three"
            shooter.stats["PTS"] += points
            self._score(off, points)
            text = f"{shooter.profile.name} makes {label} ({shooter.stats['PTS']} PTS)"
            passer = None
            if self.rng.random() < shooter.profile.assisted[zone]:
                mates = [p for p in off.lineup if p != pid]
                passer = self._pick(off, mates, lambda p: p.assist)
                off.athletes[passer].stats["AST"] += 1
                text += f", assist {self._name(off, passer)}"
            self._log(off, text, "shot", pid, passer, zone, points,
                      credit=self._make_credit(off, dfn, pid, zone) if off.directives or dfn.directives else None)
            if self.rng.random() < league.and_one[zone]:
                fouler = self._fouler(dfn)
                dfn.athletes[fouler].stats["PF"] += 1
                self._log(dfn, f"{self._name(dfn, fouler)} fouls: and-one", "foul", fouler, pid, "and-one")
                return self._free_throws(off, dfn, pid, 1)
            return False
        worn = off.directives and legs < 1 and self.effort(off, pid) > 1  # his coach's calls wore him out
        credit = self._credit(off, "tired_legs", False, 1 / legs) if worn else None
        if credit is None and dfn.directives:  # the defense's shape forced the miss
            paint = self._defense(dfn, "protect_paint")
            if paint > 0 and zone != "rim":
                credit = self._credit(dfn, "zone_stop", True, self._defense_lever(dfn, "protect_paint"))
            elif paint < 0 and zone != "three":
                credit = self._credit(dfn, "run_off", True, 1 / self._defense_lever(dfn, "protect_paint"))
        self._log(off, f"{shooter.profile.name} misses {label}", "shot", pid, None, zone, 0, credit=credit)
        blocks = [dfn.athletes[p].profile.block * self._told(dfn, p, "protect_paint", levers.PLAYER_BLOCKS) for p in dfn.lineup]
        if self.rng.random() < sum(blocks):
            blocker = self.rng.choices(dfn.lineup, blocks)[0]
            dfn.athletes[blocker].stats["BLK"] += 1
            dfn.athletes[blocker].feel(levers.CONFIDENCE_PLAY)
            rim_call = dfn.directives and (dfn.player_tactics.get(blocker, {}).get("protect_paint", 0.0) > 0 or dfn.tactics.get("protect_paint", 0.0) > 0)
            credit = self._credit(dfn, "rim_block", True, self._told(dfn, blocker, "protect_paint", levers.PLAYER_BLOCKS)) if rim_call else None
            self._log(dfn, f"blocked by {self._name(dfn, blocker)}", "block", blocker, pid, credit=credit)
        return self._rebound(off, dfn)

    def _free_throws(self, off: Side, dfn: Side, pid: int, shots: int) -> bool:
        shooter = off.athletes[pid]
        made = 0
        for number in range(1, shots + 1):
            shooter.stats["FTA"] += 1
            if self.rng.random() < shooter.profile.ft_pct:
                made += 1
                shooter.stats["FTM"] += 1
                shooter.stats["PTS"] += 1
                self._score(off, 1)
            elif number == shots:
                self._log(off, f"{shooter.profile.name} free throws {made}/{shots}", "free_throws", pid, value=made, attempts=shots)
                return self._rebound(off, dfn)
        self._log(off, f"{shooter.profile.name} free throws {made}/{shots}", "free_throws", pid, value=made, attempts=shots)
        return False

    def _rebound(self, off: Side, dfn: Side) -> bool:
        offense_weight = sum(off.athletes[p].profile.oreb for p in off.lineup) * (self._lever(off, "crash_glass") if off.directives else 1.0)
        boxing = {p: self._box_out(dfn, p) for p in dfn.lineup}
        defense_weight = sum(dfn.athletes[p].profile.dreb * boxing[p] for p in dfn.lineup)
        offense_keeps = self.rng.random() < offense_weight / (offense_weight + defense_weight)
        if not offense_keeps:
            crashed = 1 + levers.LEAK_OUT * self.boost * max(0.0, off.tactics.get("crash_glass", 0.0))  # everyone crashed: the other team runs
            leakers = [-dfn.player_tactics[p]["box_out"] for p in dfn.lineup if dfn.player_tactics.get(p, {}).get("box_out", 0.0) < 0]
            leaked = 1 + levers.LEAK_OUT * self.boost * max(leakers, default=0.0)  # one of ours left early for the break
            if crashed * leaked > 1:
                self.leak_out = (dfn, crashed * leaked, "leak" if leaked > 1 else "crash")
        side = off if offense_keeps else dfn
        kind = "offensive" if offense_keeps else "defensive"
        coached = off.directives or dfn.directives
        other = dfn if offense_keeps else off
        if self.rng.random() < self.league.team_rebound_share:
            credit = self._rebound_credit(side, other, offense_keeps, None) if coached else None
            self._log(side, f"{side.tricode} team rebound", "rebound", None, zone=kind, credit=credit)
        else:
            weights = [side.athletes[p].profile.oreb if offense_keeps else side.athletes[p].profile.dreb * boxing[p] for p in side.lineup]
            player = self.rng.choices(side.lineup, weights)[0]
            side.athletes[player].stats["OREB" if offense_keeps else "DREB"] += 1
            credit = self._rebound_credit(side, other, offense_keeps, player) if coached else None
            self._log(side, f"{kind} rebound {self._name(side, player)}", "rebound", player, zone=kind, credit=credit)
        return offense_keeps

    def _turnover(self, off: Side, dfn: Side, pid: int | None) -> None:
        if pid is None:
            off.team_turnovers += 1
            self._log(off, f"{off.tricode} team turnover", "turnover")
            return
        off.athletes[pid].stats["TOV"] += 1
        off.athletes[pid].feel(-levers.CONFIDENCE_PLAY)
        steals = [dfn.athletes[p].profile.steal * self._told(dfn, p, "pressure", levers.PLAYER_STEALS) for p in dfn.lineup]
        if self.rng.random() < sum(steals):
            thief = self.rng.choices(dfn.lineup, steals)[0]
            dfn.athletes[thief].stats["STL"] += 1
            dfn.athletes[thief].feel(levers.CONFIDENCE_PLAY)
            credit = self._turnover_credit(off, dfn, pid, thief) if off.directives or dfn.directives else None
            self._log(off, f"{self._name(off, pid)} turnover, stolen by {self._name(dfn, thief)}", "turnover", pid, thief, credit=credit)
        else:
            credit = self._turnover_credit(off, dfn, pid, None) if off.directives or dfn.directives else None
            self._log(off, f"{self._name(off, pid)} turnover", "turnover", pid, credit=credit)

    def _told(self, dfn: Side, pid: int, lever: str, reach: float) -> float:
        """A defender's share of steals or blocks under his own call: up to 1 + reach at +1, 1 - reach at -1 (x boost)."""
        return max(0.1, 1.0 + reach * self.boost * dfn.player_tactics.get(pid, {}).get(lever, 0.0)) if dfn.player_tactics else 1.0

    # --- credit: which plays a coach's call made happen (or cost), for the page to show ---------------

    def _credit(self, side: Side, call: str, good: bool, strength: float) -> dict | None:
        """Put a play down to a call in force, as often as the call made such plays likelier: the share 1 - 1/strength
        of them (strength is the call's multiplier). A call that paid off is shown at least CREDIT_FLOOR of the time,
        so the coach sees it work; a price paid is shown only as often as the call really caused it."""
        share = max(0.0, 1 - 1 / strength) if strength > 0 else 0.0
        if good:
            share = max(levers.CREDIT_FLOOR, share)
        return {"team": side.tricode, "call": call, "good": good} if self.credit_rng.random() < share else None

    def legs(self, athlete: Athlete) -> float:
        """Game mode: his energy as the game shows it and as it scales his shots, from 1 (fresh) to 1 - LEGS_DROP
        (empty); a normal stint ends near 0.85. A faithful simulation always plays at 1."""
        return 1.0 if self.boost == 1 else 1 - levers.LEGS_DROP * (1 - athlete.energy)

    def _m(self, lever: str, value: float) -> float:
        return levers.multiplier(value, self.limits[lever]) if value else 1.0

    def _make_credit(self, off: Side, dfn: Side, pid: int, zone: str) -> dict | None:
        """A made shot: the shooting team's call paid off, or the defending team's call let it happen."""
        if off.directives:
            mine = off.player_tactics.get(pid, {})
            preference = mine.get("shot_preference") or {}
            zoned = preference.get("value", 0.0) if preference.get("zone") == zone else 0.0
            team = {"rim": "attack_rim", "three": "three_point_rate"}.get(zone)
            if self.break_cause == "leak":
                return self._credit(off, "leak_out", True, self.break_bonus)
            if self.quick and off.tactics.get("pace", 0.0) > 0:  # scored before the defense was set
                return self._credit(off, "push", True, self._lever(off, "pace"))
            if zoned > 0 or (team and off.tactics.get(team, 0.0) > 0):
                strength = max(self._m("shot_preference", max(zoned, 0.0)), self._m(team, off.tactics.get(team, 0.0)) if team else 1.0)
                return self._credit(off, {"rim": "attack", "mid": "midrange", "three": "three"}[zone], True, strength)
            if off.focus == pid:
                return self._credit(off, "focus", True, self._m("aggression", levers.FOCUS))
            if mine.get("aggression", 0.0) > 0:
                return self._credit(off, "aggressive", True, self._m("aggression", mine["aggression"]))
        if dfn.directives:
            if self.break_cause == "crash":
                return self._credit(dfn, "burned", False, self.break_bonus)
            if zone == "rim" and self._defense(dfn, "pressure") > 0:
                return self._credit(dfn, "press_broken", False, 1 + levers.PRESSURE_BEATEN * self.boost * self._defense(dfn, "pressure"))
            if zone == "rim" and self._defense(dfn, "foul_caution") > 0:
                return self._credit(dfn, "hands_back", False, 1 + levers.CAUTION_CONTEST * self.boost * self._defense(dfn, "foul_caution"))
            if zone == "rim" and self._defense(dfn, "protect_paint") < 0:
                return self._credit(dfn, "paint_open", False, 1 / self._defense_lever(dfn, "protect_paint"))
            if zone == "three" and dfn.double_team in off.lineup and dfn.double_team != pid:
                return self._credit(dfn, "double_open", False, 1 + (levers.DOUBLE_TEAM_OPEN_THREES - 1) * self.boost)
            if zone == "three" and self._defense(dfn, "protect_paint") > 0:
                return self._credit(dfn, "zone_beaten", False, self._defense_lever(dfn, "protect_paint"))
        return None

    def _turnover_credit(self, off: Side, dfn: Side, pid: int, thief: int | None) -> dict | None:
        if dfn.directives:
            if dfn.double_team == pid:
                return self._credit(dfn, "trap", True, 1 + (levers.DOUBLE_TEAM_TURNOVERS - 1) * self.boost)
            if thief is not None and dfn.player_tactics.get(thief, {}).get("pressure", 0.0) > 0:
                return self._credit(dfn, "steal", True, self._told(dfn, thief, "pressure", levers.PLAYER_STEALS))
            if self._defense(dfn, "pressure") > 0:
                return self._credit(dfn, "press", True, self._defense_lever(dfn, "pressure"))
        if off.directives:
            aggression = off.player_tactics.get(pid, {}).get("aggression", 0.0) + (levers.FOCUS if off.focus == pid else 0.0)
            if aggression > 0:
                return self._credit(off, "forced", False, self._m("aggression", aggression))
        return None

    def _rebound_credit(self, side: Side, other: Side, offensive: bool, player: int | None) -> dict | None:
        if offensive and side.directives and side.tactics.get("crash_glass", 0.0) > 0:
            return self._credit(side, "crash", True, self._lever(side, "crash_glass"))
        if not offensive and side.directives and player is not None and side.player_tactics.get(player, {}).get("box_out", 0.0) > 0:
            return self._credit(side, "boxed_out", True, self._box_out(side, player))
        if offensive and other.directives and any(other.player_tactics.get(p, {}).get("box_out", 0.0) < 0 for p in other.lineup):
            return self._credit(other, "leak_cost", False, 1 / min(self._box_out(other, p) for p in other.lineup))
        return None

    def _foul_credit(self, dfn: Side, fouler: int) -> dict | None:
        """A foul by a team, or a player, told to get physical."""
        if not dfn.directives:
            return None
        physical = -min(dfn.player_tactics.get(fouler, {}).get("foul_caution", 0.0), dfn.tactics.get("foul_caution", 0.0))
        return self._credit(dfn, "physical", False, self._m("foul_caution", physical)) if physical > 0 else None

    def _box_out(self, dfn: Side, pid: int) -> float:
        """A defender's rebounding weight under his call: boxing out gains as much as a crashing team, leaking out loses it."""
        value = dfn.player_tactics.get(pid, {}).get("box_out", 0.0) if dfn.player_tactics else 0.0
        return levers.multiplier(value, self.limits["crash_glass"]) if value else 1.0

    # --- the game loop -----------------------------------------------------------------------------

    def _run_clock(self, seconds: float) -> None:
        self.clock -= seconds
        self.game_seconds += seconds
        if self.half_life:
            self._fade(seconds)
        for side in (self.home, self.away):
            on_floor = set(side.lineup)
            for pid, athlete in side.athletes.items():
                athlete.run(seconds, pid in on_floor, self.effort(side, pid) if side.directives and pid in on_floor else 1.0)

    def _fade(self, seconds: float) -> None:
        """Calls wear off as game time passes: each keeps 0.5 ** (seconds / half_life) of its strength, and one
        weaker than levers.FORGOTTEN is dropped. Focus, double teams, fouling late and rest don't fade."""
        keep = 0.5 ** (seconds / self.half_life)
        for side in (self.home, self.away):
            fading = [d for d in side.directives if levers.kind(d.lever, d.player) is not None]
            if not fading:
                continue
            for d in fading:
                d.value = {**d.value, "value": d.value["value"] * keep} if isinstance(d.value, dict) else d.value * keep
            side.directives = [d for d in side.directives if levers.kind(d.lever, d.player) is None
                               or abs(d.value["value"] if isinstance(d.value, dict) else d.value) >= levers.FORGOTTEN]
            self._refresh(side)

    def _possession(self, off: Side, dfn: Side) -> bool:
        """Play one possession. Returns False if the period clock ran out first."""
        first = True
        if (dfn.late_foul and self.period >= 4 and self.clock <= LATE_FOUL_SECONDS
                and 0 < off.points - dfn.points <= LATE_FOUL_MARGIN and self.clock > 3):
            if not self._intentional_foul(off, dfn):
                return True
            first = False  # a missed free throw rebounded by the offense: play on
        while True:
            durations = self.league.first_chance_seconds if first else self.league.second_chance_seconds
            seconds = self.rng.choice(durations)
            if first and "pace" in off.tactics:
                seconds /= self._lever(off, "pace")
            if first:
                seconds = max(seconds, self.min_first_seconds)
            if seconds >= self.clock:
                self._run_clock(self.clock)
                return False
            doubled = dfn.double_team if dfn.double_team in off.lineup else None  # shown on the court as two defenders
            self._log(off, "", "chance", other=doubled, zone="first" if first else "second", tactics=self._calls(off, dfn))
            self._run_clock(seconds)
            self.quick = first and seconds < QUICK_SECONDS
            if first:
                off.possessions += 1
            breaking = first and self.leak_out is not None and self.leak_out[0] is off
            self.break_bonus, self.break_cause = (self.leak_out[1], self.leak_out[2]) if breaking else (1.0, None)
            self.leak_out = None
            keeps = self._chance(off, dfn)
            self.break_bonus, self.break_cause = 1.0, None
            if not keeps:
                return True
            first = False

    def _intentional_foul(self, off: Side, dfn: Side) -> bool:
        """Trailing late, the defense fouls at once and sends the worst free-throw shooter on the floor to the line.

        Returns True if the offense keeps the ball (a missed last free throw that they rebound).
        """
        self._log(off, "", "chance", zone="first")
        self._run_clock(3.0)
        off.possessions += 1
        shooter = min(off.lineup, key=lambda p: off.athletes[p].profile.ft_pct)
        fouler = self._fouler(dfn)
        dfn.athletes[fouler].stats["PF"] += 1
        self._log(dfn, f"{self._name(dfn, fouler)} fouls {self._name(off, shooter)} on purpose", "foul", fouler, shooter, "intentional")
        return self._free_throws(off, dfn, shooter, 2)

    def _start_period(self) -> None:
        self.clock = PERIOD_SECONDS if self.period <= 4 else OVERTIME_SECONDS
        if self.period > 1:  # the break between periods rests everybody
            for side in (self.home, self.away):
                for athlete in side.athletes.values():
                    athlete.rest(BREAK_SECONDS["half" if self.period == 3 else "quarter"])
        if self.period in (1, 3):  # starters open each half
            for side in (self.home, self.away):
                self.substitute(side, coach.starters(side), "starters")
        if self.period <= 4:
            tip_loser = self.other(self.tip_winner)
            self.offense = self.tip_winner if self.period in (1, 4) else tip_loser
        else:
            self.offense = self.home if self.rng.random() < 0.5 else self.away
        self._log(self.offense, f"Start of period {self.period}", "period_start")
        self.period_open = True
        if self.period not in (1, 3):  # the coaches may change their five over the break
            for side in (self.home, self.away):
                coach.rotate(self, side, stopped=True)

    def _end_period(self) -> None:
        self._log(self.offense, f"End of period {self.period}", "period_end")
        self.period_open = False
        if self.period >= 4 and self.home.points != self.away.points:
            self.done = True
        else:
            self.period += 1

    def step(self) -> list[Event]:
        """Play until the next stop: one possession, then the coaches' timeouts and substitutions.

        Returns the events of this step. A live app calls this in a loop and lets the
        human coach act between steps; `play` just runs it to the end.
        """
        if self.done:
            return []
        start = len(self.events)
        for side in (self.home, self.away):
            if any(d.until is not None and d.until <= self.game_seconds for d in side.directives):
                self._refresh(side)
        if not self.period_open:
            self._start_period()
        offense, defense = self.offense, self.other(self.offense)
        before = offense.points
        if self._possession(offense, defense):
            self.offense = defense
            coach.between_possessions(self, offense if offense.points > before else None)
        else:
            self._end_period()
        return self.events[start:]

    def play(self) -> GameResult:
        while not self.done:
            self.step()
        return self.result()

    def result(self) -> GameResult:
        return GameResult(self.seed, self.home, self.away, self.period, self.events)
