"""Write a detection benchmark run into bench/: the numbers the README and the video quote.

The detection benchmark (agents/heldout_bench.py, modes dev-bench and heldout-bench of the SAM
probe workflow) publishes one annotation per variant: its id, per-check counts over the routes,
and whether it was caught with SAM on and off. This reads those annotations back through the
GitHub API (``gh``) and writes ``bench/detection/<set>.json`` and the table in
``bench/detection/README.md``. Nothing private is involved: the annotations are what the run
published.

    python3 -m agents.bench_collect --run 40841977642 --set dev
    python3 -m agents.bench_collect --run 40805529944 --set held-out
    python3 -m agents.bench_collect --matrix --run 40916077549 --run 40927304209 --set dev

``--matrix`` reads fix-matrix runs instead (annotations "Fix matrix <case> <condition>") and writes
``bench/fix-matrix/<set>.json``. With several runs, each case and condition keeps its first
result that is not an error, in run order: a later run only fills in what an earlier one could
not decide, never replaces a result. Every row says which run it came from.

To rerun a set and record it in one go: ``bench/rerun-detection.sh dev`` (or ``held-out``).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from harness.run import REPO

FORMAT = "nightshift.detection-bench/v0"
MATRIX_FORMAT = "nightshift.fix-matrix-bench/v0"
OUT_DIR = REPO / "bench" / "detection"
MATRIX_DIR = REPO / "bench" / "fix-matrix"
MATRIX_TITLE = re.compile(r"^Fix matrix (?P<case>\S+/\S+) (?P<condition>screenshots|nightshift)$")
MATRIX_MSG = re.compile(r"^detected (?P<detected>[a-z-]+); outcome (?P<outcome>[a-z-]+); attempts (?P<n>\d+) "
                        r"\((?P<tries>[^)]*)\); (?P<seconds>[\d.]+) s; live=(?P<live>True|False)$")
REPO_SLUG = "seanudeke/Nightshift"
TITLE = re.compile(r"^(?:Dev|Held-out) bench (?P<id>\S+)$")
TIME = re.compile(r"^(?:Bench|Held-out bench) time (?P<id>\S+)$")
CAUGHT = re.compile(r"(?P<label>caught|false alarm) with SAM (?P<mode>on|off): (?P<value>[a-z-]+)")
CHECK = re.compile(r"^(?P<name>[a-z0-9-]+) (?P<counts>\d+ [a-z-]+(?:, \d+ [a-z-]+)*)$")


def gh_json(path: str) -> object:
    out = subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def run_annotations(run_id: int, fetch=gh_json, prefix: str = "heldout-bench") -> tuple[dict, list[dict]]:
    run = fetch(f"repos/{REPO_SLUG}/actions/runs/{run_id}")
    jobs = fetch(f"repos/{REPO_SLUG}/actions/runs/{run_id}/jobs?per_page=100")["jobs"]
    notes: list[dict] = []
    for job in jobs:
        if job["name"].startswith(prefix):
            notes += fetch(f"repos/{REPO_SLUG}/check-runs/{job['id']}/annotations?per_page=100")
    return run, notes


def parse_message(message: str) -> dict:
    """One variant's annotation message -> caught flags, route count and per-check counts."""
    head, _, tail = message.partition("; over ")
    row: dict = {"caughtWithSamOn": None, "caughtWithSamOff": None, "checks": {}}
    for m in CAUGHT.finditer(head):
        row["caughtWithSamOn" if m["mode"] == "on" else "caughtWithSamOff"] = m["value"]
    routes, _, checks = tail.partition(" routes: ")
    row["routes"] = int(routes) if routes.isdigit() else None
    for part in checks.split("; "):
        m = CHECK.match(part.strip())
        if not m:
            raise ValueError(f"unrecognised check in annotation: {part!r}")
        counts = {"fail": 0, "needs-review": 0, "pass": 0}
        for bit in m["counts"].split(", "):
            n, result = bit.split(" ", 1)
            counts[result] = int(n)
        row["checks"][m["name"]] = counts
    return row


