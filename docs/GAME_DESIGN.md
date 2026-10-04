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

  - **Voice:** hold 🎙, speak, release: the browser's own speech recognition fills the row as you speak and sends it on release, then it's the same as typing. Pick English or 中文 next to "Hold 🎙 to speak" (Qwen understands both). Chrome sends the audio to Google's speech service; Safari uses Apple's (Siri must be on). The browser asks for the microphone once; a press made while that prompt is open is finished when you answer it. Every failure (nothing heard, released too soon, microphone blocked, no connection to the speech service) shows up as a 🎙 note in the chatter.
  - **Double teams on the court:** each possession records the player the defense is doubling (`Event.other` on the chance), and the defender whose man stands nearest leaves to help, so two figures stand on the doubled player, whose tag shows ×2.
- **Measured:** a whole game streams in about 200 possession requests in 1.2 seconds on this Mac, so the engine never makes the page wait. Tests run a real server on a free port (`tests/test_server.py`).
- **Not yet:** two human coaches; an AI coach that talks; voice tested by marinelj (the browser pane Claude uses can't grant a microphone).

**Day 4 follow-up (Oct 4): instructions you can see.** marinelj found that instructions rarely showed on the court: the engine applied them, but the figures' movement ignored them, and a lever's effect is a probability (SGA +0.8 aggression takes him from about 30% to 35% of chances, which one possession can't show). Three changes:
- **Every chance records the calls in force** (`Event.tactics`: the offense's levers, focus and player levers; the defense's levers and double team). Uncoached games carry none and are unchanged.
- **The figures act the calls out on every possession**, while the outcome stays the engine's: a 2-3 zone around the paint, a full-court pickup with two on the ball, all five crashing the rim on a miss (or getting back), a sprint or a walk-up, the told player driving at the rim and getting more of the passes, wide spacing for "more threes". A play-call strip above the court names the calls, the called player's tag is outlined, and a player shouts a new call once when it takes effect ("Two-three! Zone, zone!").
- **An engine monitor** (live page, `Game.monitor`) shows the next chance's odds at both ends with and without the directives, each player's share of chances with energy and confidence, and every directive with the coach's words and the game time it has left.

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
