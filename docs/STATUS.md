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

## The game: the centre of the NBA lab (decided 2026-10-01)

- Design and decisions: `docs/GAME_DESIGN.md`. Real players for a private prototype; names live in a separate layer.
- The 5-day build, Oct 1-5, by Claude on the MacBook Air, in `src/hoopformer/game/`. Other teammates: please don't edit that folder until the build is pushed.
- Day 1 (done): the action counter reproduces official box scores. The engine plays a game in about 2 ms with real players' rates, and 1,000 simulated games match the real 2025-26 season on 16 statistics. Try `uv run hoopformer actions` then `uv run hoopformer play --home OKC --away HOU --play-by-play`. Details are in GAME_DESIGN.md §9.
- Day 2 (done): the engine moves one possession at a time (`Game.step`); fatigue and a scripted coach make real-looking rotations (28 substitutions and 5.1 timeouts per team-game vs 26 and 5.4 real); home court is spread over shooting, free throws and turnovers; 2026-27 rosters are fetched and playable (`--rosters 2026-27`). After pulling, refit once with `uv run hoopformer actions` (the model gained home-court fields). Details are in GAME_DESIGN.md §9.
- Day 3 (done): coach language. 13 levers with limits measured from real teams and players, a Qwen translator (`qwen3.8-max`) with a keyword-rules baseline and fallback, athlete memory (directives with the coach's words, confidence), unmapped phrases logged. Try `uv run hoopformer coach "Push the pace"` and `uv run hoopformer play ... --say "Q2 6:00 Pack the paint"`. Qwen needs `DASHSCOPE_API_KEY` (in `.env`, never committed); it scores 19/20 on phrases it has never seen, against 5/20 for keyword rules. Details are in GAME_DESIGN.md §9.
- Day 4 (done): coach a live game in the browser. `uv run hoopformer serve`, then open http://127.0.0.1:8000/. The engine runs on the server one possession ahead of the page; typed or spoken words go to Qwen on the server (the key never reaches the browser); timeouts and the tactics panel change the game too. Details are in GAME_DESIGN.md §9.
- Day 4 follow-up (Oct 4): instructions now show on the court (zone, press, crash, pace, drives, spacing, with a play-call strip and shouted calls), and the live page has an engine monitor with each directive's effect on the next chance. Details are in GAME_DESIGN.md §9.
- Second follow-up (Oct 4): the talk rows are lists of calls that switch between offense and defense with the ball; a picked call goes straight to the engine (`POST /api/call`, no language model). Calls are nudges: the same call again pushes further, the opposite call pulls back, and newer calls fade older ones of the same kind. Playback is 1× only. Qwen failures now show their reason. Restart `hoopformer serve` after pulling. Details are in GAME_DESIGN.md §9.
- Third follow-up (Oct 4): every call has a price. Calls cost energy (tired players sit sooner), confidence follows makes and misses as measured in real 2025-26 games (6% more shots after two makes, slightly harder ones), and one player has 8 defensive calls. Details are in GAME_DESIGN.md §9.
- Fourth follow-up (Oct 4): a monitor card for each player on the floor replaces the bench panels; the call list switches between offense and defense even while open; a 0.5× button. Details are in GAME_DESIGN.md §9.
- Fifth follow-up (Oct 4): game mode. The live app boosts every coached effect 5× (simulations stay faithful), tired legs cost shooting in game mode, plays are credited to the calls that made them (callouts, a tally, badges, speech bubbles), and each call reports its biggest effects. `hoopformer serve --boost 1` plays the faithful version. Details are in GAME_DESIGN.md §9.
- Sixth follow-up (Oct 4): calls wear off in the live game (half-life 3 minutes of game time, `--half-life`); repeat a call to keep it strong. Details are in GAME_DESIGN.md §9.
- v0.1 moves to Oct 6-17, still locked before opening night.

## Next

1. RAPM over several seasons (later seasons weigh more).
2. The 2026-27 schedule from nba_api (current rosters: done, `fetch --rosters`).
3. The season simulator: team strength = player ratings × expected minutes; simulate the schedule thousands of times.
4. Backtest the method on 2025-26, then pre-register the 2026-27 win totals and playoff odds: push them, and post their SHA-256 on X before opening night.

## v0.2 (the transformer, due at the NBA Cup, Nov-Dec)

- marinelj writes the model and training loop, following `docs/TRANSFORMER_GUIDE.md`.
- Done: `hoopformer dataset` (`src/hoopformer/dataset.py`) writes `data/derived/possessions.parquet`, one row per possession with the split column. On 664 games of 2025-26: 134,426 rows, outcome shares 0:49.04% 1:3.24% 2:32.33% 3:15.15% 4+:0.24%.
- Done: `notebooks/G2_coaching.ipynb` (game days 2-3: stepping a game, fatigue, calibrating against real rotations, lever limits, common random numbers, the LLM translator and its validator, overfitting with held-out phrases; 8 exercises, verified end to end). `notebooks/G1_game_engine.ipynb` (a guided tour of the game engine with 5 exercises: counting a game, shrinkage, fitting, one chance, a same-seed experiment; verified end to end). `notebooks/M1_M2.ipynb` (guided cells for marinelj, each with a check cell; verified end to end against a private reference solution) and `notebooks/playground.ipynb`. The Jupyter kernel is registered with `uv run python -m ipykernel install --user --name hoopformer --display-name "Hoopformer (.venv)"`.
- Done: the grader, `hoopformer baselines` and `hoopformer evaluate` (`src/hoopformer/evaluate.py`): B0 shares, B1 situation, B2 linear lineup with its strength picked on validation; the test split is locked behind `--final` and logged. The dataset gained a `possession` column (the join key with `game_id`).
- Next (Claude): multi-season RAPM and the season simulator for v0.1.

## Known limits

- 0.090% of possession ends repeat the same team twice in a row. This is usually a lone free throw after which the fouled team keeps the ball.
- Lineup and historical-name rules are verified for 2016-17 onward. A pre-2016 backfill may expose additional legacy feed spellings or ordering quirks.
