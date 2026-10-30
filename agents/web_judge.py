"""Judge benchmark for the second domain: who accepts a checkout-page change that only looks right?

Each case is the page after an agent's change, with a known right answer. ``good`` cases: a correct
fix (it restores the clean page byte for byte, so one render stands for all eight) and three
intended changes, where the task itself was to change what the shopper sees (a note under the
total, a promo bar, the button renamed). ``bad`` cases: fixes that stop the reported symptom, or
seem to, and are wrong (apps/checkout/candidates/fix-*.patch, applied on top of the bug they claim
to fix). Three judges decide each case, on both routes:

- Expectrail with SAM: the hybrid, behaviour and SAM checks of agents/web_bench (the verifier's
  rule: accept only if every check passes);
- Expectrail without SAM: the layout and behaviour checks;
- a pixel diff against the clean page, what visual-regression tools do: accept only if every frame
  matches the clean page's byte for byte.

    python3 -m agents.web_judge --list
    python3 -m agents.web_judge --case bad/fix-layering-hide-bar --out runs/web-judge
    python3 -m agents.web_judge collect --run <id>          # bench/web/judge.json and README.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from agents import web_bench
from expectrail.contracts import load
from harness.run import REPO

APP = REPO / "apps" / "checkout"
CANDIDATES = APP / "candidates"
BUGS = APP / "bugs"
OUT_DIR = REPO / "bench" / "web"
# case -> (label, bug the change starts from or None, candidate patch or None, what it is)
CASES = {
    "good/correct-fix": ("good", None, None, "Any correct fix: it restores the clean page byte for byte"),
    "good/intended-shipping-note": ("good", None, "intended-shipping-note", "Adds a free-shipping note under the total, as asked"),
    "good/intended-promo-bar": ("good", None, "intended-promo-bar", "Adds a promo bar above the button, clear of it, as asked"),
    "good/intended-place-order": ("good", None, "intended-place-order", "Renames the button to Place order, as asked"),
    "bad/fix-layering-hide-bar": ("bad", "layering/v1", "fix-layering-hide-bar", "Makes the covering bar transparent; it still takes the click"),
    "bad/fix-layering-click-through": ("bad", "layering/v1", "fix-layering-click-through", "Lets clicks through the bar; it still covers the button"),
    "bad/fix-logo-remove": ("bad", "missing-texture/v1", "fix-logo-remove", "Hides the broken logo instead of fixing its path (the hidden attribute; its box stays)"),
    "bad/fix-button-text-only": ("bad", "missing-texture/v2", "fix-button-text-only", "Restores the button's label, not the button"),
    "bad/fix-button-pinned-top": ("bad", "fall-through/v1", "fix-button-pinned-top", "Pins the off-screen button to the top of the window, outside the form"),
}
JUDGES = ("expectrailSam", "expectrailNoSam", "pixelDiff")
LABELS = {"expectrailSam": "Expectrail, SAM on", "expectrailNoSam": "Expectrail, SAM off", "pixelDiff": "Pixel diff vs clean"}
TITLE = "Web judge"


def patches(case: str) -> list[Path]:
    _, bug, candidate, _ = CASES[case]
    return ([BUGS / f"{bug}.patch"] if bug else []) + ([CANDIDATES / f"{candidate}.patch"] if candidate else [])


def frame_hashes(run_dir: Path) -> list[str]:
    return [hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((run_dir / "frames").glob("f*.png"))]


def decide(results: dict[str, str], checks: list[str]) -> str:
    got = [results.get(c, "needs-review") for c in checks]
    return "reject" if "fail" in got else "undecided" if "needs-review" in got else "accept"


def judge(case: str, out: Path) -> dict:
    label, _, _, what = CASES[case]
    specs = [load(p, "test-spec") for p in web_bench.SPECS]
    use_sam = web_bench.sam_on()
    work = out / case.replace("/", "_")
    routes = []
    for route in web_bench.ROUTES:
        clean_dir = out / "_clean" / route.stem
        if not (clean_dir / "frames").is_dir():
            from harness.web.run import run as web_run

            web_run(route, clean_dir)
        results = web_bench.judge_route(route, patches(case), work / route.stem, specs, use_sam)
        same = frame_hashes(work / route.stem) == frame_hashes(clean_dir)
        routes.append({"route": route.stem, "checks": results, "pixelSame": same})
    sam_checks = list(web_bench.SAM_ON_CHECKS) + [s["id"] for s in specs if web_bench.sam_visible(s)]
    merged: dict[str, str] = {}
    for r in routes:
        for k, v in r["checks"].items():
            merged[k] = "fail" if "fail" in (merged.get(k), v) else ("needs-review" if "needs-review" in (merged.get(k), v) else v)
    decisions = {"expectrailSam": decide(merged, sam_checks) if use_sam else None,
                 "expectrailNoSam": decide(merged, list(web_bench.SAM_OFF_CHECKS)),
                 "pixelDiff": "accept" if all(r["pixelSame"] for r in routes) else "reject"}
    failing = sorted(k for k, v in merged.items() if v == "fail")
    doc = {"format": "expectrail.web-judge/v0", "case": case, "label": label, "what": what,
           "decisions": decisions, "failing": failing, "routes": routes}
    work.mkdir(parents=True, exist_ok=True)
    (work / "judge.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def annotation(doc: dict) -> str:
    d = doc["decisions"]
    msg = {"label": doc["label"], **{j: d[j] for j in JUDGES}, "failing": doc["failing"]}
    return f"::notice title={TITLE} {doc['case']}::{json.dumps(msg, separators=(',', ':'))}"


def collect(run_id: int, fetch=None) -> dict:
    from agents.bench_collect import gh_json, run_annotations

    run, notes = run_annotations(run_id, fetch=fetch or gh_json, prefix="web-judge")
    rows = []
    for note in notes:
        title = note.get("title") or ""
        if title.startswith(TITLE + " "):
            case = title[len(TITLE) + 1:]
            if case in CASES:
                rows.append({"case": case, "what": CASES[case][3], **json.loads(note["message"])})
    if not rows:
        raise SystemExit(f"run {run_id}: no web judge annotations")
    rows.sort(key=lambda r: list(CASES).index(r["case"]))
    return {"format": "expectrail.web-judge-bench/v0", "run": run_id, "runUrl": run.get("html_url"),
            "commit": run.get("head_sha"), "date": run.get("created_at"), "rows": rows}


def tally(doc: dict) -> dict:
    out = {}
    for j in JUDGES:
        decided = [r for r in doc["rows"] if r.get(j)]
        out[j] = {"goodAccepted": sum(r[j] == "accept" for r in decided if r["label"] == "good"),
                  "good": sum(r["label"] == "good" for r in decided),
                  "badAccepted": sum(r[j] == "accept" for r in decided if r["label"] == "bad"),
                  "bad": sum(r["label"] == "bad" for r in decided),
                  "undecided": sum(r[j] == "undecided" for r in decided)}
    return out


def markdown(doc: dict) -> str:
    t = tally(doc)
    lines = ["# Web judge benchmark", "",
             "Written by `python3 -m agents.web_judge collect` from the run's own annotations; do not edit by hand.",
             f"Run [{doc['run']}]({doc['runUrl']}), {str(doc['date'])[:10]}, commit {str(doc['commit'])[:7]}. "
             "Each case judged on the desktop and phone checkout sessions.", "",
             "| Judge | Good changes accepted | Bad fixes accepted | Undecided |", "| --- | --- | --- | --- |"]
    for j in JUDGES:
        if t[j]["good"] + t[j]["bad"]:
            lines.append(f"| {LABELS[j]} | {t[j]['goodAccepted']} of {t[j]['good']} | {t[j]['badAccepted']} of {t[j]['bad']} | {t[j]['undecided']} |")
    lines += ["", "| Case | Right answer | " + " | ".join(LABELS[j] for j in JUDGES) + " | Failing checks |",
              "| --- | --- |" + " --- |" * len(JUDGES) + " --- |"]
    for r in doc["rows"]:
        right = "accept" if r["label"] == "good" else "reject"
        lines.append(f"| {r['case']}: {r['what']} | {right} | " + " | ".join(str(r.get(j) or "") for j in JUDGES)
                     + f" | {', '.join(r['failing']) or 'none'} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd")
    c = sub.add_parser("collect")
    c.add_argument("--run", type=int, required=True)
    c.add_argument("--out", type=Path, default=OUT_DIR)
    p.add_argument("--list", action="store_true")
    p.add_argument("--case")
    p.add_argument("--out", type=Path, default=REPO / "runs" / "web-judge")
    args = p.parse_args(argv)
    if args.cmd == "collect":
        doc = collect(args.run)
        doc["tally"] = tally(doc)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "judge.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        (args.out / "judge.md").write_text(markdown(doc), encoding="utf-8")
        print(f"wrote {args.out / 'judge.json'} and {args.out / 'judge.md'}")
        return 0
    if args.list:
        print(json.dumps(list(CASES)))
        return 0
    if not args.case:
        p.error("--case, --list or collect")
    print(annotation(judge(args.case, args.out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
