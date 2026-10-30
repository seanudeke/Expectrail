"""Reported-bug bench: would Expectrail catch reproductions of publicly reported Godot bugs?

The seeded bugs under bugs/<family>/ were written by the team. The bugs in bugs/reported/ were
not: each one reproduces a bug that someone outside the team reported, or that a Godot contributor
fixed in this demo (sources in bugs/reported/README.md). This bench renders each of them, and the
clean game as the false-alarm control, on the smoke route and on every route in
bugs/reported/manifest.json, and judges each replay two ways:

- **today's checks**: what the verifier runs with SAM off, the engine ground check and the
  gameplay motion check, through the same ``judge_route`` the held-out bench uses;
- **engine-record checks** (agents/trace_checks.py): rules about the game read from the harness
  trace. They were written after these bugs were reproduced, so they are development checks, not
  blind ones, and the verifier does not run them yet.

A bug is caught by a set of checks when any of them fails on any route. SAM is off unless the
run has a SAM key and EXPECTRAIL_OBS_PROVIDER=sam, as for the verifier; with SAM on, today's checks
are also counted the way the verifier runs them then (the hybrid ground check, the gameplay check
and the SAM specs: the robot and the coins stay visible).

Everything here is public: the bugs, the routes and the checks. The table in bench/reported/ is
written from a CI run's own annotations (``python3 -m agents.bench_collect --reported --run <id>``).

    python3 -m agents.reported_bench --list
    python3 -m agents.reported_bench --variant air-jump --out runs/reported-bench
    python3 -m agents.reported_bench --clean --out runs/reported-bench
    python3 -m agents.reported_bench --annotate runs/reported-bench/air-jump/bench.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from agents import trace_checks
from agents.gameplay import MIN_DELTA_X_HARNESS, judge_trace
from agents.heldout_bench import (
    CLEAN, ERRORS_FILE, RESULTS, SAM_OFF_CHECKS, SAM_ON_CHECKS, SMOKE_ROUTE, caught, judge_route,
)
from agents.sam_observations import sam_images_since, sam_usage
from agents.verifier import REGRESSION_SPEC, reference_surfaces, sam_on, sam_specs
from expectrail.contracts import load
from harness.run import REPO

FORMAT = "expectrail.reported-bench/v0"
MANIFEST_FORMAT = "expectrail.reported-bugs/v0"
REPORTED = REPO / "bugs" / "reported"
TODAYS_CHECKS = list(SAM_OFF_CHECKS)
TRACE_CHECKS = list(trace_checks.CHECKS)
MAX_DETAIL_NOTES = 6  # GitHub keeps 10 notices per step; one is the summary, one the time


def load_manifest(root: Path = REPORTED) -> dict:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != MANIFEST_FORMAT:
        raise SystemExit(f"{root / 'manifest.json'}: format is not {MANIFEST_FORMAT}")
    names = [r["name"] for r in manifest["routes"]]
    for v in manifest["variants"]:
        if v["route"] not in names:
            raise SystemExit(f"{v['id']}: route {v['route']!r} is not in the manifest's routes")
        if v["check"] not in trace_checks.CHECKS:
            raise SystemExit(f"{v['id']}: check {v['check']!r} is not in agents/trace_checks.py")
    return manifest


def variant_ids(manifest: dict) -> list[str]:
    return [CLEAN] + [v["id"] for v in manifest["variants"]]


def routes(manifest: dict, root: Path = REPORTED) -> list[tuple[str, Path, float]]:
    """(name, route file, minimum delta-x) for the smoke route and every reported route."""
    rows = [("smoke", SMOKE_ROUTE, MIN_DELTA_X_HARNESS)]
    rows += [(r["name"], root / r["file"], float(r["minDeltaX"])) for r in manifest["routes"]]
    return rows


def judge_replay(route: Path, min_dx: float, patches: list[Path], run_dir: Path, ground_spec: dict,
                 reference: list | None, sam_spec_docs: list[dict] | None = None) -> dict:
    """Today's checks and the engine-record checks on one replay, with a reason for each that did not pass."""
    if run_dir.exists():
        shutil.rmtree(run_dir)  # never judge a trace left over from an earlier run
    checks = judge_route(route, min_dx, patches, run_dir, ground_spec, sam_spec_docs or [], reference,
                         use_sam=sam_spec_docs is not None)
    reasons: dict[str, str] = {}
    try:
        trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        trace = None
    if trace is None:
        for name in TRACE_CHECKS:
            checks[name] = "needs-review"
            reasons[name] = "no trace: the replay did not finish"
        return {"checks": checks, "reasons": reasons}
    if checks.get("gameplay") != "pass":
        reasons["gameplay"] = str(judge_trace(trace, min_delta_x=min_dx).get("reason") or "")
    errors_file = run_dir / ERRORS_FILE
    errors = json.loads(errors_file.read_text(encoding="utf-8")) if errors_file.is_file() else []
    for name, result in checks.items():
        if result == "pass" or name in reasons or name in trace_checks.CHECKS:
            continue
        found = [e.partition(": ")[2] for e in errors if e.startswith(f"{name}: ")]
        if found:
            reasons[name] = found[0]
        elif name in ("engine", "hybrid") and result == "fail":
            reasons[name] = "the robot went more than 20 px below the ground line"
        elif result == "fail":
            reasons[name] = "the spec's assertion failed"
    for name, verdict in trace_checks.judge_all(trace).items():
        checks[name] = verdict["result"]
        if verdict["result"] != "pass":
            reasons[name] = verdict["reason"]
    return {"checks": checks, "reasons": reasons}


