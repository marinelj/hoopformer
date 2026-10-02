"""Play an NBA game possession by possession, with real players' rates.

One loop and one seeded random generator: the same seed replays the same game,
which makes games testable and shareable. Each possession is one or more
chances (see actions.py); each chance picks who acts and what they do, in
proportion to the five players' rates and adjusted for the defense and home
court, then resolves makes, assists, blocks, rebounds, steals and fouls.

Day 1 rotation: each player's minutes follow their real minutes per game, and
the coach sends in whoever is furthest behind their share. Day 2 replaces this
with fatigue and a proper AI coach.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field

import pandas as pd

from hoopformer.game.actions import EVENTS, ZONES
from hoopformer.game.model import ActionModel, PlayerProfile, TeamDefense

PERIOD_SECONDS = 720.0
OVERTIME_SECONDS = 300.0
FOUL_OUT = 6
ROSTER_SIZE = 13
ROTATION_CHECK_SECONDS = 180.0
SWAP_MARGIN_SECONDS = 60.0  # bring a player in only if they're this far behind their share
MAX_SHARE = 0.9  # no one plays more than 90% of the game
SETTLED_GAMES = 10  # minutes per game from fewer games are scaled down: two 35-minute cameos aren't a starter
POINTS = {"rim": 2, "mid": 2, "three": 3}
BOX_COLUMNS = ["MIN", "PTS", "FGM", "FGA", "3PM", "3PA", "FTM", "FTA", "OREB", "DREB", "REB", "AST", "STL", "BLK", "TOV", "PF"]


@dataclass
class Athlete:
    profile: PlayerProfile
    seconds: float = 0.0
    stats: Counter = field(default_factory=Counter)

    @property
    def fouled_out(self) -> bool:
        return self.stats["PF"] >= FOUL_OUT


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


@dataclass
class Event:
    period: int
    clock: float  # seconds left in the period
    team: str
    text: str
    home_score: int
    away_score: int
    kind: str = ""          # period_start, period_end, chance, shot, block, rebound, turnover, foul, free_throws, sub
    actor: int | None = None  # who did it (shooter, rebounder, fouler, player coming in...)
    other: int | None = None  # the second player involved (passer, thief, blocked shooter, fouled player, player going out)
    zone: str | None = None   # shot zone; "offensive"/"defensive" for rebounds; foul type; "first"/"second" chance
    value: int = 0            # points on a shot; free throws made
    attempts: int = 0         # free throws attempted
    home_lineup: tuple[int, ...] = ()
    away_lineup: tuple[int, ...] = ()


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


def minute_shares(profiles: list[PlayerProfile]) -> dict[int, float]:
    """Each player's target share of game time, summing to 5 (five players on the floor).

    Like a real coach: the regulars get their real minutes per game, most minutes
    first, until the 240 team minutes are used up; the end of the bench gets what
    is left, which is often nothing.
    """
    def expected(p: PlayerProfile) -> float:
        return p.minutes_per_game * min(1.0, p.games / SETTLED_GAMES)

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
    """The team's players at the end of the season, most minutes first."""
    players = [p for p in model.players.values() if p.team_id == team_id]
    players.sort(key=lambda p: p.minutes_per_game * p.games, reverse=True)
    return [p.person_id for p in players[:size]]


