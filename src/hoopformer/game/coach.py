"""The scripted coach: timeouts and substitutions between possessions.

Both teams get one. In a human game it is the human's assistant, handling
rotations the human hasn't asked about; later, a reinforcement-learning coach
replaces it on the AI side. Its numbers come from real 2025-26 games
(docs/GAME_DESIGN.md, Day 2): teams use about 5.4 timeouts and make about 26
substitutions a game, and stints last 5 to 9 minutes depending on the player.

The rules, in order of priority:
- a player who fouls out leaves at once;
- late in a close game the best five play (closing time); late in a blowout
  the end of the bench plays (garbage time);
- otherwise players in foul trouble sit, tired players rest, rested players
  come back, and whoever is furthest behind their real minutes plays next.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hoopformer.game.engine import Game, Side

TIRED = 0.25               # below this energy a player needs a rest (energy runs from 1, fresh, to 0)
RESTED = 0.85              # a benched player is ready to come back at this energy
AHEAD_SECONDS = 300.0      # a player this far ahead of their share of minutes makes way for a rested teammate
SWAP_SECONDS = 240.0       # ...and a rested player this much further behind their share than someone on the floor comes in
CHANGE_GAP_SECONDS = 60.0  # a team changes its lineup at most once a minute, unless forced or in a timeout
CLOSING_SECONDS, CLOSING_MARGIN = 300.0, 10   # last 5 minutes of the 4th (and overtime), within 10
GARBAGE_SECONDS, GARBAGE_MARGIN = 300.0, 20   # last 5 minutes of the 4th, 20 or more apart
RUN_POINTS = 10            # call a timeout when the other team has scored this many in a row...
KEEP_FOR_THE_END = 2       # ...but keep two timeouts for the 4th quarter's last minutes
LATE_SECONDS, LATE_MARGIN = 120.0, 6  # last 2 minutes, down 1-6 after the other team scores: draw up a play
BREAK_MARKS = (420.0, 180.0)  # the first stop under 7:00 and 3:00 of each quarter is a breather, like a TV timeout
TIMEOUT_REST_SECONDS = 30.0
TIMEOUT_REASONS = {"run": "stop the run", "break": "a breather", "late": "draw up a play", "coach": "coach's call"}


def available(side: Side) -> list[int]:
    """Players who can play now: not fouled out, and not told to sit unless that leaves fewer than five."""
    players = [pid for pid, a in side.athletes.items() if not a.fouled_out]
    choosable = [pid for pid in players if pid not in side.held_out]
    return choosable if len(choosable) >= 5 else players


def starters(side: Side) -> list[int]:
    """The five who start a half: the most minutes."""
    return sorted(available(side), key=lambda pid: side.share[pid], reverse=True)[:5]


def foul_trouble(fouls: int, period: int, clock: float) -> bool:
    """The usual rule of thumb: sit with 2 fouls in the 1st, 3 in the 2nd, 4 in the 3rd, 5 before the last 5 minutes."""
    if period <= 3:
        return fouls >= period + 1
    if period == 4:
        return fouls >= 5 and clock > CLOSING_SECONDS
    return False


def wanted_lineup(game: Game, side: Side) -> tuple[list[int], str]:
    """The five this coach wants on the floor now, and why.

    Players leave when they're tired, in foul trouble, or well ahead of their minutes; whoever
    is furthest behind their minutes among the rested players comes in. Fatigue sets the
    rhythm, so stints last about as long as real ones.
    """
    players = available(side)
    pinned = [pid for pid in side.lineup if pid in side.pinned and pid in players]  # the head coach's picks stay
    by_minutes = sorted((pid for pid in players if pid not in pinned), key=lambda pid: side.share[pid], reverse=True)
    margin = abs(side.points - game.other(side).points)
    if game.period >= 4 and game.clock <= GARBAGE_SECONDS and margin >= GARBAGE_MARGIN:
        return keep_slots(side, pinned + by_minutes[len(by_minutes) - (5 - len(pinned)):]), "garbage time"
    if game.period > 4 or (game.period == 4 and game.clock <= CLOSING_SECONDS and margin <= CLOSING_MARGIN):
        return keep_slots(side, pinned + by_minutes[:5 - len(pinned)]), "closing"
    athletes = side.athletes
    need = {pid: side.share[pid] * (game.game_seconds + 60) - athletes[pid].seconds for pid in players}
    trouble = {pid for pid in players if foul_trouble(athletes[pid].stats["PF"], game.period, game.clock)}
    ready = sorted((pid for pid in players if pid not in side.lineup and pid not in trouble and athletes[pid].energy >= RESTED),
                   key=need.get, reverse=True)
    lineup = list(side.lineup)
    for slot, pid in enumerate(lineup):
        if pid in pinned:
            continue
        must_go = pid not in need or pid in trouble
        wants_rest = not must_go and (athletes[pid].energy <= TIRED or need[pid] < -AHEAD_SECONDS)
        if (must_go or wants_rest) and ready:
            lineup[slot] = ready.pop(0)
        elif must_go:  # nobody rested: the least tired of the others
            others = sorted((p for p in players if p not in lineup), key=lambda p: (p in trouble, -athletes[p].energy))
            if others:
                lineup[slot] = others[0]
    while ready:  # minutes: a rested player far behind their share replaces whoever is furthest ahead of theirs
        ahead = min((pid for pid in lineup if pid in need and pid not in pinned), key=need.get, default=None)
        if ahead is None or need[ready[0]] - need[ahead] < SWAP_SECONDS:
            break
        lineup[lineup.index(ahead)] = ready.pop(0)
    return lineup, "rotation"


def keep_slots(side: Side, five: list[int]) -> list[int]:
    """The same five, with players already on the floor kept in their slots (no needless substitutions)."""
    staying = [pid if pid in five else None for pid in side.lineup]
    coming = [pid for pid in five if pid not in side.lineup]
    return [pid if pid is not None else coming.pop(0) for pid in staying]


def leaving_reason(game: Game, side: Side, pid: int, default: str) -> str:
    athlete = side.athletes[pid]
    if athlete.fouled_out:
        return "fouled out"
    if default != "rotation":
        return default
    if foul_trouble(athlete.stats["PF"], game.period, game.clock):
        return "foul trouble"
    if athlete.energy <= TIRED:
        return "rest"
    if pid in side.held_out:
        return "coach's call"
    return "rotation"


def rotate(game: Game, side: Side, stopped: bool) -> None:
    """Make the substitutions this coach wants, if it's time to."""
    forced = any(side.athletes[pid].fouled_out for pid in side.lineup)
    if not (forced or stopped or game.game_seconds - side.last_change >= CHANGE_GAP_SECONDS):
        return
    lineup, why = wanted_lineup(game, side)
    leaving = [pid for pid in side.lineup if pid not in lineup]
    entering = [pid for pid in lineup if pid not in side.lineup]
    for out, inn in zip(leaving, entering):
        game.substitute(side, [inn if pid == out else pid for pid in side.lineup], leaving_reason(game, side, out, why))


