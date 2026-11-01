"""The demo path, live: one overnight run per process, and the tally of N of them.

The Gate 2 demo item is "passes 10 runs in a row". ``agents.loop --runs 10 --mode offline`` passes 10
of 10 in under two seconds because it runs on fixtures and cannot fail. This runs the real loop
(Wonder triage, Muse Code in bubblewrap, the Godot harness, the verifier with SAM on and the private
held-out routes, the signed morning report, the trust check) once, records what happened and what
SAM it used, and ``--summarize`` counts the accepted runs across jobs.

    python -m agents.demo_loop --run 3 --out runs/demo          # one live run (keys required)
    python -m agents.demo_loop --summarize results --expected 10
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

FORMAT = "expectrail.demo-run/v0"
LOOP_ARGS = ["--runs", "1", "--mode", "live", "--no-skip-harness", "--require-sandbox"]


def one(run: int, out: Path, loop_main=None) -> dict:
    """One live loop run in this process; never raises, a crash is a recorded non-accept."""
    from agents.sam_observations import sam_images_since, sam_usage

    if loop_main is None:
        from agents.loop import main as loop_main
    work = out / f"run-{run:02d}"
    before, t0 = sam_usage(), time.perf_counter()
    row: dict = {"format": FORMAT, "run": run}
    try:
        code = loop_main(["--out", str(work), *LOOP_ARGS])
        summary = json.loads((work / "summary.json").read_text(encoding="utf-8"))
        result = (summary.get("results") or [{}])[0]
        row.update(
            exitCode=code,
            decision=result.get("decision"),
            attempts=[a.get("decision") for a in result.get("attempts") or []],
            triageSource=result.get("triageSource"),
            fixerSource=result.get("fixerSource"),
            trustOk=(result.get("trust") or {}).get("ok"),
            verificationProvenance=result.get("verificationProvenance"),
            signed=bool((result.get("morning") or {}).get("signature")),
            error=result.get("error"),
        )
        if result.get("review"):
            row["review"] = {k: result["review"].get(k) for k in ("status", "evidenceLabel", "reasons")}
        # What the fixer was told on each attempt (agents/escalation.py) and who judged (agents/judge_ladder.py).
        row["briefings"] = [a.get("briefing") for a in result.get("attempts") or []]
        if result.get("judge"):
            row["judge"] = result["judge"]
        if result.get("preflight"):
            row["preflight"] = result["preflight"]
        from agents.observations import DRILL_ENV

        if os.environ.get(DRILL_ENV):
            row["drill"] = os.environ[DRILL_ENV]
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - a crash is a result, never an accept
        row.update(decision="error", error=f"{type(exc).__name__}: {exc}"[:300])
    row["wallClockSeconds"] = round(time.perf_counter() - t0, 1)
    row["samImages"] = sam_images_since(before)
    work.mkdir(parents=True, exist_ok=True)
    (work / "result.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    return row


def annotation(row: dict) -> str:
    tries = "; ".join(f"{i}: {d}" for i, d in enumerate(row.get("attempts") or [], 1)) or "none"
    line = (f"::notice title=Demo run {row['run']}::decision {row['decision']}; attempts {tries}; "
            f"triage {row.get('triageSource')}; fixer {row.get('fixerSource')}; trust "
            f"{'ok' if row.get('trustOk') else row.get('trustOk')}; verified on {row.get('verificationProvenance')}; "
            f"signed {row.get('signed')}; "
            f"{row['wallClockSeconds']} s; SAM images {row['samImages']}")
    if row.get("review"):  # its own line: the Demo run line's format is parsed by agents.bench_collect
        rv = row["review"]
        why = "; ".join(rv.get("reasons") or [])[:200] or "none"
        line += (f"\n::notice title=Demo run {row['run']} review::{rv.get('status')}; "
                 f"{rv.get('evidenceLabel')}; {' '.join(why.split())}")
    if row.get("briefings"):
        line += f"\n::notice title=Demo run {row['run']} briefing::{', '.join(str(b) for b in row['briefings'])}"
    judge = row.get("judge")
    if judge:  # its own line, like the review: who judged, and every step the judge ladder took
        steps = "; ".join(
            f"{s['judge']}{' (retry)' if s.get('retry') else ''}: "
            + (f"skipped, {s['skipped']}" if "skipped" in s else
               f"no answer ({s.get('error')})" if s.get("unavailable") else str(s.get("decision")))
            for s in judge.get("steps") or [])
        drill = f"drill {row['drill']}; " if row.get("drill") else ""
        line += (f"\n::notice title=Demo run {row['run']} judge::{drill}judged by {judge.get('judgedBy')}; "
                 f"stopped {judge.get('stopped')}; {' '.join(steps.split())[:700]}")
    if row.get("drill"):  # its own line: agents.bench_collect refuses a run that carries one
        line += f"\n::notice title=Demo run {row['run']} drill::{row['drill']}"
    if row.get("error"):
        line += f"\n::warning title=Demo run {row['run']} error::{' '.join(str(row['error']).split())[:300]}"
    return line


def summarize(root: Path, expected: int) -> tuple[dict, str]:
    rows = sorted((json.loads(p.read_text(encoding="utf-8")) for p in root.rglob("result.json")),
                  key=lambda r: r.get("run", 0))
    rows = [r for r in rows if r.get("format") == FORMAT]
    accepted = sum(r.get("decision") == "accept" for r in rows)
    images = sum(int(r.get("samImages") or 0) for r in rows)
    doc = {"expected": expected, "recorded": len(rows), "accepted": accepted, "samImages": images,
           "samUsd": round(images * 2.50 / 1000, 2), "rows": rows}
    lines = ["# Demo loop, live", "",
             (f"**{accepted} of {expected} runs accepted** ({len(rows)} recorded). SAM images {images:,} "
              f"(${doc['samUsd']:.2f} at list price)."), "",
             "| Run | Decision | Attempts | Triage | Fixer | Trust | Minutes | SAM images |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        lines.append(f"| {r['run']} | {r.get('decision')} | {', '.join(r.get('attempts') or []) or 'none'} | "
                     f"{r.get('triageSource')} | {r.get('fixerSource')} | {'ok' if r.get('trustOk') else r.get('trustOk')} | "
                     f"{r['wallClockSeconds'] / 60:.0f} | {r.get('samImages')} |")
    return doc, "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", type=int, help="run number: one live loop run")
    g.add_argument("--summarize", type=Path, help="a folder of runs' result.json files")
    p.add_argument("--out", type=Path, default=Path("runs/demo"))
    p.add_argument("--expected", type=int, default=10)
    args = p.parse_args(argv)
    if args.summarize:
        doc, md = summarize(args.summarize, args.expected)
        print(md, end="")
        print(f"::notice title=Demo loop::{doc['accepted']} of {doc['expected']} accepted "
              f"({doc['recorded']} recorded); SAM images {doc['samImages']}")
        return 0
    row = one(args.run, args.out)
    print(annotation(row))
    return 0 if row["decision"] == "accept" else 1


if __name__ == "__main__":
    sys.exit(main())
