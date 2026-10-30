"""The web harness's layout log as observations, the web's counterpart of the game's position log.

``layout_observations(trace, spec)`` turns the layout boxes the harness logged into
``expectrail.observations/v0`` for the objects a test spec names, so the unchanged evaluator can judge
the spec on what the page's layout says, as it judges the game's specs on the engine's position log.
An object counts as present in a frame when CSS shows it (display and visibility; opacity counts as
shown, as in Playwright's own check) and its box reaches into the viewport. The box is the layout
box, before transforms: a button drawn elsewhere by a transform is, to the layout, where it was.
``engine_objects(trace, names)`` gives the same boxes in the shape the SAM adapter takes for objects
it is not asked to find (the form a button must stay inside), as the game's ground line is given.
``agreeing(trace, names)`` is the filter the web verifier hands the SAM adapter: a SAM box for an
element counts only where it overlaps the page's paint box for that element in that frame, so a
look-alike elsewhere on the page (the cart's count badge, the theme toggle) cannot pass for it, and
SAM still has to see the element drawn there: a covered or transparent button has a paint box but
nothing SAM calls a button on it. Agreement can only remove detections, never add one.
"""
from __future__ import annotations

MODEL_NAME = "expectrail.web-layout"
AGREE_IOU = 0.5
PAGE_CHECK = {"rule": "a SAM box counts only where it overlaps the page's paint box for that element in that frame",
              "iou": AGREE_IOU}


def _in_view(box: list[float], viewport: list[int]) -> bool:
    width, height = viewport
    return box[2] > 0 and box[3] > 0 and box[0] < width and box[1] < height and box[2] > box[0] and box[3] > box[1]


def _boxes(element: dict | None, viewport: list[int], painted: bool = False) -> list[dict]:
    if not element or not element.get("shown"):
        return []
    box = element["painted" if painted else "layout"]
    return [{"box": list(box), "score": 1.0}] if _in_view(box, viewport) else []


def layout_observations(trace: dict, spec: dict, replay_sha256: str = "0" * 64) -> dict:
    names = list(spec.get("objects") or {})
    frames = [{"frame": row["frame"],
               "objects": {name: _boxes(row["elements"].get(name), trace["viewport"]) for name in names}}
              for row in trace["rows"]]
    return {"format": "expectrail.observations/v0", "replay": {"sha256": replay_sha256},
            "model": {"name": MODEL_NAME, "prompts": {n: o.get("prompt", n) for n, o in spec["objects"].items()},
                      "units": "viewport pixels", "boxes": "CSS layout boxes, before transforms"},
            "frames": frames}


def engine_objects(trace: dict, names: list[str]) -> dict[int, dict]:
    """{frame: {name: [box, ...]}} for objects SAM is not asked to find."""
    return {row["frame"]: {name: _boxes(row["elements"].get(name), trace["viewport"]) for name in names}
            for row in trace["rows"]}


def behaviour(trace: dict) -> dict:
    """The session's outcome: the shopper's last click submitted the order, or it did not."""
    outcome = trace.get("outcome") or {}
    if outcome.get("submitted"):
        return {"result": "pass", "reason": "the checkout click went through and the form was submitted"}
    return {"result": "fail", "reason": outcome.get("error") or "the form was not submitted"}


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def agreeing(trace: dict, names: list[str]):
    """{frame: {name: detections}} -> the same, keeping for each named element only the detections
    on its paint box in that frame (none when CSS hides it or it is out of view)."""
    rows = {row["frame"]: row for row in trace["rows"]}
    viewport = trace["viewport"]

    def keep(observed: dict[int, dict]) -> dict[int, dict]:
        out: dict[int, dict] = {}
        for frame, objects in observed.items():
            row = rows.get(frame)
            out[frame] = dict(objects)
            for name in names:
                if name not in objects:
                    continue
                at = _boxes((row or {}).get("elements", {}).get(name), viewport, painted=True)
                box = at[0]["box"] if at else None
                out[frame][name] = [d for d in objects[name] if box is not None and _iou(d["box"], box) >= AGREE_IOU]
        return out

    return keep
