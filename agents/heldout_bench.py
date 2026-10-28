"""Held-out detection benchmark: would the verifier catch each private bug variant?

Each held-out bug variant lives only in the private held-out set (its patch and description never
enter this repository). For one variant, this renders the game with that variant and no fix on the
smoke route and on every private route, then judges each replay with the checks the verifier runs
on a candidate:

  - engine: the ground spec on the position log against the clean level's ground line (what the
    verifier uses with SAM off);
  - hybrid: the ground spec on SAM's box for the robot against the same line (SAM on);
  - each SAM spec (player-always-visible, coins-visible) on SAM's view of the frames (SAM on);
  - gameplay: the motion check with the route's own threshold (both).

A variant is caught when a check fails on at least one route. ``--clean`` runs the same checks on
the unpatched game: any failure there is a false alarm.

Only the variant id, counts and verdicts are printed. The manifest's descriptions, route names,
frames and traces stay in the output directory, which callers must not publish.

    NIGHTSHIFT_HELDOUT_DIR=../Nightshift-heldout python3 -m agents.heldout_bench --list
    NIGHTSHIFT_HELDOUT_DIR=... NIGHTSHIFT_OBS_PROVIDER=sam MODEL_API_KEY=... \\
        python3 -m agents.heldout_bench --variant physics-fall-through/v5 --out runs/bench
    ... --clean --out runs/bench          # the false-alarm control
    python3 -m agents.heldout_bench --annotate runs/bench/physics-fall-through_v5/bench.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from agents.gameplay import MIN_DELTA_X_HARNESS, judge_trace
from agents.patchutil import sha256_file
from agents.verifier import (
    REGRESSION_SPEC, _ground_observations, _sam_verdicts, held_out_set, reference_surfaces, sam_on, sam_specs,
)
from harness.run import REPO, run as harness_run
from nightshift.contracts import load
from nightshift.evaluator import evaluate

SMOKE_ROUTE = REPO / "harness" / "routes" / "smoke.json"
CLEAN = "clean"
RESULTS = ("fail", "needs-review", "pass")
# Which checks decide the verifier's verdict in each mode.
SAM_ON_CHECKS = ("hybrid", "gameplay")  # plus every SAM spec
SAM_OFF_CHECKS = ("engine", "gameplay")


def variant_key(entry: dict) -> str:
    return f"{entry['family']}/{entry['id']}"


def active_variants(manifest: dict) -> list[dict]:
    """Variants in the benchmark: every manifest entry not marked retired."""
    return [v for v in manifest.get("variants") or [] if not v.get("retired")]


def _routes(root: Path, manifest: dict) -> list[tuple[str, Path, float]]:
    rows = [("smoke", SMOKE_ROUTE, MIN_DELTA_X_HARNESS)]
    for entry in manifest["routes"]:
        rows.append((str(entry.get("name") or Path(entry["file"]).stem), root / entry["file"],
                     float(entry["minDeltaX"])))
    return rows


def _render(route: Path, run_dir: Path, patches: list[Path]) -> None:
    # Godot has aborted on back-to-back imports in CI; one retry, as the verifier does.
    try:
        harness_run(route, run_dir, patches=patches)
    except (subprocess.CalledProcessError, OSError, TimeoutError):
        harness_run(route, run_dir, patches=patches)


def judge_route(route: Path, min_dx: float, patches: list[Path], run_dir: Path, ground_spec: dict,
                sam_spec_docs: list[dict], reference: list | None, use_sam: bool) -> dict[str, str]:
    """Every check's result on one replay. A replay or SAM failure is needs-review, never pass."""
    names = ["engine", "gameplay"] + (["hybrid"] + [s["id"] for s in sam_spec_docs] if use_sam else [])
    try:
        _render(route, run_dir, patches)
        trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
        replay_sha = sha256_file(run_dir / "replay.json")
    except (subprocess.CalledProcessError, OSError, TimeoutError, ValueError) as exc:
        (run_dir / "bench-error.txt").write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        return {n: "needs-review" for n in names}
    frames = run_dir / "frames"
    results: dict[str, str] = {}
    try:
        obs, _source = _ground_observations(ground_spec, trace, replay_sha, frames, False, reference)
        results["engine"] = evaluate(ground_spec, obs)["result"]
    except SystemExit:
        results["engine"] = "needs-review"
    results["gameplay"] = judge_trace(trace, min_delta_x=min_dx)["result"]
    if use_sam:
        try:
            obs, source = _ground_observations(ground_spec, trace, replay_sha, frames, True, reference)
            results["hybrid"] = evaluate(ground_spec, obs)["result"] if source == "hybrid" else "needs-review"
        except SystemExit:
            results["hybrid"] = "needs-review"
        for spec, verdict, _error in _sam_verdicts(sam_spec_docs, trace, replay_sha, frames, run_dir):
            results[spec["id"]] = verdict["result"] if verdict else "needs-review"
    return results


