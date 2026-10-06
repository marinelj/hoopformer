"""Player archetypes: what kind of player each one is, read from his own numbers.

A player's archetype (Michael Jordan: a two-way scoring dominator, Klay Thompson: a 3-and-D wing) comes from
where he stands among the league's rotation players (20+ minutes a game, 20+ games, today's and the classic
teams together) on a dozen per-chance rates: how much of the offense he uses, where his shots come from, how
often he gets to the line, passes, rebounds, steals and blocks. The rules below are checked in order and the
first that fits names him. They are written so the archetypes basketball fans give these players come out of
the data (tests/test_archetypes.py), not typed in.

The engine already plays every player by his real rates; the archetype is how the court moves him (where he
sets up, how he moves off the ball, whether he drives, how tight he guards, whether he crashes the glass)
and who the tactics pick for each role.
"""

from __future__ import annotations

from bisect import bisect_left

from hoopformer.game.model import ActionModel, PlayerProfile

ROTATION_MINUTES, ROTATION_GAMES = 20.0, 20

# Each archetype, in words (the page shows it under the player's name).
ARCHETYPES = {
    "Two-Way Scoring Dominator": "Takes over at both ends: scores at will, attacks the rim, hounds the ball.",
    "High-Volume Isolation Guard": "Wants the ball in his hands to beat his man one-on-one and pull up.",
    "All-Around Point Forward": "A forward who runs the offense: brings it up, passes, rebounds.",
    "Floor General": "Runs the offense and sets everyone up; pressures the ball on defense.",
    "Scoring Playmaker": "A lead guard who scores and creates for others in the same breath.",
    "Shot-Creating Wing": "Creates his own shot from the wing: jab steps, pull-ups, fadeaways.",
    "Slashing Wing": "Cuts and drives to the rim, finishes in traffic.",
    "3-and-D Wing": "Spaces the floor from the corners and locks up his man.",
    "Movement Shooter": "Never stops running off screens for catch-and-shoot jumpers.",
    "Gravity Shooter": "Shoots from anywhere: the defense bends to him beyond the arc.",
    "Stretch Big": "A big who pops out and shoots, pulling the other big from the rim.",
    "Pick-and-Roll Post Bruiser": "Sets bone-crushing screens, rolls hard and punishes in the post.",
    "Dominant Post Scorer": "Overpowers everyone on the block; lives at the rim and the line.",
    "Two-Way Post Anchor": "Scores in the post and protects the rim.",
    "Rim-Running Anchor": "Dives to the rim, finishes lobs, walls off the paint.",
    "Rebounding Specialist": "Owns the glass at both ends; rarely shoots.",
    "Energy Big": "Screens, rolls, rebounds: does the dirty work inside.",
    "Role Player": "Spaces the floor and moves the ball.",
}


def features(profile: PlayerProfile) -> dict[str, float]:
    """A player's per-chance rates: usage, shot mix, free throws, passing, rebounding, defense, shooting."""
    e = profile.events
    shots = e["rim"] + e["mid"] + e["three"]
    share = (lambda zone: e[zone] / shots) if shots else (lambda zone: 0.0)
    return {
        "usage": shots + e["free_throws"] + e["turnover"],
        "three": share("three"), "rim": share("rim"), "mid": share("mid"),
        "ftr": e["free_throws"] / shots if shots else 0.0,
        "ast": profile.assist, "oreb": profile.oreb, "dreb": profile.dreb,
        "stl": profile.steal, "blk": profile.block, "fg3": profile.make["three"],
    }


def percentiles(model: ActionModel) -> dict[int, dict[str, float]]:
    """Every player's percentile (0-100) on each feature among the rotation players."""
    pool = [features(p) for p in model.players.values() if p.minutes_per_game >= ROTATION_MINUTES and p.games >= ROTATION_GAMES]
    ranked = {k: sorted(f[k] for f in pool) for k in pool[0]}   # each feature's values, sorted: a percentile is a lookup
    return {pid: {k: 100.0 * bisect_left(ranked[k], v) / len(pool) for k, v in features(profile).items()}
            for pid, profile in model.players.items()}


def archetype(p: dict[str, float]) -> str:
    """The first rule that fits a player's percentiles (see the module docstring)."""
    use, ast, oreb, dreb, stl, blk = p["usage"], p["ast"], p["oreb"], p["dreb"], p["stl"], p["blk"]
    if oreb >= 95 and dreb >= 90 and use <= 25:
        return "Rebounding Specialist"
    if ast >= 95 and use <= 80:
        return "Floor General"
    if (ast >= 90 and dreb >= 70 and use >= 75) or (ast >= 75 and stl >= 95 and dreb >= 75 and use >= 80):
        return "All-Around Point Forward"
    if p["rim"] >= 98 and p["ftr"] >= 95 and use >= 95 and dreb >= 85:
        return "Dominant Post Scorer"
    if use >= 95 and dreb <= 30 and p["mid"] >= 80:
        return "High-Volume Isolation Guard"
    if use >= 95 and (stl >= 90 or blk >= 90) and dreb < 85:
        return "Two-Way Scoring Dominator"
    if blk >= 90 and dreb >= 85 and use >= 75:
        return "Two-Way Post Anchor"
    if blk >= 85 and dreb >= 80:
        return "Rim-Running Anchor"
    if dreb >= 80 and p["fg3"] >= 80:
        return "Stretch Big"
    if dreb >= 85 and p["rim"] >= 85 and p["ftr"] >= 85 and use >= 80:
        return "Pick-and-Roll Post Bruiser"
    if p["fg3"] >= 90 and ast <= 40 and use >= 40:
        return "Movement Shooter"
    if p["three"] >= 80 and use >= 80:
        return "Gravity Shooter"
    if p["three"] >= 75:
        return "3-and-D Wing"
    if use >= 80 and p["mid"] >= 65:
        return "Shot-Creating Wing"
    if ast >= 85 and use >= 75:
        return "Scoring Playmaker"
    if p["rim"] >= 80 and dreb < 80 and use >= 40:
        return "Slashing Wing"
    if dreb >= 75:
        return "Energy Big"
    return "Role Player"


def archetypes(model: ActionModel) -> dict[int, str]:
    """Every player's archetype."""
    return {pid: archetype(p) for pid, p in percentiles(model).items()}
