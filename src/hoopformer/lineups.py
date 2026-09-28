"""Rebuild who was on the floor for every second of a game.

The play-by-play never lists the ten players on the floor. We rebuild them:

1. The box score says who started the game.
2. For later periods, a player was on the floor at the start if they show up
   in the play-by-play (a shot, rebound, foul, being subbed out...) before
   being subbed in.
3. Each substitution swaps one player. The row gives the leaving player's id,
   but names the entering player only in text ("SUB: Eason FOR Smith Jr."),
   so we match that name against the team's box score.

Step 2 can come up short: a player who is swapped in during the break and
records nothing all period leaves no trace. For those open spots we try every
player who could fill them and keep the one choice under which each player's
rebuilt minutes match the official box score to the second. The box score is
the referee.

The result is a list of stints: stretches of game time with the same ten
players on the floor.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations, product

REGULATION_PERIOD = 720.0  # seconds in quarters 1-4
OVERTIME_PERIOD = 300.0
SUBSTITUTION = "Substitution"
NOT_ON_FLOOR_EVENTS = {"Ejection"}  # can happen to a player on the bench
SUB_PATTERN = re.compile(r"^SUB: (?P<entering>.+) FOR (?P<leaving>.+)$")
MAX_FILL_ATTEMPTS = 20_000


class LineupError(ValueError):
    """The play-by-play and box score can't be reconciled into five players per side."""


@dataclass(frozen=True)
class Stint:
    game_id: str
    period: int
    start: float  # seconds since tip-off
    end: float
    home: tuple[int, ...]  # five personIds, sorted
    away: tuple[int, ...]

    @property
    def seconds(self) -> float:
        return self.end - self.start


def clock_seconds(clock: str) -> float:
    """Seconds left in the period from an ISO clock like 'PT06M40.00S'."""
    match = re.fullmatch(r"PT(\d+)M([\d.]+)S", clock)
    if match is None:
        raise ValueError(f"unexpected clock {clock!r}")
    return int(match.group(1)) * 60 + float(match.group(2))


def period_length(period: int) -> float:
    return REGULATION_PERIOD if period <= 4 else OVERTIME_PERIOD


def period_start(period: int) -> float:
    """Seconds since tip-off when a period begins."""
    if period <= 4:
        return (period - 1) * REGULATION_PERIOD
    return 4 * REGULATION_PERIOD + (period - 5) * OVERTIME_PERIOD


def elapsed(period: int, clock: str) -> float:
    """Seconds since tip-off at a given period and game clock."""
    return period_start(period) + period_length(period) - clock_seconds(clock)


def box_seconds(minutes: str) -> float:
    """Seconds played from a box-score minutes string like '45:15' ('' means did not play)."""
    if not minutes:
        return 0.0
    whole, _, seconds = minutes.partition(":")
    return int(whole) * 60 + float(seconds or 0)


def team_rosters(box: dict) -> dict[int, list[dict]]:
    """Each team's players from the box score, keyed by teamId."""
    rosters = {}
    for side in ("homeTeam", "awayTeam"):
        team = box[side]
        rosters[team["teamId"]] = [
            {
                "personId": player["personId"],
                "firstName": player["firstName"],
                "familyName": player["familyName"],
                "nameI": player["nameI"],
                "starter": bool(player["position"]),
                "seconds": box_seconds(player["statistics"]["minutes"]),
            }
            for player in team["players"]
        ]
    return rosters


def plain(name: str) -> str:
    """Strip accents so 'Dončić' in the box score matches 'Doncic' in the play-by-play."""
    return "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))


def name_matches(name: str, player: dict) -> bool:
    """Does substitution text like 'Eason', 'J. Williams', 'Jay. Williams' or 'Hansen' name this player?

    The play-by-play uses the family name; an initial ('J. Williams') or a longer
    first-name prefix ('Jay. Williams') when teammates share it; and for a few
    players the name they go by, which the box score stores as the first name.
    """
    name = plain(name)
    first, family = plain(player["firstName"]), plain(player["familyName"])
    if name in (family, plain(player["nameI"]), first):
        return True
    prefix, dot, rest = name.partition(". ")
    return bool(dot) and rest == family and first.startswith(prefix)


def resolve_player(name: str, roster: list[dict], on_floor: set[int] | None = None) -> int:
    """personId of the player a substitution names as entering the game.

    Players who never played can't enter, and neither can anyone already on the floor.
    """
    candidates = [p for p in roster if name_matches(name, p) and p["seconds"] > 0]
    if on_floor is not None and len(candidates) > 1:
        candidates = [p for p in candidates if p["personId"] not in on_floor]
    if len(candidates) != 1:
        raise LineupError(f"can't resolve entering player {name!r}: {len(candidates)} candidates")
    return candidates[0]["personId"]


def entering_name(description: str) -> str:
    match = SUB_PATTERN.match(description)
    if match is None:
        raise LineupError(f"unexpected substitution text {description!r}")
    return match.group("entering")


def is_on_floor_event(action: dict, player_ids: set[int]) -> bool:
    """True if this action proves its player was on the floor at that moment."""
    if action["personId"] not in player_ids or action["actionType"] in NOT_ON_FLOOR_EVENTS:
        return False
    return "Technical" not in action["subType"]  # technicals can be called on the bench


