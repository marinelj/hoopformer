"""Original dialogue for the simulated players: Chinese, varied, and grounded in this game."""

PHRASES = {
    'pace': ('我拿到球先往前推，别让他们站稳。', '有球就往前走，你们跟上我。', '我先带起来，看前面有没有空当。'),
    '-pace': ('先稳一下，我看看他们怎么站。', '不赶这一下，我把这回合组织好。', '我会多看一眼，别急着把球丢出去。'),
    'three_point_rate': ('我去外面等，有空位就叫我。', '他们收进去的话，我在外面接应。', '好，空出来我就试一投。'),
    '-three_point_rate': ('不硬投外面了，我往里看看。', '这回合先找近一点的机会。', '行，没空位的三分我就不急着出手。'),
    'attack_rim': ('我往里试试，看看能不能把他们引过来。', '他们脚步一慢，我就往里走。', '好，我找条路进去，你们在外面接我。'),
    '-attack_rim': ('里面挤，我先在外面看看。', '行，先不往人堆里钻。', '我拉出来接，看看他们跟不跟。'),
    'ball_security': ('我会多看一眼，别把球送给他们。', '传之前我先看清楚，你们喊一声。', '好，不冒险塞那一下了。'),
    '-ball_security': ('有缝我就试着传，不过我会看着点。', '行，有机会我打得大胆些。', '我试试那个空当，你们准备接。'),
    'crash_glass': ('球一出手我就往里挤，先占住位置。', '我去找落点，你们注意后面。', '行，没进的话我再跟一手。'),
    '-crash_glass': ('我先往回跑，后面别漏人。', '好，这球出手我就回去。', '不都往里冲了，我先照看后场。'),
    'pressure': ('我靠上去一点，看看他怎么运。', '我缠住他，你们帮我看后面。', '好，我先把他逼到边上。'),
    '-pressure': ('行，我放半步，不乱扑了。', '我先守着，不去赌那一下抢断。', '让他运，我先卡住路线。'),
    'protect_paint': ('我在里面看着，你们先顾好外面。', '他往里来我就过去补。', '行，我先守住里面这块。'),
    '-protect_paint': ('我跟着外面的射手走，不乱收了。', '好，我贴出去一点。', '外面不能放，我先看住他。'),
    'foul_caution': ('我不乱伸手，先把脚步跟上。', '行，我用位置去挡，不急着下手。', '我手收着点，别白送罚球。'),
    '-foul_caution': ('我靠紧一点，但不乱来。', '行，让他接球没那么舒服。', '我顶住位置，手上会注意。'),
    'aggression': ('有机会我来打，你们给我留条路。', '行，我不犹豫了，先看看能不能过他。', '这回合我主动找一找机会。'),
    '-aggression': ('我不硬来了，先看看谁空着。', '好，我把球转出去再找位置。', '我先给你们做球，空了喊我。'),
    'rim': ('我先往里走走，看他跟不跟得住。', '好，有缝我就进去。', '我找个角度往篮下切。'),
    'mid': ('我去肘区看看，接到球再做判断。', '好，我找个舒服点的中距离位置。', '他退的话，我试试急停那一下。'),
    'three': ('我在外面等你们，有空位喊我。', '好，我把位置站开，接球再看。', '他们收进去，我就在外面接。'),
    'box_out': ('我先把人卡住，你们留意球落哪。', '好，这次先找人再找球。', '我顶住他，不让他轻松钻进来。'),
    '-box_out': ('我先往前跑，你们看好篮板。', '行，我去前面等机会。', '拿到球就找我，我先跑出去。'),
    'focus': ('行，这球先给我，我看看他们怎么防。', '球过来吧，我先读一下防守。', '好，我来接应，你们把位置站开。'),
    'double_team': ('我过去帮一下，你们看住漏出来的人。', '行，逼他把球交出去，后面记得补。', '我们两个人上，别把弱侧丢了。'),
    'matchup': ('好，各看各的人，刚才那个我来跟。', '我回去找自己的对位。', '行，先盯住人，别被带跑。'),
    'rest_minutes': ('我喘口气，你们先顶一会儿。', '好，我去歇一下，回来再接着打。', '我先下去缓缓，你有事再叫我。'),
    'confidence': ('听到了，刚才那一下我自己也有感觉。', '好，我不乱想了，接着打。', '谢了，我先把下一球打明白。'),
    '-confidence': ('刚才确实没处理好，我调整一下。', '我知道，下一回合先做简单一点。', '行，我缓一下，不跟那一球较劲了。'),
    'team_confidence': ('听到了，我们把下一回合接上。', '行，大家别松，再看好这球。', '好，咱们接着打，互相喊着点。'),
    'late_foul': ('明白，最后真需要犯规时我来盯着。', '好，我会看着时间和比分。', '行，需要停表的话你再叫我一声。'),
    'timeout': ('我过来，你说，刚才哪儿要改？', '好，先听你说一下。', '大家靠过来，看看这回合怎么打。'),
    'substitutions': ('行，换我上就喊一声。', '好，我去接上，你先缓缓。', '明白，我准备着。'),
    'unknown': ('教练，你是想让我先做哪一下？', '你再说具体一点，我好接着打。', '这句我还没弄明白，你指一下？'),
}