def urgent_timeout(game: Game, side: Side, scored_by: Side | None) -> str | None:
    """A timeout this coach calls on their own: to draw up a late play, or to stop a run."""
    if side.timeouts <= 0:
        return None
    other = game.other(side)
    behind = other.points - side.points
    late = game.period >= 4 and game.clock <= LATE_SECONDS
    if late and scored_by is other and 0 < behind <= LATE_MARGIN:
        return "late"
    team, run = game.run
    keep = KEEP_FOR_THE_END if game.period >= 4 else 0
    if not late and team is other and run >= RUN_POINTS and side.timeouts > keep:
        return "run"
    return None


def breather_due(game: Game) -> Side | None:
    """Who takes the breather if one is due: the first stop under 7:00 and 3:00 of a quarter, by the trailing team."""
    if game.period > 4 or not any(game.clock <= mark and (game.period, mark) not in game.timeout_windows for mark in BREAK_MARKS):
        return None
    keep = KEEP_FOR_THE_END if game.period == 4 else 0
    trailing = game.home if game.home.points <= game.away.points else game.away
    for side in (trailing, game.other(trailing)):
        if side.timeouts > keep:
            return side
    return None


def between_possessions(game: Game, scored_by: Side | None) -> None:
    """At each stop: at most one timeout, then each coach's substitutions."""
    stopped = False
    for side in (game.home, game.away):
        reason = urgent_timeout(game, side, scored_by)
        if reason and game.call_timeout(side, reason):
            stopped = True
            break
    if not stopped:
        side = breather_due(game)
        stopped = side is not None and game.call_timeout(side, "break")
    for mark in BREAK_MARKS:  # a timeout after a mark is that window's breather; a window nobody can take closes
        if game.clock <= mark and game.period <= 4:
            game.timeout_windows.add((game.period, mark))
    for side in (game.home, game.away):
        rotate(game, side, stopped)
