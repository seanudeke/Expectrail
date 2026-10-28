"""Observations providers: trace stand-in today; SAM 3.1 seam for Gate 2.

Default provider ``trace`` builds nightshift.observations/v0 from harness
trace.json world positions (y-down boxes). Set ``NIGHTSHIFT_OBS_PROVIDER=sam``
(or pass provider=\"sam\") once Zayyad's SAM adapter is installed — verifier and
loop call ``load_observations`` / ``from_trace`` through this module only.

Gameplay motion is still judged by agents.gameplay from the harness/fixture
trace; SAM replaces the position-log stand-in for the observations document.
"""
from __future__ import annotations

import importlib
import os
from typing import Callable

from nightshift.contracts import digest

PLAYER_HALF_W = 20.0
PLAYER_H = 60.0
GROUND_DEPTH = 400.0
# never-crosses tolerance is in the same units as these boxes (world px).
FLOOR_TOLERANCE_PAD = 12.0

PROVIDER_ENV = "NIGHTSHIFT_OBS_PROVIDER"
DEFAULT_PROVIDER = "trace"


def _floor_y(rows: list[dict]) -> float:
    """Lowest walkable surface in y-down space (max on-floor y).

    Median of all on-floor samples skews upward when the smoke route lands on
    platforms, which makes standing on the real ground look like fall-through.
    """
    samples = [
        float(r["player"][1])
        for r in rows
        if r.get("player") is not None and r.get("onFloor") is True
    ]
    if samples:
        return float(max(samples))
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


def from_trace_synthetic(
    trace: dict,
    replay_sha256: str = "0" * 64,
    fps: int = 60,
    physics_tps: int | None = None,
) -> dict:
    """Build nightshift.observations/v0 from a harness trace (position-log stand-in).

    Physics is 120 Hz and capture is 60 fps, so frame n ≈ after tick 2n (every other tick).
    """
    rows = list(trace.get("rows") or [])
    tps = physics_tps or int(trace.get("physicsTicksPerSecond") or 120)
    step = max(tps // fps, 1)
    floor = _floor_y(rows)
    start_x = _start_x(rows)
    ground = [start_x - 200.0, floor, start_x + 2000.0, floor + GROUND_DEPTH]

    frames = []
    for row in rows:
        tick = int(row["tick"])
        if tick % step != 0:
            continue
        frame_n = tick // step
        player = row.get("player")
        objects: dict = {
            "ground": [{"box": list(ground), "score": 0.95, "track": 2}],
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
            },
        },
        "frames": frames,
    }


def _load_sam_provider() -> Callable[..., dict]:
    """Import Zayyad's SAM adapter when present.

    Expected module: ``agents.sam_observations`` with ``from_replay(...)`` matching
    ``from_trace_synthetic`` kwargs (trace may be unused; frames/dir preferred).
    """
    try:
        mod = importlib.import_module("agents.sam_observations")
    except ImportError as exc:
        raise SystemExit(
            f"{PROVIDER_ENV}=sam but agents.sam_observations is not installed "
            f"(pair with Zayyad). Import error: {exc}"
        ) from exc
    fn = getattr(mod, "from_replay", None) or getattr(mod, "from_trace", None)
    if not callable(fn):
        raise SystemExit(
            "agents.sam_observations must export from_replay(trace, ...) or from_trace(...)"
        )
    return fn


def resolve_provider(name: str | None = None) -> str:
    raw = (name or os.environ.get(PROVIDER_ENV) or DEFAULT_PROVIDER).strip().lower()
    if raw not in ("trace", "sam"):
        raise SystemExit(f"unknown observations provider {raw!r} (want trace|sam)")
    return raw


def from_trace(
    trace: dict,
    replay_sha256: str = "0" * 64,
    fps: int = 60,
    physics_tps: int | None = None,
    *,
    provider: str | None = None,
    frames_dir: str | None = None,
) -> dict:
    """Dispatch to the configured observations provider.

    ``provider=trace`` (default): synthetic boxes from the position log.
    ``provider=sam``: delegates to ``agents.sam_observations`` once wired.
    """
    kind = resolve_provider(provider)
    if kind == "trace":
        return from_trace_synthetic(
            trace, replay_sha256=replay_sha256, fps=fps, physics_tps=physics_tps,
        )
    sam = _load_sam_provider()
    kwargs = {
        "replay_sha256": replay_sha256,
        "fps": fps,
        "physics_tps": physics_tps,
        "frames_dir": frames_dir,
    }
    try:
        return sam(trace, **kwargs)
    except TypeError as exc:
        # Only strip frames_dir when the adapter rejects that kwarg.
        if frames_dir is None or "frames_dir" not in str(exc):
            raise
        kwargs.pop("frames_dir")
        return sam(trace, **kwargs)


def observations_digest(doc: dict) -> str:
    return digest(doc)
