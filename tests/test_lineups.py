"""Tests for lineup reconstruction, on real cached games.

Game 0022500001 (HOU at OKC, 2025-26 opener) went to double overtime and
includes a player swapped in during the break who records nothing in the
extra period. Game 0022500075 has three OKC Williamses; game 0022500067 has a
player the play-by-play names by first name.
"""

import glob
import json
from pathlib import Path

import pytest

from hoopformer.fetch import BOX_SCORE, PLAY_BY_PLAY, raw_path
from hoopformer.lineups import (
    LineupError,
    audit_minutes,
    box_seconds,
    clock_seconds,
    elapsed,
    entering_name,
    is_on_floor_event,
    name_match_strength,
    period_evidence,
    period_length,
    period_start,
    plain,
    player_seconds,
    reconstruct_game,
    replay,
    resolve_player,
    team_rosters,
)

DATA = Path("data")
OKC, HOU, POR = 1610612760, 1610612745, 1610612757
HARTENSTEIN, JALEN_WILLIAMS, JAYLIN_WILLIAMS, YANG_HANSEN = 1628392, 1631114, 1631119, 1642905


def load(game_id: str) -> tuple[dict, dict]:
    pbp_path, box_path = raw_path(DATA, PLAY_BY_PLAY, game_id), raw_path(DATA, BOX_SCORE, game_id)
    if not (pbp_path.exists() and box_path.exists()):
        pytest.skip(f"game {game_id} not cached: run `uv run hoopformer fetch --season 2025-26 --limit 80`")
    return json.loads(pbp_path.read_text()), json.loads(box_path.read_text())["boxScoreTraditional"]


def test_clock_and_period_arithmetic():
    print(clock_seconds("PT06M40.00S"), clock_seconds("PT00M48.10S"), elapsed(5, "PT05M00.00S"), elapsed(6, "PT00M00.00S"))
    assert clock_seconds("PT06M40.00S") == 400.0
    assert clock_seconds("PT00M48.10S") == pytest.approx(48.1)
    assert (period_length(4), period_length(5)) == (720.0, 300.0)
    assert (period_start(1), period_start(4), period_start(5), period_start(6)) == (0.0, 2160.0, 2880.0, 3180.0)
    assert elapsed(1, "PT12M00.00S") == 0.0
    assert elapsed(6, "PT00M00.00S") == 3480.0, "a double-overtime game lasts 48 + 2 x 5 minutes"
    with pytest.raises(ValueError):
        clock_seconds("6:40")


def test_box_seconds_parses_minutes_and_treats_blank_as_did_not_play():
    assert box_seconds("45:15") == 2715.0
    assert box_seconds("1:02") == 62.0
    assert box_seconds("") == 0.0


def test_team_rosters_reads_starters_and_minutes():
    _, box = load("0022500001")
    okc = team_rosters(box)[OKC]
    starters = [p["nameI"] for p in okc if p["starter"]]
    print("OKC starters:", starters)
    assert len(starters) == 5 and "S. Gilgeous-Alexander" in starters
    assert {"personId", "firstName", "familyName", "nameI", "starter", "entered", "seconds"} <= set(okc[0])


def test_a_player_with_zero_official_seconds_can_still_enter():
    pbp, box = load("0022500564")  # "SUB: Richards FOR Brooks"; Nick Richards is listed at 0:00
    richards = next(p for r in team_rosters(box).values() for p in r if p["familyName"] == "Richards")
    print("Richards:", richards)
    assert richards["entered"] and richards["seconds"] == 0.0
    assert audit_minutes(reconstruct_game(pbp, box), box) == []


def test_plain_strips_accents():
    assert plain("Dončić") == "Doncic"
    assert plain("Jokić") == "Jokic"


def test_name_match_strength_ranks_initial_family_prefix_then_first_name():
    _, box75 = load("0022500075")
    okc = {p["personId"]: p for p in team_rosters(box75)[OKC]}
    _, box67 = load("0022500067")
    yang = next(p for p in team_rosters(box67)[POR] if p["personId"] == YANG_HANSEN)
    jaylin, jalen = okc[JAYLIN_WILLIAMS], okc[JALEN_WILLIAMS]
    print("Jay. Williams ->", name_match_strength("Jay. Williams", jaylin), name_match_strength("Jay. Williams", jalen))
    assert name_match_strength("J. Williams", jalen) > name_match_strength("Williams", jalen)
    assert name_match_strength("Williams", jalen) > name_match_strength("Jal. Williams", jalen)
    assert name_match_strength("Jal. Williams", jalen) == 2 and name_match_strength("Jay. Williams", jalen) == 0
    assert name_match_strength("Hansen", yang) == 1, "the play-by-play names this player by first name"
    assert name_match_strength("Nobody", yang) == 0