def collect(run_id: int, which: str, fetch=gh_json) -> dict:
    run, notes = run_annotations(run_id, fetch)
    rows: dict[str, dict] = {}
    seconds: dict[str, int] = {}
    for note in notes:
        title, message = note.get("title") or "", note.get("message") or ""
        if m := TITLE.match(title):
            rows[m["id"]] = parse_message(message)
        elif m := TIME.match(title):
            seconds[m["id"]] = int(message.split()[0])
    if "clean" not in rows or len(rows) < 2:
        raise SystemExit(f"run {run_id}: no clean control or no variants among its annotations")
    for vid, row in rows.items():
        row["seconds"] = seconds.get(vid)
    clean = rows.pop("clean")
    variants = [{"id": k, **v} for k, v in sorted(rows.items())]

    def tally(key: str) -> dict:
        return {"yes": sum(v[key] == "yes" for v in variants), "of": len(variants)}

    return {
        "format": FORMAT,
        "set": which,
        "run": run_id,
        "runUrl": run.get("html_url"),
        "commit": run.get("head_sha"),
        "date": run.get("created_at"),
        "caughtWithSamOn": tally("caughtWithSamOn"),
        "caughtWithSamOff": tally("caughtWithSamOff"),
        "falseAlarm": {"withSamOn": clean["caughtWithSamOn"], "withSamOff": clean["caughtWithSamOff"],
                       "cleanRoutes": clean["routes"]},
        "clean": clean,
        "variants": variants,
        "rerun": f"bench/rerun-detection.sh {which}",
    }


def _alarm(value: str | None) -> str:
    return {"no": "none", "yes": "yes", "needs-review": "needs review"}.get(value or "", str(value))


def parse_matrix_message(message: str) -> dict:
    m = MATRIX_MSG.match(" ".join(message.split()))
    if not m:
        raise ValueError(f"unrecognised fix-matrix annotation: {message!r}")
    tries = [t.split(": ", 1)[1] for t in m["tries"].split("; ") if ": " in t]
    return {"detected": m["detected"], "outcome": m["outcome"], "attemptsUsed": int(m["n"]), "attempts": tries,
            "seconds": float(m["seconds"]), "live": m["live"] == "True"}


def collect_matrix(run_ids: list[int], which: str, fetch=gh_json) -> dict:
    """Fix-matrix runs -> one row per case and condition (the first non-error result, in run order)."""
    rows: dict[tuple[str, str], dict] = {}
    runs = []
    for run_id in run_ids:
        run, notes = run_annotations(run_id, fetch, prefix="run (")
        runs.append({"run": run_id, "runUrl": run.get("html_url"), "commit": run.get("head_sha"),
                     "date": run.get("created_at")})
        for note in notes:
            m = MATRIX_TITLE.match(note.get("title") or "")
            if not m:
                continue
            key = (m["case"], m["condition"])
            row = {"case": key[0], "condition": key[1], "run": run_id, **parse_matrix_message(note["message"])}
            earlier = rows.get(key)
            if earlier is None or earlier["outcome"] == "error":
                if earlier is not None:
                    row["replaces"] = {"run": earlier["run"], "outcome": earlier["outcome"]}
                rows[key] = row
    if not rows:
        raise SystemExit(f"runs {run_ids}: no fix-matrix results among their annotations")
    if not all(r["live"] for r in rows.values()):
        raise SystemExit("an offline (live=False) result is not a fix rate; collect live runs only")
    final = sorted(rows.values(), key=lambda r: (r["case"], r["condition"]))
    conditions = {}
    for c in ("screenshots", "nightshift"):
        mine = [r for r in final if r["condition"] == c]
        conditions[c] = {o: sum(r["outcome"] == o for r in mine)
                         for o in ("fixed", "not-fixed", "not-detected", "needs-review", "error")}
        conditions[c]["cases"] = len(mine)
        conditions[c]["firstAttemptFixes"] = sum(r["outcome"] == "fixed" and r["attempts"][:1] == ["accept"]
                                                 for r in mine)
    return {"format": MATRIX_FORMAT, "set": which, "runs": runs, "conditions": conditions, "rows": final,
            "rule": "first non-error result per case and condition, in run order"}


