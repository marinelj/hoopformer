"""Learn every player's action rates from real play-by-play.

The game plays each *chance* (a possession's first try, plus one more after
every offensive rebound) as a chain of decisions:

1. who acts, and what they do: a shot at the rim, a midrange shot, a three,
   a turnover, or drawing a shooting foul (free throws);
2. whether the shot goes in;
3. on a make, who assisted; on a miss, who blocked it and who rebounds;
4. on a turnover, who stole it; on a foul, who committed it.

This module counts all of that for every player, from every chance they were
on the floor for. `ActionModel` then turns the counts into rates, pulling
small samples toward the league average, so that 50 lucky minutes don't make
a superstar. Counting is the "training"; it takes seconds, not hours.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from hoopformer.fetch import BOX_SCORE, PLAY_BY_PLAY, SCHEDULE, final_regular_season_game_ids, raw_path
from hoopformer.lineups import LineupError, box_seconds, elapsed, reconstruct_game, resolve_player, team_rosters
from hoopformer.possessions import action_team, game_possessions, is_missed, keeps_ball, stint_at_actions

ZONES = ("rim", "mid", "three")
EVENTS = ("rim", "mid", "three", "turnover", "free_throws")  # how a chance ends, by whoever acts
RIM_FEET = 4.0
ASSIST = re.compile(r"\((?P<name>[^()]+?) \d+ AST\)$")
BOX_TOTALS = ("points", "fieldGoalsMade", "fieldGoalsAttempted", "threePointersMade", "threePointersAttempted",
              "freeThrowsMade", "freeThrowsAttempted", "reboundsOffensive", "reboundsDefensive", "assists",
              "steals", "blocks", "turnovers", "foulsPersonal")
NOT_PERSONAL_FOULS = {"Defense 3 Second", "Flopping", "Bench"}  # plus anything with "Technical" in it


def shot_zone(action: dict) -> str:
    """'three' for a 3-point try, 'rim' within 4 feet, otherwise 'mid'.

    Distance comes from the court coordinates (tenths of a foot from the
    basket), because the distance field is 0 on some shots, e.g. corner threes.
    """
    if action["shotValue"] == 3:
        return "three"
    feet = math.hypot(action["xLegacy"] or 0, action["yLegacy"] or 0) / 10
    return "rim" if feet <= RIM_FEET else "mid"


def is_personal_foul(sub_type: str) -> bool:
    """Fouls that count toward a player's six: everything except technicals and the like."""
    return "Technical" not in sub_type and sub_type not in NOT_PERSONAL_FOULS


def counts_template() -> dict:
    return defaultdict(int)


@dataclass
class GameCounts:
    """Everything counted in one game: per player, per defending team, and chance lengths."""
    players: dict[int, dict] = field(default_factory=lambda: defaultdict(counts_template))
    teams: dict[int, dict] = field(default_factory=lambda: defaultdict(counts_template))  # keyed by the defending team
    first_chance_seconds: list[float] = field(default_factory=list)
    second_chance_seconds: list[float] = field(default_factory=list)
    possessions: int = 0


