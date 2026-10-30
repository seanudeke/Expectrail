"""Per-case spend for the fix-matrix and judge benchmarks: SAM, Muse gateway, Glimmer, minutes.

The benches already write ``samImages`` and ``wallClockSeconds`` into ``result.json``. Muse gateway
request counts live in ``sandbox.json`` / ``judge.json`` (``agents.gateway.evidence``). Glimmer
calls are tallied by ``agents.glimmer_usage`` when that wrap is installed before the case runs.

    python3 -m agents.case_spend --install-glimmer
    python3 -m agents.case_spend --case-dir runs/matrix/dev_sinking_v2/expectrail --glimmer-before 0
    python3 -m agents.case_spend --tree runs/matrix --bench fix --out bench/fix-matrix
    python3 -m agents.case_spend --tree runs/judge --bench judge --out bench/judge

Never invents a number: a missing field stays null and the markdown says "not counted".
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agents.gateway import evidence
from agents.glimmer_usage import glimmer_calls_since, install as install_glimmer
from agents import glimmer_usage as gu
from harness.run import REPO

FORMAT = "expectrail.case-spend/v0"
MATRIX_DIR = REPO / "bench" / "fix-matrix"
JUDGE_DIR = REPO / "bench" / "judge"
SAM_USD_PER_IMAGE = 2.50 / 1000


def _money(images: int | None, usd: float | None) -> str:
    if images is None:
        return "not counted"
    return f"{images:,} (${(usd if usd is not None else images * SAM_USD_PER_IMAGE):.2f})"


def _has_gateway_docs(case_dir: Path) -> bool:
    return any(p.name in ("sandbox.json", "judge.json") for p in Path(case_dir).rglob("*.json"))


def enrich(case_dir: Path, *, glimmer_before: dict[str, int] | None = None) -> dict:
    """Read ``result.json`` under ``case_dir``, add Muse/Glimmer/minutes, write ``spend.json``."""
    case_dir = Path(case_dir)
    result_path = case_dir / "result.json"
    if not result_path.is_file():
        raise SystemExit(f"{case_dir}: no result.json")
    row = json.loads(result_path.read_text(encoding="utf-8"))
    seconds = row.get("wallClockSeconds")
    sam = row.get("samImages")
    muse = evidence(case_dir)
    if _has_gateway_docs(case_dir) or muse["museRuns"]:
        muse_requests: int | None = muse["requests"]
        muse_runs: int | None = muse["museRuns"]
    else:
        muse_requests = None
        muse_runs = None

    if glimmer_before is not None:
        glimmer: int | None = glimmer_calls_since(glimmer_before)
    elif gu._installed:  # noqa: SLF001 — wrap on means we measured this process
        glimmer = gu.glimmer_usage()["calls"]
    else:
        glimmer = row["glimmerCalls"] if "glimmerCalls" in row else None

    spend = {
        "format": FORMAT,
        "case": row.get("case"),
        "condition": row.get("condition"),
        "label": row.get("label"),
        "samImages": sam if isinstance(sam, int) else None,
        "samUsd": round(sam * SAM_USD_PER_IMAGE, 2) if isinstance(sam, int) else None,
        "museRequests": muse_requests,
        "museRuns": muse_runs,
        "glimmerCalls": glimmer,
        "wallClockSeconds": seconds,
        "jobMinutes": round(float(seconds) / 60, 2) if isinstance(seconds, (int, float)) else None,
    }
    (case_dir / "spend.json").write_text(json.dumps(spend, indent=2) + "\n", encoding="utf-8")
    return spend


def notice(spend: dict) -> str:
    """One GitHub Actions notice line for a case's spend."""
    who = spend.get("case") or "?"
    if spend.get("condition"):
        who = f"{who} {spend['condition']}"
    sam = _money(spend.get("samImages"), spend.get("samUsd"))
    muse = "not counted" if spend.get("museRequests") is None else str(spend["museRequests"])
    glimmer = "not counted" if spend.get("glimmerCalls") is None else str(spend["glimmerCalls"])
    minutes = "not counted" if spend.get("jobMinutes") is None else f"{spend['jobMinutes']:.1f}"
    return (f"::notice title=Case spend {who}::SAM images {sam}; Muse requests {muse}; "
            f"Glimmer calls {glimmer}; {minutes} job minutes")


