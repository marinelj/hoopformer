"""Turn counted actions into the rates the game engine plays with.

Every rate is pulled toward the league average in proportion to how little
we've seen of a player ("shrinkage"):

    rate = (what the player did + k × league rate) / (opportunities + k)

With 10 opportunities a player sits almost at the league average; with
thousands, their own record dominates. k is the number of league-average
opportunities mixed in, chosen per skill: free throws settle fast, three-point
shooting slowly.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from hoopformer.game.actions import EVENTS, ZONES

# How many league-average opportunities each rate is mixed with.
PRIOR = {"events": 300, "rim": 60, "mid": 60, "three": 150, "assisted": 40, "ft": 40,
         "assist": 200, "oreb": 200, "dreb": 200, "steal": 100, "block": 200, "foul": 300, "defense": 400}


@dataclass
class League:
    event_rate: dict[str, float]         # per player per chance on the floor
    make: dict[str, float]               # field-goal % by zone
    assisted: dict[str, float]           # share of makes that are assisted, by zone
    and_one: dict[str, float]            # share of makes with an and-one free throw, by zone
    ft_pct: float
    three_shot_trip_share: float         # free-throw trips with three shots (fouled on a three)
    assist_rate: float                   # assists per teammate make
    oreb_rate: float                     # per player per own-team miss
    dreb_rate: float                     # per player per opponent miss
    team_rebound_share: float            # misses that end in a team (not player) rebound
    steal_rate: float                    # per defender per opponent turnover
    block_rate: float                    # per defender per opponent miss
    foul_rate: float                     # per defender per defended chance
    team_turnover_rate: float            # per chance (shot clock and other team turnovers)
    home_make_factor: float
    away_make_factor: float
    home_win_share: float
    first_chance_seconds: list[float] = field(repr=False)
    second_chance_seconds: list[float] = field(repr=False)


@dataclass
class PlayerProfile:
    person_id: int
    name: str
    team_id: int
    games: int
    minutes_per_game: float
    events: dict[str, float]
    make: dict[str, float]
    assisted: dict[str, float]
    ft_pct: float
    assist: float
    oreb: float
    dreb: float
    steal: float
    block: float
    foul: float


@dataclass
class TeamDefense:
    team_id: int
    tricode: str
    name: str
    make_factor: dict[str, float]        # opponents' make rate vs league, by zone
    turnover_factor: float
    free_throw_factor: float


@dataclass
class ActionModel:
    season: str
    league: League
    players: dict[int, PlayerProfile]
    teams: dict[int, TeamDefense]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self)), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "ActionModel":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            season=raw["season"],
            league=League(**raw["league"]),
            players={int(k): PlayerProfile(**v) for k, v in raw["players"].items()},
            teams={int(k): TeamDefense(**v) for k, v in raw["teams"].items()},
        )


def shrink(count: float, opportunities: float, league_rate: float, prior: float) -> float:
    """The player's rate, pulled toward the league rate (see module docstring)."""
    return float((count + prior * league_rate) / (opportunities + prior))


