"""Count points and possessions for every stint.

A possession is one team's turn with the ball. It ends when that team

- makes a field goal (or, on an and-one, after the free throw that follows),
- loses the ball on a defensive rebound,
- turns the ball over,
- makes the last free throw of a trip, or
- runs out of time at the end of a period.

Technical, flagrant and clear-path free throws never hand the ball over.

Points come from the running score on scoring rows (other rows sometimes carry
a stale score), so every point lands in the stint that was on the floor when
it was scored. A possession is credited to the stint
on the floor when it ended. Those two rules are what RAPM needs: for each
stint, how many points each side scored per possession.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from hoopformer.lineups import SUBSTITUTION, Stint, elapsed

FINAL_FREE_THROW = re.compile(r"(\d+) of (\d+)$")
BALL_KEEPING_FREE_THROWS = ("Technical", "Flagrant", "Clear Path")
SCORING_ACTIONS = {"Made Shot", "Free Throw", "Heave"}  # other rows can carry a stale score


@dataclass
class StintTotals:
    stint: Stint
    home_points: int = 0
    away_points: int = 0
    home_possessions: int = 0
    away_possessions: int = 0


def action_team(action: dict, team_ids: set[int]) -> int | None:
    """The team an action belongs to. Team rebounds and turnovers carry the team id in personId."""
    if action["teamId"] in team_ids:
        return action["teamId"]
    if action["personId"] in team_ids:
        return action["personId"]
    return None


def is_final_free_throw(sub_type: str) -> bool:
    """'Free Throw 2 of 2' ends the trip; '1 of 2' doesn't."""
    match = FINAL_FREE_THROW.search(sub_type)
    return match is not None and match.group(1) == match.group(2)


def keeps_ball(sub_type: str) -> bool:
    """Free throws after which the shooting team keeps the ball (or that don't involve it)."""
    return any(kind in sub_type for kind in BALL_KEEPING_FREE_THROWS)


def is_missed(action: dict) -> bool:
    return action["description"].startswith("MISS")


def possession_ends(actions: list[dict], team_ids: set[int]) -> list[tuple[int, int]]:
    """(action index, team) for every possession end, in game order.

    A made field goal only ends the possession once we know no and-one free
    throw follows, so it waits as `pending` until the next event that matters.
    """
    ends: list[tuple[int, int]] = []
    offense: int | None = None
    pending: tuple[int, int, str] | None = None  # (index, team, clock) of a made field goal

    def end(index: int, team: int) -> None:
        nonlocal offense
        ends.append((index, team))
        offense = (team_ids - {team}).pop()

    for index, action in enumerate(actions):
        kind = action["actionType"]
        team = action_team(action, team_ids)
        matters = kind in ("Made Shot", "Missed Shot", "Free Throw", "Rebound", "Turnover") or (
            kind == "period" and action["subType"] == "end")
        if not matters:
            continue

        if pending is not None:
            made_index, made_team, made_clock = pending
            pending = None
            and_one = (kind == "Free Throw" and team == made_team and action["clock"] == made_clock
                       and action["subType"].endswith("1 of 1") and not keeps_ball(action["subType"]))
            if not and_one:
                end(made_index, made_team)

        if kind == "period":
            if offense is not None:
                ends.append((index, offense))
            offense = None
            continue
        if team is None:
            continue
        if kind == "Made Shot":
            offense = team
            pending = (index, team, action["clock"])
        elif kind == "Missed Shot":
            offense = team
        elif kind == "Free Throw":
            if keeps_ball(action["subType"]):
                continue
            offense = team
            if is_final_free_throw(action["subType"]) and not is_missed(action):
                end(index, team)
        elif kind == "Rebound":
            if offense is not None and team != offense:
                end(index, offense)
            offense = team
        elif kind == "Turnover":
            end(index, team)
    return ends


def stint_totals(pbp: dict, box: dict, stints: list[Stint]) -> list[StintTotals]:
    """Points and possessions per side for each stint, walking the game in order."""
    home_id, away_id = box["homeTeamId"], box["awayTeamId"]
    actions = pbp["game"]["actions"]
    totals = [StintTotals(stint) for stint in stints]

    # Which stint was on the floor at each action: move on at every substitution and new period.
    position, current, stint_at = 0, 0, []
    for action in actions:
        if action["period"] != stints[current].period or action["actionType"] == SUBSTITUTION:
            now = elapsed(action["period"], action["clock"])
            position = current
            while position < len(stints) and (stints[position].period, stints[position].start) < (action["period"], now):
                position += 1
            if position < len(stints) and stints[position].period == action["period"]:
                current = position
        stint_at.append(current)

    home_score = away_score = 0
    for index, action in enumerate(actions):
        if action["actionType"] not in SCORING_ACTIONS or (action["scoreHome"] == "" and action["scoreAway"] == ""):
            continue
        new_home, new_away = int(action["scoreHome"]), int(action["scoreAway"])
        totals[stint_at[index]].home_points += new_home - home_score
        totals[stint_at[index]].away_points += new_away - away_score
        home_score, away_score = new_home, new_away

    for index, team in possession_ends(actions, {home_id, away_id}):
        if team == home_id:
            totals[stint_at[index]].home_possessions += 1
        else:
            totals[stint_at[index]].away_possessions += 1
    return totals


def audit_points(totals: list[StintTotals], box: dict) -> list[str]:
    """Problems if stint points don't add up to the final score."""
    problems = []
    for side, attr in (("homeTeam", "home_points"), ("awayTeam", "away_points")):
        official = box[side]["statistics"]["points"]
        rebuilt = sum(getattr(t, attr) for t in totals)
        if rebuilt != official:
            problems.append(f"{box[side]['teamTricode']}: stints add up to {rebuilt}, final score {official}")
    return problems
