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
