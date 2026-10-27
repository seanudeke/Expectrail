"""Verifier-side gameplay checks from harness/fixture traces (not SAM observations).

Smoke-route contracts (docs/evaluation.md): clean play moves ~485 world-x, ends on
the floor, and never sustains below-ground. Freeze / gravity-off / short-walk fail.

Harness uses MIN_DELTA_X_HARNESS (slack under the ~485 clean measurement). Offline
fixtures use MIN_DELTA_X_FIXTURE so Gate1 synthetic walks (Δx≈290) still pass while
freeze (Δx≈0) fails. Same predicate function for both — only the threshold differs.
"""
from __future__ import annotations

from typing import Any

# Clean smoke: x ≈ 90 → ≈ 575 (Δx ≈ 485). Slack for software renders / FPS jitter.
MIN_DELTA_X_HARNESS = 400.0
# Offline fixtures (obs-fixed / trace-fixed): Δx ≈ 290.
MIN_DELTA_X_FIXTURE = 200.0
FLOOR_TOLERANCE_PAD = 12.0
END_ON_FLOOR_LAST_N = 1
BELOW_GROUND_STREAK = 3

REASON_DELTA = "player delta-x below minimum (freeze or short walk)"
REASON_END_FLOOR = "player not on floor at end of route"
REASON_BELOW = "player sustained below ground"
REASON_EMPTY = "no player samples in trace"
REASON_MALFORMED = "malformed player sample in trace"


def samples_from_trace(trace: dict) -> list[dict[str, Any]]:
    """Extract {tick, x, y, onFloor} from harness trace rows."""
    samples: list[dict[str, Any]] = []
    for row in trace.get("rows") or []:
        player = row.get("player")
        if player is None:
            samples.append({
                "tick": int(row.get("tick", len(samples))),
                "x": None,
                "y": None,
                "onFloor": bool(row.get("onFloor", False)),
            })
            continue
        if not isinstance(player, (list, tuple)) or len(player) < 2:
            raise ValueError(REASON_MALFORMED)
        samples.append({
            "tick": int(row.get("tick", len(samples))),
            "x": float(player[0]),
            "y": float(player[1]),
            "onFloor": bool(row.get("onFloor", False)),
        })
    return samples


def floor_y(samples: list[dict[str, Any]]) -> float | None:
    """Lowest walkable surface in y-down space (max on-floor y).

    Fail-closed: if no onFloor samples exist, return None so end-on-floor /
    below-ground cannot vacuous-pass a gravity-off freefall.
    """
    on_floor = [
        s["y"] for s in samples
        if s.get("x") is not None and s.get("onFloor") and s.get("y") is not None
    ]
    return float(max(on_floor)) if on_floor else None


def check_motion(
    samples: list[dict[str, Any]],
    *,
    min_delta_x: float,
    floor_tol: float = FLOOR_TOLERANCE_PAD,
    end_last_n: int = END_ON_FLOOR_LAST_N,
    below_streak: int = BELOW_GROUND_STREAK,
) -> dict:
    """Judge smoke gameplay from ordered samples. Fail-closed on empty/malformed."""
    present = [s for s in samples if s.get("x") is not None and s.get("y") is not None]
    if not present:
        return _fail(REASON_EMPTY, {"deltaX": 0.0, "sampleCount": 0})

    first, last = present[0], present[-1]
    delta_x = float(last["x"] - first["x"])
    floor = floor_y(samples)
    metrics = {
        "deltaX": delta_x,
        "minDeltaX": float(min_delta_x),
        "firstX": float(first["x"]),
        "lastX": float(last["x"]),
        "lastY": float(last["y"]),
        "floorY": floor,
        "sampleCount": len(present),
        "endOnFloor": False,
        "belowStreak": 0,
    }

    if delta_x + 1e-9 < float(min_delta_x):
        return _fail(REASON_DELTA, metrics)

    # End-on-floor: last N present samples must be onFloor or within pad of floor y
    # (y-down: floating above or sunk below both fail when onFloor is false).
    tail = present[-max(end_last_n, 1):]
    end_ok = True
    for s in tail:
        if s.get("onFloor"):
            continue
        if floor is None or abs(float(s["y"]) - float(floor)) > floor_tol:
            end_ok = False
            break
    metrics["endOnFloor"] = end_ok
    if not end_ok:
        return _fail(REASON_END_FLOOR, metrics)

    # Sustained below-ground (y-down: y > floor + tol).
    streak = 0
    max_streak = 0
    if floor is not None:
        for s in present:
            if float(s["y"]) > float(floor) + floor_tol:
                streak += 1
                max_streak = max(max_streak, streak)
            else:
                streak = 0
    metrics["belowStreak"] = max_streak
    if max_streak >= below_streak:
        return _fail(REASON_BELOW, metrics)

    return {
        "result": "pass",
        "reason": (
            f"player moved {delta_x:.1f}px (min {min_delta_x:.1f}), "
            f"ended on floor, no sustained below-ground"
        ),
        "metrics": metrics,
    }


def judge_trace(trace: dict, *, min_delta_x: float) -> dict:
    """Convenience: samples_from_trace + check_motion, wrapping ValueError as fail."""
    try:
        samples = samples_from_trace(trace)
    except ValueError as exc:
        return _fail(str(exc), {"deltaX": 0.0, "sampleCount": 0})
    return check_motion(samples, min_delta_x=min_delta_x)


def _fail(reason: str, metrics: dict) -> dict:
    return {"result": "fail", "reason": reason, "metrics": metrics}
