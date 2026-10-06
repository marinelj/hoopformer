"""Tests for coaching in plain language: lever limits, validation, the engine's levers, memory, translators.

All on real 2025-26 data. Lever effects are measured with common random numbers:
the same seeds with and without an instruction, so the difference is the lever,
not luck. The LLM tests need a key (DASHSCOPE_API_KEY for Qwen, OPENAI_API_KEY for
OpenAI) and the network: `uv run pytest -m network -k llm`.
"""

import os
from pathlib import Path

import numpy as np
import pytest

from hoopformer.game.engine import Game
from hoopformer.game.levers import BOOST, TEAM_LEVERS, lever_limits, measure_limits, multiplier, validate
from hoopformer.game.translator import (HOLDOUT2_PHRASES, HOLDOUT_PHRASES, PHRASES, check_phrases, find_players, load_env,
                                         translate)

DATA = Path("data")
OKC, BOS, SGA, TATUM, HOLMGREN = 1610612760, 1610612738, 1628983, 1628369, 1631096
SEEDS = range(300)


@pytest.fixture(scope="module")
def limits(fitted):
    return measure_limits(DATA, "2025-26")


def instruct(game, raw, addressed=None):
    side = game.home
    return game.instruct(side, validate(raw, "test", set(side.athletes), set(game.away.athletes), addressed, "test"))


def season(model, limits, raw=None, addressed=None):
    """Totals over the same 300 seeds of OKC vs BOS, with or without an instruction at tip-off."""
    totals = {"home": {}, "away": {}, "games": len(SEEDS), "intentional": 0}
    for seed in SEEDS:
        game = Game(model, OKC, BOS, seed=seed, limits=limits)
        if raw is not None:
            instruct(game, raw, addressed)
        result = game.play()
        for key, side in (("home", result.home), ("away", result.away)):
            for athlete in side.athletes.values():
                for stat in ("FGA", "3PA", "FTA", "TOV", "OREB", "PF"):
                    totals[key][stat] = totals[key].get(stat, 0) + athlete.stats[stat]
            totals[key]["poss"] = totals[key].get("poss", 0) + side.possessions
        totals["sga_fga"] = totals.get("sga_fga", 0) + result.home.athletes[SGA].stats["FGA"]
        totals["intentional"] += sum(e.zone == "intentional" for e in result.events)
    return totals


def test_limits_come_from_real_teams_and_players(limits):
    print({lever: [round(x, 3) for x in pair] for lever, pair in limits.items()})
    assert set(TEAM_LEVERS) <= set(limits) and {"aggression", "shot_preference"} <= set(limits)
    for lever, (low, high) in limits.items():
        assert 0.4 < low < 1 < high < 1.6, lever
    assert limits["pace"][1] < 1.06, "real teams' pace differs by only a few percent"


def test_lever_limits_are_cached(tmp_path, limits):
    (tmp_path / "raw").symlink_to((DATA / "raw").resolve())
    first = lever_limits(tmp_path, "2025-26")
    assert (tmp_path / "derived" / "lever_limits_2025-26.json").exists() and first == lever_limits(tmp_path, "2025-26")


def test_multiplier_reaches_the_real_extremes_and_no_further():
    limits = [0.8, 1.2]
    assert multiplier(0, limits) == 1 and multiplier(1, limits) == pytest.approx(1.2) and multiplier(-1, limits) == pytest.approx(0.8)
    assert multiplier(5, limits) == pytest.approx(1.2), "values are clamped to [-1, 1]"
    assert multiplier(0.5, limits) == pytest.approx(1.1)


def test_validate_clamps_values_and_sends_the_rest_to_unmapped(fitted):
    model, _ = fitted
    game = Game(model, OKC, BOS, seed=1)
    own, opponents = set(game.home.athletes), set(game.away.athletes)
    raw = {"team": {"pace": 3, "three_point_rate": -0.4, "zone_defense": 1},
           "players": [{"person_id": SGA, "aggression": 0.7, "dunk_more": 1}, {"person_id": TATUM, "aggression": 1}],
           "double_team": SGA, "focus": SGA, "substitutions": [{"in": SGA, "out": SGA}], "unmapped": ["make every shot"],
           "reply": "Got it, coach.", "replier": TATUM}
    instruction = validate(raw, "words", own, opponents, None, "test")
    print(instruction)
    assert instruction.team == {"pace": 1.0, "three_point_rate": -0.4}
    assert instruction.players == {SGA: {"aggression": 0.7}} and instruction.focus == SGA and instruction.double_team is None
    assert instruction.substitutions == [] and instruction.replier is None
    assert "make every shot" in instruction.unmapped and "team.zone_defense" in instruction.unmapped
    assert any("dunk_more" in u for u in instruction.unmapped) and any(str(TATUM) in u for u in instruction.unmapped)


