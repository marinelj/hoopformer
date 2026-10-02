"""Tests for coaching in plain language: lever limits, validation, the engine's levers, memory, translators.

All on real 2025-26 data. Lever effects are measured with common random numbers:
the same seeds with and without an instruction, so the difference is the lever,
not luck. The Qwen tests need DASHSCOPE_API_KEY and the network:
`uv run pytest -m network -k qwen`.
"""

import os
from pathlib import Path

import numpy as np
import pytest

from hoopformer.game.engine import Game
from hoopformer.game.levers import TEAM_LEVERS, lever_limits, measure_limits, multiplier, validate
from hoopformer.game.translator import HOLDOUT_PHRASES, PHRASES, check_phrases, find_players, load_env, translate

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
        for seed in range(150):
            game = Game(model, BOS, OKC, seed=seed, limits=limits)  # Boston coaches, doubling SGA
            if raw:
                game.instruct(game.home, validate(raw, "double SGA", set(game.home.athletes), set(game.away.athletes), None, "test"))
            total += game.play().away.athletes[SGA].stats["FGA"]
        shots[label] = total / 150
    print(shots)
    assert shots["doubled"] < shots["free"] * 0.85


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
def test_qwen_translates_coach_phrases(fitted, limits):
    load_env()
    if not os.environ.get("DASHSCOPE_API_KEY"):
        pytest.skip("set DASHSCOPE_API_KEY (shell profile or .env) to test Qwen")
    model, _ = fitted
    game = mid_game(model, limits)
    seen, total, rows = check_phrases(game, game.home, "qwen", PHRASES)
    held_out, total_held, rows_held = check_phrases(game, game.home, "qwen", HOLDOUT_PHRASES)
    seconds = np.mean([r["seconds"] for r in rows + rows_held])
    print(f"Qwen: {seen}/{total} and {held_out}/{total_held} held out; {seconds:.1f} s per instruction")
    print("sample replies:", [r["reply"] for r in rows[:5]])
    assert seen >= 0.9 * total and held_out >= 0.85 * total_held


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