def test_historical_substitution_names_match_the_current_box_score_spellings():
    cases = [
        ("0021700015", "Kanter", 202683),       # box score now says Freedom
        ("0021600133", "McClellan", 1627815),   # box score now says Mac
        ("0021600007", "Marc Morris", 202694),  # feed abbreviates Marcus
        ("0021600189", "Jones, Jr.", 1627884),  # feeds disagree about comma
        ("0022201113", "Bullock", 203493),      # box score says Bullock Jr.
        ("0022300343", "Boston Jr.", 1630527),  # box score omits Jr.
        ("0022400005", "Pöltl", 1627751),       # box score spells it Poeltl
    ]
    resolved = []
    for game_id, name, person_id in cases:
        _, box = load(game_id)
        roster = next(roster for roster in team_rosters(box).values()
                      if any(player["personId"] == person_id for player in roster))
        resolved.append((name, resolve_player(name, roster)))
        assert resolve_player(name, roster) == person_id
    print("historical substitution names:", resolved)


def test_resolve_player_prefers_a_family_name_over_a_first_name():
    roster = [
        {"personId": 1, "firstName": "DeAndre", "familyName": "Jordan", "nameI": "D. Jordan", "entered": True, "seconds": 600.0},
        {"personId": 2, "firstName": "Jordan", "familyName": "Poole", "nameI": "J. Poole", "entered": True, "seconds": 900.0},
    ]
    assert resolve_player("Jordan", roster) == 1


def test_resolve_player_rules_out_players_who_never_played_or_are_already_on():
    _, box = load("0022500075")
    okc = team_rosters(box)[OKC]
    assert resolve_player("Jay. Williams", okc) == JAYLIN_WILLIAMS
    with pytest.raises(LineupError):
        resolve_player("J. Williams", okc)  # Jalen and Jaylin both played
    assert resolve_player("J. Williams", okc, on_floor={JALEN_WILLIAMS}) == JAYLIN_WILLIAMS
    with pytest.raises(LineupError):
        resolve_player("Nobody", okc)


def test_entering_name_reads_substitution_text():
    assert entering_name("SUB: Eason FOR Smith Jr.") == "Eason"
    assert entering_name("SUB: Jal. Williams FOR Caruso") == "Jal. Williams"
    with pytest.raises(LineupError):
        entering_name("Eason checks in")


def test_is_on_floor_event_ignores_technicals_and_other_teams_players():
    shot = {"personId": 7, "actionType": "Made Shot", "subType": "Jump Shot"}
    technical = {"personId": 7, "actionType": "Foul", "subType": "Technical"}
    assert is_on_floor_event(shot, {7})
    assert not is_on_floor_event(technical, {7}), "technicals can be called on a player on the bench"
    assert not is_on_floor_event(shot, {8})

    pbp_timeout, _ = load("0021600655")
    timeout = next(a for a in pbp_timeout["game"]["actions"] if a["description"] == "Williams Timeout:Short")
    pbp_flop, _ = load("0022300512")
    flopping = next(a for a in pbp_flop["game"]["actions"] if a["subType"] == "Flopping")
    print("bench-compatible events:", timeout["description"], flopping["description"])
    assert not is_on_floor_event(timeout, {timeout["personId"]})
    assert not is_on_floor_event(flopping, {flopping["personId"]})


def test_period_evidence_finds_four_of_okcs_first_overtime_five():
    pbp, box = load("0022500001")
    ot1 = [a for a in pbp["game"]["actions"] if a["period"] == 5]
    found, subbed_in = period_evidence(ot1, OKC, team_rosters(box)[OKC])
    names = {p["personId"]: p["nameI"] for p in team_rosters(box)[OKC]}
    print("proven on floor at OT1 start:", sorted(names[i] for i in found), "| subbed in:", sorted(names[i] for i in subbed_in))
    assert len(found) == 4, "Hartenstein played OT1 without a single event"
    assert HARTENSTEIN not in found


