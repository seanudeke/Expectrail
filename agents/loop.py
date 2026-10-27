"""Overnight agent loop: triage → fix → verify → morning report.

    python3 -m agents.loop --out runs/loop [--use-muse] [--offline-triage] [--runs 1]

Exit 0 only if every run ends with verification accept (Gate 2 demo-path stability).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agents.fixer import run_fixer
from agents.report import build_report
from agents.triage import triage
from agents.verifier import verify
from harness.run import REPO
from nightshift.contracts import load


def one_run(out: Path, *, use_muse: bool, offline_triage: bool, observations: Path | None,
            candidate_patch: Path | None, skip_harness: bool) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    request = triage(
        spec=load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec"),
        verdict=load(REPO / "contracts" / "examples" / "verdict.json", "verdict"),
        route=load(REPO / "harness" / "routes" / "smoke.json", "route"),
        out=out / "triage",
        offline=offline_triage,
    )
    fix_out = out / "fix"
    run_fixer(
        request, fix_out,
        candidate_patch=None if use_muse else (
            candidate_patch or REPO / "agents" / "fixtures" / "fix-collision-mask.patch"
        ),
    )
    verification = verify(
        request, fix_out / "candidate.patch", out / "verify",
        observations_path=observations,
        skip_harness=skip_harness or observations is not None,
    )
    summary = build_report(
        verification=verification,
        candidate=fix_out / "candidate.patch",
        out=out / "morning",
        signing_key_path=None,
    )
    return {"decision": verification["decision"], "morning": summary}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=Path("runs/loop"))
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--use-muse", action="store_true")
    p.add_argument("--offline-triage", action="store_true", default=True)
    p.add_argument("--online-triage", action="store_true")
    p.add_argument("--observations", type=Path,
                   default=REPO / "agents" / "fixtures" / "obs-fixed.json")
    p.add_argument("--candidate-patch", type=Path)
    p.add_argument("--skip-harness", action="store_true", default=True)
    args = p.parse_args(argv)

    offline = not args.online_triage
    results = []
    for i in range(args.runs):
        run_out = args.out / f"run-{i:02d}"
        results.append(one_run(
            run_out, use_muse=args.use_muse, offline_triage=offline,
            observations=args.observations, candidate_patch=args.candidate_patch,
            skip_harness=args.skip_harness,
        ))
        print(f"run {i}: {results[-1]['decision']}")

    accepted = sum(1 for r in results if r["decision"] == "accept")
    summary = {"runs": args.runs, "accepted": accepted, "results": results}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"{accepted} of {args.runs} accepted")
    return 0 if accepted == args.runs else 1


if __name__ == "__main__":
    sys.exit(main())
