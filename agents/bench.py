"""Regenerate agents-lane offline bench stubs from an overnight summary.json.

These are filmable measurement stubs for the demo path — NOT the Gate-2 evaluation
matrix in docs/evaluation.md. Provenance is always agents-offline-stub.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness.run import REPO
from nightshift.contracts import load, validate

DEFAULT_OUT = REPO / "bench" / "overnight-offline.json"


def from_summary(summary: dict) -> dict:
    validate(summary, "overnight-summary")
    return {
        "format": "nightshift.agents-bench-stub/v0",
        "provenance": "agents-offline-stub",
        "disclaimer": (
            "Offline agents-lane film stub regenerated from overnight-summary. "
            "Not a Gate-2 evaluation matrix result; not Meta API spend."
        ),
        "mode": summary.get("mode", {}).get("mode"),
        "runs": summary["runs"],
        "accepted": summary["accepted"],
        "verificationProvenance": summary["verificationProvenance"],
        "cost": summary["cost"],
        "timing": summary["timing"],
        "decisions": [r.get("decision") for r in summary.get("results", [])],
        "gameplayFails": [
            r.get("gameplay")
            for r in summary.get("results", [])
            if isinstance(r.get("gameplay"), dict) and r["gameplay"].get("result") == "fail"
        ],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--summary", type=Path, required=True, help="overnight summary.json")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args(argv)
    summary = load(args.summary, "overnight-summary")
    stub = from_summary(summary)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(stub, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out} provenance={stub['provenance']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
