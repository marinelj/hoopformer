// Run against the real DevTools runtime and real HTTP server. No mocked wx APIs.
// HOOPFORMER_AUTOMATOR=/path/to/miniprogram-automator node tests/wechat_live.cjs [http://127.0.0.1:8128]
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const automator = require(process.env.HOOPFORMER_AUTOMATOR);
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
let mp, original;
const evidence = {};
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
    assert.equal(row.callIndex, 0, 'same call can be picked again');
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

  // Reproduce the original array corruption through the actual picker change event.
  for (let round = 0; round < 2; round++) for (let i = 0; i < 5; i++) {
    const pickers = await page.$$('.player-card picker');
    assert.equal(pickers.length, 10);
    await pickers[i * 2 + 1].trigger('change', { value: '1' });
    await settle(page);
    await rowsIntact(page);
    assert.match(await page.data('notice'), /已执行/);
  }
  evidence.playerCalls = 10;
  console.log('PLAYER_CALLS', evidence.playerCalls, 'five cards remain complete');

  // Change every tactic offered for this real possession and swap each player's role.
  const tactics = await page.data('tactics');
  for (let i = 0; i < tactics.length; i++) {
    const picker = await page.$('.team-card picker');
    await picker.trigger('change', { value: String(i) });
    await settle(page);
    await rowsIntact(page);
    assert.match(await page.data('notice'), /战术已调整/);
  }
  evidence.tactics = tactics.map(t => t.name);
  for (let i = 0; i < 5; i++) {
    const rows = await rowsIntact(page);
    const pickers = await page.$$('.player-card picker');
    await pickers[i * 2].trigger('change', { value: String((rows[i].roleIndex + 1) % rows[i].roles.length) });
    await settle(page);
    await rowsIntact(page);
    assert.match(await page.data('notice'), /战术已调整/);
  }
  console.log('TACTICS_AND_ROLES', evidence.tactics);

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
  assert.match(await page.data('notice'), /已执行/); evidence.typed = words;
  await draft.input('你防不住我们！'); await wait(100);
  const opponent = await page.$('.team-card .send.opponent');
  await opponent.touchstart({touches:[{clientX:300,clientY:400}]});await wait(60);await opponent.touchend({touches:[]});
  await settle(page);assert.equal(await page.data('teamDraft'),'');
  assert.match((await page.data('callout')).big,/被干扰|更有斗志/);evidence.inlineTrash = true;
  await mp.pageScrollTo(500);await wait(250);assert.ok(Number(await page.scrollTop())>0,'whole page must scroll naturally');
  await mp.pageScrollTo(200);await wait(250);
  const courtPoint = await mp.evaluate(() => {
    const p = getCurrentPages().slice(-1)[0], h = p.playHit;
    return { x:p.canvasLeft+h.x+h.w/2, y:p.canvasPageTop-p.pageScrollTop+h.y+h.h/2 };
  });
  await (await page.$('#court')).trigger('tap', courtPoint);await wait(250);
  assert.equal(await page.data('locked'),true,'court control must remain clickable after page scroll');
  await (await page.$('.play')).tap();await settle(page);
  assert.equal(await page.data('locked'),false);
  page = await mp.reLaunch('/pages/game/game');
  for(let n=0;n<100&&!(await page.data('ready'));n++)await wait(100);
  await mp.pageScrollTo(0);await wait(250);
  console.log('INLINE_INPUTS_AND_PAGE_SCROLL',evidence.typed,evidence.inlineTrash);

  const play = await page.$('.play');
  await play.tap(); await wait(4500);
  assert.equal(await page.data('locked'), true);
  assert.match(await page.data('playLabel'), /叫暂停/);
  evidence.audio = await mp.evaluate(() => getCurrentPages().slice(-1)[0].sound.stats);
  assert.ok(evidence.audio.played.dribble > 0, 'actual audio onPlay must fire while holding the ball');
  assert.deepEqual(evidence.audio.errors, []);
  await play.tap(); await settle(page);
  assert.equal(await page.data('inTimeout'), true);
  assert.equal(await page.data('locked'), false);
  assert.equal(await page.data('notice'), '');
  assert.match(await page.data('playLabel'), /继续比赛.*14次/);
  evidence.timeout = await page.data('playLabel');
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
        const picker = await page.$('.team-card picker');
        await picker.trigger('change', { value: String((tacticIndex + 1) % (await page.data('tactics')).length) });
      } else {
        const picker = (await page.$$('.player-card picker'))[0];
        await picker.trigger('change', { value: String((before[0].roleIndex + 1) % before[0].roles.length) });
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
