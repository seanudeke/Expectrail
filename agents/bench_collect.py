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
JUDGE_DIR = REPO / "bench" / "judge"
DEMO_DIR = REPO / "bench" / "demo-loop"
DEMO_TITLE = re.compile(r"^Demo run (?P<run>\d+)$")
DEMO_MSG = re.compile(r"^decision (?P<decision>[a-z-]+); attempts (?P<tries>.*?); triage (?P<triage>\S+); "
                      r"fixer (?P<fixer>\S+); trust (?P<trust>\S+); verified on (?P<prov>\S+); signed (?P<signed>\S+); "
                      r"(?P<seconds>[\d.]+) s; SAM images (?P<sam>\d+)$")
JUDGE_TITLE = re.compile(r"^Judge (?P<case>(?:good|bad)/\S+)$")
JUDGE_MSG = re.compile(r"^label (?P<label>good|bad); SAM on (?P<sam>\S+); SAM off (?P<nosam>\S+); "
                       r"Muse screenshots (?P<muse>\S+); (?P<seconds>[\d.]+) s; live=(?P<live>True|False)"
                       r"(?:; SAM images (?P<samImages>\d+))?$")
MATRIX_TITLE = re.compile(r"^Fix matrix (?P<case>\S+/\S+) (?P<condition>screenshots|nightshift)$")
MATRIX_MSG = re.compile(r"^detected (?P<detected>[a-z-]+); outcome (?P<outcome>[a-z-]+); attempts (?P<n>\d+) "
                        r"\((?P<tries>[^)]*)\); (?P<seconds>[\d.]+) s; live=(?P<live>True|False)"
                        r"(?:; SAM images (?P<sam>\d+))?$")
REPO_SLUG = "seanudeke/Nightshift"
# sam-3.1 image segmentation, $2.50 per 1,000 images (https://dev.meta.ai/docs/pricing-rate-limits, Oct 29, 2026).
SAM_USD_PER_IMAGE = 2.50 / 1000


def spend(rows: list[dict], *, muse_key: str) -> dict:
    """What a set of results cost: SAM images (and dollars), Muse Code calls and job minutes.

    SAM images are counted only by runs from Oct 29 evening on; a run whose results carry no count
    reports None, never an estimate.
    """
    counted = [r["samImages"] for r in rows if r.get("samImages") is not None]
    images = sum(counted) if rows and len(counted) == len(rows) else None
    return {"samImages": images,
            "samUsd": round(images * SAM_USD_PER_IMAGE, 2) if images is not None else None,
            "museCalls": sum(int(r.get(muse_key) or 0) for r in rows),
            "jobMinutes": round(sum(r.get("seconds") or 0 for r in rows) / 60, 1)}


def _money(s: dict) -> str:
    if s["samImages"] is None:
        return "not counted"
    return f"{s['samImages']:,} (${s['samUsd']:.2f})"
TITLE = re.compile(r"^(?:Dev|Held-out) bench (?P<id>\S+)$")
TIME = re.compile(r"^(?:Bench|Held-out bench) time (?P<id>\S+)$")
SAM_IMAGES = re.compile(r"^Bench SAM images (?P<id>\S+)$")
CAUGHT = re.compile(r"(?P<label>caught|false alarm) with (?P<mode>SAM on|SAM off|Glimmer\+engine \(no SAM\)): "
                    r"(?P<value>[a-z-]+)")
CAUGHT_KEYS = {"SAM on": "caughtWithSamOn", "SAM off": "caughtWithSamOff",
               "Glimmer+engine (no SAM)": "caughtWithGlimmerEngine"}
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
        row[CAUGHT_KEYS[m["mode"]]] = m["value"]
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