def caught(per_check: dict[str, dict[str, int]], checks: list[str]) -> str:
    """'yes' when any of these checks failed on a route, 'needs-review' when none failed but one
    could not decide, else 'no'."""
    present = [c for c in checks if c in per_check]
    if any(per_check[c]["fail"] for c in present):
        return "yes"
    if any(per_check[c]["needs-review"] for c in present):
        return "needs-review"
    return "no"


def bench(key: str, out: Path) -> dict:
    root, manifest, problem = held_out_set()
    if manifest is None:
        raise SystemExit(f"held-out set unavailable: {problem or 'NIGHTSHIFT_HELDOUT_DIR is not set'}")
    if key == CLEAN:
        patches: list[Path] = []
        expected = None
    else:
        matches = [v for v in active_variants(manifest) if variant_key(v) == key]
        if len(matches) != 1:
            raise SystemExit(f"{key}: not one active variant in the held-out manifest")
        patches = [root / matches[0]["patch"]]
        expected = matches[0].get("spec")
    use_sam = sam_on()
    ground_spec = load(REGRESSION_SPEC, "test-spec")
    sam_spec_docs = sam_specs(ground_spec["id"]) if use_sam else []
    work = out / key.replace("/", "_")
    work.mkdir(parents=True, exist_ok=True)
    reference = reference_surfaces(work)
    per_route = []
    for name, route, min_dx in _routes(root, manifest):
        per_route.append({"route": name, "checks": judge_route(route, min_dx, patches, work / name, ground_spec,
                                                               sam_spec_docs, reference, use_sam)})
    check_names = list(per_route[0]["checks"])
    per_check = {c: {r: sum(row["checks"].get(c) == r for row in per_route) for r in RESULTS} for c in check_names}
    sam_on_checks = list(SAM_ON_CHECKS) + [s["id"] for s in sam_spec_docs]
    doc = {
        "format": "nightshift.held-out-bench/v0",
        "variant": key,
        "expectedSpec": expected,
        "sam": use_sam,
        "routes": len(per_route),
        "checks": per_check,
        "caughtWithSamOn": caught(per_check, sam_on_checks) if use_sam else None,
        "caughtWithSamOff": caught(per_check, list(SAM_OFF_CHECKS)),
        "perRoute": per_route,  # route names: private, never printed
    }
    (work / "bench.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def annotation(doc: dict) -> str:
    """One public line: the variant id, counts and verdicts, nothing from the private manifest."""
    n = doc["routes"]
    parts = []
    for check, counts in doc["checks"].items():
        bits = [f"{counts[r]} {r}" for r in RESULTS if counts[r]]
        parts.append(f"{check} {', '.join(bits)}")
    label = "false alarm" if doc["variant"] == CLEAN else "caught"
    head = f"{label} with SAM on: {doc['caughtWithSamOn']}; " if doc["sam"] else ""
    head += f"{label} with SAM off: {doc['caughtWithSamOff']}"
    title = f"Held-out bench {doc['variant']}"
    return f"::notice title={title}::{head}; over {n} routes: " + "; ".join(parts)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="print the active variant ids (and clean) as JSON")
    g.add_argument("--variant", help="family/id of one held-out variant")
    g.add_argument("--clean", action="store_true", help="the unpatched game (false-alarm control)")
    g.add_argument("--annotate", type=Path, help="print the public annotation for a bench.json")
    p.add_argument("--out", type=Path, default=REPO / "runs" / "held-out-bench")
    args = p.parse_args(argv)
    if args.annotate:
        print(annotation(json.loads(args.annotate.read_text(encoding="utf-8"))))
        return 0
    if args.list:
        _root, manifest, problem = held_out_set()
        if manifest is None:
            raise SystemExit(f"held-out set unavailable: {problem or 'NIGHTSHIFT_HELDOUT_DIR is not set'}")
        print(json.dumps([CLEAN] + [variant_key(v) for v in active_variants(manifest)]))
        return 0
    doc = bench(CLEAN if args.clean else args.variant, args.out)
    print(annotation(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
