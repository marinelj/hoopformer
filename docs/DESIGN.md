# Hoopformer design (draft v0)

Status: draft for review, 2026-09-27. Nothing here is final until marinelj signs off.

## 1. Goal

Learn a vector for every NBA player from who was on the floor and what happened on each possession. Use those vectors on the court (possessions, lineups, games, seasons) and beyond it (global attention). Grade every claim in public against simple baselines.

## 2. Credits and the clean-room rule

The core model re-implements ideas that others have described publicly:

- **Unicorn** by Nick Brown ([uptownnickbrown/unicorn](https://github.com/uptownnickbrown/unicorn)). A transformer over the 10 players on the floor, with player vectors made of a career base plus a per-season adjustment. It is trained to predict possession outcomes and to identify a hidden player, and it is warm-started from LLM-written scouting reports.
- **NBA2Vec** ([arXiv 2302.13386](https://arxiv.org/abs/2302.13386)). Fixed player vectors learned by predicting possession outcomes from the offensive and defensive players on the court.

Related: [nba-lineup-model](https://github.com/EvanZ/nba-lineup-model) by Evan Zamir, which covers an audited lineup data pipeline, RAPM, and a transformer residual.

Rule: Unicorn and nba-lineup-model publish no license, so their code is all rights reserved. Hoopformer is written from public descriptions only. Nobody on the project copies or reads their source code.

## 3. Data

| Item | Plan |
|---|---|
| Source | stats.nba.com play-by-play, plus box scores to get the starters |
| Where it runs | On marinelj's Mac. stats.nba.com blocks cloud servers, including GitHub Actions. |
| Storage | Raw responses are cached locally, byte for byte. A SHA-256 manifest of them is committed to git; the raw data never is. |
| Parser | Our own (`src/hoopformer/lineups.py`, `possessions.py`). `pbpstats` hasn't had a release since April 2024. On every tested game, rebuilt lineups reproduce official minutes to the second and points add up to the final score. |
| Unit | One possession segment, during which the same 10 players stay on the floor |
| First scope | The last 10 seasons (2016-17 to 2025-26), roughly 2.5M possessions. Backfill to 1996-97 once the pipeline is proven; older play-by-play has more lineup gaps. |

Each row holds:
- game id and season
- period and seconds left
- score margin, and whether the offense is at home
- 5 offense player ids and 5 defense player ids
- points scored (0 to 4+) and how the possession ended

## 4. Model

**Tokens.** 10 player tokens: offense in slots 0-4, defense in 5-9, with no positions. Plus 1 context token: season, period, clock bucket, margin bucket, home/away.

**Player vector.** `base[player] + B · delta[player, season]`
- `base` is one learned vector per player: their career-long style.
- `delta` is a small per-season adjustment (e.g. 32 numbers), projected up to model width by the learned matrix `B`. Keeping it small stops a 400-possession season from overfitting.
- A side embedding marks offense vs. defense.

**Encoder.** A standard transformer encoder. Start small: 4 layers, 4 heads, width 256, about 4M parameters. Scale up only when held-out loss improves.

**Heads (trained together).**
1. **Possession outcome:** probabilities for 0, 1, 2, 3 and 4+ points (decided 2026-09-28). These give expected points.
2. **Masked player:** in a copy of each batch, hide 1-2 of the 10 players and predict who they were, the way BERT predicts masked words. This forces each vector to encode a player's style, not just their value.

Loss = outcome cross-entropy + λ × masked-player cross-entropy.

## 5. What Hoopformer adds

1. **Season deltas you can forecast.** A small recurrent network (GRU) predicts next season's `delta` from a player's past deltas and age. That gives preseason forecasts and a model that works on seasons it never trained on. Unicorn's README names transfer to an unseen season as its current weakness.
2. **Leak-proof LLM warm start.** The scouting text is generated only from stats available before the training cutoff, with names removed, so the LLM can't leak how a career turned out. This comes later as a measured experiment, not in the first transformer.
3. **RAPM on every scoreboard.** Every result is reported next to ridge-regression RAPM on the same split.
4. **Beyond the court.** Inputs: player vectors, performance forecasts, attention history (Wikipedia pageviews by language, Google Trends by country) and World Bank country weights. Output: next month's attention per country. Graded against All-Star fan votes and the NBA's jersey-sales rankings.
5. **Actually open.** Apache-2.0 code, released weights, and a pip package.

## 6. Evaluation

- **Split:** train through 2024-25, test on 2025-26. Never split at random: that leaks the future.
- **Baselines:** league average, and ridge RAPM.
- **Metrics:**
  - possession log-loss and expected-points error
  - game winner from the ten starters (accuracy and Brier score)
  - held-out five-man lineups: rank correlation of predicted vs. actual net rating
  - masked player: top-1 and top-5 accuracy
  - a calibration plot
- **Pre-registration:** before each run, commit and push the test set and the pass/fail thresholds, and post the file's SHA-256 on X. Publish the result either way.

## 7. Release plan

| Release | NBA moment | Content |
|---|---|---|
| v0.1 | Before opening night | Data pipeline, RAPM, season simulator, pre-registered 2026-27 win totals |
| v0.2 | NBA Cup (Nov-Dec) | The transformer (random start) vs. RAPM |
| v0.3 | Dec-Jan | Beyond the court #1: All-Star fan-vote forecast, pre-registered before voting opens; LLM warm-start experiment |
| v0.4 | Trade deadline (Feb) | Season-delta forecaster; trade simulator |
| v0.5+ | Playoffs to draft | Series simulator, calibration vs. prediction markets, rookies |

## 8. Decisions

| Question | Decision (2026-09-28) |
|---|---|
| Outcome classes | Points scored: 0, 1, 2, 3, 4+ |
| First scope | 10 seasons, 2016-17 to 2025-26 |
| Who writes the transformer | marinelj writes the model and training loop (`docs/TRANSFORMER_GUIDE.md`). Claude builds the dataset and evaluation harness, and reviews. |
