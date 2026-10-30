"""The drawn-floor ground check on the public routes: what it changes, and what it catches.

    python3 bench/drawn-floor/check.py --out runs/drawn-floor [--routes smoke,traversal,coins,combat]

Renders each public route with the clean game, every development variant, the floor-art bugs in
this folder and the candidate fixtures (on the bug each was written against), then judges the
ground spec twice on the position log, as the verifier does with SAM off: against the clean level's
collision only (the check before Oct 30), and against the higher of that and the floor as drawn
(levelArt, the check now). Writes results.json beside this file and prints a table.

The floor-art bugs were written for this check, from the public game, before it ran on the held-out
set: the tiles' art moved 26 px up by a shader (art-shader-up) or by the tile set's texture origin
(art-origin-up), and 26 px down by a shader (art-shader-down). Collision is untouched in all three.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from agents.observations import FEET_OFFSET, with_reference_ground  # noqa: E402
from agents.verifier import _ground_observations  # noqa: E402
from harness.run import REPO, run as harness_run  # noqa: E402
from expectrail.contracts import load  # noqa: E402
from expectrail.evaluator import evaluate  # noqa: E402

ROUTES = ("smoke", "traversal", "coins", "combat")
FIXTURES = REPO / "agents" / "fixtures"
FALL = REPO / "bugs" / "physics-fall-through" / "v1.patch"
CANDIDATES = {  # fixture -> the bug it was written against (agents/judge_bench.py)
    "fix-collision-mask": FALL, "fix-but-hide-player": FALL, "fix-but-sink-player": FALL,
    "fix-and-lower-the-floor": FALL, "freeze-player": FALL, "fix-comment-only": FALL,
    "fix-sinking-overcorrected": REPO / "bugs" / "sinking" / "v1.patch",
}


def variants() -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {"clean": []}
    for p in sorted((REPO / "bugs").glob("*/v*.patch")):
        out[f"dev/{p.parent.name}/{p.stem}"] = [p]
    for p in sorted(HERE.glob("*.patch")):
        out[f"floor/{p.stem}"] = [p]
    for name, bug in CANDIDATES.items():
        out[f"candidate/{name}"] = [bug, FIXTURES / f"{name}.patch"]
    return out


def judge(trace: dict, reference: list, spec: dict) -> dict:
    out = {}
    without_art = {k: v for k, v in trace.items() if k != "levelArt"}
    for label, t in (("collision", without_art), ("drawn", trace)):
        obs, _source = _ground_observations(spec, t, "0" * 64, None, False, reference)
        out[label] = evaluate(spec, obs)["result"]
    lined = with_reference_ground(trace, reference)
    gaps = [r["player"][1] + FEET_OFFSET - r["ground"] for r in lined["rows"]
            if r.get("ground") is not None and r.get("player")]
    out["worstGapPx"] = round(max(gaps), 1) if gaps else None  # world px the feet go below the line
    out["levelArt"] = "levelArt" in trace
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path, default=REPO / "runs" / "drawn-floor")
    p.add_argument("--routes", default=",".join(ROUTES))
    p.add_argument("--workers", type=int, default=2)
    args = p.parse_args(argv)
    spec = load(REPO / "specs" / "player-stays-above-ground.json", "test-spec")
    table = variants()
    routes = args.routes.split(",")

    def render(route: str, name: str) -> dict:
        run_dir = args.out / route / name.replace("/", "_")
        if not (run_dir / "trace.json").is_file():
            harness_run(REPO / "harness" / "routes" / f"{route}.json", run_dir, patches=table[name])
        return json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))

    clean = {r: render(r, "clean") for r in routes}
    reference = clean[routes[0]]["levelSurfaces"]  # the clean level, as the verifier reads it
    results: dict = {}
    with cf.ThreadPoolExecutor(args.workers) as pool:
        jobs = {pool.submit(render, r, n): (r, n) for n in table for r in routes}
        for job in cf.as_completed(jobs):
            route, name = jobs[job]
            results.setdefault(name, {})[route] = judge(job.result(), reference, spec)
    doc = {"format": "expectrail.drawn-floor-bench/v0", "routes": routes,
           "results": {n: results[n] for n in table}}
    (HERE / "results.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    count = lambda name, label, verdict: sum(1 for r in routes if results[name][r][label] == verdict)  # noqa: E731
    print(f"| Run | Collision only: fail | Collision or drawn floor: fail | Worst gap (px) |")
    print("| --- | --- | --- | --- |")
    for name in table:
        worst = max((results[name][r]["worstGapPx"] or 0.0) for r in routes)
        print(f"| {name} | {count(name, 'collision', 'fail')} of {len(routes)} | "
              f"{count(name, 'drawn', 'fail')} of {len(routes)} | {worst} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
