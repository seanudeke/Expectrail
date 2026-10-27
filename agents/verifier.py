"""Verify a candidate patch outside the fixer's reach.

    python3 -m agents.verifier --request rr.json --candidate runs/fix/candidate.patch \\
        --out runs/verify [--observations path.json] [--skip-harness]

Applies base seed + candidate, replays the route (unless --skip-harness with
pre-built observations), runs regression + gameplay specs, and emits
nightshift.verification/v0 via nightshift.evaluator.decide.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agents.observations import from_trace
from agents.patchutil import assert_editable, sha256_file
from harness.run import REPO, run as harness_run, tree_digest
from nightshift.contracts import digest, load, validate
from nightshift.evaluator import decide, evaluate

REGRESSION_SPEC = REPO / "agents" / "specs" / "player-stays-above-ground.json"
GAMEPLAY_SPEC = REPO / "agents" / "specs" / "player-reaches-end-of-route.json"


def _resolve(repo_relative: str | Path) -> Path:
    path = Path(repo_relative)
    return path if path.is_absolute() else REPO / path


def verify(
    request: dict,
    candidate: Path,
    out: Path,
    *,
    route: Path | None = None,
    observations_path: Path | None = None,
    skip_harness: bool = False,
    attempt: int = 1,
) -> dict:
    validate(request, "repair-request")
    out.mkdir(parents=True, exist_ok=True)
    patch_text = candidate.read_text(encoding="utf-8")
    bad = assert_editable(patch_text, request["editable"])
    if bad:
        decision, reasons = "reject", [f"candidate touches paths outside editable: {bad}"]
        checks = [{
            "spec": "editable-globs", "kind": "regression", "route": "n/a", "result": "fail",
        }]
        return _write_verification(out, request, candidate, attempt, checks, decision, reasons)

    game = REPO / "game" / "platformer"
    if request["base"]["tree"] != tree_digest(game):
        decision, reasons = "reject", ["base.tree does not match game/platformer"]
        checks = [{
            "spec": "base-tree", "kind": "regression", "route": "n/a", "result": "fail",
        }]
        return _write_verification(out, request, candidate, attempt, checks, decision, reasons)

    failing = request["failing"][0]
    route_doc = failing["route"]
    # Always materialize the request's route so verify is bound to the RR, not only
    # the default smoke file on disk.
    route_path = out / "route.json"
    route_path.write_text(json.dumps(route_doc, indent=2) + "\n", encoding="utf-8")
    if route is None:
        route = route_path

    patches: list[Path] = []
    seed = request["base"].get("patch")
    if seed:
        patches.append(_resolve(seed))
    patches.append(candidate)

    if observations_path is not None:
        observations = load(observations_path, "observations")
        replay_sha = observations.get("replay", {}).get("sha256", "0" * 64)
    elif skip_harness:
        raise SystemExit("--skip-harness requires --observations")
    else:
        harness_run(route, out / "replay", patches=patches)
        trace = json.loads((out / "replay" / "trace.json").read_text(encoding="utf-8"))
        replay_sha = sha256_file(out / "replay" / "replay.json")
        observations = from_trace(trace, replay_sha256=replay_sha)
        (out / "observations.json").write_text(json.dumps(observations, indent=2) + "\n", encoding="utf-8")

    checks = []
    for kind, spec_path in (("regression", REGRESSION_SPEC), ("gameplay", GAMEPLAY_SPEC)):
        spec = load(spec_path, "test-spec")
        # Prefer the failing spec from the request for regression when ids match.
        if kind == "regression" and failing.get("spec", {}).get("id") == spec["id"]:
            spec = failing["spec"]
        verdict = evaluate(spec, observations)
        (out / f"verdict-{spec['id']}.json").write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
        checks.append({
            "spec": spec["id"],
            "kind": kind,
            "route": route_doc.get("name", route.stem),
            "result": verdict["result"],
            "verdictSha256": digest(verdict),
        })

    decision, reasons = decide(checks)
    return _write_verification(out, request, candidate, attempt, checks, decision, reasons)


def _write_verification(out, request, candidate, attempt, checks, decision, reasons) -> dict:
    from nightshift import __version__ as eval_version

    doc = {
        "format": "nightshift.verification/v0",
        "candidate": {
            "patchSha256": sha256_file(candidate),
            "baseTree": request["base"]["tree"],
            "attempt": attempt,
            "request": request["id"],
        },
        "evaluator": {"name": "nightshift.evaluator", "version": eval_version},
        "checks": checks,
        "decision": decision,
        "reasons": reasons,
    }
    validate(doc, "verification")
    (out / "verification.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--route", type=Path)
    p.add_argument("--observations", type=Path)
    p.add_argument("--skip-harness", action="store_true")
    p.add_argument("--attempt", type=int, default=1)
    args = p.parse_args(argv)
    request = load(args.request, "repair-request")
    doc = verify(
        request, args.candidate, args.out, route=args.route,
        observations_path=args.observations, skip_harness=args.skip_harness, attempt=args.attempt,
    )
    print(f"{doc['decision']}: {'; '.join(doc['reasons'])}")
    return 0 if doc["decision"] == "accept" else 1


if __name__ == "__main__":
    sys.exit(main())
