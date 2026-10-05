"""Classic teams: the 1990s All-Stars and the 2000s All-Stars, each player as he was in one season of his prime.

There is no play-by-play before 1996-97, so these players' engine rates come from their season totals
(stats.nba.com career stats, cached with `hoopformer fetch --legends`). A season total says how often a
player shot, scored, passed, rebounded, stole, blocked and fouled; the engine wants the same things per
chance on the floor (model.PlayerProfile). The bridge is the era's averages below (assumed, typical of the
1990s and 2000s): how many chances a team has per 48 minutes, how many shots it makes and misses, how many
turnovers it forces. Two-point shots are split into rim and midrange from the player's two-point
percentage, since season totals don't say where shots came from.

The players keep their own rates; the league around them (pace, home court, and-ones) is the model's.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from hoopformer.fetch import CAREER, raw_path
from hoopformer.game.actions import ZONES
from hoopformer.game.model import PRIOR, ActionModel, PlayerProfile, TeamDefense, shrink

NINETIES, TWO_THOUSANDS = 1990, 2000   # team ids for the classic teams (real NBA team ids start at 1610612737)
LEGEND_ID = 90_000_000                 # a classic player's id is this plus his real id, so he never clashes with today's
TEAMS = {   # team id: (tricode, name, [(real person id, name, the season he plays as)])
    NINETIES: ("90S", "1990s All-Stars", [
        (893, "Michael Jordan", "1995-96"), (165, "Hakeem Olajuwon", "1993-94"), (937, "Scottie Pippen", "1994-95"),
        (252, "Karl Malone", "1996-97"), (787, "Charles Barkley", "1992-93"), (764, "David Robinson", "1994-95"),
        (304, "John Stockton", "1993-94"), (121, "Patrick Ewing", "1992-93"), (56, "Gary Payton", "1997-98"),
        (17, "Clyde Drexler", "1991-92"), (397, "Reggie Miller", "1997-98"), (23, "Dennis Rodman", "1995-96"),
    ]),
    TWO_THOUSANDS: ("00S", "2000s All-Stars", [
        (977, "Kobe Bryant", "2005-06"), (406, "Shaquille O'Neal", "1999-00"), (1495, "Tim Duncan", "2001-02"),
        (708, "Kevin Garnett", "2003-04"), (947, "Allen Iverson", "2000-01"), (1717, "Dirk Nowitzki", "2006-07"),
        (2544, "LeBron James", "2008-09"), (2548, "Dwyane Wade", "2008-09"), (959, "Steve Nash", "2004-05"),
        (1503, "Tracy McGrady", "2002-03"), (1718, "Paul Pierce", "2005-06"), (467, "Jason Kidd", "2001-02"),
    ]),
}
# The era's averages per 48 minutes of one team (assumed: typical of 1990s and 2000s seasons).
PACE = 92.0                # possessions
CHANCES_PER_POSSESSION = 1.14  # a second chance after an offensive rebound is another chance
TEAM_FGM, TEAM_MISSES = 37.5, 44.0
TEAM_TURNOVERS = 15.0      # forced by the defense: what a steal is out of
RIM_MAKE, MID_MAKE = 0.59, 0.40  # make rates at the rim and from midrange, to split a player's twos
AND_ONE_FTS = 0.05         # free throws from and-ones, per made shot
FTS_PER_TRIP = 2.05        # free throws per trip to the line (a few are three-shot trips)


def person_ids() -> list[int]:
    """Every classic player's real stats.nba.com id, for `hoopformer fetch --legends`."""
    return [pid for _, _, roster in TEAMS.values() for pid, _, _ in roster]


def season_totals(data_dir: Path, person_id: int, season: str) -> dict:
    """One player's regular-season totals for one season (his whole season, if he was traded)."""
    data = json.loads(raw_path(data_dir, CAREER, str(person_id)).read_text(encoding="utf-8"))
    table = next(t for t in data["resultSets"] if t["name"] == "SeasonTotalsRegularSeason")
    rows = [dict(zip(table["headers"], row)) for row in table["rowSet"] if row[table["headers"].index("SEASON_ID")] == season]
    if not rows:
        raise ValueError(f"no {season} season for player {person_id}")
    return next((r for r in rows if r["TEAM_ABBREVIATION"] == "TOT"), rows[0])


def profile_from_totals(person_id: int, name: str, team_id: int, row: dict, model: ActionModel) -> PlayerProfile:
    """A season's totals as the engine's per-chance rates."""
    league, floor = model.league, row["MIN"] / 48   # games' worth of time on the floor
    chances = floor * PACE * CHANCES_PER_POSSESSION
    two_tries, two_makes = row["FGA"] - row["FG3A"], row["FGM"] - row["FG3M"]
    two_pct = two_makes / two_tries if two_tries else MID_MAKE
    rim_share = min(0.85, max(0.15, (two_pct - MID_MAKE) / (RIM_MAKE - MID_MAKE)))  # good finishers make more twos
    scale = two_pct / (rim_share * RIM_MAKE + (1 - rim_share) * MID_MAKE)        # so rim and mid add up to his 2P%
    trips = max(0.0, row["FTA"] - AND_ONE_FTS * row["FGM"]) / FTS_PER_TRIP
    misses = floor * TEAM_MISSES
    return PlayerProfile(
        person_id=LEGEND_ID + person_id, name=name, team_id=team_id, games=row["GP"], minutes_per_game=row["MIN"] / row["GP"],
        events={"rim": rim_share * two_tries / chances, "mid": (1 - rim_share) * two_tries / chances, "three": row["FG3A"] / chances,
                "turnover": row["TOV"] / chances, "free_throws": trips / chances},
        make={"rim": min(0.8, RIM_MAKE * scale), "mid": min(0.6, MID_MAKE * scale),
              "three": shrink(row["FG3M"], row["FG3A"], league.make["three"], PRIOR["three"])},
        assisted=dict(league.assisted),
        ft_pct=shrink(row["FTM"], row["FTA"], league.ft_pct, PRIOR["ft"]),
        assist=row["AST"] / max(1.0, floor * TEAM_FGM - row["FGM"]),
        oreb=row["OREB"] / misses, dreb=row["DREB"] / misses,
        steal=row["STL"] / (floor * TEAM_TURNOVERS), block=row["BLK"] / misses,
        foul=row["PF"] / chances,
    )


def cached(data_dir: Path) -> bool:
    return all(raw_path(data_dir, CAREER, str(pid)).exists() for pid in person_ids())


def with_legends(model: ActionModel, data_dir: Path) -> ActionModel:
    """The model plus the two classic teams (tricodes 90S and 00S), with plain average defenses."""
    players, teams = dict(model.players), dict(model.teams)
    for team_id, (code, name, roster) in TEAMS.items():
        teams[team_id] = TeamDefense(team_id=team_id, tricode=code, name=name, make_factor={z: 1.0 for z in ZONES},
                                     turnover_factor=1.0, free_throw_factor=1.0)
        for person_id, player, season in roster:
            profile = profile_from_totals(person_id, player, team_id, season_totals(data_dir, person_id, season), model)
            players[profile.person_id] = profile
    return replace(model, players=players, teams=teams)
