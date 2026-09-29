# Writing your first transformer: the Hoopformer guide

For marinelj. You write the model and the training loop; Claude builds the dataset and the evaluation harness, and reviews. Keeping the exam separate from the student is deliberate: whoever writes the model shouldn't also write the thing that grades it.

## 1. The task in one sentence

Given the ten players on the floor and the game situation when a possession starts, predict the probability of each outcome: **0, 1, 2, 3 or 4+ points**.

Measured on 134,426 possessions from 664 games of 2025-26:

| Points | 0 | 1 | 2 | 3 | 4+ |
|---|---|---|---|---|---|
| Share | 49.04% | 3.24% | 32.33% | 15.15% | 0.24% |

Always predicting these shares gives a **log-loss of 1.1260 nats**: the floor any model must go below. Expect the good models to win by **1 to 5 millinats** (0.001 to 0.005). That isn't failure. One possession is mostly luck, and the whole game of player evaluation lives in that thin signal. Report every result in millinats (mnats) so small differences are readable.

## 2. What you get from Claude (milestone 0)

**Dataset (ready):** `data/derived/possessions.parquet`, built by `uv run hoopformer dataset`, about 2.4 million rows. One row per possession; games in schedule order, possessions in game order:

| Column | Type | Meaning |
|---|---|---|
| `game_id`, `season`, `game_date` | str | where it happened |
| `split` | str | `train`, `validation` or `test` (see Splits below; defined once in `src/hoopformer/dataset.py`) |
| `possession` | int | 0, 1, 2... within the game. With `game_id`, it identifies the row: predictions are joined on these two |
| `period` | int | 1-4, 5+ is overtime |
| `seconds_left` | float | seconds left in the period when the possession started |
| `start_margin` | int | offense score minus defense score at the start |
| `offense_is_home` | bool | |
| `off_0` … `off_4` | int | personIds of the offense, sorted |
| `def_0` … `def_4` | int | personIds of the defense, sorted |
| `points` | int | 0-4, where 4 means 4 or more |

The lineup is the one on the floor when the possession ended, the same rule RAPM uses.

**Splits:** chronological, never random.

| Split | Seasons | Use |
|---|---|---|
| train | 2016-17 to 2023-24 | fitting |
| validation | 2024-25 | every tuning decision |
| test | 2025-26 | **locked**, see §6 |

**Grader (ready):** `src/hoopformer/evaluate.py`.
- `uv run hoopformer baselines`: fits B0-B2 once (cached in `data/derived/`) and prints them on validation. Run it first: B2's line is your bar.
- Save your model's predictions with `predictions_frame(rows, probabilities)`, where `rows` is the split's DataFrame and `probabilities` is your model's (n, 5) softmax output in the same order. Then `frame.to_parquet("data/derived/runs/<name>.parquet")`.
- `uv run hoopformer evaluate --predictions data/derived/runs/<name>.parquet --name "<name>"` scores it on validation next to B0-B2. It first checks that every row is predicted exactly once and each row's probabilities add up to 1.
- `--split test` is refused without `--final`, and every final run is appended to `docs/EXPERIMENTS.md`.

The three baselines:
- **B0 shares:** the training outcome shares.
- **B1 situation:** logistic regression on period, clock (including under-24-seconds and late-game flags) and margin.
- **B2 linear lineup:** logistic regression on one-hot offense and defense players plus B1's features, with its strength picked on validation. This is RAPM's classification cousin, and **the real bar.** For the test split, the baselines are refitted on train + validation, like your final model.

## 3. Milestones

Do them in order. Each one ends with a check that must pass before you move on.

### M1: Setup
- Work in `notebooks/M1_M2.ipynb` with the **Hoopformer (.venv)** kernel. PyTorch is already a project dependency, so `uv sync` installs it.
- Check `torch.backends.mps.is_available()`, then time a 4096×4096 matmul on `mps` vs `cpu`, calling `torch.mps.synchronize()` before reading the clock.
- **Learn:** tensors, devices, asynchronous GPU work, and why the GPU wins on big matrix products. On Apple silicon the gap is small, because the CPU has built-in matrix units: the MacBook Air M5 measured 1.96 TFLOPS on the CPU and 2.74 on the GPU (1.4×).
- **Check:** record both numbers in `docs/EXPERIMENTS.md`. From M4 on, time a real training step on both devices and use the faster one: for a model this small, that isn't guaranteed to be the GPU.

### M2: Data loader (prototype in `notebooks/M1_M2.ipynb`, then move to `src/hoopformer/data.py`)
- `build_vocab(train_df) -> dict[int, int]`: personId → index, **from train rows only**. Index 0 = PAD, 1 = UNK, 2 = MASK (used in M6).
- `PossessionDataset(df, vocab)`: a torch `Dataset` returning `players` (10 ints: offense then defense; unseen players → UNK), `situation` (float features: period, seconds_left / 720, clipped start_margin / 20, offense_is_home) and `label` (0-4).
- **Learn:** why the vocabulary and any scaling come from train only (leakage).
- **Checks, as tests on real rows:**
  - shapes are right
  - labels are in 0-4
  - a player who first appears in 2025-26 maps to UNK
  - no personId is on both sides of a row

### M3: A bag of players, no attention yet (`src/hoopformer/model.py`)
- Embed each player (`nn.Embedding`, width 64). Average the offense and average the defense, concatenate with the situation, then an MLP outputs 5 logits.
- **Learn:** embeddings, logits vs probabilities, cross-entropy. Also the "init well" trick: set the final layer's bias to the log of the class shares, so the loss starts at 1.126 instead of ln 5 = 1.609.
- **Checks:**
  - the loss at step 0 is about 1.126 with the bias trick
  - it can **overfit 256 possessions** to a loss near 0 (this proves the training loop works)
  - it beats B0 on validation

