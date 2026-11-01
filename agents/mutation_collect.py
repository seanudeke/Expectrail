"""Record a Mutation bench run in bench/mutation/ from the run's own artifacts, and plan the SAM phase.

Every number in bench/ comes from a CI run's output. A bench run leaves one artifact per case, and
Part 2 spans two runs, so this does the join by hand no one should: it downloads each run into its own
folder, so a mutant judged in both phases counts once, and summarizes them together. It refuses a
rehearsal, results from another registration, and a run that is not the one the part asks for. Cases
that are missing are reported, and never filled in or dropped.

    python3 -m agents.mutation_collect --part wrong-fix --run <id>                  # #154
    python3 -m agents.mutation_collect --part generated --run <cheap id>            # #155, the cheap tier
    python3 -m agents.mutation_collect --part generated --run <cheap> --run <sam>   # #155, both phases
    python3 -m agents.mutation_collect --plan-sam --run <cheap id>                  # what the SAM phase needs

Needs gh, signed in. Reads artifacts; it spends nothing and dispatches nothing.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

from agents import mutate_game as mg
from agents import mutation_bench as mb
from agents.bench_collect import REPO_SLUG, SAM_USD_PER_IMAGE
from agents.export_scan import main as export_scan

PARTS = {"wrong-fix": "wrong-fix", "generated": "mutant"}  # the part -> the rows it records
# A case the SAM phase looks at sends at most two prompts over 120 frames on each of its two replays.
MAX_IMAGES_PER_CASE = 480


def download(run_id: int, dest: Path) -> None:
    subprocess.run(["gh", "run", "download", str(run_id), "--repo", REPO_SLUG, "--dir", str(dest),
                    "--pattern", "mutation-*"], check=True, capture_output=True, text=True)


def gather(runs: list[int], root: Path, fetch: Callable[[int, Path], None] = download) -> None:
    """Each run in its own folder: result.json files of two phases share a path inside a run."""
    if len(set(runs)) != len(runs):
        raise SystemExit("a run was named twice")
    for run in runs:
        fetch(run, root / str(run))


def check_rows(rows: list[dict], part: str, prereg: dict) -> None:
    if not rows:
        raise SystemExit("these runs have no results")
    if any(r.get("rehearsal") for r in rows):
        raise SystemExit("these runs hold a rehearsal, which is never recorded as a result")
    foreign = sum(r.get("preregistrationSha256") != prereg["sha256"] for r in rows)
    if foreign:
        raise SystemExit(f"{foreign} results are not from this registration")
    kinds = {r.get("kind") for r in rows}
    if kinds != {PARTS[part]}:
        raise SystemExit(f"--part {part} records {PARTS[part]} rows, and these are {sorted(map(str, kinds))}")


def expected(part: str, prereg: dict) -> set[str]:
    """The cases this part must hold, by the name its rows carry."""
    if part == "wrong-fix":
        return {f"{case} {op}" for case, op in mb.study_pairs(prereg)}
    return {m["id"] for m in mg.load_manifest(prereg, mb.MANIFEST)["mutants"]}


def spend(doc: dict) -> dict:
    images = doc["samImages"]["spent"] + doc["samImages"]["warm"]
    return {"samImages": images, "samUsd": round(images * SAM_USD_PER_IMAGE, 2)}


def record(runs: list[int], part: str, out: Path, *, prereg: dict | None = None,
           fetch: Callable[[int, Path], None] = download) -> dict:
    """Write ``out``/README.md, summary.json and findings/ from the runs' artifacts."""
    prereg = prereg or mg.load_preregistration()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        gather(runs, root, fetch)
        rows = mb._rows(root)
        check_rows(rows, part, prereg)
        doc = mb.summarize(root)
        names = {mb._name(r) for r in rows}
        doc["runs"] = runs
        doc["spend"] = spend(doc)
        doc["missingCases"] = sorted(expected(part, prereg) - names)
        doc["unexpectedCases"] = sorted(names - expected(part, prereg))
        out.mkdir(parents=True, exist_ok=True)
        head = [f"Recorded from run{'s' if len(runs) > 1 else ''} {', '.join(str(r) for r in runs)} by "
                f"`python3 -m agents.mutation_collect`. Actual SAM spend: {doc['spend']['samImages']:,} images, "
                f"${doc['spend']['samUsd']:.2f} at list price.", ""]
        if doc["missingCases"] or doc["unexpectedCases"]:
            head += [f"**Not complete: {len(doc['missingCases'])} cases missing, {len(doc['unexpectedCases'])} unexpected.** "
                     "They are listed in summary.json.", ""]
        (out / "README.md").write_text("\n".join(head) + "\n" + mb.markdown(doc), encoding="utf-8")
        (out / "summary.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        for name in ("finding.json", "catch-spec.json"):
            for path in root.rglob(name):
                dest = out / "findings" / path.parent.name / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, dest)
    if export_scan([str(out)]) != 0:
        raise SystemExit(f"the export scan refused {out}: do not commit it")
    return doc


def plan(cheap_run: int, *, prereg: dict | None = None, fetch: Callable[[int, Path], None] = download) -> dict:
    """What the SAM phase must judge, from the cheap phase's artifacts, and what it could cost."""
    prereg = prereg or mg.load_preregistration()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        gather([cheap_run], root, fetch)
        rows = mb._rows(root)
        check_rows(rows, "generated", prereg)
        chosen = mb.plan_sam(root, prereg)
    cases = len(chosen["survivors"]) + len(chosen["agreement"])
    return {**chosen, "maxImages": cases * MAX_IMAGES_PER_CASE,
            "maxUsd": round(cases * MAX_IMAGES_PER_CASE * SAM_USD_PER_IMAGE, 2)}


def dispatch_lines(chosen: dict) -> list[str]:
    """The two dispatches: SAM on what the cheap tier passed, and forced SAM on the agreement sample."""
    lines = []
    for ids, force in ((chosen["survivors"], "off"), (chosen["agreement"], "on")):
        if ids:
            lines.append(f"gh workflow run mutation-bench.yml --repo {REPO_SLUG} --ref main -f mode=generated-sam "
                         f"-f force_sam={force} -f mutants='{','.join(ids)}'")
    return lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run", type=int, action="append", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--part", choices=sorted(PARTS))
    g.add_argument("--plan-sam", action="store_true")
    p.add_argument("--out", type=Path, help="default: bench/mutation/<part>")
    args = p.parse_args(argv)
    try:
        if args.plan_sam:
            if len(args.run) != 1:
                p.error("--plan-sam takes the cheap phase's one run")
            chosen = plan(args.run[0])
            print(f"{len(chosen['survivors'])} the cheap tier passed; {len(chosen['agreement'])} for the agreement "
                  f"table; at most {chosen['maxImages']:,} images, ${chosen['maxUsd']:.2f}. Post that in #127 first.")
            print("\n".join(dispatch_lines(chosen)))
            return 0
        out = args.out or mg.PREREGISTRATION.parent / args.part
        doc = record(args.run, args.part, out)
    except mg.PreregistrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{out}: {doc['cases']} cases, {len(doc['missingCases'])} missing; ${doc['spend']['samUsd']:.2f}")
    return 1 if doc["missingCases"] else 0


if __name__ == "__main__":
    sys.exit(main())
