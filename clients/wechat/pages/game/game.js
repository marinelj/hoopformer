// The game page: the court (a canvas), the scoreboard, the Timeout button and the coaching rows, in a compact layout
// that turns with the phone (portrait: the court on top; landscape: the court on the left, the coaching on the right).
// The engine plays on the server; where everyone stands comes from the shared rules (core/court.js), so this page
// shows the same game the same way as the web page.
const core = require("../../core/court.js");
const config = require("../../config.js");
const { request } = require("../../utils/api.js");
const { freshState, apply } = require("../../utils/state.js");
const draw = require("../../utils/draw.js");

const SPEED = 0.8;   // game seconds per real second, as on the web

function ink(hex) {   // dark text on a light team colour, white on a dark one
  const n = parseInt(hex.replace("#", ""), 16), r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  return 0.299 * r + 0.587 * g + 0.114 * b > 165 ? "#111111" : "#ffffff";
}
const initials = (name) => name.split(" ").filter((w) => !/^(Jr\.|Sr\.|II|III|IV)$/.test(w)).map((w) => w[0]).join("").slice(0, 3).toUpperCase();

Page({
  data: {
    ready: false, error: "", landscape: false, courtW: 300, courtH: 160, panelW: 0,
    board: { awayCode: "", homeCode: "", awayPts: 0, homePts: 0, awayColor: "#555", homeColor: "#555" },
    period: "1ST", clock: "12:00", shot: 24, playLabel: "▶ Tip-off", timeoutDisabled: false, inTimeout: false,
    phaseLabel: "", strip: "", tab: "coach", tactics: [], tacticIndex: 0, locked: false, teamCalls: [], rows: [],
    helper: { name: "", say: "" }, feed: [], banner: "", callout: { show: false, big: "", small: "", kind: "" },
  },

  onLoad() {
    this.frame = this.frame.bind(this);
    this.start().catch((err) => this.setData({ error: `${err.message}. Is hoopformer serve running at ${config.SERVER}?` }));
  },
  onResize() { if (this.G) this.layout(); },   // the phone turned
  onUnload() { this.running = false; },

  async start() {
    const query = [config.HOME && `home=${config.HOME}`, config.AWAY && `away=${config.AWAY}`].filter(Boolean).join("&");
    const G = (this.G = await request(`/api/new${query ? `?${query}` : ""}`));
    this.rules = core.createCourt(G);
    this.rules.rebuild();
    this.S = freshState();
    this.T = 0; this.played = 0; this.hold = 0; this.playing = false; this.started = false; this.inTimeout = false;
    this.shown = {}; this.lastBall = null; this.walk = null; this.fetching = false; this.selected = null; this.keys = {};
    while (this.S.applied < G.events.length && G.events[this.S.applied].t <= 0.1) apply(this.S, G, G.events[this.S.applied]);
    this.T = 0.1;
    const team = (key) => ({ primary: G[key].primary, secondary: G[key].secondary, ink: ink(G[key].primary) });
    this.colors = { away: G.away.primary, home: G.home.primary, awayTeam: team("away"), homeTeam: team("home") };
    if (config.VOICE) this.recognizer = requirePlugin("WechatSI").getRecordRecognitionManager();
    this.whistleSound = wx.createInnerAudioContext();
    this.whistleSound.src = "/assets/whistle.wav";
    this.setData({ ready: true, board: { awayCode: G.away.tricode, homeCode: G.home.tricode, awayPts: 0, homePts: 0,
                                         awayColor: G.away.primary, homeColor: G.home.primary } });
    this.layout();
    this.refresh(true);
  },

  // ---------- layout: the court as large as the screen allows, in either orientation ----------
  layout() {
    const win = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
    const landscape = win.windowWidth > win.windowHeight;
    let courtW, panelW = 0;
    if (landscape) {   // the court on the left under the scoreboard, the coaching column on the right
      const high = win.windowHeight - 34 - 26 - 12;   // less the scoreboard, the strip and the margins
      courtW = Math.floor(Math.min(win.windowWidth * 0.62, (high * 94) / 50));
      panelW = win.windowWidth - courtW - 18;
    } else {
      courtW = win.windowWidth - 12;
    }
    this.setData({ landscape, courtW, courtH: Math.round((courtW * 50) / 94), panelW }, () => this.setupCanvas());
  },
  setupCanvas() {
    wx.createSelectorQuery().select("#court").fields({ node: true, size: true }).exec((res) => {
      if (!res || !res[0] || !res[0].node) return;
      const canvas = res[0].node, dpr = (wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync()).pixelRatio;
      canvas.width = res[0].width * dpr; canvas.height = res[0].height * dpr;
      this.ctx = canvas.getContext("2d");
      this.ctx.scale(dpr, dpr);
      this.canvas = canvas; this.cw = res[0].width;
      if (!this.running) { this.running = true; this.lastFrame = null; canvas.requestAnimationFrame(this.frame); }
    });
  },

  // ---------- playback: the same timing as the web page ----------
  frame(now) {
    if (!this.running) return;
    const dt = this.lastFrame == null ? 0 : Math.min(0.1, (now - this.lastFrame) / 1000);
    this.lastFrame = now;
    if (this.playing) this.advance(dt);
    this.drawCourt();
    this.ticks = (this.ticks || 0) + 1;
    if (this.ticks % 6 === 0) this.refresh(false);   // the text around the court, ten times a second
    this.canvas.requestAnimationFrame(this.frame);
  },
  totalT() { return 4 * this.rules.PERIOD + Math.max(0, this.G.periods - 4) * this.rules.OT; },
  bufferEnd() { const ev = this.G.events; return this.G.done ? this.totalT() : ev.length ? ev[ev.length - 1].t : 0; },
  advance(dt) {
    this.played += dt;
    if (this.hold > 0) { this.hold -= dt; return; }
    const G = this.G, S = this.S, next = G.events[S.applied], target = Math.min(this.bufferEnd(), this.T + dt * SPEED);
    if (next && next.t <= target) {
      this.T = next.t;
      apply(S, G, next);
      this.hold = next.kind === "chance" ? 0 : 0.45;   // a beat on every whistle
      if (next.kind === "timeout" && next.zone !== "coach") { this.hold = 1.4; this.showBanner(`TIMEOUT · ${next.team}`, 1600); }
      const fouled = S.dead && (next.kind === "foul" || next.kind === "free_throws") && this.rules.planAt(this.T - 1e-6);
      if (fouled) {   // the dead ball lasts until they're on the line, and the free throw is up
        this.deadBall(fouled);
        this.hold = Math.max(this.hold, this.walk.at + this.walk.dur - this.played + (next.kind === "free_throws" ? 0.7 : 0.15));
      }
    } else this.T = target;
    if (!G.done && S.applied >= G.events.length) this.fetchNext();
    if (G.done && this.T >= this.totalT() && S.applied >= G.events.length) this.setPlaying(false);
  },
  // A shooting foul: everyone walks from where the play left them to the free-throw line-up, the shooter with the
  // ball; then the free throw goes up to the rim. (As on the web page.)
  deadBall(plan) {
    const S = this.S, key = `${plan.t1}/${S.dead.shooter}`, to = this.rules.freeThrowFormation(plan, S.dead.shooter), now = this.played;
    if (!this.walk || this.walk.key !== key) {
      const from = {}; let far = 0;
      for (const id in to) { from[id] = this.shown[id] || to[id]; far = Math.max(far, Math.hypot(to[id].x - from[id].x, to[id].y - from[id].y)); }
      this.walk = { key, from, to, dur: Math.min(2.2, Math.max(0.8, far / 15)), at: now, shotAt: null, ball: this.lastBall };
    }
    const w = this.walk, u = Math.min(1, (now - w.at) / w.dur), ease = this.rules.ease, pos = {};
    for (const id in to) pos[id] = this.rules.lerp(w.from[id], to[id], ease(u));
    const h = pos[S.dead.shooter], hand = { x: h.x + 0.6, y: h.y - 1.4, holder: S.dead.shooter };
    if (S.dead.shot && w.shotAt === null) w.shotAt = now;
    if (w.shotAt === null) return { pos, ball: w.ball && u < 0.5 ? this.rules.lerp(w.ball, hand, ease(u * 2)) : hand };
    const v = Math.min(1, (now - w.shotAt) / 0.5), p = this.rules.lerp(hand, { x: plan.basket.x, y: plan.basket.y - 1.4 }, ease(v));
    return { pos, ball: { x: p.x, y: p.y - Math.sin(Math.PI * v) * 4, holder: null } };
  },
  drawCourt() {
    if (!this.ctx) return;
    const rules = this.rules, S = this.S, T = this.T, plan = rules.planShown(T, S.applied);
    let pos = rules.positionsAt(T, plan).pos, ball = plan ? rules.ballAt(T, plan, pos) : { x: 47, y: 25, holder: null };
    const fouled = S.dead && rules.planAt(T - 1e-6);
    if (fouled) { const dead = this.deadBall(fouled); pos = Object.assign({}, pos, dead.pos); ball = dead.ball; }
    this.shown = pos; this.lastBall = ball;
    const floor = [...S.lineups.home, ...S.lineups.away], by = rules.playerById;
    const players = floor.map((id) => ({ id, team: S.lineups.home.includes(id) ? "home" : "away", initials: initials(by[id].name), name: rules.last(by[id].name) }));
    let outline = null;   // a zone or a box, once the defenders are in it
    if (plan && plan.zoneSpot && !S.dead && T >= plan.t0 + Math.max(0, ...Object.values(plan.blend || {}))) {
      const ids = Object.keys(plan.zoneSpot).filter((id) => pos[id]);
      if (ids.length >= 3) {
        const c = ids.reduce((m, id) => ({ x: m.x + pos[id].x / ids.length, y: m.y + pos[id].y / ids.length }), { x: 0, y: 0 });
        outline = ids.map((id) => pos[id]).sort((a, b) => Math.atan2(a.y - c.y, a.x - c.x) - Math.atan2(b.y - c.y, b.x - c.x));
      }
    }
    draw.court(this.ctx, this.cw, { pos, ball, players, colors: this.colors, outline, selected: this.selected, names: this.cw >= 480 });   // names under the figures when there's room (landscape)
  },

  // ---------- the server ----------
  async fetchNext() {
    if (this.fetching || this.G.done) return;
    this.fetching = true;
    try {
      const moved = this.rules.fillRoles(this.homeFloor(), this.awayFloor()) || this.rolesMoved;   // a substitute took a role:
      this.rolesMoved = false;
      if (moved) await this.sendTactic(false, true);                                                // the engine hears it first
      this.ingest(await request("/api/next"));
    } catch (err) {
      this.setPlaying(false); this.toast(err.message);
    } finally { this.fetching = false; }
  },
  ingest(data) {
    for (const e of data.events || []) if (e.kind !== "coach" && e.kind !== "reply") this.G.events.push(e);
    if (data.periods) this.G.periods = Math.max(4, data.periods);
    if (data.done !== undefined) this.G.done = data.done;
    this.rules.rebuild();
  },
  homeFloor() { return this.S.lineups.home.length ? this.S.lineups.home : this.G.home.players.slice(0, 5).map((p) => p.id); },
  awayFloor() { return this.S.lineups.away.length ? this.S.lineups.away : this.G.away.players.slice(0, 5).map((p) => p.id); },
  phase() { return this.S.offense === "away" ? "defense" : "offense"; },
  timeoutsLeft() {   // yours: 15 at tip-off, less those called (counted the moment you call them)
    const G = this.G, pending = G.events.slice(this.S.applied).filter((e) => e.kind === "timeout" && e.zone === "coach" && e.team === G.home.tricode).length;
    return Math.max(0, (G.timeouts ? G.timeouts.home : 7) - this.S.timeouts.home - pending);
  },

  // ---------- the text around the court (only what changed goes to setData) ----------
  refresh(force) {
    const rules = this.rules, G = this.G, S = this.S, T = this.T, total = this.totalT();
    const period = rules.periodOf(Math.min(T, total - 0.01)), left = rules.periodStart(period) + (period <= 4 ? rules.PERIOD : rules.OT) - T;
    const plan = rules.planShown(T, S.applied), strip = plan && plan.tac ? rules.callsText(plan).map(([who, what]) => `${who}: ${what}`).join("   ") : "";
    const out = {
      "board.awayPts": S.away, "board.homePts": S.home, period: rules.periodLabel(period).replace(" QTR", ""), clock: rules.fmt(left),
      shot: Math.max(0, Math.min(S.chanceLen, Math.ceil(S.chanceLen - (T - S.chanceT)))), strip, playLabel: this.playLabel(),
      timeoutDisabled: this.playing && this.timeoutsLeft() <= 0, inTimeout: this.inTimeout, locked: this.playing,
    };
    const feedKey = S.feed.length;
    if (force || feedKey !== this.keys.feed) {
      this.keys.feed = feedKey;
      out.feed = S.feed.slice(-60).reverse().map((e, i) => ({ key: `${S.feed.length - i}`, clock: `${rules.periodLabel(e.period).replace(" QTR", "")} ${rules.fmt(e.clock)}`,
        team: e.team, color: G[e.team === G.home.tricode ? "home" : "away"].primary, text: e.text }));
    }
    const coachKey = JSON.stringify([this.phase(), this.homeFloor(), this.awayFloor(), rules.tactic, this.playing]);
    if (force || coachKey !== this.keys.coach) { this.keys.coach = coachKey; Object.assign(out, this.coaching()); }
    const changed = {};
    for (const k in out) if (force || JSON.stringify(out[k]) !== JSON.stringify(this.last && this.last[k])) changed[k] = out[k];
    this.last = Object.assign(this.last || {}, out);
    if (Object.keys(changed).length) this.setData(changed);
  },
  coaching() {   // the tactic list, each player's role and calls, the helper text: all from the shared rules
    const rules = this.rules, phase = this.phase(), floor = this.homeFloor(), theirs = this.awayFloor(), by = rules.playerById;
    if (rules.fillRoles(floor, theirs)) this.rolesMoved = true;
    const t = rules.tacticFor(phase), roles = rules.tactic.roles, c = rules.controlsOf(t, roles);
    const list = phase === "offense" ? rules.PLAYS : rules.SCHEMES, current = phase === "offense" ? rules.tactic.play : rules.tactic.scheme;
    const tactics = Object.keys(list).map((key) => ({ key, name: list[key].name }));
    const roleList = rules.roleList(t, theirs);
    const rows = floor.map((id) => {
      const mine = roleList.findIndex(([r]) => roles[r] === id);
      return { id, name: rules.last(by[id].name), kind: by[id].archetype, roles: roleList.map(([key, label]) => ({ key, label })),
               roleIndex: Math.max(0, mine), roleLabel: mine >= 0 ? roleList[mine][1] : "", calls: rules.callList(phase, id, floor, theirs, c) };
    });
    const say = t.say.replace(/\{(\w+)\}/g, (_, r) => (roles[r] ? rules.last(by[roles[r]].name) : "?"));
    return { tactics, tacticIndex: Math.max(0, tactics.findIndex((x) => x.key === current)), rows, helper: { name: t.name, say },
             teamCalls: rules.callList(phase, "team", floor, theirs, c),
             phaseLabel: phase === "offense" ? `${this.G.home.tricode} ball · your offense` : `${this.G.away.tricode} ball · your defense` };
  },
  playLabel() {
    const over = this.G.done && this.T >= this.totalT(), left = this.timeoutsLeft();
    if (over) return "Final";
    if (!this.playing) return this.T < 1 ? "▶ Tip-off" : "▶ Resume";
    return left > 0 ? `⏱ Timeout · ${left}` : "No timeouts";
  },

  // ---------- the Timeout button: tip-off, timeout, resume ----------
  setPlaying(on) { this.playing = on; this.lastFrame = null; this.refresh(true); },
  pressPlay() {
    if (this.G.done && this.T >= this.totalT()) return;
    if (!this.playing) { this.inTimeout = false; this.setData({ banner: "" }); this.setPlaying(true); return; }
    this.callTimeout();
  },
  async callTimeout() {
    if (this.G.done || this.timeoutsLeft() <= 0) return;
    this.inTimeout = true;
    this.setPlaying(false);
    this.whistle();
    this.setData({ banner: `TIMEOUT · ${this.G.home.tricode}`, tab: "coach" });
    try {
      const data = await request("/api/timeout", {});
      this.ingest(data);
      this.toast(data.called ? `${data.left} timeouts left · a breather for everyone on the floor` : "No timeouts left");
    } catch (err) { this.toast(err.message); }
    this.refresh(true);
  },
  whistle() {
    try { this.whistleSound.stop(); this.whistleSound.play(); } catch (err) { /* no sound */ }
    wx.vibrateShort({ type: "heavy" });
  },

  // ---------- coaching ----------
  setTab(e) { this.setData({ tab: e.currentTarget.dataset.tab }); },
  pickTactic(e) {   // in a timeout (or before the tip-off) only
    if (this.playing) return;
    const key = this.data.tactics[Number(e.detail.value)].key, phase = this.phase();
    if (!this.rules.setTactic(phase, key)) return;
    this.sendTactic(phase === "defense" && key === "man", false);
  },
  pickRole(e) {
    if (this.playing) return;
    const row = this.data.rows[Number(e.currentTarget.dataset.i)], role = row.roles[Number(e.detail.value)].key;
    if (this.rules.pickRole(this.phase(), row.id, role, this.awayFloor())) this.sendTactic(false, false);
  },
  async sendTactic(stopDouble, quiet) {   // the engine plays it from the next possession; in a timeout the court from now
    const rules = this.rules;
    rules.fillRoles(this.homeFloor(), this.awayFloor());
    if (!quiet && !this.playing) rules.restartAt(this.T);
    const raw = rules.tacticRaw(stopDouble), words = rules.tacticWords();
    this.refresh(true);
    try {
      const data = await request("/api/tactics", { raw, words });
      this.ingest(data);
      if (!quiet) this.toast(`${words}: from the next possession`);
    } catch (err) { if (!quiet) this.toast(err.message); }
  },
  pickCall(e) {
    const i = e.currentTarget.dataset.i, call = i === "team" ? this.data.teamCalls[Number(e.detail.value)] : this.data.rows[Number(i)].calls[Number(e.detail.value)];
    this.sendCall(call, i === "team" ? null : this.data.rows[Number(i)].id);
  },
  async sendCall(call, to) {
    try {
      const data = await request("/api/call", { raw: call.raw, words: call.label, to });
      this.ingest(data);
      this.toast(`${data.reply || call.label}${data.impact && data.impact.length ? ` · ${data.impact[0]}` : ""}`);
    } catch (err) { this.toast(err.message); }
  },
  // 🎙 talks to him (or everybody), 🗯 talks trash to his man (or their team): voice with the WechatSI plugin, else typed
  voiceStart(e) {
    if (!this.recognizer) return;
    this.recognizer.onStop = (res) => { if (res.result) this.said(e.currentTarget.dataset.kind, e.currentTarget.dataset.i, res.result); };
    this.recognizer.start({ lang: "en_US", duration: 30000 });
  },
  voiceEnd(e) {
    if (this.recognizer) { this.recognizer.stop(); return; }
    const kind = e.currentTarget.dataset.kind, i = e.currentTarget.dataset.i;
    wx.showModal({ title: kind === "trash" ? "Talk trash" : "Say it", editable: true, placeholderText: kind === "trash" ? "You can't guard me" : "Push the pace",
                   success: (res) => { if (res.confirm && res.content) this.said(kind, i, res.content); } });
  },
  async said(kind, i, text) {
    const id = i === "team" ? null : this.data.rows[Number(i)].id;
    try {
      if (kind === "trash") {
        const to = id == null ? null : this.rules.counterpart(id, this.T, this.awayFloor(), (pid) => this.shown[pid] || { x: 47, y: 25 });
        const data = await request("/api/trash", { text, from: id, to });
        this.ingest(data);
        if (data.replier) {
          const who = id == null ? this.G.away.tricode : this.rules.last(this.rules.playerById[data.replier].name);
          this.showCallout(data.rattled ? "good" : "bad", `${who.toUpperCase()} ${data.rattled ? "RATTLED 😬" : "FIRED UP 🔥"}`, `"${data.reply}" · ${data.effect[0] || ""}`);
        }
      } else {
        const data = await request("/api/say", { text, to: id });
        this.ingest(data);
        this.toast(`${data.reply || "Heard you, coach."} · ${data.levers}`);
      }
    } catch (err) { this.toast(err.message); }
  },
  tapCourt(e) {   // a player: his name and his kind
    if (!this.cw) return;
    const s = this.cw / 94, x = e.detail.x - (e.currentTarget.offsetLeft || 0), y = e.detail.y - (e.currentTarget.offsetTop || 0);
    let best = null, near = 4;
    for (const id in this.shown) { const p = this.shown[id], d = Math.hypot(p.x - x / s, p.y - y / s); if (d < near) { near = d; best = Number(id); } }
    if (best == null) return;
    this.selected = best;
    const p = this.rules.playerById[best];
    this.toast(`${p.name} · ${p.archetype}`);
  },

  // ---------- messages ----------
  toast(text) { wx.showToast({ title: String(text).slice(0, 60), icon: "none", duration: 2200 }); },
  showBanner(text, ms) { this.setData({ banner: text }); clearTimeout(this.bannerTimer); this.bannerTimer = setTimeout(() => { if (!this.inTimeout) this.setData({ banner: "" }); }, ms); },
  showCallout(kind, big, small) {
    this.setData({ callout: { show: true, kind, big, small } });
    clearTimeout(this.calloutTimer);
    this.calloutTimer = setTimeout(() => this.setData({ "callout.show": false }), 2600);
  },
});
