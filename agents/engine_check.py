"""The engine cross-check: Muse Glimmer's boxes count only where the game engine put that object.

Glimmer is a vision-language model, and the fixer controls the candidate's pixels: text drawn into
the game could talk Glimmer into answering "the robot is right here". The harness knows where the
robot and every coin are on every frame (the position log and the coins rows of trace.json,
projected to frame pixels with that frame's camera, see agents.observations.engine_refs_by_frame).
A Glimmer box is kept only when it agrees with one of those engine boxes:

- it contains the engine object's centre (it is on the object, not beside it), and
- it is at most MAX_SIZE_RATIO times the engine object's width and height (a box over half the
  screen contains everything's centre and says nothing).

So a hidden robot still fails (Glimmer, answering honestly, has no box to keep), and a box put
anywhere the engine did not place the object is dropped. What it does not stop: an answer steered
onto the object's true position, which the fixer can compute because it wrote the game. SAM, a
segmenter that follows no instructions, is still the stronger guard; see docs/open-weights.md.

The check runs after the frame cache (the cache holds Glimmer's raw answers) because it depends on
the trace, not only on the pixels.
"""
from __future__ import annotations

from agents.sam_observations import SamError

# The objects the engine can place. A spec asking about anything else cannot be cross-checked.
ENGINE_OBJECTS = ("player", "coin")
MAX_SIZE_RATIO = 3.0
RULE = (f"a box counts only if it contains the centre of an object the engine placed on that frame and is at "
        f"most {MAX_SIZE_RATIO:g}x its width and height")


def agrees(box: list[float], ref: list[float], max_ratio: float = MAX_SIZE_RATIO) -> bool:
    cx, cy = (ref[0] + ref[2]) / 2, (ref[1] + ref[3]) / 2
    if not (box[0] <= cx <= box[2] and box[1] <= cy <= box[3]):
        return False
    return (box[2] - box[0]) <= max_ratio * (ref[2] - ref[0]) and (box[3] - box[1]) <= max_ratio * (ref[3] - ref[1])


def miss_gap(box: list[float], refs: list[list[float]]) -> float:
    """How far a box missed the nearest engine object, in that object's sizes; inf with no object.

    0 means it contains the centre (it was dropped for its size); 0.5 means the centre is half the
    object's width or height outside the box. Calibration only: the rule itself is agrees().
    """
    best = float("inf")
    for ref in refs:
        cx, cy = (ref[0] + ref[2]) / 2, (ref[1] + ref[3]) / 2
        w, h = max(ref[2] - ref[0], 1e-9), max(ref[3] - ref[1], 1e-9)
        gx = max(box[0] - cx, 0.0, cx - box[2]) / w
        gy = max(box[1] - cy, 0.0, cy - box[3]) / h
        best = min(best, max(gx, gy))
    return best


def _quantiles(values: list[float]) -> dict:
    finite = sorted(v for v in values if v != float("inf"))
    pick = lambda q: round(finite[min(len(finite) - 1, int(q * len(finite)))], 2) if finite else None  # noqa: E731
    return {"n": len(values), "noObject": len(values) - len(finite), "p25": pick(0.25), "p50": pick(0.5),
            "p75": pick(0.75), "p90": pick(0.9), "atCentre": sum(1 for v in finite if v == 0.0)}


class EngineCheck:
    """Filters {frame: {object: detections}} against {frame: {object: engine boxes}}; counts what it drops.

    A frame the engine cannot place, or an object it does not know, raises SamError (needs-review):
    an unchecked box never reaches a verdict.
    """

    def __init__(self, refs: dict[int, dict[str, list[list[float]]]]):
        self.refs = refs
        self.kept: dict[str, int] = {}
        self.dropped: dict[str, int] = {}
        self.gaps: dict[str, list[float]] = {}  # per dropped box: how far it missed, in object sizes

    def __call__(self, observed: dict[int, dict]) -> dict[int, dict]:
        out: dict[int, dict] = {}
        for i, objects in observed.items():
            if i not in self.refs:
                raise SamError(f"the engine cannot place objects on frame {i} (no trace row or camera for it), "
                               "so Glimmer's boxes there cannot be checked")
            out[i] = {}
            for name, detections in objects.items():
                if name not in self.refs[i]:
                    raise SamError(f"the engine does not place {name!r} (it places {', '.join(ENGINE_OBJECTS)}), "
                                   "so Glimmer's boxes for it cannot be checked")
                refs = self.refs[i][name]
                keep = [d for d in detections if any(agrees(d["box"], r) for r in refs)]
                for d in detections:
                    if d not in keep:
                        self.gaps.setdefault(name, []).append(miss_gap(d["box"], refs))
                out[i][name] = keep
                self.kept[name] = self.kept.get(name, 0) + len(keep)
                self.dropped[name] = self.dropped.get(name, 0) + len(detections) - len(keep)
        return out

    def summary(self) -> dict:
        names = sorted(set(self.kept) | set(self.dropped))
        out = {"rule": RULE, "kept": {n: self.kept.get(n, 0) for n in names},
               "dropped": {n: self.dropped.get(n, 0) for n in names}}
        gaps = {n: _quantiles(g) for n, g in sorted(self.gaps.items()) if g}
        if gaps:
            out["droppedGap"] = gaps
        return out


def check_for_trace(trace: dict | None, frames: list[int], fps: int = 60) -> EngineCheck:
    """An EngineCheck for one replay, or SamError when its trace cannot place objects in frame pixels."""
    from agents.observations import engine_refs_by_frame, has_engine_refs

    if not trace or not has_engine_refs(trace):
        raise SamError("the engine check needs the replay's harness trace with the camera (view); without it "
                       "Glimmer's boxes cannot be checked")
    return EngineCheck(engine_refs_by_frame(trace, (0, 0), frames, fps=fps))
