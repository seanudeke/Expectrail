"""Engine-record checks: rules about the game judged on the harness trace, not on a model's view.

The harness records, on every physics tick, where the robot is and which way its sprite faces,
where every enemy is, and where every bullet is (harness/godot/expectrail_harness.gd). These
checks read that record. Each one states a rule of the game in one sentence, and each one decides
deterministically: pass, fail, or needs-review when the trace lacks what the rule needs (a missing
record is never a pass).

They were written for the reported bugs in bugs/reported/ after those bugs were reproduced, so
they are development checks, not blind ones (bugs/reported/README.md). They run in the
reported-bug bench (agents/reported_bench.py); the verifier does not use them yet.

The numbers come from the game's own constants (player/player.gd, player/gun.gd and the scenes):
  - a jump starts at 725 px/s against gravity 2100 px/s^2, so it rises about 125 px, and a double
    jump started at the top of the first rises about 250 px in all;
  - the gun's cooldown timer is 0.3 s;
  - level tiles are 64 px.
"""
from __future__ import annotations

from typing import Any

MAX_RISE_PX = 260.0          # a full double jump rises about 250 px
MOVING_PX_PER_TICK = 0.5     # at 120 ticks per second, 60 px/s: walking, not drifting
MAX_FACING_MISMATCH_TICKS = 6
SHOT_LOOK_AHEAD_TICKS = 6
MIN_SHOT_TRAVEL_PX = 3.0     # a bullet that hits a wall at once says nothing about its direction
MIN_SHOT_INTERVAL_S = 0.25   # the cooldown is 0.3 s
MAX_ENEMY_DROP_PX = 64.0     # one tile
ENEMY_SETTLE_TICKS = 30      # enemies are placed a few px above the floor and settle at the start

CHECKS: dict[str, str] = {
    "jump-height": "The robot never rises more than 260 px above the floor it last stood on.",
    "facing-follows-motion": "While the robot walks left or right, it faces the way it walks.",
    "shots-follow-facing": "A bullet travels the way the robot faced when it fired.",
    "fire-rate": "The gun fires at most once every 0.25 seconds.",
    "enemies-stay-up": "No enemy falls more than one tile (64 px) below where it settled.",
}


def _result(result: str, reason: str, **metrics: Any) -> dict:
    return {"result": result, "reason": reason, "metrics": metrics}


def _rows(trace: dict) -> list[dict]:
    return [r for r in trace.get("rows") or [] if isinstance(r, dict)]


def jump_height(trace: dict, max_rise: float = MAX_RISE_PX) -> dict:
    takeoff = None
    worst = 0.0
    worst_tick = None
    for row in _rows(trace):
        player = row.get("player")
        if not player:
            continue
        y = float(player[1])
        if row.get("onFloor"):
            takeoff = y
            continue
        if takeoff is not None and takeoff - y > worst:
            worst, worst_tick = takeoff - y, row.get("tick")
    if takeoff is None:
        return _result("needs-review", "the robot never stood on a floor in this trace")
    if worst > max_rise:
        return _result("fail", f"the robot rose {worst:.0f} px above the floor it left (max {max_rise:.0f}), "
                       f"highest at tick {worst_tick}", maxRise=round(worst, 1), tick=worst_tick)
    return _result("pass", f"highest rise {worst:.0f} px (max {max_rise:.0f})", maxRise=round(worst, 1))


def facing_follows_motion(trace: dict, max_mismatch: int = MAX_FACING_MISMATCH_TICKS) -> dict:
    rows = [r for r in _rows(trace) if r.get("player")]
    if not any("facing" in r for r in rows):
        return _result("needs-review", "the trace has no facing record")
    moving = mismatched = 0
    first = None
    for prev, row in zip(rows, rows[1:]):
        dx = float(row["player"][0]) - float(prev["player"][0])
        if abs(dx) < MOVING_PX_PER_TICK or "facing" not in row:
            continue
        moving += 1
        if int(row["facing"]) != (1 if dx > 0 else -1):
            mismatched += 1
            first = row.get("tick") if first is None else first
    if mismatched >= max_mismatch:
        return _result("fail", f"the robot faced away from where it walked on {mismatched} of {moving} moving ticks "
                       f"(first at tick {first})", movingTicks=moving, mismatchedTicks=mismatched)
    return _result("pass", f"faced the way it walked on {moving - mismatched} of {moving} moving ticks",
                   movingTicks=moving, mismatchedTicks=mismatched)


