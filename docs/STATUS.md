# Status

Updated 2026-10-09. v0.1 (data pipeline, RAPM, season simulator, pre-registered 2026-27 predictions) is due before opening night, around Oct 20.

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
- Fix (Oct 4): players no longer jump at the end of a possession. The free-throw line-up, the rebounder going up for the ball and a substitute walking on are part of the animation, each possession starts exactly where the last one ended, and anything left glides instead of teleporting.
- Seventh follow-up (Oct 4): no cross-court zooms on short possessions (game mode: first chances of at least 4 seconds; runs paced by distance), players fill the lanes, playback is 0.5× only with sound always on, and "Man to man" ends a double team. Details are in GAME_DESIGN.md §9.
- Eighth follow-up (Oct 4): the press drops back smoothly (it was the remaining teleport), and in the live game a shot goes in at its chance times the shooter's energy (100% fresh, ~85% at a normal sub, 80% empty).
- Ninth follow-up (Oct 4): the live game stops after every possession for your calls (they apply to the very next play), the tactics panel's pick-and-roll / pop / five-out / isolation are acted out on the court, and the spacing is wider.
- Tenth follow-up (Oct 5): no timeouts for the coach; the tactic (a set play or a defensive scheme) is a list in the All team row, each player has a role list (handler, screener, post, chaser, ...), a helper draws the tactic, and substitutions are picked from a player's name.
- Eleventh follow-up (Oct 5): every player always has a role (spots, matchups like "On Bryant", zone spots), and the live game's default matchup is the 1990s All-Stars against the 2000s All-Stars (`hoopformer fetch --legends`, then `hoopformer serve`). Their rates come from career season totals with era averages; a shot-chart refinement is open for Codex (see below).
- Twelfth follow-up (Oct 5): the break lights up the talk panel instead of a pop-up, call lists leave out anything the tactic already decides, and playback is 0.8x.
- Thirteenth follow-up (Oct 5): the court acts out the tactic shown in the talk panel at once (the engine follows from the next possession); the 2-3 zone and the box-and-one stand on their spots, slide with the ball and are outlined on the floor; no more sprints across the floor at possession starts.
- Fourteenth follow-up (Oct 6): at the break the players walk into the next possession's tactic and it starts from there; the court draws every tactic as the helper does (the helper is drawn from the court's own formation); drop coverage, blitz, isolation and motion look like themselves; a 🗯 trash-talk button rattles or fires up his man (confidence ±0.05); the language choice is gone.
- Fifteenth follow-up (Oct 6): the Play button is now the timeout (whistle; 15 a game, each a real breather in the engine, never spent by the scripted coach); the stop after every possession is gone.
- Sixteenth follow-up (Oct 6): tactics and roles change only in a timeout; a change continues the possession from that moment (nobody moves during the timeout, your five run into it after, the other team only reacts) instead of redrawing it from its start.
- Seventeenth follow-up (Oct 6): no teleports at possession ends (free throws walked to, the ball carried from where it was, the next possession drawn only once it starts; one 4 ft ball flick left in a whole game, checked frame by frame); live second chances last at least 1.5 s; every player always has a role, and your own picks take their roles back after a substitution.
- Eighteenth follow-up (Oct 6): player archetypes from each player's own numbers (Jordan a two-way scoring dominator, Klay a 3-and-D wing: tested), and every player moves by his; five scripted set plays (Elevator, Horns, Spain pick-and-roll, Floppy, Hammer) and two defenses (1-3-1, triangle-and-two), played exactly as the helper draws them.
- Nineteenth follow-up (Oct 6): a production page (the default; debug with --debug or ?debug=1); the project now has two clients in clients/ (the web page and a WeChat Mini Program, compact in portrait and landscape) sharing the engine on the server and the court's rules in clients/core/court.js.
- v0.1 moves to Oct 6-17, still locked before opening night.

## Next

- WeChat phone bug fixes (ChatGPT, 2026-10-09): reproduced the Android screenshot through an actual DevTools picker event: `rows` changed from a five-element array to `{"0":{"callIndex":0}}` because the numeric-dot setData path was invalid. Picker updates now preserve the full array and bind stable player ids. Added ordered API requests, busy states, structured Chinese HTTP errors, rollback of failed tactics/role changes, an explicit new-game recovery button and animation-frame cleanup. Fixed partial-word translation (Wing inside Ewing) and localized classic-player names and offense/defense strips. Added original PCM dribble, swish, rim and buzzer assets alongside the existing whistle, held-ball bounce timing, event cues, media-volume playback and a mute button. Actual DevTools audio onPlay callbacks confirmed dribble and whistle with no audio errors; this does not establish the phone speaker volume. Backend/web/phone now use independent game ids; the single process retains up to 32 games for two idle hours and returns GAME_EXPIRED rather than another player's state. Single-instance hosting remains required; process restarts lose games. Twenty-seven real-data/client/HTTP checks passed in 10.52 s, including a full 199-request game, independent clients, malformed HTTP bodies, 1,495 coached strips and real PCM levels. `tests/wechat_live.cjs` passed actual picker/textarea/button flows: repeated calls to five players, all 13 offense tactics and all nine defenses across runs, role swaps, pause/resume, mute toggle, and actual session eviction with tactic/role rollback and successful restart. Private project config and API keys are not packaged; microphone transcription remains a phone test. Deployment-branch regression checks also passed (27 in 11.05 s; three isolated torch-free Docker-source checks in 2.19 s). Backend deployment and replacement preview are pending this fix's publication.

