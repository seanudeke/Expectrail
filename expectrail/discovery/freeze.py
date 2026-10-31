"""Freeze advisory discovery before a blind run, and check a checkout against the freeze.

    python -m expectrail.discovery.freeze write     # writes discovery/freeze.json
    python -m expectrail.discovery.freeze verify    # exit 1, naming every file that changed

A blind run means nothing if the discoverer can be adjusted after the defects exist. The freeze
records the sha256 of every file that decides a finding (the probes, the route compiler, the profile
and its templates, the signals and the interpreter, the job, the planner's prompt and model, the
record schemas, the recorder and the replay harness, and the clean game's whole tree) and the exact
command a blind job runs. Its own digest is what the fresh defect set's manifest names, and the
blind run verifies it on the commit it checks out before it replays anything. Until the blind run is
recorded, tests/test_discovery_freeze.py keeps the freeze holding on main, so a frozen file cannot
change without a test failing.

The report and collection code (cli.py's report, annotate and collect) is left out on purpose: it
formats findings and decides none.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FREEZE = Path("discovery/freeze.json")
FROZEN = (
    "discovery/platformer.profile.json",
    "expectrail/contracts.py",
    "expectrail/trace/__init__.py",
    "expectrail/trace/evaluator.py",
    "expectrail/trace/normalize.py",
    "expectrail/trace/signals.py",
    "expectrail/discovery/__init__.py",
    "expectrail/discovery/planner.py",
    "expectrail/discovery/probes.py",
    "expectrail/discovery/route_compiler.py",
    "expectrail/discovery/run.py",
    "expectrail/discovery/templates.py",
    "contracts/episode.v1.schema.json",
    "contracts/trace-spec.v1.schema.json",
    "contracts/trace-verdict.v1.schema.json",
    "contracts/mechanics-profile.v1.schema.json",
    "contracts/discovery-run.v1.schema.json",
    "contracts/route.schema.json",
    "harness/run.py",
    "harness/godot/expectrail_harness.gd",
    "harness/godot/expectrail_recorder.gd",
)
GAME = "game/platformer"
COMMAND = ("python -m expectrail.discovery.cli discover --profile discovery/platformer.profile.json "
           "--snapshot <id>:base:<patch> --out <dir> --planner <off|spark> --label 'FRESH LIVE' --max-seconds 1800")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and ".godot" not in p.parts):
        h.update(path.relative_to(root).as_posix().encode() + b"\0" + _sha(path).encode() + b"\n")
    return h.hexdigest()


def compute(root: Path = REPO) -> dict:
    missing = [f for f in FROZEN if not (root / f).is_file()]
    if missing:
        raise SystemExit(f"cannot freeze: missing {', '.join(missing)}")
    body = {"format": "expectrail.discovery-freeze/v1", "files": {f: _sha(root / f) for f in FROZEN},
            "gameTree": {GAME: _tree(root / GAME)}, "command": COMMAND}
    body["sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return body


def verify(root: Path = REPO) -> tuple[bool, list[str], str | None]:
    """(ok, problems, the recorded digest) for the checkout at root."""
    path = root / FREEZE
    if not path.is_file():
        return False, [f"no {FREEZE}"], None
    recorded = json.loads(path.read_text(encoding="utf-8"))
    current = compute(root)
    problems = [f"{f} changed" for f in FROZEN if recorded["files"].get(f) != current["files"][f]]
    problems += [f"{f} is frozen but no longer listed" for f in recorded["files"] if f not in current["files"]]
    if recorded["gameTree"] != current["gameTree"]:
        problems.append(f"{GAME} changed")
    if recorded["command"] != current["command"]:
        problems.append("the blind command changed")
    if not problems and recorded["sha256"] != current["sha256"]:
        problems.append("the recorded digest does not match its contents")
    return not problems, problems, recorded.get("sha256")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("action", choices=("write", "verify"))
    p.add_argument("--root", type=Path, default=REPO)
    args = p.parse_args(argv)
    if args.action == "write":
        doc = compute(args.root)
        (args.root / FREEZE).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        print(f"frozen: {doc['sha256']} ({len(doc['files'])} files and the clean game)")
        return 0
    ok, problems, digest = verify(args.root)
    if ok:
        print(f"freeze holds: {digest}")
        return 0
    print("freeze broken: " + "; ".join(problems), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