def bench(key: str, out: Path, root: Path = REPORTED) -> dict:
    manifest = load_manifest(root)
    if key == CLEAN:
        entry = None
        patches: list[Path] = []
    else:
        matches = [v for v in manifest["variants"] if v["id"] == key]
        if len(matches) != 1:
            raise SystemExit(f"{key}: not one variant in {root / 'manifest.json'}")
        entry = matches[0]
        patches = [root / entry["patch"]]
    ground_spec = load(REGRESSION_SPEC, "test-spec")
    use_sam = sam_on()
    sam_spec_docs = sam_specs(ground_spec["id"]) if use_sam else None
    sam_before = sam_usage()
    work = out / key
    work.mkdir(parents=True, exist_ok=True)
    reference = reference_surfaces(work)
    per_route = []
    for name, route, min_dx in routes(manifest, root):
        per_route.append({"route": name, **judge_replay(route, min_dx, patches, work / name, ground_spec, reference,
                                                        sam_spec_docs)})
    names = list(per_route[0]["checks"])
    per_check = {c: {r: sum(row["checks"].get(c) == r for row in per_route) for r in RESULTS} for c in names}
    expected = entry["check"] if entry else None
    doc = {
        "format": FORMAT,
        "variant": key,
        "source": entry.get("source") if entry else None,
        "expectedCheck": expected,
        "sam": use_sam,
        "routes": len(per_route),
        "checks": per_check,
        "caughtByTodaysChecksSamOn": (caught(per_check, list(SAM_ON_CHECKS) + [d["id"] for d in sam_spec_docs])
                                      if use_sam else None),
        "caughtByTodaysChecks": caught(per_check, TODAYS_CHECKS),
        "caughtByTraceChecks": caught(per_check, TRACE_CHECKS),
        "caughtByOwnCheck": caught(per_check, [expected]) if expected else None,
        "samImages": sam_images_since(sam_before) if use_sam else None,
        "perRoute": per_route,
    }
    (work / "bench.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def _one_line(text: str) -> str:
    return " ".join(str(text).replace("%", "%25").split())


def annotation(doc: dict) -> str:
    """The run's public output: one summary line per variant, then a line per check that did not pass."""
    parts = []
    for check, counts in doc["checks"].items():
        parts.append(f"{check} " + ", ".join(f"{counts[r]} {r}" for r in RESULTS if counts[r]))
    variant = doc["variant"]
    label = "false alarm" if variant == CLEAN else "caught"
    head = f"{label} with today's checks (SAM on): {doc['caughtByTodaysChecksSamOn']}; " if doc.get("sam") else ""
    head += (f"{label} with today's checks (SAM off): {doc['caughtByTodaysChecks']}; "
             f"{label} with engine-record checks: {doc['caughtByTraceChecks']}")
    if variant != CLEAN:
        head += f"; caught by its own check {doc['expectedCheck']}: {doc['caughtByOwnCheck']}"
    title = f"Reported bench {variant}"
    lines = [f"::notice title={title}::{head}; over {doc['routes']} routes: " + "; ".join(parts)]
    details = [(result, f"{check} on {row['route']}: {row['reasons'].get(check, '')}")
               for row in doc["perRoute"] for check, result in row["checks"].items() if result != "pass"]
    for result, text in details[:MAX_DETAIL_NOTES]:
        lines.append(f"::notice title={title} {result}::{_one_line(text)}")
    if len(details) > MAX_DETAIL_NOTES:
        lines.append(f"::notice title={title} more::{len(details) - MAX_DETAIL_NOTES} more checks did not pass; "
                     f"see bench.json")
    if doc.get("samImages") is not None:
        lines.append(f"::notice title=Reported bench SAM images {variant}::{doc['samImages']}")
    return "\n".join(lines)


def undecided(doc: dict) -> bool:
    """True when any check on any route could not decide: such a run is not a result."""
    return any(counts["needs-review"] for counts in doc["checks"].values())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="print clean and every reported bug id as JSON")
    g.add_argument("--variant", help="one reported bug id from bugs/reported/manifest.json")
    g.add_argument("--clean", action="store_true", help="the unpatched game (false-alarm control)")
    g.add_argument("--annotate", type=Path, help="print the public annotation for a bench.json")
    p.add_argument("--out", type=Path, default=REPO / "runs" / "reported-bench")
    args = p.parse_args(argv)
    if args.annotate:
        print(annotation(json.loads(args.annotate.read_text(encoding="utf-8"))))
        return 0
    if args.list:
        print(json.dumps(variant_ids(load_manifest())))
        return 0
    doc = bench(CLEAN if args.clean else args.variant, args.out)
    print(annotation(doc))
    return 1 if undecided(doc) else 0


if __name__ == "__main__":
    sys.exit(main())