def test_an_uncoached_game_is_unchanged_by_the_lever_machinery(fitted, limits):
    model, _ = fitted
    plain, with_limits = Game(model, OKC, BOS, seed=9).play(), Game(model, OKC, BOS, seed=9, limits=limits).play()
    assert [e.text for e in plain.events] == [e.text for e in with_limits.events]


@pytest.mark.parametrize("lever, stat, side, direction", [
    ("three_point_rate", "3PA share", "home", +1), ("pace", "poss", "home", +1), ("ball_security", "TOV", "home", -1),
    ("crash_glass", "OREB", "home", +1), ("pressure", "TOV", "away", +1), ("protect_paint", "3PA share", "away", +1),
    ("foul_caution", "PF", "home", -1),
])
def test_each_team_lever_moves_its_stat_within_real_limits(fitted, limits, lever, stat, side, direction):
    model, _ = fitted
    base, coached = season(model, limits), season(model, limits, {"team": {lever: 1.0}})

    def value(totals):
        t = totals[side]
        return t["3PA"] / t["FGA"] if stat == "3PA share" else t[stat] / totals["games"]

    ratio = value(coached) / value(base)
    low, high = limits[lever]
    print(f"{lever} +1: {stat} ({side}) {value(base):.3f} -> {value(coached):.3f}, x{ratio:.3f}; real limits {low:.3f}-{high:.3f}")
    assert (ratio - 1) * direction > 0.01, "the lever moves its stat"
    assert low - 0.02 <= ratio <= high + 0.02, "but no further than real teams go"


def test_aggression_and_focus_give_a_player_more_shots(fitted, limits):
    model, _ = fitted
    base = season(model, limits)["sga_fga"]
    aggressive = season(model, limits, {"players": [{"person_id": SGA, "aggression": 1}]}, SGA)["sga_fga"]
    focused = season(model, limits, {"focus": SGA})["sga_fga"]
    print(f"SGA shots per game: {base / 300:.1f}, aggressive {aggressive / 300:.1f}, offense through SGA {focused / 300:.1f}")
    assert base < focused < aggressive <= base * limits["aggression"][1] * 1.02


def test_double_team_takes_the_ball_out_of_a_stars_hands(fitted, limits):
    model, _ = fitted
    shots = {}
    for label, raw in (("free", None), ("doubled", {"double_team": SGA})):
        total = 0
        for seed in range(300):  # 150 games left the ratio within noise of the bar
            game = Game(model, BOS, OKC, seed=seed, limits=limits)  # Boston coaches, doubling SGA
            if raw:
                game.instruct(game.home, validate(raw, "double SGA", set(game.home.athletes), set(game.away.athletes), None, "test"))
            total += game.play().away.athletes[SGA].stats["FGA"]
        shots[label] = total / 300
    print(shots)
    assert shots["doubled"] < shots["free"] * 0.85


def test_possessions_say_who_is_doubled_so_the_court_can_show_it(fitted, limits):
    model, _ = fitted
    game = Game(model, BOS, OKC, seed=3, limits=limits)
    game.instruct(game.home, validate({"double_team": SGA}, "double SGA", set(game.home.athletes), set(game.away.athletes), None, "test"))
    result = game.play()
    okc_chances = [e for e in result.events if e.kind == "chance" and e.team == "OKC"]
    doubled = [e for e in okc_chances if e.other == SGA]
    print(len(doubled), "of", len(okc_chances), "OKC chances show SGA doubled")
    assert doubled and all(SGA in e.away_lineup for e in doubled), "marked only while SGA is on the floor"
    assert all(e.other is None for e in result.events if e.kind == "chance" and e.team == "BOS")


def test_rest_keeps_a_player_on_the_bench_until_it_lapses(fitted, limits):
    model, _ = fitted
    game = Game(model, OKC, BOS, seed=4, limits=limits)
    game.step()
    events = instruct(game, {"players": [{"person_id": SGA, "rest_minutes": 5}]}, SGA)
    assert SGA not in game.home.lineup and any(e.kind == "sub" and e.other == SGA for e in events)
    while game.game_seconds < 5 * 60:
        game.step()
        assert SGA not in game.home.lineup, f"SGA came back at {game.game_seconds:.0f}s"
    while not game.done and SGA not in game.home.lineup:
        game.step()
    print(f"SGA back in at {game.game_seconds / 60:.1f} minutes")
    assert SGA in game.home.lineup and not game.home.directives