def matrix_markdown(doc: dict) -> str:
    runs = ", ".join(f"[{r['run']}]({r['runUrl']}) ({r['commit'][:7]})" for r in doc["runs"])
    lines = ["# Fix matrix", "",
             "Written by `python3 -m agents.bench_collect --matrix` from the runs' own annotations; do not edit by hand.",
             f"Set: {doc['set']}. Runs: {runs}. Rule: {doc['rule']}.", "",
             "| Condition | Fixed | Not fixed | Not detected | Needs review | Errors |",
             "| --- | --- | --- | --- | --- | --- |"]
    for c, s in doc["conditions"].items():
        lines.append(f"| {c} | {s['fixed']} of {s['cases']} | {s['not-fixed']} | {s['not-detected']} | "
                     f"{s['needs-review']} | {s['error']} |")
    lines += ["", "| Case | Condition | Outcome | Attempts | Minutes | Run |", "| --- | --- | --- | --- | --- | --- |"]
    for r in doc["rows"]:
        note = f" (replaces an error in {r['replaces']['run']})" if r.get("replaces") else ""
        lines.append(f"| {r['case']} | {r['condition']} | {r['outcome']} | {', '.join(r['attempts']) or 'none'} | "
                     f"{r['seconds'] / 60:.0f} | {r['run']}{note} |")
    return "\n".join(lines) + "\n"


def markdown(docs: list[dict]) -> str:
    lines = ["# Detection benchmark", "",
             "Written by `python3 -m agents.bench_collect` from the run's own annotations; do not edit by hand.",
             "A variant is caught when any check fails on at least one route. Rerun a set with",
             "`bench/rerun-detection.sh dev` or `bench/rerun-detection.sh held-out`.", ""]
    for d in docs:
        on, off, fa = d["caughtWithSamOn"], d["caughtWithSamOff"], d["falseAlarm"]
        lines += [f"## {d['set']} (run [{d['run']}]({d['runUrl']}), {d['date'][:10]}, commit {d['commit'][:7]})", "",
                  f"Caught with SAM: **{on['yes']} of {on['of']}**. Without SAM: **{off['yes']} of {off['of']}**. "
                  f"False alarms on the clean game ({fa['cleanRoutes']} routes): {_alarm(fa['withSamOn'])} with SAM, "
                  f"{_alarm(fa['withSamOff'])} without.", "",
                  "| Variant | Caught, SAM on | Caught, SAM off | Failing checks (routes) |",
                  "| --- | --- | --- | --- |"]
        for v in d["variants"]:
            failing = ", ".join(f"{name} {c['fail']}" for name, c in v["checks"].items() if c["fail"]) or "none"
            lines.append(f"| {v['id']} | {v['caughtWithSamOn']} | {v['caughtWithSamOff']} | {failing} |")
        lines.append("")
    return "\n".join(lines)


def write(doc: dict, out_dir: Path = OUT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{doc['set']}.json"
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out_dir.glob("*.json"))]
    (out_dir / "README.md").write_text(markdown(docs), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--run", type=int, required=True, action="append",
                   help="the dev-bench or heldout-bench run id (with --matrix: one or more fix-matrix runs)")
    p.add_argument("--set", choices=("dev", "held-out"), required=True, dest="which")
    p.add_argument("--matrix", action="store_true", help="fix-matrix runs instead of a detection run")
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)
    if args.matrix:
        out = args.out or MATRIX_DIR
        doc = collect_matrix(args.run, args.which)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{args.which}.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        (out / "README.md").write_text(matrix_markdown(doc), encoding="utf-8")
        print(f"wrote {out / (args.which + '.json')} and {out / 'README.md'}")
        return 0
    if len(args.run) != 1:
        p.error("a detection set is one run")
    args.out = args.out or OUT_DIR
    args.run = args.run[0]
    path = write(collect(args.run, args.which), args.out)
    print(f"wrote {path} and {args.out / 'README.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
