"""Overnight agent loop: triage → fix → verify → morning report (+ trust beat).

    python3 -m agents.loop --out runs/loop [--mode auto|offline|live] [--runs 1]

Modes:
  offline — fixtures only (CI default; no Meta keys required)
  live    — Wonder + Muse Code; requires keys (fails closed if missing)
  auto    — live steps when keys/muse are available, else fixtures

Exit 0 only if every run ends with verification accept. Crashes never forge accept.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from agents.fixer import run_fixer
from agents.keys import resolve_mode
from agents.report import build_report
from agents.triage import triage
from agents.trust import run_trust_check
from agents.verifier import verify
from harness.run import REPO
from nightshift.contracts import load


def one_run(
    out: Path,
    *,
    use_muse: bool,
    offline_triage: bool,
    observations: Path | None,
    candidate_patch: Path | None,
    skip_harness: bool,
    run_trust: bool,
) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    # Signing key only on the morning/verifier side of this run — never in fixer-work.
    signing_key = out / "verifier-host" / ".nightshift-signing-key"
    signing_key.parent.mkdir(parents=True, exist_ok=True)
    if not signing_key.exists():
        signing_key.write_text("DEMO-FAKE-SIGNING-KEY-NOT-REAL\n", encoding="utf-8")

    trust = None
    if run_trust:
        trust = run_trust_check(out / "trust")
        if not trust["ok"]:
            return {
                "decision": "reject",
                "error": "trust beat failed",
                "trust": trust,
                "morning": None,
            }

    try:
        request = triage(
            spec=load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec"),
            verdict=load(REPO / "contracts" / "examples" / "verdict.json", "verdict"),
            route=load(REPO / "harness" / "routes" / "smoke.json", "route"),
            out=out / "triage",
            offline=offline_triage,
        )
        fix_out = out / "fix"
        # Refuse to mount the signing key into the fixer workspace.
        if (fix_out / "fixer-work" / ".nightshift-signing-key").exists():
            raise SystemExit("signing key must not appear in fixer-work")
        run_fixer(
            request, fix_out,
            candidate_patch=None if use_muse else (
                candidate_patch or REPO / "agents" / "fixtures" / "fix-collision-mask.patch"
            ),
        )
        if (fix_out / "fixer-work").exists():
            leaked = list((fix_out / "fixer-work").rglob(".nightshift-signing-key"))
            if leaked:
                raise SystemExit(f"signing key leaked into fixer workspace: {leaked}")

        verification = verify(
            request, fix_out / "candidate.patch", out / "verify",
            observations_path=observations,
            skip_harness=skip_harness or observations is not None,
        )
        summary = build_report(
            verification=verification,
            candidate=fix_out / "candidate.patch",
            out=out / "morning",
            signing_key_path=signing_key,
        )
        return {
            "decision": verification["decision"],
            "morning": summary,
            "trust": trust,
            "triageSource": json.loads((out / "triage" / "triage.json").read_text()).get("source"),
            "fixerSource": json.loads((fix_out / "candidate.json").read_text()).get("source"),
        }
    except (Exception, SystemExit) as exc:  # noqa: BLE001 — overnight loop must not forge accept
        (out / "loop-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        return {
            "decision": "reject",
            "error": f"{type(exc).__name__}: {exc}",
            "trust": trust,
            "morning": None,
        }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=Path("runs/loop"))
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--mode", choices=("auto", "offline", "live"), default="auto")
    p.add_argument("--use-muse", action="store_true", help="force Muse Code (overrides --mode fixer)")
    p.add_argument("--online-triage", action="store_true", help="force Wonder triage")
    p.add_argument("--offline-triage", action="store_true", help="force offline triage")
    p.add_argument("--observations", type=Path,
                   default=REPO / "agents" / "fixtures" / "obs-fixed.json")
    p.add_argument("--candidate-patch", type=Path)
    p.add_argument("--skip-harness", action="store_true", default=True)
    p.add_argument("--no-skip-harness", action="store_true")
    p.add_argument("--no-trust", action="store_true", help="skip trust beat (not for demo path)")
    args = p.parse_args(argv)

    resolved = resolve_mode(args.mode)
    offline_triage = resolved["offline_triage"]
    use_muse = resolved["use_muse"]
    if args.offline_triage:
        offline_triage = True
    if args.online_triage:
        offline_triage = False
    if args.use_muse:
        use_muse = True
    skip_harness = False if args.no_skip_harness else args.skip_harness
    observations = None if args.no_skip_harness else args.observations

    print(
        f"mode={resolved['mode']} triage={'offline' if offline_triage else 'wonder'} "
        f"fixer={'muse' if use_muse else 'fixture'} harness={'skip' if skip_harness else 'live'}"
    )

    results = []
    for i in range(args.runs):
        run_out = args.out / f"run-{i:02d}"
        results.append(one_run(
            run_out,
            use_muse=use_muse,
            offline_triage=offline_triage,
            observations=observations,
            candidate_patch=args.candidate_patch,
            skip_harness=skip_harness,
            run_trust=not args.no_trust,
        ))
        print(f"run {i}: {results[-1]['decision']}"
              + (f" ({results[-1].get('error')})" if results[-1].get("error") else ""))

    accepted = sum(1 for r in results if r["decision"] == "accept")
    summary = {
        "mode": resolved,
        "runs": args.runs,
        "accepted": accepted,
        "results": results,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"{accepted} of {args.runs} accepted")
    return 0 if accepted == args.runs else 1


if __name__ == "__main__":
    sys.exit(main())
