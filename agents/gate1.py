"""Gate 1 end-to-end: repair-request → fixer → verifier → morning for physics-fall-through.

    python3 -m agents.gate1 --out runs/gate1 \\
        [--candidate-patch agents/fixtures/fix-collision-mask.patch]

Builds a repair request from the example failing verdict (or --verdict), runs the
fixer (fixture or muse), then the verifier, then a filmable morning report + RC.
Exit 0 only on verification accept.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agents.fixer import run_fixer
from agents.keys import load_dotenv
from agents.orchestrator import build_repair_request
from agents.report import build_report
from agents.signing import generate_run_keys
from agents.trust import POISON
from agents.verifier import verify
from harness.run import REPO
from expectrail.contracts import load

DEFAULT_BEFORE = REPO / "agents" / "fixtures" / "frames" / "before-fall.png"
DEFAULT_AFTER = REPO / "agents" / "fixtures" / "frames" / "after-fixed.png"


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=Path("runs/gate1"))
    p.add_argument("--candidate-patch", type=Path,
                   default=REPO / "agents" / "fixtures" / "fix-collision-mask.patch")
    p.add_argument("--use-muse", action="store_true",
                   help="call muse exec instead of the fixture candidate patch")
    p.add_argument("--verdict", type=Path, default=REPO / "contracts" / "examples" / "verdict.json")
    p.add_argument("--spec", type=Path, default=REPO / "agents" / "specs" / "player-stays-above-ground.json")
    p.add_argument("--route", type=Path, default=REPO / "harness" / "routes" / "smoke.json")
    p.add_argument("--skip-harness", action="store_true")
    p.add_argument("--observations", type=Path)
    p.add_argument("--before", type=Path, action="append", default=[])
    p.add_argument("--after", type=Path, action="append", default=[])
    p.add_argument("--no-morning", action="store_true", help="skip morning/RC packaging")
    p.add_argument("--require-sandbox", action="store_true",
                   help="confine Muse under bubblewrap; fail closed if unavailable")
    p.add_argument("--plant-poison", action="store_true",
                   help="write poisoned readme into fixer-work before Muse / fixture apply")
    args = p.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    request = build_repair_request(
        request_id="rr-gate1",
        spec=load(args.spec, "test-spec"),
        verdict=load(args.verdict, "verdict"),
        route=load(args.route, "route"),
        base_patch="bugs/physics-fall-through/v1.patch",
        key_frames=["frames/f00000008.png", "frames/f00000016.png"],
    )
    rr_path = args.out / "repair-request.json"
    rr_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")

    fix_out = args.out / "fix"
    candidate = None if args.use_muse else args.candidate_patch
    run_fixer(
        request, fix_out, candidate_patch=candidate,
        require_sandbox=args.require_sandbox,
        plant_poison=args.plant_poison,
    )
    cand = fix_out / "candidate.patch"

    # Ensure poison remains for the Trust beat even if Muse deleted it.
    if args.plant_poison:
        poison_dir = fix_out / "fixer-work" / "player"
        poison_dir.mkdir(parents=True, exist_ok=True)
        poison_path = poison_dir / "readme-extra.txt"
        if not poison_path.exists():
            poison_path.write_text(POISON, encoding="utf-8")

    verify_out = args.out / "verify"
    doc = verify(
        request, cand, verify_out, route=args.route,
        observations_path=args.observations, skip_harness=args.skip_harness,
    )
    print(f"gate1 {doc['decision']}: {'; '.join(doc['reasons'])}")

    if not args.no_morning:
        before = args.before or [DEFAULT_BEFORE]
        after = args.after or [DEFAULT_AFTER]
        gameplay_path = verify_out / "verdict-gameplay.json"
        keys = generate_run_keys(args.out / "verifier-host")
        morning = build_report(
            verification=doc,
            candidate=cand,
            out=args.out / "morning",
            before=before,
            after=after,
            signing_key_path=keys["privatePathObj"],
            gameplay_verdict=gameplay_path if gameplay_path.is_file() else None,
            verification_path=verify_out / "verification.json",
        )
        print(
            f"gate1 morning: {args.out / 'morning' / 'morning-report.md'} "
            f"rc={morning['decision']} pub={morning.get('publicKey', '')[:16]}…"
        )

    return 0 if doc["decision"] == "accept" else 1


if __name__ == "__main__":
    sys.exit(main())