def period_evidence(actions: list[dict], team_id: int, roster: list[dict]) -> tuple[set[int], set[int]]:
    """Players proven on the floor when the period began, and players subbed in during it."""
    player_ids = {p["personId"] for p in roster}
    starters: set[int] = set()
    subbed_in: set[int] = set()
    for action in actions:
        if action["teamId"] != team_id:
            continue
        if action["actionType"] == SUBSTITUTION:
            if action["personId"] not in subbed_in:
                starters.add(action["personId"])
            subbed_in.add(resolve_player(entering_name(action["description"]), roster))
        elif is_on_floor_event(action, player_ids) and action["personId"] not in subbed_in:
            starters.add(action["personId"])
    return starters, subbed_in


def replay(game_id: str, by_period: dict[int, list[dict]], rosters: dict[int, list[dict]],
           home_id: int, away_id: int, starters: dict[tuple[int, int], set[int]]) -> list[Stint]:
    """Walk every substitution from known period-start lineups and cut the game into stints."""
    stints: list[Stint] = []
    for period in sorted(by_period):
        on_floor = {team: set(starters[period, team]) for team in (home_id, away_id)}
        start = period_start(period)

        def close(end: float) -> None:
            if end > start:
                stints.append(Stint(game_id, period, start, end,
                                    tuple(sorted(on_floor[home_id])), tuple(sorted(on_floor[away_id]))))

        for action in by_period[period]:
            if action["actionType"] != SUBSTITUTION:
                continue
            team = action["teamId"]
            now = elapsed(period, action["clock"])
            close(now)
            start = now
            leaving = action["personId"]
            entering = resolve_player(entering_name(action["description"]), rosters[team], on_floor[team])
            if leaving not in on_floor[team] or entering in on_floor[team]:
                raise LineupError(f"{game_id} P{period} {action['clock']}: impossible substitution {action['description']!r}")
            on_floor[team] = (on_floor[team] - {leaving}) | {entering}
        close(period_start(period) + period_length(period))
    return stints


def reconstruct_game(pbp: dict, box: dict) -> list[Stint]:
    """Every stretch of the game with the same ten players on the floor."""
    game_id = box["gameId"]
    home_id, away_id = box["homeTeamId"], box["awayTeamId"]
    rosters = team_rosters(box)
    by_period: dict[int, list[dict]] = defaultdict(list)
    for action in pbp["game"]["actions"]:
        by_period[action["period"]].append(action)

    starters: dict[tuple[int, int], set[int]] = {}
    open_spots: list[tuple[tuple[int, int], int, list[int]]] = []  # (period, team), spots, candidates
    for period in sorted(by_period):
        for team in (home_id, away_id):
            if period == 1:
                found = {p["personId"] for p in rosters[team] if p["starter"]}
                if len(found) != 5:
                    raise LineupError(f"{game_id} team {team}: box score lists {len(found)} starters")
                starters[period, team] = found
                continue
            found, subbed_in = period_evidence(by_period[period], team, rosters[team])
            if len(found) > 5:
                raise LineupError(f"{game_id} P{period} team {team}: {len(found)} players on the floor at the start")
            starters[period, team] = found
            if len(found) < 5:
                pool = sorted(p["personId"] for p in rosters[team]
                              if p["seconds"] > 0 and p["personId"] not in found | subbed_in)
                open_spots.append(((period, team), 5 - len(found), pool))

    if not open_spots:
        return replay(game_id, by_period, rosters, home_id, away_id, starters)

    choices = [list(combinations(pool, spots)) for _, spots, pool in open_spots]
    attempts = 1
    for options in choices:
        attempts *= len(options)
    if attempts > MAX_FILL_ATTEMPTS:
        raise LineupError(f"{game_id}: {attempts} ways to fill open spots, too many to check")

    solutions = []
    for picks in product(*choices):
        trial = dict(starters)
        for (key, _, _), picked in zip(open_spots, picks):
            trial[key] = starters[key] | set(picked)
        try:
            stints = replay(game_id, by_period, rosters, home_id, away_id, trial)
        except LineupError:
            continue
        if not audit_minutes(stints, box):
            solutions.append(stints)
    if len(solutions) != 1:
        spots = [f"P{period} team {team}" for (period, team), _, _ in open_spots]
        raise LineupError(f"{game_id}: {len(solutions)} ways to fill {spots} match the box score")
    return solutions[0]


def player_seconds(stints: list[Stint]) -> dict[int, float]:
    """Total time on the floor per player, summed over stints."""
    totals: dict[int, float] = defaultdict(float)
    for stint in stints:
        for player in stint.home + stint.away:
            totals[player] += stint.seconds
    return dict(totals)


def audit_minutes(stints: list[Stint], box: dict, tolerance: float = 1.0) -> list[dict]:
    """Players whose rebuilt time differs from the official box score by more than `tolerance` seconds."""
    rebuilt = player_seconds(stints)
    mismatches = []
    for roster in team_rosters(box).values():
        for player in roster:
            diff = rebuilt.get(player["personId"], 0.0) - player["seconds"]
            if abs(diff) > tolerance:
                mismatches.append({"personId": player["personId"], "name": player["nameI"],
                                   "rebuilt": rebuilt.get(player["personId"], 0.0), "official": player["seconds"], "diff": diff})
    return mismatches
