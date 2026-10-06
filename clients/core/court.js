// The court's rules, shared by the two clients: the web page (clients/web) and the WeChat Mini Program
// (clients/wechat, which keeps a copy: `hoopformer clients` updates it). The engine on the server decides what happens;
// this decides where everyone is while it happens: every player's position at every moment of a possession (a function
// of game time), the tactics (set plays and defenses, the roles in them, who fits each role), how each archetype moves,
// and the calls the coach can make. No page code: each client draws the court and talks to the server itself.
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();   // the Mini Program: require()
  else root.HoopformerCourt = factory();                                            // the web page: a global
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  function createCourt(G) {   // the rules for one game (G: the game data the server sends)
  const playerById = {};
  for (const key of ["home", "away"]) for (const p of G[key].players) playerById[p.id] = p;
  const last = (name) => { const parts = name.split(" "); return parts.length > 1 && /^(Jr\.|Sr\.|II|III|IV)$/.test(parts.at(-1)) ? parts.at(-2) : parts.at(-1); };

  // ---------- choreography: positions are a function of game time ----------
  // Court in feet: 94 x 50, baskets at x = 5.25 and 88.75. Every possession gets a plan built from
  // the engine's events: a run to the attacking end on curved paths, a few illustrative passes, and a
  // final action that matches the engine (shooter, passer, turnover, stealer, foul, rebounder).
  const attacksRight = (key, period) => { const homeRight = period <= 2 || period >= 5; return key === "home" ? homeRight : !homeRight; };
  // dy > 0 is the helper's right (it draws the basket at the bottom), so a play on the court is the helper's drawing
  // turned to face the basket, never its mirror image
  const toCourt = (right, dx, dy) => ({ x: right ? 88.75 - dx : 5.25 + dx, y: 25 + (right ? -dy : dy) });
  const basketOf = (right) => toCourt(right, 0, 0);
  const SPOTS = [[25, 0], [15, -20], [15, 20], [1.5, -22.5], [4.5, 10]];   // feet from the basket: top, wings, corner, dunker spot
  // How each archetype (archetypes.py: from his own numbers) plays on the court. fit: how well he suits each kind
  // of role [handle the ball, play the wing, spot up, play inside, score]; move: what he does off the ball; drive:
  // he attacks the rim in free play; gap: how far he sags from his man toward the basket (small: tight); crash: he
  // goes to the glass on a miss. A set play decides where everyone is; the archetype decides how he moves there.
  const STYLE = {
    "Two-Way Scoring Dominator":   { fit: [0.6, 1, 0.4, 0.1, 1], move: "cut", drive: true, gap: 0.2 },
    "High-Volume Isolation Guard": { fit: [0.9, 0.6, 0.4, 0, 1], move: "hold", drive: true, gap: 0.3 },
    "All-Around Point Forward":    { fit: [1, 0.7, 0.3, 0.4, 0.8], move: "cut", drive: true, gap: 0.28, crash: true },
    "Floor General":               { fit: [1, 0.4, 0.5, 0, 0.3], move: "hold", gap: 0.22 },
    "Scoring Playmaker":           { fit: [0.95, 0.6, 0.6, 0, 0.8], move: "hold", drive: true, gap: 0.3 },
    "Shot-Creating Wing":          { fit: [0.5, 1, 0.5, 0.1, 0.9], move: "relocate", drive: true, gap: 0.3 },
    "Slashing Wing":               { fit: [0.3, 1, 0.2, 0.2, 0.6], move: "cut", drive: true, gap: 0.28 },
    "3-and-D Wing":                { fit: [0.1, 0.7, 1, 0.1, 0.3], move: "relocate", gap: 0.18 },
    "Movement Shooter":            { fit: [0.2, 0.8, 1, 0, 0.6], move: "curl", gap: 0.3 },
    "Gravity Shooter":             { fit: [0.8, 0.7, 1, 0, 0.9], move: "relocate", gap: 0.3 },
    "Stretch Big":                 { fit: [0.1, 0.3, 0.6, 0.8, 0.7], move: "pop", gap: 0.35 },
    "Pick-and-Roll Post Bruiser":  { fit: [0.1, 0.1, 0, 1, 0.8], move: "screen", gap: 0.35, crash: true },
    "Dominant Post Scorer":        { fit: [0, 0, 0, 1, 0.9], move: "seal", gap: 0.5, crash: true },
    "Two-Way Post Anchor":         { fit: [0.1, 0.1, 0, 1, 0.6], move: "seal", gap: 0.5, crash: true },
    "Rim-Running Anchor":          { fit: [0, 0, 0, 1, 0.2], move: "dive", gap: 0.55, crash: true },
    "Rebounding Specialist":       { fit: [0, 0.1, 0, 0.9, 0], move: "crash", gap: 0.35, crash: true },
    "Energy Big":                  { fit: [0, 0.1, 0, 0.8, 0.2], move: "seal", gap: 0.4, crash: true },
    "Role Player":                 { fit: [0.3, 0.6, 0.6, 0.3, 0.3], move: "relocate", gap: 0.3 },
  };
  const styleOf = (id) => STYLE[(playerById[id] || {}).archetype] || STYLE["Role Player"];
  const [HANDLE, WING, SHOOT, BIG, SCORE] = [0, 1, 2, 3, 4];
  function fitScore(id, kind) {   // how well he suits a kind of role: his archetype first, then his numbers
    const p = playerById[id];
    return styleOf(id).fit[kind] * 10 + (kind === HANDLE ? p.handler * 2 : kind === BIG ? p.big * 3 : kind === SCORE ? p.usage * 3 : 0);
  }
  // Off the ball, between the set play's moves: where he goes next from his spot (and back, every other time).
  // Shooters slide along the arc, movement shooters curl toward the top, slashers cut, rim-runners dive, post
  // players seal, stretch bigs pop out, bruisers come up to screen for the ball, handlers dribble around the top.
  function offBall(how, spot, right, r, out) {
    const feet = { dx: right ? 88.75 - spot.x : spot.x - 5.25, dy: right ? 25 - spot.y : spot.y - 25 };
    const d = Math.hypot(feet.dx, feet.dy), a = Math.atan2(feet.dy, feet.dx), basket = basketOf(right);
    const at = (dist, angle) => clampCourt(toCourt(right, Math.max(1, dist * Math.cos(angle)), dist * Math.sin(Math.max(-1.52, Math.min(1.52, angle)))));
    const near = (n) => clampCourt({ x: spot.x + (r() - 0.5) * n, y: spot.y + (r() - 0.5) * n });
    if (!out) return near(how === "hold" ? 4 : 2.5);
    if (how === "cut" || how === "motion") return clampCourt(lerp(spot, basket, 0.5 + r() * 0.2));
    if (how === "dive" || how === "crash") return clampCourt(lerp(spot, basket, 0.55 + r() * 0.25));
    if (how === "relocate") return at(d, a + (r() < 0.5 ? -1 : 1) * (0.12 + r() * 0.15));
    if (how === "curl") return at(Math.max(15, d * 0.85), a * 0.35);   // around a screen, up toward the top
    if (how === "pop") return at(Math.max(d, 21.5), a);
    if (how === "screen") return clampCourt(lerp(spot, toCourt(right, 24, a > 0 ? 3 : -3), 0.75));   // up to screen for the ball
    if (how === "seal") return clampCourt(lerp(near(3), basket, 0.2));
    return near(4);
  }
  // The tactics drawn: where each role sets up (also on the court) and how they move (the helper under the talk rows).
  // Each tactic's roles and where they stand ([feet out from the basket, feet across]): on the court, and in the helper
  // under the talk rows, which also draws the moves ([role, from, to, kind]). Man-to-man defenses have no spots:
  // each defender is on his man (MAN_SPOTS by where his man plays).
  const LAYOUT = {
    free: { spots: { point: [25, 0], lwing: [15, -20], rwing: [15, 20], corner: [1.5, -22.5], dunker: [4.5, 10] } },
    pnr: { spots: { handler: [25, 0], screener: [21, 3.5], lwing: [15, -20], rwing: [15, 20], corner: [1.5, 22.5] }, start: { screener: [4.5, 10] },
           moves: [["screener", [4.5, 10], [21, 3.5], "run"], ["handler", [25, 0], [11, -2], "run"], ["screener", [21, 3.5], [3.5, 1], "roll"]] },
    pop: { spots: { handler: [25, 0], screener: [21, 3.5], lwing: [15, -20], rwing: [15, 20], corner: [1.5, -22.5] }, start: { screener: [4.5, 10] },
           moves: [["screener", [4.5, 10], [21, 3.5], "run"], ["handler", [25, 0], [11, -2], "run"], ["screener", [21, 3.5], [21, 13], "roll"]] },
    iso: { spots: { scorer: [15, 17], top: [25, -6], lwing: [15, -20], corner: [1.5, -22.5], dunker: [4.5, -10] }, moves: [["scorer", [15, 17], [3, 4], "run"]] },
    post: { spots: { post: [6, 7], entry: [15, 18], top: [25, -3], lwing: [15, -20], corner: [1.5, -22.5] }, moves: [["entry", [15, 18], [6, 7], "pass"]] },
    triangle: { spots: { post: [6, 8], wing: [16, 18], corner: [2, 22], point: [25, -4], weak: [14, -16] }, triangle: ["post", "wing", "corner"],
                moves: [["point", [25, -4], [16, 18], "pass"], ["wing", [16, 18], [6, 8], "pass"], ["weak", [14, -16], [3, -2], "roll"]] },
    five_out: { spots: { point: [25, 0], lwing: [17, -18], rwing: [17, 18], lcorner: [1.5, -22.5], rcorner: [1.5, 22.5] } },
    motion: { spots: { point: [25, 0], lwing: [15, -20], rwing: [15, 20], corner: [1.5, -22.5], dunker: [4.5, 10] },
              moves: [["lwing", [15, -20], [8, -6], "run"], ["rwing", [15, 20], [8, 6], "run"]] },
    // Scripted set plays: once all five are set, script: [seconds, role, feet out, feet across, kind] is each move (a
    // run, a screen, a roll) arriving at its time, and passes: [seconds, role] who gets the ball when.
    elevator: { spots: { shooter: [5, 0], doorl: [18.5, -4.5], doorr: [18.5, 4.5], passer: [22, -17], corner: [1.5, 22.5] },
                script: [[1.1, "shooter", 14, 0, "run"], [1.8, "doorl", 18.5, -1.3, "screen"], [1.8, "doorr", 18.5, 1.3, "screen"], [2.0, "shooter", 24.5, 0, "run"]],
                passes: [[-0.8, "passer"], [2.2, "shooter"]] },
    horns: { spots: { handler: [27, 0], elbowl: [18, -6], elbowr: [18, 6], lcorner: [1.5, -22.5], rcorner: [1.5, 22.5] },
             script: [[0.9, "elbowl", 24.5, -2.5, "screen"], [1.9, "handler", 15, 9, "run"], [2.3, "elbowr", 21, 12, "run"], [2.6, "elbowl", 5, -1.5, "roll"]],
             passes: [[-0.8, "handler"], [2.9, "elbowl"]] },
    spain: { spots: { handler: [27, 0], screener: [7, -9], backscreen: [13, 0], lwing: [16, -20], rcorner: [1.5, 22.5] },
             script: [[1.0, "screener", 24, -2.5, "screen"], [2.0, "handler", 16, 8, "run"], [2.3, "backscreen", 19.5, -1.5, "screen"], [2.8, "screener", 5, -1, "roll"],
                      [3.3, "backscreen", 24.5, -5, "run"]],
             passes: [[-0.8, "handler"], [3.6, "backscreen"]] },
    floppy: { spots: { shooter: [4, 0], single: [8, -9], stagger1: [8, 9], stagger2: [14, 12], handler: [27, 0] },
              script: [[0.6, "single", 9, -8, "screen"], [0.6, "stagger1", 9, 8, "screen"], [0.8, "stagger2", 15, 11, "screen"], [1.4, "shooter", 12, 11, "run"],
                       [2.2, "shooter", 21, 17, "run"]],
              passes: [[-0.8, "handler"], [2.4, "shooter"]] },
    hammer: { spots: { driver: [20, 17], shooter: [15, -20], hammer: [8, -11], big: [4, 9], top: [27, 0] },
              script: [[1.2, "hammer", 9, -17, "screen"], [1.7, "driver", 5, 10, "run"], [1.9, "big", 9, 2, "run"], [2.1, "shooter", 1.5, -22.5, "run"]],
              passes: [[-0.8, "driver"], [2.5, "shooter"]] },
    zone23: { spots: { topl: [19, -7.5], topr: [19, 7.5], wingl: [6, -13], wingr: [6, 13], middle: [4.5, 0] } },
    zone131: { spots: { trap: [26, 0], wingl: [17, -17], middle: [14, 0], wingr: [17, 17], rover: [4, 0] } },
    box1: { spots: { chaser: [22, 4], boxtl: [15, -8], boxtr: [15, 8], boxll: [5, -9], boxlr: [5, 9] }, moves: [["chaser", [22, 4], [22, 1], "chase"]] },
    tri2: { spots: { chaser: [22, 4], chaser2: [22, -4], tritop: [15, 0], tril: [5, -8], trir: [5, 8] },
            moves: [["chaser", [22, 4], [20, 8], "chase"], ["chaser2", [22, -4], [20, -8], "chase"]] },
    man: {}, switch: {}, drop: {}, blitz: {}, press: {},
  };
  // A scripted play, drawn: each role's runs, screens and rolls from its spot, and the passes, from the same script the
  // court plays (planSegment), so the helper never shows something the court doesn't do.
  for (const lay of Object.values(LAYOUT)) {
    if (!lay.script) continue;
    const steps = [...lay.script].sort((a, b) => a[0] - b[0]), at = { ...lay.spots }, moves = [];
    const where = (role, t) => { let q = lay.spots[role]; for (const [dt, r2, dx, dy] of steps) if (r2 === role && dt <= t) q = [dx, dy]; return q; };
    for (const [, role, dx, dy, kind] of steps) { moves.push([role, at[role], [dx, dy], kind]); at[role] = [dx, dy]; }
    let holder = null;
    for (const [dt, role] of lay.passes || []) { if (holder) moves.push([holder, where(holder, dt), where(role, dt + 0.3), "pass"]); holder = role; }
    lay.moves = moves;
  }
  const MAN_SPOTS = [[22, 0], [13, -17], [13, 17], [3, -19], [4, 7]];   // on the offense's point guard, wings, corner and big
  const restarts = [];   // tactics changed in a timeout during a possession: { s: its chance's event index, at: game time, tactic }
  const pickLog = [];   // the coach's own role picks over the game: { events: how many the page had then, picked }
  const picksFor = (s) => { let p = {}; for (const x of pickLog) if (x.events <= s) p = x.picked; return p; };
  function withPicks(given, picked, ids) {   // the coach's own picks take their roles back whenever they're on the floor
    const out = { ...given };
    for (const [r, id] of Object.entries(picked || {})) {
      if (!ids.includes(id)) continue;
      for (const k of Object.keys(out)) if (out[k] === id) delete out[k];
      out[r] = id;
    }
    return out;
  }
  function withShape(tac, ev, coach = tactic) {   // a chance's calls with the coach's tactic (now, or then) in place of the one it was played with
    const ours = ev.team === G.home.tricode ? "off" : "def", out = { off: { ...((tac && tac.off) || {}) }, def: { ...((tac && tac.def) || {}) } };
    if (ours === "off") {
      const focusOf = (play) => (PLAYS[play] || {}).focus;   // the man a play runs through
      if (focusOf(out.off.play) || focusOf(coach.play)) out.off.focus = focusOf(coach.play) ? coach.roles[focusOf(coach.play)] : undefined;
      out.off.play = coach.play === "free" ? undefined : coach.play;
      out.off.roles = { ...coach.roles };
    } else {
      const scheme = SCHEMES[coach.scheme];
      out.def.scheme = coach.scheme === "man" ? undefined : coach.scheme;
      out.def.roles = { ...coach.roles };
      out.def.chaser = coach.scheme === "box1" ? coach.roles.chaser : undefined;
      out.def.protect_paint = (scheme.team || {}).protect_paint || 0;   // the shape comes from the tactic, not the old levers
      out.def.pressure = (scheme.team || {}).pressure || 0;
      if (coach.scheme === "man") delete out.def.double_team;
    }
    return out;
  }
  function playSpots(offT, off) {   // where each player sets up for a set play: his role's spot, as the helper draws it
    const lay = LAYOUT[offT.play || "free"], rl = offT.roles || {};
    if (!lay || !lay.spots) return {};
    const out = {};
    for (const [role, spot] of Object.entries(lay.spots)) if (off.includes(rl[role]) && !out[rl[role]]) out[rl[role]] = (lay.start || {})[role] || spot;
    return out;
  }
  function spotOf(offT, setUp, i, id) {   // where he sets up, in feet from the basket: his role's spot, else his place in the five
    let [dx, dy] = setUp[id] || SPOTS[i] || [20, 0];
    const pref = (offT.players || {})[id];
    const spotsUp = (i <= 2 && (offT.three_point_rate || 0) > 0.2) || (pref && pref.shot_preference && pref.shot_preference.zone === "three")
      || offT.play === "five_out";   // five-out: even the big stands beyond the arc
    if (spotsUp && !setUp[id]) { const d = Math.hypot(dx, dy) || 1; dx = (dx / d) * 25.5; dy = Math.max(-21, Math.min(21, (dy / d) * 25.5)); }   // spaced beyond the arc
    if ((!offT.play || offT.play === "motion") && !spotsUp) {   // free play: each sets up where his kind plays
      const st = styleOf(id), big = st.fit[BIG] >= 0.8, side = dy < 0 ? -1 : 1;
      if (big && Math.hypot(dx, dy) > 14) [dx, dy] = st.move === "pop" ? [18, 8 * side] : side > 0 ? [17, 6] : [7, -9];   // a big inside: the high post or the block
      else if (!big && Math.hypot(dx, dy) < 12) [dx, dy] = [1.5, 22.5 * side];   // no big for the dunker spot: a shooter in the corner
    }
    return [dx, dy];
  }
  // the shape a defense plays: a scheme's own (drop coverage packs the paint but stays man to man; a blitz presses
  // only on screens), else the levers' (the other coach's calls)
  const pressing = (defT) => defT.scheme === "press" || (!defT.scheme && (defT.pressure || 0) > 0.2);
  const zoned = (defT) => defT.scheme === "zone23" || defT.scheme === "zone131" || (!defT.scheme && (defT.protect_paint || 0) > 0.2);
  const boxed = (defT) => defT.scheme === "box1" || defT.scheme === "tri2";   // chasers on their scorers, the rest in a zone
  function chasersOf(defT, def, off) {   // [defender, the man he chases]: their main scorers, by usage
    const stars = [...off].sort((a, b) => (playerById[b].usage || 0) - (playerById[a].usage || 0)), rl = defT.roles || {};
    const pairs = defT.scheme === "box1" ? [[rl.chaser ?? defT.chaser, stars[0]]] : defT.scheme === "tri2" ? [[rl.chaser, stars[0]], [rl.chaser2, stars[1]]] : [];
    return pairs.filter(([d]) => def.includes(d));
  }
  function zoneSpots(plan) {   // each defender's spot in the zone or the box: his role's, or a free one (null: a man-to-man defense)
    const shape = plan.box ? plan.scheme : plan.zone ? (plan.scheme === "zone131" ? "zone131" : "zone23") : null;
    if (!shape || !LAYOUT[shape]) return null;
    const chasing = new Set(plan.chasers.map(([d]) => d)), chaserRoles = ["chaser", "chaser2"];
    const spots = LAYOUT[shape].spots, free = Object.keys(spots).filter((r) => !chaserRoles.includes(r)), out = {};
    for (const [r, id] of Object.entries(plan.droles)) {
      if (spots[r] && !chaserRoles.includes(r) && plan.def.includes(id) && !out[id] && !chasing.has(id) && free.includes(r)) { out[id] = spots[r]; free.splice(free.indexOf(r), 1); }
    }
    for (const id of plan.def) if (!out[id] && !chasing.has(id)) out[id] = spots[free.shift()] || [8, 0];
    return out;
  }
  function defenseRoles(plan, defT) {   // who leaves his man: the big in drop coverage sags, a blitz sends a second man at the ball
    const theirBig = plan.off[4];   // the big of their five (roles)
    const onBig = plan.def.findIndex((d, i) => markOf(plan, i) === theirBig);
    if (defT.scheme === "drop") plan.dropper = onBig >= 0 ? plan.def[onBig] : null;   // stays back near the rim
    if (defT.scheme === "blitz" && !plan.doubled) {   // the man on their big jumps the ball handler with the handler's own man
      const handler = plan.pnr ? plan.pnr.handler : plan.off[0];
      if (onBig >= 0 && theirBig !== handler) { plan.doubled = handler; plan.helper = onBig; }
    }
  }
  const LANE = [[11, -7], [11, 7], [7, -7], [7, 7], [16, -9], [16, 9], [24, -3], [24, 3]];
  function seeded(n) { let s = (n * 9301 + 49297) % 233280 || 1; return () => { s = (s * 16807) % 2147483647; return s / 2147483647; }; }
  function roles(ids) {   // a five in order: the ball handler, three wings (smallest first), the big (by archetype)
    if (ids.length < 5) return [...ids];
    const handler = ids.reduce((a, b) => (fitScore(b, HANDLE) > fitScore(a, HANDLE) ? b : a));
    const rest = ids.filter((p) => p !== handler);
    const big = rest.reduce((a, b) => (fitScore(b, BIG) > fitScore(a, BIG) ? b : a));
    const wings = rest.filter((p) => p !== big).sort((a, b) => fitScore(a, BIG) - fitScore(b, BIG));
    return [handler, wings[0], wings[1], wings[2], big];
  }
  // Where a shot comes from, relative to the basket: in its zone, on the side of the floor the shooter is on
  // (angle `toward`, 0 = straight out from the basket), so he doesn't sprint across the floor to take it.
  function shotSpot(zone, r, toward = null) {
    const angle = (spread) => Math.max(-spread / 2, Math.min(spread / 2, toward === null ? (r() - 0.5) * spread : toward + (r() - 0.5) * 0.5));
    if (zone === "rim") { const a = angle(2); return [1.5 + r() * 2.5, 3 * Math.sin(a)]; }
    if (zone === "mid") { const a = angle(2.6); return [2 + 13 * Math.cos(a), 13 * Math.sin(a)]; }
    const a = angle(2.9);
    return [Math.max(1.5, 23.75 * Math.cos(a)), Math.max(-22, Math.min(22, 23.75 * Math.sin(a)))];
  }
  const ease = (u) => u * u * (3 - 2 * u);
  const lerp = (a, b, u) => ({ x: a.x + (b.x - a.x) * u, y: a.y + (b.y - a.y) * u });
  const clampCourt = (p) => ({ x: Math.max(1, Math.min(93, p.x)), y: Math.max(1, Math.min(49, p.y)) });
  function track(keys, t) {   // a key [t, x, y, true] is a bend he runs through without stopping
    if (t <= keys[0][0]) return { x: keys[0][1], y: keys[0][2] };
    for (let i = 1; i < keys.length; i++) {
      if (t <= keys[i][0]) {
        const [t0, x0, y0, from] = keys[i - 1], [t1, x1, y1, to] = keys[i];
        const v = t1 > t0 ? (t - t0) / (t1 - t0) : 1;
        const u = from && to ? v : from ? 1 - (1 - v) * (1 - v) : to ? v * v : ease(v);   // speeds up from a stop, slows into one
        return { x: x0 + (x1 - x0) * u, y: y0 + (y1 - y0) * u };
      }
    }
    const k = keys[keys.length - 1]; return { x: k[1], y: k[2] };
  }

  const RESOLVE = new Set(["shot", "turnover", "free_throws"]);
  const VMAX = 26;   // feet per game second: nobody on the court runs faster (an NBA sprint is about 25-30)
  const benchSpot = (id) => ({ x: 47 + ((id % 9) - 4) * 0.9, y: 48.6 });   // a player coming in walks on from the scorer's table
  // the opening tip: starters stand around the centre circle
  const TIP = {};
  { const ids = [...G.events[0].home_lineup, ...G.events[0].away_lineup];
    ids.forEach((id, i) => { const a = (i / ids.length) * Math.PI * 2 + 0.3; TIP[id] = { x: 47 + Math.cos(a) * 9, y: 25 + Math.sin(a) * 9 }; }); }
  // The plan of one possession (or of its rest, after a timeout in which the coach changed the tactic): where everyone
  // is at every moment, from `where` at `start`, and the ball, from `carrier`. With `keep`, the offense (the other
  // team's) goes on exactly as before and only the defense (the coach's) changes.
  function planSegment({ k, s, next, ev, start, where, carrier, inbound, tac, r, keep, picked }) {
    const offKey = ev.team === G.home.tricode ? "home" : "away", defKey = offKey === "home" ? "away" : "home";
    const right = attacksRight(offKey, ev.period);
    const basket = basketOf(right);
    const off = roles(ev[offKey + "_lineup"]), def = roles(ev[defKey + "_lineup"]);
    let resolve = null, shootingFoul = null, rebound = null, ftShooter = null;
    for (let j = s + 1; j < next; j++) {
      const e = G.events[j];
      if (!resolve && e.kind === "foul" && e.zone === "shooting") shootingFoul = e;
      if (!resolve && RESOLVE.has(e.kind)) resolve = e;
      if (e.kind === "rebound" && !rebound) rebound = e;
      if (e.kind === "free_throws") ftShooter = e.actor;   // the possession ends at the line (a foul, an and-one)
    }
    const t0 = start, resumed = start > ev.t;   // resumed: the rest of a possession, after a timeout
    const t1 = resolve ? resolve.t : (next < G.events.length ? G.events[next].t : ev.t + 6);
    const dur = Math.max(0.5, t1 - t0);
    let offT = (tac && tac.off) || {}, defT = (tac && tac.def) || {};
    // your five: every one in a role, the ones you picked in theirs whenever they're on the floor
    if (offKey === "home") offT = { ...offT, roles: completeRoles(PLAYS[offT.play] || PLAYS.free, withPicks(offT.roles, picked, off), off, def) };
    if (defKey === "home") {
      const droles = completeRoles(SCHEMES[defT.scheme] || SCHEMES.man, withPicks(defT.roles, picked, def), def, off);
      defT = { ...defT, roles: droles, chaser: defT.scheme === "box1" ? droles.chaser : defT.chaser };
    }
    const firstChance = ev.zone !== "second";
    let travel = resumed ? Math.min(1, dur * 0.3) : firstChance ? Math.min(7, dur * 0.45) : Math.min(1.5, dur * 0.4);
    const pace = offT.pace || 0;
    if (firstChance && !resumed && pace > 0.2) travel *= 1 - 0.4 * pace;                                   // they sprint into the offense
    if (firstChance && !resumed && pace < -0.2) travel = Math.min(dur * 0.65, travel * (1 + 0.5 * -pace));  // they walk it up

    function offense() {   // the offense's runs, its set play, the final action and the ball
      // offense: start where they were, run to their spots on a curved path, then keep moving
      const keys = {};
      const homeSpot = {}, arrive = {};   // arrive: when he's at his spot
      const setUp = playSpots(offT, off);   // a set play: each player at his role's spot
      off.forEach((id, i) => {
        const [dx, dy] = spotOf(offT, setUp, i, id);
        const spot = clampCourt(toCourt(right, dx + (r() - 0.5) * 3, dy + (r() - 0.5) * 3));
        homeSpot[id] = spot;
        const start = where[id] || benchSpot(id);
        const mid = lerp(start, spot, 0.5);
        const bend = (r() - 0.5) * 14;
        const long = Math.abs(spot.x - start.x) > 30;   // a run up the floor: out to his lane early, up it, then to his spot
        const lane = Math.max(4, Math.min(46, 25 + (spot.y - 25) * 0.9 + bend * 0.15));   // the lane on his spot's side of the floor
        const curve = clampCourt({ x: mid.x + bend * 0.25, y: mid.y + bend });
        // his run takes as long as its distance needs at VMAX, plus half again for speeding up and slowing down
        // (not a fixed share of the possession), within the possession
        const need = (1.5 * Math.hypot(spot.x - start.x, spot.y - start.y)) / VMAX;
        const run = Math.min(Math.max(travel, need), firstChance ? dur * 0.85 : Math.max(travel, dur * 0.6));
        arrive[id] = t0 + run;
        // one run, no stops at the bends: speeding up to the first, full speed between, slowing into his spot
        const legs = (pts) => {   // times for the bends: a speeding-up or slowing-down leg takes twice as long per foot
          const d = pts.map((q, j) => Math.hypot(q.x - (j ? pts[j - 1] : start).x, q.y - (j ? pts[j - 1] : start).y) * (j === 0 || j === pts.length - 1 ? 2 : 1));
          const sum = d.reduce((a, b) => a + b, 0) || 1;
          let at = t0;
          return pts.map((q, j) => { at += (run * d[j]) / sum; return [j === pts.length - 1 ? t0 + run : at, q.x, q.y, j < pts.length - 1]; });
        };
        const k0 = [[t0, start.x, start.y]];
        if (long && run > 1.5) {
          k0.push(...legs([{ x: start.x + (spot.x - start.x) * 0.3, y: lane }, { x: start.x + (spot.x - start.x) * 0.72, y: lane }, spot]));
        } else {   // a short run; on a short chance (a putback) he only gets as far toward his spot as he can
          const to = lerp(start, spot, Math.min(1, run / need));
          if (run > 1.2) k0.push(...legs([lerp(start, curve, Math.min(1, run / need)), to])); else k0.push([t0 + run, to.x, to.y]);
        }
        // off the ball he moves as his kind does (motion: everyone keeps cutting to the basket and back out)
        const how = offT.play === "motion" ? "motion" : styleOf(id).move, every = how === "motion" ? 1.2 : how === "hold" ? 1.0 : 1.6;
        let tt = t0 + run, out = true;
        while (tt + every + 0.4 < t1 - 1.6) {
          tt += every + r() * 1.2;
          if (tt > t1 - 1.6) break;
          const to = offBall(how, spot, right, r, out);
          out = !out;
          k0.push([tt, to.x, to.y]);
        }
        keys[id] = k0;
      });
      // a pick-and-roll (or pop) from the tactics panel: the big comes up to screen for the handler, the handler
      // comes off it downhill, and the screener rolls to the rim (or pops out to the arc)
      let pnr = null;
      if ((offT.play === "pnr" || offT.play === "pop") && firstChance) {
        const rl = offT.roles || {};   // the coach's roles, or the likeliest pair
        const handler = off.includes(rl.handler) ? rl.handler : offT.focus && off.includes(offT.focus) ? offT.focus : off[0];
        const screener = off.includes(rl.screener) && rl.screener !== handler ? rl.screener
          : off.filter((p) => p !== handler).reduce((a, b) => (playerById[b].big > playerById[a].big ? b : a));
        const ts = t0 + travel + 0.8;
        if (ts + 3.4 < t1 - 1.0) {
          const h = track(keys[handler], ts), side = h.y < 25 ? 1 : -1;
          const screen = clampCourt({ x: h.x + (basket.x - h.x) * 0.1, y: h.y + side * 2.8 });
          const downhill = clampCourt(lerp(h, basket, 0.6));
          const away = Math.hypot(screen.x - basket.x, screen.y - basket.y) || 1;
          const finish = offT.play === "pnr" ? clampCourt(lerp(basket, screen, 4 / away))   // rolls to the rim
            : clampCourt(lerp(basket, screen, 23.5 / away));                                  // pops to the arc
          keys[screener] = [...keys[screener].filter((k, j) => j === 0 || k[0] < ts - 1.4), [ts, screen.x, screen.y], [ts + 0.8, screen.x, screen.y],
                            [ts + 2.3, finish.x, finish.y], [ts + 3.4, finish.x, finish.y]];
          keys[handler] = [...keys[handler].filter((k, j) => j === 0 || k[0] < ts - 0.4), [ts, h.x, h.y], [ts + 0.8, h.x, h.y],
                           [ts + 2.1, downhill.x, downhill.y], ...keys[handler].filter((k) => k[0] > ts + 3.6)];
          pnr = { handler, screener, ts };
        }
      }
      // post-up: the entry passer feeds the post. Triangle: the point hits the wing, the wing feeds the post, the weak side cuts.
      const rl2 = offT.roles || {}, fixedPasses = [];
      const iso = offT.play === "iso" && firstChance && off.includes(rl2.scorer) ? rl2.scorer : null;
      if (iso && t0 + travel + 1.4 < t1 - 1.0) fixedPasses.push([iso, t0 + travel + 0.4]);   // isolation: the ball to the scorer, and it stays
      if (offT.play === "post" && firstChance && off.includes(rl2.post)) {
        const ts = t0 + travel + 1.0;
        if (ts + 1 < t1 - 1.0) fixedPasses.push([off.includes(rl2.entry) ? rl2.entry : off[0], ts - 1.2], [rl2.post, ts]);
      }
      if (offT.play === "triangle" && firstChance && ["post", "wing", "point"].every((x) => off.includes(rl2[x]))) {
        const ts = t0 + travel + 1.2;
        if (ts + 3.2 < t1 - 1.0) {
          fixedPasses.push([rl2.point, ts - 1.4], [rl2.wing, ts], [rl2.post, ts + 1.6]);
          if (off.includes(rl2.weak) && keys[rl2.weak]) {
            const home = homeSpot[rl2.weak], cut = clampCourt(lerp(home, basket, 0.8));
            keys[rl2.weak] = [...keys[rl2.weak].filter((k, j) => j === 0 || k[0] < ts + 1.0), [ts + 1.4, home.x, home.y], [ts + 2.6, cut.x, cut.y], [ts + 3.8, home.x, home.y]];
          }
        }
      }
      // a scripted set play (elevator, horns, Spain, floppy, hammer): once all five are set, each role's runs, screens
      // and rolls at their times, then he holds there; and the ball goes to whom the play sends it
      const lay = LAYOUT[offT.play];
      let scriptAt = null;   // when the script started
      if (lay && lay.script && firstChance) {
        const rl = offT.roles || {}, ids = Object.keys(lay.spots).map((role) => rl[role]).filter((id) => off.includes(id) && keys[id]);
        const ts = Math.max(t0 + travel, ...ids.map((id) => arrive[id])) + 0.4;
        const end = Math.max(...lay.script.map((m) => m[0]), ...(lay.passes || []).map((m) => m[0]));
        const pace = Math.min(1, (t1 - 2.0 - ts) / end);   // a short possession runs the play quicker (not under 55% of its time)
        if (pace >= 0.55) {
          for (const role of Object.keys(lay.spots)) {
            const id = rl[role];
            if (!off.includes(id) || !keys[id]) continue;
            const ks = keys[id].filter((k, j) => j === 0 || k[0] < ts - 0.05);
            ks.push([ts, homeSpot[id].x, homeSpot[id].y]);
            let at = homeSpot[id], tt = ts;
            for (const [dt, , dx, dy] of lay.script.filter((m) => m[1] === role).sort((a, b) => a[0] - b[0])) {
              at = clampCourt(toCourt(right, dx, dy)); tt = ts + dt * pace; ks.push([tt, at.x, at.y]);
            }
            while (tt + 2 < t1 - 1.6) { tt += 1.6 + r() * 1.2; const q = clampCourt({ x: at.x + (r() - 0.5) * 3, y: at.y + (r() - 0.5) * 3 }); ks.push([tt, q.x, q.y]); }
            keys[id] = ks;
          }
          for (const [dt, role] of lay.passes || []) if (off.includes(rl[role])) fixedPasses.push([rl[role], ts + dt * (dt > 0 ? pace : 1)]);
          scriptAt = { ts, pace };
        }
      }
      // the player told to attack (or the one the offense runs through) drives at the rim mid-possession
      const told = offT.players || {};
      const driver = [offT.focus, ...Object.keys(told).map(Number).filter((p) => (told[p].aggression || 0) > 0.2 || (told[p].shot_preference && told[p].shot_preference.zone === "rim"))]
        .find((p) => p && off.includes(p)) || ((offT.attack_rim || 0) > 0.2 ? off[0] : null)
        || (!offT.play && r() < 0.7 ? off.filter((p) => styleOf(p).drive).sort((a, b) => playerById[b].usage - playerById[a].usage)[0] || null : null);   // free play: his kind attacks
      if (driver && keys[driver] && !pnr && (!fixedPasses.length || driver === iso)) {
        const td = t0 + travel + Math.max(iso ? 1.4 : 0.3, (t1 - t0 - travel) * 0.3);
        if (td + 1.6 < t1 - 1.6) {
          const lane = clampCourt(toCourt(right, 5 + r() * 3, (r() - 0.5) * 8)), back = homeSpot[driver];
          keys[driver] = [...keys[driver].filter((k) => k[0] < td - 0.6), [td, lane.x, lane.y], [td + 1.4, back.x, back.y], ...keys[driver].filter((k) => k[0] > td + 1.8)];
        }
      }

      // the final action, as the engine says it happened
      const final = { t: t1, kind: resolve ? resolve.kind : "none", shooter: null, passer: null, zone: null, made: false, loser: null, thief: null };
      if (resolve && resolve.kind === "shot") Object.assign(final, { shooter: resolve.actor, passer: resolve.other, zone: resolve.zone, made: resolve.value > 0 });
      if (resolve && resolve.kind === "free_throws") Object.assign(final, { kind: "drive_foul", shooter: resolve.actor, zone: "rim" });
      if (resolve && resolve.kind === "turnover") Object.assign(final, { loser: resolve.actor, thief: resolve.other });
      const target = final.shooter || final.loser;
      if (final.shooter && keys[final.shooter]) {
        const set = track(keys[final.shooter], Math.max(t0, t1 - 1.3));   // where he is when the shot is coming
        const [dx, dy] = shotSpot(final.zone, r, Math.atan2(right ? 25 - set.y : set.y - 25, Math.max(0.5, right ? 88.75 - set.x : set.x - 5.25)));
        const spot = clampCourt(toCourt(right, dx, dy)), ks0 = keys[final.shooter];
        const need = (at) => { const q = track(ks0, at); return (1.5 * Math.hypot(spot.x - q.x, spot.y - q.y)) / VMAX; };
        let leave = Math.max(t0, t1 - 1.6);   // he heads for his shot from wherever he is then, early enough to get there running
        for (let n = 0; n < 2; n++) leave = Math.max(t0, Math.min(leave, t1 - 0.15 - need(leave)));
        const from = track(ks0, leave), before = track(ks0, Math.max(t0, leave - 0.1));
        const moving = Math.hypot(from.x - before.x, from.y - before.y) > 0.3;   // already running: no stop on the way
        const arrive = Math.min(t1 - 0.15, Math.max(t1 - 1.3, leave + need(leave)));
        const ks = ks0.filter((k, j) => j === 0 || k[0] < leave - 0.05);
        if (leave > t0) ks.push([leave, from.x, from.y, moving]);
        ks.push([Math.max(t0 + 0.2, arrive), spot.x, spot.y], [t1, spot.x, spot.y]);
        keys[final.shooter] = ks;
      }
      // on a miss: crashing sends the other four to the rim; "get back" sends them up the floor
      const crash = offT.crash_glass || 0;
      if (final.kind === "shot" && !final.made && Math.abs(crash) > 0.2) {
        for (const id of off) {
          if (id === final.shooter) continue;
          const to = crash > 0 ? clampCourt(toCourt(right, 3 + r() * 5, (r() - 0.5) * 14)) : clampCourt(toCourt(right, 36 + r() * 8, (r() - 0.5) * 24));
          keys[id] = [...keys[id].filter((k) => k[0] < t1 - 0.9), [t1, to.x, to.y]];
        }
      } else if (final.kind === "shot" && !final.made) {   // no call: the ones whose kind crashes the glass go
        for (const id of off) {
          if (id === final.shooter || !styleOf(id).crash) continue;
          const to = clampCourt(toCourt(right, 3 + r() * 5, (r() - 0.5) * 14));
          keys[id] = [...keys[id].filter((k) => k[0] < t1 - 0.9), [t1, to.x, to.y]];
        }
      }

      // the ball: who holds it when, passes in between, and the last touch the engine recorded
      const ball = [];
      let holder = carrier && off.includes(carrier) ? carrier : off[0];
      let tb = t0;
      const pass = (to, when, flight = 0.55) => {
        if (to === holder || when <= tb + 0.2 || when + flight > t1) return;
        ball.push({ hold: holder, from: tb, to: when });
        ball.push({ pass: [holder, to], from: when, to: when + flight });
        holder = to; tb = when + flight;
      };
      if (holder !== off[0] && firstChance && !resumed) pass(off[0], t0 + Math.min(1.2, dur * 0.2));
      const passes = Math.max(0, Math.min(4, Math.round((dur - travel - 2.5) / 4)));
      if (pnr) fixedPasses.push([pnr.handler, pnr.ts - 1.0]);   // he has it for the screen
      const quiet = fixedPasses.length ? [Math.min(...fixedPasses.map((f) => f[1])) - 0.9, iso ? t1 : Math.max(...fixedPasses.map((f) => f[1])) + (pnr ? 3.4 : 1.2)] : null;
      fixedPasses.sort((a, b) => a[1] - b[1]);
      let fi = 0;
      for (let i = 0; i < passes; i++) {
        const when = t0 + travel + (dur - travel - 2.8) * ((i + 0.5 + (r() - 0.5) * 0.4) / passes);
        const choices = off.filter((p) => p !== holder);
        while (fi < fixedPasses.length && fixedPasses[fi][1] <= when) { pass(fixedPasses[fi][0], fixedPasses[fi][1]); fi++; }
        if (quiet && when > quiet[0] && when < quiet[1]) continue;   // the set play's own passes
        pass(driver && driver !== holder && r() < 0.6 ? driver : choices[Math.floor(r() * choices.length)], when);
      }
      while (fi < fixedPasses.length) { pass(fixedPasses[fi][0], fixedPasses[fi][1]); fi++; }
      // The last touches are fixed by the engine. Schedule them backwards from the end of the
      // possession, shortening pass flights when the clock is short, so they always fit.
      const f = Math.max(0.12, Math.min(0.55, (t1 - tb) / 6));
      const forcePass = (to, when) => {
        when = Math.max(when, tb + 0.02);
        ball.push({ hold: holder, from: tb, to: when });
        ball.push({ pass: [holder, to], from: when, to: when + f });
        holder = to; tb = when + f;
      };
      const finale = (receivers, endAt) => {
        let end = endAt - 0.1;
        const plan = [];
        for (let i = receivers.length - 1; i >= 0; i--) { plan.unshift([receivers[i], end - f]); end -= f + 0.12; }
        for (const [to, when] of plan) forcePass(to, when);
      };
      if (final.kind === "shot") {
        const release = t1 - Math.min(0.6, f * 1.2);
        const receivers = [];
        if (final.passer && final.passer !== final.shooter) { if (holder !== final.passer) receivers.push(final.passer); receivers.push(final.shooter); }
        else if (holder !== final.shooter) receivers.push(final.shooter);
        finale(receivers, release);
        ball.push({ hold: holder, from: tb, to: release });
        ball.push({ shot: holder, from: release, to: t1, made: final.made });
      } else if (final.kind === "turnover" && final.loser) {
        const lose = t1 - Math.min(0.5, f);
        if (holder !== final.loser) finale([final.loser], lose);
        ball.push({ hold: holder, from: tb, to: lose });
        if (final.thief) { ball.push({ pass: [holder, final.thief], from: lose, to: t1 }); holder = final.thief; }
        else ball.push({ loose: holder, from: lose, to: t1 });
      } else if (final.kind === "drive_foul") {
        if (holder !== final.shooter) finale([final.shooter], t1 - 0.8);
        ball.push({ hold: holder, from: tb, to: t1 });
      } else {
        ball.push({ hold: holder, from: tb, to: t1 });
      }
      return { keys, homeSpot, pnr, driver, final, ball, scriptAt };
    }
    const { keys, homeSpot, pnr, driver, final, ball, scriptAt } = keep || offense();

    // a double team: the defender whose man stands nearest the doubled player leaves him to help
    const doubled = off.includes(ev.other) && (!resumed || defT.double_team) ? ev.other : null;   // called off in a timeout: no more
    const near = (id) => Math.hypot(homeSpot[id].x - homeSpot[doubled].x, homeSpot[id].y - homeSpot[doubled].y);
    const helper = doubled ? off.map((id, i) => [id, i]).filter(([id]) => id !== doubled).sort((a, b) => near(a[0]) - near(b[0]))[0][1] : -1;
    const plan = { k, s, next, t0, t1, offKey, defKey, right, basket, off, def, keys, ball, final, shootingFoul, doubled, helper, tac, driver, pnr, homeSpot,
      roles: offKey === "home" ? offT.roles : defT.roles, play: offT.play || "free", scheme: defT.scheme || "man", script: scriptAt,
      rebound, ftShooter,
      zone: zoned(defT), hug: (defT.protect_paint || 0) < -0.2,
      box: boxed(defT), chasers: chasersOf(defT, def, off), droles: defT.roles || {},
      star: off.reduce((a, b) => ((playerById[b].usage || 0) > (playerById[a].usage || 0) ? b : a)),   // their main scorer
      dropper: null,   // drop coverage: whoever guards their biggest (set below, once the plan exists)
      pressUntil: pressing(defT) && !resumed ? t0 + Math.max(travel, dur * 0.45) : null };
    plan.zoneSpot = zoneSpots(plan);
    defenseRoles(plan, defT);
    plan.was = {}; plan.blend = {}; plan.arrive = {}; plan.ballFrom = inbound;
    def.forEach((id, i) => {   // defenders run over from where they were, on their own path, at most VMAX
      const was = where[id] || benchSpot(id), at = defenderAt(plan, i, t0 + Math.min(travel, dur * 0.85));
      plan.was[id] = was;
      plan.blend[id] = Math.min(Math.max(1.2, (1.5 * Math.hypot(at.x - was.x, at.y - was.y)) / VMAX), Math.max(1.2, dur * 0.85));
      plan.arrive[id] = defenderAt(plan, i, t0 + plan.blend[id]);   // where he picks up his man
    });

    return plan;
  }

  function buildPlans() {
    const plans = [];
    const where = { ...TIP };    // last known position of every player
    let carrier = null;          // who has the ball when the next possession starts
    let inbound = null;          // after a basket or free throws: where the ball is when the next possession starts
    const chanceAt = G.events.map((e, i) => (e.kind === "chance" ? i : -1)).filter((i) => i >= 0);
    chanceAt.forEach((s, k) => {
      const ev = G.events[s], next = k + 1 < chanceAt.length ? chanceAt[k + 1] : G.events.length;
      const floor = [...ev.home_lineup, ...ev.away_lineup];
      for (const id of Object.keys(where).map(Number)) if (!floor.includes(id)) delete where[id];   // went to the bench: comes back from it
      // the calls in force (engine's chance event): the figures act them out on every possession,
      // while the outcome stays the one the engine rolled
      // (a tactic changed in a timeout earlier in this possession plays on in its later chances, which the engine had
      // already played with the old one: an offensive rebound's second chance)
      const carried = restarts.filter((x) => x.s < s && s < x.events && x.at <= ev.t).pop();
      const tac = carried ? withShape(ev.tactics || null, ev, carried.tactic) : ev.tactics || null;
      let plan = planSegment({ k, s, next, ev, start: ev.t, where, carrier, inbound, tac, r: seeded(k + 1), picked: carried ? carried.tactic.picked : picksFor(s) });
      plans.push(plan);
      // A tactic changed in a timeout during this possession: from that moment the coach's five play it, moving
      // into it at running speed once play resumes; the other team only reacts on the court
      restarts.filter((x) => x.s === s && x.at > plan.t0 + 0.05 && x.at < plan.t1 - 1).sort((a, b) => a.at - b.at).forEach((x, j) => {
        const ours = plan.offKey === "home" ? "off" : "def";
        plan = planSegment({ k, s, next, ev, start: x.at, where: positionsIn(plan, x.at), carrier: holderAt(plan, x.at), inbound: null,
                             tac: withShape(ev.tactics || null, ev, x.tactic), r: seeded((k + 1) * 97 + j), keep: ours === "def" ? plan : null,
                             picked: x.tactic.picked });
        plans.push(plan);
      });

      // where everyone ends up (the next possession starts exactly there, as it was last drawn), and the ball
      const { off, def, final, rebound, ftShooter, basket, right, t1 } = plan, r = seeded(k + 7);
      if (rebound && rebound.actor) {   // off a free throw he was already on the lane
        Object.assign(plan, { rebounder: rebound.actor, reboundT: rebound.t,
                              reboundSpot: ftShooter ? freeThrowFormation(plan, ftShooter)[rebound.actor]
                                : clampCourt({ x: basket.x + (right ? -4 : 4) * r(), y: basket.y + (r() - 0.5) * 8 }) });
        carrier = rebound.actor;
      } else if (final.kind === "turnover" && final.thief) {
        carrier = final.thief;
      } else {
        carrier = null; // inbound after a make, free throws or a dead ball
      }
      const end = positionsIn(plan, t1);
      Object.assign(where, end);
      if (ftShooter) Object.assign(where, freeThrowFormation(plan, ftShooter));   // they walked to the line (deadBall)
      plan.endAt = Object.fromEntries([...off, ...def].map((id) => [id, where[id]]));
      const ball = ballAt(t1 + 1e-6, plan, end);
      inbound = { x: ball.x, y: ball.y };   // in the net or off the rim, out of bounds, or in the hands of whoever had it
    });
    return plans;
  }
  function zoneSlide(plan, t) {   // a zone moves as one toward the side of the floor the ball is on
    const at = (id) => (plan.keys[id] ? track(plan.keys[id], t - 0.3) : plan.basket);
    let y = plan.basket.y;
    for (const seg of plan.ball) {
      if (t < seg.from || t > seg.to) continue;
      if (seg.hold !== undefined) y = at(seg.hold).y;
      else if (seg.pass) y = lerp(at(seg.pass[0]), at(seg.pass[1]), (t - seg.from) / Math.max(0.01, seg.to - seg.from)).y;
      else if (seg.shot !== undefined) y = at(seg.shot).y;
      else if (seg.loose !== undefined) y = at(seg.loose).y;
      break;
    }
    return Math.max(-7, Math.min(7, (y - 25) * 0.35));
  }
  function markOf(plan, i) {   // the man this defender guards: the coach's matchup ("on:<id>"), else the same place in their five
    const me = plan.def[i];
    for (const [r, id] of Object.entries(plan.droles || {})) if (id === me && r.startsWith("on:") && plan.off.includes(Number(r.slice(3)))) return Number(r.slice(3));
    return plan.off[i];
  }
  const PRESS_RELEASE = 1.5;   // game seconds to drop back from the press into the half-court defense
  function pressAt(plan, i, t) {   // pressure: picked up full court, two on the ball handler
    const target = i === 1 ? plan.off[0] : markOf(plan, i);
    if (!target || !plan.keys[target]) return null;
    const o = track(plan.keys[target], t - 0.2), b = plan.basket;
    return clampCourt({ x: o.x + (b.x - o.x) * 0.06, y: o.y + (b.y - o.y) * 0.06 + (i === 1 ? 1.8 : 0) });
  }
  function defenderAt(plan, i, t) {
    if (i === plan.helper) {   // the second defender on a doubled player, on the other shoulder
      const o = track(plan.keys[plan.doubled], t - 0.3), b = plan.basket;
      return clampCourt({ x: o.x + (b.x - o.x) * 0.22, y: o.y + (b.y - o.y) * 0.22 - 1.6 });
    }
    if (plan.pressUntil && t < plan.pressUntil) { const p = pressAt(plan, i, t); if (p) return p; }
    const p = settledAt(plan, i, t);
    if (plan.pressUntil && t < plan.pressUntil + PRESS_RELEASE) {   // the press is over: he runs back to his spot, not a jump
      const q = pressAt(plan, i, plan.pressUntil);
      if (q) return lerp(q, p, ease((t - plan.pressUntil) / PRESS_RELEASE));
    }
    return p;
  }
  function settledAt(plan, i, t) {   // the half-court defense: a zone, a box-and-one, or man to man
    if (plan.box) {   // box-and-one, triangle-and-two: the chasers on their scorers wherever they go, the others in their zone
      const chase = plan.chasers.find(([d]) => d === plan.def[i]);
      if (chase && plan.keys[chase[1]]) {
        const o = track(plan.keys[chase[1]], t - 0.25), b = plan.basket;
        return clampCourt({ x: o.x + (b.x - o.x) * 0.08, y: o.y + (b.y - o.y) * 0.08 + 0.8 });
      }
      const z = (plan.zoneSpot || {})[plan.def[i]] || [8, 0], spot = toCourt(plan.right, z[0], z[1]);
      return clampCourt({ x: spot.x, y: spot.y + zoneSlide(plan, t) });
    }
    if (plan.zone) {   // a 2-3 zone: two up top, three low, the five sliding together toward the ball
      const z = (plan.zoneSpot || {})[plan.def[i]] || [8, 0], spot = toCourt(plan.right, z[0], z[1]);
      return clampCourt({ x: spot.x, y: spot.y + zoneSlide(plan, t) });
    }
    const mark = markOf(plan, i);
    if (!mark || !plan.keys[mark]) return plan.basket;
    const o = track(plan.keys[mark], t - 0.45);
    const b = plan.basket, gap = plan.dropper === plan.def[i] ? 0.62 : plan.hug ? 0.12 : styleOf(plan.def[i]).gap;   // drop: the big sags; else as his kind does
    return clampCourt({ x: o.x + (b.x - o.x) * gap, y: o.y + (b.y - o.y) * gap + 1.2 });
  }
  let plans = [], startOf = [];   // rebuilt whenever the game's events or the coach's tactic change
  function rebuild() { plans = buildPlans(); startOf = plans.map((p) => p.t0); }
  function planIndex(t) {
    let lo = 0, hi = plans.length - 1, ans = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (startOf[m] <= t) { ans = m; lo = m + 1; } else hi = m - 1; }
    return ans;
  }
  function planAt(t) { const i = planIndex(t); return i >= 0 ? plans[i] : null; }
  function planShown(t, applied) {   // the court: the next possession only once its chance is shown (applied: events shown)
    let i = planIndex(t);
    while (i > 0 && plans[i].s >= applied) i--;
    return i >= 0 ? plans[i] : null;
  }
  function positionsAt(t, plan = planAt(t)) {
    if (!plan) {   // before the opening tip: line up around the centre circle
      const pos = {}, ids = [...(G.events[0].home_lineup || []), ...(G.events[0].away_lineup || [])];
      ids.forEach((id, i) => { const a = (i / ids.length) * Math.PI * 2; pos[id] = { x: 47 + Math.cos(a) * 8, y: 25 + Math.sin(a) * 8 }; });
      return { pos, plan: null };
    }
    return { pos: positionsIn(plan, t), plan };
  }
  function holderAt(plan, t) {   // who has the ball at t (a pass in the air: whoever it's going to)
    for (const seg of plan.ball) if (t >= seg.from && t <= seg.to) return seg.hold ?? (seg.pass ? seg.pass[1] : null);
    return null;
  }
  function positionsIn(plan, t) {   // everyone's spot at time t in this plan
    const pos = {};
    plan.off.forEach((id) => { pos[id] = track(plan.keys[id], t); });
    plan.def.forEach((id, i) => {
      let p = defenderAt(plan, i, t);
      const blend = plan.blend[id];
      if (t < plan.t0 + blend) {   // running back from where he was: across to his man's side of the floor first, then up it
        const u = Math.max(0, (t - plan.t0) / blend), was = plan.was[id], to = plan.arrive[id];
        p = { x: was.x + (to.x - was.x) * ease(u), y: was.y + (to.y - was.y) * (1 - (1 - u) ** 2) };
      }
      pos[id] = p;
    });
    const up = plan.rebounder && !plan.ftShooter ? Math.max(plan.t0, plan.reboundT - 0.8) : Infinity;
    if (pos[plan.rebounder] && t > up) {   // he goes up for the rebound as the ball comes off, within his possession
      pos[plan.rebounder] = lerp(pos[plan.rebounder], plan.reboundSpot, ease(Math.min(1, (t - up) / Math.max(0.05, plan.reboundT - up))));
    }
    return pos;
  }
  function ballAt(t, plan, pos) {
    if (!plan) return { x: 47, y: 25, holder: null };
    const pick = plan.ball.length && plan.ball[0].hold !== undefined ? Math.min(0.7, plan.ball[0].to - plan.t0) : 0;
    if (plan.ballFrom && t < plan.t0 + pick) {   // picked up where the last possession left it, before his first pass
      const h = pos[plan.ball[0].hold] || plan.basket, p = lerp(plan.ballFrom, { x: h.x + 0.6, y: h.y - 1.4 }, ease(Math.max(0, (t - plan.t0) / pick)));
      return { x: p.x, y: p.y, holder: null };
    }
    for (const seg of plan.ball) {
      if (t < seg.from || t > seg.to) continue;
      const u = seg.to > seg.from ? (t - seg.from) / (seg.to - seg.from) : 1;
      if (seg.hold !== undefined) { const p = pos[seg.hold] || plan.basket; return { x: p.x + 0.6, y: p.y - 1.4 + Math.abs(Math.sin(t * 7)) * 0.9, holder: seg.hold }; }
      if (seg.pass) { const a = pos[seg.pass[0]] || plan.basket, b = pos[seg.pass[1]] || plan.basket; const p = lerp(a, b, u); return { x: p.x, y: p.y - 1.4 - Math.sin(Math.PI * u) * 1.8, holder: null }; }
      if (seg.shot !== undefined) { const a = pos[seg.shot] || plan.basket; const p = lerp(a, plan.basket, ease(u)); return { x: p.x, y: p.y - 1.4 - Math.sin(Math.PI * u) * 5, holder: null }; }
      if (seg.loose !== undefined) { const a = pos[seg.loose] || plan.basket; const out = { x: a.x, y: a.y < 25 ? 0.5 : 49.5 }; const p = lerp(a, out, u); return { x: p.x, y: p.y - 1.4, holder: null }; }
    }
    const last = plan.ball[plan.ball.length - 1];   // after the last touch: where it ended
    if (!last) { const h = plan.off[0], p = pos[h] || plan.basket; return { x: p.x + 0.6, y: p.y - 1.4, holder: h }; }
    if (plan.ftShooter || last.shot !== undefined) return { x: plan.basket.x, y: plan.basket.y - 1.4, holder: null };   // a shot or the free throws: at the rim
    if (last.loose !== undefined) { const a = pos[last.loose] || plan.basket; return { x: a.x, y: (a.y < 25 ? 0.5 : 49.5) - 1.4, holder: null }; }   // out of bounds
    const h = last.pass ? last.pass[1] : last.hold, p = pos[h] || plan.basket;
    return { x: p.x + 0.6, y: p.y - 1.4, holder: h };
  }
  // A shooting foul stops the clock: everyone walks from where the play left them to the free-throw line-up (in real
  // time, while the dead ball holds), the shooter with the ball; then the free throw goes up to the rim.
  function freeThrowFormation(plan, shooter) {
    const pos = {};
    const others = [...plan.off.filter((p) => p !== shooter), ...plan.def];
    pos[shooter] = toCourt(plan.right, 15, 0);
    others.forEach((id, i) => { const [dx, dy] = LANE[i] || [26, 0]; pos[id] = toCourt(plan.right, dx, dy); });
    return pos;
  }

  const SPACING = [["point", "Point"], ["lwing", "Left wing"], ["rwing", "Right wing"], ["corner", "Corner"], ["dunker", "Dunker spot"]];
  const PLAYS = {
    free: { name: "Free offense", say: "No set play: the five space the floor and read the defense.", roles: SPACING, main: [] },
    pnr: { name: "Pick-and-roll", say: "{handler} brings it up; {screener} comes up to screen for him, then rolls to the rim. The other three space the floor.",
           roles: [["handler", "Ball handler"], ["screener", "Screener"], ["lwing", "Left wing"], ["rwing", "Right wing"], ["corner", "Corner"]],
           main: ["handler", "screener"], team: { attack_rim: 0.4 }, focus: "handler", prefer: { screener: ["rim", 0.5] } },
    pop: { name: "Pick-and-pop", say: "{handler} comes off {screener}'s screen; {screener} pops out to the three-point line for the shot.",
           roles: [["handler", "Ball handler"], ["screener", "Screener"], ["lwing", "Left wing"], ["rwing", "Right wing"], ["corner", "Corner"]],
           main: ["handler", "screener"], team: { three_point_rate: 0.3 }, focus: "handler", prefer: { screener: ["three", 0.5] } },
    iso: { name: "Isolation", say: "{scorer} takes his man one-on-one on the wing; the other four clear out to the far side.",
           roles: [["scorer", "Scorer"], ["top", "Top"], ["lwing", "Far wing"], ["corner", "Far corner"], ["dunker", "Dunker spot"]], main: ["scorer"], focus: "scorer" },
    post: { name: "Post-up", say: "{entry} feeds {post} on the block; the others space out on the far side.",
            roles: [["post", "Post player"], ["entry", "Entry passer"], ["top", "Top"], ["lwing", "Far wing"], ["corner", "Far corner"]],
            main: ["post", "entry"], team: { attack_rim: 0.5, pace: -0.3 }, focus: "post", prefer: { post: ["rim", 0.5] } },
    triangle: { name: "Triangle", say: "{post} on the block, {wing} on the wing and {corner} in the corner make the triangle on one side; {point} sits at the top and {weak} cuts from the weak side.",
                roles: [["post", "Post"], ["wing", "Wing"], ["corner", "Corner"], ["point", "Point"], ["weak", "Weak side"]],
                main: ["post", "wing", "corner", "point", "weak"], team: { attack_rim: 0.2, pace: -0.2 }, prefer: { post: ["rim", 0.3] } },
    five_out: { name: "Five-out", say: "All five outside the arc: drive and kick.", main: [], team: { three_point_rate: 0.6 },
                roles: [["point", "Top"], ["lwing", "Left wing"], ["rwing", "Right wing"], ["lcorner", "Left corner"], ["rcorner", "Right corner"]] },
    motion: { name: "Motion", say: "Keep cutting and passing until someone is open.", roles: SPACING, main: [] },
    elevator: { name: "Elevator screen", say: "{shooter} runs up the lane between {doorl} and {doorr}; the doors shut behind him and he catches at the top for a three.",
                roles: [["shooter", "Shooter"], ["doorl", "Left door"], ["doorr", "Right door"], ["passer", "Passer"], ["corner", "Corner"]],
                main: ["shooter", "doorl", "doorr", "passer"], team: { three_point_rate: 0.3 }, focus: "shooter", prefer: { shooter: ["three", 0.6] } },
    horns: { name: "Horns", say: "Two bigs at the elbows: {elbowl} comes up to screen for {handler} and rolls; {elbowr} pops out for a jumper.",
             roles: [["handler", "Ball handler"], ["elbowl", "Left elbow (screens, rolls)"], ["elbowr", "Right elbow (pops)"], ["lcorner", "Left corner"], ["rcorner", "Right corner"]],
             main: ["handler", "elbowl", "elbowr"], team: { attack_rim: 0.3 }, focus: "handler", prefer: { elbowl: ["rim", 0.4] } },
    spain: { name: "Spain pick-and-roll", say: "{screener} screens for {handler} and rolls; {backscreen} back-screens the roller's man, then pops to the top for three.",
             roles: [["handler", "Ball handler"], ["screener", "Screener (rolls)"], ["backscreen", "Back-screener (pops)"], ["lwing", "Left wing"], ["rcorner", "Right corner"]],
             main: ["handler", "screener", "backscreen"], team: { attack_rim: 0.3 }, focus: "handler", prefer: { screener: ["rim", 0.4], backscreen: ["three", 0.5] } },
    floppy: { name: "Floppy", say: "{shooter} starts under the basket and comes off {stagger1} and {stagger2}'s staggered screens to the wing; {single} screens the other side.",
              roles: [["shooter", "Shooter"], ["single", "Single screen"], ["stagger1", "Low stagger"], ["stagger2", "High stagger"], ["handler", "Ball handler"]],
              main: ["shooter", "stagger1", "stagger2", "single"], team: { three_point_rate: 0.3 }, focus: "shooter", prefer: { shooter: ["three", 0.5] } },
    hammer: { name: "Hammer", say: "{driver} drives the baseline; {hammer} screens {shooter}'s man, {big} clears the lane and {shooter} drifts to the corner for the kick-out three.",
              roles: [["driver", "Baseline driver"], ["shooter", "Corner shooter"], ["hammer", "Hammer screener"], ["big", "Big"], ["top", "Top"]],
              main: ["driver", "shooter", "hammer", "big"], team: { attack_rim: 0.2, three_point_rate: 0.2 }, focus: "driver", prefer: { shooter: ["three", 0.6] } },
  };
  const SCHEMES = {   // matchups: each defender's role is his man
    man: { name: "Man to man", say: "Each defender guards his man. No double teams.", matchups: true, main: [] },
    switch: { name: "Switch everything", say: "Each defender starts on his man and swaps men on every screen.", matchups: true, main: [] },
    drop: { name: "Drop coverage", say: "Man to man; the big on their big stays back near the rim on screens.", matchups: true, main: [], team: { protect_paint: 0.4 } },
    blitz: { name: "Blitz the ball", say: "Man to man; two defenders jump the ball handler on every screen.", matchups: true, main: [], team: { pressure: 0.5 } },
    zone23: { name: "2-3 zone", say: "Two up top, three across the paint: each defender guards an area, not a man.", main: [], team: { protect_paint: 0.7 },
              roles: [["topl", "Top left"], ["topr", "Top right"], ["wingl", "Left wing"], ["wingr", "Right wing"], ["middle", "Middle"]] },
    press: { name: "Full-court press", say: "Each defender picks up his man the length of the floor.", matchups: true, main: [], team: { pressure: 0.8 } },
    box1: { name: "Box-and-one", say: "{chaser} chases their main scorer everywhere; the other four play a box around the paint.", main: ["chaser"],
            roles: [["chaser", "Chaser"], ["boxtl", "Box top left"], ["boxtr", "Box top right"], ["boxll", "Box low left"], ["boxlr", "Box low right"]],
            team: { protect_paint: 0.5 }, pressers: ["chaser"] },
    zone131: { name: "1-3-1 zone", say: "{trap} traps at the top, {middle} holds the middle between two wings, {rover} covers the whole baseline.",
               roles: [["trap", "Top (traps)"], ["wingl", "Left wing"], ["middle", "Middle"], ["wingr", "Right wing"], ["rover", "Baseline rover"]],
               main: ["trap", "middle", "rover"], team: { protect_paint: 0.3, pressure: 0.35 } },
    tri2: { name: "Triangle-and-two", say: "{chaser} and {chaser2} chase their two main scorers everywhere; the other three play a triangle in the paint.",
            roles: [["chaser", "Chaser on their 1st scorer"], ["chaser2", "Chaser on their 2nd scorer"], ["tritop", "Triangle top"], ["tril", "Triangle low left"], ["trir", "Triangle low right"]],
            main: ["chaser", "chaser2"], team: { protect_paint: 0.4 }, pressers: ["chaser", "chaser2"] },
  };
  const tactic = { play: "free", scheme: "man", roles: {}, picked: {} };   // picked: the roles the coach chose himself
  function guessOrder(role, ids, theirs) {   // who suits a role best, most likely first
    const [handler, w1, w2, w3, big] = roles(ids);
    if (role.startsWith("on:")) {   // a matchup: the man at the same place in their five (point on point, big on big)
      const k = roles(theirs).indexOf(Number(role.slice(3)));
      return [roles(ids)[k]];
    }
    if (role === "chaser" || role === "chaser2") return [...ids].sort((a, b) => playerById[b].steal * 10 - styleOf(b).gap - (playerById[a].steal * 10 - styleOf(a).gap));
    const kind = ROLE_KIND[role] ?? WING;
    return [...ids].sort((a, b) => fitScore(b, kind) - fitScore(a, kind));   // the best fit for the role, by archetype
  }
  // the kind of player each role wants: [handle, wing, spot up, inside, score]
  const ROLE_KIND = { point: HANDLE, handler: HANDLE, top: HANDLE, entry: HANDLE, scorer: SCORE, wing: WING, weak: WING, lwing: WING, rwing: WING,
    corner: SHOOT, lcorner: SHOOT, rcorner: SHOOT, dunker: BIG, screener: BIG, post: BIG,
    topl: HANDLE, topr: WING, wingl: WING, wingr: WING, middle: BIG, boxtl: HANDLE, boxtr: WING, boxll: BIG, boxlr: BIG,
    shooter: SHOOT, doorl: BIG, doorr: BIG, passer: HANDLE, elbowl: BIG, elbowr: BIG, backscreen: SHOOT, single: BIG, stagger1: BIG, stagger2: WING,
    driver: SCORE, hammer: WING, big: BIG, trap: HANDLE, rover: WING, tritop: WING, tril: BIG, trir: BIG };
  const KIND_ORDER = [BIG, HANDLE, SCORE, SHOOT, WING];   // filled first: the scarce kinds
  // Every player on the floor has a role in a tactic: the coach's choice while he's on the floor, else the best fit
  // (a substitute takes over the role of the man he replaced). The rows, the helper and the court all use this.
  function completeRoles(t, given, ids, theirs) {
    const want = t.matchups ? roles(theirs).map((id) => `on:${id}`) : t.roles.map(([r]) => r), out = {}, taken = new Set();
    for (const r of want) { const id = given[r]; if (ids.includes(id) && !taken.has(id)) { out[r] = id; taken.add(id); } }
    const order = t.matchups ? want : [...want].sort((a, b) => KIND_ORDER.indexOf(ROLE_KIND[a] ?? WING) - KIND_ORDER.indexOf(ROLE_KIND[b] ?? WING));
    for (const r of order) if (!out[r]) { const id = [...guessOrder(r, ids, theirs), ...ids].find((p) => p && !taken.has(p)); if (id) { out[r] = id; taken.add(id); } }
    return out;
  }

  const V = 1;   // a call gives its lever's direction; the engine moves the lever one step that way (levers.STEP)
  const STEP = 0.35;   // the same as levers.STEP: three of the same call reach the limit
  const TEAM_CALLS = [   // [when it's offered, what the coach says, the levers]
    ["offense", "Push the pace", { team: { pace: V } }],
    ["offense", "Slow it down, use the clock", { team: { pace: -V } }],
    ["offense", "Let it fly from three", { team: { three_point_rate: V } }],
    ["offense", "Attack the rim", { team: { attack_rim: V } }],
    ["offense", "Take care of the ball", { team: { ball_security: V } }],
    ["offense", "Crash the offensive glass", { team: { crash_glass: V } }],
    ["offense", "Get back after every shot", { team: { crash_glass: -V } }],
    ["defense", "Sit back, no gambling", { team: { pressure: -V } }],
    ["defense", "Run them off the three-point line", { team: { protect_paint: -V } }],
    ["defense", "No fouls, hands back", { team: { foul_caution: V } }],
    ["defense", "Get physical", { team: { foul_caution: -V } }],
    ["defense", "Foul when we're down late", { late_foul: true }],
    ["any", "Great job, everybody!", { team_confidence: 0.5 }],
  ];
  const PLAYER_CALLS = [   // the same for one player; the row adds who
    ["offense", "Be aggressive, look for your shot", { aggression: V }],
    ["offense", "Move the ball, find the open man", { aggression: -V }],
    ["offense", "Get to the rim", { shot_preference: { zone: "rim", value: V } }],
    ["offense", "Hunt your midrange", { shot_preference: { zone: "mid", value: V } }],
    ["offense", "Spot up for threes", { shot_preference: { zone: "three", value: V } }],
    ["defense", "Pressure your man", { pressure: V }],
    ["defense", "Play off your man", { pressure: -V }],
    ["defense", "Protect the rim", { protect_paint: V }],
    ["defense", "Stay home on your shooter", { protect_paint: -V }],
    ["defense", "Box out, finish the play", { box_out: V }],
    ["defense", "Leak out for the break", { box_out: -V }],
    ["defense", "Stay out of foul trouble", { foul_caution: V }],
    ["defense", "Be physical with your man", { foul_caution: -V }],
    ["any", "Take a breather (3 min)", { rest_minutes: 3 }],
    ["any", "Great job, keep it up!", { confidence: 0.5 }],
  ];
  function fights(raw, c) {
    if (Object.keys(raw.team || {}).some((k) => c.team.has(k))) return true;
    for (const entry of raw.players || []) for (const k of Object.keys(entry)) {
      if (k === "person_id") continue;
      if (c.team.has(k)) return true;   // one player's pressure or paint adds to the team's, which the tactic sets
      if (c.players[entry.person_id] && c.players[entry.person_id].has(k)) return true;   // his role already says it
      if (k === "aggression" && c.focus === entry.person_id) return true;   // the play already runs through him
    }
    return raw.focus !== undefined && c.focus !== null;   // the play decides who it runs through
  }

  // What the tactic already decides at this end of the floor (t: the play or the defense, r: the roles): a call about
  // the same thing would fight it, so the lists leave it out.
  function controlsOf(t, r) {
    const players = {}, mark = (pid, lever) => { if (pid) (players[pid] ||= new Set()).add(lever); };
    const focus = t.focus ? r[t.focus] : null;
    for (const role of Object.keys(t.prefer || {})) mark(r[role], "shot_preference");
    for (const role of t.pressers || []) mark(r[role], "pressure");
    return { team: new Set(Object.keys(t.team || {})), players, focus };
  }
  // The calls the coach can make now: to the team (who: "team") or one player (his id), at this end of the floor, less
  // those the tactic decides (c: controlsOf). floor, theirs: the two fives on the floor.
  function callList(phase, who, floor, theirs, c) {
    const list = [], add = (when, label, raw) => { if ((when === phase || when === "any") && !fights(raw, c)) list.push({ when, label, raw }); };
    if (who === "team") {
      for (const [when, label, raw] of TEAM_CALLS) add(when, label, raw);
      for (const id of floor) add("offense", `Run it through ${last(playerById[id].name)}`, { focus: id });
      for (const id of theirs) add("defense", `Double-team ${last(playerById[id].name)}`, { double_team: id });
    } else {
      for (const [when, label, raw] of PLAYER_CALLS) add(when, label, { players: [{ person_id: who, ...raw }] });
      add("offense", "We're running it through you", { focus: who });
    }
    return list;
  }

  return { playerById, last, rebuild, plans: () => plans, controlsOf, callList,
    attacksRight, toCourt, basketOf, SPOTS, STYLE, styleOf, HANDLE, WING, SHOOT, BIG, SCORE, fitScore, offBall, LAYOUT, MAN_SPOTS, restarts, pickLog, picksFor, withPicks, withShape, playSpots, spotOf, pressing, zoned, boxed, chasersOf, zoneSpots, defenseRoles, LANE, seeded, roles, shotSpot, ease, lerp, clampCourt, track, RESOLVE, VMAX, benchSpot, TIP, planSegment, buildPlans, zoneSlide, markOf, PRESS_RELEASE, pressAt, defenderAt, settledAt, planIndex, planAt, planShown, positionsAt, holderAt, positionsIn, ballAt, freeThrowFormation, SPACING, PLAYS, SCHEMES, tactic, guessOrder, ROLE_KIND, KIND_ORDER, completeRoles, V, STEP, TEAM_CALLS, PLAYER_CALLS, fights };
  }

  return { createCourt };
});