def _projectile_tracks(rows: list[dict]) -> dict[int, list[tuple[int, float, float]]]:
    tracks: dict[int, list[tuple[int, float, float]]] = {}
    for row in rows:
        for pid, x, y in row.get("projectiles") or []:
            tracks.setdefault(int(pid), []).append((int(row["tick"]), float(x), float(y)))
    return tracks


def shots_follow_facing(trace: dict) -> dict:
    rows = _rows(trace)
    tracks = _projectile_tracks(rows)
    if not tracks:
        return _result("pass", "no shots fired on this route", shots=0)
    facing_at = {int(r["tick"]): int(r["facing"]) for r in rows if "facing" in r}
    if not facing_at:
        return _result("needs-review", "shots were fired but the trace has no facing record")
    judged = wrong = 0
    first = None
    for _pid, track in sorted(tracks.items()):
        t0, x0, _ = track[0]
        later = [p for p in track if p[0] <= t0 + SHOT_LOOK_AHEAD_TICKS]
        dx = later[-1][1] - x0
        facing = facing_at.get(t0, facing_at.get(t0 - 1))
        if facing is None or abs(dx) < MIN_SHOT_TRAVEL_PX:
            continue
        judged += 1
        if (1 if dx > 0 else -1) != facing:
            wrong += 1
            first = t0 if first is None else first
    if wrong:
        return _result("fail", f"{wrong} of {judged} bullets went the other way from where the robot faced "
                       f"(first fired at tick {first})", shots=len(tracks), judged=judged, wrong=wrong)
    if not judged:
        return _result("pass", f"{len(tracks)} shots, none travelled far enough to judge", shots=len(tracks))
    return _result("pass", f"all {judged} judged bullets went the way the robot faced", shots=len(tracks),
                   judged=judged)


def fire_rate(trace: dict, min_interval_s: float = MIN_SHOT_INTERVAL_S) -> dict:
    tps = float(trace.get("physicsTicksPerSecond") or 0)
    tracks = _projectile_tracks(_rows(trace))
    if len(tracks) < 2:
        return _result("pass", f"{len(tracks)} shot(s) on this route", shots=len(tracks))
    if tps <= 0:
        return _result("needs-review", "the trace does not say how many ticks make a second")
    fired = sorted(track[0][0] for track in tracks.values())
    gap = min(b - a for a, b in zip(fired, fired[1:])) / tps
    if gap < min_interval_s:
        return _result("fail", f"two shots {gap:.2f} s apart (min {min_interval_s:.2f} s); {len(fired)} shots",
                       shots=len(fired), minIntervalS=round(gap, 3))
    return _result("pass", f"{len(fired)} shots, at least {gap:.2f} s apart", shots=len(fired),
                   minIntervalS=round(gap, 3))


def enemies_stay_up(trace: dict, max_drop: float = MAX_ENEMY_DROP_PX) -> dict:
    rows = _rows(trace)
    tracks: dict[int, list[tuple[int, float]]] = {}
    for row in rows:
        for eid, _x, y in row.get("enemies") or []:
            tracks.setdefault(int(eid), []).append((int(row["tick"]), float(y)))
    if not tracks:
        return _result("needs-review", "the trace has no enemy record")
    worst = 0.0
    worst_id = None
    for eid, track in tracks.items():
        settled = [y for t, y in track if t >= track[0][0] + ENEMY_SETTLE_TICKS]
        if not settled:
            continue
        drop = max(settled) - settled[0]
        if drop > worst:
            worst, worst_id = drop, eid
    if worst > max_drop:
        return _result("fail", f"enemy {worst_id} fell {worst:.0f} px below where it settled (max {max_drop:.0f})",
                       enemies=len(tracks), maxDrop=round(worst, 1))
    return _result("pass", f"{len(tracks)} enemies, largest drop {worst:.0f} px", enemies=len(tracks),
                   maxDrop=round(worst, 1))


# Guard kinds: parameterized rules a guard file names with its own thresholds. A guard catches a fix
# that stops a bug by removing what the game is meant to do (the double jump, the gun, the
# enemies' patrol). The kinds are public; which guard applies to which bug, on which route and with
# which threshold, lives with the held-out set (agents/reported_trial.py), so the fixer never sees it.


def rises_at_least(trace: dict, min_px: float) -> dict:
    """The robot rises at least ``min_px`` above the floor it last stood on, at least once."""
    verdict = jump_height(trace, max_rise=float("inf"))
    if verdict["result"] == "needs-review":
        return verdict
    rise = verdict["metrics"]["maxRise"]
    if rise < min_px:
        return _result("fail", f"the robot never rose more than {rise:.0f} px above its floor (needs {min_px:.0f})",
                       maxRise=rise)
    return _result("pass", f"rose {rise:.0f} px (needs {min_px:.0f})", maxRise=rise)


