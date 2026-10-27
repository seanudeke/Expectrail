"""Overnight agent loop: triage → fix → verify → morning report (+ trust beat).

    python3 -m agents.loop --out runs/loop [--mode auto|offline|live] [--runs 1]

Modes:
  offline — fixtures only (CI default; no Meta keys required)
  live    — Wonder + Muse Code; requires keys (fails closed if missing)
  auto    — live steps when keys/muse are available, else fixtures

Exit 0 only if every run ends with verification accept. Crashes never forge accept.
Live/online triage that soft-falls to offline fixtures is treated as reject.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from agents.fixer import run_fixer
from agents.keys import resolve_mode, seal_mode_flags
from agents.report import build_report, write_loop_rollup
from agents.triage import WONDER_MODEL, triage
from agents.trust import run_trust_check
from agents.verifier import verify
from harness.run import REPO
from nightshift.contracts import load

DEFAULT_BEFORE = REPO / "agents" / "fixtures" / "frames" / "before-fall.png"
DEFAULT_AFTER = REPO / "agents" / "fixtures" / "frames" / "after-fixed.png"


def one_run(
    out: Path,
    *,
    use_muse: bool,
    offline_triage: bool,
    observations: Path | None,
    candidate_patch: Path | None,
    skip_harness: bool,
    run_trust: bool,
    before_frames: list[Path] | None = None,
    after_frames: list[Path] | None = None,
) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    # Signing key is created only AFTER the fixer returns so Muse never sees it
    # on disk during exec (deny-by-absence for the overnight topology).
    signing_key = out / "verifier-host" / ".nightshift-signing-key"
    trust = None

    try:
        request = triage(
            spec=load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec"),
            verdict=load(REPO / "contracts" / "examples" / "verdict.json", "verdict"),
            route=load(REPO / "harness" / "routes" / "smoke.json", "route"),
            out=out / "triage",
            offline=offline_triage,
        )
        triage_meta = json.loads((out / "triage" / "triage.json").read_text(encoding="utf-8"))
        triage_source = triage_meta.get("source")
        # Live / online triage must not soft-accept offline-fallback as success.
        if not offline_triage and triage_source != WONDER_MODEL:
            raise SystemExit(
                f"live Wonder triage required; got source={triage_source!r}"
            )

        fix_out = out / "fix"
        if signing_key.exists():
            # Stale key from a prior partial run — remove before Muse so it is absent.
            signing_key.unlink()
        run_fixer(
            request, fix_out,
            candidate_patch=None if use_muse else (
                candidate_patch or REPO / "agents" / "fixtures" / "fix-collision-mask.patch"
            ),
        )
        fixer_work = fix_out / "fixer-work"
        if not fixer_work.is_dir():
            raise SystemExit("fixer-work missing after fixer")
        leaked = list(fixer_work.rglob(".nightshift-signing-key"))
        if leaked:
            raise SystemExit(f"signing key leaked into fixer workspace: {leaked}")

        # Materialize signing key only on the verifier side, after fixer completes.
        signing_key.parent.mkdir(parents=True, exist_ok=True)
        signing_key.write_text("DEMO-FAKE-SIGNING-KEY-NOT-REAL\n", encoding="utf-8")

        if run_trust:
            trust = run_trust_check(
                out / "trust",
                fixer_work=fixer_work,
                verifier_host=signing_key.parent,
            )
            if not trust["ok"]:
                return {
                    "decision": "reject",
                    "error": "trust beat failed",
                    "trust": trust,
                    "morning": None,
                    "triageSource": triage_source,
                    "verificationProvenance": "harness" if not skip_harness else "fixture",
                }

        verification = verify(
            request, fix_out / "candidate.patch", out / "verify",
            observations_path=observations,
            skip_harness=skip_harness or observations is not None,
        )
        before = list(before_frames) if before_frames is not None else [DEFAULT_BEFORE]
        after = list(after_frames) if after_frames is not None else [DEFAULT_AFTER]
        if not before or not after:
            raise SystemExit("morning report requires non-empty before and after frames")
        summary = build_report(
            verification=verification,
            candidate=fix_out / "candidate.patch",
            out=out / "morning",
            before=before,
            after=after,
            signing_key_path=signing_key,
        )
        return {
            "decision": verification["decision"],
            "morning": summary,
            "trust": trust,
            "triageSource": triage_source,
            "fixerSource": json.loads((fix_out / "candidate.json").read_text()).get("source"),
            "verificationProvenance": "harness" if not skip_harness else "fixture",
        }
    except (Exception, SystemExit) as exc:  # noqa: BLE001 — overnight loop must not forge accept
        (out / "loop-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        return {
            "decision": "reject",
            "error": f"{type(exc).__name__}: {exc}",
            "trust": trust,
            "morning": None,
            "verificationProvenance": "harness" if not skip_harness else "fixture",
        }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=Path("runs/loop"))
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--mode", choices=("auto", "offline", "live"), default="auto")
    p.add_argument("--use-muse", action="store_true", help="force Muse Code (sealed: not with --mode offline)")
    p.add_argument("--online-triage", action="store_true", help="force Wonder triage (sealed)")
    p.add_argument("--offline-triage", action="store_true", help="force offline triage (sealed: not with --mode live)")
    p.add_argument("--observations", type=Path,
                   default=REPO / "agents" / "fixtures" / "obs-fixed.json")
    p.add_argument("--candidate-patch", type=Path)
    p.add_argument("--skip-harness", action="store_true", default=True)
    p.add_argument("--no-skip-harness", action="store_true")
    p.add_argument("--no-trust", action="store_true", help="skip trust beat (not for demo path)")
    p.add_argument("--before", type=Path, action="append", default=[],
                   help="before frame(s) for morning report (default: fixture PNG)")
    p.add_argument("--after", type=Path, action="append", default=[],
                   help="after frame(s) for morning report (default: fixture PNG)")
    args = p.parse_args(argv)

    resolved = seal_mode_flags(
        resolve_mode(args.mode),
        force_offline_triage=args.offline_triage,
        force_online_triage=args.online_triage,
        force_muse=args.use_muse,
    )
    offline_triage = resolved["offline_triage"]
    use_muse = resolved["use_muse"]
    skip_harness = False if args.no_skip_harness else args.skip_harness
    observations = None if args.no_skip_harness else args.observations
    provenance = "harness" if not skip_harness else "fixture"
    before_frames = args.before or None
    after_frames = args.after or None

    print(
        f"mode={resolved['mode']} triage={'offline' if offline_triage else 'wonder'} "
        f"fixer={'muse' if use_muse else 'fixture'} harness={provenance}"
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
            before_frames=before_frames,
            after_frames=after_frames,
        ))
        print(f"run {i}: {results[-1]['decision']}"
              + (f" ({results[-1].get('error')})" if results[-1].get("error") else ""))

    accepted = sum(1 for r in results if r["decision"] == "accept")
    summary = {
        "mode": resolved,
        "runs": args.runs,
        "accepted": accepted,
        "verificationProvenance": provenance,
        "results": results,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    rollup = write_loop_rollup(args.out, summary=summary)
    print(f"{accepted} of {args.runs} accepted; morning rollup: {rollup}")
    return 0 if accepted == args.runs else 1


if __name__ == "__main__":
    sys.exit(main())