def count_game(pbp: dict, box: dict) -> GameCounts:
    """Count every chance of one game: who acted, what happened, who was on the floor."""
    home_id, away_id = box["homeTeamId"], box["awayTeamId"]
    teams = {home_id, away_id}
    actions = pbp["game"]["actions"]
    stints = reconstruct_game(pbp, box)
    stint_at = stint_at_actions(actions, stints)
    rosters = team_rosters(box)
    possessions, _ = game_possessions(actions, home_id, away_id)
    counts = GameCounts(possessions=len(possessions))

    def five(index: int, team: int) -> tuple[int, ...]:
        stint = stints[stint_at[index]]
        return stint.home if team == home_id else stint.away

    # Skills that don't depend on the possession: a steal row comes after the
    # turnover that ended the possession, and technical free throws sit outside
    # the possession rules. Count them over the whole game.
    for action in actions:
        actor = action["personId"]
        if actor in teams:
            continue
        if action["actionType"] == "Free Throw":
            counts.players[actor]["ft_attempts"] += 1
            counts.players[actor]["ft_made"] += 0 if is_missed(action) else 1
        elif action["actionType"] == "" and "STEAL" in action["description"]:
            counts.players[actor]["steals"] += 1
        elif action["actionType"] == "" and "BLOCK" in action["description"]:
            counts.players[actor]["blocks"] += 1
        elif action["actionType"] == "Foul" and is_personal_foul(action["subType"]):
            counts.players[actor]["fouls"] += 1

    for possession in possessions:
        offense = possession.team
        defense = (teams - {offense}).pop()
        first = possession.start + 1
        if first > possession.end:
            continue
        chance_start = elapsed(actions[first]["period"], actions[possession.start]["clock"]) if possession.start >= 0 else 0.0
        chance_number, chance_open = 0, True
        last_made: tuple[int, str, str] | None = None  # (shooter, clock, zone) for and-one detection

        def record_length(index: int) -> None:
            """Time from this chance's start to the next chance's start or the possession's end."""
            seconds = elapsed(actions[index]["period"], actions[index]["clock"]) - chance_start
            if seconds >= 0:
                (counts.first_chance_seconds if chance_number == 0 else counts.second_chance_seconds).append(seconds)

        def open_chance(index: int) -> None:
            for player in five(index, offense):
                counts.players[player]["chances"] += 1
            for player in five(index, defense):
                counts.players[player]["defended_chances"] += 1
            counts.teams[defense]["chances"] += 1

        def close_chance(index: int) -> None:
            nonlocal chance_open
            chance_open = False

        open_chance(first)
        for index in range(first, possession.end + 1):
            action = actions[index]
            kind, team, actor = action["actionType"], action_team(action, teams), action["personId"]
            if kind in ("Made Shot", "Missed Shot") and action["isFieldGoal"] == 1 and team == offense:
                zone = shot_zone(action)
                player = counts.players[actor]
                player[zone] += 1
                counts.teams[defense][f"opp_{zone}"] += 1
                if chance_open:
                    close_chance(index)
                if kind == "Made Shot":
                    player[f"{zone}_made"] += 1
                    counts.teams[defense][f"opp_{zone}_made"] += 1
                    last_made = (actor, action["clock"], zone)
                    match = ASSIST.search(action["description"])
                    if match:
                        on_floor = [p for p in rosters[offense] if p["personId"] in five(index, offense) and p["personId"] != actor]
                        try:
                            counts.players[resolve_player(match.group("name"), on_floor)]["assists"] += 1
                        except LineupError:
                            pass
                        counts.players[actor][f"{zone}_assisted"] += 1
                    for teammate in five(index, offense):
                        if teammate != actor:
                            counts.players[teammate]["teammate_makes"] += 1
                else:
                    for player_id in five(index, offense):
                        counts.players[player_id]["oreb_chances"] += 1
                    for player_id in five(index, defense):
                        counts.players[player_id]["dreb_chances"] += 1
                        counts.players[player_id]["opp_misses"] += 1
                    counts.teams[defense]["misses"] += 1
            elif kind == "Turnover" and team == offense:
                if actor in counts.players or actor not in teams:
                    counts.players[actor]["turnover"] += 1 if actor not in teams else 0
                if actor in teams:
                    counts.teams[defense]["team_turnovers"] += 1
                counts.teams[defense]["opp_turnovers"] += 1
                for player_id in five(index, defense):
                    counts.players[player_id]["opp_turnovers"] += 1
                if chance_open:
                    close_chance(index)
            elif kind == "Free Throw" and team == offense and not keeps_ball(action["subType"]):
                player = counts.players[actor]
                sub_type = action["subType"]
                and_one = (sub_type.endswith("1 of 1") and last_made is not None
                           and last_made[0] == actor and last_made[1] == action["clock"])
                if and_one:
                    counts.players[actor][f"{last_made[2]}_and_one"] += 1
                elif sub_type.endswith("1 of 2") or sub_type.endswith("1 of 3") or sub_type.endswith("1 of 1"):
                    player["free_throws"] += 1
                    player["three_shot_trips"] += 1 if sub_type.endswith("1 of 3") else 0
                    counts.teams[defense]["opp_free_throws"] += 1
                    if chance_open:
                        close_chance(index)
                final = re.search(r"(\d+) of (\d+)$", sub_type)
                if final and final.group(1) == final.group(2) and is_missed(action):
                    for player_id in five(index, offense):
                        counts.players[player_id]["oreb_chances"] += 1
                    for player_id in five(index, defense):
                        counts.players[player_id]["dreb_chances"] += 1
                    counts.teams[defense]["misses"] += 1
            elif kind == "Rebound":
                if team == offense:
                    if actor not in teams:
                        counts.players[actor]["oreb"] += 1
                    counts.teams[defense]["opp_oreb"] += 1
                    if index < possession.end:  # an offensive rebound starts another chance
                        record_length(index)
                        chance_number += 1
                        chance_start = elapsed(action["period"], action["clock"])
                        chance_open = True
                        open_chance(index)
                elif team == defense and actor not in teams:
                    counts.players[actor]["dreb"] += 1
        record_length(possession.end)
    return counts


