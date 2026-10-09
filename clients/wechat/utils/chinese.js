// Chinese presentation only. Player ids, tactic keys and engine values stay unchanged.
const TEAMS = { '90S': '90年代全明星', '00S': '00年代全明星', ATL: '老鹰', BOS: '凯尔特人', BKN: '篮网', CHA: '黄蜂', CHI: '公牛', CLE: '骑士', DAL: '独行侠', DEN: '掘金', DET: '活塞', GSW: '勇士', HOU: '火箭', IND: '步行者', LAC: '快船', LAL: '湖人', MEM: '灰熊', MIA: '热火', MIL: '雄鹿', MIN: '森林狼', NOP: '鹈鹕', NYK: '尼克斯', OKC: '雷霆', ORL: '魔术', PHI: '76人', PHX: '太阳', POR: '开拓者', SAC: '国王', SAS: '马刺', TOR: '猛龙', UTA: '爵士', WAS: '奇才' };
const NAMES = { 'Michael Jordan': '乔丹', 'Scottie Pippen': '皮蓬', 'Hakeem Olajuwon': '奥拉朱旺', 'John Stockton': '斯托克顿', 'Karl Malone': '马龙', 'Charles Barkley': '巴克利', 'Patrick Ewing': '尤因', 'David Robinson': '大卫·罗宾逊', 'Reggie Miller': '雷吉·米勒', 'Gary Payton': '佩顿', 'Dennis Rodman': '罗德曼', 'Clyde Drexler': '德雷克斯勒', 'Kobe Bryant': '科比', "Shaquille O'Neal": '奥尼尔', 'Tim Duncan': '邓肯', 'Kevin Garnett': '加内特', 'LeBron James': '詹姆斯', 'Allen Iverson': '艾弗森', 'Steve Nash': '纳什', 'Jason Kidd': '基德', 'Dirk Nowitzki': '诺维茨基', 'Dwyane Wade': '韦德', 'Tracy McGrady': '麦迪', 'Paul Pierce': '皮尔斯', 'Shai Gilgeous-Alexander': '亚历山大', 'Jayson Tatum': '塔图姆', 'Jaylen Brown': '杰伦·布朗', 'Chet Holmgren': '霍姆格伦', 'Stephen Curry': '库里' };
const TACTICS = {
  free: ['自由进攻', '拉开空间，谁有机会就把球传给谁。'],
  pnr: ['挡拆顺下', '{handler}持球，{screener}上来挡人，再往篮下跑。其余三人拉开。'],
  pop: ['挡拆外弹', '{handler}借{ screener }的掩护突破，{screener}退到三分线等传球。'],
  iso: ['拉开单打', '把球交给{scorer}，其他人拉开，让他一对一。'],
  post: ['低位进攻', '{entry}把球传给篮下的{post}，其他人拉开。'],
  triangle: ['三角进攻', '{post}在低位、{wing}在侧翼、{corner}在底角，三人配合；{weak}从另一侧切入。'],
  five_out: ['五人拉开', '五个人都站到三分线外，突破后找空位队友。'],
  motion: ['跑动传球', '多跑动、多传球，找到空位再出手。'],
  elevator: ['电梯掩护', '{shooter}从{doorl}和{doorr}中间跑出去，两人挡住追防，{passer}传球给他投三分。'],
  horns: ['双高位挡拆', '{elbowl}为{handler}挡人后顺下，{elbowr}退到外线接球投篮。'],
  spain: ['西班牙挡拆', '{screener}挡拆后顺下，{backscreen}再挡一下他的防守人，然后跑到外线。'],
  floppy: ['底线绕掩护', '{shooter}借{stagger1}和{stagger2}的连续掩护跑到侧翼接球；{single}在另一侧掩护。'],
  hammer: ['底角掩护', '{driver}沿底线突破，{hammer}挡住防守人，{shooter}去底角接球投三分。'],
  man: ['人盯人', '各自盯住对位球员，不包夹。'],
  switch: ['遇掩护就换防', '遇到对手掩护，两名防守人交换盯防对象。'],
  drop: ['内线守篮下', '外线继续盯人，大个子退到篮下保护篮筐。'],
  blitz: ['夹击持球人', '对手打挡拆时，两人一起夹住持球人。'],
  zone23: ['二三联防', '两人在外线，三人在篮下附近，各自守住区域。'],
  press: ['全场紧逼', '从对手后场开始贴身防守，不让他们轻松运球。'],
  box1: ['四人联防，一人追防', '{chaser}紧跟对手的主要得分手，其余四人守住篮下附近。'],
  zone131: ['一三一联防', '{trap}在外线逼抢，{middle}守中间，{rover}照看底线。'],
  tri2: ['三人联防，两人追防', '{chaser}和{chaser2}追防两名得分手，另外三人守住篮下。'],
};
const TEXT = {
  'pressure the ball': '贴紧持球人', 'protect the ball': '护好球', 'take chances': '大胆进攻', 'no fouls': '减少犯规',
  'Free offense': '自由进攻', 'Pick-and-roll': '挡拆顺下', 'Pick-and-pop': '挡拆外弹', Isolation: '拉开单打', 'Post-up': '低位进攻', Triangle: '三角进攻', 'Five-out': '五人拉开', Motion: '跑动传球', 'Elevator screen': '电梯掩护', Horns: '双高位挡拆', 'Spain pick-and-roll': '西班牙挡拆', Floppy: '底线绕掩护', Hammer: '底角掩护', 'Man to man': '人盯人', 'Switch everything': '遇掩护就换防', 'Drop coverage': '内线守篮下', 'Blitz the ball': '夹击持球人', '2-3 zone': '二三联防', 'Full-court press': '全场紧逼', 'Box-and-one': '四人联防，一人追防', '1-3-1 zone': '一三一联防', 'Triangle-and-two': '三人联防，两人追防',
  Point: '弧顶组织', Top: '弧顶', 'Left wing': '左侧翼', 'Right wing': '右侧翼', Corner: '底角', 'Dunker spot': '篮下接应', 'Ball handler': '持球组织', Screener: '掩护', Scorer: '主要得分手', 'Far wing': '远侧翼', 'Far corner': '远侧底角', 'Post player': '低位接球', 'Entry passer': '传球到低位', Post: '低位', Wing: '侧翼', 'Weak side': '弱侧切入', 'Left corner': '左底角', 'Right corner': '右底角', Shooter: '接球投篮', 'Left door': '左侧挡人', 'Right door': '右侧挡人', Passer: '传球', 'Left elbow (screens, rolls)': '左高位挡拆', 'Right elbow (pops)': '右高位外弹', 'Screener (rolls)': '掩护后顺下', 'Back-screener (pops)': '背掩护后外弹', 'Single screen': '单人掩护', 'Low stagger': '第一道掩护', 'High stagger': '第二道掩护', 'Baseline driver': '底线突破', 'Corner shooter': '底角投篮', 'Hammer screener': '底角挡人', Big: '内线接应', 'Top left': '左上区域', 'Top right': '右上区域', Middle: '中间区域', Chaser: '追防得分手', 'Box top left': '左上区域', 'Box top right': '右上区域', 'Box low left': '左下区域', 'Box low right': '右下区域', 'Top (traps)': '外线逼抢', 'Baseline rover': '底线补防', 'Chaser on their 1st scorer': '追防第一得分手', 'Chaser on their 2nd scorer': '追防第二得分手', 'Triangle top': '弧顶区域', 'Triangle low left': '左下区域', 'Triangle low right': '右下区域',
  'Two-Way Scoring Dominator': '攻防都强的得分手', 'High-Volume Isolation Guard': '擅长单打的后卫', 'All-Around Point Forward': '全能组织前锋', 'Floor General': '组织核心', 'Scoring Playmaker': '能得分的组织者', 'Shot-Creating Wing': '能自己创造机会的侧翼', 'Slashing Wing': '突破型侧翼', '3-and-D Wing': '三分与防守型侧翼', 'Movement Shooter': '跑动型射手', 'Gravity Shooter': '吸引防守的射手', 'Stretch Big': '能投三分的内线', 'Pick-and-Roll Post Bruiser': '擅长挡拆的内线', 'Dominant Post Scorer': '篮下强力得分手', 'Two-Way Post Anchor': '攻防内线核心', 'Rim-Running Anchor': '顺下护框型内线', 'Rebounding Specialist': '篮板专家', 'Energy Big': '拼抢型内线', 'Role Player': '团队型球员',
  'Push the pace': '打快一点', 'Slow it down, use the clock': '稳一点，慢慢打', 'Let it fly from three': '多投三分', 'Attack the rim': '多冲篮下', 'Take care of the ball': '护好球，少失误', 'Crash the offensive glass': '积极抢进攻篮板', 'Get back after every shot': '出手后马上回防', 'Sit back, no gambling': '稳住防守，别乱抢', 'Run them off the three-point line': '贴住对手的三分射手', 'No fouls, hands back': '少犯规，别乱伸手', 'Get physical': '防守强硬一点', "Foul when we're down late": '最后落后时主动犯规', 'Great job, everybody!': '全队打得好，继续！', 'Be aggressive, look for your shot': '大胆进攻，找机会出手', 'Move the ball, find the open man': '多传球，找空位', 'Get to the rim': '往篮下冲', 'Hunt your midrange': '找机会投中距离', 'Spot up for threes': '站好位置投三分', 'Pressure your man': '贴紧你的对手', 'Play off your man': '留点距离防守', 'Protect the rim': '守住篮筐', 'Stay home on your shooter': '盯住射手，别乱协防', 'Box out, finish the play': '先卡位，再抢篮板', 'Leak out for the break': '提前跑出去打快攻', 'Stay out of foul trouble': '注意犯规', 'Be physical with your man': '对位防守强硬一点', 'Take a breather (3 min)': '休息三分钟', 'Great job, keep it up!': '打得好，继续！', "We're running it through you": '这回合你来主攻',
  'push the pace': '加快节奏', 'slow it down': '放慢节奏', 'more threes': '多投三分', 'fewer threes': '少投三分', 'attack the rim': '冲击篮下', 'stay outside': '留在外线', 'take care of the ball': '护好球', 'take risks': '大胆进攻', 'crash the glass': '抢篮板', 'get back': '回防', 'pressure': '施压', 'sit back': '稳守', 'pack the paint': '守住篮下', 'run off the line': '贴住射手', 'hands back': '减少犯规', 'get physical': '强硬防守', 'be aggressive': '积极进攻', 'move it': '多传球', 'box out': '卡位抢篮板', 'leak out': '跑快攻',
};

