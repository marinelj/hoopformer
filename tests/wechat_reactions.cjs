// Real cloud SDK, compiled custom menus, and actual credited possessions. No wx or server mocks.
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const automator = require(process.env.HOOPFORMER_AUTOMATOR);
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const out = process.env.HOOPFORMER_WECHAT_ARTIFACTS;
let mp;
const deadline = setTimeout(() => { console.error('Cloud reaction checks timed out'); process.exit(2); }, 90000);
async function idle(page) { await wait(150); for (let n=0;n<200;n++) {if(!(await page.data('requestBusy'))&&!(await page.data('sending')))return;await wait(100);}throw Error('request remained busy'); }
async function capture(page, name) {
  if(!out)return;
  await mp.pageScrollTo(1);await wait(80);await mp.pageScrollTo(0);await wait(180);await page.callMethod('layout');await wait(250);
  await mp.screenshot({path:path.join(out,name+'.png')});
}
(async()=>{
  if(out)fs.mkdirSync(out,{recursive:true});
  mp=await automator.connect({wsEndpoint:'ws://127.0.0.1:9420'});
  const page=await mp.reLaunch('/pages/game/game');
  for(let n=0;n<150&&!(await page.data('ready'));n++)await wait(100);
  assert.equal(await page.data('ready'),true,await page.data('error'));await wait(300);
  assert.equal((await page.$$('picker')).length,0);
  await (await page.$('.team-card .call-choice')).tap();await wait(100);
  const catalog=await page.data('teamCalls'), selected=catalog.find(c=>c.raw.team&&c.raw.team.attack_rim>0)||catalog.find(c=>c.raw.team&&c.raw.team.pressure>0)||catalog.find(c=>c.raw.team&&Object.values(c.raw.team).some(v=>v>0));assert.ok(selected);const lever=Object.keys(selected.raw.team).find(k=>selected.raw.team[k]>0), label=selected.label;
  let menu=await page.data('menu'), index=menu.options.findIndex(o=>o.label===label);assert.ok(index>=0);
  await capture(page,'custom-menu');
  await (await page.$$('.choice-option'))[index].tap();await idle(page);await wait(750);
  let reply=await page.data('reply');assert.ok(reply.show);assert.match(reply.text,/[\u3400-\u9fff]/);assert.equal((await page.data('callout')).show,false);
  assert.equal(reply.target,'team');assert.equal((await page.$$('.row-reply')).length,0);await mp.pageScrollTo(500);await wait(100);assert.ok(await page.$('.team-card .row-reply'));await mp.pageScrollTo(0);await wait(100);
  assert.equal(await page.data('teamCallLabel'),label);await capture(page,'player-reply');
  console.log('CLOUD_ACTUAL_PLAYER_REPLY',JSON.stringify(reply));
  const control=await page.$('.board .play');assert.ok(control);assert.equal(await page.$('.court-box .play'),null);
  const controlSize=await control.size();assert.ok(controlSize.height>=44);
  // Repeat the exact selection: the actual server must accumulate a second nudge.
  for(let n=0;n<2;n++){await (await page.$('.team-card .call-choice')).tap();await wait(120);const current=await page.data('menu');assert.ok(current, 'call menu should open: '+JSON.stringify({busy:await page.data('requestBusy'),sending:await page.data('sending'),phase:await page.data('phaseLabel')}));const again=current.options.findIndex(o=>o.label===label);assert.ok(again>=0);await (await page.$$('.choice-option'))[again].tap();await idle(page);}
  const levers=await mp.evaluate(()=>getCurrentPages().slice(-1)[0].monitor.directives);
  assert.ok(levers.some(d=>d.lever===lever&&d.value>=.95),'three genuine requests must accumulate');
  // Build actual server possessions, then use the existing playback loop to show their effects quickly.
  await mp.evaluate(async()=>{const p=getCurrentPages().slice(-1)[0];await p.fetchNext();for(let n=0;n<3;n++)p.ingest(await require('utils/api.js').request('/api/call',{raw:{team:{attack_rim:1,pressure:1,crash_glass:1}},words:'冲击篮下，积极逼抢，拼抢篮板',to:null}));});
  for(let batch=0;batch<16;batch++){
    const counts=await mp.evaluate(async()=>{const p=getCurrentPages().slice(-1)[0];for(let n=0;n<5;n++)await p.fetchNext();const credits=p.G.events.filter(e=>e.credit&&e.credit.team===p.G.home.tricode);return {count:credits.length,good:credits.some(e=>e.credit.good),bad:credits.some(e=>!e.credit.good)};});
    if(counts.count>=5&&counts.good&&counts.bad)break;
  }
  const actual=await mp.evaluate(()=>{const p=getCurrentPages().slice(-1)[0];return p.G.events.filter(e=>e.credit&&e.credit.team===p.G.home.tricode);});
  assert.ok(actual.length>0,'actual coached engine must produce credited plays');
  const evidence=[];
  for(const target of ['good','bad'].map(kind=>actual.find(e=>e.credit.good===(kind==='good'))).filter(Boolean).sort((a,b)=>a.t-b.t)){
    const kind=target.credit.good?'good':'bad';
    const displayed=await mp.evaluate(event=>{const p=getCurrentPages().slice(-1)[0];p.hold=0;let n=0;const end=p.G.events.findIndex(e=>e.t===event.t&&e.kind===event.kind&&e.actor===event.actor&&e.value===event.value);while(p.S.applied<=end&&n++<20000){p.hold=0;p.advance(.2);}p.drawCourt();p.refresh(true);return {callout:p.data.callout,flash:p.flash,reactions:p.reactions,T:p.T};},target);
    assert.equal(displayed.callout.kind,kind);assert.match(displayed.callout.big,/[\u3400-\u9fff]/);
    evidence.push({event:target,callout:displayed.callout});await capture(page,'credit-'+kind);
  }
  assert.ok(evidence.length>=1);
  const score=await mp.evaluate(()=>getCurrentPages().slice(-1)[0].G.events.find(e=>e.kind==='shot'&&e.value&&e.t>getCurrentPages().slice(-1)[0].T));
  if(score){const flash=await mp.evaluate(event=>{const p=getCurrentPages().slice(-1)[0];const end=p.G.events.findIndex(e=>e.t===event.t&&e.kind===event.kind&&e.actor===event.actor&&e.value===event.value);while(p.S.applied<=end){p.hold=0;p.advance(.2);}p.drawCourt();return p.flash;},score);assert.equal(flash.value,score.value);await capture(page,'score-flash');}
  const hit={size:await control.size(),offset:await control.offset(),court:await (await page.$('#court')).offset()};
  assert.ok(hit.offset.top+hit.size.height<=hit.court.top);assert.equal(await page.$('.court-box .play'),null);
  await control.tap();await wait(300);await control.tap();await idle(page);assert.equal(await page.data('locked'),false);await capture(page,'scoreboard-timeout');
  const input=await page.$('.team-card input.command-input');
  await input.input('全队降低进攻节奏，保护好球，多给乔丹创造冲击篮筐的机会。');await wait(100);
  const own=await page.$('.team-card .send.own');await own.touchstart({touches:[{clientX:40,clientY:400}]});await wait(60);await own.touchend({touches:[]});await idle(page);await wait(700);
  assert.equal(await page.data('teamDraft'),'');const qwenReply=await page.data('reply');assert.ok(qwenReply.show);assert.match(qwenReply.text,/[\u3400-\u9fff]/);assert.equal((await page.data('callout')).show,false);
  console.log('CLOUD_FREE_LANGUAGE_CALLOUT',JSON.stringify(qwenReply));await capture(page,'qwen-reply');
  console.log('CLOUD_REACTIONS_PASSED',JSON.stringify({credits:actual.length,kinds:evidence.map(e=>e.callout.kind),control:hit,scoreFlash:!!score}));
  if(out)fs.writeFileSync(path.join(out,'cloud-reactions.json'),JSON.stringify({reply,qwenReply,levers,evidence,control:hit},null,2));
})().catch(e=>{console.error(e.stack);process.exitCode=1;}).finally(async()=>{if(mp){await mp.reLaunch('/pages/game/game').catch(()=>{});await mp.disconnect();}clearTimeout(deadline);});
