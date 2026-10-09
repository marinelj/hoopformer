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
    const reaction = (v.reactions || {})[p.id], age = reaction ? v.now - reaction.at : Infinity;
    if (reaction && age >= 0 && age < reaction.ms) {
      ctx.save(); ctx.globalAlpha = (1 - age / reaction.ms) * .8;
      ctx.strokeStyle = reaction.kind === 'bad' ? '#ff9769' : reaction.kind === 'good' ? '#82ffb1' : '#ffe09a';
      ctx.shadowColor = ctx.strokeStyle; ctx.shadowBlur = 12; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.arc(x, y, r + 4 + 3 * Math.sin(age / 85), 0, Math.PI * 2); ctx.stroke(); ctx.restore();
    }
    if (v.ball && v.ball.holder === p.id) { ctx.beginPath(); ctx.arc(x, y, r + 3, 0, 2 * Math.PI); ctx.fillStyle = "rgba(255,190,70,0.55)"; ctx.fill(); }
    ctx.beginPath(); ctx.arc(x, y, r, 0, 2 * Math.PI);
    ctx.fillStyle = team.primary; ctx.fill();
    ctx.lineWidth = p.id === v.selected ? 3 : 1.5; ctx.strokeStyle = p.id === v.selected ? "#ffd166" : team.secondary; ctx.stroke();
    ctx.fillStyle = team.ink; ctx.font = `bold ${Math.round(r * 0.85)}px sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText(p.initials, x, y + 0.5);
    if (v.names) { ctx.font = `${Math.round(r * 0.8)}px sans-serif`; ctx.fillStyle = "#fff"; ctx.fillText(p.name, x, y + r + r * 0.7); }
    if (p.badges) {
      ctx.font = 'bold 8px sans-serif'; const width = ctx.measureText(p.badges).width + 7;
      box(ctx, x - width / 2, y + r + (v.names ? r * 1.3 : 2), width, 12, 4);
      ctx.fillStyle = '#14291ee8'; ctx.fill(); ctx.fillStyle = '#d8ffe5'; ctx.fillText(p.badges, x, y + r + (v.names ? r * 1.3 : 2) + 6);
    }
  }
  if (v.ball) {
    ctx.beginPath(); ctx.arc(v.ball.x * s, v.ball.y * s, Math.max(3, 0.6 * s), 0, 2 * Math.PI);
    ctx.fillStyle = "#ff8a2a"; ctx.fill(); ctx.lineWidth = 1; ctx.strokeStyle = "#3a1a05"; ctx.stroke();
  }
}

// Prefer a wholly vacant half. During transitions, use the clearest corner and hide the count.
// All calculations use the actual shared court positions; neither half is permanently designated.
function playBounds(w, pos) {
  const height = w * 50 / 94, pw = Math.min(178, w * .42), ph = Math.min(46, height * .25), s = w / 94;
  const points = Object.values(pos), empty = [points.every(p => p.x > 49.5), points.every(p => p.x < 44.5)];
  let best = null, score = -Infinity;
  for (let side = 0; side < 2; side++) for (const cy of (empty[side] ? [.76] : [(height - ph / 2 - 5) / height, .5, (ph / 2 + 5) / height])) {
    const x = Math.round(w * (side ? .75 : .25) - pw / 2), y = Math.round(height * cy - ph / 2);
    const clearance = points.length ? Math.min(...points.map(p => Math.hypot(Math.max(x - p.x * s, 0, p.x * s - x - pw), Math.max(y - p.y * s, 0, p.y * s - y - ph)))) : w;
    const rank = clearance + (empty[side] ? w : 0);
    if (rank > score) { best = { x, y, w: Math.round(pw), h: Math.round(ph), side: side ? 'right' : 'left', vacant: empty[side], clear: clearance >= Math.max(7, s * 1.9) + 4 }; score = rank; }
  }
  return best;
}

function box(ctx, x, y, w, h, r) {
  ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}

function lines(ctx, text, maxWidth, limit = 2) {
  const out = []; let row = '';
  for (const char of Array.from(String(text || ''))) {
    if (row && ctx.measureText(row + char).width > maxWidth) { out.push(row); row = ''; }
    row += char;
  }
  if (row) out.push(row);
  if (out.length > limit) { out.length = limit; out[limit - 1] = out[limit - 1].slice(0, -1) + '…'; }
  return out;
}

function control(ctx, hit, v) {
  if (!hit.clear) return; // Never cover a player even when both halves are occupied.
  const pressed = v.pressed, x = hit.x + (pressed ? 2 : 0), y = hit.y + (pressed ? 3 : 0), w = hit.w - (pressed ? 4 : 0);
  ctx.save(); ctx.shadowColor = '#11261b99'; ctx.shadowBlur = pressed ? 2 : 8; ctx.shadowOffsetY = pressed ? 1 : 4;
  box(ctx, x, y, w, hit.h, 11); ctx.fillStyle = v.disabled ? '#879a8e' : pressed ? '#4dd68a' : '#93f0b5'; ctx.fill();
  ctx.shadowBlur = 0; ctx.shadowOffsetY = 0; ctx.strokeStyle = v.disabled ? '#b2beb5' : '#dbffe9'; ctx.lineWidth = 1.5; ctx.stroke();
  ctx.fillStyle = '#102c1b'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.font = 'bold 13px sans-serif';
  const title = v.busy ? '正在确认…' : v.over ? '比赛结束' : v.playing ? (v.left > 0 ? 'Ⅱ  叫暂停' : '暂停已用完') : `▶  ${v.started ? '继续比赛' : '开始比赛'}`;
  ctx.fillText(title, x + w / 2, y + hit.h * (hit.vacant ? .36 : .5), w - 14);
  if (hit.vacant) { ctx.font = '10px sans-serif'; ctx.fillStyle = '#286242'; ctx.fillText(`剩余 ${v.left} 次暂停`, x + w / 2, y + hit.h * .73, w - 12); }
  ctx.restore();
}

function effects(ctx, w, v) {
  const h = w * 50 / 94, s = w / 94, now = v.now;
  ctx.save(); ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  // A reply follows the actual player, stays inside the court, and expires in real time even when paused.
  for (const b of v.bubbles || []) {
    const p = v.pos[b.id], age = now - b.at;
    if (!p || age < 0 || age >= b.ms) continue;
    ctx.font = 'bold 10px sans-serif'; const width = Math.min(w * .46, Math.max(65, ctx.measureText(b.text).width + 16));
    const text = lines(ctx, b.text, width - 14, 3), height = text.length * 13 + 12;
    const x = Math.max(4, Math.min(w - width - 4, p.x * s - width / 2)), y = Math.max(4, Math.min(h - height - 4, p.y * s - height - 15));
    ctx.globalAlpha = Math.min(1, age / 110, (b.ms - age) / 250);
    box(ctx, x, y, width, height, 7); ctx.fillStyle = b.kind === 'call' ? '#ffdfa0' : '#f2fff6'; ctx.fill();
    ctx.fillStyle = '#143723'; text.forEach((line, i) => ctx.fillText(line, x + width / 2, y + 12 + i * 13));
  }
  const flash = v.flash;
  if (flash && now - flash.at < 1100) {
    const age = now - flash.at, x = flash.team === 'home' ? w * .91 : w * .09;
    ctx.globalAlpha = Math.max(0, 1 - age / 1100); ctx.fillStyle = '#fff8d4'; ctx.strokeStyle = '#173423'; ctx.lineWidth = 3; ctx.font = 'bold 23px sans-serif';
    ctx.strokeText('+' + flash.value, x, h * .36 - age / 90); ctx.fillText('+' + flash.value, x, h * .36 - age / 90);
  }
  const c = v.callout;
  if (c && c.show) {
    const half = v.hit && (v.hit.vacant ? v.hit.side : v.hit.side === 'left' ? 'right' : 'left');
    const width = half ? w * .44 : Math.min(350, w * .84), x = half ? w * (half === 'left' ? .25 : .75) - width / 2 : (w - width) / 2;
    ctx.globalAlpha = Math.min(1, (now - c.at) / 150);
    ctx.font = 'bold 12px sans-serif'; const title = lines(ctx, c.big, width - 16, 2);
    ctx.font = '10px sans-serif'; const detail = lines(ctx, c.small, width - 16, 3), height = 15 * title.length + 13 * detail.length + 16;
    const y = 6; box(ctx, x, y, width, height, 10); ctx.fillStyle = '#10251aee'; ctx.fill();
    ctx.strokeStyle = c.kind === 'bad' ? '#ffa272' : c.kind === 'call' ? '#ffdf96' : '#89ffb4'; ctx.lineWidth = 1.5; ctx.stroke();
    ctx.fillStyle = ctx.strokeStyle; ctx.font = 'bold 12px sans-serif'; title.forEach((line, i) => ctx.fillText(line, x + width / 2, y + 15 + i * 15));
    ctx.font = '10px sans-serif'; ctx.fillStyle = '#e8f5ed'; detail.forEach((line, i) => ctx.fillText(line, x + width / 2, y + 15 + title.length * 15 + i * 13));
  }
  if (v.banner) { ctx.globalAlpha = 1; ctx.font = 'bold 11px sans-serif'; ctx.fillStyle = '#e7fff0'; ctx.fillText(v.banner, w / 2, h - 12); }
  ctx.restore();
}

module.exports = { court, playBounds, control, effects };