def test_late_fouling_happens_only_late_and_behind(fitted, limits):
    model, _ = fitted
    fouls = []
    for seed in range(200):
        game = Game(model, BOS, OKC, seed=seed, limits=limits)  # Boston is usually behind against OKC
        instruct_raw = validate({"late_foul": True}, "foul late", set(game.home.athletes), set(game.away.athletes), None, "test")
        game.instruct(game.home, instruct_raw)
        result = game.play()
        for e in result.events:
            if e.zone == "intentional":
                fouls.append(e)
                assert e.period >= 4 and e.clock <= 60, "only in the last minute"
                assert e.home_score < e.away_score, "only when trailing"
    print(len(fouls), "intentional fouls in 200 games")
    assert len(fouls) > 5


def test_instructions_live_in_memory_with_the_coaches_words_and_lapse(fitted, limits):
    model, _ = fitted
    game = Game(model, OKC, BOS, seed=2, limits=limits)
    for _ in range(10):
        game.step()
    words = "Push the pace this quarter, and Shai, be aggressive"
    raw = {"team": {"pace": 0.6}, "players": [{"person_id": SGA, "aggression": 0.6, "confidence": 0.5}], "duration": "quarter",
           "reply": "Pushing it, coach.", "replier": SGA}
    events = game.instruct(game.home, validate(raw, words, set(game.home.athletes), set(game.away.athletes), SGA, "test"))
    memory = game.memory(game.home, SGA)
    print({k: v for k, v in memory.items() if k != "recent"})
    assert [e.kind for e in events][:2] == ["coach", "reply"] and events[0].text == words
    assert {d.lever for d in memory["directives"]} == {"pace", "aggression"} and all(d.words == words for d in memory["directives"])
    assert memory["confidence"] > 0.5 and game.home.tactics == {"pace": 0.6}
    period = game.period
    while game.period == period and not game.done:
        game.step()
    game.step()
    assert game.home.tactics == {} and not game.home.directives, "a quarter-long instruction lapses at the end of the quarter"


def test_a_coachs_substitution_sticks(fitted, limits):
    model, _ = fitted
    game = Game(model, OKC, BOS, seed=3, limits=limits)
    game.step()
    bench = next(pid for pid in game.home.athletes if pid not in game.home.lineup and game.home.share[pid] > 0)
    out = game.home.lineup[0]
    instruct(game, {"substitutions": [{"in": bench, "out": out}]})
    assert bench in game.home.lineup and out not in game.home.lineup
    for _ in range(6):
        game.step()
        if game.game_seconds > 200:
            break
        assert bench in game.home.lineup and out not in game.home.lineup


def test_rules_translator_finds_names():
    players = [{"person_id": 1, "name": "Shai Gilgeous-Alexander"}, {"person_id": 2, "name": "Jalen Williams"},
               {"person_id": 3, "name": "Jaylin Williams"}, {"person_id": 4, "name": "Luka Dončić"}]
    assert find_players("Run it through Shai", players) == [1]
    assert find_players("feed jalen williams", players) == [2]
    assert find_players("Williams is open", players) == [], "two Williamses: ambiguous"
    assert find_players("Doncic, take over", players) == [4], "accents don't matter"


def mid_game(model, limits):
    game = Game(model, OKC, BOS, seed=1, limits=limits)
    for _ in range(60):
        game.step()
    return game


def test_rules_baseline_on_the_phrases_it_was_written_for_and_on_new_ones(fitted, limits):
    model, _ = fitted
    game = mid_game(model, limits)
    seen, total, _ = check_phrases(game, game.home, "rules", PHRASES, log=lambda line: None)
    held_out, total_held, rows = check_phrases(game, game.home, "rules", HOLDOUT_PHRASES, log=print)
    print(f"rules: {seen}/{total} on the phrases they were written for, {held_out}/{total_held} on held-out phrases")
    assert seen >= total - 2, "the rules still cover the phrases they were written for"
    assert held_out < 0.5 * total_held, "...but they don't generalize: that's why the game uses an LLM"


def test_translate_logs_what_it_cannot_map(fitted, limits, tmp_path):
    model, _ = fitted
    game = mid_game(model, limits)
    log = tmp_path / "unmapped.jsonl"
    instruction = translate("Switch everything on defense.", game, game.home, use="rules", unmapped_log=log)
    print(instruction.unmapped, log.read_text())
    assert instruction.unmapped and "Switch everything" in log.read_text()


