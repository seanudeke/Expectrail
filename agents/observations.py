"""Trace-backed synthetic observations until SAM 3.1 is wired (Gate 1 seam).

Uses harness trace.json world positions as boxes in y-down space. Floor height and
the gameplay goal are calibrated from on-floor samples in the same trace so Linux
CI and local software renders stay consistent without a hand-tuned screen map.
"""
from __future__ import annotations

from statistics import median

from nightshift.contracts import digest

PLAYER_HALF_W = 20.0
PLAYER_H = 60.0
GROUND_DEPTH = 400.0
# never-crosses tolerance is in the same units as these boxes (world px).
FLOOR_TOLERANCE_PAD = 12.0
# Gameplay: player must get near a goal placed ahead of the starting on-floor x.
GOAL_AHEAD = 400.0
GOAL_HALF = 40.0


def _floor_y(rows: list[dict]) -> float:
    samples = [
        float(r["player"][1])
        for r in rows
        if r.get("player") is not None and r.get("onFloor") is True
    ]
    if samples:
        return float(median(samples))
    # Fall-through-only traces: use the earliest player y as a standing guess.
    for r in rows:
        if r.get("player") is not None:
            return float(r["player"][1])
    return 452.0


def _start_x(rows: list[dict]) -> float:
    for r in rows:
        if r.get("player") is not None and r.get("onFloor") is True:
            return float(r["player"][0])
    for r in rows:
        if r.get("player") is not None:
            return float(r["player"][0])
    return 210.0


def _player_box(x: float, y: float) -> list[float]:
    return [x - PLAYER_HALF_W, y - PLAYER_H, x + PLAYER_HALF_W, y]


def from_trace(trace: dict, replay_sha256: str = "0" * 64, fps: int = 60,
               physics_tps: int | None = None) -> dict:
    """Build nightshift.observations/v0 from a harness trace.

    Physics is 120 Hz and capture is 60 fps, so frame n ≈ after tick 2n (every other tick).
    """
    rows = list(trace.get("rows") or [])
    tps = physics_tps or int(trace.get("physicsTicksPerSecond") or 120)
    step = max(tps // fps, 1)
    floor = _floor_y(rows)
    start_x = _start_x(rows)
    ground = [start_x - 200.0, floor, start_x + 2000.0, floor + GROUND_DEPTH]
    goal = [
        start_x + GOAL_AHEAD - GOAL_HALF,
        floor - PLAYER_H,
        start_x + GOAL_AHEAD + GOAL_HALF,
        floor + FLOOR_TOLERANCE_PAD,
    ]

    frames = []
    for row in rows:
        tick = int(row["tick"])
        if tick % step != 0:
            continue
        frame_n = tick // step
        player = row.get("player")
        objects: dict = {
            "ground": [{"box": list(ground), "score": 0.95, "track": 2}],
            "goal": [{"box": list(goal), "score": 0.9, "track": 3}],
        }
        if player is None:
            objects["player"] = []
        else:
            x, y = float(player[0]), float(player[1])
            box = _player_box(x, y)
            # Far below the camera / level → treat as missing (off-screen).
            if y > floor + 800:
                objects["player"] = []
            else:
                objects["player"] = [{"box": box, "score": 0.94, "track": 1}]
        frames.append({"frame": frame_n, "objects": objects})

    return {
        "format": "nightshift.observations/v0",
        "replay": {"sha256": replay_sha256},
        "model": {
            "name": "nightshift.trace-synthetic",
            "prompts": {
                "player": "small robot character",
                "ground": "grass-topped ground",
                "goal": "route end marker",
            },
        },
        "frames": frames,
    }


def observations_digest(doc: dict) -> str:
    return digest(doc)
