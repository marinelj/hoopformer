"""Character dialogue tested against the actual cached classic-inclusive engine, without mocks."""
from pathlib import Path
import pytest
from hoopformer.game.dialogue import natural_reply
from hoopformer.game.legends import with_legends
from hoopformer.game.levers import lever_limits, validate
from hoopformer.game.server import LiveGame
from hoopformer.game.translator import context_for

@pytest.fixture
def conversation(fitted):
    model, _ = fitted
    model = with_legends(model, Path('data'))
    codes = {t.tricode: t.team_id for t in model.teams.values()}
    return LiveGame(model, lever_limits(Path('data'), '2025-26'), codes['90S'], codes['00S'], 7, use='rules')

def test_repeated_calls_are_varied_and_logged_once(conversation):
    live=conversation; samples=[]; speakers=[]
    for n in range(8):
        before=len(live.game.events)
        data=live.call({'team': {'pace': 1}}, '加快节奏', None)
        samples.append(data['reply']);speakers.append(data['replier'])
        replies=[e for e in live.game.events[before:] if e.kind=='reply']
        assert len(replies)==1 and replies[0].text==data['reply']
        assert any('\u3400'<=c<='\u9fff' for c in data['reply'])
    print('Actual repeated dialogue:',list(zip(speakers,samples)))
    assert len(set(samples))>=4 and len(set(speakers))>=3
    assert all(a!=b for a,b in zip(samples,samples[1:]))
    assert all(a!=b for a,b in zip(speakers,speakers[1:]))
    context=context_for(live.game,live.game.home,None)
    assert len(context['recent_conversation'])==8
    assert context['recent_conversation'][-1]['text']==samples[-1]
    assert all('confidence' in p for p in context['your_players'])

def test_addressed_player_and_facts_come_from_the_real_game(conversation):
    live=conversation;side=live.game.home
    for _ in range(110): live.game.step()
    pid=max(side.lineup,key=lambda p:side.athletes[p].stats['PF'])
    instruction=validate({'players':[{'person_id':pid,'foul_caution':1}]},'别再犯规',set(side.athletes),set(live.game.away.athletes),pid,'call')
    text,replier=natural_reply(live.game,side,instruction)
    print('Actual late-game reply:',side.athletes[pid].profile.name,'PF',side.athletes[pid].stats['PF'],'energy',side.athletes[pid].energy,text)
    assert replier==pid and ('手' in text or '位置' in text or '罚球' in text)
    if side.athletes[pid].stats['PF']>=4:assert str(side.athletes[pid].stats['PF'])+'次犯规' in text
    else:assert '次犯规' not in text
    before=live.game.rng.getstate();natural_reply(live.game,side,instruction)
    assert live.game.rng.getstate()==before,'dialogue never consumes basketball RNG'

def test_rules_free_input_has_chinese_conversation(conversation):
    live=conversation;pid=live.game.home.lineup[1]
    data=live.say('传球稳一点，不要轻易丢球',pid,provider='rules')
    print('Actual rules free-language reply:',data['reply'],data['replier'])
    assert any('\u3400'<=c<='\u9fff' for c in data['reply'])
    assert data['replier']==pid