@pytest.mark.network
@pytest.mark.parametrize("provider", ["qwen", "openai"])
def test_llm_translates_coach_phrases(fitted, limits, provider):
    from hoopformer.game.translator import PROVIDERS

    load_env()
    if not os.environ.get(PROVIDERS[provider]["key"]):
        pytest.skip(f"set {PROVIDERS[provider]['key']} (shell profile or .env) to test {provider}")
    model, _ = fitted
    game = mid_game(model, limits)
    scores, rows = {}, []
    for label, path in (("test", PHRASES), ("held out", HOLDOUT_PHRASES), ("held out 2", HOLDOUT2_PHRASES)):
        passed, total, these = check_phrases(game, game.home, provider, path)
        scores[label] = (passed, total)
        rows += these
    print(f"{provider}:", {label: f"{p}/{t}" for label, (p, t) in scores.items()},
          f"{np.mean([r['seconds'] for r in rows]):.1f} s per instruction")
    print("sample replies:", [r["reply"] for r in rows[:5]])
    assert all(p >= 0.85 * t for p, t in scores.values())

def test_cli_coach_and_play_with_instructions(fitted, tmp_path, capsys):
    from hoopformer.cli import main, model_path

    model, _ = fitted
    (tmp_path / "raw").symlink_to((DATA / "raw").resolve())
    model.save(model_path(tmp_path, "2025-26"))
    assert main(["coach", "Push the pace and pack the paint", "--use", "rules", "--data-dir", str(tmp_path)]) == 0
    assert main(["coach", "Be more aggressive", "--to", "Shai Gilgeous-Alexander", "--use", "rules", "--data-dir", str(tmp_path)]) == 0
    assert main(["coach", "hello", "--to", "Nobody Here", "--data-dir", str(tmp_path)]) == 1
    page = tmp_path / "replay.html"
    assert main(["play", "--home", "OKC", "--away", "BOS", "--seed", "4", "--use", "rules", "--data-dir", str(tmp_path),
                 "--say", "Q2 6:00 Crash the offensive glass", "--say", "Q3 5:00 Shai Gilgeous-Alexander: take over this game",
                 "--replay", str(page)]) == 0
    output = capsys.readouterr().out
    print(output[-900:])
    assert '"pace": 0.6' in output and '"protect_paint": 0.6' in output and '"aggression": 0.6' in output
    assert "coach: 'Crash the offensive glass' -> crash_glass +0.6" in output
    assert "Shai Gilgeous-Alexander aggression +0.6" in output and "Final" in output
    assert '"kind":"coach"' in page.read_text() and (tmp_path / "derived" / "lever_limits_2025-26.json").exists()


def test_chances_carry_the_calls_in_force_so_the_court_can_act_them_out(fitted, limits):
    model, _ = fitted
    game = Game(model, OKC, BOS, seed=6, limits=limits)
    raw = {"team": {"crash_glass": 0.8, "protect_paint": 0.7}, "players": [{"person_id": SGA, "aggression": 0.8}], "double_team": TATUM}
    game.instruct(game.home, validate(raw, "crash, zone, Shai attack, double Tatum", set(game.home.athletes), set(game.away.athletes), SGA, "test"))
    result = game.play()
    okc = [e.tactics for e in result.events if e.kind == "chance" and e.team == "OKC"]
    bos = [e.tactics for e in result.events if e.kind == "chance" and e.team == "BOS"]
    print("an OKC chance:", okc[0], "| a BOS chance:", bos[0])
    assert all(t["off"]["crash_glass"] == 0.8 and "protect_paint" not in t["off"] for t in okc)
    assert all(t["def"]["protect_paint"] == 0.7 and "crash_glass" not in t["def"] for t in bos)
    assert any(SGA in t["off"].get("players", {}) for t in okc) and any(t["def"].get("double_team") == TATUM for t in bos)
    assert all(e.tactics is None for e in Game(model, OKC, BOS, seed=6).play().events), "uncoached games carry no calls"