def collect_tree(root: Path) -> list[dict]:
    """Every ``spend.json`` under ``root``, or enrich each ``result.json`` that lacks one."""
    root = Path(root)
    rows = []
    for result in sorted(root.rglob("result.json")):
        case_dir = result.parent
        spend_path = case_dir / "spend.json"
        if spend_path.is_file():
            rows.append(json.loads(spend_path.read_text(encoding="utf-8")))
        else:
            rows.append(enrich(case_dir))
    return rows


def _sum_or_none(rows: list[dict], key: str):
    if not rows:
        return 0 if key != "samImages" else None
    if any(r.get(key) is None for r in rows):
        return None
    return sum(r[key] for r in rows)


def aggregate(rows: list[dict]) -> dict:
    """Run-level totals. Any null among rows makes that total null (never estimate)."""
    images = _sum_or_none(rows, "samImages")
    minutes = _sum_or_none(rows, "jobMinutes")
    return {
        "format": FORMAT + "-summary",
        "cases": len(rows),
        "samImages": images,
        "samUsd": round(images * SAM_USD_PER_IMAGE, 2) if images is not None else None,
        "museRequests": _sum_or_none(rows, "museRequests"),
        "glimmerCalls": _sum_or_none(rows, "glimmerCalls"),
        "jobMinutes": round(minutes, 1) if minutes is not None else None,
        "rows": rows,
    }


