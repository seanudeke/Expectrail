"""Mutation bench: wrong-fix operators stacked on the correct fix for each public dev case.

For each of the eight development variants, build the exact undo (the good fix), then stack one
operator-only patch (hide, sink, freeze, scale-to-zero, behind-scenery, comment-only). Verify with
public checks only — this job never sets EXPECTRAIL_HELDOUT_DIR and never checks out the private
set. SAM off first; SAM on only for survivors. A mutant that still accepts is a finding, not a
failure: publish it with the catch-spec that would catch it.

    python3 -m agents.mutation_bench --list
    python3 -m agents.mutation_bench --case dev/sinking/v2 --operator hide --out runs/mutation
    python3 -m agents.mutation_bench --summarize runs/mutation
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

from agents.judge_bench import provider, undo_patch
from agents.matrix import EDITABLE, SMOKE_ROUTE, case_spec, dev_variants
from agents.orchestrator import build_repair_request
from agents.verifier import verify
from expectrail.contracts import digest, load
from expectrail.evaluator import EVALUATOR
from harness.run import REPO, apply_patches

FORMAT = "expectrail.mutation-bench/v0"
OPERATORS_DIR = REPO / "agents" / "fixtures" / "operators"
CATCH_DIR = REPO / "agents" / "fixtures" / "catch-specs"
GAME = REPO / "game" / "platformer"
HELDOUT_ENV = "EXPECTRAIL_HELDOUT_DIR"

OPERATORS = ("hide", "sink", "freeze", "scale-to-zero", "behind-scenery", "comment-only")

# Spec that would catch the operator when public checks miss it (finding publish target).
CATCH_SPECS = {
    "hide": REPO / "specs" / "player-always-visible.json",
    "sink": REPO / "specs" / "player-stays-above-ground.json",
    "freeze": CATCH_DIR / "player-motion-required.json",
    "scale-to-zero": REPO / "specs" / "player-always-visible.json",
    "behind-scenery": REPO / "specs" / "player-always-visible.json",
    "comment-only": CATCH_DIR / "comment-only-delta.json",
}
# Freeze is caught by the gameplay check in the verifier suite, not a visual spec file.
CATCH_NOTES = {
    "freeze": "public gameplay check player-motion-on-smoke (SAM off is enough when motion is gone)",
    "comment-only": "proposed process check: candidate must change non-comment tokens",
}


def operator_path(name: str) -> Path:
    path = OPERATORS_DIR / f"{name}.patch"
    if not path.is_file():
        raise SystemExit(f"unknown operator {name!r}: expected {path}")
    return path


def catch_spec_for(operator: str) -> dict:
    path = CATCH_SPECS[operator]
    if path.parent == CATCH_DIR:
        return json.loads(path.read_text(encoding="utf-8"))
    return load(path, "test-spec")


def pairs() -> list[tuple[str, str]]:
    return [(case, op) for case in sorted(dev_variants()) for op in OPERATORS]


def _diff_trees(before: Path, after: Path, rels: list[str]) -> str:
    chunks = []
    for rel in rels:
        a, b = before / rel, after / rel
        if not a.is_file() and not b.is_file():
            continue
        if a.is_file() and b.is_file() and a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8"):
            continue
        r = subprocess.run(["diff", "-u", str(a), str(b)], capture_output=True, text=True)
        fixed = []
        for line in r.stdout.splitlines(True):
            if line.startswith("--- "):
                fixed.append(f"--- a/{rel}\n")
            elif line.startswith("+++ "):
                fixed.append(f"+++ b/{rel}\n")
            else:
                fixed.append(line)
        chunks.append("".join(fixed))
    return "".join(chunks)


def build_candidate(bug: Path, operator: Path, out: Path) -> Path:
    """One candidate: the correct undo of ``bug``, then ``operator``, as a single patch on the bugged tree."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bugged = root / "bugged"
        mutant = root / "mutant"
        shutil.copytree(GAME, bugged, ignore=shutil.ignore_patterns(".godot"))
        shutil.copytree(GAME, mutant, ignore=shutil.ignore_patterns(".godot"))
        apply_patches(bugged, [bug])
        apply_patches(mutant, [bug])
        undo = undo_patch(bug, root / "undo.patch")
        apply_patches(mutant, [undo, operator])
        rels = sorted({line[6:].strip() for patch in (undo, operator)
                       for line in patch.read_text(encoding="utf-8").splitlines()
                       if line.startswith("+++ b/")})
        text = _diff_trees(bugged, mutant, rels)
    out.write_text(text, encoding="utf-8")
    return out


def _public_only() -> None:
    """Refuse to run with the private set mounted: this bench is public checks only."""
    if os.environ.get(HELDOUT_ENV, "").strip():
        raise SystemExit(f"{HELDOUT_ENV} is set; mutation_bench is public checks only — unset it")


