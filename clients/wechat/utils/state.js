// The game as the phone has shown it so far: which events, the score, the five on the floor for each team, who has
// the ball, the shot clock, a dead ball at the free-throw line, the timeouts taken and the play-by-play.
// (Where everyone is on the court comes from the shared rules, core/court.js.)

function freshState() {
  return { applied: 0, home: 0, away: 0, offense: null, chanceT: 0, chanceLen: 24, lineups: { home: [], away: [] },
           dead: null, timeouts: { home: 0, away: 0 }, feed: [] };
}

function apply(S, G, e) {   // one engine event, shown
  S.home = e.home_score; S.away = e.away_score;
  S.lineups.home = e.home_lineup; S.lineups.away = e.away_lineup;
  const team = e.team === G.home.tricode ? "home" : "away";
  if (e.kind === "chance") { S.offense = team; S.chanceT = e.t; S.chanceLen = e.zone === "second" ? 14 : 24; S.dead = null; }
  if (e.kind === "period_start") { S.offense = team; S.chanceT = e.t; S.chanceLen = 24; if (!(S.dead && S.dead.shot)) S.dead = null; }
  if (e.kind === "foul" && (e.zone === "shooting" || e.zone === "and-one")) S.dead = { shooter: e.other };   // to the line
  if (e.kind === "free_throws") S.dead = { shooter: e.actor, shot: true };
  if (e.kind === "rebound") { if (!(S.dead && S.dead.shot)) S.dead = null; if (e.zone === "defensive") S.offense = team; }
  if (e.kind === "timeout") S.timeouts[team] += 1;
  if (e.text && e.kind !== "coach" && e.kind !== "reply") S.feed.push(e);
  S.applied += 1;
}

module.exports = { freshState, apply };
