"""Tests for the grader, on the real possession dataset."""

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hoopformer.dataset import KEY
from hoopformer.evaluate import (
    B2_STRENGTHS,
    CLASSES,
    PROBABILITY_COLUMNS,
    LockedSplitError,
    aligned_probabilities,
    baseline_probabilities,
    cached_baselines,
    class_shares,
    evaluate,
    expected_points_error,
    fit_logistic,
    full_probabilities,
    lineup_matrix,
    log_loss,
    player_index,
    predictions_frame,
    score,
    situation_features,
)

DATASET = Path("data/derived/possessions.parquet")


GAMES_PER_SPLIT = 30  # a real sample: fitting B2 on all 1.9M training rows takes minutes per fit


@pytest.fixture(scope="module")
def dataset():
    if not DATASET.exists():
        pytest.skip("build the dataset first: uv run hoopformer dataset")
    frame = pd.read_parquet(DATASET)
    if not {"train", "validation", "test"} <= set(frame.split):
        pytest.skip("the dataset needs train, validation and test rows")
    sample = [frame[frame.split == split].game_id.drop_duplicates().sort_values().head(GAMES_PER_SPLIT)
              for split in ("train", "validation", "test")]
    return frame[frame.game_id.isin(pd.concat(sample))].reset_index(drop=True)


def shares_predictions(dataset, split):
    rows = dataset[dataset.split == split]
    return predictions_frame(rows, np.tile(class_shares(dataset[dataset.split == "train"]), (len(rows), 1)))


def test_log_loss_of_uniform_and_perfect_guesses():
    labels = np.array([0, 2, 3, 1, 4])
    uniform = np.full((5, CLASSES), 1 / CLASSES)
    perfect = np.eye(CLASSES)[labels]
    print("uniform:", log_loss(uniform, labels), "perfect:", log_loss(perfect, labels))
    assert log_loss(uniform, labels) == pytest.approx(math.log(5))
    assert log_loss(perfect, labels) == pytest.approx(0.0, abs=1e-12)
    assert np.isfinite(log_loss(np.eye(CLASSES)[[1, 1, 1, 1, 1]], labels)), "a 0 probability is clipped, not infinite"


def test_expected_points_error():
    probabilities = np.array([[0.5, 0, 0.5, 0, 0]])  # expects 1 point
    assert expected_points_error(probabilities, np.array([3])) == pytest.approx(4.0)


def test_predictions_frame_and_alignment_round_trip(dataset):
    rows = dataset[dataset.split == "validation"]
    probabilities = np.random.default_rng(0).dirichlet(np.ones(CLASSES), size=len(rows))
    frame = predictions_frame(rows, probabilities)
    shuffled = frame.sample(frac=1, random_state=1)
    print(frame.head(2).to_string())
    assert list(frame.columns) == KEY + PROBABILITY_COLUMNS
    assert np.allclose(aligned_probabilities(shuffled, rows.reset_index(drop=True)), probabilities), "order in the file doesn't matter"


def test_aligned_probabilities_rejects_bad_files(dataset):
    rows = dataset[dataset.split == "validation"].reset_index(drop=True)
    good = shares_predictions(dataset, "validation")
    problems = {
        "missing rows": good.iloc[1:],
        "duplicates": pd.concat([good, good.iloc[:1]]),
        "not adding up to 1": good.assign(p0=good.p0 + 0.1),
        "negative": good.assign(p0=-good.p0),
        "missing column": good.drop(columns="p4"),
    }
    for name, bad in problems.items():
        with pytest.raises(ValueError) as error:
            aligned_probabilities(bad, rows)
        print(f"{name}: {error.value}")


def test_situation_features_mark_the_end_of_periods(dataset):
    rows = dataset.head(1000)
    features = situation_features(rows)
    last_shot = features[:, 6]
    print("shape", features.shape, "| last-shot possessions:", int(last_shot.sum()))
    assert features.shape == (1000, 12), "4 quarters, overtime, clock, last shot, margin, late game x3, home"
    assert (last_shot == (rows.seconds_left.to_numpy() <= 24)).all()


