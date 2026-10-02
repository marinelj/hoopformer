"""Tests for the game engine: counting actions, the action model, the engine, and realism.

All on real cached 2025-26 games. The realism test is the important one: a
simulated league has to match the real season on 16 statistics.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from hoopformer.fetch import BOX_SCORE, PLAY_BY_PLAY, SCHEDULE, raw_path
from hoopformer.game.actions import EVENTS, ZONES, count_game, is_personal_foul, season_counts, shot_zone
from hoopformer.game import coach
from hoopformer.game.engine import Game, default_roster, minute_shares
from hoopformer.game.model import ActionModel, fit_action_model, shrink
from hoopformer.game.realism import (compare, real_per_team_game, real_rotations, simulate_league, simulated_per_team_game,
                                     simulated_rotations)

DATA = Path("data")
OKC, HOU, SGA = 1610612760, 1610612745, 1628983
EXACT = {"FGA": "fieldGoalsAttempted", "FGM": "fieldGoalsMade", "3PA": "threePointersAttempted",
         "FTA": "freeThrowsAttempted", "FTM": "freeThrowsMade", "AST": "assists", "TOV": "turnovers",
         "OREB": "reboundsOffensive", "DREB": "reboundsDefensive", "STL": "steals"}


def our_stat(counts: dict, stat: str) -> int:
    getters = {"FGA": lambda k: sum(k.get(z, 0) for z in ZONES), "FGM": lambda k: sum(k.get(f"{z}_made", 0) for z in ZONES),
               "3PA": lambda k: k.get("three", 0), "FTA": lambda k: k.get("ft_attempts", 0), "FTM": lambda k: k.get("ft_made", 0),
               "AST": lambda k: k.get("assists", 0), "TOV": lambda k: k.get("turnover", 0), "OREB": lambda k: k.get("oreb", 0),
               "DREB": lambda k: k.get("dreb", 0), "STL": lambda k: k.get("steals", 0), "BLK": lambda k: k.get("blocks", 0),
               "PF": lambda k: k.get("fouls", 0)}
    return getters[stat](counts)


def load(game_id: str) -> tuple[dict, dict]:
    pbp_path, box_path = raw_path(DATA, PLAY_BY_PLAY, game_id), raw_path(DATA, BOX_SCORE, game_id)
    if not (pbp_path.exists() and box_path.exists()):
        pytest.skip(f"game {game_id} not cached")
    return json.loads(pbp_path.read_text()), json.loads(box_path.read_text())["boxScoreTraditional"]


@pytest.fixture(scope="module")
def fitted():
    if not raw_path(DATA, SCHEDULE, "2025-26").exists():
        pytest.skip("2025-26 not downloaded")
    players, teams, extras = season_counts(DATA, "2025-26", log=print)
    if extras["games"] < 300:
        pytest.skip("need at least 300 cached 2025-26 games")
    return fit_action_model(players, teams, extras, "2025-26"), extras


def test_shot_zone_uses_coordinates_because_corner_threes_report_distance_zero():
    corner_three = {"shotValue": 3, "xLegacy": 225, "yLegacy": -6}
    layup = {"shotValue": 2, "xLegacy": 10, "yLegacy": 8}
    jumper = {"shotValue": 2, "xLegacy": -28, "yLegacy": 136}
    assert (shot_zone(corner_three), shot_zone(layup), shot_zone(jumper)) == ("three", "rim", "mid")


def test_personal_fouls_exclude_technicals():
    assert is_personal_foul("Shooting") and is_personal_foul("Offensive Charge") and is_personal_foul("Flagrant Type 1")
    assert not is_personal_foul("Technical") and not is_personal_foul("Defense 3 Second") and not is_personal_foul("Delay Technical")


def test_count_game_reproduces_the_box_score_exactly():
    pbp, box = load("0022500003")
    counts = count_game(pbp, box)
    for side in ("homeTeam", "awayTeam"):
        for player in box[side]["players"]:
            mine = counts.players.get(player["personId"], {})
            for stat, field in EXACT.items():
                assert our_stat(mine, stat) == player["statistics"][field], (player["familyName"], stat)
    print("every player's", ", ".join(EXACT), "match the official box score")


def test_count_game_over_every_cached_game_of_2025_26():
    games = sorted(Path(p).stem for p in (DATA / "raw" / PLAY_BY_PLAY).glob("00225*.json"))[:400]
    if len(games) < 50:
        pytest.skip("need cached 2025-26 games")
    ours, official = {s: 0 for s in list(EXACT) + ["BLK", "PF"]}, {s: 0 for s in list(EXACT) + ["BLK", "PF"]}
    names = dict(EXACT, BLK="blocks", PF="foulsPersonal")
    for game_id in games:
        pbp, box = load(game_id)
        counts = count_game(pbp, box)
        for side in ("homeTeam", "awayTeam"):
            for player in box[side]["players"]:
                for stat, field in names.items():
                    ours[stat] += our_stat(counts.players.get(player["personId"], {}), stat)
                    official[stat] += player["statistics"][field]
    print({stat: f"{ours[stat]}/{official[stat]}" for stat in ours})
    assert all(ours[stat] == official[stat] for stat in EXACT)
    assert abs(ours["BLK"] / official["BLK"] - 1) < 0.01 and abs(ours["PF"] / official["PF"] - 1) < 0.005


def test_shrink_pulls_small_samples_to_the_league():
    assert shrink(0, 0, 0.36, 150) == pytest.approx(0.36), "no data: league average"
    assert shrink(1, 1, 0.36, 150) == pytest.approx((1 + 54) / 151), "one make in one try barely moves it"
    assert shrink(4000, 10000, 0.36, 150) == pytest.approx(0.4, abs=0.001), "lots of data: the player's own rate"


def test_fit_action_model_league_constants_look_like_the_nba(fitted):
    model, _ = fitted
    league = model.league
    print({z: round(league.make[z], 3) for z in ZONES}, round(league.ft_pct, 3))
    assert 0.60 < league.make["rim"] < 0.72 and 0.38 < league.make["mid"] < 0.47 and 0.33 < league.make["three"] < 0.39
    assert 0.74 < league.ft_pct < 0.82
    assert league.home_make_factor > 1 > league.away_make_factor
    assert set(league.event_rate) == set(EVENTS)
    assert len(model.teams) == 30 and len(model.players) > 400


def test_a_star_stands_out_from_the_league(fitted):
    model, _ = fitted
    sga, league = model.players[SGA], model.league
    print(sga.name, round(sga.minutes_per_game, 1), {z: round(sga.make[z], 3) for z in ZONES}, round(sga.ft_pct, 3))
    assert sga.ft_pct > league.ft_pct + 0.05 and sga.make["mid"] > league.make["mid"] + 0.05
    assert sum(sga.events[e] for e in EVENTS) > 1.4 * sum(league.event_rate[e] for e in EVENTS), "a high-usage player"


def test_action_model_saves_and_loads_unchanged(fitted, tmp_path):
    model, _ = fitted
    path = tmp_path / "model.json"
    model.save(path)
    loaded = ActionModel.load(path)
    assert loaded.players[SGA] == model.players[SGA] and loaded.teams[OKC] == model.teams[OKC] and loaded.league == model.league


def test_minute_shares_give_regulars_their_real_minutes(fitted):
    model, _ = fitted
    roster = [model.players[p] for p in default_roster(model, OKC)]
    shares = minute_shares(roster)
    print({model.players[p].name: round(s * 48, 1) for p, s in shares.items()})
    assert sum(shares.values()) == pytest.approx(5.0)
    assert max(shares.values()) <= 0.9
    assert shares[SGA] * 48 == pytest.approx(min(model.players[SGA].minutes_per_game, 0.9 * 48), abs=0.01)


def test_default_roster_holds_the_teams_players(fitted):
    model, _ = fitted
    roster = default_roster(model, OKC)
    assert len(roster) == 13 and SGA in roster
    assert all(model.players[p].team_id == OKC for p in roster)


def test_the_same_seed_replays_the_same_game(fitted):
    model, _ = fitted
    first, again = Game(model, OKC, HOU, seed=7).play(), Game(model, OKC, HOU, seed=7).play()
    other = Game(model, OKC, HOU, seed=8).play()
    assert [e.text for e in first.events] == [e.text for e in again.events]
    assert [e.text for e in first.events] != [e.text for e in other.events]


def test_a_game_is_internally_consistent(fitted):
    model, _ = fitted
    result = Game(model, OKC, HOU, seed=11).play()
    length = 48 * 60 + (result.periods - 4) * 300
    for side in (result.home, result.away):
        box = result.box_score(side)
        print(side.tricode, side.points, "| minutes", round(box.MIN.sum(), 1))
        assert box.PTS.sum() == side.points
        assert box.PTS.sum() == 2 * box.FGM.sum() + box["3PM"].sum() + box.FTM.sum()
        assert (box.FGM <= box.FGA).all() and (box["3PM"] <= box["3PA"]).all() and (box.FTM <= box.FTA).all()
        assert sum(a.seconds for a in side.athletes.values()) == pytest.approx(5 * length), "five players on the floor at every second"
        assert (box.PF <= 6).all()
    assert result.home.points != result.away.points, "no ties: overtime until someone wins"


def test_a_simulated_league_matches_the_real_season(fitted):
    model, extras = fitted
    # 2000 games: home win share has a standard error of about 1.1 points (1.6 with 1000)
    table = compare(real_per_team_game(extras), simulated_per_team_game(simulate_league(model, 2000, seed=1)))
    print(table[["statistic", "real", "simulated", "difference", "tolerance", "ok"]].round(4).to_string(index=False))
    assert table.ok.all(), table[~table.ok].statistic.tolist()


def test_good_teams_win_more_in_simulation_too(fitted):
    model, _ = fitted
    schedule = json.loads(raw_path(DATA, SCHEDULE, "2025-26").read_text())
    real, simulated = {}, {}
    games = [g["gameId"] for day in schedule["leagueSchedule"]["gameDates"] for g in day["games"]]
    for seed, game_id in enumerate(g for g in sorted(games) if raw_path(DATA, BOX_SCORE, g).exists()):
        box = json.loads(raw_path(DATA, BOX_SCORE, game_id).read_text())["boxScoreTraditional"]
        home, away = box["homeTeamId"], box["awayTeamId"]
        margin = box["homeTeam"]["statistics"]["points"] - box["awayTeam"]["statistics"]["points"]
        result = Game(model, home, away, seed=seed).play()
        for team, real_margin, sim_margin in ((home, margin, result.home.points - result.away.points),
                                              (away, -margin, result.away.points - result.home.points)):
            real.setdefault(team, []).append(real_margin)
            simulated.setdefault(team, []).append(sim_margin)
    teams = sorted(real)
    correlation = np.corrcoef([np.mean(real[t]) for t in teams], [np.mean(simulated[t]) for t in teams])[0, 1]
    print(f"team point differential, real vs simulated: correlation {correlation:.3f}")
    assert correlation > 0.75


def test_cli_fits_the_model_and_plays_a_game(fitted, tmp_path, capsys):
    from hoopformer.cli import main

    (tmp_path / "raw").symlink_to((DATA / "raw").resolve())
    assert main(["actions", "--season", "2025-26", "--games", "2000", "--data-dir", str(tmp_path)]) == 0, "realism needs 2000 games to be stable"
    assert main(["play", "--home", "OKC", "--away", "HOU", "--seed", "3", "--data-dir", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    print(output[-600:])
    assert "Final" in output and "Shai Gilgeous-Alexander" in output
    assert main(["play", "--home", "XXX", "--away", "HOU", "--data-dir", str(tmp_path)]) == 1


def test_events_carry_who_did_what_and_both_lineups(fitted):
    model, _ = fitted
    result = Game(model, OKC, HOU, seed=11).play()
    shots = [e for e in result.events if e.kind == "shot"]
    made_points = sum(e.value for e in shots) + sum(e.value for e in result.events if e.kind == "free_throws")
    print(len(result.events), "events |", {k: sum(e.kind == k for e in result.events) for k in ("chance", "shot", "rebound", "turnover", "foul", "sub")})
    assert made_points == result.home.points + result.away.points, "every point appears on exactly one event"
    assert all(len(e.home_lineup) == 5 and len(e.away_lineup) == 5 for e in result.events if e.kind != "period_start")
    assert all(e.actor is not None for e in shots)


def test_replay_data_and_page(fitted, tmp_path):
    from hoopformer.game.replay import TEAM_COLORS, replay_data, replay_html

    model, _ = fitted
    result = Game(model, OKC, HOU, seed=11).play()
    data = replay_data(result, model)
    times = [e["t"] for e in data["events"]]
    print(len(times), "events, last at", times[-1], "s")
    assert times == sorted(times), "events in time order"
    assert data["final"] == {"home": result.home.points, "away": result.away.points}
    assert {t.tricode for t in model.teams.values()} <= set(TEAM_COLORS)
    page = replay_html(data)
    assert "__GAME_DATA__" not in page and "<title>Hoopformer Courtside</title>" in page and "</script>" in page


def test_cli_play_writes_a_replay_page(fitted, tmp_path):
    from hoopformer.cli import main, model_path

    model, _ = fitted
    model.save(model_path(tmp_path, "2025-26"))
    page = tmp_path / "replay.html"
    assert main(["play", "--home", "OKC", "--away", "BOS", "--seed", "264", "--data-dir", str(tmp_path), "--replay", str(page)]) == 0
    assert page.exists() and page.stat().st_size > 50_000


# --- day 2: steps, fatigue, the scripted coach, home court -------------------------------------------

def test_stepping_plays_the_same_game_as_play(fitted):
    model, _ = fitted
    whole = Game(model, OKC, HOU, seed=21).play()
    game, steps = Game(model, OKC, HOU, seed=21), []
    while not game.done:
        steps.append(game.step())
    print(len(steps), "steps;", "first step:", [e.text for e in steps[0] if e.text])
    assert [e.text for step in steps for e in step] == [e.text for e in whole.events]
    assert game.step() == [], "a finished game has no more steps"
    assert all(step for step in steps), "every step plays something"


def test_coaches_substitute_and_call_timeouts_within_the_rules(fitted):
    model, _ = fitted
    result = Game(model, OKC, HOU, seed=5).play()
    timeouts = [e for e in result.events if e.kind == "timeout"]
    subs = [e for e in result.events if e.kind == "sub"]
    print(len(timeouts), "timeouts:", [(e.team, e.period, e.zone) for e in timeouts])
    print(len(subs), "substitutions, reasons:", sorted({e.zone for e in subs}))
    for side in (result.home, result.away):
        assert 7 - side.timeouts == sum(e.team == side.tricode for e in timeouts) <= 7
    assert {e.zone for e in timeouts} <= set(coach.TIMEOUT_REASONS)
    assert all(len(set(e.home_lineup)) == 5 and len(set(e.away_lineup)) == 5 for e in subs)
    assert len({e.actor for e in subs}) >= 8, "the bench plays"


def test_foul_trouble_rule_of_thumb():
    assert coach.foul_trouble(2, 1, 400) and not coach.foul_trouble(1, 1, 400)
    assert coach.foul_trouble(3, 2, 400) and not coach.foul_trouble(3, 3, 400)
    assert coach.foul_trouble(5, 4, 600) and not coach.foul_trouble(5, 4, 120), "with 5 minutes left, play through it"
    assert not coach.foul_trouble(5, 5, 200), "overtime: no sitting"


def test_close_games_end_with_the_best_five(fitted):
    model, _ = fitted
    checked = 0
    for seed in range(60):
        result = Game(model, OKC, HOU, seed=seed).play()
        if result.periods != 4 or abs(result.home.points - result.away.points) > 4:
            continue
        side = result.home
        best = coach.starters(side)  # most minutes among those still eligible
        final = result.events[-1]
        print(seed, result.home.points, result.away.points, "closing five:", sorted(final.home_lineup) == sorted(best))
        assert sorted(final.home_lineup) == sorted(best)
        checked += 1
    assert checked >= 5


def test_substitute_rejects_an_impossible_five(fitted):
    model, _ = fitted
    game = Game(model, OKC, HOU, seed=1)
    with pytest.raises(ValueError):
        game.substitute(game.home, game.home.lineup[:4] + [game.away.lineup[0]])
    bench = [pid for pid in game.home.athletes if pid not in game.home.lineup][0]
    game.substitute(game.home, [bench] + game.home.lineup[1:])
    assert game.home.lineup[0] == bench and game.events[-1].kind == "sub"


def test_fatigue_tires_players_on_the_floor_and_rests_them_on_the_bench(fitted):
    model, _ = fitted
    game = Game(model, OKC, HOU, seed=1)
    starter = game.home.athletes[game.home.lineup[0]]
    bench = game.home.athletes[[pid for pid in game.home.athletes if pid not in game.home.lineup][0]]
    starter.run(300, on_floor=True)
    bench.energy = 0.3
    bench.run(300, on_floor=False)
    print("starter after 5 minutes:", round(starter.energy, 3), "| bench player after 5 minutes' rest:", round(bench.energy, 3))
    assert 0.25 < starter.energy < 0.8 and bench.energy == 1.0 and starter.seconds == 300 and bench.seconds == 0


def test_rotations_look_like_real_games(fitted):
    model, _ = fitted
    real = real_rotations(DATA, "2025-26", model)
    simulated = simulated_rotations(simulate_league(model, 600, seed=1), model)
    for key in ("subs per team-game", "timeouts per team-game"):
        print(f"{key}: real {real[key]:.2f}, simulated {simulated[key]:.2f}")
    for tier, minutes in real["stint minutes"].items():
        print(f"stint, {tier}: real {minutes:.2f} min, simulated {simulated['stint minutes'][tier]:.2f}")
    assert abs(simulated["subs per team-game"] / real["subs per team-game"] - 1) < 0.2
    assert abs(simulated["timeouts per team-game"] - real["timeouts per team-game"]) < 0.8
    assert all(abs(simulated["stint minutes"][t] - m) < 1.5 for t, m in real["stint minutes"].items())
    targets = {}
    for team in model.teams:
        side = Game(model, team, OKC if team != OKC else HOU, seed=0).home
        targets.update({pid: share * 48 for pid, share in side.share.items() if share * 48 >= 10})
    errors = np.array([simulated["minutes per game"][pid] - target for pid, target in targets.items() if pid in simulated["minutes per game"]])
    print(f"minutes vs target, {len(errors)} players: mean {errors.mean():+.2f}, mean abs {np.abs(errors).mean():.2f}")
    assert np.abs(errors).mean() < 1.5 and errors.mean() > -1.5


def test_home_court_is_spread_over_shooting_free_throws_and_turnovers(fitted):
    model, _ = fitted
    league = model.league
    print({k: round(getattr(league, k), 4) for k in ("home_make_factor", "away_make_factor", "home_free_throw_factor",
                                                      "away_free_throw_factor", "home_turnover_factor", "away_turnover_factor")})
    assert league.home_make_factor > 1 > league.away_make_factor
    assert league.home_free_throw_factor > 1 > league.away_free_throw_factor
    assert league.home_turnover_factor < 1 < league.away_turnover_factor


def test_next_seasons_rosters_keep_last_seasons_rates(fitted):
    from hoopformer.fetch import ROSTER
    from hoopformer.game.rosters import NEWCOMER_MINUTES, season_rosters, with_rosters

    model, _ = fitted
    if len(list((DATA / "raw" / ROSTER).glob("2026-27_*.json"))) < 30:
        pytest.skip("2026-27 rosters not cached: run `uv run hoopformer fetch --rosters --season 2026-27`")
    rosters = season_rosters(DATA, "2026-27")
    season = with_rosters(model, rosters, "2026-27")
    known = [pid for team in rosters.values() for pid in (p["person_id"] for p in team) if pid in model.players]
    newcomers = [pid for team in rosters.values() for pid in (p["person_id"] for p in team) if pid not in model.players]
    print(len(rosters), "teams |", len(known), "players with 2025-26 rates |", len(newcomers), "newcomers")
    assert len(rosters) == 30 and all(len(team) >= 13 for team in rosters.values())
    sga = season.players[SGA]
    assert sga.team_id == OKC and sga.make == model.players[SGA].make, "a returning player keeps last season's rates"
    rookie = season.players[newcomers[0]]
    assert rookie.make == model.league.make and rookie.minutes_per_game == NEWCOMER_MINUTES
    assert {p.team_id for p in season.players.values()} == set(rosters)
    result = Game(season, OKC, HOU, seed=3).play()
    assert result.home.points > 70 and result.away.points > 70
