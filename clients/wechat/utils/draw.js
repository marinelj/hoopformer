// The court on a canvas (the Mini Program's <canvas type="2d">, the same 2D API as a browser's): the floor, the
// players in their team colours with their initials, the ball, and a zone's outline. Court in feet: 94 x 50.

const WOOD = "#c99a5d", LINE = "rgba(255,255,255,0.9)", ARC = Math.atan2(22, Math.sqrt(23.75 * 23.75 - 22 * 22));

function floor(ctx, s, colors) {
  ctx.fillStyle = WOOD;
  ctx.fillRect(0, 0, 94 * s, 50 * s);
  ctx.globalAlpha = 0.55;   // the paint, in each team's colour (the away team's basket on the left, as on the web)
  ctx.fillStyle = colors.away; ctx.fillRect(0, 17 * s, 19 * s, 16 * s);
  ctx.fillStyle = colors.home; ctx.fillRect(75 * s, 17 * s, 19 * s, 16 * s);
  ctx.globalAlpha = 1;
  ctx.strokeStyle = LINE; ctx.lineWidth = Math.max(1, s * 0.17);
  ctx.strokeRect(0.5, 0.5, 94 * s - 1, 50 * s - 1);
  ctx.beginPath(); ctx.moveTo(47 * s, 0); ctx.lineTo(47 * s, 50 * s); ctx.stroke();
  ctx.beginPath(); ctx.arc(47 * s, 25 * s, 6 * s, 0, 2 * Math.PI); ctx.stroke();
  for (const right of [false, true]) {
    const bx = right ? 88.75 : 5.25, base = right ? 94 : 0, dir = right ? -1 : 1, x14 = bx + dir * Math.sqrt(23.75 * 23.75 - 22 * 22);
    ctx.strokeRect(Math.min(base, base + dir * 19) * s, 17 * s, 19 * s, 16 * s);   // the lane
    ctx.beginPath(); ctx.arc((base + dir * 19) * s, 25 * s, 6 * s, 0, 2 * Math.PI); ctx.stroke();   // the free-throw circle
    ctx.beginPath(); ctx.moveTo(base * s, 3 * s); ctx.lineTo(x14 * s, 3 * s); ctx.stroke();        // the corner threes
    ctx.beginPath(); ctx.moveTo(base * s, 47 * s); ctx.lineTo(x14 * s, 47 * s); ctx.stroke();
    ctx.beginPath();
    if (right) ctx.arc(bx * s, 25 * s, 23.75 * s, Math.PI - ARC, Math.PI + ARC);
    else ctx.arc(bx * s, 25 * s, 23.75 * s, -ARC, ARC);
    ctx.stroke();
    ctx.beginPath(); ctx.moveTo((base + dir * 4) * s, 22 * s); ctx.lineTo((base + dir * 4) * s, 28 * s); ctx.stroke();   // the backboard
    ctx.strokeStyle = "#ff6a2b";
    ctx.beginPath(); ctx.arc(bx * s, 25 * s, 0.75 * s, 0, 2 * Math.PI); ctx.stroke();   // the rim
    ctx.strokeStyle = LINE;
  }
}

// v: { pos: id -> {x, y}, ball: {x, y, holder}, players: [{id, team, initials, name}], colors, outline: [{x, y}],
//      selected: id, names: show last names }
function court(ctx, w, v) {
  const s = w / 94;
  floor(ctx, s, v.colors);
  if (v.outline && v.outline.length >= 3) {   // a zone or a box, through its defenders
    ctx.beginPath();
    v.outline.forEach((p, i) => (i ? ctx.lineTo(p.x * s, p.y * s) : ctx.moveTo(p.x * s, p.y * s)));
    ctx.closePath();
    ctx.fillStyle = "rgba(255,255,255,0.12)"; ctx.fill();
    ctx.setLineDash([6, 4]); ctx.strokeStyle = "rgba(255,255,255,0.8)"; ctx.lineWidth = 1.5; ctx.stroke(); ctx.setLineDash([]);
  }
  const r = Math.max(7, 1.9 * s);   // big enough to read the initials on a phone
  for (const p of v.players) {
    const at = v.pos[p.id];
    if (!at) continue;
    const x = at.x * s, y = at.y * s, team = v.colors[p.team + "Team"];
    if (v.ball && v.ball.holder === p.id) { ctx.beginPath(); ctx.arc(x, y, r + 3, 0, 2 * Math.PI); ctx.fillStyle = "rgba(255,190,70,0.55)"; ctx.fill(); }
    ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI);
    ctx.fillStyle = team.primary; ctx.fill();
    ctx.lineWidth = p.id === v.selected ? 3 : 1.5; ctx.strokeStyle = p.id === v.selected ? "#ffd166" : team.secondary; ctx.stroke();
    ctx.fillStyle = team.ink; ctx.font = `bold ${Math.round(r * 0.85)}px sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(p.initials, x, y + 0.5);
    if (v.names) { ctx.font = `${Math.round(r * 0.8)}px sans-serif`; ctx.fillStyle = "#fff"; ctx.fillText(p.name, x, y + r + r * 0.7); }
  }
  if (v.ball) {
    ctx.beginPath(); ctx.arc(v.ball.x * s, v.ball.y * s, Math.max(3, 0.6 * s), 0, 2 * Math.PI);
    ctx.fillStyle = "#ff8a2a"; ctx.fill(); ctx.lineWidth = 1; ctx.strokeStyle = "#3a1a05"; ctx.stroke();
  }
}

module.exports = { court };
