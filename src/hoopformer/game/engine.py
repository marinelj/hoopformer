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


def stint_seconds(minutes_per_game: float) -> float:
    """How long a player plays from fresh to tired: real stints, 2.5 minutes plus 0.17 per minute per game (6 to 10)."""
    return 60 * max(6.0, min(10.0, 2.5 + 0.17 * minutes_per_game))


@dataclass
class Athlete:
    profile: PlayerProfile
    seconds: float = 0.0
    stats: Counter = field(default_factory=Counter)
    energy: float = 1.0
    confidence: float = 0.5  # memory only: moves with the coach's words, changes how the athlete talks

    @property
    def fouled_out(self) -> bool:
        return self.stats["PF"] >= FOUL_OUT

    def run(self, seconds: float, on_floor: bool) -> None:
        """Time passes: on the floor it tires the player and counts as minutes, on the bench it rests them."""
        if on_floor:
            self.seconds += seconds
            self.energy = max(0.0, self.energy - seconds * (1 - TIRED) / stint_seconds(self.profile.minutes_per_game))
        else:
            self.rest(seconds)

    def rest(self, seconds: float) -> None:
        self.energy = min(1.0, self.energy + seconds * (1 - TIRED) / REST_SECONDS)


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
                 limits: dict[str, list[float]] | None = None):
        self.model = model
        self.league = model.league
        self.limits = limits  # how far each lever reaches (levers.lever_limits); needed only for instructions
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
        self.leak_out: tuple[Side, float] | None = None  # a fast break earned against a team that crashed the glass
        self.break_bonus = 1.0  # make-rate factor for the chance being played
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
        athletes = {pid: Athlete(self.model.players[pid]) for pid in roster}
        share = minute_shares([athletes[pid].profile for pid in roster])
        side = Side(team_id, defense.tricode, defense.name, is_home, defense, athletes, share)
        side.lineup = coach.starters(side)
        return side

    def other(self, side: Side) -> Side:
        return self.away if side is self.home else self.home

    # --- bookkeeping -------------------------------------------------------------------------------

    def _log(self, side: Side, text: str, kind: str = "", actor: int | None = None, other: int | None = None,
             zone: str | None = None, value: int = 0, attempts: int = 0, tactics: dict | None = None) -> None:
        self.events.append(Event(self.period, round(self.clock, 1), side.tricode, text, self.home.points, self.away.points,
                                 kind, actor, other, zone, value, attempts,
                                 tuple(self.home.lineup), tuple(self.away.lineup), tactics))

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
            pressing = levers.PRESSURE_FOULS * max(0.0, dfn.tactics.get("pressure", 0.0))
            silent *= self._lever(dfn, "foul_caution", invert=True) * levers.multiplier(pressing, self.limits["foul_caution"])
        if self.rng.random() < silent:
            fouler = self._fouler(dfn)
            dfn.athletes[fouler].stats["PF"] += 1
            self._log(dfn, f"{self._name(dfn, fouler)} personal foul", "foul", fouler, zone="personal")
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
        self._log(dfn, f"{self._name(dfn, fouler)} shooting foul on {self._name(off, pid)}", "foul", fouler, pid, "shooting")
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
            paint = self._lever(dfn, "protect_paint")  # packing the paint concedes threes
            team_zones = {"rim": self._lever(off, "attack_rim") / paint, "mid": 1.0, "three": self._lever(off, "three_point_rate") * paint}
            safe = levers.multiplier(-levers.SAFE_PLAY * off.tactics.get("ball_security", 0.0), self.limits["attack_rim"])
            team_zones["rim"] *= safe
            free_throw_factor *= self._lever(off, "attack_rim") * safe * self._lever(dfn, "foul_caution", invert=True)
            turnover_factor *= self._lever(off, "ball_security", invert=True) * self._lever(dfn, "pressure")
        choices, weights = [], []
        for pid in off.lineup:
            profile = off.athletes[pid].profile
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
                weights.append(weight)
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
        directives in force; each player's share of chances, energy and confidence; and every directive
        with the coach's words and how long it has left.
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
        players = [{"name": side.athletes[pid].profile.name, "id": pid,
                    "before": sum(p for q, _, p in before if q == pid), "after": sum(p for q, _, p in after if q == pid),
                    "energy": side.athletes[pid].energy, "confidence": side.athletes[pid].confidence}
                   for pid in side.lineup]
        if side.double_team in other.lineup:
            doubled = side.double_team
            defense.append({"label": f"{other.athletes[doubled].profile.name} acting (doubled)",
                            "before": sum(p for q, _, p in their_before if q == doubled), "after": sum(p for q, _, p in their_after if q == doubled)})
        names = {pid: a.profile.name for team in (side, other) for pid, a in team.athletes.items()}
        directives = [{"lever": d.lever, "value": names.get(d.value, d.value) if d.lever in ("focus", "double_team") else d.value,
                       "player": names.get(d.player), "words": d.words,
                       "left": None if d.until is None else max(0.0, d.until - self.game_seconds)} for d in side.directives]
        return {"offense": offense, "defense": defense, "players": players, "directives": directives}

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
            usage *= levers.DOUBLE_TEAM_TOUCHES
        weights = {z: profile.events[z] * zones[z] * before / after for z in ZONES}
        weights["turnover"] = profile.events["turnover"] * turnover_factor * (levers.DOUBLE_TEAM_TURNOVERS if doubled else 1.0)
        weights["free_throws"] = profile.events["free_throws"] * free_throw_factor
        return {event: weight * usage for event, weight in weights.items()}

    def _fouler(self, dfn: Side) -> int:
        """Who commits a foul: by foul rate, less often for a player told to be careful."""
        if not dfn.player_tactics:
            return self._pick(dfn, dfn.lineup, lambda p: p.foul)
        weights = [dfn.athletes[p].profile.foul * levers.multiplier(-dfn.player_tactics.get(p, {}).get("foul_caution", 0.0),
                                                                     self.limits["foul_caution"]) for p in dfn.lineup]
        return self.rng.choices(dfn.lineup, weights)[0]

    def _shot(self, off: Side, dfn: Side, pid: int, zone: str) -> bool:
        league, shooter = self.league, off.athletes[pid]
        home_factor = league.home_make_factor if off.is_home else league.away_make_factor
        chance = shooter.profile.make[zone] * dfn.defense.make_factor[zone] * home_factor
        chance *= self.break_bonus
        if dfn.directives:
            if zone == "three" and dfn.double_team in off.lineup and dfn.double_team != pid:
                chance *= levers.DOUBLE_TEAM_OPEN_THREES
            if zone == "rim":
                chance *= 1 + levers.CAUTION_CONTEST * max(0.0, dfn.tactics.get("foul_caution", 0.0))
                chance *= 1 + levers.PRESSURE_BEATEN * max(0.0, dfn.tactics.get("pressure", 0.0))
        chance = min(0.98, max(0.02, chance))
        shooter.stats["FGA"] += 1
        if zone == "three":
            shooter.stats["3PA"] += 1
        label = {"rim": "at the rim", "mid": "midrange", "three": "3PT"}[zone]
        if self.rng.random() < chance:
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
            self._log(off, text, "shot", pid, passer, zone, points)
            if self.rng.random() < league.and_one[zone]:
                fouler = self._fouler(dfn)
                dfn.athletes[fouler].stats["PF"] += 1
                self._log(dfn, f"{self._name(dfn, fouler)} fouls: and-one", "foul", fouler, pid, "and-one")
                return self._free_throws(off, dfn, pid, 1)
            return False
        self._log(off, f"{shooter.profile.name} misses {label}", "shot", pid, None, zone, 0)
        block_chance = sum(dfn.athletes[p].profile.block for p in dfn.lineup)
        if self.rng.random() < block_chance:
            blocker = self._pick(dfn, dfn.lineup, lambda p: p.block)
            dfn.athletes[blocker].stats["BLK"] += 1
            self._log(dfn, f"blocked by {self._name(dfn, blocker)}", "block", blocker, pid)
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
        defense_weight = sum(dfn.athletes[p].profile.dreb for p in dfn.lineup)
        offense_keeps = self.rng.random() < offense_weight / (offense_weight + defense_weight)
        if not offense_keeps and off.tactics.get("crash_glass", 0.0) > 0:  # everyone crashed: the other team leaks out
            self.leak_out = (dfn, 1 + levers.LEAK_OUT * off.tactics["crash_glass"])
        side = off if offense_keeps else dfn
        kind = "offensive" if offense_keeps else "defensive"
        if self.rng.random() < self.league.team_rebound_share:
            self._log(side, f"{side.tricode} team rebound", "rebound", None, zone=kind)
        else:
            weight = (lambda p: p.oreb) if offense_keeps else (lambda p: p.dreb)
            player = self._pick(side, side.lineup, weight)
            side.athletes[player].stats["OREB" if offense_keeps else "DREB"] += 1
            self._log(side, f"{kind} rebound {self._name(side, player)}", "rebound", player, zone=kind)
        return offense_keeps

    def _turnover(self, off: Side, dfn: Side, pid: int | None) -> None:
        if pid is None:
            off.team_turnovers += 1
            self._log(off, f"{off.tricode} team turnover", "turnover")
            return
        off.athletes[pid].stats["TOV"] += 1
        steal_chance = sum(dfn.athletes[p].profile.steal for p in dfn.lineup)
        if self.rng.random() < steal_chance:
            thief = self._pick(dfn, dfn.lineup, lambda p: p.steal)
            dfn.athletes[thief].stats["STL"] += 1
            self._log(off, f"{self._name(off, pid)} turnover, stolen by {self._name(dfn, thief)}", "turnover", pid, thief)
        else:
            self._log(off, f"{self._name(off, pid)} turnover", "turnover", pid)

    # --- the game loop -----------------------------------------------------------------------------

    def _run_clock(self, seconds: float) -> None:
        self.clock -= seconds
        self.game_seconds += seconds
        for side in (self.home, self.away):
            on_floor = set(side.lineup)
            for pid, athlete in side.athletes.items():
                athlete.run(seconds, pid in on_floor)

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
            if seconds >= self.clock:
                self._run_clock(self.clock)
                return False
            doubled = dfn.double_team if dfn.double_team in off.lineup else None  # shown on the court as two defenders
            self._log(off, "", "chance", other=doubled, zone="first" if first else "second", tactics=self._calls(off, dfn))
            self._run_clock(seconds)
            if first:
                off.possessions += 1
            breaking = first and self.leak_out is not None and self.leak_out[0] is off
            self.break_bonus, self.leak_out = (self.leak_out[1] if breaking else 1.0), None
            keeps = self._chance(off, dfn)
            self.break_bonus = 1.0
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
