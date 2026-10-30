"""Judge the clean game once per CI run, so the run's other jobs need not ask SAM about it again.

A correct fix renders frames byte-identical to the clean game (the real fall-through fix: 120 of 120
frames on the smoke route), and every verification judges the clean game too, as its clean control.
Each CI job starts with an empty SAM cache, so without this every job pays SAM to look at frames
that another job of the same run has already judged: a correct fix's verification cost 1,164 images,
the same as the clean game on the same five routes (run 41003749744).

This renders the clean game on the smoke route and, with ``--scope all``, on every private route,
and judges each replay with the verifier's own SAM checks and its clean-replay score floor. The
answers are kept only when every check passes on every route: SAM's answers vary slightly between
requests (dev.meta.ai, Segmenting with prompts), and a weak or missing answer kept here would repeat
in every job of the run instead of being asked again. Anything else leaves the cache empty.

The answers go into the SAM cache, which is keyed by frame SHA-256, prompt, model and request
settings: a job that restores it skips only frames whose bytes match exactly, and judges every
other frame itself. The workflow encrypts the cache before it leaves this job (it holds SAM's boxes
for private routes), and a job that cannot restore it judges everything itself, as before.

    NIGHTSHIFT_HELDOUT_DIR=... NIGHTSHIFT_OBS_PROVIDER=sam MODEL_API_KEY=... \\
        python3 -m agents.sam_warm --scope all --cache runs/sam-warm/cache --out runs/sam-warm
    python3 -m agents.sam_warm --count ~/.cache/nightshift/sam

Only counts and check ids are printed: route names, frames and boxes stay in ``--out`` and the cache.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from agents.heldout_bench import SMOKE_ROUTE, _render, _routes
from agents.patchutil import sha256_file
from agents.sam_observations import CACHE_ENV, sam_images_since, sam_usage
from agents.verifier import (
    REGRESSION_SPEC,
    SAM_CLEAN_SCORE_FLOOR,
    _ground_observations,
    _sam_verdicts,
    held_out_set,
    reference_surfaces,
    sam_on,
    sam_specs,
)
from nightshift.contracts import load
from nightshift.evaluator import evaluate

FORMAT = "nightshift.sam-warm/v0"
SCOPES = ("all", "public")


def count(cache_dir: Path) -> int:
    """How many answers a cache directory holds."""
    root = Path(cache_dir)
    return sum(1 for _ in root.glob("*/*.json")) if root.is_dir() else 0


def _clear(cache_dir: Path) -> None:
    if cache_dir.is_dir():
        shutil.rmtree(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)


def warm(scope: str, out: Path, cache_dir: Path) -> dict:
    """Judge the clean game on the scope's routes into ``cache_dir``; keep the answers only if all pass."""
    if scope not in SCOPES:
        raise SystemExit(f"--scope must be one of {SCOPES}")
    if not sam_on():
        raise SystemExit("SAM is off (set NIGHTSHIFT_OBS_PROVIDER=sam): there is nothing to share")
    from agents.sam_observations import vision_backend

    judge = vision_backend()
    routes: list[Path] = [SMOKE_ROUTE]
    if scope == "all":
        root, manifest, problem = held_out_set()
        if manifest is None:
            raise SystemExit(f"held-out set unavailable: {problem or 'NIGHTSHIFT_HELDOUT_DIR is not set'}")
        routes += [path for _name, path, _dx in _routes(root, manifest)[1:]]
    cache_dir = Path(cache_dir)
    _clear(cache_dir)
    os.environ[CACHE_ENV] = str(cache_dir)  # read by every SAM call below
    out.mkdir(parents=True, exist_ok=True)
    ground = load(REGRESSION_SPEC, "test-spec")
    specs = sam_specs(ground["id"])
    before = sam_usage()
    reference = reference_surfaces(out)
    problems: list[dict] = []  # route index and check id only: private route names are never printed
    for i, route in enumerate(routes):
        run_dir = out / f"route-{i}"
        try:
            _render(route, run_dir, [])
            trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
            replay_sha = sha256_file(run_dir / "replay.json")
        except (subprocess.CalledProcessError, OSError, TimeoutError, ValueError, SystemExit):
            problems.append({"route": i, "check": "render", "result": "needs-review"})
            continue
        frames = run_dir / "frames"
        try:
            # The same call the verifier makes, so the same prompts land in the cache (SAM's robot box
            # for the ground line; under glimmer-engine the ground is judged on the position log).
            obs, _source = _ground_observations(ground, trace, replay_sha, frames, True, reference)
            result = evaluate(ground, obs)["result"]
        except SystemExit:
            result = "needs-review"
        if result != "pass":
            problems.append({"route": i, "check": ground["id"], "result": result})
        for spec, verdict, _error in _sam_verdicts(specs, trace, replay_sha, frames, run_dir, "clean-",
                                                   SAM_CLEAN_SCORE_FLOOR):
            result = verdict["result"] if verdict else "needs-review"
            if result != "pass":
                problems.append({"route": i, "check": spec["id"], "result": result})
    shared = not problems
    if not shared:
        _clear(cache_dir)  # nothing is shared that a check did not pass on
    doc = {
        "format": FORMAT,
        "scope": scope,
        "judge": judge,
        "routes": len(routes),
        "shared": shared,
        "answers": count(cache_dir),
        "problems": problems,
        "samImages": sam_images_since(before),
    }
    (out / "sam-warm.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def annotation(doc: dict) -> str:
    where = "the smoke route" if doc["scope"] == "public" else f"the smoke route and {doc['routes'] - 1} private routes"
    if doc["shared"]:
        return (f"::notice title=SAM shared cache::the clean game passed every check on {where}; "
                f"{doc['answers']} answers shared with this run's jobs; SAM images {doc['samImages']}")
    failed = sorted({f"{p['check']} {p['result']}" for p in doc["problems"]})
    routes = len({p["route"] for p in doc["problems"]})
    return (f"::warning title=SAM shared cache::not shared: {routes} of {doc['routes']} routes did not pass every "
            f"check on the clean game ({', '.join(failed)}), so every job judges its frames itself; "
            f"SAM images {doc['samImages']}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--scope", choices=SCOPES, help="all: smoke and private routes; public: the smoke route only")
    g.add_argument("--count", type=Path, metavar="CACHE_DIR", help="print how many answers a cache holds")
    p.add_argument("--cache", type=Path, default=Path("runs/sam-warm/cache"))
    p.add_argument("--out", type=Path, default=Path("runs/sam-warm"))
    args = p.parse_args(argv)
    if args.count is not None:
        print(count(args.count))
        return 0
    doc = warm(args.scope, args.out, args.cache)
    print(annotation(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
