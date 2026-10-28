"""Replay every seeded bug and fail if any of them leaves the picture unchanged.

    python3 -m harness.check_seeded [--route harness/routes/smoke.json] [--out runs/seeded-check]
                                    [--only physics-fall-through/v2 ...]

A seeded variant whose frames are identical to the clean game is not a bug anyone could see, not a
player and not SAM, so the benchmark would count it as a miss it can never catch. This renders the
clean route once, then each variant in bugs/<family>/v*.patch on the same route, and compares frame
hashes. Writes <out>/summary.json and exits 1 if any variant changes no frame.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness.run import REPO, run


def seeded_patches(only: list[str] | None = None) -> list[Path]:
    patches = sorted((REPO / "bugs").glob("*/v*.patch"))
    if only:
        wanted = {name.removesuffix(".patch") for name in only}
        patches = [p for p in patches if f"{p.parent.name}/{p.stem}" in wanted]
        missing = wanted - {f"{p.parent.name}/{p.stem}" for p in patches}
        if missing:
            raise SystemExit(f"no such seeded variant: {', '.join(sorted(missing))}")
    return patches


def compare(clean: dict, variant: dict) -> dict:
    a, b = clean["frameSha256"], variant["frameSha256"]
    differing = sum(1 for x, y in zip(a, b) if x != y) + abs(len(a) - len(b))
    return {
        "frames": len(b),
        "framesDifferingFromClean": differing,
        "traceDiffersFromClean": clean["trace"]["sha256"] != variant["trace"]["sha256"],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--route", type=Path, default=REPO / "harness" / "routes" / "smoke.json")
    p.add_argument("--out", type=Path, default=REPO / "runs" / "seeded-check")
    p.add_argument("--only", nargs="*", help="limit to family/vN names")
    args = p.parse_args(argv)

    patches = seeded_patches(args.only)
    clean = run(args.route, args.out / "clean")
    rows = []
    for patch in patches:
        name = f"{patch.parent.name}/{patch.stem}"
        replay = run(args.route, args.out / name.replace("/", "_"), patches=[patch])
        row = {"variant": name, "patch": patch.relative_to(REPO).as_posix(), **compare(clean, replay)}
        row["visible"] = row["framesDifferingFromClean"] > 0
        rows.append(row)
        status = "ok" if row["visible"] else "INVISIBLE"
        print(f"{status:9} {name}: {row['framesDifferingFromClean']}/{row['frames']} frames differ from clean"
              f"{', trace differs' if row['traceDiffersFromClean'] else ''}")

    summary = {
        "format": "nightshift.seeded-check/v0",
        "route": args.route.name,
        "variants": rows,
        "ok": all(r["visible"] for r in rows),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if not summary["ok"]:
        bad = ", ".join(r["variant"] for r in rows if not r["visible"])
        print(f"seeded variants with no visible change: {bad}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
