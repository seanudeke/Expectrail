"""Observations providers: trace stand-in by default; SAM 3.1 when asked.

Default provider ``trace`` builds nightshift.observations/v0 from harness
trace.json world positions (y-down boxes). Set ``NIGHTSHIFT_OBS_PROVIDER=sam``
(or pass provider=\"sam\") to use SAM 3.1 through the Meta Model API
(``agents.sam_observations``, docs/sam.md). Verifier and loop call ``from_trace``
through this module only.

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
# Where the player's feet are relative to its origin, measured on the clean game (its collision
# rectangle's bottom edge). A constant on purpose: a bug that moves or shrinks the player's own
# collision shape must not move the yardstick it is judged by.
FEET_OFFSET = 13.25

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

    When the harness logged the level's ground line (``ground`` on each row), the ground box sits
    on it and the player's box ends at its feet (origin + FEET_OFFSET). Older traces without it
    fall back to taking the floor from the player's own on-floor positions, which cannot see a
    player that rests too low.
    """
    rows = list(trace.get("rows") or [])
    tps = physics_tps or int(trace.get("physicsTicksPerSecond") or 120)
    step = max(tps // fps, 1)
    floor = _floor_y(rows)
    start_x = _start_x(rows)
    ground = [start_x - 200.0, floor, start_x + 2000.0, floor + GROUND_DEPTH]
    level_ground = any(r.get("ground") is not None for r in rows)

    frames = []
    for row in rows:
        tick = int(row["tick"])
        if tick % step != 0:
            continue
        frame_n = tick // step
        player = row.get("player")
        if level_ground:
            g = row.get("ground")
            x0 = float(player[0]) if player is not None else start_x
            objects: dict = {"ground": [] if g is None else [
                {"box": [x0 - 2000.0, float(g), x0 + 2000.0, float(g) + GROUND_DEPTH], "score": 0.95, "track": 2}]}
        else:
            objects = {"ground": [{"box": list(ground), "score": 0.95, "track": 2}]}
        if player is None:
            objects["player"] = []
        else:
            x, y = float(player[0]), float(player[1])
            box = _player_box(x, y + FEET_OFFSET) if level_ground else _player_box(x, y)
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
                "player": "blue robot",
                "ground": "grass-topped ground",
            },
            "ground": "level tile geometry (harness)" if level_ground else "player's own on-floor positions",
        },
        "frames": frames,
    }


def _load_sam_provider() -> Callable[..., dict]:
    """Import the SAM 3.1 adapter (``agents.sam_observations``, Meta Model API).

    ``from_replay(...)`` takes ``from_trace_synthetic``'s kwargs plus ``frames_dir`` and
    ``spec`` (prompts, window, sampling); the trace itself is unused there.
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
    spec: dict | None = None,
    engine_objects: dict | None = None,
) -> dict:
    """Dispatch to the configured observations provider.

    ``provider=trace`` (default): synthetic boxes from the position log; ``spec`` is ignored.
    ``provider=sam``: ``agents.sam_observations`` (SAM 3.1 over the captured frames). A SAM
    failure surfaces as SystemExit, which the verifier turns into needs-review for the candidate,
    clean and held-out checks; it is never a pass.
    """
    kind = resolve_provider(provider)
    if kind == "trace":
        return from_trace_synthetic(
            trace, replay_sha256=replay_sha256, fps=fps, physics_tps=physics_tps,
        )
    sam = _load_sam_provider()
    sam_error = getattr(importlib.import_module("agents.sam_observations"), "SamError", None)
    catch = sam_error if isinstance(sam_error, type) and issubclass(sam_error, Exception) else ()

    kwargs = {
        "replay_sha256": replay_sha256,
        "fps": fps,
        "physics_tps": physics_tps,
        "frames_dir": frames_dir,
        "spec": spec,
    }
    if engine_objects is not None:
        kwargs["engine_objects"] = engine_objects
    while True:
        try:
            return sam(trace, **kwargs)
        except catch as exc:
            raise SystemExit(f"sam observations unavailable: {exc}") from exc
        except TypeError as exc:
            # An older adapter may not take every kwarg; drop only the one it rejects.
            dropped = next((k for k in ("engine_objects", "spec", "frames_dir")
                            if k in kwargs and f"'{k}'" in str(exc)), None)
            if dropped is None:
                raise
            kwargs.pop(dropped)


def observations_digest(doc: dict) -> str:
    return digest(doc)


def engine_ground_by_frame(trace: dict, frame_size: tuple[int, int], frames: list[int],
                           fps: int = 60) -> dict[int, dict]:
    """The level's ground line for each captured frame, in that frame's pixels.

    Built from the harness's ``ground`` (world y of the tile surface under the player) and
    ``view`` (world to frame pixels) on the last physics tick before the frame was drawn; the very
    first frame takes the camera from the next tick, since the camera only settles on frame 0.
    Returns {frame: {"ground": [box]}}, with an empty list when the engine logged no ground then.
    """
    rows = list(trace.get("rows") or [])
    tps = int(trace.get("physicsTicksPerSecond") or 120)
    step = max(tps // fps, 1)
    width, height = frame_size
    out: dict[int, dict] = {}
    for n in frames:
        tick = n * step + step - 1
        if tick >= len(rows):
            continue
        row = rows[tick]
        view = row.get("view")
        if view and view[4] == 0 and view[5] == 0 and tick + 1 < len(rows):
            view = rows[tick + 1].get("view") or view  # camera not placed yet on the first draw
        g = row.get("ground")
        if g is None or not view:
            out[n] = {"ground": []}
            continue
        y = view[3] * float(g) + view[1] * float(row["player"][0] if row.get("player") else 0.0) + view[5]
        out[n] = {"ground": [{"box": [0.0, round(y, 3), float(width), float(max(height, y + 1))],
                              "score": 1.0, "source": "engine"}]}
    return out


def has_engine_ground(trace: dict) -> bool:
    return any(r.get("ground") is not None and r.get("view") for r in trace.get("rows") or [])