def test_monitor_shows_the_engine_with_and_without_the_coachs_words(fitted, limits):
    model, _ = fitted
    game = Game(model, OKC, BOS, seed=2, limits=limits)
    for _ in range(8):
        game.step()
    quiet = game.monitor(game.home)
    assert all(abs(r["after"] - r["before"]) < 1e-12 for r in quiet["offense"] + quiet["defense"] + quiet["players"]) and not quiet["directives"]
    raw = {"team": {"crash_glass": 1, "pace": 1}, "players": [{"person_id": SGA, "aggression": 1}], "double_team": TATUM}
    game.instruct(game.home, validate(raw, "everything", set(game.home.athletes), set(game.away.athletes), None, "test"))
    m = game.monitor(game.home)
    rows = {r["label"]: r for r in m["offense"] + m["defense"]}
    for r in m["offense"] + m["defense"]:
        print(f"{r['label']:38s} {r['before']:.3f} -> {r['after']:.3f}")
    assert rows["an offensive rebound, after a miss"]["after"] > rows["an offensive rebound, after a miss"]["before"]
    assert rows["seconds per first chance"]["after"] < rows["seconds per first chance"]["before"]
    sga = next(p for p in m["players"] if p["id"] == SGA)
    assert sga["after"] > sga["before"] + 0.03
    doubled = rows["Jayson Tatum acting (doubled)"]
    assert doubled["after"] < doubled["before"]
    assert {d["lever"] for d in m["directives"]} == {"crash_glass", "pace", "aggression", "double_team"}
    assert abs(sum(r["after"] for r in m["offense"][:5]) - 1) < 1e-9, "the five ways a chance ends add up to 1"


def test_calls_from_the_list_are_nudges_that_stack_and_fade(fitted, limits):
    model, _ = fitted
    game = Game(model, OKC, BOS, seed=3, limits=limits)

    def call(raw):
        game.nudge(game.home, validate(raw, "a call", set(game.home.athletes), set(game.away.athletes), None, "call"))
        return {(d.lever, d.player): d.value for d in game.home.directives}

    steps = [call({"team": {"attack_rim": 1}})[("attack_rim", None)] for _ in range(4)]
    print("attack the rim, four times:", steps)
    assert steps == [0.35, 0.7, 1.0, 1.0], "each call is one step, up to the limit"
    after = call({"team": {"attack_rim": -1}})
    print("then the opposite call:", after)
    assert after[("attack_rim", None)] == 0.65
    after = call({"team": {"three_point_rate": 1}})
    print("then a different offensive call:", after)
    assert after[("three_point_rate", None)] == 0.35 and after[("attack_rim", None)] == round(0.65 * 0.7, 2), "the older call fades"
    after = call({"team": {"pressure": 1}})
    assert after[("three_point_rate", None)] == 0.35, "a defensive call leaves the offense alone"
    for _ in range(8):
        after = call({"team": {"protect_paint": 1}})
    print("after eight more defensive calls:", after)
    assert ("pressure", None) not in after, "a call that fades below 0.05 is forgotten"
    call({"team": {"pace": 1}})
    after = call({"team": {"pace": -1}})
    assert ("pace", None) not in after and "pace" not in game.home.tactics, "back to where it started: nothing left"
    after = call({"players": [{"person_id": SGA, "shot_preference": {"zone": "rim", "value": 1}}]})
    after = call({"players": [{"person_id": SGA, "shot_preference": {"zone": "three", "value": 1}}]})
    print("SGA, rim then three:", after[("shot_preference", SGA)])
    assert after[("shot_preference", SGA)] == {"zone": "three", "value": 0.35}, "a new zone replaces the old one"


def test_every_call_has_an_energy_price_paid_in_minutes(fitted, limits):
    model, _ = fitted
    game = Game(model, OKC, BOS, seed=4, limits=limits)
    instruct(game, {"team": {"pressure": 1, "pace": 1}})
    print("press and run:", {game.home.athletes[p].profile.name: round(game.effort(game.home, p), 2) for p in game.home.lineup})
    assert all(abs(game.effort(game.home, p) - 1.6) < 1e-9 for p in game.home.lineup), "40% for the press, 20% for the pace"
    instruct(game, {"team": {"pressure": -1, "pace": -1}})
    assert all(abs(game.effort(game.home, p) - 0.8) < 1e-9 for p in game.home.lineup), "sitting back and walking it up save legs"
    minutes = {}
    for label, raw in (("normal", None), ("press all game", {"team": {"pressure": 1}})):
        total = 0.0
        for seed in range(200):
            g = Game(model, OKC, BOS, seed=seed, limits=limits)
            if raw:
                instruct(g, raw)
            total += g.play().home.athletes[SGA].seconds / 60
        minutes[label] = total / 200
    print("SGA minutes:", {k: round(v, 1) for k, v in minutes.items()})
    assert minutes["press all game"] < minutes["normal"] - 0.5, "tired players go to the bench sooner"


