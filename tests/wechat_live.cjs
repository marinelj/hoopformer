// Run against the real DevTools runtime and real HTTP server. No mocked wx APIs.
// HOOPFORMER_AUTOMATOR=/path/to/miniprogram-automator node tests/wechat_live.cjs [http://127.0.0.1:8128]
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const automator = require(process.env.HOOPFORMER_AUTOMATOR);
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
let mp, original;
const evidence = {};
async function choose(page, selector, index) {
  const field=await page.$(selector);assert.ok(field, selector);await field.tap();await wait(80);
  const options=await page.$$('.choice-option');assert.ok(options[index], 'custom option ' + index);await options[index].tap();await settle(page);
}
const deadline = setTimeout(() => { console.error('Real WeChat checks timed out'); process.exit(2); }, 120000);

async function settle(page) {
  await wait(150);
  for (let i = 0; i < 150; i++) {
    if (!(await page.data('requestBusy')) && !(await page.data('sending'))) return;
    await wait(100);
  }
  throw Error('UI request remained busy');
}

async function rowsIntact(page) {
  const rows = await page.data('rows');
  assert.ok(Array.isArray(rows), 'picker must preserve the array');
  assert.equal(rows.length, 5);
  assert.equal(new Set(rows.map(r => r.id)).size, 5);
  assert.equal((await page.$$('.player-card')).length, 5, 'five actual cards must be rendered');
  for (const row of rows) {
    assert.ok(row.name && row.roleLabel && row.roles.length && row.calls.length);
    assert.ok(row.callLabel, 'selected face must remain explicit');
  }
  return rows;
}