def collect(run_ids, which: str, fetch=gh_json) -> dict:
    """Detection runs -> one table. Several runs fill in only variants an earlier run did not report
    (a job that never reached the bench, such as a Glimmer deployment that was still waking)."""
    run_ids = [run_ids] if isinstance(run_ids, int) else list(run_ids)
    rows: dict[str, dict] = {}
    runs = []
    for run_id in run_ids:
        run, notes = run_annotations(run_id, fetch)
        runs.append({"run": run_id, "runUrl": run.get("html_url"), "commit": run.get("head_sha"),
                     "date": run.get("created_at")})
        found: dict[str, dict] = {}
        seconds: dict[str, int] = {}
        images: dict[str, int] = {}
        for note in notes:
            title, message = note.get("title") or "", note.get("message") or ""
            if m := TITLE.match(title):
                found[m["id"]] = parse_message(message)
            elif m := TIME.match(title):
                seconds[m["id"]] = int(message.split()[0])
            elif m := SAM_IMAGES.match(title):
                images[m["id"]] = int(message.split()[0])
        for vid, row in found.items():
            if vid not in rows:
                rows[vid] = dict(row, seconds=seconds.get(vid), samImages=images.get(vid), run=run_id)
    if "clean" not in rows or len(rows) < 2:
        raise SystemExit(f"runs {run_ids}: no clean control or no variants among their annotations")
    judges = {"glimmer-engine" if r.get("caughtWithGlimmerEngine") is not None else "sam" for r in rows.values()}
    if len(judges) != 1:
        raise SystemExit(f"runs {run_ids} mix judges {sorted(judges)}; collect each judge on its own")
    judge = judges.pop()
    run_spend = spend(list(rows.values()), muse_key="none")
    clean = rows.pop("clean")
    variants = [{"id": k, **v} for k, v in sorted(rows.items())]

    def tally(key: str) -> dict:
        return {"yes": sum(v.get(key) == "yes" for v in variants), "of": len(variants)}

    first = runs[0]
    doc = {
        "format": FORMAT,
        "set": which,
        "judge": judge,
        "run": first["run"],
        "runUrl": first["runUrl"],
        "commit": first["commit"],
        "date": first["date"],
        "caughtWithSamOn": tally("caughtWithSamOn"),
        "caughtWithSamOff": tally("caughtWithSamOff"),
        "falseAlarm": {"withSamOn": clean["caughtWithSamOn"], "withSamOff": clean["caughtWithSamOff"],
                       "cleanRoutes": clean["routes"]},
        "clean": clean,
        "variants": variants,
        "rerun": f"bench/rerun-detection.sh {which}" + (f" main {judge}" if judge != "sam" else ""),
        "spend": run_spend,
    }
    if judge == "glimmer-engine":
        doc["caughtWithGlimmerEngine"] = tally("caughtWithGlimmerEngine")
        doc["falseAlarm"]["withGlimmerEngine"] = clean.get("caughtWithGlimmerEngine")
    if len(runs) > 1:
        doc["runs"] = runs
    return doc


def _alarm(value: str | None) -> str:
    return {"no": "none", "yes": "yes", "needs-review": "needs review"}.get(value or "", str(value))


def parse_matrix_message(message: str) -> dict:
    m = MATRIX_MSG.match(" ".join(message.split()))
    if not m:
        raise ValueError(f"unrecognised fix-matrix annotation: {message!r}")
    tries = [t.split(": ", 1)[1] for t in m["tries"].split("; ") if ": " in t]
    return {"detected": m["detected"], "outcome": m["outcome"], "attemptsUsed": int(m["n"]), "attempts": tries,
            "seconds": float(m["seconds"]), "live": m["live"] == "True",
            "samImages": int(m["sam"]) if m["sam"] is not None else None}


def collect_matrix(run_ids: list[int], which: str, fetch=gh_json) -> dict:
    """Fix-matrix runs -> one row per case and condition (the first non-error result, in run order)."""
    rows: dict[tuple[str, str], dict] = {}
    runs = []
    for run_id in run_ids:
        run, notes = run_annotations(run_id, fetch, prefix="run (")
        runs.append({"run": run_id, "runUrl": run.get("html_url"), "commit": run.get("head_sha"),
                     "date": run.get("created_at")})
        everything = []
        for note in notes:
            m = MATRIX_TITLE.match(note.get("title") or "")
            if not m:
                continue
            key = (m["case"], m["condition"])
            row = {"case": key[0], "condition": key[1], "run": run_id, **parse_matrix_message(note["message"])}
            everything.append(row)
            earlier = rows.get(key)
            if earlier is None or earlier["outcome"] == "error":
                if earlier is not None:
                    row["replaces"] = {"run": earlier["run"], "outcome": earlier["outcome"]}
                rows[key] = row
        # Spend counts every result the run produced, errors and later-replaced ones included.
        runs[-1]["spend"] = spend(everything, muse_key="attemptsUsed")
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


JUDGES = {"nightshiftSam": "Nightshift, SAM on", "nightshiftNoSam": "Nightshift, SAM off",
          "museScreenshots": "Muse from screenshots"}
REASON_LABELS = {"SAM on": "nightshiftSam", "SAM off": "nightshiftNoSam", "Muse screenshots": "museScreenshots"}


def parse_judge_reasons(message: str) -> dict:
    """'SAM on: a | b ;; Muse screenshots: c' -> {"nightshiftSam": ["a", "b"], "museScreenshots": ["c"]}."""
    out = {}
    for part in message.split(" ;; "):
        label, sep, text = part.partition(": ")
        if sep and label.strip() in REASON_LABELS:
            out[REASON_LABELS[label.strip()]] = [x.strip() for x in text.split(" | ") if x.strip()]
    return out


