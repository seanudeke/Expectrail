"""Run advisory discovery, or render its record as a report.

    python -m expectrail.discovery.cli discover --profile discovery/platformer.profile.json \\
        --snapshot clean:reference --snapshot build-a:base:path/to/a.patch --out out/discovery \\
        [--planner off|spark] [--probes id,id] [--max-episodes N] [--label "FRESH LIVE"]
    python -m expectrail.discovery.cli report out/discovery/discovery-run.json [more runs...]
    python -m expectrail.discovery.cli annotate out/discovery/discovery-run.json     # in CI
    python -m expectrail.discovery.cli collect --run <workflow run id>               # record a CI run

Discovery never accepts or rejects a fix; the report says what was found, how often it reproduced,
what was rejected on the healthy reference, and what was not exercised.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from expectrail.contracts import load_strict


def _snapshot(text: str) -> dict:
    parts = text.split(":", 2)
    if len(parts) < 2 or parts[1] not in ("reference", "base"):
        raise argparse.ArgumentTypeError(f"--snapshot NAME:reference|base[:PATCH], got {text!r}")
    patch = Path(parts[2]) if len(parts) == 3 and parts[2] else None
    if patch is not None and not patch.is_file():
        raise argparse.ArgumentTypeError(f"no patch at {patch}")
    return {"name": parts[0], "role": parts[1], "patch": patch}


def report(runs: list[dict]) -> str:
    lines = ["# Advisory discovery", ""]
    for doc in runs:
        lines += [f"## {doc['runId']}", "",
                  f"Evidence: **{doc['evidenceLabel']}**, condition **{doc['contextManifest']['condition']}**, "
                  f"{doc['completion']}{' (' + doc['stopReason'] + ')' if doc['stopReason'] else ''}. "
                  f"{doc['usage']['episodes']} replays in {doc['usage']['wallSeconds']:.0f} s.", "",
                  "Withheld from every stage: " + "; ".join(doc["contextManifest"]["withheld"]) + ".", "",
                  "| Snapshot | Role | Replays | pass | fail | not exercised | insufficient | error |",
                  "|---|---|---:|---:|---:|---:|---:|---:|"]
        for s in doc["snapshots"]:
            cov = doc["coverage"].get(s["name"], {"episodes": 0, "results": {}})
            r = cov["results"]
            lines.append(f"| {s['name']} | {s['role']} | {cov['episodes']} | {r.get('pass', 0)} | {r.get('fail', 0)} | "
                         f"{r.get('not_exercised', 0)} | {r.get('insufficient_observation', 0)} | "
                         f"{r.get('execution_error', 0)} |")
        lines += ["", "### Findings", ""]
        if not doc["findings"]:
            lines.append("None: no contract failed on a base snapshot without also failing on the reference.")
        else:
            lines += ["| Snapshot | Contract | Probes | Reproduced | Observation |", "|---|---|---|---|---|"]
            for f in doc["findings"]:
                rep = f"{f['reproduction']['failures']}/{f['reproduction']['runs']} ({f['lifecycle']})"
                lines.append(f"| {f['snapshot']} | `{f['specId']}` ({f['expectationRef']['authority']}) | "
                             f"{', '.join(f['probeIds'])} | {rep} | {f['observation']} |")
            probes = sorted({p for f in doc["findings"] for p in f["probeIds"]})
            lines += ["", "Rerun the probes behind these findings on a build (each finding names its probes):", "",
                      "    python -m expectrail.discovery.cli discover --profile discovery/platformer.profile.json \\",
                      "        --snapshot NAME:base:PATCH --out runs/rerun --probes " + ",".join(probes)]
        rejected = [c for c in doc["candidates"] if c["lifecycle"] == "rejected"]
        lines += ["", "### Rejected on the healthy reference", ""]
        lines += [f"- `{c['specId']}` ({c['source']}): {c['detail']}" for c in rejected] or ["None."]
        lines += ["", "### Stages", ""]
        lines += [f"- {s['name']}: {s['status']}. {s['detail']}" for s in doc["stages"]]
        if doc["diagnostics"]:
            lines += ["", "### Diagnostics", ""] + [f"- {d}" for d in doc["diagnostics"][:20]]
        lines += ["", "A finding is advisory: a contract inferred from the game's code or proposed by a model failed "
                  "on this build, three times out of three, and passed on the healthy reference. It does not "
                  "reject anything. No finding means none within these probes and contracts, nothing more.", ""]
    return "\n".join(lines)


def annotation(doc: dict) -> str:
    """One GitHub notice per job: the numbers the collector reads back (artifacts are not always
    reachable, annotations are)."""
    bases = [s["name"] for s in doc["snapshots"] if s["role"] == "base"]
    planner = next((s for s in doc["stages"] if s["name"] == "planner"), {"status": "skipped", "detail": ""})
    compact = {
        "runId": doc["runId"], "snapshots": [[s["name"], s["role"]] for s in doc["snapshots"]],
        "completion": doc["completion"], "stopReason": doc["stopReason"], "episodes": doc["usage"]["episodes"],
        "wallSeconds": doc["usage"]["wallSeconds"], "coverage": {k: v["results"] for k, v in doc["coverage"].items()},
        "findings": [[f["snapshot"], f["specId"], f["lifecycle"], f["reproduction"]["failures"],
                      f["reproduction"]["runs"], f["probeIds"]] for f in doc["findings"]],
        "rejected": [c["specId"] for c in doc["candidates"] if c["lifecycle"] == "rejected"],
        "modelCandidates": [[c["specId"], c["lifecycle"]] for c in doc["candidates"] if c["source"] == "model"],
        "plannerProbes": [p["id"] for p in doc["probes"] if p["source"] == "planner"],
        "planner": [planner["status"], planner["detail"][:300]],
        "diagnostics": len(doc["diagnostics"]),
    }
    return f"::notice title=Discovery {'+'.join(bases) or 'reference'}::{json.dumps(compact, separators=(',', ':'))}"


def collect(run_id: int, out_dir: Path, fetch=None) -> dict:
    """Read a discovery workflow run's notices back into bench/discovery/run-<id>.json."""
    from agents.bench_collect import gh_json, run_annotations

    run, notes = run_annotations(run_id, fetch or gh_json, prefix="discovery")
    jobs = [json.loads(n["message"]) for n in notes
            if (n.get("title") or "").startswith("Discovery ") and not n["title"].startswith("Discovery time ")]
    if not jobs:
        raise SystemExit(f"run {run_id}: no discovery notices")
    clean_fails = {sid for j in jobs if any(n == "clean" for n, _ in j["snapshots"])
                   for snap, sid, *_ in j["findings"] if snap == "clean"}
    rows = []
    for j in sorted(jobs, key=lambda j: j["snapshots"][0][0]):
        for snap, sid, lifecycle, failures, runs, probes in j["findings"]:
            rows.append({"snapshot": snap, "specId": sid, "lifecycle": lifecycle, "failures": failures, "runs": runs,
                         "probes": probes, "alsoFailsOnClean": sid in clean_fails and snap != "clean"})
    doc = {"run": run_id, "url": run.get("html_url"), "headSha": run.get("head_sha"), "createdAt": run.get("created_at"),
           "condition": "development-reproduction", "jobs": jobs, "findings": rows}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"run-{run_id}.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return doc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("discover")
    d.add_argument("--profile", type=Path, required=True)
    d.add_argument("--snapshot", type=_snapshot, action="append", required=True)
    d.add_argument("--out", type=Path, required=True)
    d.add_argument("--planner", choices=("off", "spark"), default="off")
    d.add_argument("--probes", help="comma-separated probe ids (default: the whole library)")
    d.add_argument("--max-episodes", type=int)
    d.add_argument("--max-seconds", type=int)
    d.add_argument("--label", default="FRESH LIVE", choices=("FRESH LIVE", "RECORDED LIVE", "SAMPLE", "MIXED OR INCOMPLETE"))
    d.add_argument("--run-id")
    r = sub.add_parser("report")
    r.add_argument("runs", type=Path, nargs="+")
    r.add_argument("--out", type=Path)
    a = sub.add_parser("annotate")
    a.add_argument("run", type=Path)
    c = sub.add_parser("collect")
    c.add_argument("--run", type=int, required=True)
    c.add_argument("--out", type=Path, default=Path("bench/discovery"))
    args = p.parse_args(argv)

    if args.cmd == "annotate":
        print(annotation(load_strict(args.run, "discovery-run")))
        return 0
    if args.cmd == "collect":
        doc = collect(args.run, args.out)
        print(f"{len(doc['jobs'])} jobs, {len(doc['findings'])} findings: {args.out / f'run-{args.run}.json'}")
        return 0

    if args.cmd == "report":
        text = report([load_strict(path, "discovery-run") for path in args.runs])
        if args.out:
            args.out.write_text(text, encoding="utf-8")
        else:
            print(text)
        return 0

    from expectrail.discovery.run import discover

    planner = None
    if args.planner == "spark":
        from expectrail.discovery.planner import spark_planner

        planner = spark_planner()
    budget = {k: v for k, v in (("maxEpisodes", args.max_episodes), ("maxJobWallSeconds", args.max_seconds)) if v}
    doc = discover(args.profile, args.snapshot, args.out, planner=planner, budget=budget,
                   evidence_label=args.label, run_id=args.run_id,
                   probe_ids=args.probes.split(",") if args.probes else None)
    (args.out / "report.md").write_text(report([doc]), encoding="utf-8")
    found = [f for f in doc["findings"] if f["lifecycle"] == "reproduced"]
    print(f"{doc['completion']}: {len(found)} reproduced findings, {len(doc['findings']) - len(found)} other; "
          f"{args.out / 'discovery-run.json'}")
    print(json.dumps({"findings": [[f["snapshot"], f["specId"], f["lifecycle"]] for f in doc["findings"]]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