### M4: Training loop (`src/hoopformer/train.py`)
- AdamW (lr 3e-4, weight decay 0.01, none on biases or LayerNorm), warmup over the first 2% of steps, then cosine decay.
- Batch size 2048, gradient clipping at 1.0.
- Evaluate on validation every N steps. Stop early after 3 evaluations without improvement, and keep the best checkpoint in `data/derived/runs/` (git-ignored).
- Every run appends one line to `docs/EXPERIMENTS.md`: date, git hash, seed, config, best validation mnats vs B0 and B2, minutes.
- **Learn:** learning-rate schedules, early stopping, why weight decay on embeddings acts like RAPM's ridge penalty.
- **Check:** three seeds of M3 land within 1 mnat of each other. If not, find out why before going further.

### M5: The transformer
- Tokens: 10 player tokens plus 1 **situation token** that works like BERT's [CLS]. Add a learned **side embedding** (offense or defense) to each player token.
- `nn.TransformerEncoder` with 3 layers, d_model 128, 4 heads, feed-forward 512, dropout 0.1, `batch_first=True`, `norm_first=True`.
- Read the situation token's output and feed it to the 5-way head.
- **No positional encoding.** A lineup is a set, not a sentence: the order of the five players carries no information.
- **Learn:** self-attention (every player looks at the other nine), multi-head, residuals + LayerNorm, permutation invariance.
- **Checks:**
  - **shuffling the five offense players changes no logit** (in eval mode, to 1e-5)
  - overfit-256 still works
  - compare with M3 and B2 over 3 seeds

### M6: Composed player vectors and the masked-player task
- **Player vector** = `base[player] + B · delta[player, season]`, with a 16-number `delta` and heavier weight decay on it. A player-season never seen in training uses `delta = 0`.
- **Masked player:** in a copy of each batch, replace one random player token with MASK (keep its side embedding) and predict who it was over the vocabulary. **Tie the output weights to the embedding table.**
- Loss = outcome CE + λ × masked CE, starting with λ = 0.5. The outcome loss uses the unmasked copy.
- **Learn:** multi-task learning, weight tying, why guessing a hidden teammate forces each vector to encode style.
- **Checks:**
  - masked top-5 accuracy on validation
  - the 5 nearest neighbours of 5 well-known players look sensible to a fan
  - outcome mnats vs M5

### M7: Final run (v0.2 release)
- Pick the configuration on validation. **Pre-register** it and the pass threshold in `docs/preregistration/v0.2.md`, then commit, push and post the file's SHA-256.
- Retrain on 2016-17 to 2024-25, run `hoopformer evaluate --split test` **once**, and publish the result either way.

## 4. Guardrails (hard rules)

1. **The test season is locked.** The harness logs every test evaluation to `docs/EXPERIMENTS.md`, so the number of peeks is public. Tune on validation only.
2. **Chronological splits only.** A random split leaks the future and flatters every model.
3. **Train-only statistics.** Vocabulary, scaling, class shares and anything else learned from data comes from the training split.
4. **Inputs known at the start of the possession only:** the players, period, clock, margin and home. Never anything from later in the possession.
5. **No result without its baselines.** Every number sits next to B0 and B2 on the same split, as the mean of 3 seeds with the spread, in mnats.
6. **Pre-register before the test run:** configuration and pass threshold, pushed with the hash posted.
7. **Clean room.** Never read Unicorn's code, and never ask ChatGPT to reproduce it. Our design is in `docs/DESIGN.md`.
8. **Tests for every function** (AGENTS.md):
   - shapes
   - permutation invariance
   - overfit-256
   - masking touches exactly the chosen token
   - no NaNs after 100 steps
9. **Small commits** with what and why. Run `uv run pytest` before every push.
10. **Stuck for more than an hour?** Write down what you tried and ask. Claude and ChatGPT explain and review; they don't write your model.

## 5. When training goes wrong

| Symptom | Likely cause |
|---|---|
| Loss sits at 1.126 | The model ignores its inputs: check that embeddings get gradients, and the lr |
| Loss starts at 1.609 | Output bias not initialised (see M3) |
| Validation loss rises early | Overfitting: more dropout or weight decay, a smaller d_model |
| NaN | lr too high, missing gradient clipping, log of 0 |
| Seeds disagree by more than 1 mnat | Too few evaluation rows, or a bug that depends on data order |
| MPS errors about an unsupported op | Run with `PYTORCH_ENABLE_MPS_FALLBACK=1`, then report which op |

## 6. How your Coursera course maps onto this

| Course | Here |
|---|---|
| Week 1: neural networks | M3 |
| Week 2: training, softmax, Adam | M3 and M4 |
| Week 3: bias and variance, evaluation | M4, guardrails 1-5 |
| Week 4: trees and XGBoost | an extra baseline you can add to the harness later |

## 7. Reading, in this order

1. Andrej Karpathy, "A Recipe for Training Neural Networks" (2019 blog post). Read it before M3.
2. "The Annotated Transformer" (Harvard NLP), before M5.
3. PyTorch docs for `nn.TransformerEncoderLayer`.
4. Lee et al., "Set Transformer" (2019): why sets need no positions.
5. Devlin et al., "BERT" (2018), section 3.1 on the masked language model, before M6.
