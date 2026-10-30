"""The OBAAF audit in CI: the lane inventory must hold, and every finding is reported, not gated.

``obaaf check`` classifies each job into a lane and applies the agent controls only to agent jobs.
It does not recognise our model entry points (``python -m agents.*``), so ``.github/obaaf.yml``
declares them. A declaration is only as good as its upkeep, so this fails CI when:

- a job declared as an agent is not classified as one, or
- a job holds a model key (Muse, SAM, Glimmer, Spark Open) and is neither a declared agent nor a
  known perception-only job (one that only sends frames to SAM or Glimmer and acts on nothing).

Everything else is reporting: the findings, by category and severity, as notices. They are not
suppressed and do not fail the build; gating comes when the agent jobs stop receiving provider
keys (integration spec, Phase C), not by ignoring findings to get a green check.

    obaaf check . --lanes > lanes.txt
    obaaf check . --format json --fail-on never --output obaaf-audit.json
    python3 -m agents.assurance.audit --lanes lanes.txt --report obaaf-audit.json
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

from harness.run import REPO

CONFIG = REPO / ".github" / "obaaf.yml"
WORKFLOWS = REPO / ".github" / "workflows"
# Secrets that reach a hosted model: a job holding one either acts on a model's output (an agent)
# or only sends it frames to look at (perception).
MODEL_KEYS = frozenset({"META_API_KEY", "MODEL_API_KEY", "BASETEN_API_KEY", "FIREWORKS_API_KEY", "GLIMMER_API_KEY"})
# Jobs that only send frames to SAM 3.1 or Muse Glimmer and record what they say. Not agents, but
# they still hold model keys, and those findings are reported.
PERCEPTION = frozenset({
    ".github/workflows/fix-matrix.yml#sam-warm",
    ".github/workflows/glimmer-probe.yml#glimmer",
    ".github/workflows/sam-probe.yml#sam-probe",
    ".github/workflows/sam-probe.yml#sam-video",
    ".github/workflows/sam-probe.yml#sam-verify",
    ".github/workflows/sam-probe.yml#heldout-bench",
})
LANE_LINE = re.compile(r"^(?P<job>\S+#\S+): (?P<lane>[a-z]+) \(")


def declared_agents(config: Path = CONFIG) -> set[str]:
    doc = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    return {job for job, lane in (doc.get("lanes") or {}).items() if lane == "agent"}


def model_jobs(workflows: Path = WORKFLOWS) -> dict[str, set[str]]:
    """{workflow#job: model keys it references}, for every job that references one."""
    out: dict[str, set[str]] = {}
    for path in sorted(workflows.glob("*.y*ml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        rel = path.relative_to(workflows.parent.parent).as_posix()
        for name, job in (doc.get("jobs") or {}).items():
            keys = set(re.findall(r"secrets\.([A-Z0-9_]+)", yaml.safe_dump(job))) & MODEL_KEYS
            if keys:
                out[f"{rel}#{name}"] = keys
    return out


def parse_lanes(text: str) -> dict[str, str]:
    """``obaaf check --lanes`` output as {workflow#job: lane}."""
    return {m["job"]: m["lane"] for m in map(LANE_LINE.match, text.splitlines()) if m}


def inventory_problems(lanes: dict[str, str], declared: set[str], models: dict[str, set[str]]) -> list[str]:
    problems = []
    for job in sorted(declared):
        if job not in lanes:
            problems.append(f"{job} is declared in .github/obaaf.yml but no such job was checked")
        elif lanes[job] != "agent":
            problems.append(f"{job} is declared as an agent but OBAAF classified it {lanes[job]}")
    for job, keys in sorted(models.items()):
        if lanes.get(job) != "agent" and job not in PERCEPTION:
            problems.append(f"{job} holds {', '.join(sorted(keys))} but is neither a declared agent lane nor a "
                            "perception-only job: declare it in .github/obaaf.yml or add it to PERCEPTION, "
                            "after review")
    return problems


def finding_lines(report: dict) -> list[str]:
    """A summary line and one line per rule (GitHub shows ten notices a step, so findings are grouped)."""
    findings = [f for f in report.get("findings") or [] if not f.get("suppressed")]
    counts = Counter((f["category"], f["severity"]) for f in findings)
    summary = "; ".join(f"{cat} {', '.join(f'{counts[(cat, s)]} {s}' for s in ('high', 'medium', 'low'))}"
                        for cat in ("authority", "hygiene"))
    lines = [(f"::notice title=OBAAF audit::{len(findings)} findings, reported, not gated ({summary}); "
              f"{len(report.get('files') or [])} workflow files; {report.get('tool')}")]
    rules: dict[tuple[str, str, str], list[str]] = {}
    for f in findings:
        where = f["job"] or f"{f['path']}:{f.get('line') or 1}"
        rules.setdefault((f["severity"], f["rule"], f["title"]), []).append(where)
    order = {"high": 0, "medium": 1, "low": 2}
    for (severity, rule, title), where in sorted(rules.items(), key=lambda kv: (order.get(kv[0][0], 3), kv[0][1])):
        lines.append(f"::notice title=OBAAF {severity} {rule} x{len(where)}::{title}: {', '.join(where)}")
    for error in report.get("errors") or []:
        lines.append(f"::warning title=OBAAF error::{' '.join(str(error).split())[:300]}")
    return lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--lanes", type=Path, required=True, help="output of obaaf check . --lanes")
    p.add_argument("--report", type=Path, help="output of obaaf check . --format json")
    args = p.parse_args(argv)
    lanes = parse_lanes(args.lanes.read_text(encoding="utf-8"))
    if not lanes:
        print("::error title=OBAAF lanes::no lanes in the obaaf check --lanes output")
        return 1
    problems = inventory_problems(lanes, declared_agents(), model_jobs())
    agents = sorted(job for job, lane in lanes.items() if lane == "agent")
    print(f"::notice title=OBAAF lanes::{len(lanes)} jobs; {len(agents)} agent lanes: "
          + ", ".join(a.split("/")[-1] for a in agents))
    if args.report:
        import json

        for line in finding_lines(json.loads(args.report.read_text(encoding="utf-8"))):
            print(line)
    for problem in problems:
        print(f"::error title=OBAAF lane inventory::{problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
