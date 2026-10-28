"""Verify a candidate patch outside the fixer's reach.

    python3 -m agents.verifier --request rr.json --candidate runs/fix/candidate.patch \\
        --out runs/verify [--observations path.json] [--skip-harness]

Applies base seed + candidate, replays the route (unless --skip-harness with
pre-built observations), runs regression + gameplay + clean + held-out checks,
and emits nightshift.verification/v0 via nightshift.evaluator.decide.

Clean uses a distinct observation source (never the candidate obs object).
Held-out evaluates interim verifier-side observations until Sean lands real
held-out variants; both go through evaluate(), never a rubber-stamp pass row.

Optional `suite` on the verification document records candidate/clean/held-out
provenance (harness vs fixture vs fixture-fallback vs unavailable).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import traceback
from pathlib import Path

from agents.gameplay import (
    MIN_DELTA_X_FIXTURE,
    MIN_DELTA_X_HARNESS,
    judge_trace,
)
from agents.isolation import arm
from agents.observations import from_trace
from agents.patchutil import assert_editable, sha256_file
from harness.run import REPO, run as harness_run, tree_digest
from nightshift.contracts import digest, load, validate
from nightshift.evaluator import decide, evaluate

REGRESSION_SPEC = REPO / "agents" / "specs" / "player-stays-above-ground.json"
# Opaque check id for verification / filmable rows. Judged by agents.gameplay from
# the harness/fixture trace — not evaluate(reaches) and not a SAM goal.
# Retired label player-reaches-end-of-route stays on FIXER_FORBIDDEN forever.
GAMEPLAY_SPEC_ID = "player-motion-on-smoke"
CLEAN_OBS = REPO / "agents" / "fixtures" / "obs-clean.json"
HELD_OUT_OBS = REPO / "agents" / "fixtures" / "obs-held-out.json"
TRACE_FIXTURES = {
    "obs-fixed.json": REPO / "agents" / "fixtures" / "trace-fixed.json",
    "obs-freeze.json": REPO / "agents" / "fixtures" / "trace-freeze.json",
    "obs-fallthrough.json": REPO / "agents" / "fixtures" / "trace-fallthrough.json",
}

_NOT_RUN = arm(source="not-run", detail="suite checks skipped (early reject)")


def _resolve(repo_relative: str | Path) -> Path:
    path = Path(repo_relative)
    return path if path.is_absolute() else REPO / path


def _check(kind: str, spec_id: str, route_name: str, verdict: dict) -> dict:
    return {
        "spec": spec_id,
        "kind": kind,
        "route": route_name,
        "result": verdict["result"],
        "verdictSha256": digest(verdict),
    }


def _early_suite(*, gate: str, detail: str) -> dict:
    return {
        "candidate": dict(_NOT_RUN),
        "clean": dict(_NOT_RUN),
        "heldOut": dict(_NOT_RUN),
        "earlyReject": {"gate": gate, "detail": detail},
    }


def _resolve_gameplay_trace(
    out: Path,
    *,
    observations_path: Path | None,
) -> tuple[dict, str, float]:
    """Return (trace, source_label, min_delta_x).

    When --observations is set (offline / skip-harness), mapped fixture traces win
    so a leftover out/replay/trace.json cannot override freeze fixtures.
    Otherwise use the live harness candidate trace.
    """
    if observations_path is not None:
        mapped = TRACE_FIXTURES.get(observations_path.name)
        if mapped is not None and mapped.is_file():
            return (
                json.loads(mapped.read_text(encoding="utf-8")),
                f"fixture-trace:{mapped.name}",
                MIN_DELTA_X_FIXTURE,
            )
        raise SystemExit(
            f"no mapped fixture gameplay trace for observations {observations_path.name}"
        )
    harness_trace = out / "replay" / "trace.json"
    if harness_trace.is_file():
        return (
            json.loads(harness_trace.read_text(encoding="utf-8")),
            "harness-trace",
            MIN_DELTA_X_HARNESS,
        )
    raise SystemExit("gameplay requires candidate replay/trace.json when observations are unset")


def verify(
    request: dict,
    candidate: Path,
    out: Path,
    *,
    route: Path | None = None,
    observations_path: Path | None = None,
    clean_observations_path: Path | None = None,
    held_out_observations_path: Path | None = None,
    skip_harness: bool = False,
    attempt: int = 1,
) -> dict:
    validate(request, "repair-request")
    out.mkdir(parents=True, exist_ok=True)
    patch_text = candidate.read_text(encoding="utf-8")
    bad = assert_editable(patch_text, request["editable"])
    if bad:
        detail = f"candidate touches paths outside editable: {bad}"
        decision, reasons = "reject", [detail]
        checks = [{
            "spec": "editable-globs", "kind": "regression", "route": "n/a", "result": "fail",
        }]
        return _write_verification(
            out, request, candidate, attempt, checks, decision, reasons,
            suite=_early_suite(gate="editable-globs", detail=detail),
        )

    game = REPO / "game" / "platformer"
    if request["base"]["tree"] != tree_digest(game):
        detail = "base.tree does not match game/platformer"
        decision, reasons = "reject", [detail]
        checks = [{
            "spec": "base-tree", "kind": "regression", "route": "n/a", "result": "fail",
        }]
        return _write_verification(
            out, request, candidate, attempt, checks, decision, reasons,
            suite=_early_suite(gate="base-tree", detail=detail),
        )

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
        candidate_arm = arm(
            source="fixture",
            path=str(observations_path),
            observations_sha256=digest(observations),
        )
    elif skip_harness:
        raise SystemExit("--skip-harness requires --observations")
    else:
        harness_run(route, out / "replay", patches=patches)
        trace = json.loads((out / "replay" / "trace.json").read_text(encoding="utf-8"))
        replay_sha = sha256_file(out / "replay" / "replay.json")
        observations = from_trace(trace, replay_sha256=replay_sha)
        (out / "observations.json").write_text(json.dumps(observations, indent=2) + "\n", encoding="utf-8")
        candidate_arm = arm(
            source="harness",
            path=str(out / "observations.json"),
            observations_sha256=digest(observations),
        )

    route_name = route_doc.get("name", route.stem)
    checks = []
    # Regression: still the observations evaluator (never-crosses).
    reg_spec = load(REGRESSION_SPEC, "test-spec")
    if failing.get("spec", {}).get("id") == reg_spec["id"]:
        reg_spec = failing["spec"]
    reg_verdict = evaluate(reg_spec, observations)
    (out / f"verdict-{reg_spec['id']}.json").write_text(
        json.dumps(reg_verdict, indent=2) + "\n", encoding="utf-8"
    )
    checks.append(_check("regression", reg_spec["id"], route_name, reg_verdict))

    # Gameplay: same agents.gameplay predicate for harness trace and offline fixtures.
    gameplay_trace, gameplay_source, min_dx = _resolve_gameplay_trace(
        out, observations_path=observations_path,
    )
    gameplay = judge_trace(gameplay_trace, min_delta_x=min_dx)
    metrics = dict(gameplay.get("metrics") or {})
    metrics.setdefault("minDeltaX", float(min_dx))
    gameplay_doc = {
        "format": "nightshift.gameplay-verdict/v0",
        "spec": GAMEPLAY_SPEC_ID,
        "result": gameplay["result"],
        "reason": gameplay["reason"],
        "metrics": metrics,
        "source": gameplay_source,
        "minDeltaX": float(min_dx),
        "evaluator": {"name": "agents.gameplay", "version": "0.1.0"},
    }
    validate(gameplay_doc, "gameplay-verdict")
    (out / "verdict-gameplay.json").write_text(json.dumps(gameplay_doc, indent=2) + "\n", encoding="utf-8")
    # Non-contract extract for operators; morning uses verdict-gameplay.json.
    (out / "gameplay-metrics.json").write_text(
        json.dumps(gameplay.get("metrics", {}), indent=2) + "\n", encoding="utf-8"
    )
    checks.append({
        "spec": GAMEPLAY_SPEC_ID,
        "kind": "gameplay",
        "route": route_name,
        "result": gameplay["result"],
        "verdictSha256": digest(gameplay_doc),
    })

    # Clean control: distinct obs source — never reuse the candidate observations object.
    # Harness clean-replay can SIGABRT on back-to-back Godot imports in CI; fall back to the
    # fixture so verify still emits a four-kind decision (fail still beats unclear).
    clean_path = clean_observations_path or CLEAN_OBS
    if skip_harness or observations_path is not None:
        clean_obs = load(clean_path, "observations")
        if digest(clean_obs) == digest(observations):
            raise SystemExit(
                "clean observations must be a distinct document from candidate observations "
                f"(same digest {digest(observations)[:12]}…)"
            )
        clean_route = "clean-control"
        clean_arm = arm(
            source="fixture",
            path=str(clean_path),
            observations_sha256=digest(clean_obs),
        )
    else:
        try:
            harness_run(route, out / "clean-replay", patches=[])
            clean_trace = json.loads((out / "clean-replay" / "trace.json").read_text(encoding="utf-8"))
            clean_replay_sha = sha256_file(out / "clean-replay" / "replay.json")
            clean_obs = from_trace(clean_trace, replay_sha256=clean_replay_sha)
            (out / "observations-clean.json").write_text(
                json.dumps(clean_obs, indent=2) + "\n", encoding="utf-8"
            )
            clean_route = "clean-control"
            clean_arm = arm(
                source="harness",
                path=str(out / "observations-clean.json"),
                observations_sha256=digest(clean_obs),
            )
        except (subprocess.CalledProcessError, SystemExit, OSError, TimeoutError) as exc:
            (out / "clean-harness-error.txt").write_text(
                f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}",
                encoding="utf-8",
            )
            clean_obs = load(clean_path, "observations")
            if digest(clean_obs) == digest(observations):
                raise SystemExit(
                    "clean fixture-fallback must be distinct from candidate observations "
                    f"(same digest {digest(observations)[:12]}…)"
                ) from exc
            clean_route = "clean-control-fixture-fallback"
            clean_arm = arm(
                source="fixture-fallback",
                path=str(clean_path),
                observations_sha256=digest(clean_obs),
                detail=f"clean harness failed; see {out / 'clean-harness-error.txt'}",
            )
    clean_spec = load(REGRESSION_SPEC, "test-spec")
    clean_verdict = evaluate(clean_spec, clean_obs)
    (out / "verdict-clean.json").write_text(json.dumps(clean_verdict, indent=2) + "\n", encoding="utf-8")
    checks.append(_check("clean", clean_spec["id"], clean_route, clean_verdict))

    # Held-out: evaluate verifier-side observations (interim fixture until Sean's variants).
    held_path = held_out_observations_path or HELD_OUT_OBS
    if held_path.is_file():
        held_obs = load(held_path, "observations")
        held_spec = load(REGRESSION_SPEC, "test-spec")
        held_verdict = evaluate(held_spec, held_obs)
        (out / "verdict-held-out.json").write_text(json.dumps(held_verdict, indent=2) + "\n", encoding="utf-8")
        checks.append(_check("held-out", held_spec["id"], "held-out-interim", held_verdict))
        held_source = "path" if held_out_observations_path is not None else "interim-fixture"
        held_arm = arm(
            source=held_source,
            path=str(held_path),
            observations_sha256=digest(held_obs),
        )
    else:
        checks.append({
            "spec": "held-out-unavailable",
            "kind": "held-out",
            "route": "held-out-unavailable",
            "result": "needs-review",
            "verdictSha256": "0" * 64,
        })
        held_arm = arm(source="unavailable", detail="held-out observations path missing")

    suite = {"candidate": candidate_arm, "clean": clean_arm, "heldOut": held_arm}
    decision, reasons = decide(checks)
    return _write_verification(
        out, request, candidate, attempt, checks, decision, reasons, suite=suite,
    )


def _write_verification(
    out, request, candidate, attempt, checks, decision, reasons, *, suite: dict | None = None,
) -> dict:
    from nightshift import __version__ as eval_version

    doc = {
        "format": "nightshift.verification/v0",
        "candidate": {
            "patchSha256": sha256_file(candidate),
            "baseTree": request["base"]["tree"],
            "attempt": attempt,
            "request": request["id"],
            "requestSha256": digest(request),
        },
        "evaluator": {"name": "nightshift.evaluator", "version": eval_version},
        "checks": checks,
        "decision": decision,
        "reasons": reasons,
    }
    if suite is not None:
        doc["suite"] = suite
        (out / "suite-provenance.json").write_text(json.dumps(suite, indent=2) + "\n", encoding="utf-8")
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
    p.add_argument("--clean-observations", type=Path, help="clean-control observations (default: fixtures/obs-clean.json)")
    p.add_argument("--held-out-observations", type=Path,
                   help="held-out observations (default: fixtures/obs-held-out.json interim)")
    p.add_argument("--skip-harness", action="store_true")
    p.add_argument("--attempt", type=int, default=1)
    args = p.parse_args(argv)
    request = load(args.request, "repair-request")
    doc = verify(
        request, args.candidate, args.out, route=args.route,
        observations_path=args.observations,
        clean_observations_path=args.clean_observations,
        held_out_observations_path=args.held_out_observations,
        skip_harness=args.skip_harness, attempt=args.attempt,
    )
    print(f"{doc['decision']}: {'; '.join(doc['reasons'])}")
    return 0 if doc["decision"] == "accept" else 1


if __name__ == "__main__":
    sys.exit(main())