def collect_judge_run(run_id: int, fetch=gh_json) -> dict:
    """One judge-benchmark run -> per-case decisions (and reasons, when the run published them)."""
    run, notes = run_annotations(run_id, fetch, prefix="judge-run")
    rows, reasons = [], {}
    decided = lambda v: v if v in ("accept", "reject", "needs-review") else None
    for note in notes:
        title = note.get("title") or ""
        message = " ".join((note.get("message") or "").split())
        if title.startswith("Judge reasons "):
            reasons[title[len("Judge reasons "):]] = parse_judge_reasons(message)
            continue
        m = JUDGE_TITLE.match(title)
        if not m:
            continue
        msg = JUDGE_MSG.match(message)
        if not msg:
            raise ValueError(f"unrecognised judge annotation: {note.get('message')!r}")
        rows.append({"case": m["case"], "label": msg["label"], "seconds": float(msg["seconds"]),
                     "live": msg["live"] == "True",
                     "samImages": int(msg["samImages"]) if msg["samImages"] is not None else None,
                     "museCalls": 1 if msg["muse"] in ("accept", "reject", "needs-review", "None") else 0,
                     "decisions": {"nightshiftSam": decided(msg["sam"]), "nightshiftNoSam": decided(msg["nosam"]),
                                   "museScreenshots": decided(msg["muse"])}})
    if not rows:
        raise SystemExit(f"run {run_id}: no judge results among its annotations")
    if not all(r["live"] for r in rows):
        raise SystemExit(f"run {run_id}: offline judge results are plumbing checks, not benchmark numbers")
    for r in rows:
        if r["case"] in reasons:
            r["reasons"] = reasons[r["case"]]
    rows.sort(key=lambda r: (r["label"] != "bad", r["case"]))
    good = [r for r in rows if r["label"] == "good"]
    bad = [r for r in rows if r["label"] == "bad"]
    judges = {j: {"goodAccepted": sum(r["decisions"][j] == "accept" for r in good), "good": len(good),
                  "badAccepted": sum(r["decisions"][j] == "accept" for r in bad), "bad": len(bad),
                  "undecided": sum(r["decisions"][j] is None for r in rows)} for j in JUDGES}
    return {"run": run_id, "runUrl": run.get("html_url"), "commit": run.get("head_sha"),
            "date": run.get("created_at"), "judges": judges, "rows": rows,
            "spend": spend(rows, muse_key="museCalls")}


def collect_judge(run_ids, fetch=gh_json) -> dict:
    """Judge-benchmark runs -> each run's counts, and per judge the cases whose decision changed between runs."""
    runs = [collect_judge_run(r, fetch) for r in ([run_ids] if isinstance(run_ids, int) else run_ids)]
    cases = sorted({r["case"] for run in runs for r in run["rows"]},
                   key=lambda c: (not c.startswith("bad/"), c))
    changed = {j: [c for c in cases
                   if len({r["decisions"][j] for run in runs for r in run["rows"] if r["case"] == c}) > 1]
               for j in JUDGES}
    return {"format": "nightshift.judge-bench/v1", "runs": runs, "changedBetweenRuns": changed}


