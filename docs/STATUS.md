# Status

Updated 2026-09-29. v0.1 (data pipeline, RAPM, season simulator, pre-registered 2026-27 predictions) is due before opening night, around Oct 20.

## Done

| Piece | Where | Checked how |
|---|---|---|
| Fetcher | `hoopformer fetch`, `src/hoopformer/fetch.py` | Rejects NBA's HTML block page; each file's SHA-256 goes into `manifests/raw.jsonl`; atomic writes; re-runs skip cached games |
| Lineups | `src/hoopformer/lineups.py` | On all 11,979 games from 2016-17 through 2025-26, every player's rebuilt minutes match the official box score to the second |
| Possessions and points per stint | `src/hoopformer/possessions.py` | All 11,979 games add up to the final score; 2,397,244 possession ends pass the alternation check |
| RAPM baseline | `hoopformer rapm`, `src/hoopformer/rapm.py` | Ridge strength chosen on the latest 20% of games; 2025-26 league rate is 114.6 per 100 and 2024-25 is 113.6 |

## 10-season download complete (Mac Studio)

The regular-season archive was downloaded from stats.nba.com and verified on 2026-09-29. Raw responses remain in the git-ignored `data/` directory; `manifests/raw.jsonl` commits 23,968 file records with their SHA-256 hashes.

| Season | Games |
|---|---:|
| 2025-26 | 1,230 |
| 2024-25 | 1,230 |
| 2023-24 | 1,230 |
| 2022-23 | 1,230 |
| 2021-22 | 1,230 |
| 2020-21 | 1,080 |
| 2019-20 | 1,059 |
| 2018-19 | 1,230 |
| 2017-18 | 1,230 |
| 2016-17 | 1,230 |
| **Total** | **11,979** |

The retry pass ended with `0 failed` for every season. `uv run pytest` reports `49 passed, 1 deselected`; the deselected test is the explicit stats.nba.com network smoke test. RAPM also completes for both 2025-26 and 2024-25.

## Next

1. RAPM over several seasons (later seasons weigh more).
2. The 2026-27 schedule and current rosters from nba_api.
3. The season simulator: team strength = player ratings × expected minutes; simulate the schedule thousands of times.
4. Backtest the method on 2025-26, then pre-register the 2026-27 win totals and playoff odds: push them, and post their SHA-256 on X before opening night.

## v0.2 (the transformer, due at the NBA Cup, Nov-Dec)

- marinelj writes the model and training loop, following `docs/TRANSFORMER_GUIDE.md`.
- Done: `hoopformer dataset` (`src/hoopformer/dataset.py`) writes `data/derived/possessions.parquet`, one row per possession with the split column. On 664 games of 2025-26: 134,426 rows, outcome shares 0:49.04% 1:3.24% 2:32.33% 3:15.15% 4+:0.24%.
- Next (Claude): `hoopformer evaluate` (locked splits, baselines B0-B2).

## Known limits

- 0.090% of possession ends repeat the same team twice in a row. This is usually a lone free throw after which the fouled team keeps the ball.
- Lineup and historical-name rules are verified for 2016-17 onward. A pre-2016 backfill may expose additional legacy feed spellings or ordering quirks.
