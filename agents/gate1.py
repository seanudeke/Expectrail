"""Gate 1 end-to-end: repair-request → fixer → verifier for physics-fall-through.

    python3 -m agents.gate1 --out runs/gate1 \\
        [--candidate-patch agents/fixtures/fix-collision-mask.patch]

Builds a repair request from the example failing verdict (or --verdict), runs the
fixer (fixture or muse), then the verifier. Exit 0 only on verification accept.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agents.fixer import run_fixer
from agents.orchestrator import build_repair_request
from agents.verifier import verify
from harness.run import REPO
from nightshift.contracts import load


def main(argv: list[str] | None = None) -> int:
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
    run_fixer(request, fix_out, candidate_patch=candidate)
    cand = fix_out / "candidate.patch"

    doc = verify(
        request, cand, args.out / "verify", route=args.route,
        observations_path=args.observations, skip_harness=args.skip_harness,
    )
    print(f"gate1 {doc['decision']}: {'; '.join(doc['reasons'])}")
    return 0 if doc["decision"] == "accept" else 1


if __name__ == "__main__":
    sys.exit(main())
