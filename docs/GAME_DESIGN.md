# Hoopformer Game: coach an AI team in plain language

Status: in progress. Written 2026-09-30 from marinelj's idea and Claude's review; decisions below made 2026-10-01.

**Decisions (marinelj, 2026-10-01)**
- **The game is the centre of the NBA lab.** The Studio / Belief Lab idea becomes its analysis mode.
- **Real players.** Fine for a private prototype. Player names and identities live in a separate layer, so switching to a fictional league before a public release or a sponsor deal is a configuration change (see §8).
- **v0.1 (season simulator, before opening night) and v0.2 (marinelj's transformer) stay on schedule.**
- **The build:** 5 days, Oct 1-5 (§9). Claude builds it on the MacBook Air in `src/hoopformer/game/`; other teammates don't edit that folder while it's being built.
- **Movement learned from game footage: not now.** NBA footage is copyrighted, extracting tracking from broadcast video is a research project of its own, and a coaching game lives on decisions. The game simulates decisions learned from play-by-play, and a 2D court animates them.

## 1. The idea

marinelj's idea, condensed:
- A simulated game has ten athletes, each an independent agent with its own memory of instructions, strategies and past actions.
- Two human players each coach one team. They intervene only in natural language, typed and later spoken, the way Gregg Popovich would: timeouts, substitutions, sideline instructions.
- Each athlete interprets instructions through an LLM, stores them in memory, and plays accordingly.

## 2. Architecture (proposed)

```
coach speaks or types
   │  (speech-to-text for voice)
   ▼
translator (LLM, structured output) ──▶ tactic, in the lever schema (§5)
   │
   ▼
validator: clamp to realistic ranges measured from real NBA data
   │
   ▼
athlete and team memory (§4)
   │
   ▼
game engine: one loop, possession by possession (§3)
   │  uses Hoopformer's possession model for the odds
   ▼
events ──▶ play-by-play text, athlete replies ("Got it, coach"), box score
```

| Component | Job | Built from |
|---|---|---|
| Game engine | Runs the game possession by possession; a seed makes every game replayable | New |
| Possession model | The odds of each outcome given the ten players, the situation and the tactics | Hoopformer v0.2 (marinelj's transformer); B2 until then |
| Athlete agents | Hold memory, react to instructions, reply in plain language | New |
| Translator | Turns free language into levers | LLM with structured output |
| AI opponent coach | Timeouts, substitutions, tactics | Scripted first, then reinforcement learning (§6) |
| Narrator | Play-by-play text, later voice | LLM, or templates |
| UI | Court view, play-by-play, coach input | Web |

## 3. Game engine: one loop, possession by possession

- **State:** score, clock, period, possession, both lineups, fouls, timeouts, each athlete's fatigue.
- **Each possession:**
  1. who initiates (a usage model)
  2. a short chain of actions (pass, drive, post-up)
  3. the outcome (shot and make/miss, turnover, foul and free throws)
  4. the rebound

  The odds come from the possession model, conditioned on the lineup, the situation and the active tactics. The clock runs down according to pace.
- **One thread, one loop, one seed.** The same seed replays the same game. That makes the engine testable, and "watch my game" becomes shareable.
- **Data we have for this:** play-by-play gives initiators, shot types, shooters, assists, turnovers, fouls and rebounds for 2.4 million possessions. It gives no player movement, so the simulation stays at the level of decisions, not dribbles.

## 4. Athlete and team memory

Per athlete:

| Field | Example | Changes when |
|---|---|---|
| identity | archetype vector ("passing center") | never, within a game |
| fatigue | 0-1 | minutes played, rest on the bench |
| fouls | 3 | fouls committed |
| confidence | 0-1 | makes, misses, the coach's words |
| directives | list of {lever, value, from, time, expires, original words} | coach instructions, timeouts |
| recent actions | the last 10 events | every possession |

Per team: active tactics, and conditional rules ("if they go small, switch to zone").

## 5. The translator: free language in, levers out

The human only ever uses free language. The levers are what the engine can execute; they're never shown to the player.

| Level | Levers (v1) |
|---|---|
| Team offense | pace; shot mix (3s / rim / midrange); who gets the ball; pick-and-roll frequency |
| Team defense | scheme (man / zone / switch everything); double-team target; who guards whom; full-court press; late-game fouling |
| Each player | aggression (share of shots); shot preference; defensive assignment; foul caution; rest |
| Morale | confidence |
| Conditions | if [game situation] then [lever change] |
| Direct commands | timeout; substitution |

- Values like "more" and "less" become bounded changes. Each bound is measured from real NBA data (e.g. a team's share of shots that are threes), and every change carries realistic side effects.
- The original words are kept with every directive, so athletes can quote them back.
- Anything that doesn't map goes to `unmapped` and is logged. The most frequent unmapped phrases decide which lever gets built next.
- Impossible requests ("make every shot") get a realistic reply and the closest real lever (better shot selection).

## 6. AI opponent coach (reinforcement learning, later)

- **Actions:** timeouts, substitutions, tactic presets. Only a few choices at each step, which makes it tractable.
- **State:** score, time, fouls, fatigue, lineup strength.
- **Reward:** winning.
- **Training:** by playing itself thousands of times inside the engine, on the Mac Studio.
- **Later:** publish results for AI coach vs. human coaches.

## 7. Realism checks (graded like everything else)

A simulated league must land inside real NBA ranges on:
- pace, shooting percentages, three-point share, free-throw rate, turnover rate, rebound rates
- home win percentage

Levers must move stats by plausible amounts. Every check becomes a test, run on real data.

## 8. Players: real players for now, fictional league as a switch

Decision: real players, for a private prototype. The risk to remember: analysing real players by name and stats is protected (*C.B.C. v. MLB Advanced Media*), but using real athletes as game characters is not (*Keller v. Electronic Arts*, 2013), and NBA 2K licenses them from the players' union. So names and identities live in a separate layer. Before any public release or sponsor deal, revisit this; the alternative is fictional athletes whose styles come from real players' Hoopformer vectors ("a Jokić-like passing center").

## 9. Staging

**The 5-day build (Oct 1-5).** Claude builds it; marinelj plays and reviews.

| Day | Build | Done when |
|---|---|---|
| 1 (Oct 1) | Engine core: each player's action rates learned from 2025-26 play-by-play, and a seeded possession loop | Counted stats match the official box scores; a simulated league lands in real NBA ranges (tests) |
| 2 | Real rosters, rotations, fatigue, a scripted AI coach | AI vs. AI games produce believable box scores and minutes |
| 3 | Coach language: lever schema, LLM translator, limits, athlete memory, replies | 50 test phrases map to the right levers |
| 4 | Web UI: 2D court with moving dots, play-by-play, box score, coach input box, voice through the browser's speech recognition | marinelj coaches a full game by typing or speaking |
| 5 | Polish and the fun test: friends play; a demo video | someone asks for a second game |

**After the build:**
- Oct 6-17: v0.1 (season simulator), predictions locked before opening night.
- Nov-Dec: v0.2 (marinelj's transformer), which can replace the day-1 action model as the game's engine.
- Then: richer athlete memory, the reinforcement-learning AI coach, two humans in real time.

**Day 1 result (engine core, done):**
- `game/actions.py` counts every player's chances and actions from play-by-play. Over 400 games it reproduces the official box scores: FGA, FGM, 3PA, FTA, FTM, AST, TOV, OREB, DREB and STL exactly, PF 99.95%, BLK 99.5%.
- `game/model.py` turns the counts into rates with shrinkage toward the league, plus team defense factors and home court. It fits in about 6 seconds.
- `game/engine.py` plays a seeded game in about 2 ms; the same seed replays the same game.
- `game/realism.py`: 1,000 simulated games match the real 2025-26 season on all 16 statistics checked:
  - points 116.1 vs 115.3, possessions 101.6 vs 101.0
  - FG% 47.3 vs 46.9
  - home win share 51.9% vs 54.2%
- Replaying the real season's matchups, simulated team point differentials correlate 0.86 with real ones. They're about 24% compressed: defense is still per team, and rosters are end-of-season.
- Commands: `uv run hoopformer actions --season 2025-26` fits, saves and checks realism; `uv run hoopformer play --home OKC --away HOU --seed 7 [--play-by-play]` plays one game.

**Day 2 result (rotations, fatigue, the scripted coach, home court, 2026-27 rosters; done):**
- **The engine moves one possession at a time.** `Game.step()` plays one possession, then lets both coaches act, and returns the new events; `play()` just loops it. A live app (day 4) will stop between steps for the human coach. `Game.substitute()` and `Game.call_timeout()` are the actions a human coach will use.
- **What real games told us (2025-26, measured from the rebuilt lineups and play-by-play):**

  | Measured | Real |
  |---|---|
  | Substitutions per team per game (not counting period starts) | 26.1 |
  | Timeouts per team per game | 5.4 (2.2 / 2.3 / 2.4 / 3.8 per game in Q1-Q4) |
  | Average stint, players over 33 / 28-33 / 20-28 / under 20 minutes a game | 9.0 / 7.7 / 6.6 / 5.4 minutes |
  | Average rest between stints, same groups | 3.9 / 4.6 / 5.9 / 8.0 minutes |
  | Shooting by time since checking in (made / expected) | 0-3 min 0.984, 3-6 0.998, 6-9 1.000, 9-12 1.010, 12+ 0.992 |
  | Opponent's run when a timeout is called | 3.7 points on average; only 10% after 8-0 or more |
  | Home minus away, per game | +1.7 points: +0.6 FG% points, +0.6 free throws attempted, -0.2 turnovers |

- **Fatigue changes who plays, not how well they shoot.** Real shooting doesn't drop late in a stint (the table above: the data shows no fatigue penalty within the stints coaches actually allow). So energy only drives rotations: it runs down on the floor in `2.5 + 0.17 × minutes per game` minutes (6 to 10, the real stint lengths) and back up on the bench in about 4 minutes; quarter breaks, halftime and timeouts rest players too.
- **The scripted coach** (`game/coach.py`), for both teams:
  - substitutions: fouled-out players leave at once; foul trouble sits (2 fouls in Q1, 3 in Q2, 4 in Q3, 5 before the last 5 minutes); tired players rest; rested players come back, whoever is furthest behind their minutes first; the best five close games (last 5 minutes within 10, and overtime); the end of the bench plays garbage time (last 5 minutes, 20+ apart);
  - timeouts: a breather at the first stop under 7:00 and 3:00 of each quarter (like TV timeouts; the trailing team takes it), one to stop a 10-0 run, and one to draw up a play when down 1-6 in the last 2 minutes after the other team scores; two are kept for the 4th quarter.
- **Simulated vs real rotations** (600 games, `test_rotations_look_like_real_games`): substitutions 28.3 vs 26.1 per team-game; timeouts 5.1 vs 5.4; stints 9.7 / 7.4 / 5.9 / 4.2 vs 9.0 / 7.7 / 6.6 / 5.4 minutes; each player's minutes land within 1.1 minutes of the coach's target on average (stars 0.7 short).
- **Home court is spread out:** home teams shoot better (FG% × 1.007, away × 0.993), draw more free throws (× 1.012 / 0.988) and turn it over less (× 0.995 / 1.005), each measured directly. Over 6,000 games: home margin +1.2, home win share 53% (real +1.7 and 55.5%).
- **Known gap:** simulated games are more spread out than real ones (margin SD 18 vs 16.4; 27% of games decided by 20+ vs 23%). It was already there on day 1, and earlier garbage time doesn't fix it. Real teams ease off with a lead and push when behind ("score effects"); the engine doesn't model that yet. This also holds home win share below the real one.
- **2026-27 rosters:** `uv run hoopformer fetch --rosters --season 2026-27` caches all 30 training-camp rosters (619 players; 480 have 2025-26 rates). `game/rosters.py` moves every player to their current team with last season's rates; newcomers start as league-average 10-minute players. Play with them: `uv run hoopformer play --home OKC --away BOS --rosters 2026-27`.
- A game now takes about 4 ms (the coach checks both benches after every possession).
- The realism check uses 2,000 games: with 1,000, home win share alone moves by ±1.6 points from seed to seed.

**Day 3 result (coach language: levers, limits, translator, memory; done):**
- **Levers** (`game/levers.py`), each a value from -1 to 1:

  | Scope | Levers |
  |---|---|
  | Team offense | pace, three_point_rate, attack_rim, ball_security, crash_glass, focus (one player) |
  | Team defense | pressure, protect_paint, foul_caution, double_team (one opponent), late_foul |
  | One player | aggression, shot_preference (rim / mid / three), foul_caution, rest |
  | Commands | timeout, substitutions |
  | Memory only | confidence (changes how players talk, not how they play: no data shows an effect) |

- **Limits from real data.** +1 moves a team as far from the league average as the most extreme real 2025-26 team went (from box scores), and a player as far as their own games swing (10th-90th percentile). Measured: pace 0.96-1.04 (real teams barely differ), three-point rate 0.82-1.20, getting to the line 0.79-1.21, turnovers 0.87-1.17, offensive rebounds 0.81-1.34, turnovers forced 0.82-1.16, threes allowed 0.91-1.09, fouls 0.90-1.11, a player's usage 0.68-1.33, a player's three-point share 0.53-1.49.
- **Each lever, measured with common random numbers** (300 OKC-BOS games with and without it): threes +1 raises the 3PA share from 37.5% to 41.1%; ball security +1 cuts turnovers 11%; crash the glass +1 adds 30% offensive rebounds; pressure +1 forces 14% more turnovers; foul caution +1 cuts fouls 7%; "be aggressive" +1 gives SGA 18% more shots. All stay inside the real limits (`test_each_team_lever_moves_its_stat_within_real_limits`).
- **No free wins.** Without side effects, crashing the glass was worth +3.7 points a game for nothing. Now crashing concedes better fast breaks, pressing concedes layups and fouls, and protecting the ball means attacking the rim less. These sizes are assumptions (named constants in levers.py) until the transformer can measure them.
- **Memory.** `Game.instruct` stores each lever as a directive with the coach's own words, when it started and when it lapses (the rest of the game, the quarter, or N possessions). `Game.memory(side, player)` gives an athlete's energy, fouls, confidence, directives and last 10 actions. A coach's substitution sticks for 4 minutes before the assistant may undo it; "rest" keeps a player on the bench until it lapses.
- **Translators** (`game/translator.py`), same output format:
  - Qwen (`qwen3.8-max`, the Qianwen AI platform's OpenAI-compatible API with JSON output, thinking off), one call per instruction, about 1,600 tokens each. Key: a pay-as-you-go key (`sk-...`) as `DASHSCOPE_API_KEY` in the shell profile or a git-ignored `.env`. Token Plan keys (`sk-sp-...`) are for interactive coding tools only and the code refuses them.
  - OpenAI (`gpt-6-astra`, its most capable model, reasoning effort low; about $0.03 an instruction at $10/$50 per million tokens), same API shape. Key: `OPENAI_API_KEY`. `--use openai`, or `auto` picks the first provider with a key set.
  - Keyword rules: no network; the baseline and the fallback when the API is down.
  - Both go through `levers.validate`: values clamped, players checked against the rosters, anything else into `unmapped`, which is logged to `data/derived/unmapped.jsonl`. The most frequent unmapped phrases decide the next lever (today: box out, switch everything, move the ball).
- **50 test phrases + 30 held out** (`game/coach_phrases*.json`). The rules score 50/50 on the phrases they were written against and 5/30 on the held-out ones. That's overfitting, the same lesson as the train/validation split: a score on data you tuned to means nothing. Qwen (`qwen3.8-max`, 2026-10-02), about 3 seconds and 1,600 tokens an instruction:

    | Phrase set | Rules | Qwen, first prompt | Qwen, fixed prompt |
    |---|---|---|---|
    | 50 test phrases (the rules were written against them) | 50/50 | 47/50 | 50/50 |
    | 30 held out (their misses shaped the fixed prompt) | 5/30 | 28/30 | 30/30 |
    | 20 held out, written before the fix: **the honest score** | 5/20 | not run | **19/20** |

    The first prompt's misses were one pattern: told something by one player's talk row ("stop forcing it"), Qwen changed the whole team instead of that player. The fix states the rule (one player's own game goes on that player) and what rim, mid and three mean. Once a set's misses have shaped the prompt, its score stops being an honest measure, so a fresh set was written before testing the fix. Re-run: `uv run pytest -m network -k llm` or `uv run hoopformer coach --check --use qwen`.
- Commands:
  - `uv run hoopformer coach "Push the pace and run their shooters off the line" [--to "Shai Gilgeous-Alexander"] [--use rules|qwen]` prints the levers and the reply.
  - `uv run hoopformer play --home OKC --away BOS --say "Q2 6:00 Pack the paint" --say "Q4 3:00 Shai Gilgeous-Alexander: take over" --replay page.html` coaches a simulated game; the replay shows each instruction and the reply in the chatter.

**Day 4 result (the live app; done):**
- **Play:** `uv run hoopformer serve`, then open http://127.0.0.1:8000/ in Chrome or Safari. Options: `--home OKC --away BOS`, `--port`, `--use qwen|openai|rules`. "New game" on the page starts another (`/?home=..&away=..&seed=..`).
- **How it works** (`game/server.py`, standard library only, reachable from this Mac only):
  - The server holds the engine. The page asks for the next possession (`GET /api/next`) only when it has shown the last one, so the game is never more than one possession ahead of what you see. Whatever you say applies from the next possession.
  - Your words go to the server (`POST /api/say`), which calls the translator; **the API key never reaches the browser.** The page shows your line at once, then the player's reply and the levers it set ("→ Shai Gilgeous-Alexander aggression +0.8, shot_preference rim +0.8 · qwen3.8-max"). The game keeps playing during the model's ~3 seconds.
  - **Timeout** (`POST /api/timeout`) is an engine timeout (it rests your players and counts against your 7). **The tactics panel** (`POST /api/tactics`) needs no language model: each choice is already a lever, and a new plan replaces the old one.

    | Panel choice | Levers |
    |---|---|
    | Pick-and-roll / pick-and-pop / post-up | attack_rim +0.4 / three_point_rate +0.3 / attack_rim +0.5, pace -0.3 |
    | Five-out / push / slow down | three_point_rate +0.6 / pace +0.6 / pace -0.6 |
    | Drop / blitz / 2-3 zone / press / box-and-one | protect_paint +0.4 / pressure +0.5 / protect_paint +0.7 / pressure +0.8 / protect_paint +0.5 |
    | Run it through X / double-team X / foul late | focus X / double_team X / late_foul |
    | Motion offense, switch everything | no lever yet: logged as unmapped |

  - **Voice:** hold 🎙, speak, release: the browser's own speech recognition shows the words over the row's list as you speak and sends them to the language model on release. The voice is English (the language choice was removed in the fourteenth follow-up). Chrome sends the audio to Google's speech service; Safari uses Apple's (Siri must be on). The browser asks for the microphone once; a press made while that prompt is open is finished when you answer it. Every failure (nothing heard, released too soon, microphone blocked, no connection to the speech service) shows up as a 🎙 note in the chatter.
  - **Double teams on the court:** each possession records the player the defense is doubling (`Event.other` on the chance), and the defender whose man stands nearest leaves to help, so two figures stand on the doubled player, whose tag shows ×2.
- **Measured:** a whole game streams in about 200 possession requests in 1.2 seconds on this Mac, so the engine never makes the page wait. Tests run a real server on a free port (`tests/test_server.py`).
- **Not yet:** two human coaches; an AI coach that talks; voice tested by marinelj (the browser pane Claude uses can't grant a microphone).

**Day 4 follow-up (Oct 4): instructions you can see.** marinelj found that instructions rarely showed on the court: the engine applied them, but the figures' movement ignored them, and a lever's effect is a probability (SGA +0.8 aggression takes him from about 30% to 35% of chances, which one possession can't show). Three changes:
- **Every chance records the calls in force** (`Event.tactics`: the offense's levers, focus and player levers; the defense's levers and double team). Uncoached games carry none and are unchanged.
- **The figures act the calls out on every possession**, while the outcome stays the engine's: a 2-3 zone around the paint, a full-court pickup with two on the ball, all five crashing the rim on a miss (or getting back), a sprint or a walk-up, the told player driving at the rim and getting more of the passes, wide spacing for "more threes". A play-call strip above the court names the calls, the called player's tag is outlined, and a player shouts a new call once when it takes effect ("Two-three! Zone, zone!").
- **An engine monitor** (live page, `Game.monitor`) shows the next chance's odds at both ends with and without the directives, each player's share of chances with energy and confidence, and every directive with the coach's words and the game time it has left.

**Second follow-up (Oct 4): calls from a list, real time only.**
- **Each talk row is a list of calls** instead of a text box. The list follows the ball: offensive calls while we have it, defensive calls while they do, plus a few any-time calls, and it changes with the lineup ("Run it through X" for each of ours on the floor, "Double-team X" for each of theirs). A suggested call is preselected every 15-30 seconds, never one that would undo a call in force or one already at its limit.
- **A picked call needs no language model.** It is already levers (the same JSON Qwen writes), so the page posts it to `POST /api/call` and the engine applies it from the next possession. Each call names a direction (+ or −) on these levers:

  | Row | On offense | On defense | Any time |
  |---|---|---|---|
  | All team | pace ±, three_point_rate +, attack_rim +, ball_security +, crash_glass ±, focus X | pressure ±, protect_paint ±, foul_caution ±, double_team X, late_foul | timeout, team confidence +0.5 |
  | One player | aggression ±, shot_preference rim / mid / three +, focus on him | foul_caution ± | rest 3 minutes, confidence +0.5 |

- **Picking a call sends it**: there is no send button. The closed list shows the suggestion (💡, also marked inside the list) and, for a moment after a pick, "Sent: ...".
- **Calls are nudges, not switches** (`Game.nudge`), because a real coach repeats himself and changes his mind:
  - **Each call moves its lever one step** (`STEP` = 0.35) from where it stands. The same call again pushes further (0.35, 0.7, then the limit 1.0); the opposite call ("Slow it down" after "Push the pace") takes a step back, and a lever back at 0 is forgotten. A player's new shot zone replaces his old one.
  - **A new call fades the others of the same kind** (`FADE` = 0.7): the team's offense, the team's defense, or one player's offense or defense each compete for attention. "Let it fly from three" after two "Attack the rim" calls leaves attack_rim at 0.49 and three_point_rate at 0.35. A call that fades below 0.05 is forgotten (about six newer calls of its kind). To keep a call strong, repeat it.
  - **Each option shows where its lever stands**: ●○○, ●●○ or ●●● steps in that call's direction (● for focus, double team and foul-late). There is no take-back option: the opposite call or newer calls do that, as on a real bench.
  - Words said through 🎙 and the tactics panel still set a level directly (the language model reads "a lot more" as a bigger number); only list calls step.
- **Hold 🎙 still says anything**: the words go to the language model as before. Picking "Timeout!" from the list is the same as the timeout button.
- **Playback is real time only** (1×): the speed buttons are gone, since a live game can't run ahead of the server anyway and the calls need time to read.
- **The server keeps the page it started with** (`replay.PAGE`, read once). Before, it read the page from disk on every request, so after a `git pull` an old server sent the new page without the routes the page needs ("Couldn't apply that (not found)"). Now page and server always match, and a page that meets an older server says to restart it.
- **Language model failures say why.** When Qwen can't be reached the page now shows the error's message (for example an SSL handshake failure), the server prints it, and a dropped connection is retried once before falling back to the keyword rules.

**Third follow-up (Oct 4): every call has a price; energy and confidence are shared resources.**
- **Energy** (`levers.EFFORT`, `Game.effort`): each call changes how fast the players it covers tire on the floor. At +1 / -1:

  | Lever | +1 | -1 |
  |---|---|---|
  | pressure | +40% | -10% |
  | pace | +20% | -10% |
  | aggression (one player; focus counts as aggression) | +20% | -5% |
  | crash_glass | +15% | +5% |
  | attack_rim | +10% | 0 |
  | box_out (one player) | +10% | +10% (leaking out is running too) |
  | protect_paint | -10% (a zone saves legs) | +10% |
  | foul_caution | -5% | +10% |
  | a double team in force | +10% for the five | |

  These are assumed: no public data measures effort. The price is paid in minutes, not in shooting, because real shooting doesn't drop late in a stint (§9 Day 2): tired players go to the bench sooner. Pressing all game costs Shai Gilgeous-Alexander about 1.5 of his 33 minutes (`test_every_call_has_an_energy_price_paid_in_minutes`). The live page shows each call's price ("energy use x1.00 → x1.14") and each player's rate ("tiring x1.42") in the monitor.
- **Confidence**, measured (`actions.hot_hand`, all 1,230 games of 2025-26): after making his last two shots a player takes **6.0% more** of his team's shots, and makes **1.2% fewer** of them than his usual rate in that zone (hot players take harder shots, as Bocskocsky, Ezekowitz and Stein found in 2014); after two misses, **5.4% fewer** shots and **0.7% more** makes. The engine copies this in every game, coached or not:
  - Confidence (0 to 1, 0.5 normal) remembers a player's last few shots, the latest most: each shot keeps half his lead over 0.5 and adds or takes 0.1, so two makes give 0.65 and two misses 0.35.
  - His share of chances is x(1 + 0.4 × (confidence − 0.5)) and his make rate x(1 − 0.08 × (confidence − 0.5)): x1.06 and x0.988 after two makes, matching the measurement (`test_the_hot_hand_in_real_games_and_the_engines_confidence_match`).
  - A turnover takes 0.05, a steal or a block gives 0.05 (assumed), and praise gives 0.15 × its strength. So praise has a price too: the player shoots more, slightly worse.
- **More calls for one player on defense** (8, was 2): pressure your man / play off him, protect the rim / stay home on your shooter, box out / leak out for the break, stay out of foul trouble / be physical.
  - **A player's defensive call counts for a fifth of the team's** (`levers.ONE_OF_FIVE`): five players told to pressure equal one team press. On top of that, the steals (for pressure) or the blocks (for protect the rim) shift to him, up to 50% more (assumed).
  - **Box out** raises his defensive-rebounding weight as much as a crashing team raises its offensive one; **leak out** lowers it but starts a fast break (`LEAK_OUT`) after every defensive rebound.
  - The translator's prompt knows these levers too (Qwen: 50/50, 29/30, 18/20 after the change, against 50/50, 30/30, 19/20 before; the three misses were rest and shot-zone phrases, not the new levers).
- **"Get physical" now has a benefit:** the rim contest (`CAUTION_CONTEST`) works both ways, so physical defense makes finishes 2% harder while it fouls more.

**Fourth follow-up (Oct 4): a monitor for each player, a list that follows the ball while open, and 0.5×.**
- **The bench panels are gone.** In their place, under the court, a card for each of your five on the floor (`Game.monitor` → `players`), refreshed every possession and after every call:
  - points, fouls and minutes; energy, how fast he's tiring under your calls, and his confidence with what it does to his shooting;
  - the calls to him, with how far each stands (●○○ to ●●●);
  - **offense:** his share of your chances, and how his own chances end (rim, midrange, three, to the line, turnover), without and with your calls;
  - **defense:** his share of the team's steals, blocks, defensive rebounds and fouls, without and with your calls. A call to one player moves his teammates' shares too ("Pressure your man" raises his steals share and lowers theirs).
  - The team monitor keeps the team's outcomes and the list of calls in force.
- **The call list is the page's own** instead of the browser's `<select>`, because the browser's drop-down can't change while it's open. Now an open list switches between offense and defense when the ball changes hands (its heading flashes), and the rows check the ball every 0.25 seconds. Arrow keys, Enter and Escape work.
- **0.5×** next to Play halves the speed, for time to think about the next call. Real time stays the default.

**Fifth follow-up (Oct 4): game mode. Calls you can feel.** marinelj: "this is a game, not a simulation for rigorous analysis. I want my decisions to feel impactful."
- **The live app plays boosted** (`levers.BOOST` = 5, `Game(boost=...)`, `hoopformer serve --boost 1` for the faithful version). Every coached effect reaches 5 times further from "no change":
  - the lever limits (`levers.boosted`);
  - the side effects, so each call keeps its price;
  - how much confidence changes who shoots (how well a confident player shoots stays as measured);
  - the energy costs, at half that (x3).
  - Simulations, tests and the realism checks still use boost 1, measured from real games.

  Over 100–150 games, OKC vs BOS:

  | Calls (each one step) | Faithful (boost 1) | Game (boost 5) |
  |---|---|---|
  | crash the glass ×3: OKC offensive rebounds | 9.8 → 12.6 | 10.0 → 21.3 |
  | press ×3: BOS turnovers | | 13.8 → 22.9 |
  | SGA aggressive ×3: his shots | | 17.7 → 27.5 |
  | attack the rim ×3: point margin | | +4.3 → +14.6 |
  | push the pace ×3: point margin | | +4.3 → +1.5 (the team tires) |
- **Energy (game mode only), marinelj's rule: a shot goes in at its usual chance times the shooter's energy.**
  - Energy as shown and used runs from 100% fresh to about 85% at the end of a normal stint (where the coach subs him) and 80% at empty (`levers.LEGS_DROP`, `Game.legs`). It drains about 2% a minute on the floor (faster under tiring calls) and comes back about 4% a minute on the bench.
  - Real stints show no such drop because coaches sub players out first. In the game, boosted calls tire players far faster, and this is what keeps a tiring call a trade-off and not a free win.
  - (Replaces the earlier tired-legs penalty, which only started below 60% on the old fatigue clock.)
- **Credit (`Event.credit`):** the engine marks a play it can put down to a call in force, with its own random numbers so crediting never changes the game. Credited:
  - a call that paid off ("THE PRESS WORKS!", "ATTACK MODE!", "CRASHED THE GLASS!", "THE ZONE HOLDS!", ...), at least half the time such a play happens (`CREDIT_FLOOR` = 0.5) so the coach sees it;
  - a price paid ("PRESS BROKEN", "BURNED IN TRANSITION", "ZONE BEATEN FROM DEEP", "TIRED LEGS", ...), only as often as the call really caused it.

  One game with three calls had 34 credited plays: 25 paid off, 9 cost something.
- **On the court:**
  - Credited plays get a callout naming your call, a glow on the player, a sound and a one-second pause.
  - A tally under your score ("your calls ✓7 paid off · ✗3 cost you").
  - Badges under each player for his calls (💥 aggressive, 🚀🎯🏹 shot zone, ⚡ pressure, 🛡️ protect the rim, 📦 box out, 🏃 leak out, ✋/💪 fouls, ⭐ focus, ² ³ for two or three steps) and his state (🔥 hot, 🧊 cold, 💦 tired), for both teams' state.
  - Players' chatter shows as speech bubbles over their heads.
  - A call you make: a banner (team) or a pulse and "Coach: ..." bubble (player), then the reply over the replier's head.
- **Every call says what it changed** (`server.impact`, in the chatter as 📈): the three biggest moves in the next chance's odds, e.g. "Gilgeous-Alexander takes 27.9% → 38.0% of our chances".

**Sixth follow-up (Oct 4): calls wear off.**
- In the live game every call loses half its strength each `levers.CALL_HALF_LIFE` = 180 seconds of game time (`Game(half_life=...)`, `Game._fade`).
  - A call at the limit (●●●) is at ●◐○ after about 2.5 minutes, ●○○ after 5, and forgotten after 13 (below `FORGOTTEN` = 0.05), unless the coach repeats it.
  - Its energy cost fades with it. Focus, double teams, fouling late and rest don't fade.
- The meter shows half steps (◐) so the fade is visible, and the monitor says "fading: forgotten in 9:45 unless you repeat it".
- `hoopformer serve --half-life 300` makes calls last longer, `--half-life 0` keeps them forever. Simulations and tests keep calls at full strength.

**Seventh follow-up (Oct 4): smooth, spread-out movement; 0.5×; man to man.**
- **No more cross-court teleports.** Some possessions are very short in game time; real play-by-play has 6.6% of first chances under 4 seconds, mostly transition plays where players are already running.
  - The animation had to fit a full-court run into them, so players crossed 77 feet in under a second.
  - Now the live game (game mode) has no first chance under 4 seconds (`levers.MIN_FIRST_SECONDS`, `Game(min_first_seconds=...)`); simulations keep the real distribution.
  - On the court, every run is paced by its distance at up to 26 ft/s (`VMAX`), not by a fixed share of the possession. Defenders run back on their own path to where they pick up their man, and a shot is taken on the side of the floor the shooter is on.
  - After a basket, the ball goes from the rim to the inbounder. A player coming off the bench walks on from the scorer's table, not from where he last stood.
  - Measured over several hundred game seconds with calls in force: median speed 2 ft/s, 99% under 32, 99.9% under 45.
- **Spread out:** on a run up the floor the offense fills the lanes (the handler in the middle, wings on both sidelines, trailers between), and defenders move toward their man's side of the floor first.
- **Playback is 0.5× only**, and sound is always on: the speed and sound buttons are gone.
- **"Man to man"** (team, defense) ends a double team (`stop: ["double_team"]` in `POST /api/call`); ● shows while nobody is doubled. A double team in force shows 👥 on the doubled player at once, before it reaches the court on their next possession.

**Eighth follow-up (Oct 4): the press no longer teleports.** When a press ended a few seconds into a possession, all five defenders switched from the full-court press to their half-court spots in a single frame (jumps of 6–25 feet). Now they run back over 1.5 seconds (`PRESS_RELEASE`), and anything else that has to move at once (the free-throw line-up) walks over 0.9 seconds. Checked frame by frame with a press, a double team, a zone, crashing and pushing the pace in force: no player moved more than 2 feet in a frame in 99 seconds of game time.

**Ninth follow-up (Oct 4): a break after every possession, set plays you can see, wider spacing.**
- **The game stops between possessions (live).** After a possession has been shown, and before the server plays the next one, a pop-up over the court holds the talk rows, set for the coming possession ("BOS ball next: your defense"), with the last play and the score.
  - Whatever you call there is in force from the very next play, not the one after.
  - "▶ Next possession" (or Enter) goes on. "Stop after every possession", in the pop-up and next to Play, turns it off.
- **Set plays from the tactics panel are acted out.** The plan's offense is sent with every chance (`Side.play`, `Event.tactics.off.play`):
  - **pick-and-roll / pick-and-pop:** the big comes up to screen for the handler (the "run it through" player, or the point guard), the handler comes off it downhill, and the screener rolls to the rim or pops to the arc. Both are outlined while it happens, and the strip above the court names them ("pick-and-roll Gilgeous-Alexander–Holmgren").
  - **five-out:** all five beyond the arc.
  - **isolation:** the other four clear out wide.
- **Wider spacing:** half-court spots at the top beyond the arc, both wings at 45° beyond the arc, the corner, and the dunker spot. On the run up the floor each player goes out to his lane early, on his own side.

**Tenth follow-up (Oct 5): tactics in the talk rows, roles, no timeouts.**
- **No timeouts for the coach.** The button, the "Timeout!" call and the timeout-locked tactics panel are gone, and the break after every possession replaces them. The engine's scripted coaches still call their own (TV breaks, stopping a run), which rest players.
- **The tactic is the first list in the All team row**, in front of its calls, and follows the ball like the calls do.
  - On offense, a set play: free offense, pick-and-roll, pick-and-pop, isolation, post-up, triangle, five-out, motion.
  - On defense, a scheme: man to man (also ends a double team), switch everything, drop coverage, blitz, 2-3 zone, full-court press, box-and-one.
  - It goes to `POST /api/tactics` as levers plus `play`, `scheme` and `roles` (`Side.play`, `Side.scheme`, `Side.roles`, sent with every chance).
  - A tactic's levers don't fade (`Instruction.fades = False`); calls still do.
- **Each player's first list is his role in the tactic:**
  - pick-and-roll: ball handler and screener;
  - isolation: scorer;
  - post-up: post player and entry passer;
  - triangle: post, wing, corner, point and weak side;
  - box-and-one: the chaser.
  - The rest are spacers (or in the box). Roles start with the likeliest players (handler by assist rate, big by rebounding, chaser by steal rate). Picking a role for one player swaps it with whoever had it.
  - Roles mean something in the engine: the pick-and-roll runs through the handler (focus) and the screener looks for the rim (or the three on a pop); the isolation and the post-up run through their scorer; the chaser pressures his man.
- **A helper under the rows** draws the tactic on a half court with your five in their roles (screens, rolls, passes, the triangle, the box) and says in a sentence who does what.
- **On the court:**
  - the pick-and-roll uses the chosen handler and screener;
  - the post-up feeds the post;
  - the triangle sets up its triangle, swings the ball point → wing → post, and the weak side cuts;
  - the box-and-one's chaser stays on their main scorer (by usage) while four play the box;
  - drop coverage sags the big.
- **Substitutions:** a player's name in his row is a list of the bench; picking someone brings him in (`POST /api/call` with `substitutions`), and he takes over the role.
- **The pop-up between possessions** is now a window over the whole page, with the rows, the tactic and the helper.

**Eleventh follow-up (Oct 5): every player always has a role; the 1990s vs the 2000s.**
- **Every tactic gives all five a role, so no list is ever greyed out.**
  - On offense, each play's special roles plus spots for the rest. For example the pick-and-roll: ball handler, screener, left wing, right wing, corner. A free offense: point, wings, corner, dunker spot.
  - In man-to-man defenses (man to man, switch, drop, blitz, press), each defender's role is his man: "On Bryant".
  - In the 2-3 zone, a zone spot; in the box-and-one, the chaser and the four box spots.
  - Picking a role swaps it with whoever had it. Defaults pair players by size: each five is ordered handler, wings from smallest to biggest, big, so Olajuwon takes Shaq and Pippen takes Kobe.
  - The court follows: the offense sets up at its role spots, and each defender guards his chosen man, zone spot or box spot. In drop coverage, the defender on their biggest man sags.
  - Each chance carries both teams' roles (`Event.tactics.off.roles`, `def.roles`).
- **Classic teams** (`game/legends.py`): the 1990s All-Stars (90S) and the 2000s All-Stars (00S), twelve players each as they were in one season of their prime. Jordan 1995-96, Olajuwon 1993-94, Stockton 1993-94 and Rodman 1995-96 are on one side; Kobe 2005-06, Shaq 1999-00, Duncan 2001-02 and LeBron 2008-09 on the other.
  - **Where the numbers come from:** there is no play-by-play before 1996-97, so their rates come from season totals (`hoopformer fetch --legends`: stats.nba.com career stats, 24 files, in the manifest). These are turned into per-chance rates with era averages (assumed: 92 possessions and 1.14 chances per possession per 48 minutes, 37.5 made and 44 missed field goals, 15 forced turnovers).
  - Two-point shots are split into rim and midrange from each player's two-point percentage (rim 59%, midrange 40%), since season totals don't say where shots came from.
  - Their ids are 90,000,000 plus the real id, so the 2008-09 LeBron never clashes with today's. Their defenses are league average, and the league around them (pace, home court) is the model's.
  - **How they play:** 60 games end 115.9 to 107.5 on average (the 90s win 38 of 60; over 200 games 114.4 to 112.4, the 90s win 53%), and each team takes about 11.5 threes a game, like their eras.
  - **The default live game:** `hoopformer serve` coaches the 90S against the 00S once their careers are cached (`--home`/`--away` to change; OKC vs BOS otherwise).

**Twelfth follow-up (Oct 5): no pop-up, calls that agree with the tactic, 0.8x.**
- **The break after each possession no longer covers the screen.** The talk panel lights up, with a bar at its top: "00S ball next: your defense", the last play, "Stop after every possession" and "▶ Next possession". The Play button says "▶ Next possession" too. The court stays in view.
- **Calls never fight the tactic.**
  - "Pressure the ball full court" and "Pack the paint (2-3 zone)" are gone: the full-court press and the 2-3 zone are tactics.
  - Any other call about something the current tactic decides is left out of the list (`tacticControls`, `fights`). Under a press or a blitz there is no "Sit back" and no "Pressure / Play off your man"; under a zone, drop or box-and-one, no "Run them off the line", "Protect the rim" or "Stay home". Under a pick-and-roll, isolation or post-up, there is no "Run it through" and no aggression call for the player the play runs through. A screener or post player gets no shot-zone call.
- **Playback runs at 0.8x** (a quarter takes 15 minutes).

**Thirteenth follow-up (Oct 5): the court shows the tactic in the talk panel.**
- **Why they disagreed:** a tactic change applies to the engine from the next possession, so the court kept playing the possession in progress with the old tactic while the panel already showed the new one. In the 2-3 zone, each defender also leaned toward the man in the same place in the other five, so the zone looked like a smeared man-to-man.
- **The court switches at once.** Picking a tactic or a role redraws the possession in progress with it (`shapeFrom`, `withShape`): the defenders walk from the old shape to the new one, and the strip above the court says what they are in. The engine's numbers still change from the next possession.
- **Zones look like zones.** In the 2-3 zone and the box-and-one, each defender stands on his role's spot (two up top and three across the paint; four in a box with the chaser on their main scorer). The five slide together toward the side of the floor the ball is on, up to 7 ft. A dashed outline joins them on the floor, and a dashed line joins the chaser to his man.
- **No more sprints across the floor.** Frame by frame, a few players ran 40-75 ft/s for a moment. The causes:
  - the run up the floor went up a fixed lane and cut across the whole width to the spot at the end; the lane is now on his spot's side;
  - every bend of a run was a full stop; a run now passes through its bends;
  - run times were set from the average speed, so the peak was 1.5x faster; they now allow for speeding up and slowing down;
  - the shooter's last run to his shot spot started too late;
  - on a one-second putback chance, players ran all the way to their set spots; they now go only as far as they can.

  Over a minute and a half of play, the 99th percentile of running speed fell from 37 to 26 ft/s (an NBA sprint is about 25-30). The remaining jumps are dead-ball glides (free-throw line-ups, a tactic switch).

**Fourteenth follow-up (Oct 6): every tactic on the court as the helper draws it; trash talk.**
- **Why an isolation didn't look like one:** three causes.
  - The court redrew only while the game played, so a tactic picked while paused moved nobody.
  - Every possession began with a run up the floor, so the shape appeared only seconds in.
  - The court drew every play as the mirror image of the helper, then flipped half the possessions at random.
- **The break is now when they set up.** While the break is open (the clock is stopped), the ten on the floor walk from where the last possession ended into the next one's shape: the offense at its play's spots, the defense in its scheme. Against a full-court press, the offense stays back and the pressers pick them up there.
  - Picking a tactic, a role or a substitute re-routes them at once.
  - The next possession starts exactly where they stand, so the run up the floor happened during the break, and its first action comes after about a second instead of three or four.
  - With "Stop after every possession" off, possessions still start with the run up the floor.
- **Picking a tactic while paused** redraws the possession in progress with it; everyone glides into the new shape.
- **The court and the helper agree.** The court draws a play exactly as the helper does, turned to face the basket, never mirrored. The helper now draws your five where the court will put them, from the same function (`shapeFor`), for every tactic except the press, which happens full court and stays a sketch. Checked at the break for all 8 plays and 6 half-court defenses: every player within 0.1 ft of his helper dot. Through a whole possession (isolation, 2-3 zone, box-and-one, blitz), players stayed within about 6 ft of their spots while cutting, and the zone and the box slid as one block toward the ball.
- **Tactics that looked like something else:**
  - Drop coverage was drawn as a 2-3 zone, because it packs the paint; a zone is now drawn only for the 2-3 zone (or for the other coach's pack-the-paint call).
  - Blitz was drawn as a full-court press; it now sends the man on their big at the ball handler, together with the handler's own man (marked ×2).
  - In an isolation the ball handler kept the ball while the scorer drove without it; the scorer now gets the ball early and keeps it.
  - Motion offense now keeps cutting to the basket and back out.
  - A new play's focus replaces the old play's (the strip said "triangle · through Jordan").
- **Trash talk (🗯, next to 🎙 in every row):** hold it and say it. It goes to the opponent he's matched with: his man, the man guarding him, or in a zone the nearest. From the All team row, it goes to their whole five.
  - The opponent answers over his head and in the chatter. A callout says whether he was rattled (green) or fired up (red), with what changed.
  - `Game.trash_talk` moves his confidence by 0.05 (as much as a steal or a block; assumed), and with it his share of their chances (Athlete.usage). The whole team: 0.025 each.
  - Cold players are rattled more often and hot ones feed off it: the chance of rattling him is 0.5 + (0.5 − his confidence) + half the talker's lead, kept between 0.2 and 0.8. Measured over 400 games: 72.5% rattled at confidence 0.3, 29.5% at 0.7.
  - It has its own random numbers, so talking never changes the rest of the game's dice. What is said doesn't matter yet; who says it to whom does. Route: `POST /api/trash`.
- **The language choice (English / 中文) is gone:** voice is English.

## 10. Open questions for marinelj

1. ~~Fictional or real players?~~ Real players for now (§8).
2. ~~Keep v0.1 and v0.2 on schedule?~~ Yes.
3. ~~Game vs. Studio?~~ The game is the centre of the lab; Studio becomes its analysis mode.
4. Platform: web first? Desktop? Mobile?
5. Single player against the AI coach first, then two humans?
6. Voice: which speech-to-text service, and is it on-device or in the cloud?

## 11. Agenda for the deep dive

1. **The possession engine:** which decisions happen in each possession, and which data trains each one.
2. **Lever schema v1:** pick about 12 levers and measure their real-data ranges.
3. **Memory dynamics:** what fades, what persists, how confidence moves.
4. **The translator:** the structured-output schema, and a test set of 50 real coach phrases with expected levers.
5. **The fun test:** who plays, what they do, and what counts as a pass.
