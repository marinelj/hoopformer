// The game page: the court (a canvas), the scoreboard, the Timeout button and the coaching rows, in a compact layout
// that turns with the phone (portrait: the court on top; landscape: the court on the left, the coaching on the right).
// The engine plays on the server; where everyone stands comes from the shared rules (core/court.js), so this page
// shows the same game the same way as the web page.
const core = require("../../core/court.js");
const config = require("../../config.js");
const { request } = require("../../utils/api.js");
const { freshState, apply } = require("../../utils/state.js");
const draw = require("../../utils/draw.js");
const zh = require("../../utils/chinese.js");
const { createSound, eventSound, dribbleBeat } = require("../../utils/sound.js");

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
    period: "第1节", clock: "12:00", shot: 24, playLabel: "开始比赛", timeoutDisabled: false, inTimeout: false,
    phaseLabel: "", strip: "", tab: "coach", tactics: [], tacticIndex: 0, locked: false, teamCalls: [], teamCallIndex: 0, rows: [],
    helper: { name: "", say: "" }, feed: [], banner: "", notice: "",
    soundMessage: "", requestBusy: false, reconnectNeeded: false, teamDraft: "",
    voiceAvailable: false, voiceHint: "正在准备语音…", voiceStatus: "idle", voiceMessage: "", voiceTarget: "", sending: false,
    callout: { show: false, big: "", small: "", kind: "" },
  },

  onLoad() {
    this.frame = this.frame.bind(this);
    this.sound = createSound((message) => { if (!this.unloaded) this.setData({ soundMessage: message }); });
    this.initVoice();
    this.retryStart();
  },
  onResize() { if (this.G) this.layout(); },   // the phone turned
  onPageScroll(e) { this.pageScrollTop = e.scrollTop; },
  onHide() { this.cancelGesture(); if (this.G) this.setPlaying(false); this.sound.stop(); },
  onUnload() {
    this.running = false; this.unloaded = true; this.cancelGesture();
    if (this.canvas && this.canvas.cancelAnimationFrame) this.canvas.cancelAnimationFrame(this.animationFrame);
    clearTimeout(this.bannerTimer); clearTimeout(this.calloutTimer); clearTimeout(this.voiceTimer); clearTimeout(this.holdTimer);
    if (this.sound) this.sound.destroy();
  },
  retryStart() {
    if (this.starting) return;
    this.starting = true;
    this.cancelGesture();
    wx.hideToast();
    this.running = false;
    if (this.canvas && this.canvas.cancelAnimationFrame) this.canvas.cancelAnimationFrame(this.animationFrame);
    this.setData({ ready: false, error: "" });
    this.start().catch((err) => this.setData({ ready: false, error: zh.requestError(err) })).finally(() => { this.starting = false; });
  },

  async start() {
    const query = [config.HOME && `home=${config.HOME}`, config.AWAY && `away=${config.AWAY}`].filter(Boolean).join("&");
    const G = (this.G = await request(`/api/new${query ? `?${query}` : ""}`));
    this.rules = core.createCourt(G);
    this.rules.rebuild();
    this.S = freshState();
    this.T = 0; this.played = 0; this.hold = 0; this.playing = false; this.started = false; this.inTimeout = false;
    this.drafts = {}; this.shown = {}; this.lastBall = null; this.walk = null; this.fetching = false; this.selected = null; this.keys = {}; this.lastBeat = null; this.last = {};
    while (this.S.applied < G.events.length && G.events[this.S.applied].t <= 0.1) apply(this.S, G, G.events[this.S.applied]);
    this.T = 0.1;
    const team = (key) => ({ primary: G[key].primary, secondary: G[key].secondary, ink: ink(G[key].primary) });
    this.colors = { away: G.away.primary, home: G.home.primary, awayTeam: team("away"), homeTeam: team("home") };
    this.setData({ ready: true, error: "", notice: "", banner: "", requestBusy: false, reconnectNeeded: false, teamDraft: "", voiceStatus: "idle", voiceMessage: "", voiceTarget: "", board: { awayCode: zh.teamName(G.away.tricode), homeCode: zh.teamName(G.home.tricode), awayPts: 0, homePts: 0,
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
      const high = win.windowHeight - 92 - 34 - 24;   // less the scoreboard, the strip and the margins
      courtW = Math.floor(Math.min((win.windowWidth - 34) * 0.58, (high * 94) / 50));
      panelW = win.windowWidth - courtW - 36;
    } else {
      courtW = win.windowWidth - 24;
    }
    this.setData({ landscape, courtW, courtH: Math.round((courtW * 50) / 94), panelW }, () => this.setupCanvas());
  },
  setupCanvas() {
    wx.createSelectorQuery().select("#court").fields({ node: true, size: true, rect: true }).exec((res) => {
      if (!res || !res[0] || !res[0].node) return;
      const canvas = res[0].node, dpr = (wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync()).pixelRatio;
      canvas.width = res[0].width * dpr; canvas.height = res[0].height * dpr;
      this.ctx = canvas.getContext("2d");
      this.ctx.scale(dpr, dpr);
      this.canvas = canvas; this.cw = res[0].width;
      this.canvasLeft = res[0].left || 0; this.canvasPageTop = (res[0].top || 0) + (this.pageScrollTop || 0);
      if (!this.running) { this.running = true; this.lastFrame = null; this.animationFrame = canvas.requestAnimationFrame(this.frame); }
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
    this.animationFrame = this.canvas.requestAnimationFrame(this.frame);
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
      const cue = eventSound(next);
      if (cue) this.sound.play(cue);
      this.hold = next.kind === "chance" ? 0 : 0.45;   // a beat on every whistle
      if (next.kind === "timeout" && next.zone !== "coach") { this.hold = 1.4; this.showBanner(`${zh.teamName(next.team)}暂停`, 1600); }
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
    const beat = dribbleBeat(T, ball, this.playing && this.hold <= 0, S.dead);
    if (beat !== null && beat !== this.lastBeat) this.sound.play("dribble");
    this.lastBeat = beat;
    const floor = [...S.lineups.home, ...S.lineups.away], by = rules.playerById;
    const players = floor.map((id) => ({ id, team: S.lineups.home.includes(id) ? "home" : "away", initials: zh.playerName(by[id].name) !== by[id].name ? zh.playerName(by[id].name).slice(0, 2) : initials(by[id].name), name: zh.playerName(by[id].name) }));
    let outline = null;   // a zone or a box, once the defenders are in it
    if (plan && plan.zoneSpot && !S.dead && T >= plan.t0 + Math.max(0, ...Object.values(plan.blend || {}))) {
      const ids = Object.keys(plan.zoneSpot).filter((id) => pos[id]);
      if (ids.length >= 3) {
        const c = ids.reduce((m, id) => ({ x: m.x + pos[id].x / ids.length, y: m.y + pos[id].y / ids.length }), { x: 0, y: 0 });
        outline = ids.map((id) => pos[id]).sort((a, b) => Math.atan2(a.y - c.y, a.x - c.x) - Math.atan2(b.y - c.y, b.x - c.x));
      }
    }
    draw.court(this.ctx, this.cw, { pos, ball, players, colors: this.colors, outline, selected: this.selected, names: this.cw >= 480 });   // names under the figures when there's room (landscape)
    // Draw the control on the canvas: native canvas layers can hide DOM overlays.
    const w = this.playing ? 125 : this.cw * 0.6, h = 36;
    const x = this.playing ? this.cw - w - 7 : this.cw * 0.2, y = this.data.courtH - h - 10;
    this.playHit = { x, y, w, h };
    const ctx = this.ctx;
    ctx.save(); ctx.fillStyle = this.data.requestBusy || this.data.timeoutDisabled || this.data.reconnectNeeded ? "#80988a" : "#6ee5a1";
    ctx.fillRect(x, y, w, h); ctx.fillStyle = "#102719"; ctx.font = "bold 12px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(this.data.requestBusy ? "正在确认…" : this.data.playLabel, x + w / 2, y + h / 2, w - 12); ctx.restore();
  },

  // ---------- the server ----------
  async fetchNext() {
    if (this.fetching || this.G.done) return;
    this.fetching = true;
    try {
      const moved = this.rules.fillRoles(this.homeFloor(), this.awayFloor()) || this.rolesMoved;   // a substitute took a role:
      this.rolesMoved = false;
      if (moved && !(await this.sendTactic(false, true))) { this.setPlaying(false); return; }       // the engine hears it first
      this.ingest(await request("/api/next"));
    } catch (err) {
      this.setPlaying(false); this.toast(zh.requestError(err));
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
    const plan = rules.planShown(T, S.applied), strip = plan && plan.tac ? rules.callsText(plan).map(([who, what]) => `${zh.label(who)}：${zh.label(what)}`).join("   ") : "";
    const out = {
      "board.awayPts": S.away, "board.homePts": S.home, period: zh.periodLabel(period), clock: rules.fmt(left),
      shot: Math.max(0, Math.min(S.chanceLen, Math.ceil(S.chanceLen - (T - S.chanceT)))), strip, playLabel: this.playLabel(),
      timeoutDisabled: this.playing && this.timeoutsLeft() <= 0, inTimeout: this.inTimeout, locked: this.playing,
    };
    const feedKey = S.feed.length;
    if (force || feedKey !== this.keys.feed) {
      this.keys.feed = feedKey;
      out.feed = S.feed.slice(-60).reverse().map((e, i) => ({ key: `${S.feed.length - i}`, clock: `${zh.periodLabel(e.period)} ${rules.fmt(e.clock)}`,
        team: zh.teamName(e.team), color: G[e.team === G.home.tricode ? "home" : "away"].primary, text: zh.eventText(e, rules.playerById) }));
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
    const tactics = Object.keys(list).map((key) => ({ key, name: zh.label(list[key].name) }));
    const roleList = rules.roleList(t, theirs);
    const rows = floor.map((id) => {
      const mine = roleList.findIndex(([r]) => roles[r] === id);
      return { id, draft: this.drafts[String(id)] || "", name: zh.playerName(by[id].name), kind: zh.label(by[id].archetype), roles: roleList.map(([key, label]) => ({ key, label: zh.label(label) })),
               roleIndex: Math.max(0, mine), roleLabel: mine >= 0 ? zh.label(roleList[mine][1]) : "", callIndex: 0,
               calls: [{ label: "选择一条指令", raw: null }, ...rules.callList(phase, id, floor, theirs, c).map((call) => ({ ...call, label: zh.label(call.label) }))] };
    });
    const helper = zh.tacticText(current, roles, by);
    return { tactics, tacticIndex: Math.max(0, tactics.findIndex((x) => x.key === current)), rows, helper,
             teamCallIndex: 0, teamCalls: [{ label: "选择一条指令", raw: null }, ...rules.callList(phase, "team", floor, theirs, c).map((call) => ({ ...call, label: zh.label(call.label) }))],
             phaseLabel: phase === "offense" ? "我们进攻，把机会打出来" : "我们防守，守好这一回合" };
  },
  playLabel() {
    const over = this.G.done && this.T >= this.totalT(), left = this.timeoutsLeft();
    if (over) return "比赛结束";
    if (!this.playing) return `${this.T < 1 ? "开始比赛" : "继续比赛"} · 暂停${left}次`;
    return left > 0 ? `叫暂停 · 剩${left}次` : "暂停已用完";
  },

  // ---------- the Timeout button: tip-off, timeout, resume ----------
  setPlaying(on) { this.playing = on; this.lastFrame = null; this.refresh(true); },
  pressPlay() {
    if (this.data.requestBusy || this.data.reconnectNeeded) return;
    if (this.G.done && this.T >= this.totalT()) return;
    if (!this.playing) { this.sound.enable(true); this.inTimeout = false; this.setData({ banner: "", notice: "" }); this.setPlaying(true); return; }
    this.callTimeout();
  },
  async callTimeout() {
    if (this.data.requestBusy || this.G.done || this.timeoutsLeft() <= 0) return;
    this.setData({ requestBusy: true });
    const wasPlaying = this.playing;
    this.inTimeout = true;
    this.setPlaying(false);
    this.whistle();
    this.setData({ banner: "", notice: "", tab: "coach" });
    try {
      const data = await request("/api/timeout", {});
      this.ingest(data);
      this.setData({ notice: "" });
    } catch (err) { this.inTimeout = false; this.setData({ banner: "" }); this.setPlaying(wasPlaying); this.toast(zh.requestError(err)); }
    finally { if (!this.unloaded) this.setData({ requestBusy: false }); }
    this.refresh(true);
  },
  whistle() {
    this.sound.enable(true); this.sound.play("whistle");
    wx.vibrateShort({ type: "heavy" });
  },

  // ---------- coaching ----------
  setTab(e) { this.setData({ tab: e.currentTarget.dataset.tab }); },
  async pickTactic(e) {   // in a timeout (or before the tip-off) only
    if (this.playing || this.data.requestBusy) return;
    const before = JSON.parse(JSON.stringify(this.rules.tactic)), restarts = JSON.parse(JSON.stringify(this.rules.restarts));
    const key = this.data.tactics[Number(e.detail.value)].key, phase = this.phase();
    if (!this.rules.setTactic(phase, key)) return;
    if (!(await this.sendTactic(phase === "defense" && key === "man", false))) {
      Object.assign(this.rules.tactic, before);
      this.rules.restarts.splice(0, this.rules.restarts.length, ...restarts);
      this.rules.rebuild(); this.refresh(true);
    }
  },
  async pickRole(e) {
    if (this.playing || this.data.requestBusy) return;
    const row = this.data.rows.find((r) => r.id === Number(e.currentTarget.dataset.id));
    if (!row || !row.roles[Number(e.detail.value)]) return;
    const before = JSON.parse(JSON.stringify(this.rules.tactic)), restarts = JSON.parse(JSON.stringify(this.rules.restarts)), picks = JSON.parse(JSON.stringify(this.rules.pickLog));
    const role = row.roles[Number(e.detail.value)].key;
    if (this.rules.pickRole(this.phase(), row.id, role, this.awayFloor()) && !(await this.sendTactic(false, false))) {
      Object.assign(this.rules.tactic, before);
      this.rules.restarts.splice(0, this.rules.restarts.length, ...restarts);
      this.rules.pickLog.splice(0, this.rules.pickLog.length, ...picks);
      this.rules.rebuild(); this.refresh(true);
    }
  },
  async sendTactic(stopDouble, quiet) {   // the engine plays it from the next possession; in a timeout the court from now
    if (this.data.requestBusy) return false;
    this.setData({ requestBusy: true });
    const rules = this.rules;
    rules.fillRoles(this.homeFloor(), this.awayFloor());
    if (!quiet && !this.playing) rules.restartAt(this.T);
    const raw = rules.tacticRaw(stopDouble), words = rules.tacticWords();
    this.refresh(true);
    try {
      const data = await request("/api/tactics", { raw, words });
      this.ingest(data);
      if (!quiet) this.toast("战术已调整，从下一回合开始执行。");
      return true;
    } catch (err) { this.rolesMoved = true; this.toast(zh.requestError(err)); return false; }
    finally { if (!this.unloaded) this.setData({ requestBusy: false }); }
  },
  async pickCall(e) {
    const id = e.currentTarget.dataset.id, row = id === "team" ? null : this.data.rows.find((r) => r.id === Number(id));
    const index = Number(e.detail.value), call = id === "team" ? this.data.teamCalls[index] : row && row.calls[index];
    if (!call || !call.raw) return;
    const target = row ? row.id : null;
    if (row) this.setData({ rows: this.data.rows.map((r) => r.id === target ? { ...r, callIndex: index } : r) });
    else this.setData({ teamCallIndex: index });
    await this.sendCall(call, target);
    // Reset after the actual request so choosing the same call again is another nudge.
    if (!this.unloaded) {
      if (row) this.setData({ rows: this.data.rows.map((r) => r.id === target ? { ...r, callIndex: 0 } : r) });
      else this.setData({ teamCallIndex: 0 });
    }
  },
  async sendCall(call, to) {
    if (this.data.requestBusy) return false;
    this.setData({ requestBusy: true });
    try {
      const data = await request("/api/call", { raw: call.raw, words: call.label, to });
      this.ingest(data);
      this.toast(`已执行：${call.label}`);
      return true;
    } catch (err) { this.toast(zh.requestError(err)); return false; }
    finally { if (!this.unloaded) this.setData({ requestBusy: false }); }
  },
  // Tap either side to send text. Hold to speak, release to send, slide up to cancel.
  initVoice() {
    try {
      if (!config.VOICE) throw new Error("disabled");
      this.recognizer = requirePlugin("WechatSI").getRecordRecognitionManager();
      this.setData({ voiceAvailable: true, voiceHint: "左发队员，右发对手；长按说话，松开发送，上滑取消。" });
    } catch (_) {
      this.setData({ voiceAvailable: false, voiceHint: "语音暂不可用；输入文字后点左右按钮发送。" });
      return;
    }
    this.recognizer.onStart = () => {
      const session = this.voiceSession;
      if (!session) return;
      session.started = true;
      if (!session.held || session.cancelled) { this.recognizer.stop(); return; }
      this.setData({ voiceStatus: "recording", voiceMessage: "正在听…松开发送，上滑取消" });
    };
    this.recognizer.onRecognize = (res) => {
      const session = this.voiceSession;
      if (session && !session.cancelled && !this.unloaded) this.updateDraft(session.id, res.result || "");
    };
    this.recognizer.onStop = (res) => {
      clearTimeout(this.voiceTimer);
      const session = this.voiceSession;
      if (!session) return;
      if (!this.unloaded) this.sound.enable(true);
      if (session.cancelled || this.unloaded) { this.voiceSession = null; return; }
      session.finished = true; session.result = String(res.result || "").trim();
      if (session.held) {
        this.updateDraft(session.id, session.result || session.previousDraft);
        this.setData({ voiceStatus: "held", voiceMessage: "录音已结束，松开发送，上滑取消。" });
      } else this.finishVoice(session);
    };
    this.recognizer.onError = () => {
      clearTimeout(this.voiceTimer);
      const session = this.voiceSession;
      this.voiceSession = null;
      if (!this.unloaded) this.sound.enable(true);
      if (!session || session.cancelled || this.unloaded) return;
      this.setData({ voiceStatus: "idle", voiceMessage: "语音识别失败，请重试或直接输入文字。" });
    };
  },
  async finishVoice(session) {
    if (this.voiceSession !== session || session.cancelled || this.unloaded) return;
    this.voiceSession = null;
    this.sound.enable(true);
    this.updateDraft(session.id, session.result || session.previousDraft);
    this.setData({ voiceStatus: "idle", voiceMessage: session.result ? "正在发送…" : "没有听清，请重新按住说话。" });
    if (session.result) {
      const sent = await this.sendWords(session.kind, session.id, session.result);
      if (!this.unloaded) this.setData({ voiceMessage: sent ? "已发送" : "发送未完成，文字已保留，可点按钮重试。" });
    }
  },
  gestureStart(e) {
    if (this.voiceSession || this.data.sending || this.data.requestBusy || this.data.reconnectNeeded) return;
    const data = e.currentTarget.dataset;
    const id = data.id === "team" ? null : Number(data.id);
    const touch = e.touches && e.touches[0];
    const gesture = this.buttonGesture = { id, kind: data.kind, y: touch ? touch.clientY : 0, held: true, cancelled: false, long: false };
    clearTimeout(this.holdTimer);
    this.holdTimer = setTimeout(() => {
      if (this.buttonGesture !== gesture || !gesture.held || gesture.cancelled) return;
      gesture.long = true;
      this.voiceStart(gesture);
    }, 350);
  },
  async gestureEnd() {
    clearTimeout(this.holdTimer);
    const gesture = this.buttonGesture;
    this.buttonGesture = null;
    if (!gesture) return;
    gesture.held = false;
    if (gesture.cancelled) return;
    if (gesture.long) { this.voiceEnd(); return; }
    const text = String(this.drafts[gesture.id == null ? "team" : String(gesture.id)] || "").trim();
    if (text) await this.sendWords(gesture.kind, gesture.id, text);
    else this.setData({ voiceTarget: gesture.id == null ? "team" : gesture.id, voiceMessage: "输入文字后点发送，或长按说话。" });
  },
  voiceStart(gesture) {
    if (!this.recognizer || this.voiceSession) {
      this.setData({ voiceTarget: gesture.id == null ? "team" : gesture.id, voiceMessage: "语音暂不可用，请直接输入文字。" });
      return;
    }
    const session = this.voiceSession = { ...gesture, started: false, previousDraft: this.drafts[gesture.id == null ? "team" : String(gesture.id)] || "" };
    this.sound.enable(false);
    this.setData({ voiceTarget: session.id == null ? "team" : session.id, voiceStatus: "permission", voiceMessage: "正在准备麦克风…" });
    wx.authorize({ scope: "scope.record", success: () => {
      if (this.voiceSession !== session) return;
      if (!session.held || session.cancelled) {
        this.voiceSession = null;
        this.sound.enable(true);
        if (!this.unloaded) this.setData({ voiceStatus: "idle", voiceMessage: session.cancelled ? "已取消，没有发送。" : "请确认权限后重新按住说话。" });
        return;
      }
      this.setData({ voiceStatus: "starting", voiceMessage: "正在开始录音…" });
      try {
        session.requested = true;
        this.recognizer.start({ lang: "zh_CN", duration: 30000 });
        this.voiceTimer = setTimeout(() => {
          if (this.voiceSession !== session) return;
          session.cancelled = true;
          try { this.recognizer.stop(); } catch (_) { /* already stopped */ }
          // A missing terminal callback must not block the text buttons forever.
          this.voiceSession = null; this.recognizer = null;
          if (!this.unloaded) {
            this.sound.enable(true); this.updateDraft(session.id, session.previousDraft);
            this.setData({ voiceAvailable: false, voiceStatus: "idle", voiceMessage: "识别超时，请直接输入文字；重新打开后可重试语音。" });
          }
        }, 45000);
      } catch (_) {
        this.voiceSession = null;
        this.sound.enable(true);
        this.setData({ voiceStatus: "idle", voiceMessage: "录音没有启动，请重试或直接输入文字。" });
      }
    }, fail: () => {
      if (this.voiceSession !== session) return;
      this.voiceSession = null;
      this.sound.enable(true);
      if (!this.unloaded) this.setData({ voiceStatus: "idle", voiceMessage: "麦克风权限未开启，可在小程序设置中开启。" });
    } });
  },
  voiceMove(e) {
    const gesture = this.buttonGesture, touch = e.touches && e.touches[0];
    if (gesture && touch && gesture.y - touch.clientY > 60) this.cancelGesture();
  },
  voiceEnd() {
    const session = this.voiceSession;
    if (!session) return;
    session.held = false;
    if (session.cancelled) return;
    if (session.finished) { this.finishVoice(session); return; }
    this.setData({ voiceStatus: "processing", voiceMessage: "正在识别并发送…" });
    if (session.started) this.recognizer.stop();
  },
  cancelGesture() {
    clearTimeout(this.holdTimer);
    if (!this.unloaded) this.sound.enable(true);
    if (this.buttonGesture) { this.buttonGesture.held = false; this.buttonGesture.cancelled = true; }
    this.buttonGesture = null;
    const session = this.voiceSession;
    if (session) {
      session.held = false; session.cancelled = true;
      if (!this.unloaded) this.updateDraft(session.id, session.previousDraft);
      if (session.started) { try { this.recognizer.stop(); } catch (_) { /* already stopped */ } }
      if (!session.requested || session.finished) this.voiceSession = null;
    }
    if (!this.unloaded) this.setData({ voiceStatus: "idle", voiceMessage: "已取消，没有发送。" });
  },
  updateDraft(id, text) {
    const key = id == null ? "team" : String(id);
    this.drafts[key] = String(text);
    if (id == null) this.setData({ teamDraft: String(text) });
    else this.setData({ rows: this.data.rows.map((row) => row.id === id ? { ...row, draft: String(text) } : row) });
  },
  editDraft(e) {
    const id = e.currentTarget.dataset.id === "team" ? null : Number(e.currentTarget.dataset.id);
    this.updateDraft(id, e.detail.value);
  },
  async sendWords(kind, id, text) {
    if (this.data.sending || this.data.requestBusy || this.data.reconnectNeeded || !text) return false;
    this.setData({ sending: true });
    try {
      const sent = await this.said(kind, id, text);
      if (sent && !this.unloaded) this.updateDraft(id, "");
      return sent;
    } finally { if (!this.unloaded) this.setData({ sending: false }); }
  },
  async said(kind, id, text) {
    try {
      if (kind === "trash") {
        const to = id == null ? null : this.rules.counterpart(id, this.T, this.awayFloor(), (pid) => this.shown[pid] || { x: 47, y: 25 });
        const data = await request("/api/trash", { text, from: id, to });
        this.ingest(data);
        if (data.replier) {
          const who = id == null ? zh.teamName(this.G.away.tricode) : zh.playerName(this.rules.playerById[data.replier].name);
          this.showCallout(data.rattled ? "good" : "bad", `${who}${data.rattled ? "被干扰了 😬" : "更有斗志了 🔥"}`, "这句话影响了对手的信心。");
        }
      } else {
        const rules = this.rules, phase = this.phase(), floor = this.homeFloor(), theirs = this.awayFloor();
        const calls = rules.callList(phase, id == null ? "team" : id, floor, theirs, rules.controlsOf(rules.tacticFor(phase), rules.tactic.roles)).map((call) => ({ ...call, label: zh.label(call.label) }));
        const matched = zh.matchingCall(text, calls);
        if (matched) return await this.sendCall(matched, id);
        this.setData({ notice: "千问正在理解你的指令…" });
        const data = await request("/api/say", { text, to: id, provider: "qwen" });
        if (!data.source || data.source.startsWith("rules")) {
          this.toast("云端尚未调用千问，当前返回的是规则处理；请配置千问并发布新版后端。");
          return false;
        }
        this.ingest(data);
        this.toast(data.unmapped && data.unmapped.length ? "千问已理解，但这项要求暂不能在比赛中执行。" : "教练的话已传达给球员。");
      }
      return true;
    } catch (err) { this.toast(zh.requestError(err)); return false; }
  },
  tapCourt(e) {   // a player: his name and his kind
    if (!this.cw) return;
    const touch = e.changedTouches && e.changedTouches[0];
    const x = (touch ? touch.clientX : e.detail.x) - this.canvasLeft;
    const y = (touch ? touch.clientY : e.detail.y) - (this.canvasPageTop - (this.pageScrollTop || 0));
    const hit = this.playHit;
    if (hit && x >= hit.x && x <= hit.x + hit.w && y >= hit.y && y <= hit.y + hit.h) { this.pressPlay(); return; }
    const s = this.cw / 94, courtX = x / s, courtY = y / s;
    let best = null, near = 4;
    for (const id in this.shown) { const p = this.shown[id], d = Math.hypot(p.x - courtX, p.y - courtY); if (d < near) { near = d; best = Number(id); } }
    if (best == null) return;
    this.selected = best;
    const p = this.rules.playerById[best];
    this.toast(`${zh.playerName(p.name)} · ${zh.label(p.archetype)}`);
  },

  // ---------- messages ----------
  toast(text) {
    const message = /[\u3400-\u9fff]/.test(String(text)) ? zh.label(text) : zh.requestError(new Error(String(text)));
    const expired = /已失效|连接已失效/.test(message);
    this.setData({ notice: message, reconnectNeeded: this.data.reconnectNeeded || expired });
    if (expired && this.G) { this.inTimeout = false; this.setData({ banner: "" }); this.setPlaying(false); }
    wx.showToast({ title: message.slice(0, 28), icon: "none", duration: 2200 });
  },
  showBanner(text, ms) { this.setData({ banner: text }); clearTimeout(this.bannerTimer); this.bannerTimer = setTimeout(() => { if (!this.inTimeout) this.setData({ banner: "" }); }, ms); },
  showCallout(kind, big, small) {
    this.setData({ callout: { show: true, kind, big, small } });
    clearTimeout(this.calloutTimer);
    this.calloutTimer = setTimeout(() => this.setData({ "callout.show": false }), 2600);
  },
});