function playerName(name) { return NAMES[name] || String(name || '球员'); }
function teamName(code) { return TEAMS[code] || code; }
function label(text) {
  text = String(text || '');
  if (TEXT[text]) return TEXT[text];
  if (text.startsWith('Run it through ')) return `让${label(text.slice(15))}主攻`;
  if (text.startsWith('Double-team ')) return `包夹${label(text.slice(12))}`;
  if (text.startsWith('On ')) return `盯防${label(text.slice(3))}`;
  for (const name of Object.keys(NAMES)) {
    const last = name.split(' ').slice(-1)[0];
    if (text === name || text === last) return NAMES[name];
  }
  // Translate names before vocabulary: "wing" must never change the surname Ewing.
  for (const name of Object.keys(NAMES)) text = text.split(name).join(NAMES[name]);
  for (const name of Object.keys(NAMES)) {
    const last = name.split(' ').slice(-1)[0].replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    text = text.replace(new RegExp(`\\b${last}\\b`, 'g'), NAMES[name]);
  }
  for (const [code, name] of Object.entries(TEAMS)) text = text.replace(new RegExp(`\\b${code}\\b`, 'g'), name);
  const terms = Object.keys(TEXT).sort((a, b) => b.length - a.length);
  for (const term of terms) {
    const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    text = text.replace(new RegExp(`(^|[^A-Za-z])${escaped}(?=$|[^A-Za-z])`, 'gi'), (_, lead) => lead + TEXT[term]);
  }
  for (const [from, to] of Object.entries({ offense: '进攻', defense: '防守', 'protect the ball': '护好球', 'take chances': '大胆进攻', 'no fouls': '减少犯规', aggressive: '主动进攻', 'moving it': '多传球', 'looking for the rim': '冲击篮下', 'looking for midrange': '找中距离', 'looking for threes': '找三分机会' })) text = text.split(from).join(to);
  return text.replace(/through /g, '主攻：').replace(/doubling /g, '包夹：').replace(/ chasing /g, '追防').replace(/pick-and-roll/g, '挡拆顺下').replace(/pick-and-pop/g, '挡拆外弹');
}
function tacticText(key, roles, players) {
  const tactic = TACTICS[key] || TACTICS.free;
  return { name: tactic[0], say: tactic[1].replace(/\{\s*(\w+)\s*\}/g, (_, role) => playerName((players[roles[role]] || {}).name)) };
}
function periodLabel(period) { return period <= 4 ? `第${period}节` : `加时${period - 4}`; }
function eventText(event, players) {
  const who = event.actor ? playerName((players[event.actor] || {}).name) : teamName(event.team);
  const other = event.other ? playerName((players[event.other] || {}).name) : '';
  if (event.kind === 'shot') return `${who}${({ rim: '篮下出手', mid: '中距离出手', three: '投三分' })[event.zone] || '投篮'}${event.value ? `命中，得${event.value}分` : '未中'}${other ? `，${other}助攻` : ''}`;
  if (event.kind === 'free_throws') return `${who}罚球${event.attempts}次，命中${event.value}次`;
  if (event.kind === 'rebound') return `${who}拿到${event.zone === 'offensive' ? '进攻' : '防守'}篮板`;
  if (event.kind === 'turnover') return `${who}失误${other ? `，${other}抢断` : ''}`;
  if (event.kind === 'block') return `${who}封盖了${other}的投篮`;
  if (event.kind === 'foul') return `${who}${event.zone === 'shooting' ? `对${other}投篮犯规` : event.zone === 'and-one' ? '犯规，对手加罚一次' : '犯规'}`;
  if (event.kind === 'sub') return `${who}上场，${other}下场`;
  if (event.kind === 'timeout') return `${teamName(event.team)}叫暂停`;
  if (event.kind === 'period_start') return `${periodLabel(event.period)}开始`;
  if (event.kind === 'period_end') return `${periodLabel(event.period)}结束`;
  if (event.kind === 'chance') return `${teamName(event.team)}进攻`;
  return label(event.text);
}
function requestError(error) {
  const message = String(error && error.message || error || '');
  if ((error && error.code === 'GAME_EXPIRED') || /no game|game expired/i.test(message)) return '比赛连接已失效，请重新打开小程序开始新比赛。';
  if (/timeout|timed out|超时/i.test(message)) return '比赛服务响应超时，请稍后重试。';
  if (error && error.status === 404) return '比赛接口不存在（HTTP 404），请检查云端部署版本。';
  if (error && error.status === 409) return '比赛状态已失效（HTTP 409），请重新打开小程序。';
  if (error && error.status >= 500) return `比赛服务处理失败（HTTP ${error.status}），请稍后重试。`;
  if (/fail|network|connection|网络/i.test(message)) return '连接比赛服务失败，请检查网络后重试。';
  if (/[\u3400-\u9fff]/.test(message)) return message;
  return '操作没有完成，请重试；若持续失败，请重新打开小程序。';
}
function matchingCall(text, calls) {
  const clean = String(text).replace(/[\s，。！？、,.!?]/g, '');
  const aliases = { '加快节奏': '打快一点', '打快点': '打快一点', '快一点': '打快一点', '慢一点': '稳一点，慢慢打', '多投三分球': '多投三分', '冲击篮下': '多冲篮下', '抢进攻篮板': '积极抢进攻篮板', '保护球': '护好球，少失误', '少失误': '护好球，少失误', '多传球': '多传球，找空位', '积极一点': '大胆进攻，找机会出手', '大胆进攻': '大胆进攻，找机会出手', '卡位': '先卡位，再抢篮板', '别犯规': '注意犯规' };
  const wanted = aliases[clean] || text;
  return calls.find((call) => call.label.replace(/[\s，。！？、,.!?]/g, '') === String(wanted).replace(/[\s，。！？、,.!?]/g, '')) || null;
}

module.exports = { TEAMS, NAMES, TACTICS, TEXT, playerName, teamName, label, tacticText, periodLabel, eventText, matchingCall, requestError };