- Cloud image/runtime repair (ChatGPT, 2026-10-09): user reports failed deployment and supplied `flask-y3ue-004` build logs. The logs prove successful Linux package installation and image export, but the image is 9.6GB because the original Dockerfile installed PyTorch/CUDA/NVIDIA research dependencies. They stop during TCR push and contain no final failure message, so image size is not claimed as the proven direct failure cause. Added `deploy/tencent/pyproject.toml` for the current cached-rates server; Docker now installs that profile while the root research dependencies remain unchanged. Clean installation via the same Tencent package mirror yields 18 compatible distributions, no torch, and a 297 MiB Mac runtime environment (not a Linux image size measurement). Also reproduced an actual installed-console startup failure: webpage lookup points into site-packages and raises FileNotFoundError. Added Docker `PYTHONPATH=/app/src` to resolve copied source/assets correctly. Previous deployment tests supplied their own source path; they now read the image's ENV settings and invoke the installed `hoopformer` executable. Three checks passed in 1.60 s using the clean torch-free environment: profile/real model hashes, actual console startup, Chinese pace +0.35, 199 possession requests / 704 events ending 69-95 and the assembled web court. Linux rebuild size, cloud version startup and successful WeChat game calls remain pending. Requested final failure lines separately.

- GitHub cloud deployment profile (ChatGPT, 2026-10-08): branch `codex/wechat-cloud-deployment` is based on current `origin/main` (`facd5b5`) and adds a root Dockerfile, Docker context exclusions, a deployment guide, and two frozen derived models under `deploy/tencent/models/` with SHA-256 provenance. Why: pulling game code alone cannot build the cloud service when Docker configuration is local and runtime models are ignored in `data/`. The committed models are the previously verified 2025-26 + classic-player bundle (606 players, 32 teams, 2,077,038 bytes); no raw NBA responses or credentials are included. Two real-data/deployment tests passed in 1.42 s: hashes/classic players, the Docker COPY inputs isolated from all local raw data, actual CLI startup, Chinese pace +0.35, 204 possession responses / 667 events through a final 129-91, and the assembled web court. Cloud settings: existing environment `prod-d2gq2p7vs296b0a1e`, service `flask-y3ue`, GitHub repository `marinelj/hoopformer`, this deployment branch, root `Dockerfile`, port 8000. No game-engine changes. Local source/data HTTP checks pass; Linux image build, actual cloud deployment and voice transcription remain unverified.

1. RAPM over several seasons (later seasons weigh more).
2. The 2026-27 schedule from nba_api (current rosters: done, `fetch --rosters`).
3. The season simulator: team strength = player ratings × expected minutes; simulate the schedule thousands of times.
4. Backtest the method on 2025-26, then pre-register the 2026-27 win totals and playoff odds: push them, and post their SHA-256 on X before opening night.

## v0.2 (the transformer, due at the NBA Cup, Nov-Dec)

- marinelj writes the model and training loop, following `docs/TRANSFORMER_GUIDE.md`.
- Done: `hoopformer dataset` (`src/hoopformer/dataset.py`) writes `data/derived/possessions.parquet`, one row per possession with the split column. On 664 games of 2025-26: 134,426 rows, outcome shares 0:49.04% 1:3.24% 2:32.33% 3:15.15% 4+:0.24%.
- Done: `notebooks/G2_coaching.ipynb` (game days 2-3: stepping a game, fatigue, calibrating against real rotations, lever limits, common random numbers, the LLM translator and its validator, overfitting with held-out phrases; 8 exercises, verified end to end). `notebooks/G1_game_engine.ipynb` (a guided tour of the game engine with 5 exercises: counting a game, shrinkage, fitting, one chance, a same-seed experiment; verified end to end). `notebooks/M1_M2.ipynb` (guided cells for marinelj, each with a check cell; verified end to end against a private reference solution) and `notebooks/playground.ipynb`. The Jupyter kernel is registered with `uv run python -m ipykernel install --user --name hoopformer --display-name "Hoopformer (.venv)"`.
- Done: `notebooks/B0_B2_baselines.ipynb`, the three baselines by hand: log-loss and why not accuracy, B0's shares (their training log-loss is the entropy), softmax, the softmax gradient checked by finite differences, gradient descent that reaches sklearn's B1, the sparse lineup matrix, choosing C on validation, overfitting as train vs validation gains over B0, players in points per 100, and standard errors on the scoreboard. 6 exercises, verified end to end against a private reference solution; each check stops with a clear message until its exercise is written.
- Done: the grader, `hoopformer baselines` and `hoopformer evaluate` (`src/hoopformer/evaluate.py`): B0 shares, B1 situation, B2 linear lineup with its strength picked on validation; the test split is locked behind `--final` and logged. The dataset gained a `possession` column (the join key with `game_id`).
- Next (Claude): multi-season RAPM and the season simulator for v0.1.

## Known limits

- The baseline cache (`data/derived/baselines_<split>_<hash>.parquet`) is keyed on the dataset only, so a code or library change can leave it stale: on the MacBook the cached B2 reads 1.10106 where a refit with today's code gives 1.10090 (B0 and B1 match). Delete the file to refit.
- 0.090% of possession ends repeat the same team twice in a row. This is usually a lone free throw after which the fouled team keeps the ball.
- Lineup and historical-name rules are verified for 2016-17 onward. A pre-2016 backfill may expose additional legacy feed spellings or ordering quirks.