(async () => {
  mp = await automator.connect({ wsEndpoint: process.env.HOOPFORMER_WECHAT_WS || 'ws://127.0.0.1:9420' });
  original = await mp.evaluate(() => {
    const c = require('config.js');
    return { CLOUD_ENV: c.CLOUD_ENV, CLOUD_SERVICE: c.CLOUD_SERVICE, SERVER: c.SERVER };
  });
  if (process.argv[2]) await mp.evaluate(server => {
    const c = require('config.js'); c.CLOUD_ENV = ''; c.CLOUD_SERVICE = ''; c.SERVER = server;
  }, process.argv[2]);
  let page = await mp.reLaunch('/pages/game/game');
  for (let n = 0; n < 100 && !(await page.data('ready')); n++) await wait(100);
  assert.equal(await page.data('ready'), true, await page.data('error'));
  assert.equal(await page.data('error'), '');
  evidence.initial = (await rowsIntact(page)).map(r => r.name);

  assert.equal((await page.$$('picker')).length, 0, 'no OS pickers');
  // Send the same actual option again: no change-event reset and no array corruption.
  for (let round = 0; round < 2; round++) for (let i = 0; i < 5; i++) {
    const fields=await page.$$('.player-card .call-choice');
    await fields[i].tap();await wait(80);
    const menu=await page.data('menu'), label=menu.options[0].label;
    await (await page.$$('.choice-option'))[0].tap();await settle(page);
    const rows=await rowsIntact(page);
    assert.equal(rows[i].callLabel,label);assert.equal(rows[i].callIndex,0);
    assert.equal(await fields[i].text(),label+'⌄');
    await wait(700);
    const c=await page.data('reply');assert.ok(c.show);assert.match(c.text,/[\u3400-\u9fff]/);assert.equal((await page.data('callout')).show,false,'no duplicate court-corner reply');assert.equal((await page.$$('.row-reply')).length,0,'visible court has only its player bubble');
    const reaction=await mp.evaluate(id=>{const p=getCurrentPages().slice(-1)[0];return {pulse:p.reactions[id],bubble:p.bubbles[0]};},rows[i].id);
    assert.equal(reaction.bubble.id,rows[i].id);assert.equal(reaction.bubble.text,c.text);assert.equal(reaction.pulse.kind,'good');
  }
  evidence.playerCalls = 10;evidence.actualPlayerReplies=true;
  console.log('PLAYER_CALLS_AND_REPLIES', evidence.playerCalls, 'selected labels persist; actual replies have callouts and player bubbles');

  const tactics = await page.data('tactics');
  for (let i = 0; i < tactics.length; i++) {
    await choose(page,'.team-card .tactic-choice',i);await rowsIntact(page);
    assert.match(await page.data('notice'),/战术已生效/);
  }
  evidence.tactics = tactics.map(t => t.name);
  for (let i = 0; i < 5; i++) {
    const rows=await rowsIntact(page), fields=await page.$$('.player-card .role-choice');
    await fields[i].tap();await wait(80);
    await (await page.$$('.choice-option'))[(rows[i].roleIndex+1)%rows[i].roles.length].tap();await settle(page);await rowsIntact(page);
    assert.match(await page.data('notice'),/战术已生效/);
  }
  console.log('CUSTOM_TACTICS_AND_ROLES', evidence.tactics);

  // The input stays in the card; both sides are native touch controls, with no sheet.
  assert.equal((await page.$$('.shade')).length, 0);
  assert.equal((await page.$$('scroll-view')).length, 0);
  assert.equal((await page.$$('.audio-control')).length, 0);
  assert.equal((await page.$$('input.command-input')).length, 6);
  const calls = await page.data('teamCalls'), words = calls.find(c => c.raw).label;
  const draft = await page.$('.team-card input.command-input');
  await draft.input(words); await wait(150);
  const own = await page.$('.team-card .send.own');
  await own.touchstart({touches:[{clientX:40,clientY:400}]});await wait(60);await own.touchend({touches:[]});
  await settle(page);
  assert.equal(await page.data('teamDraft'), '');
  assert.equal(await page.data('teamCallLabel'),words);evidence.typed=words;
  await draft.input('你防不住我们！'); await wait(100);
  const opponent = await page.$('.team-card .send.opponent');
  await opponent.touchstart({touches:[{clientX:300,clientY:400}]});await wait(60);await opponent.touchend({touches:[]});
  await settle(page);assert.equal(await page.data('teamDraft'),'');
  assert.match((await page.data('reply')).text,/[\u3400-\u9fff]/);evidence.inlineTrash = true;
  await mp.pageScrollTo(500);await wait(250);assert.ok(Number(await page.scrollTop())>0,'whole page must scroll naturally');
  await mp.pageScrollTo(200);await wait(250);
  const courtPoint = await mp.evaluate(() => {
    const p=getCurrentPages().slice(-1)[0], id=Number(Object.keys(p.shown)[0]), q=p.shown[id];
    return {id,x:p.canvasLeft+q.x*p.cw/94,y:p.canvasPageTop-(p.pageScrollTop||0)+q.y*p.cw/94};
  });
  await (await page.$('#court')).trigger('tap',courtPoint);await wait(150);
  assert.equal(await mp.evaluate(()=>getCurrentPages().slice(-1)[0].selected),courtPoint.id,'court player remains clickable after page scroll');
  page = await mp.reLaunch('/pages/game/game');
  for(let n=0;n<100&&!(await page.data('ready'));n++)await wait(100);
  await mp.pageScrollTo(0);await wait(250);
  console.log('INLINE_INPUTS_AND_PAGE_SCROLL',evidence.typed,evidence.inlineTrash);

  const play = await page.$('.play');
  assert.ok(await page.$('.board .play'));assert.equal(await page.$('.court-box .play'),null);
  const controlSize=await play.size(),controlOffset=await play.offset(),courtOffset=await (await page.$('#court')).offset();
  assert.ok(controlSize.height>=44);assert.ok(controlOffset.top+controlSize.height<=courtOffset.top,'button stays above the court');
  assert.equal(await play.attribute('hover-class'),'play-pressed');
  await play.tap(); await wait(4500);
  assert.equal(await page.data('locked'), true);assert.match(await page.data('playLabel'),/叫暂停/);
  evidence.control={size:controlSize,offset:controlOffset,court: courtOffset,remaining:await page.data('playCount')};
  evidence.audio = await mp.evaluate(() => getCurrentPages().slice(-1)[0].sound.stats);
  assert.ok(evidence.audio.played.dribble > 0, 'actual audio onPlay must fire while holding the ball');
  assert.deepEqual(evidence.audio.errors, []);
  await play.tap(); await settle(page);
  assert.equal(await page.data('inTimeout'), true);
  assert.equal(await page.data('locked'), false);
  assert.equal(await page.data('notice'), '');
  assert.match(await page.data('playLabel'), /继续比赛.*14次/);
  evidence.timeout = await page.data('playLabel');
  const frozen=await mp.evaluate(()=>{const p=getCurrentPages().slice(-1)[0];p.drawCourt();return {T:p.T,pos:p.shown,ball:p.lastBall,prefix:p.G.events.slice(0,p.S.applied)};});
  const tacticsNow=await page.data('tactics'),nextTactic=tacticsNow.findIndex(t=>t.key==='iso'||t.key==='zone23');assert.ok(nextTactic>=0);
  await choose(page,'.team-card .tactic-choice',nextTactic);await wait(150);
  const immediate=await mp.evaluate(()=>{const p=getCurrentPages().slice(-1)[0];p.drawCourt();const plan=p.rules.planAt(p.T);return {T:p.T,pos:p.shown,ball:p.lastBall,plan:{t0:plan.t0,play:plan.play,scheme:plan.scheme},count:p.timeoutsLeft(),events:p.G.events};});
  assert.equal(immediate.T,frozen.T);assert.equal(immediate.plan.t0,frozen.T);assert.ok(immediate.plan.play==='iso'||immediate.plan.scheme==='zone23');assert.equal(immediate.count,14);
  for(const id of Object.keys(frozen.pos))assert.ok(Math.hypot(immediate.pos[id].x-frozen.pos[id].x,immediate.pos[id].y-frozen.pos[id].y)<1e-6,'tactic moved a paused player '+id);
  assert.ok(Math.hypot(immediate.ball.x-frozen.ball.x,immediate.ball.y-frozen.ball.y)<1e-6);
  evidence.immediate={T:immediate.T,plan:immediate.plan,count:immediate.count};console.log('CURRENT_CHANCE_TACTIC_APPLIED',JSON.stringify(evidence.immediate));
  evidence.audioAfterToggle = await mp.evaluate(() => getCurrentPages().slice(-1)[0].sound.stats);
  assert.ok(evidence.audioAfterToggle.played.whistle > 0);
  assert.deepEqual(evidence.audioAfterToggle.errors, []);
  await play.tap(); await wait(700);
  assert.equal(await page.data('inTimeout'), false);
  assert.equal(await page.data('locked'), true);
  await rowsIntact(page);
  console.log('TIMEOUT_RESUME_AUDIO', JSON.stringify({ timeout: evidence.timeout, audio: evidence.audioAfterToggle }));

  page = await mp.reLaunch('/pages/game/game');
  for(let n=0;n<100&&!(await page.data('ready'));n++)await wait(100);
  const cancelWords=(await page.data('teamCalls')).find(c=>c.raw).label;
  const cancelInput=await page.$('.team-card input.command-input');await cancelInput.input(cancelWords);await wait(100);
  const cancelButton=await page.$('.team-card .send.own');
  await cancelButton.touchstart({touches:[{clientX:40,clientY:400}]});
  await cancelButton.touchmove({touches:[{clientX:40,clientY:320}]});
  await cancelButton.touchend({touches:[]});await wait(500);
  assert.equal(await page.data('teamDraft'),cancelWords,'cancel keeps the previous typed draft');
  const cancelled=await mp.evaluate(async()=>{const data=await require('utils/api.js').request('/api/next');return data.monitor.directives;});
  assert.deepEqual(cancelled,[],'slide up must not send a coaching instruction');
  evidence.slideCancelled = true;
  if(process.argv[2]) {
    const freeWords='请让控球人多利用挡拆制造错位，其他人及时拉开接应。';
    await cancelInput.input(freeWords);await wait(100);
    await cancelButton.touchstart({touches:[{clientX:40,clientY:400}]});await wait(60);await cancelButton.touchend({touches:[]});
    await settle(page);
    assert.equal(await page.data('teamDraft'),freeWords,'failed Qwen instruction must remain retryable');
    assert.match(await page.data('notice'),/千问服务尚未连接/);
    evidence.requiredQwenMissing=await page.data('notice');
    console.log('SLIDE_CANCEL_AND_REQUIRED_QWEN',evidence.slideCancelled,evidence.requiredQwenMissing);
  }

  // These errors are produced by the real server, then formatted by the actual compiled client.
  evidence.errors = await mp.evaluate(async () => {
    const request = require('utils/api.js').request, zh = require('utils/chinese.js');
    const out = [];
    for (const route of ['/api/next?game_id=expired', '/api/missing']) {
      try { await request(route); out.push({ route, unexpected: 'success' }); }
      catch (error) { out.push({ route, status: error.status, code: error.code, message: zh.requestError(error) }); }
    }
    return out;
  });
  assert.deepEqual(evidence.errors.map(e => e.status), [409, 404]);
  assert.match(evidence.errors[0].message, /失效/);
  assert.match(evidence.errors[1].message, /404/);
  console.log('REAL_HTTP_ERRORS', evidence.errors);

  if (process.argv[2]) {
    // Evict the real session by opening other real games, without changing the client's id.
    // This reproduces a restarted/expired backend and verifies rollback and explicit recovery.
    for (const kind of ['tactic', 'role']) {
      page = await mp.reLaunch('/pages/game/game');
      for (let n = 0; n < 100 && (!(await page.data('ready')) || await page.data('reconnectNeeded')); n++) await wait(100);
      const before = await page.data('rows'), tacticIndex = await page.data('tacticIndex');
      for (let batch = 0; batch < 5; batch++) await mp.evaluate(async start => {
        const config = require('config.js');
        for (let i = 0; i < 8; i++) await new Promise((resolve, reject) => wx.request({
          url: config.SERVER + '/api/new?seed=' + (start + i),
          success: r => r.statusCode === 200 ? resolve() : reject(Error('eviction HTTP ' + r.statusCode)),
          fail: reject,
        }));
      }, 300 + batch * 8);
      if (kind === 'tactic') {
        await choose(page,'.team-card .tactic-choice',(tacticIndex+1)%(await page.data('tactics')).length);
      } else {
        await (await page.$$('.player-card .role-choice'))[0].tap();await wait(80);
        await (await page.$$('.choice-option'))[(before[0].roleIndex+1)%before[0].roles.length].tap();
      }
      await settle(page);
      assert.match(await page.data('notice'), /失效/);
      assert.equal(await page.data('reconnectNeeded'), true);
      assert.equal(await page.data('tacticIndex'), tacticIndex);
      assert.deepEqual((await rowsIntact(page)).map(r => [r.id, r.roleLabel]), before.map(r => [r.id, r.roleLabel]));
      const reconnect = await page.$('button.reconnect'); assert.ok(reconnect); await reconnect.tap();
      for (let n = 0; n < 100 && (!(await page.data('ready')) || await page.data('reconnectNeeded')); n++) await wait(100);
      assert.equal(await page.data('ready'), true);
      assert.equal(await page.data('reconnectNeeded'), false);
      console.log('EXPIRED_SESSION_ROLLBACK_RECOVERY', kind, 'passed');
    }
    evidence.expiredRecovery = ['tactic', 'role'];
  }

  if (process.env.HOOPFORMER_WECHAT_ARTIFACTS) {
    fs.mkdirSync(process.env.HOOPFORMER_WECHAT_ARTIFACTS, { recursive: true });
    fs.writeFileSync(path.join(process.env.HOOPFORMER_WECHAT_ARTIFACTS, 'live-checks.json'), JSON.stringify(evidence, null, 2));
    // Reflow native canvas layers after DevTools reLaunch/page-scroll checks.
    await mp.evaluate(() => wx.pageScrollTo({scrollTop:1,duration:0})); await wait(100);
    await mp.evaluate(() => wx.pageScrollTo({scrollTop:0,duration:0})); await wait(300);
    await page.callMethod('layout'); await wait(500);
    await mp.screenshot({ path: path.join(process.env.HOOPFORMER_WECHAT_ARTIFACTS, 'fixed-game.png') });
  }
  console.log('REAL_WECHAT_CHECKS_PASSED');
})().catch(error => { console.error(error.stack); process.exitCode = 1; }).finally(async () => {
  if (mp) {
    if (original) {
      await mp.evaluate(config => { Object.assign(require('config.js'), config); }, original).catch(() => {});
      await mp.reLaunch('/pages/game/game').catch(() => {});
    }
    mp.disconnect();
  }
  clearTimeout(deadline);
});
