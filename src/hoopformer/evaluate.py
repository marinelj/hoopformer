"""The grader: score a model's predictions against what happened, next to the baselines.

A model hands in a Parquet file with `game_id`, `possession` and `p0`...`p4`
(its probabilities of 0, 1, 2, 3 and 4+ points) for every row of one split.
The grader checks the file, then reports:

- log-loss: the average of -log(probability given to what actually happened).
  Lower is better; always predicting the outcome shares scores about 1.126.
- mnats vs B0: how many thousandths of a nat better than baseline B0.
- expected-points error: squared error of sum(k * p_k) against the points
  scored (4+ counts as 4).

Baselines, fitted on the training split (plus validation when scoring test):

- B0 shares: the training outcome shares, the same for every possession.
- B1 situation: logistic regression on period, clock and margin.
- B2 linear lineup: logistic regression on one-hot offense and defense players
  plus the B1 features, with its L2 strength picked on validation. This is
  RAPM's classification cousin, and the bar a lineup model has to clear.

The test season is locked: scoring it needs `final=True`, and every final
evaluation is appended to docs/EXPERIMENTS.md, so the number of peeks is public.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.linear_model import LogisticRegression

from hoopformer.dataset import KEY, MAX_POINTS

CLASSES = MAX_POINTS + 1
PROBABILITY_COLUMNS = [f"p{k}" for k in range(CLASSES)]
PLAYER_COLUMNS = [f"off_{i}" for i in range(5)] + [f"def_{i}" for i in range(5)]
B2_STRENGTHS = (1e-4, 1e-3, 1e-2, 1e-1)  # sklearn's C: smaller means a stronger L2 pull toward zero
EPSILON = 1e-15


class LockedSplitError(PermissionError):
    """The test season can only be scored with final=True, after pre-registration."""


def predictions_frame(rows: pd.DataFrame, probabilities: np.ndarray) -> pd.DataFrame:
    """Turn a model's (n, 5) probabilities for `rows`, in the same order, into the file the grader reads."""
    if probabilities.shape != (len(rows), CLASSES):
        raise ValueError(f"expected probabilities of shape ({len(rows)}, {CLASSES}), got {probabilities.shape}")
    frame = rows[KEY].reset_index(drop=True).copy()
    frame[PROBABILITY_COLUMNS] = probabilities
    return frame


def aligned_probabilities(predictions: pd.DataFrame, rows: pd.DataFrame) -> np.ndarray:
    """The (n, 5) probabilities in `rows` order, after checking the file covers every row exactly once."""
    missing = [c for c in KEY + PROBABILITY_COLUMNS if c not in predictions.columns]
    if missing:
        raise ValueError(f"predictions are missing columns {missing}")
    if predictions.duplicated(KEY).any():
        raise ValueError(f"{int(predictions.duplicated(KEY).sum())} possessions are predicted more than once")
    merged = rows[KEY].merge(predictions[KEY + PROBABILITY_COLUMNS], on=KEY, how="left", validate="one_to_one")
    unmatched = int(merged[PROBABILITY_COLUMNS[0]].isna().sum())
    extra = len(predictions) - (len(rows) - unmatched)
    if unmatched or extra:
        raise ValueError(f"predictions don't match the split: {unmatched} rows have no prediction, {extra} predictions match no row")
    probabilities = merged[PROBABILITY_COLUMNS].to_numpy(dtype=float)
    if not np.isfinite(probabilities).all() or (probabilities < 0).any():
        raise ValueError("probabilities must be finite and non-negative")
    sums = probabilities.sum(axis=1)
    if np.abs(sums - 1).max() > 1e-4:
        raise ValueError(f"each row's probabilities must add up to 1 (worst row adds up to {sums[np.abs(sums - 1).argmax()]:.6f})")
    return probabilities


def log_loss(probabilities: np.ndarray, labels: np.ndarray) -> float:
    """Average -log(probability given to the outcome that happened), in nats."""
    chosen = probabilities[np.arange(len(labels)), labels]
    return float(-np.log(np.clip(chosen, EPSILON, 1.0)).mean())