class Game:
    def __init__(self, model: ActionModel, home_team_id: int, away_team_id: int, seed: int,
                 home_roster: list[int] | None = None, away_roster: list[int] | None = None):
        self.model = model
        self.league = model.league
        self.seed = seed
        self.rng = random.Random(seed)
        self.home = self._side(home_team_id, True, home_roster or default_roster(model, home_team_id))
        self.away = self._side(away_team_id, False, away_roster or default_roster(model, away_team_id))
        self.events: list[Event] = []
        self.period = 1
        self.clock = PERIOD_SECONDS
        self.game_seconds = 0.0
        self.last_rotation = -ROTATION_CHECK_SECONDS
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
        side.lineup = sorted(roster, key=lambda pid: share[pid], reverse=True)[:5]
        return side

    # --- bookkeeping -------------------------------------------------------------------------------

    def _log(self, side: Side, text: str, kind: str = "", actor: int | None = None, other: int | None = None,
             zone: str | None = None, value: int = 0, attempts: int = 0) -> None:
        self.events.append(Event(self.period, round(self.clock, 1), side.tricode, text, self.home.points, self.away.points,
                                 kind, actor, other, zone, value, attempts,
                                 tuple(self.home.lineup), tuple(self.away.lineup)))

    def _name(self, side: Side, pid: int) -> str:
        return side.athletes[pid].profile.name

    def _pick(self, side: Side, players: list[int], weight) -> int:
        return self.rng.choices(players, [weight(side.athletes[p].profile) for p in players])[0]

    def _rotate(self, side: Side, force: bool = False) -> None:
        """Swap in whoever is furthest behind their share of game time; starters open halves."""
        available = [pid for pid, a in side.athletes.items() if not a.fouled_out]
        if force:
            new = sorted(available, key=lambda pid: side.share[pid], reverse=True)[:5]
        else:
            need = {pid: side.share[pid] * (self.game_seconds + 60) - side.athletes[pid].seconds for pid in available}
            new = [pid for pid in side.lineup if pid in need]
            bench = sorted((pid for pid in available if pid not in new), key=need.get, reverse=True)
            while len(new) < 5 and bench:
                new.append(bench.pop(0))
            for _ in range(5):
                if not bench:
                    break
                tired = min(new, key=need.get)
                fresh = bench[0]
                if need[fresh] - need[tired] < SWAP_MARGIN_SECONDS:
                    break
                new[new.index(tired)] = bench.pop(0)
                bench.append(tired)
                bench.sort(key=need.get, reverse=True)
        leaving = [p for p in side.lineup if p not in new]
        entering = [p for p in new if p not in side.lineup]
        side.lineup = new
        for out, inn in zip(leaving, entering):
            self._log(side, f"SUB: {self._name(side, inn)} for {self._name(side, out)}", "sub", inn, out)

    # --- one chance --------------------------------------------------------------------------------

    def _chance(self, off: Side, dfn: Side) -> bool:
        """Play one chance. Returns True if the offense keeps the ball (offensive rebound)."""
        league = self.league
        if self.rng.random() < self.silent_foul_rate:
            fouler = self._pick(dfn, dfn.lineup, lambda p: p.foul)
            dfn.athletes[fouler].stats["PF"] += 1
            self._log(dfn, f"{self._name(dfn, fouler)} personal foul", "foul", fouler, zone="personal")
        choices, weights = [], []
        for pid in off.lineup:
            profile = off.athletes[pid].profile
            for event in EVENTS:
                weight = profile.events[event]
                if event == "turnover":
                    weight *= dfn.defense.turnover_factor
                elif event == "free_throws":
                    weight *= dfn.defense.free_throw_factor
                choices.append((pid, event))
                weights.append(weight)
        choices.append((None, "turnover"))
        weights.append(league.team_turnover_rate * dfn.defense.turnover_factor)
        pid, event = self.rng.choices(choices, weights)[0]
        if event in ZONES:
            return self._shot(off, dfn, pid, event)
        if event == "turnover":
            self._turnover(off, dfn, pid)
            return False
        shots = 3 if self.rng.random() < league.three_shot_trip_share else 2
        fouler = self._pick(dfn, dfn.lineup, lambda p: p.foul)
        dfn.athletes[fouler].stats["PF"] += 1
        self._log(dfn, f"{self._name(dfn, fouler)} shooting foul on {self._name(off, pid)}", "foul", fouler, pid, "shooting")
        return self._free_throws(off, dfn, pid, shots)

    def _shot(self, off: Side, dfn: Side, pid: int, zone: str) -> bool:
        league, shooter = self.league, off.athletes[pid]
        home_factor = league.home_make_factor if off.is_home else league.away_make_factor
        chance = min(0.98, max(0.02, shooter.profile.make[zone] * dfn.defense.make_factor[zone] * home_factor))
        shooter.stats["FGA"] += 1
        if zone == "three":
            shooter.stats["3PA"] += 1
        label = {"rim": "at the rim", "mid": "midrange", "three": "3PT"}[zone]
        if self.rng.random() < chance:
            points = POINTS[zone]
            shooter.stats["FGM"] += 1
            shooter.stats["3PM"] += zone == "three"
            shooter.stats["PTS"] += points
            off.points += points
            text = f"{shooter.profile.name} makes {label} ({shooter.stats['PTS']} PTS)"
            passer = None
            if self.rng.random() < shooter.profile.assisted[zone]:
                mates = [p for p in off.lineup if p != pid]
                passer = self._pick(off, mates, lambda p: p.assist)
                off.athletes[passer].stats["AST"] += 1
                text += f", assist {self._name(off, passer)}"
            self._log(off, text, "shot", pid, passer, zone, points)
            if self.rng.random() < league.and_one[zone]:
                fouler = self._pick(dfn, dfn.lineup, lambda p: p.foul)
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
                off.points += 1
            elif number == shots:
                self._log(off, f"{shooter.profile.name} free throws {made}/{shots}", "free_throws", pid, value=made, attempts=shots)
                return self._rebound(off, dfn)
        self._log(off, f"{shooter.profile.name} free throws {made}/{shots}", "free_throws", pid, value=made, attempts=shots)
        return False

    def _rebound(self, off: Side, dfn: Side) -> bool:
        offense_weight = sum(off.athletes[p].profile.oreb for p in off.lineup)
        defense_weight = sum(dfn.athletes[p].profile.dreb for p in dfn.lineup)
        offense_keeps = self.rng.random() < offense_weight / (offense_weight + defense_weight)
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
            for pid in side.lineup:
                side.athletes[pid].seconds += seconds

    def _possession(self, off: Side, dfn: Side) -> bool:
        """Play one possession. Returns False if the period clock ran out first."""
        first = True
        while True:
            durations = self.league.first_chance_seconds if first else self.league.second_chance_seconds
            seconds = self.rng.choice(durations)
            if seconds >= self.clock:
                self._run_clock(self.clock)
                return False
            self._log(off, "", "chance", zone="first" if first else "second")
            self._run_clock(seconds)
            if first:
                off.possessions += 1
            if not self._chance(off, dfn):
                return True
            first = False

    def play(self) -> GameResult:
        tip_winner = self.home if self.rng.random() < 0.5 else self.away
        tip_loser = self.away if tip_winner is self.home else self.home
        while self.period <= 4 or self.home.points == self.away.points:
            self.clock = PERIOD_SECONDS if self.period <= 4 else OVERTIME_SECONDS
            if self.period in (1, 3):
                for side in (self.home, self.away):
                    self._rotate(side, force=True)
            if self.period <= 4:
                offense = tip_winner if self.period in (1, 4) else tip_loser
            else:
                offense = self.home if self.rng.random() < 0.5 else self.away
            self._log(offense, f"Start of period {self.period}", "period_start")
            while self.clock > 0:
                defense = self.away if offense is self.home else self.home
                if not self._possession(offense, defense):
                    break
                offense = defense
                if self.game_seconds - self.last_rotation >= ROTATION_CHECK_SECONDS or any(
                        side.athletes[p].fouled_out for side in (self.home, self.away) for p in side.lineup):
                    for side in (self.home, self.away):
                        self._rotate(side)
                    self.last_rotation = self.game_seconds
            self._log(offense, f"End of period {self.period}", "period_end")
            self.period += 1
        return GameResult(self.seed, self.home, self.away, self.period - 1, self.events)
