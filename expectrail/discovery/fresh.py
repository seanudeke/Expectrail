"""The fresh defect sets for the blind discovery runs: their digests, checks, and counts-only notices.

Each set lives only in the private held-out repository, in its own directory: set 1 under
``fresh/`` (written against freeze 1, ids f01 to f10, retired after blind runs 1 and 2), set 2 under
``fresh-2/`` (written against freeze 2, ids g01 to g10). A set is written by someone who has not
tuned the discoverer to it, after discovery was frozen (expectrail/discovery/freeze.py), and its
digest is committed here (``bugs/fresh/fresh.sha256`` for set 1, ``bugs/fresh/fresh-2.sha256`` for
set 2) before its blind run. The run publishes
counts only: per opaque id, whether it was a defect or an intentional change, and whether discovery
reported a reproduced finding. Which contracts fired would hint at the mechanism, so it stays out of
the public logs until the event is over.

    python -m expectrail.discovery.fresh digest ../Nightshift-heldout/fresh-2
    python -m expectrail.discovery.fresh check ../Nightshift-heldout --dir fresh-2   # manifest, patches, routes
    python -m expectrail.discovery.fresh list ../Nightshift-heldout --dir fresh-2    # ids, for the CI matrix
    python -m expectrail.discovery.fresh notice RUN.json --id g03 --set ../Nightshift-heldout --dir fresh-2
    python -m expectrail.discovery.fresh collect --run <workflow run id>

``--dir`` defaults to ``fresh`` (set 1). Manifest (``<dir>/manifest.json``; paths start with ``<dir>/``)::

    {"format": "expectrail.fresh-set/v1",
     "frozenDiscovery": {"commit": "<the freeze commit>", "sha256": "<discovery/freeze.json sha256>"},
     "createdAt": "2026-11-01T...Z",
     "entries": [{"id": "f01", "kind": "defect" | "intentional", "patch": "fresh/f01.patch",
                  "area": "...", "description": "...", "howItShows": "...", "route": "fresh/routes/f01.json",
                  "traceVisible": "yes" | "no" | "unsure", "timing": "immediate" | "delayed" | "conditional"}]}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FORMAT = "expectrail.fresh-set/v1"
COMMITMENT = REPO / "bugs" / "fresh" / "fresh.sha256"
SETS = {"fresh": ("f", COMMITMENT), "fresh-2": ("g", REPO / "bugs" / "fresh" / "fresh-2.sha256")}
FIELDS = {"id", "kind", "patch", "area", "description", "howItShows", "route", "traceVisible", "timing"}


def digest(fresh_dir: Path) -> str:
    """sha256 over every file under fresh/: its path relative to fresh/, a NUL, its sha256, a newline."""
    h = hashlib.sha256()
    files = sorted(p for p in Path(fresh_dir).rglob("*") if p.is_file())
    if not files:
        raise SystemExit(f"{fresh_dir}: no files")
    for p in files:
        h.update(p.relative_to(fresh_dir).as_posix().encode() + b"\0" + hashlib.sha256(p.read_bytes()).hexdigest().encode()
                 + b"\n")
    return h.hexdigest()


def committed(path: Path = COMMITMENT) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            return line.split()[0]
    return None


def manifest(set_root: Path, set_dir: str = "fresh") -> dict:
    return json.loads((Path(set_root) / set_dir / "manifest.json").read_text(encoding="utf-8"))


def check(set_root: Path, *, freeze_sha: str | None = None, require_commitment: bool = False,
          game: Path | None = None, set_dir: str = "fresh") -> list[str]:
    """Every problem with the set: format, ids, kinds, patches that do not apply, routes that do not
    validate, a frozen digest that is not the freeze's, a digest that is not the committed one."""
    from expectrail.contracts import validate

    set_root = Path(set_root)
    problems: list[str] = []
    try:
        doc = manifest(set_root, set_dir)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{set_dir}/manifest.json: {exc}"]
    if set_dir not in SETS:
        return [f"unknown set {set_dir!r} (known: {', '.join(SETS)})"]
    prefix, commitment = SETS[set_dir]
    id_re = re.compile(rf"^{prefix}\d{{2}}$")
    if doc.get("format") != FORMAT:
        problems.append(f"format is not {FORMAT}")
    if freeze_sha is None:
        freeze_file = REPO / "discovery" / "freeze.json"
        freeze_sha = json.loads(freeze_file.read_text())["sha256"] if freeze_file.is_file() else None
    if (doc.get("frozenDiscovery") or {}).get("sha256") != freeze_sha:
        problems.append("frozenDiscovery.sha256 is not the freeze's digest (discovery/freeze.json)")
    entries = doc.get("entries") or []
    ids = [e.get("id") for e in entries]
    if len(set(ids)) != len(ids) or not all(isinstance(i, str) and id_re.match(i) for i in ids):
        problems.append(f"ids must be unique and look like {prefix}01")
    kinds = [e.get("kind") for e in entries]
    if kinds.count("defect") < 6 or kinds.count("intentional") < 1 or set(kinds) - {"defect", "intentional"}:
        problems.append("needs at least 6 defects and 1 intentional change, and no other kind")
    game = game or REPO / "game" / "platformer"
    for e in entries:
        where = e.get("id", "?")
        if set(e) != FIELDS:
            problems.append(f"{where}: fields must be exactly {sorted(FIELDS)}")
            continue
        for key in ("patch", "route"):
            if not str(e[key]).startswith(f"{set_dir}/") or ".." in str(e[key]) or not (set_root / e[key]).is_file():
                problems.append(f"{where}: {key} {e[key]!r} is not a file under {set_dir}/")
        if e["traceVisible"] not in ("yes", "no", "unsure") or e["timing"] not in ("immediate", "delayed", "conditional"):
            problems.append(f"{where}: traceVisible or timing has an unknown value")
        patch = set_root / str(e["patch"])
        if patch.is_file():
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp) / "game"
                shutil.copytree(game, work, ignore=shutil.ignore_patterns(".godot"))
                res = subprocess.run(["patch", "-p1", "--forward", "--batch", "--dry-run", "-d", str(work), "-i",
                                      str(patch.resolve())], capture_output=True, text=True)
                if res.returncode != 0:
                    problems.append(f"{where}: the patch does not apply to the clean game")
        route = set_root / str(e["route"])
        if route.is_file():
            try:
                validate(json.loads(route.read_text(encoding="utf-8")), "route")
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{where}: route does not validate ({str(exc)[:120]})")
    fresh_dir = set_root / set_dir
    if require_commitment:
        want = committed(commitment)
        where = f"bugs/fresh/{commitment.name}"
        if want is None:
            problems.append(f"no digest committed in {where}")
        elif digest(fresh_dir) != want:
            problems.append(f"{set_dir}/ does not match the digest committed in {where}")
    return problems