def season_counts(data_dir: Path, season: str, log=print) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Counts for every cached, finished regular-season game of a season.

    Returns per-player counts, per-defending-team counts, and extras: chance
    lengths in seconds, who played for which team and how much, team names,
    box-score totals (also split by home and away), and the number of home wins.
    """
    schedule = json.loads(raw_path(data_dir, SCHEDULE, season).read_text(encoding="utf-8"))
    players: dict[int, dict] = defaultdict(counts_template)
    teams: dict[int, dict] = defaultdict(counts_template)
    durations = {"first": [], "second": []}
    meta: dict[int, dict] = {}
    team_names: dict[int, dict] = {}
    shooting = defaultdict(int)  # home/away field goals, for home-court advantage
    team_totals = defaultdict(int)  # summed box-score team stats, for realism checks
    home_away = {"home": defaultdict(int), "away": defaultdict(int)}  # the same, split by home and away, for home court
    games = skipped = home_wins = possessions = home_margin = 0
    for game_id in final_regular_season_game_ids(schedule):
        pbp_path, box_path = raw_path(data_dir, PLAY_BY_PLAY, game_id), raw_path(data_dir, BOX_SCORE, game_id)
        if not (pbp_path.exists() and box_path.exists()):
            skipped += 1
            continue
        pbp = json.loads(pbp_path.read_text(encoding="utf-8"))
        box = json.loads(box_path.read_text(encoding="utf-8"))["boxScoreTraditional"]
        counts = count_game(pbp, box)
        for player, values in counts.players.items():
            for key, value in values.items():
                players[player][key] += value
        for team, values in counts.teams.items():
            for key, value in values.items():
                teams[team][key] += value
        durations["first"].extend(counts.first_chance_seconds)
        durations["second"].extend(counts.second_chance_seconds)
        for side in ("homeTeam", "awayTeam"):
            team = box[side]
            team_names[team["teamId"]] = {"tricode": team["teamTricode"], "name": f"{team['teamCity']} {team['teamName']}"}
            shooting[f"{side}_made"] += team["statistics"]["fieldGoalsMade"]
            shooting[f"{side}_attempts"] += team["statistics"]["fieldGoalsAttempted"]
            for player in team["players"]:
                seconds = box_seconds(player["statistics"]["minutes"])
                entry = meta.setdefault(player["personId"], {"name": f"{player['firstName']} {player['familyName']}", "games": 0, "seconds": 0.0})
                entry["team_id"] = team["teamId"]  # games are in id order, so the last one wins
                if seconds > 0:
                    entry["games"] += 1
                    entry["seconds"] += seconds
            for stat in BOX_TOTALS:
                team_totals[stat] += team["statistics"][stat]
                home_away["home" if side == "homeTeam" else "away"][stat] += team["statistics"][stat]
        home_wins += box["homeTeam"]["statistics"]["points"] > box["awayTeam"]["statistics"]["points"]
        home_margin += box["homeTeam"]["statistics"]["points"] - box["awayTeam"]["statistics"]["points"]
        possessions += counts.possessions
        games += 1
    log(f"{season}: counted {games} games ({skipped} not downloaded)")
    player_frame = pd.DataFrame.from_dict(players, orient="index").fillna(0).astype(int)
    player_frame.index.name = "personId"
    team_frame = pd.DataFrame.from_dict(teams, orient="index").fillna(0).astype(int)
    team_frame.index.name = "teamId"
    extras = {"durations": durations, "players": meta, "teams": team_names, "shooting": dict(shooting),
              "games": games, "home_wins": home_wins, "home_margin": home_margin, "possessions": possessions, "team_totals": dict(team_totals),
              "home_away": {key: dict(values) for key, values in home_away.items()}}
    return player_frame, team_frame, extras


def hot_hand(data_dir: Path, season: str) -> dict:
    """Do players shoot more, and better, after making their last two shots?

    For every field goal attempt, each player of the shooting team on the floor is in a state from his
    own last two shots of the game: "hot" (both made), "cold" (both missed), "mixed", or "none" (fewer
    than two). Usage: how often he took the team's shot in that state, against his usual share while on
    the floor. Makes: his makes in that state, against his own make rate by zone. 1.0 means no change.
    """
    schedule = json.loads(raw_path(data_dir, SCHEDULE, season).read_text(encoding="utf-8"))
    on = defaultdict(counts_template)      # player -> state -> team shots while he was on the floor
    took = defaultdict(counts_template)    # player -> state -> his shots
    tried = defaultdict(counts_template)   # player -> (state, zone) -> his shots
    made = defaultdict(counts_template)    # player -> (state, zone) -> his makes
    games = 0
    for game_id in final_regular_season_game_ids(schedule):
        pbp_path, box_path = raw_path(data_dir, PLAY_BY_PLAY, game_id), raw_path(data_dir, BOX_SCORE, game_id)
        if not (pbp_path.exists() and box_path.exists()):
            continue
        pbp = json.loads(pbp_path.read_text(encoding="utf-8"))
        box = json.loads(box_path.read_text(encoding="utf-8"))["boxScoreTraditional"]
        try:
            stints = reconstruct_game(pbp, box)
        except LineupError:
            continue
        actions = pbp["game"]["actions"]
        stint_at = stint_at_actions(actions, stints)
        history = defaultdict(list)  # player -> made (True) or missed, for each of his shots so far this game
        for index, action in enumerate(actions):
            if action["actionType"] not in ("Made Shot", "Missed Shot") or action["isFieldGoal"] != 1 or not action["personId"]:
                continue
            shooter, hit = action["personId"], action["actionType"] == "Made Shot"
            stint = stints[stint_at[index]]
            for player in (stint.home if action["teamId"] == box["homeTeamId"] else stint.away):
                last_two = history[player][-2:]
                state = "none" if len(last_two) < 2 else "hot" if all(last_two) else "cold" if not any(last_two) else "mixed"
                on[player][state] += 1
                if player == shooter:
                    took[player][state] += 1
                    tried[player][(state, shot_zone(action))] += 1
                    made[player][(state, shot_zone(action))] += hit
            history[shooter].append(hit)
        games += 1
    result = {"games": games, "usage": {}, "makes": {}}
    for state in ("hot", "mixed", "cold", "none"):
        his = usual = 0.0
        for player, shots in took.items():
            if sum(shots.values()) >= 100:  # regulars only: a usual share needs enough shots
                his += shots[state]
                usual += on[player][state] * sum(shots.values()) / sum(on[player].values())
        result["usage"][state] = his / usual
    for state in ("hot", "mixed", "cold"):
        hits = expected = 0.0
        for player in tried:
            for zone in ZONES:
                zone_tries = sum(v for (s, z), v in tried[player].items() if z == zone)
                if zone_tries >= 50:
                    hits += made[player][(state, zone)]
                    expected += tried[player][(state, zone)] * sum(v for (s, z), v in made[player].items() if z == zone) / zone_tries
        result["makes"][state] = hits / expected
    return result