def fit_action_model(players: pd.DataFrame, teams: pd.DataFrame, extras: dict, season: str) -> ActionModel:
    """Rates for every player who appeared, plus league constants and team defenses."""
    total = players.sum()
    player_chances = total["chances"]
    made = {zone: total[f"{zone}_made"] for zone in ZONES}
    attempts = {zone: total[zone] for zone in ZONES}
    team_chances = teams["chances"].sum()
    misses = teams["misses"].sum()
    # Home court: real home teams outscore visitors by `margin` points a game, through shooting,
    # free throws, turnovers and rebounding together. The engine puts all of it into shooting:
    # home makes rise and away makes fall by the share of field-goal points that closes the gap.
    totals = extras["team_totals"]
    field_goal_points = (2 * totals["fieldGoalsMade"] + totals["threePointersMade"]) / (2 * extras["games"])
    margin = extras["home_margin"] / extras["games"]
    home_shift = margin / 2 / field_goal_points

    league = League(
        event_rate={event: float(total[event] / player_chances) for event in EVENTS},
        make={zone: float(made[zone] / attempts[zone]) for zone in ZONES},
        assisted={zone: float(total[f"{zone}_assisted"] / made[zone]) for zone in ZONES},
        and_one={zone: float(total.get(f"{zone}_and_one", 0) / made[zone]) for zone in ZONES},
        ft_pct=float(total["ft_made"] / total["ft_attempts"]),
        three_shot_trip_share=float(total["three_shot_trips"] / total["free_throws"]),
        assist_rate=float(total["assists"] / total["teammate_makes"]),
        oreb_rate=float(total["oreb"] / total["oreb_chances"]),
        dreb_rate=float(total["dreb"] / total["dreb_chances"]),
        team_rebound_share=float(1 - (total["oreb"] + total["dreb"]) / misses),
        steal_rate=float(total["steals"] / total["opp_turnovers"]),
        block_rate=float(total["blocks"] / total["opp_misses"]),
        foul_rate=float(total["fouls"] / total["defended_chances"]),
        team_turnover_rate=float(teams["team_turnovers"].sum() / team_chances),
        home_make_factor=float(1 + home_shift),
        away_make_factor=float(1 - home_shift),
        home_win_share=float(extras["home_wins"] / extras["games"]),
        first_chance_seconds=[round(s, 1) for s in extras["durations"]["first"]],
        second_chance_seconds=[round(s, 1) for s in extras["durations"]["second"]],
    )

    profiles = {}
    for person_id, row in players.iterrows():
        info = extras["players"].get(int(person_id))
        if info is None or info["games"] == 0:
            continue
        profiles[int(person_id)] = PlayerProfile(
            person_id=int(person_id), name=info["name"], team_id=info["team_id"], games=info["games"],
            minutes_per_game=info["seconds"] / info["games"] / 60,
            events={e: shrink(row[e], row["chances"], league.event_rate[e], PRIOR["events"]) for e in EVENTS},
            make={z: shrink(row[f"{z}_made"], row[z], league.make[z], PRIOR[z]) for z in ZONES},
            assisted={z: shrink(row[f"{z}_assisted"], row[f"{z}_made"], league.assisted[z], PRIOR["assisted"]) for z in ZONES},
            ft_pct=shrink(row["ft_made"], row["ft_attempts"], league.ft_pct, PRIOR["ft"]),
            assist=shrink(row["assists"], row["teammate_makes"], league.assist_rate, PRIOR["assist"]),
            oreb=shrink(row["oreb"], row["oreb_chances"], league.oreb_rate, PRIOR["oreb"]),
            dreb=shrink(row["dreb"], row["dreb_chances"], league.dreb_rate, PRIOR["dreb"]),
            steal=shrink(row["steals"], row["opp_turnovers"], league.steal_rate, PRIOR["steal"]),
            block=shrink(row["blocks"], row["opp_misses"], league.block_rate, PRIOR["block"]),
            foul=shrink(row["fouls"], row["defended_chances"], league.foul_rate, PRIOR["foul"]),
        )

    defenses = {}
    league_turnovers = teams["opp_turnovers"].sum() / team_chances
    league_free_throws = teams["opp_free_throws"].sum() / team_chances
    for team_id, row in teams.iterrows():
        info = extras["teams"].get(int(team_id), {"tricode": str(team_id), "name": str(team_id)})
        defenses[int(team_id)] = TeamDefense(
            team_id=int(team_id), tricode=info["tricode"], name=info["name"],
            make_factor={z: shrink(row[f"opp_{z}_made"], row[f"opp_{z}"], league.make[z], PRIOR["defense"]) / league.make[z] for z in ZONES},
            turnover_factor=shrink(row["opp_turnovers"], row["chances"], league_turnovers, PRIOR["defense"]) / league_turnovers,
            free_throw_factor=shrink(row["opp_free_throws"], row["chances"], league_free_throws, PRIOR["defense"]) / league_free_throws,
        )
    return ActionModel(season=season, league=league, players=profiles, teams=defenses)
