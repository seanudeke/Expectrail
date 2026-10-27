"""Build a nightshift.repair-request/v0 for the Muse Code fixer.

    python3 -m agents.orchestrator --spec ... --verdict ... --route ... --out rr.json \\
        [--base-patch bugs/physics-fall-through/v1.patch] [--key-frame frames/f00000008.png]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness.run import REPO, tree_digest
from nightshift.contracts import load, validate

DEFAULT_EDITABLE = ["player/**", "level/**"]


def build_repair_request(
    *,
    request_id: str,
    spec: dict,
    verdict: dict,
    route: dict,
    base_tree: str | None = None,
    base_patch: str | None = None,
    editable: list[str] | None = None,
    key_frames: list[str] | None = None,
    attempts: int = 3,
    notes: str | None = None,
) -> dict:
    game = REPO / "game" / "platformer"
    doc = {
        "format": "nightshift.repair-request/v0",
        "id": request_id,
        "base": {
            "tree": base_tree or tree_digest(game),
            "patch": base_patch,
        },
        "editable": list(editable or DEFAULT_EDITABLE),
        "failing": [
            {
                "spec": spec,
                "verdict": verdict,
                "route": route,
                **({"keyFrames": key_frames} if key_frames else {}),
            }
        ],
        "budget": {"attempts": attempts, "minutesPerAttempt": 15},
    }
    if notes is not None:
        doc["notes"] = notes
    else:
        doc["notes"] = (
            "Held-out variants, the evaluator and the gameplay checks are not in your workspace."
        )
    validate(doc, "repair-request")
    return doc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--id", default="rr-0001")
    p.add_argument("--spec", type=Path, required=True)
    p.add_argument("--verdict", type=Path, required=True)
    p.add_argument("--route", type=Path, required=True)
    p.add_argument("--base-patch", type=Path)
    p.add_argument("--base-tree")
    p.add_argument("--editable", action="append", default=[])
    p.add_argument("--key-frame", action="append", default=[])
    p.add_argument("--attempts", type=int, default=3)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--notes")
    args = p.parse_args(argv)
    doc = build_repair_request(
        request_id=args.id,
        spec=load(args.spec, "test-spec"),
        verdict=load(args.verdict, "verdict"),
        route=load(args.route, "route"),
        base_tree=args.base_tree,
        base_patch=str(args.base_patch) if args.base_patch else None,
        editable=args.editable or None,
        key_frames=args.key_frame or None,
        attempts=args.attempts,
        notes=args.notes,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
