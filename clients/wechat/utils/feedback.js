// The same reactions as the web court, using actual server replies and credited plays.
const zh = require('./chinese.js');

const REPLIES = {
  'Got it, coach.': '明白，教练。', 'Heard you, coach!': '听到了，教练！',
  'Pushing it, coach.': '收到，加快推进！', 'Letting it fly.': '有机会就投三分。',
  'Attacking the rim.': '我会多冲击篮下。', 'Strong with the ball. Got it.': '收到，我会护好球。',
  'Crashing the glass.': '我会积极抢进攻篮板。', 'Turning up the pressure.': '收到，加紧逼抢。',
  'Walling up the paint.': '我会守住篮下。', 'Hands back. No cheap ones.': '收到，不乱伸手犯规。',
  'Say less. Attacking.': '收到，我会主动找机会进攻。', "I'll look for that shot.": '我会找这种出手机会。',
  'Appreciate it, coach!': '谢谢教练，我会继续努力！', 'Bringing it in.': '收到，过来集合。',
  "Got it: we foul if we're down late.": '明白，最后落后时主动犯规。', "We'll send two.": '收到，我们上两人包夹。',
  "We'll go through them.": '明白，把球交给主攻手。', 'On it, coach.': '收到，教练。',
  'Okay, taking a breather.': '好的，我休息一下。', 'Man to man. Got it.': '收到，回到人盯人。',
  "I'll pick him up full court.": '我会从后场就贴紧他。', 'Giving him a little space.': '明白，留点距离防守。',
  'Nothing easy at the rim.': '我会守住篮筐，不让他轻松上篮。', 'Staying home on my shooter.': '我会盯住自己的射手。',
  'Boxing out, every time.': '收到，每次都先卡位。', "I'll leak out for the break.": '我会提前跑出去打快攻。',
  'Slowing it down.': '收到，稳下来慢慢打。', 'Fewer threes, got it.': '明白，减少三分出手。',
  'Staying out of the crowd.': '收到，留在外线找机会。', 'Taking more chances.': '明白，打得更大胆一些。',
  'Getting back on D.': '收到，出手后马上回防。', 'Sitting back, no gambling.': '我会稳住防守，不乱抢球。',
  'Running them off the line.': '我会贴住对手的三分射手。', 'Getting physical.': '收到，防守更强硬一点。',
  'Moving it, finding the open man.': '我会多传球，找空位队友。',
  'Man, just play.': '别说了，好好打球。', 'Whatever.': '随你怎么说。', 'Get out of my face.': '离我远一点。',
  'You talk too much.': '你话太多了。', 'Not now.': '现在别烦我。', 'Shut up and guard me.': '少说话，来防我。',
  'Keep talking. Watch this.': '继续说，看我怎么打。', 'You just woke me up.': '你把我的斗志点起来了。',
  'Bad idea.': '挑衅我可不明智。', 'Say that again after this bucket.': '等我打完这球，你再说一遍。',
  "Oh, now I'm locked in.": '这下我要认真打了。', "Let's go then!": '那就来吧！',
};
const CREDITS = {
  attack: ['冲击篮下奏效！', '多冲篮下'], three: ['三分打开局面！', '多投三分'], midrange: ['中距离奏效！', '找中距离机会'],
  focus: ['主攻手站出来了！', '指定主攻手'], aggressive: ['主动进攻奏效！', '大胆进攻'],
  leak_out: ['快攻得手！', '提前跑快攻'], push: ['抢在防守落位前！', '加快节奏'], crash: ['拼下进攻篮板！', '积极抢板'],
  boxed_out: ['卡位守住篮板！', '先卡位再抢板'], press: ['紧逼奏效！', '全场紧逼'], steal: ['逼抢断球！', '贴紧对手'],
  trap: ['包夹奏效！', '上两人包夹'], rim_block: ['护框成功！', '守住篮筐'], zone_stop: ['联防守住了！', '保护篮下'],
  run_off: ['封住三分机会！', '贴住射手'], press_broken: ['紧逼被突破', '全场紧逼'], hands_back: ['对手轻松得分', '减少犯规'],
  paint_open: ['篮下出现空当', '贴住射手'], double_open: ['包夹漏了空位', '上两人包夹'], zone_beaten: ['联防被三分击穿', '保护篮下'],
  burned: ['回防来不及', '积极抢板'], forced: ['这次出手太勉强', '大胆进攻'], leak_cost: ['提前快攻丢了篮板', '提前跑快攻'],
  physical: ['强硬防守付出犯规', '强硬防守'], tired_legs: ['体力跟不上了', '高强度指令'],
};

function replyText(text) { return REPLIES[text] || String(text || ''); } // Keep Qwen's own words, including Chinese.

function creditFeedback(event, game) {
  const c = event.credit;
  if (!c || c.team !== game.home.tricode) return null;
  const players = [...game.home.players, ...game.away.players], ours = new Set(game.home.players.map(p => p.id));
  const hero = event.kind === 'turnover' && ours.has(event.other) ? event.other : event.actor;
  const player = players.find(p => p.id === hero), words = CREDITS[c.call] || ['战术影响了这一球', '临场指令'];
  const points = event.kind === 'shot' && event.value ? ` · ${c.good ? '+' : '−'}${event.value}` : '';
  return { kind: c.good ? 'good' : 'bad', big: words[0], small: `${player ? zh.playerName(player.name) : '全队'}${points} · ${words[1]}`, hero };
}

function badgesFor(id, monitor, players, step) {
  if (!monitor) return '';
  const marks = { aggression: ['攻', '传'], pressure: ['压', '稳'], protect_paint: ['框', '盯'], box_out: ['板', '快'], foul_caution: ['慎', '硬'] };
  const out = [];
  for (const d of monitor.directives || []) {
    if (d.lever === 'focus' && d.value === (players[id] || {}).name) out.push('主攻');
    if (d.lever === 'double_team' && d.value === (players[id] || {}).name) out.push('包夹');
    if (d.player_id !== id) continue;
    if (d.lever === 'rest') { out.push('休'); continue; }
    const value = typeof d.value === 'object' ? d.value.value : d.value;
    const mark = d.lever === 'shot_preference' ? { rim: '突', mid: '中', three: '三' }[d.value.zone] : marks[d.lever] && marks[d.lever][value > 0 ? 0 : 1];
    const steps = Math.max(1, Math.min(3, Math.round(Math.abs(value) / step)));
    if (mark) out.push(mark + ['', '²', '³'][steps - 1]);
  }
  const status = [...(monitor.players || []), ...(monitor.opponents || [])].find(p => p.id === id);
  if (status) { if (status.confidence >= .62) out.push('热'); else if (status.confidence <= .38) out.push('冷'); if (status.tired) out.push('累'); }
  return out.slice(0, 3).join('·');
}

module.exports = { REPLIES, CREDITS, replyText, creditFeedback, badgesFor };