def expected_points_error(probabilities: np.ndarray, labels: np.ndarray) -> float:
    """Mean squared error of the expected points sum(k * p_k) against the points scored."""
    expected = probabilities @ np.arange(CLASSES)
    return float(np.mean((expected - labels) ** 2))


def class_shares(train: pd.DataFrame) -> np.ndarray:
    counts = np.bincount(train["points"].to_numpy(), minlength=CLASSES)
    return counts / counts.sum()


def situation_features(rows: pd.DataFrame) -> np.ndarray:
    """What B1 sees: period, clock, margin, home, and the end-of-period and late-game situations."""
    period = rows["period"].to_numpy()
    seconds = rows["seconds_left"].to_numpy()
    margin = np.clip(rows["start_margin"].to_numpy(), -20, 20) / 20
    late = ((period >= 4) & (seconds <= 120)).astype(float)  # fouling and clock management
    columns = [
        *(period == p for p in (1, 2, 3, 4)), period >= 5,
        seconds / 720,
        seconds <= 24,  # less than a shot clock left: end-of-period heaves
        margin,
        late, late * margin, late * np.abs(margin),
        rows["offense_is_home"].to_numpy(),
    ]
    return np.column_stack(columns).astype(float)


def lineup_matrix(rows: pd.DataFrame, players: dict[int, int]) -> sparse.csr_matrix:
    """B2's inputs: one-hot offense players, one-hot defense players, then the situation features.

    Players missing from `players` (never seen in fitting) get no column: the model treats them as average.
    """
    n, width = len(rows), len(players)
    blocks = []
    for side in ("off", "def"):
        ids = rows[[f"{side}_{i}" for i in range(5)]].to_numpy().ravel()
        columns = np.array([players.get(int(p), -1) for p in ids])
        row_index = np.repeat(np.arange(n), 5)
        known = columns >= 0
        blocks.append(sparse.csr_matrix((np.ones(int(known.sum())), (row_index[known], columns[known])), shape=(n, width)))
    blocks.append(sparse.csr_matrix(situation_features(rows)))
    return sparse.hstack(blocks, format="csr")


def player_index(rows: pd.DataFrame) -> dict[int, int]:
    return {int(p): i for i, p in enumerate(np.unique(rows[PLAYER_COLUMNS].to_numpy()))}


def fit_logistic(x, labels: np.ndarray, strength: float) -> LogisticRegression:
    return LogisticRegression(C=strength, max_iter=1000).fit(x, labels)


def full_probabilities(model: LogisticRegression, x) -> np.ndarray:
    """(n, 5) probabilities, with a zero column for any class the fitting data never had."""
    out = np.zeros((x.shape[0], CLASSES))
    out[:, model.classes_] = model.predict_proba(x)
    return out


def baseline_probabilities(dataset: pd.DataFrame, split: str, log=print) -> dict[str, np.ndarray]:
    """B0, B1 and B2 probabilities for every row of `split`, in dataset order.

    Validation is scored by baselines fitted on train. Test is scored by
    baselines refitted on train + validation, like the final model.
    """
    rows = dataset[dataset["split"] == split]
    fit_on = ["train"] if split == "validation" else ["train", "validation"]
    fit_rows = dataset[dataset["split"].isin(fit_on)]
    validation = dataset[dataset["split"] == "validation"]
    train = dataset[dataset["split"] == "train"]
    labels = fit_rows["points"].to_numpy()

    shares = class_shares(fit_rows)
    b0 = np.tile(shares, (len(rows), 1))
    b1 = full_probabilities(fit_logistic(situation_features(fit_rows), labels, 1.0), situation_features(rows))

    # B2's strength is always chosen on validation, from models fitted on train.
    train_players = player_index(train)
    best_strength, best_loss = None, np.inf
    for strength in B2_STRENGTHS:
        model = fit_logistic(lineup_matrix(train, train_players), train["points"].to_numpy(), strength)
        loss = log_loss(full_probabilities(model, lineup_matrix(validation, train_players)), validation["points"].to_numpy())
        log(f"B2 strength C={strength}: validation log-loss {loss:.5f}")
        if loss < best_loss:
            best_strength, best_loss = strength, loss
    if best_strength in (B2_STRENGTHS[0], B2_STRENGTHS[-1]):
        log(f"WARNING: B2's best C={best_strength} is at the edge of {B2_STRENGTHS}; the true best may lie beyond it")
    fit_players = player_index(fit_rows)
    b2_model = fit_logistic(lineup_matrix(fit_rows, fit_players), labels, best_strength)
    b2 = full_probabilities(b2_model, lineup_matrix(rows, fit_players))
    log(f"B2 uses C={best_strength}, fitted on {' + '.join(fit_on)}")
    return {"B0 shares": b0, "B1 situation": b1, "B2 linear lineup": b2}