def judge_markdown(doc: dict) -> str:
    runs = doc["runs"]
    lines = ["# Judge benchmark", "",
             "Written by `python3 -m agents.bench_collect --judge` from the runs' own annotations; do not edit by hand.",
             "Runs: " + ", ".join(f"[{r['run']}]({r['runUrl']}) ({r['date'][:10]}, commit {r['commit'][:7]})"
                                  for r in runs) + ".", "",
             "| Judge | Run | Good fixes accepted | Bad fixes accepted | Undecided |", "| --- | --- | --- | --- | --- |"]
    for j, name in JUDGES.items():
        for r in runs:
            s = r["judges"][j]
            lines.append(f"| {name} | {r['run']} | {s['goodAccepted']} of {s['good']} | "
                         f"{s['badAccepted']} of {s['bad']} | {s['undecided']} |")
    lines += ["", "Spend per run: " + "; ".join(
        f"{r['run']}: {r['spend']['museCalls']} Muse Code judge calls, SAM images {_money(r['spend'])}, "
        f"{r['spend']['jobMinutes']:.0f} job minutes" for r in runs) + "."]
    if len(runs) > 1:
        lines += ["", "Cases whose decision changed between runs: "
                  + "; ".join(f"{name}: {', '.join(doc['changedBetweenRuns'][j]) or 'none'}"
                              for j, name in JUDGES.items()) + "."]
    lines += ["", "Each cell lists the decision in each run, in the order above.", "",
              "| Case | Right answer | " + " | ".join(JUDGES.values()) + " |", "| --- | --- | --- | --- | --- |"]
    cases = sorted({r["case"] for run in runs for r in run["rows"]}, key=lambda c: (not c.startswith("bad/"), c))
    by = {(run["run"], r["case"]): r for run in runs for r in run["rows"]}
    for c in cases:
        label = next(by[(run["run"], c)]["label"] for run in runs if (run["run"], c) in by)
        cells = [", ".join(str((by.get((run["run"], c)) or {}).get("decisions", {}).get(j) or "none") for run in runs)
                 for j in JUDGES]
        lines.append(f"| {c} | {'accept' if label == 'good' else 'reject'} | " + " | ".join(cells) + " |")
    reasons = [(run["run"], r) for run in runs for r in run["rows"] if r.get("reasons")]
    if reasons:
        lines += ["", "## Reasons", "",
                  ("Failed checks for Nightshift (routes left out); Muse's own words before its decision."), ""]
        for run_id, r in reasons:
            lines.append(f"- **{r['case']}** (run {run_id}): " + "; ".join(
                f"{JUDGES[j]}: {' / '.join(v)}" for j, v in r["reasons"].items() if j in JUDGES and v))
    return "\n".join(lines) + "\n"


def collect_demo(run_id: int, fetch=gh_json) -> dict:
    """A live demo-loop run -> each overnight run's outcome, and how many were accepted."""
    run, notes = run_annotations(run_id, fetch, prefix="demo-run")
    rows = []
    for note in notes:
        m = DEMO_TITLE.match(note.get("title") or "")
        if not m:
            continue
        msg = DEMO_MSG.match(" ".join((note.get("message") or "").split()))
        if not msg:
            raise ValueError(f"unrecognised demo annotation: {note.get('message')!r}")
        tries = [t.split(": ", 1)[1] for t in msg["tries"].split("; ") if ": " in t]
        rows.append({"run": int(m["run"]), "decision": msg["decision"], "attempts": tries,
                     "triage": msg["triage"], "fixer": msg["fixer"], "trust": msg["trust"],
                     "verifiedOn": msg["prov"], "signed": msg["signed"] == "True",
                     "seconds": float(msg["seconds"]), "samImages": int(msg["sam"])})
    jobs = fetch(f"repos/{REPO_SLUG}/actions/runs/{run_id}/jobs?per_page=100")["jobs"]
    asked = sum(1 for j in jobs if j["name"].startswith("demo-run"))
    if not rows:
        raise SystemExit(f"run {run_id}: no demo results among its annotations")
    rows.sort(key=lambda r: r["run"])
    accepted = sum(r["decision"] == "accept" for r in rows)
    return {"format": "nightshift.demo-loop/v0", "run": run_id, "runUrl": run.get("html_url"),
            "commit": run.get("head_sha"), "date": run.get("created_at"), "asked": asked, "recorded": len(rows),
            "accepted": accepted, "firstAttempt": sum(r["attempts"][:1] == ["accept"] for r in rows),
            "spend": spend(rows, muse_key="none") | {"museCalls": sum(len(r["attempts"]) for r in rows)},
            "rows": rows}