def test_a_players_defensive_call_is_a_fifth_of_the_teams(fitted, limits):
    model, _ = fitted
    team = Game(model, BOS, OKC, seed=5, limits=limits)  # Boston defends against OKC's possession below
    instruct(team, {"team": {"pressure": 1}})
    one = Game(model, BOS, OKC, seed=5, limits=limits)
    defender = one.home.lineup[0]
    instruct(one, {"players": [{"person_id": defender, "pressure": 1}]})
    base = Game(model, BOS, OKC, seed=5, limits=limits)

    def turnovers(game):
        choices, weights = game.chance_weights(game.away, game.home)
        return sum(w for (p, e), w in zip(choices, weights) if e == "turnover") / sum(weights)

    shares = {"nobody told": turnovers(base), "one player": turnovers(one), "the team": turnovers(team)}
    print("their turnover share:", {k: round(v, 4) for k, v in shares.items()})
    assert shares["nobody told"] < shares["one player"] < shares["the team"]
    assert abs((shares["one player"] - shares["nobody told"]) / (shares["the team"] - shares["nobody told"]) - 0.2) < 0.05
    assert abs(one.effort(one.home, defender) - 1.4) < 1e-9 and one.effort(one.home, one.home.lineup[1]) == 1.0, "only he pays"
    steals = {"base": 0, "told": 0}
    for label, raw in (("base", None), ("told", {"players": [{"person_id": defender, "pressure": 1}]})):
        for seed in range(150):
            g = Game(model, BOS, OKC, seed=seed, limits=limits)
            if raw:
                instruct(g, raw)
            steals[label] += g.play().home.athletes[defender].stats["STL"]
    print(f"{one.home.athletes[defender].profile.name}'s steals in 150 games:", steals)
    assert steals["told"] > steals["base"] * 1.2


def test_leaking_out_trades_rebounds_for_fast_breaks(fitted, limits):
    model, _ = fitted
    game = Game(model, BOS, OKC, seed=6, limits=limits)
    leaker = game.home.lineup[0]
    instruct(game, {"players": [{"person_id": leaker, "box_out": -1}]})
    assert game._box_out(game.home, leaker) < 1.0, "he leaves before the rebound"
    breaks = []
    for _ in range(400):
        game.leak_out = None
        if not game._rebound(game.away, game.home):  # Boston rebounds OKC's miss
            breaks.append(game.leak_out)
    print(len(breaks), "defensive rebounds, each with a break bonus of", breaks[0][1])
    assert breaks and all(b is not None and b[0] is game.home and b[1] > 1 for b in breaks), "every one starts a break"



def test_each_players_card_shows_what_his_calls_change(fitted, limits):
    model, _ = fitted
    game = Game(model, OKC, BOS, seed=7, limits=limits)
    for _ in range(5):
        game.step()
    raw = {"players": [{"person_id": SGA, "pressure": 1, "shot_preference": {"zone": "rim", "value": 1}}]}
    game.nudge(game.home, validate(raw, "a call", set(game.home.athletes), set(game.away.athletes), SGA, "call"))
    cards = {p["id"]: p for p in game.monitor(game.home)["players"]}
    sga = cards[SGA]
    for row in sga["offense"] + sga["defense"]:
        print(f"SGA {row['label']:28s} {row['before']:.3f} -> {row['after']:.3f}")
    print("tiring x", round(sga["effort"], 2), "| shoots x", round(sga["usage"], 3))
    rim = next(r for r in sga["offense"] if r["label"] == "a shot at the rim")
    steals = next(r for r in sga["defense"] if r["label"] == "of our steals")
    assert rim["after"] > rim["before"] and steals["after"] > steals["before"] and sga["effort"] > 1.0
    assert abs(sum(r["after"] for r in sga["offense"]) - sga["after"]) < 1e-9, "his rows add up to the share of our chances he takes"
    others = [p for pid, p in cards.items() if pid != SGA]
    assert all(next(r for r in p["defense"] if r["label"] == "of our steals")["after"] < next(r for r in p["defense"] if r["label"] == "of our steals")["before"]
               for p in others), "his teammates' share of the steals drops to match"