def shots_at_least(trace: dict, minimum: int) -> dict:
    """At least ``minimum`` bullets are fired on the route."""
    n = len(_projectile_tracks(_rows(trace)))
    if n < minimum:
        return _result("fail", f"{n} bullets fired (needs {minimum})", shots=n)
    return _result("pass", f"{n} bullets fired (needs {minimum})", shots=n)


def shots_move(trace: dict, min_px: float, within_ticks: int = SHOT_LOOK_AHEAD_TICKS) -> dict:
    """Every bullet travels at least ``min_px`` sideways within ``within_ticks`` of being fired."""
    tracks = _projectile_tracks(_rows(trace))
    if not tracks:
        return _result("needs-review", "no bullets fired, so none could be seen to move", shots=0)
    slow = []
    for pid, track in sorted(tracks.items()):
        t0, x0, _ = track[0]
        later = [p for p in track if p[0] <= t0 + within_ticks]
        if len(later) < 2:
            continue  # gone at once (hit something): says nothing about its speed
        if abs(later[-1][1] - x0) < min_px:
            slow.append(t0)
    if slow:
        return _result("fail", f"{len(slow)} of {len(tracks)} bullets moved less than {min_px:.0f} px in "
                       f"{within_ticks} ticks (first fired at tick {slow[0]})", shots=len(tracks), slow=len(slow))
    return _result("pass", f"all {len(tracks)} bullets moved at least {min_px:.0f} px", shots=len(tracks))


def _enemy_tracks(trace: dict) -> dict[int, list[tuple[int, float, float]]]:
    tracks: dict[int, list[tuple[int, float, float]]] = {}
    for row in _rows(trace):
        for eid, x, y in row.get("enemies") or []:
            tracks.setdefault(int(eid), []).append((int(row["tick"]), float(x), float(y)))
    return tracks


def enemies_remain(trace: dict, minimum: int) -> dict:
    """At least ``minimum`` enemies are still in the game on the route's last tick."""
    rows = _rows(trace)
    if not rows:
        return _result("needs-review", "the trace has no rows")
    last = len(rows[-1].get("enemies") or [])
    if last < minimum:
        return _result("fail", f"{last} enemies left at the end (needs {minimum})", enemies=last)
    return _result("pass", f"{last} enemies at the end (needs {minimum})", enemies=last)


def enemies_patrol(trace: dict, min_px: float) -> dict:
    """Every enemy covers at least ``min_px`` sideways over the route."""
    tracks = _enemy_tracks(trace)
    if not tracks:
        return _result("needs-review", "the trace has no enemy record")
    spans = {eid: max(p[1] for p in t) - min(p[1] for p in t) for eid, t in tracks.items()}
    still = sorted(eid for eid, span in spans.items() if span < min_px)
    if still:
        return _result("fail", f"{len(still)} of {len(spans)} enemies moved less than {min_px:.0f} px sideways",
                       enemies=len(spans), minSpan=round(min(spans.values()), 1))
    return _result("pass", f"all {len(spans)} enemies moved at least {min_px:.0f} px sideways",
                   enemies=len(spans), minSpan=round(min(spans.values()), 1))


GUARD_KINDS = {
    "rises-at-least": lambda trace, p: rises_at_least(trace, float(p["minPx"])),
    "shots-at-least": lambda trace, p: shots_at_least(trace, int(p["min"])),
    "shots-move": lambda trace, p: shots_move(trace, float(p["minPx"]), int(p.get("withinTicks", SHOT_LOOK_AHEAD_TICKS))),
    "enemies-remain": lambda trace, p: enemies_remain(trace, int(p["min"])),
    "enemies-patrol": lambda trace, p: enemies_patrol(trace, float(p["minPx"])),
}


def judge_guard(trace: dict, guard: dict) -> dict:
    """One guard (``{"kind": ..., <its thresholds>}``) on one trace."""
    kind = guard.get("kind")
    if kind not in GUARD_KINDS:
        return _result("needs-review", f"unknown guard kind {kind!r}")
    return GUARD_KINDS[kind](trace, guard)


RULES = {
    "jump-height": jump_height,
    "facing-follows-motion": facing_follows_motion,
    "shots-follow-facing": shots_follow_facing,
    "fire-rate": fire_rate,
    "enemies-stay-up": enemies_stay_up,
}


def judge_all(trace: dict) -> dict[str, dict]:
    """Every engine-record check on one trace."""
    return {name: rule(trace) for name, rule in RULES.items()}