def run_case(case: str, operator: str, out: Path) -> dict:
    """Correct fix + operator; SAM off, then SAM on only if it survived. Finding != failure."""
    _public_only()
    if case not in dev_variants():
        raise SystemExit(f"{case}: not a public development variant")
    if operator not in OPERATORS:
        raise SystemExit(f"{operator}: unknown operator (want {', '.join(OPERATORS)})")
    work = out / f"{case.replace('/', '_')}+{operator}"
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    bug = dev_variants()[case]
    row: dict = {
        "format": FORMAT, "case": case, "operator": operator, "bug": case,
        "decisions": {}, "reasons": {}, "finding": False, "caught": None,
    }
    try:
        candidate = build_candidate(bug, operator_path(operator), work / "candidate.patch")
        shutil.copyfile(operator_path(operator), work / "operator.patch")
        verdict = {
            "format": "expectrail.verdict/v0",
            "spec": {"id": case_spec(case)["id"], "sha256": digest(case_spec(case))},
            "observations": {"sha256": "0" * 64}, "result": "fail", "reason": "seeded bug",
            "firstFrame": None, "evidence": [], "framesJudged": 0, "evaluator": dict(EVALUATOR),
        }
        request = build_repair_request(
            request_id=f"rr-mutation-{case.replace('/', '-')}-{operator}",
            spec=case_spec(case), verdict=verdict, route=load(SMOKE_ROUTE, "route"),
            base_patch=str(bug.relative_to(REPO)), editable=EDITABLE, attempts=1,
        )
        # SAM off first.
        with provider("trace"):
            off = verify(request, candidate, work / "sam-off")
        row["decisions"]["expectrailNoSam"] = off["decision"]
        row["reasons"]["expectrailNoSam"] = list(dict.fromkeys(
            r.split(" on ")[0] for r in (off.get("reasons") or [])))[:6]
        if off["decision"] != "accept":
            row["caught"] = "sam-off"
        else:
            with provider("sam"):
                on = verify(request, candidate, work / "sam-on")
            row["decisions"]["expectrailSam"] = on["decision"]
            row["reasons"]["expectrailSam"] = list(dict.fromkeys(
                r.split(" on ")[0] for r in (on.get("reasons") or [])))[:6]
            if on["decision"] != "accept":
                row["caught"] = "sam-on"
            else:
                row["caught"] = None
                row["finding"] = True
                catch = catch_spec_for(operator)
                finding = {
                    "format": FORMAT + "-finding",
                    "case": case,
                    "operator": operator,
                    "decisions": row["decisions"],
                    "reasons": row["reasons"],
                    "catchSpec": {"id": catch.get("id"), "path": str(CATCH_SPECS[operator].relative_to(REPO)),
                                  "notes": CATCH_NOTES.get(operator)},
                    "catchSpecDoc": catch,
                }
                (work / "finding.json").write_text(json.dumps(finding, indent=2) + "\n", encoding="utf-8")
                (work / "catch-spec.json").write_text(json.dumps(catch, indent=2) + "\n", encoding="utf-8")
                print(f"::notice title=Mutation finding {case} {operator}::"
                      f"survived SAM off and SAM on; catch-spec {catch.get('id')}")
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        (work / "mutation-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        row["error"] = f"{type(exc).__name__}: {exc}"[:300]
    row["wallClockSeconds"] = round(time.perf_counter() - t0, 1)
    (work / "result.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    if row.get("caught"):
        print(f"::notice title=Mutation caught {case} {operator}::caught with {row['caught']}")
    return row


def summarize(out: Path) -> dict:
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.rglob("result.json"))]
    rows = [r for r in rows if r.get("format") == FORMAT]
    findings = [r for r in rows if r.get("finding")]
    doc = {
        "format": FORMAT + "-summary",
        "cases": len(rows),
        "findings": len(findings),
        "caughtSamOff": sum(r.get("caught") == "sam-off" for r in rows),
        "caughtSamOn": sum(r.get("caught") == "sam-on" for r in rows),
        "errors": sum(1 for r in rows if r.get("error")),
        "rows": rows,
        "findingCases": [{"case": r["case"], "operator": r["operator"]} for r in findings],
    }
    (out / "mutation-summary.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def markdown(doc: dict) -> str:
    lines = ["# Mutation bench", "",
             "Wrong-fix operators on the correct fix for each public development case. "
             "Public checks only. A survivor is a finding, not a CI failure.", "",
             (f"Findings: **{doc['findings']}** of {doc['cases']}. "
              f"Caught with SAM off: {doc['caughtSamOff']}; with SAM on: {doc['caughtSamOn']}; "
              f"errors: {doc['errors']}."), "",
             "| Case | Operator | Caught | Finding |",
             "| --- | --- | --- | --- |"]
    for r in doc["rows"]:
        lines.append(f"| {r['case']} | {r['operator']} | {r.get('caught') or '—'} | "
                     f"{'yes' if r.get('finding') else 'no'} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    from agents.keys import load_dotenv
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--case", help="dev/<family>/vN")
    g.add_argument("--summarize", type=Path)
    p.add_argument("--operator", choices=OPERATORS, help="with --case")
    p.add_argument("--out", type=Path, default=REPO / "runs" / "mutation")
    args = p.parse_args(argv)
    if args.list:
        print(json.dumps([{"case": c, "operator": o} for c, o in pairs()]))
        return 0
    if args.summarize:
        doc = summarize(args.summarize)
        print(markdown(doc))
        return 0
    if not args.operator:
        p.error("--case needs --operator")
    row = run_case(args.case, args.operator, args.out)
    print(json.dumps({k: row.get(k) for k in ("case", "operator", "caught", "finding", "decisions",
                                               "error", "wallClockSeconds")}))
    # Findings and catches are success; only tooling errors fail the job.
    return 1 if row.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