def test_game_mode_makes_a_call_felt_and_keeps_its_price(fitted, limits):
    """The live game stretches every coached effect BOOST times: three "crash the glass" calls should be
    impossible to miss, and the price (fast breaks the other way) grows with them."""
    model, _ = fitted
    result = {}
    for boost in (1.0, BOOST):
        for calls in (0, 3):
            oreb = burned = 0
            for seed in range(150):
                game = Game(model, OKC, BOS, seed=seed, limits=limits, boost=boost)
                for _ in range(calls):
                    game.nudge(game.home, validate({"team": {"crash_glass": 1}}, "crash", set(game.home.athletes), set(game.away.athletes), None, "call"))
                r = game.play()
                oreb += sum(a.stats["OREB"] for a in r.home.athletes.values())
                burned += sum(1 for e in r.events if e.credit and e.credit["call"] == "burned")
            result[(boost, calls)] = (oreb / 150, burned / 150)
    print({f"boost {b}, {c} calls": f"OKC OREB {o:.1f}, burned {x:.1f}" for (b, c), (o, x) in result.items()})
    faithful = result[(1.0, 3)][0] / result[(1.0, 0)][0]
    game_mode = result[(BOOST, 3)][0] / result[(BOOST, 0)][0]
    assert faithful < 1.4 < 1.8 < game_mode, "a real team gains a few boards; the game's team gains a lot"
    assert result[(BOOST, 3)][1] > result[(1.0, 3)][1] > 0 == result[(BOOST, 0)][1], "and gets burned in transition more"


def test_plays_are_credited_to_the_calls_that_made_them(fitted, limits):
    model, _ = fitted
    quiet = Game(model, OKC, BOS, seed=11, limits=limits, boost=BOOST).play()
    assert not any(e.credit for e in quiet.events), "no calls, nothing to credit"
    game = Game(model, OKC, BOS, seed=11, limits=limits, boost=BOOST)
    for raw in ({"team": {"pressure": 1}}, {"team": {"attack_rim": 1}}, {"players": [{"person_id": SGA, "aggression": 1}]}):
        game.nudge(game.home, validate(raw, "a call", set(game.home.athletes), set(game.away.athletes), None, "call"))
    credited = [e for e in game.play().events if e.credit]
    calls = {}
    for e in credited:
        calls[(e.credit["call"], e.credit["good"])] = calls.get((e.credit["call"], e.credit["good"]), 0) + 1
    print(len(credited), "credited plays:", calls)
    assert all(e.credit["team"] == "OKC" for e in credited), "only the coached team's calls get credit"
    assert any(good for _, good in calls) and any(not good for _, good in calls), "calls pay off, and they cost something"
    steals = [e for e in credited if e.credit["call"] in ("press", "steal")]
    assert steals and all(e.kind == "turnover" and e.team == "BOS" for e in steals), "the press is credited with BOS turnovers"


def test_in_game_mode_a_shot_goes_in_at_its_chance_times_his_energy(fitted, limits):
    model, _ = fitted
    for boost, expected in ((1.0, 1.0), (BOOST, 0.86)):
        game = Game(model, OKC, BOS, seed=1, limits=limits, boost=boost)
        athlete = game.home.athletes[SGA]
        athlete.energy = 0.3   # the fatigue clock, near where the coach subs him
        print(f"boost {boost}: energy shown and used {game.legs(athlete):.2f}")
        assert abs(game.legs(athlete) - expected) < 1e-9, "real stints show no fatigue in shooting; the game does"
    minutes, shown = 0, []
    game = Game(model, OKC, BOS, seed=2, limits=limits, boost=BOOST)
    while game.game_seconds < 600:
        game.step()
        shown.append(game.monitor(game.home)["players"][0]["energy"])
    print("energy shown over 10 minutes:", [round(e, 2) for e in shown[::8]])
    assert 0.8 <= min(shown) and max(shown) <= 1.0, "between 80% and 100%"


def test_calls_wear_off_unless_repeated(fitted, limits):
    model, _ = fitted
    game = Game(model, OKC, BOS, seed=12, limits=limits, boost=BOOST, half_life=180.0)
    for _ in range(3):
        game.nudge(game.home, validate({"team": {"pressure": 1}}, "press", set(game.home.athletes), set(game.away.athletes), None, "call"))
    seen = []
    while game.game_seconds < 900 and not game.done:
        game.step()
        pressure = game.home.tactics.get("pressure", 0.0)
        if not seen or game.game_seconds - seen[-1][0] >= 90:
            seen.append((game.game_seconds, round(pressure, 2), game.monitor(game.home)["directives"][0]["fades_in"] if game.home.directives else None))
    for t, value, left in seen:
        print(f"{t / 60:5.1f} min: pressure {value:+.2f}" + (f", forgotten in {left / 60:.1f} min" if left else ""))
    halfway = min(seen, key=lambda r: abs(r[0] - 180))
    assert abs(halfway[1] - 0.5 * 0.5 ** ((halfway[0] - 180) / 180)) < 0.05, "half as strong after one half-life"
    assert "pressure" not in game.home.tactics, "and forgotten after about 13 minutes"
    quiet = Game(model, OKC, BOS, seed=12, limits=limits, boost=BOOST)  # no half-life: simulations keep calls at full strength
    instruct(quiet, {"team": {"pressure": 1}})
    for _ in range(40):
        quiet.step()
    assert quiet.home.tactics["pressure"] == 1.0