def notice(run: dict, entry_id: str, kind: str) -> str:
    """Counts only: no contract ids, no observations, no probe names."""
    reproduced = [f for f in run["findings"] if f["lifecycle"] == "reproduced"]
    flaky = [f for f in run["findings"] if f["lifecycle"] != "reproduced"]
    results = {}
    for cov in run["coverage"].values():
        for k, v in cov["results"].items():
            results[k] = results.get(k, 0) + v
    planner = next((s["status"] for s in run["stages"] if s["name"] == "planner"), "skipped")
    compact = {"id": entry_id, "kind": kind, "flagged": bool(reproduced), "reproduced": len(reproduced),
               "otherFindings": len(flaky), "completion": run["completion"], "episodes": run["usage"]["episodes"],
               "wallSeconds": run["usage"]["wallSeconds"], "results": results, "planner": planner}
    return f"::notice title=Blind {entry_id}::{json.dumps(compact, separators=(',', ':'))}"


def collect(run_id: int, out_dir: Path, fetch=None) -> dict:
    """Read a blind run's notices into bench/discovery/blind-run-<id>.json, with the scores."""
    from agents.bench_collect import gh_json, run_annotations

    run, notes = run_annotations(run_id, fetch or gh_json, prefix="blind")
    rows = [json.loads(n["message"]) for n in notes
            if (n.get("title") or "").startswith("Blind ") and not n["title"].startswith(("Blind time ", "Blind error"))
            and " error" not in n["title"]]
    if not rows:
        raise SystemExit(f"run {run_id}: no blind notices")
    rows.sort(key=lambda r: r["id"])
    defects = [r for r in rows if r["kind"] == "defect"]
    healthy = [r for r in rows if r["kind"] in ("intentional", "clean")]
    doc = {"run": run_id, "url": run.get("html_url"), "headSha": run.get("head_sha"), "createdAt": run.get("created_at"),
           "condition": "blind", "rows": rows,
           "score": {"defectsFlagged": sum(r["flagged"] for r in defects), "defects": len(defects),
                     "healthyFlagged": sum(r["flagged"] for r in healthy), "healthy": len(healthy),
                     "incomplete": sum(r["completion"] != "complete" for r in rows)}}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"blind-run-{run_id}.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return doc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("digest").add_argument("fresh_dir", type=Path)
    c = sub.add_parser("check")
    c.add_argument("set_root", type=Path)
    c.add_argument("--committed", action="store_true", help="also require the digest committed in bugs/fresh/")
    c.add_argument("--freeze-sha", help="the freeze digest to expect (default: discovery/freeze.json here)")
    l = sub.add_parser("list")
    l.add_argument("set_root", type=Path)
    n = sub.add_parser("notice")
    n.add_argument("run", type=Path)
    n.add_argument("--id", required=True)
    n.add_argument("--set", type=Path, help="the private set (for the entry's kind); omit for the clean control")
    for sp in (c, l, n):
        sp.add_argument("--dir", default="fresh", choices=sorted(SETS), help="which set (default fresh, set 1)")
    k = sub.add_parser("collect")
    k.add_argument("--run", type=int, required=True)
    k.add_argument("--out", type=Path, default=REPO / "bench" / "discovery")
    args = p.parse_args(argv)
    if args.cmd == "digest":
        print(digest(args.fresh_dir))
    elif args.cmd == "check":
        problems = check(args.set_root, freeze_sha=args.freeze_sha, require_commitment=args.committed,
                         set_dir=args.dir)
        for line in problems:
            print(f"problem: {line}", file=sys.stderr)
        if problems:
            return 1
        print(f"fresh set ok: {len(manifest(args.set_root, args.dir)['entries'])} entries")
    elif args.cmd == "list":
        print(json.dumps(["clean"] + [e["id"] for e in manifest(args.set_root, args.dir)["entries"]]))
    elif args.cmd == "notice":
        kind = "clean"
        if args.set is not None:
            kind = next(e["kind"] for e in manifest(args.set, args.dir)["entries"] if e["id"] == args.id)
        print(notice(json.loads(args.run.read_text(encoding="utf-8")), args.id, kind))
    else:
        doc = collect(args.run, args.out)
        print(json.dumps(doc["score"]))
    return 0

if __name__ == "__main__":
    sys.exit(main())