def demo_markdown(doc: dict) -> str:
    s = doc["spend"]
    lines = ["# Demo path, live", "",
             ("Written by `python3 -m agents.bench_collect --demo --run <id>` from the run's own annotations; "
              "do not edit by hand."),
             (f"Run [{doc['run']}]({doc['runUrl']}), {doc['date'][:10]}, commit {doc['commit'][:7]}. Each run is the "
              "overnight loop end to end in its own job: Wonder triage, Muse Code in bubblewrap, the Godot harness, "
              "the verifier with SAM on and the private held-out routes, the signed morning report and the trust check."),
             "",
             (f"**{doc['accepted']} of {doc['asked']} runs accepted**, {doc['firstAttempt']} on the first attempt. "
              f"Muse Code attempts {s['museCalls']}; SAM images {_money(s)}; {s['jobMinutes']:.0f} job minutes."), "",
             "| Run | Decision | Attempts | Triage | Fixer | Trust | Signed | Minutes | SAM images |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in doc["rows"]:
        lines.append(f"| {r['run']} | {r['decision']} | {', '.join(r['attempts']) or 'none'} | {r['triage']} | "
                     f"{r['fixer']} | {r['trust']} | {'yes' if r['signed'] else 'no'} | {r['seconds'] / 60:.0f} | "
                     f"{r['samImages']:,} |")
    return "\n".join(lines) + "\n"


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
    lines += ["", ("Spend per run, every case it ran. An error records no attempts even when Muse Code ran before it, "
                   "so attempts are a floor for a run with errors."), "",
              "| Run | Muse Code attempts | SAM images (USD) | Job minutes |", "| --- | --- | --- | --- |"]
    for r in doc["runs"]:
        s = r.get("spend")
        if s:
            lines.append(f"| {r['run']} | {s['museCalls']} | {_money(s)} | {s['jobMinutes']:.0f} |")
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
        glimmer = d.get("judge") == "glimmer-engine"
        vision, key, alarm = (("Glimmer+engine (no SAM)", "caughtWithGlimmerEngine", "withGlimmerEngine") if glimmer
                              else ("SAM", "caughtWithSamOn", "withSamOn"))
        seen = d.get(key) or on
        runs = ", ".join(f"[{r['run']}]({r['runUrl']})" for r in d.get("runs") or [{"run": d["run"], "runUrl": d["runUrl"]}])
        title = f"{d['set']}, judged by Glimmer checked against the engine" if glimmer else d["set"]
        lines += [f"## {title} (run {runs}, {d['date'][:10]}, commit {d['commit'][:7]})", "",
                  (f"Caught with {vision}: **{seen['yes']} of {seen['of']}**. Without {'vision' if glimmer else 'SAM'}: "
                   f"**{off['yes']} of {off['of']}**. "
                   f"False alarms on the clean game ({fa['cleanRoutes']} routes): {_alarm(fa.get(alarm))} with {vision}, "
                   f"{_alarm(fa['withSamOff'])} without."), ""]
        if d.get("spend") and glimmer:
            lines += [(f"Spend: no SAM. Glimmer runs on a Fireworks deployment billed by the hour, not counted here; "
                       f"{d['spend']['jobMinutes']:.0f} job minutes."), ""]
        elif d.get("spend"):
            lines += [f"Spend: SAM images {_money(d['spend'])}; {d['spend']['jobMinutes']:.0f} job minutes.", ""]
        lines += [f"| Variant | Caught, {'Glimmer+engine' if glimmer else 'SAM on'} | Caught, SAM off | Failing checks (routes) |",
                  "| --- | --- | --- | --- |"]
        for v in d["variants"]:
            failing = ", ".join(f"{name} {c['fail']}" for name, c in v["checks"].items() if c["fail"]) or "none"
            lines.append(f"| {v['id']} | {v.get(key)} | {v['caughtWithSamOff']} | {failing} |")
        lines.append("")
    return "\n".join(lines)


def write(doc: dict, out_dir: Path = OUT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    judge = doc.get("judge", "sam")
    path = out_dir / (f"{doc['set']}.json" if judge == "sam" else f"{doc['set']}-{judge}.json")
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out_dir.glob("*.json"))]
    (out_dir / "README.md").write_text(markdown(docs), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--run", type=int, required=True, action="append",
                   help="the dev-bench or heldout-bench run id (with --matrix: one or more fix-matrix runs)")
    p.add_argument("--set", choices=("dev", "held-out"), default="dev", dest="which")
    p.add_argument("--matrix", action="store_true", help="fix-matrix runs instead of a detection run")
    p.add_argument("--judge", action="store_true", help="a judge-benchmark run instead of a detection run")
    p.add_argument("--demo", action="store_true", help="a live demo-loop run (Fix matrix, bench demo)")
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)
    if args.demo:
        out = args.out or DEMO_DIR
        doc = collect_demo(args.run[-1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "demo.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        (out / "README.md").write_text(demo_markdown(doc), encoding="utf-8")
        print(f"wrote {out / 'demo.json'} and {out / 'README.md'}")
        return 0
    if args.judge:
        out = args.out or JUDGE_DIR
        doc = collect_judge(args.run)
        out.mkdir(parents=True, exist_ok=True)
        (out / "judge.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        (out / "README.md").write_text(judge_markdown(doc), encoding="utf-8")
        print(f"wrote {out / 'judge.json'} and {out / 'README.md'}")
        return 0
    if args.matrix:
        out = args.out or MATRIX_DIR
        doc = collect_matrix(args.run, args.which)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{args.which}.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        (out / "README.md").write_text(matrix_markdown(doc), encoding="utf-8")
        print(f"wrote {out / (args.which + '.json')} and {out / 'README.md'}")
        return 0
    args.out = args.out or OUT_DIR
    path = write(collect(args.run, args.which), args.out)
    print(f"wrote {path} and {args.out / 'README.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
