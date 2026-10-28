"""Overnight agent loop: triage → fix (bounded retries) → verify → morning (+ trust).

    python3 -m agents.loop --out runs/loop [--mode auto|offline|live] [--runs 1]

Modes:
  offline — fixtures only (CI default; no Meta keys required)
  live    — Wonder + Muse Code; requires keys (fails closed if missing)
  auto    — live steps when keys/muse are available, else fixtures

Live Muse honors repair-request ``budget.attempts`` (re-prompt on verify reject /
empty patch). Fixture path is always a single attempt.
Exit 0 only if every run ends with verification accept. Crashes never forge accept.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from agents.fixer import run_fixer
from agents.keys import resolve_mode, seal_mode_flags
from agents.report import build_report, gameplay_film_stub, write_loop_rollup
from agents.signing import generate_run_keys
from agents.triage import WONDER_MODEL, triage
from agents.trust import run_trust_check
from agents.verifier import verify
from harness.run import REPO
from nightshift.contracts import load, validate

DEFAULT_BEFORE = REPO / "agents" / "fixtures" / "frames" / "before-fall.png"
DEFAULT_AFTER = REPO / "agents" / "fixtures" / "frames" / "after-fixed.png"


def _promote_candidate(attempt_out: Path, fix_out: Path) -> None:
    fix_out.mkdir(parents=True, exist_ok=True)
    for name in (
        "candidate.patch", "candidate.json", "muse.log", "muse-prompt.txt",
        "muse-env-names.json", "sandbox.json", "repair-request.json",
    ):
        src = attempt_out / name
        if src.is_file():
            shutil.copy2(src, fix_out / name)
    work = attempt_out / "fixer-work"
    dest = fix_out / "fixer-work"
    if work.is_dir():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(work, dest, ignore=shutil.ignore_patterns(".godot"))


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
    require_sandbox: bool = False,
) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    signing_key = out / "verifier-host" / ".nightshift-signing-key"
    trust = None
    t0 = time.perf_counter()
    attempt_films: list[dict] = []

    def _with_timing(payload: dict) -> dict:
        payload["timing"] = {"wallClockMs": round((time.perf_counter() - t0) * 1000, 3)}
        payload["attempts"] = attempt_films
        payload["attemptsConsumed"] = len(attempt_films)
        return payload

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
        if not offline_triage and triage_source != WONDER_MODEL:
            raise SystemExit(
                f"live Wonder triage required; got source={triage_source!r}"
            )

        fix_out = out / "fix"
        max_attempts = 1 if not use_muse else int(request["budget"]["attempts"])
        fixture = None if use_muse else (
            candidate_patch or REPO / "agents" / "fixtures" / "fix-collision-mask.patch"
        )
        prior_reject: dict | None = None
        verification = None
        last_meta: dict | None = None

        for attempt in range(1, max_attempts + 1):
            if signing_key.exists():
                signing_key.unlink()
            pub = signing_key.with_name(signing_key.name + ".pub")
            if pub.exists():
                pub.unlink()
            attempt_out = fix_out / f"attempt-{attempt:02d}"
            meta = run_fixer(
                request,
                attempt_out,
                candidate_patch=fixture,
                attempt=attempt,
                allow_empty=use_muse,
                require_sandbox=require_sandbox,
                prior_reject=prior_reject,
            )
            last_meta = meta
            _promote_candidate(attempt_out, fix_out)
            film = {
                "attempt": attempt,
                "source": meta.get("source"),
                "ok": meta.get("ok", True),
                "empty": meta.get("empty", False),
                "patchSha256": meta.get("patchSha256"),
                "dir": str(attempt_out.relative_to(out)) if attempt_out.is_relative_to(out) else str(attempt_out),
            }
            attempt_films.append(film)

            if meta.get("empty"):
                prior_reject = {"reason": "empty-patch", "attempt": attempt}
                film["decision"] = "retry-empty"
                continue

            fixer_work = fix_out / "fixer-work"
            if not fixer_work.is_dir():
                raise SystemExit("fixer-work missing after fixer")
            leaked = list(fixer_work.rglob(".nightshift-signing-key"))
            if leaked:
                raise SystemExit(f"signing key leaked into fixer workspace: {leaked}")

            generate_run_keys(signing_key.parent)

            if run_trust and trust is None:
                trust = run_trust_check(
                    out / "trust",
                    fixer_work=fixer_work,
                    verifier_host=signing_key.parent,
                    require_sandbox=require_sandbox,
                )
                if not trust["ok"]:
                    return _with_timing({
                        "decision": "reject",
                        "error": "trust beat failed",
                        "trust": trust,
                        "morning": None,
                        "gameplay": None,
                        "triageSource": triage_source,
                        "fixerSource": meta.get("source"),
                        "verificationProvenance": "harness" if not skip_harness else "fixture",
                    })

            verify_dir = out / "verify" / f"attempt-{attempt:02d}"
            verification = verify(
                request, fix_out / "candidate.patch", verify_dir,
                observations_path=observations,
                skip_harness=skip_harness or observations is not None,
            )
            # Promote latest verify to out/verify for morning consumers.
            final_verify = out / "verify"
            for name in ("verification.json", "verdict-gameplay.json"):
                src = verify_dir / name
                if src.is_file():
                    final_verify.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, final_verify / name)
            film["decision"] = verification["decision"]
            film["reasons"] = verification.get("reasons")
            if verification["decision"] == "accept":
                break
            prior_reject = {
                "decision": verification["decision"],
                "reasons": verification.get("reasons"),
                "attempt": attempt,
            }
            for stale in (signing_key, signing_key.with_name(signing_key.name + ".pub")):
                if stale.exists():
                    stale.unlink()

        if verification is None or not (out / "verify" / "verification.json").is_file():
            return _with_timing({
                "decision": "reject",
                "error": "budget exhausted without an acceptable candidate",
                "trust": trust,
                "morning": None,
                "gameplay": None,
                "triageSource": triage_source,
                "fixerSource": (last_meta or {}).get("source"),
                "verificationProvenance": "harness" if not skip_harness else "fixture",
            })

        before = list(before_frames) if before_frames is not None else [DEFAULT_BEFORE]
        after = list(after_frames) if after_frames is not None else [DEFAULT_AFTER]
        if not before or not after:
            raise SystemExit("morning report requires non-empty before and after frames")
        if not signing_key.exists():
            generate_run_keys(signing_key.parent)
        verify_out = out / "verify"
        gameplay_path = verify_out / "verdict-gameplay.json"
        summary = build_report(
            verification=verification,
            candidate=fix_out / "candidate.patch",
            out=out / "morning",
            before=before,
            after=after,
            signing_key_path=signing_key,
            gameplay_verdict=gameplay_path if gameplay_path.is_file() else None,
            verification_path=verify_out / "verification.json",
        )
        return _with_timing({
            "decision": verification["decision"],
            "morning": summary,
            "gameplay": gameplay_film_stub(summary),
            "trust": trust,
            "triageSource": triage_source,
            "fixerSource": (last_meta or {}).get("source"),
            "verificationProvenance": "harness" if not skip_harness else "fixture",
        })
    except (Exception, SystemExit) as exc:  # noqa: BLE001 — overnight loop must not forge accept
        (out / "loop-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        payload = {
            "decision": "reject",
            "error": f"{type(exc).__name__}: {exc}",
            "trust": trust,
            "morning": None,
            "gameplay": None,
            "verificationProvenance": "harness" if not skip_harness else "fixture",
        }
        if "triage_source" in locals() and triage_source is not None:
            payload["triageSource"] = triage_source
        fix_meta = out / "fix" / "candidate.json"
        if fix_meta.is_file():
            try:
                payload["fixerSource"] = json.loads(fix_meta.read_text(encoding="utf-8")).get("source")
            except (OSError, json.JSONDecodeError):
                pass
        return _with_timing(payload)


def main(argv: list[str] | None = None) -> int:
    from agents.keys import load_dotenv
    load_dotenv()
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
    p.add_argument("--require-sandbox", action="store_true",
                   help="require OS sandbox for Muse + trust blocked canary")
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

    started = datetime.now(timezone.utc)
    t_loop = time.perf_counter()
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
            require_sandbox=args.require_sandbox,
        ))
        print(f"run {i}: {results[-1]['decision']}"
              + (f" ({results[-1].get('error')})" if results[-1].get("error") else ""))

    finished = datetime.now(timezone.utc)
    accepted = sum(1 for r in results if r["decision"] == "accept")
    if offline_triage and not use_muse:
        cost = {
            "modelCalls": 0,
            "costUsd": None,
            "costProvenance": "unmetered-offline",
        }
    else:
        # Only Muse attempts count as model calls; fixture/auto-without-muse stays 0.
        muse_calls = 0
        if use_muse:
            muse_calls = sum(int(r.get("attemptsConsumed") or 0) for r in results)
        cost = {
            "modelCalls": muse_calls,
            "costUsd": None,
            "costProvenance": "unmetered-live-unset",
        }
    summary = {
        "format": "nightshift.overnight-summary/v0",
        "mode": resolved,
        "runs": args.runs,
        "accepted": accepted,
        "verificationProvenance": provenance,
        "cost": cost,
        "timing": {
            "wallClockMs": round((time.perf_counter() - t_loop) * 1000, 3),
            "startedAt": started.isoformat(),
            "finishedAt": finished.isoformat(),
        },
        "results": results,
    }
    validate(summary, "overnight-summary")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    rollup = write_loop_rollup(args.out, summary=summary)
    print(f"{accepted} of {args.runs} accepted; morning rollup: {rollup}")
    return 0 if accepted == args.runs else 1


if __name__ == "__main__":
    sys.exit(main())
