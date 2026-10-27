"""Run a route N times and report how much the replays differ (Gate: 10 of 10 identical).

    python3 -m harness.replay_check --route harness/routes/smoke.json --runs 10 [--patch ...]

Exit status 0 only if every run produced the same frames and the same player trace as the first.
Identical on one machine does not mean identical across machines: compare runs on the machine
that will produce the evidence.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness.run import run


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--route", type=Path, required=True)
    p.add_argument("--runs", type=int, default=10)
    p.add_argument("--patch", type=Path, action="append", default=[],
                   help="patch to apply (repeatable; order is seed then candidate)")
    p.add_argument("--out", type=Path, default=Path("runs/replay-check"))
    args = p.parse_args(argv)
    patches = args.patch or None
    first_frames = first_trace = None
    identical = 0
    for i in range(args.runs):
        out = args.out / f"run-{i:02d}"
        replay = run(args.route, out, patch=None, patches=patches)
        trace = [row.get("player") for row in json.loads((out / "trace.json").read_text())["rows"]]
        if first_frames is None:
            first_frames, first_trace = replay["frameSha256"], trace
            identical += 1
            print(f"run {i}: reference ({len(first_frames)} frames)")
            continue
        frames_diff = sum(a != b for a, b in zip(first_frames, replay["frameSha256"])) + abs(
            len(first_frames) - len(replay["frameSha256"]))
        trace_diff = sum(a != b for a, b in zip(first_trace, trace)) + abs(len(first_trace) - len(trace))
        same = frames_diff == 0 and trace_diff == 0
        identical += same
        print(f"run {i}: {'identical' if same else f'{frames_diff} frames and {trace_diff} trace rows differ'}")
    print(f"{identical} of {args.runs} runs identical to the first")
    summary = {"route": str(args.route),
               "patches": [str(p) for p in patches] if patches else None,
               "runs": args.runs, "identical": identical}
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return 0 if identical == args.runs else 1


if __name__ == "__main__":
    sys.exit(main())
