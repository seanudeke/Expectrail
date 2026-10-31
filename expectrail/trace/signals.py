"""Derived signals: the small vocabulary of game measurements the contracts and relations are built on.

Each signal is a number computed from one episode, or None when the episode cannot support it (the
recorder did not collect what it needs). They are the quantities the four reported bugs turned on:
how far the player rose above the floor it left, when bullets appeared, which way the sprite faced
while moving, how far an enemy dropped from where it settled. Nothing here judges; the interpreter
(expectrail/trace/evaluator.py) does.
"""
from __future__ import annotations

ENEMY_SETTLE_TICKS = 30
MOVING_PX_PER_TICK = 0.5
IMPULSE_PX_PER_TICK = 0.5   # an upward kick in one tick, well above anything gravity or a ceiling gives


def player_samples(ep: dict) -> list[dict]:
    return [s for s in ep["samples"] if s["player"] is not None]


def airborne_episodes(ep: dict) -> tuple[list[dict], bool]:
    """Anchored airborne spans: [{start, end, anchorY, maxRise, maxRiseTick}], and whether floor state was
    recorded at all. A span that begins before the first supported sample has no anchor and is skipped."""
    samples = player_samples(ep)
    if not any(s["onFloor"] is not None for s in samples):
        return [], False
    spans: list[dict] = []
    anchor = None
    current = None
    for s in samples:
        on = s["onFloor"]
        if on is None:
            continue
        y = s["player"][1]
        if on:
            if current is not None:
                current["end"] = s["tick"]
                spans.append(current)
                current = None
            anchor = y
            continue
        if anchor is None:
            continue  # left-censored: never seen standing
        if current is None:
            current = {"start": s["tick"], "end": None, "anchorY": anchor, "maxRise": 0.0, "maxRiseTick": s["tick"]}
        rise = anchor - y  # world y grows downward
        if rise > current["maxRise"]:
            current["maxRise"], current["maxRiseTick"] = rise, s["tick"]
    if current is not None:
        spans.append(current)  # right-censored: still airborne at the end
    return spans, True


def max_rise_px(ep: dict) -> float | None:
    spans, recorded = airborne_episodes(ep)
    if not recorded:
        return None
    return round(max((sp["maxRise"] for sp in spans), default=0.0), 2)


def air_jumps(ep: dict) -> int | None:
    """The most upward kicks in one airborne span: ticks where the player's vertical motion turns sharply
    upward while it is already in the air. Gravity only ever turns it downward, a ceiling stops it, and
    a released jump slows the rise, so a kick mid-air is a jump made in the air."""
    spans, recorded = airborne_episodes(ep)
    if not recorded:
        return None
    y = {s["tick"]: s["player"][1] for s in player_samples(ep)}
    worst = 0
    for sp in spans:
        end = sp["end"] if sp["end"] is not None else max(y)
        kicks = 0
        for t in range(sp["start"] + 1, end):
            if t in y and t - 1 in y and t - 2 in y:
                if (y[t] - y[t - 1]) - (y[t - 1] - y[t - 2]) < -IMPULSE_PX_PER_TICK:
                    kicks += 1
        worst = max(worst, kicks)
    return worst


def airborne_ticks(ep: dict) -> int | None:
    samples = player_samples(ep)
    if not any(s["onFloor"] is not None for s in samples):
        return None
    return sum(1 for s in samples if s["onFloor"] is False)


def spawn_ticks(ep: dict) -> list[int] | None:
    if ep["capabilities"]["projectiles"] == "unknown" and not any(e["type"] == "projectile_spawn" for e in ep["events"]):
        return None
    return [e["tick"] for e in ep["events"] if e["type"] == "projectile_spawn"]


def projectile_count(ep: dict) -> int | None:
    if ep["capabilities"]["projectiles"] == "unknown":
        return None  # an empty tick cannot prove that no bullet was fired
    return len(spawn_ticks(ep) or [])


def min_projectile_interval_ticks(ep: dict) -> int | None:
    ticks = spawn_ticks(ep) or []
    if len(ticks) < 2:
        return None
    return min(b - a for a, b in zip(ticks, ticks[1:]))


def facing_flips(ep: dict) -> int | None:
    faced = [s["facing"] for s in ep["samples"] if s["facing"] is not None]
    if not faced:
        return None
    return sum(1 for a, b in zip(faced, faced[1:]) if a != b)


def facing_mismatch_fraction(ep: dict) -> float | None:
    samples = player_samples(ep)
    moving = mismatched = 0
    for a, b in zip(samples, samples[1:]):
        if b["facing"] is None:
            continue
        dx = b["player"][0] - a["player"][0]
        if abs(dx) < MOVING_PX_PER_TICK:
            continue
        moving += 1
        if b["facing"] != (1 if dx > 0 else -1):
            mismatched += 1
    if not moving:
        return None
    return round(mismatched / moving, 4)


def enemy_tracks(ep: dict) -> dict[int, list[tuple[int, float, float]]] | None:
    if ep["capabilities"]["enemies"] == "unknown" and not any(s["enemies"] for s in ep["samples"]):
        return None
    tracks: dict[int, list[tuple[int, float, float]]] = {}
    for s in ep["samples"]:
        for eid, x, y in s["enemies"] or []:
            tracks.setdefault(eid, []).append((s["tick"], x, y))
    return tracks


def max_enemy_drop_px(ep: dict, settle_ticks: int = ENEMY_SETTLE_TICKS) -> float | None:
    tracks = enemy_tracks(ep)
    if not tracks:
        return None
    worst = None
    for track in tracks.values():
        settled = [y for t, _x, y in track if t >= track[0][0] + settle_ticks]
        if settled:
            drop = max(settled) - settled[0]
            worst = drop if worst is None else max(worst, drop)
    return round(worst, 2) if worst is not None else None


def min_enemy_extent_px(ep: dict) -> float | None:
    tracks = enemy_tracks(ep)
    if not tracks:
        return None
    return round(min(max(p[1] for p in t) - min(p[1] for p in t) for t in tracks.values()), 2)


def enemies_at_end(ep: dict) -> int | None:
    if ep["capabilities"]["enemies"] == "unknown":
        return None
    last = ep["samples"][-1]["enemies"]
    return len(last) if last is not None else None


def player_dx_px(ep: dict) -> float | None:
    samples = player_samples(ep)
    if len(samples) < 2:
        return None
    return round(samples[-1]["player"][0] - samples[0]["player"][0], 2)


SIGNALS = {
    "max_rise_px": max_rise_px,
    "projectile_count": projectile_count,
    "min_projectile_interval_ticks": min_projectile_interval_ticks,
    "facing_flips": facing_flips,
    "facing_mismatch_fraction": facing_mismatch_fraction,
    "max_enemy_drop_px": max_enemy_drop_px,
    "min_enemy_extent_px": min_enemy_extent_px,
    "enemies_at_end": enemies_at_end,
    "player_dx_px": player_dx_px,
    "airborne_ticks": airborne_ticks,
    "air_jumps": air_jumps,
}


def summary(ep: dict) -> dict:
    """Every signal for one episode: what a planner or reviewer is shown instead of raw frames."""
    return {name: fn(ep) for name, fn in SIGNALS.items()}