def natural_reply(game, side, instruction, stop=()):
    """Choose one actual teammate and one non-repeating spoken reply without consuming game RNG."""
    words, addressed = instruction.words, instruction.addressed
    players = {pid: dict(values) for pid, values in instruction.players.items()}
    for pid, minutes in instruction.rest.items(): players.setdefault(pid, {})['rest_minutes'] = minutes
    for pid, change in instruction.confidence.items():
        if pid != 'team': players.setdefault(pid, {})['confidence'] = change
    raw = {'team': instruction.team, 'players': [{'person_id': pid, **values} for pid, values in players.items()],
           'focus': instruction.focus, 'double_team': instruction.double_team, 'late_foul': instruction.late_foul,
           'timeout': instruction.timeout, 'substitutions': instruction.substitutions,
           'team_confidence': instruction.confidence.get('team'), 'stop': stop}
    entries = list((raw.get('team') or {}).items())
    for entry in raw.get('players') or []:
        entries.extend((key, value) for key, value in entry.items() if key != 'person_id')
    entries.extend((key, raw[key]) for key in ('focus', 'double_team', 'late_foul', 'team_confidence', 'timeout', 'substitutions') if raw.get(key))
    first, value = entries[0] if entries else ('matchup' if raw.get('stop') else 'unknown', 1)
    if first == 'shot_preference': first, value = value['zone'], value['value']
    if isinstance(value, (int, float)) and value < 0 and '-' + first in PHRASES: first = '-' + first
    history = [e for e in game.events if e.team == side.tricode and e.kind in ('coach', 'reply')][-12:]
    previous = next((e for e in reversed(history) if e.kind == 'reply'), None)
    candidates = [pid for pid in side.lineup if previous is None or pid != previous.actor] or side.lineup
    targeted = addressed if addressed in side.lineup else raw.get('focus')
    if targeted not in side.lineup:
        targeted = next((p['person_id'] for p in raw.get('players') or [] if p.get('person_id') in side.lineup), None)
    pid = targeted if targeted in side.lineup else game.talk_rng.choice(candidates) if candidates else None
    options = PHRASES.get(first, PHRASES['unknown'])
    choices = [text for text in options if previous is None or text not in previous.text] or options
    reply = game.talk_rng.choice(choices)
    repeated = next((e for e in reversed(history) if e.kind == 'coach'), None)
    if repeated and repeated.text == words:
        reply = game.talk_rng.choice(('我记着呢，', '刚才说的没忘，', '嗯，还照这个来，')) + reply
    athlete = side.athletes.get(pid)
    lead = ''
    if athlete and athlete.stats['PF'] >= 4 and first in ('foul_caution', '-foul_caution', 'pressure'):
        reply = f"我已经{athlete.stats['PF']}次犯规了，" + reply
    elif athlete and athlete.energy < .35 and first in ('pace', 'aggression', 'pressure', 'crash_glass'):
        reply = '我有点喘，先缓口气再跟上。' + reply
    elif game.period >= 4 and game.clock < 120 and game.other(side).points > side.points:
        reply = f"还差{game.other(side).points - side.points}分，" + reply
    elif athlete and athlete.profile.name in ('Hakeem Olajuwon', 'Tim Duncan'):
        lead = game.talk_rng.choice(('', '嗯，', '好，'))
    elif athlete and athlete.profile.name in ('Michael Jordan', 'Kobe Bryant', 'Gary Payton'):
        lead = game.talk_rng.choice(('', '行，', '来吧，'))
    if lead: reply = lead + reply.removeprefix('行，').removeprefix('好，')
    return reply, pid
