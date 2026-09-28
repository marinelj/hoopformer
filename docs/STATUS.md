# Status

Updated 2026-09-28. v0.1 (data pipeline, RAPM, season simulator, pre-registered 2026-27 predictions) is due before opening night, around Oct 20.

## Done

| Piece | Where | Checked how |
|---|---|---|
| Fetcher | `hoopformer fetch`, `src/hoopformer/fetch.py` | Rejects NBA's HTML block page; each file's SHA-256 goes into `manifests/raw.jsonl`; atomic writes; re-runs skip cached games |
| Lineups | `src/hoopformer/lineups.py` | On all 664 games tested (2025-26), every player's rebuilt minutes match the official box score to the second |
| Possessions and points per stint | `src/hoopformer/possessions.py` | Every tested game's points add up to the final score; possessions average 0.99 of the box-score estimate |
| RAPM baseline | `hoopformer rapm --season 2025-26`, `src/hoopformer/rapm.py` | Ridge strength chosen on the latest 20% of games; league rate 114.6 per 100 matches the box scores |

## In progress: the 10-season download (on the Mac Studio)

A first download on the MacBook Air was stopped on purpose at 664 games of 2025-26. The Mac Studio starts its own copy. Run from the repo root on the Studio:

```bash
caffeinate -i uv run hoopformer fetch --season 2025-26 2024-25 2023-24 2022-23 2021-22 2020-21 2019-20 2018-19 2017-18 2016-17
```

- About 4.6 seconds per game: roughly 16 hours for 12,300 games and about 3 GB in `data/`, which git ignores.
- Safe to stop and re-run: games already on disk are skipped.
- It must run on a Mac at home. stats.nba.com doesn't answer cloud machines or sandboxed shells.
- When it finishes:
  1. Run `uv run pytest`. The lineup and points checks then run on every downloaded game, and older seasons have not been tested yet.
  2. Fix or report any failing games.
  3. Commit `manifests/raw.jsonl`. Never commit `data/`.

## Next

1. RAPM over several seasons (later seasons weigh more).
2. The 2026-27 schedule and current rosters from nba_api.
3. The season simulator: team strength = player ratings × expected minutes; simulate the schedule thousands of times.
4. Backtest the method on 2025-26, then pre-register the 2026-27 win totals and playoff odds: push them, and post their SHA-256 on X before opening night.

## v0.2 (the transformer, due at the NBA Cup, Nov-Dec)

- marinelj writes the model and training loop, following `docs/TRANSFORMER_GUIDE.md`.
- Claude builds `hoopformer dataset` (possession-level Parquet) and `hoopformer evaluate` (locked splits, baselines B0-B2) by about Oct 3.

## Known limits

- 0.12% of possession ends repeat the same team twice in a row. This is a lone free throw after which the fouled team keeps the ball.
- The lineup and name-matching rules were built on 2025-26 data only.