def test_period_evidence_handles_an_event_listed_before_its_same_clock_substitution():
    pbp, box = load("0021800920")
    team = box["homeTeamId"]
    third = [a for a in pbp["game"]["actions"] if a["period"] == 3]
    found, subbed_in = period_evidence(third, team, team_rosters(box)[team])
    print("2018-19 game 920 third-quarter evidence:", found, subbed_in)
    assert 201147 not in found, "Brewer's jump ball is listed before his same-clock substitution"
    assert 201147 in subbed_in


def test_reconstruct_game_fills_the_silent_overtime_player_from_the_box_score():
    pbp, box = load("0022500001")
    stints = reconstruct_game(pbp, box)
    ot1_start = next(s for s in stints if s.period == 5)
    home_okc = box["homeTeamId"] == OKC
    okc_five = ot1_start.home if home_okc else ot1_start.away
    print("stints:", len(stints), "| OKC at OT1 tip:", okc_five)
    assert HARTENSTEIN in okc_five
    assert stints[0].start == 0.0 and stints[-1].end == 3480.0
    assert all(len(s.home) == 5 and len(s.away) == 5 for s in stints)
    assert sum(s.seconds for s in stints) == pytest.approx(3480.0), "stints must tile the game with no gaps"


def test_reconstruct_game_uses_play_by_play_when_an_old_box_score_marks_too_many_starters():
    pbp, box = load("0021600001")
    cavaliers = team_rosters(box)[box["homeTeamId"]]
    assert sum(player["starter"] for player in cavaliers) == 9
    stints = reconstruct_game(pbp, box)
    print("2016-17 opener starters:", stints[0].home, stints[0].away)
    assert len(stints[0].home) == len(stints[0].away) == 5
    assert audit_minutes(stints, box) == []


@pytest.mark.parametrize("game_id", ["0022000853", "0022200234"])
def test_reconstruct_game_ignores_a_duplicated_stale_substitution(game_id):
    pbp, box = load(game_id)
    stints = reconstruct_game(pbp, box)
    print(game_id, "stints after ignoring duplicate substitution:", len(stints))
    assert audit_minutes(stints, box) == []


def test_replay_rejects_a_wrong_starting_lineup():
    pbp, box = load("0022500001")
    rosters = team_rosters(box)
    by_period = {}
    for action in pbp["game"]["actions"]:
        by_period.setdefault(action["period"], []).append(action)
    stints = reconstruct_game(pbp, box)
    starters = {}
    for s in stints:
        starters.setdefault((s.period, box["homeTeamId"]), set(s.home))
        starters.setdefault((s.period, box["awayTeamId"]), set(s.away))
    assert replay(box["gameId"], by_period, rosters, box["homeTeamId"], box["awayTeamId"], starters) == stints
    wrong = dict(starters)
    wrong[1, OKC] = (starters[1, OKC] - {HARTENSTEIN}) | {JAYLIN_WILLIAMS}
    with pytest.raises(LineupError):
        replay(box["gameId"], by_period, rosters, box["homeTeamId"], box["awayTeamId"], wrong)


def test_audit_catches_a_missing_stint():
    pbp, box = load("0022500001")
    stints = reconstruct_game(pbp, box)
    mismatches = audit_minutes(stints[1:], box)
    print("after dropping the first stint:", [(m["name"], m["diff"]) for m in mismatches])
    assert len(mismatches) == 10, "all ten players of the dropped stint lose time"


def test_every_cached_game_rebuilds_to_the_official_minutes():
    games = sorted(Path(p).stem for p in glob.glob(str(DATA / "raw" / PLAY_BY_PLAY / "*.json")))
    games = [g for g in games if raw_path(DATA, BOX_SCORE, g).exists()]
    if not games:
        pytest.skip("no cached games")
    failures = {}
    for game_id in games:
        pbp, box = load(game_id)
        try:
            mismatches = audit_minutes(reconstruct_game(pbp, box), box)
        except LineupError as exc:
            failures[game_id] = str(exc)
            continue
        if mismatches:
            failures[game_id] = [(m["name"], round(m["diff"], 1)) for m in mismatches]
    print(f"{len(games) - len(failures)}/{len(games)} games match the box score to the second")
    for game_id, problem in failures.items():
        print("  ", game_id, problem)
    assert not failures


def test_player_seconds_sums_stints():
    pbp, box = load("0022500001")
    totals = player_seconds(reconstruct_game(pbp, box))
    print("SGA seconds:", totals[1628983])
    assert totals[1628983] == box_seconds("47:13")
    assert sum(totals.values()) == pytest.approx(10 * 3480.0), "ten players on the floor at every second"