def cached_baselines(dataset: pd.DataFrame, split: str, cache_dir: Path, refresh: bool = False, log=print) -> dict[str, np.ndarray]:
    """Baseline probabilities, fitted once per dataset version and split, then read from disk."""
    rows = dataset[dataset["split"] == split]
    version = hashlib.sha256(pd.util.hash_pandas_object(dataset[KEY + ["split", "points"]], index=False).to_numpy().tobytes()).hexdigest()[:12]
    path = cache_dir / f"baselines_{split}_{version}.parquet"
    if path.exists() and not refresh:
        cached = pd.read_parquet(path)
        return {name: cached[[f"{name}|{c}" for c in PROBABILITY_COLUMNS]].to_numpy() for name in dict.fromkeys(c.split("|")[0] for c in cached.columns if "|" in c)}
    baselines = baseline_probabilities(dataset, split, log=log)
    frame = rows[KEY].reset_index(drop=True).copy()
    for name, probabilities in baselines.items():
        frame[[f"{name}|{c}" for c in PROBABILITY_COLUMNS]] = probabilities
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return baselines


def score(probabilities: dict[str, np.ndarray], labels: np.ndarray) -> pd.DataFrame:
    """One line per model: log-loss, mnats better than B0, expected-points error."""
    reference = log_loss(probabilities["B0 shares"], labels)
    lines = []
    for name, p in probabilities.items():
        loss = log_loss(p, labels)
        lines.append({"model": name, "log_loss": loss, "mnats_vs_B0": 1000 * (reference - loss),
                      "expected_points_error": expected_points_error(p, labels)})
    return pd.DataFrame(lines)


def evaluate(predictions: pd.DataFrame, dataset: pd.DataFrame, split: str, cache_dir: Path, model_name: str = "your model",
             final: bool = False, experiments_log: Path = Path("docs/EXPERIMENTS.md"), log=print) -> pd.DataFrame:
    """Score predictions for one split, next to B0, B1 and B2."""
    if split not in ("validation", "test"):
        raise ValueError("evaluate the validation or test split")
    if split == "test" and not final:
        raise LockedSplitError("the test season is locked: pre-register first (TRANSFORMER_GUIDE.md M7), then pass final=True / --final")
    rows = dataset[dataset["split"] == split].reset_index(drop=True)
    labels = rows["points"].to_numpy()
    probabilities = {model_name: aligned_probabilities(predictions, rows)}
    probabilities.update(cached_baselines(dataset, split, cache_dir, log=log))
    report = score({"B0 shares": probabilities["B0 shares"], **probabilities}, labels)
    if split == "test":
        attempt = sum(1 for line in experiments_log.read_text().splitlines() if "| TEST EVALUATION |" in line) + 1 if experiments_log.exists() else 1
        mine = report[report.model == model_name].iloc[0]
        b2 = report[report.model == "B2 linear lineup"].iloc[0]
        digest = hashlib.sha256(pd.util.hash_pandas_object(predictions, index=False).to_numpy().tobytes()).hexdigest()[:16]
        line = (f"| {datetime.now(timezone.utc):%Y-%m-%d} | grader | | | TEST EVALUATION | attempt {attempt}: {model_name} "
                f"log-loss {mine.log_loss:.5f} ({mine.mnats_vs_B0:+.2f} mnats vs B0, {mine.mnats_vs_B0 - b2.mnats_vs_B0:+.2f} vs B2), predictions hash {digest} |")
        with experiments_log.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        log(f"logged test attempt {attempt} to {experiments_log}")
    return report