def test_lineup_matrix_has_ten_players_and_treats_unknowns_as_average(dataset):
    train = dataset[dataset.split == "train"]
    players = player_index(train)
    x = lineup_matrix(train.head(200), players)
    player_part = x[:, : 2 * len(players)]
    print("shape", x.shape, "| players per row:", sorted(set(np.diff(player_part.indptr))))
    assert x.shape == (200, 2 * len(players) + 12)
    assert set(np.diff(player_part.indptr)) == {10}
    test_rows = dataset[dataset.split == "test"].head(500)
    unknown_rows = np.diff(lineup_matrix(test_rows, players)[:, : 2 * len(players)].indptr)
    assert unknown_rows.min() < 10, "players never seen in training get no column"


def test_full_probabilities_fill_classes_the_fit_never_saw():
    x = np.array([[0.0], [1.0], [2.0], [3.0]])
    model = fit_logistic(x, np.array([0, 2, 0, 2]), 1.0)
    probabilities = full_probabilities(model, x)
    assert probabilities.shape == (4, CLASSES) and np.allclose(probabilities.sum(axis=1), 1)
    assert (probabilities[:, [1, 3, 4]] == 0).all()


def test_baselines_beat_shares_or_tie_on_validation(dataset):
    baselines = baseline_probabilities(dataset, "validation", log=print)
    report = score(baselines, dataset[dataset.split == "validation"].points.to_numpy())
    print(report.round(5).to_string(index=False))
    assert list(report.model) == ["B0 shares", "B1 situation", "B2 linear lineup"]
    assert report.set_index("model").loc["B1 situation", "mnats_vs_B0"] > 0, "the clock and score margin carry real information"
    assert len(B2_STRENGTHS) >= 3


def test_cached_baselines_are_read_back_unchanged(dataset, tmp_path):
    first = cached_baselines(dataset, "validation", tmp_path, log=print)
    second = cached_baselines(dataset, "validation", tmp_path, log=lambda _: pytest.fail("should come from the cache"))
    assert len(list(tmp_path.glob("baselines_validation_*.parquet"))) == 1
    for name in first:
        assert np.allclose(first[name], second[name])


def test_evaluate_scores_validation_next_to_the_baselines(dataset, tmp_path):
    report = evaluate(shares_predictions(dataset, "validation"), dataset, "validation", tmp_path, model_name="shares again")
    print(report.round(5).to_string(index=False))
    assert list(report.model) == ["B0 shares", "shares again", "B1 situation", "B2 linear lineup"]
    assert report.set_index("model").loc["shares again", "mnats_vs_B0"] == pytest.approx(0.0, abs=1e-9)


def test_the_test_season_is_locked_and_every_final_run_is_logged(dataset, tmp_path):
    predictions = shares_predictions(dataset, "test")
    log = tmp_path / "EXPERIMENTS.md"
    with pytest.raises(LockedSplitError):
        evaluate(predictions, dataset, "test", tmp_path)
    evaluate(predictions, dataset, "test", tmp_path, model_name="shares", final=True, experiments_log=log)
    evaluate(predictions, dataset, "test", tmp_path, model_name="shares", final=True, experiments_log=log)
    lines = log.read_text().splitlines()
    print("\n".join(lines))
    assert len(lines) == 2 and "attempt 1" in lines[0] and "attempt 2" in lines[1]


def test_cli_evaluate_refuses_the_test_split_without_final(dataset, tmp_path):
    from hoopformer.cli import main

    sample, path = tmp_path / "sample.parquet", tmp_path / "predictions.parquet"
    dataset.to_parquet(sample)
    shares_predictions(dataset, "validation").to_parquet(path)
    assert main(["evaluate", "--predictions", str(path), "--split", "validation", "--dataset", str(sample), "--data-dir", str(tmp_path)]) == 0
    shares_predictions(dataset, "test").to_parquet(path)
    assert main(["evaluate", "--predictions", str(path), "--split", "test", "--dataset", str(sample), "--data-dir", str(tmp_path)]) == 1


def test_cli_baselines_prints_the_bar(dataset, tmp_path, capsys):
    from hoopformer.cli import main

    sample = tmp_path / "sample.parquet"
    dataset.to_parquet(sample)
    assert main(["baselines", "--dataset", str(sample), "--data-dir", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    print(output)
    assert "B2 linear lineup" in output and "mnats_vs_B0" in output