def markdown(doc: dict, *, bench: str) -> str:
    """Spend table for ``bench/fix-matrix`` or ``bench/judge`` (additive section)."""
    title = "Fix matrix" if bench == "fix" else "Judge benchmark"
    lines = [f"# {title} — per-case spend", "",
             "Written by `python3 -m agents.case_spend` from each case's `spend.json`; do not edit by hand.",
             "SAM images, Muse gateway requests, Glimmer calls, and job minutes. Missing counts say "
             "\"not counted\"; nothing is estimated.", ""]
    s = doc
    muse_t = "not counted" if s.get("museRequests") is None else s["museRequests"]
    glimmer_t = "not counted" if s.get("glimmerCalls") is None else s["glimmerCalls"]
    minutes_t = "not counted" if s.get("jobMinutes") is None else f"{s['jobMinutes']:.0f}"
    lines += [
        (f"Totals: SAM images {_money(s.get('samImages'), s.get('samUsd'))}; "
         f"Muse requests {muse_t}; Glimmer calls {glimmer_t}; {minutes_t} job minutes."),
        "",
        "| Case | Condition / label | SAM images | Muse requests | Glimmer calls | Job minutes |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in doc.get("rows") or []:
        key = r.get("condition") or r.get("label") or ""
        sam = "not counted" if r.get("samImages") is None else f"{r['samImages']:,}"
        muse = "not counted" if r.get("museRequests") is None else str(r["museRequests"])
        glimmer = "not counted" if r.get("glimmerCalls") is None else str(r["glimmerCalls"])
        minutes = "not counted" if r.get("jobMinutes") is None else f"{r['jobMinutes']:.1f}"
        lines.append(f"| {r.get('case')} | {key} | {sam} | {muse} | {glimmer} | {minutes} |")
    return "\n".join(lines) + "\n"


def write_bench(doc: dict, out_dir: Path, *, bench: str) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "spend.json"
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    (out_dir / "spend.md").write_text(markdown(doc, bench=bench), encoding="utf-8")
    return path


def run_fix_case(case: str, condition: str, out: Path, *, live: bool,
                  fixture: Path | None = None) -> tuple[dict, dict]:
    """Install the Glimmer wrap, run one fix-matrix case in-process, enrich spend."""
    from agents.matrix import run_case

    install_glimmer()
    before = gu.glimmer_usage()
    row = run_case(case, condition, out, live=live, fixture=fixture,
                   require_sandbox=live)
    case_dir = out / case.replace("/", "_") / condition
    spend = enrich(case_dir, glimmer_before=before)
    return row, spend


def run_judge_case(case: str, out: Path, *, live: bool, sam: bool = True) -> tuple[dict, dict]:
    """Install the Glimmer wrap, run one judge case in-process, enrich spend."""
    from agents.judge_bench import run_case

    install_glimmer()
    before = gu.glimmer_usage()
    row = run_case(case, out, live=live, sam=sam)
    case_dir = out / case.replace("/", "_")
    spend = enrich(case_dir, glimmer_before=before)
    return row, spend


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--install-glimmer", action="store_true",
                   help="wrap GlimmerClient._call for this process, then exit 0")
    p.add_argument("--case-dir", type=Path, help="enrich one case directory (writes spend.json)")
    p.add_argument("--glimmer-before", type=int,
                   help="glimmer_usage calls at case start (with --case-dir)")
    p.add_argument("--run-fix", metavar="CASE",
                   help="run one fix-matrix case in-process and write spend.json")
    p.add_argument("--condition", choices=("screenshots", "expectrail"),
                   help="with --run-fix")
    p.add_argument("--run-judge", metavar="CASE",
                   help="run one judge case in-process and write spend.json")
    p.add_argument("--live", action="store_true", help="with --run-fix / --run-judge")
    p.add_argument("--fixture-candidate", type=Path, help="offline fix-matrix candidate")
    p.add_argument("--no-sam", action="store_true", help="judge: skip SAM-on verifier")
    p.add_argument("--tree", type=Path, help="enrich/collect every result.json under this tree")
    p.add_argument("--bench", choices=("fix", "judge"), help="with --tree: which bench to write")
    p.add_argument("--out", type=Path, help="run output dir, or with --tree the spend write dir")
    args = p.parse_args(argv)
    if args.install_glimmer:
        install_glimmer()
        print("glimmer usage counter installed")
        return 0
    if args.run_fix:
        if not args.condition:
            p.error("--run-fix needs --condition")
        out = args.out or (REPO / "runs" / "matrix")
        from agents.keys import load_dotenv
        load_dotenv()
        row, spend = run_fix_case(args.run_fix, args.condition, out, live=args.live,
                                   fixture=args.fixture_candidate)
        print(notice(spend))
        print(json.dumps({k: row.get(k) for k in ("case", "condition", "outcome", "attemptsUsed",
                                                   "wallClockSeconds", "detail")}))
        return 1 if row.get("outcome") == "error" else 0
    if args.run_judge:
        out = args.out or (REPO / "runs" / "judge")
        from agents.keys import load_dotenv
        load_dotenv()
        row, spend = run_judge_case(args.run_judge, out, live=args.live, sam=not args.no_sam)
        print(notice(spend))
        print(json.dumps({k: row.get(k) for k in ("case", "label", "decisions", "error",
                                                   "wallClockSeconds")}))
        return 1 if row.get("error") else 0
    if args.case_dir:
        before = {"calls": args.glimmer_before} if args.glimmer_before is not None else None
        spend = enrich(args.case_dir, glimmer_before=before)
        print(notice(spend))
        print(json.dumps({k: spend.get(k) for k in ("case", "condition", "samImages", "museRequests",
                                                     "glimmerCalls", "jobMinutes")}))
        return 0
    if args.tree:
        if not args.bench:
            p.error("--tree needs --bench fix|judge")
        out = args.out or (MATRIX_DIR if args.bench == "fix" else JUDGE_DIR)
        doc = aggregate(collect_tree(args.tree))
        path = write_bench(doc, out, bench=args.bench)
        print(f"wrote {path} and {out / 'spend.md'}")
        return 0
    p.error("pass --install-glimmer, --run-fix, --run-judge, --case-dir, or --tree")
    return 2


if __name__ == "__main__":
    sys.exit(main())