def test_be_aggressive_shows_in_every_shot_he_takes(fitted, limits):
    """The card counts his shots as shares of all our chances, so a call that gives him the ball more
    raises each kind of shot he takes, not only his total."""
    model, _ = fitted
    game = Game(model, OKC, BOS, seed=8, limits=limits, boost=BOOST)
    game.step()
    game.nudge(game.home, validate({"players": [{"person_id": SGA, "aggression": 1}]}, "be aggressive",
                                   set(game.home.athletes), set(game.away.athletes), SGA, "call"))
    sga = next(p for p in game.monitor(game.home)["players"] if p["id"] == SGA)
    for row in sga["offense"]:
        print(f"{row['label']:24s} {100 * row['before']:5.1f}% -> {100 * row['after']:5.1f}% of our chances")
    assert all(row["after"] > row["before"] for row in sga["offense"])



def test_trash_talk_rattles_cold_players_and_fires_up_hot_ones(fitted, limits):
    """Talking trash moves his man's confidence by levers.TRASH_TALK, and with it his share of their chances;
    the whole team reaches all five by half as much. Cold players are rattled more often than hot ones, and the
    game's own random numbers are untouched (trash talk has its own)."""
    from hoopformer.game.levers import TRASH_TALK

    model, _ = fitted
    game = Game(model, OKC, BOS, seed=3, limits=limits, boost=BOOST)
    game.step()
    state = game.rng.getstate()
    tatum = game.away.athletes[TATUM]
    before = {pid: a.confidence for pid, a in game.away.athletes.items()}
    one = game.trash_talk(game.home, SGA, TATUM)
    reached = one["players"][0]
    print("SGA at Tatum:", "rattled" if one["rattled"] else "fired up", reached)
    assert [p["id"] for p in one["players"]] == [TATUM]
    assert abs(abs(tatum.confidence - before[TATUM]) - TRASH_TALK) < 1e-9
    assert (reached["share"][1] < reached["share"][0]) == one["rattled"], "his share of their chances moves with his confidence"
    assert all(a.confidence == before[pid] for pid, a in game.away.athletes.items() if pid != TATUM)
    assert game.rng.getstate() == state, "talking never draws from the game's own numbers"

    team = game.trash_talk(game.home, None, None)
    moved = [round(abs(game.away.athletes[p["id"]].confidence - p["confidence"][0]), 3) for p in team["players"]]
    print("the whole team:", "rattled" if team["rattled"] else "fired up", moved)
    assert len(team["players"]) == 5 and set(moved) == {TRASH_TALK / 2}

    rattled = {}
    for feeling in (0.3, 0.7):
        count = 0
        for seed in range(400):
            game = Game(model, OKC, BOS, seed=seed, limits=limits, boost=BOOST)
            game.step()
            game.away.athletes[TATUM].confidence = feeling
            count += game.trash_talk(game.home, SGA, TATUM)["rattled"]
        rattled[feeling] = count / 400
    print("rattled when cold (0.3):", rattled[0.3], "when hot (0.7):", rattled[0.7])
    assert rattled[0.3] > 0.6 and rattled[0.7] < 0.4


def test_the_scripted_coach_never_spends_a_human_coachs_timeouts(fitted, limits):
    """In the live game the home team is coached by a person, who has his own timeouts; the scripted coach still
    calls the other team's (and still substitutes for both)."""
    model, _ = fitted
    called = {"home": 0, "away": 0}
    for seed in range(5):
        game = Game(model, OKC, BOS, seed=seed, limits=limits)
        game.home.human, game.home.timeouts = True, 15
        result = game.play()
        for e in result.events:
            if e.kind == "timeout":
                called["home" if e.team == "OKC" else "away"] += 1
        assert result.home.timeouts == 15
    print("timeouts called over 5 games:", called)
    assert called["home"] == 0 and called["away"] > 0
