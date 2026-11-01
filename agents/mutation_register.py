"""Write the mutation bench's registration, in the order #145 sets, from a person's decisions.

The decisions come from a file a person writes. This file holds none of them, on purpose: #127 keeps
operators, thresholds and samples with a person. What it does is the part that goes wrong by hand,
because the order matters: it writes the decisions, Sean's two recorded decisions and the status, then
the pins last, then the manifest, and reads both back through the same gates a judged run uses.

    python3 -m agents.mutation_register --values decisions.json          # checks, and writes nothing
    python3 -m agents.mutation_register --values decisions.json --write  # writes the registration

decisions.json uses the pre-registration's dotted names:

    {"generator.seed": ..., "generator.sampleSize": ..., "generator.sampling": {...},
     "generator.samplingWhy": "...", "generator.positionStep": ..., "generator.offsetStep": ...,
     "generator.scaleStep": ..., "generator.zIndexStep": ..., "generator.constantScale": ...,
     "generator.collisionBits": ..., "oracle.traceThresholdPx": ..., "oracle.frameThreshold": ...,
     "stopRule": "...", "agreement.seed": ..., "agreement.minimum": ..., "reportTemplate": "..."}

A registration is never overwritten, and never pins uncommitted work: a pin must name what is in git.
"""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from agents import mutate_game as mg
from harness.run import REPO

STATUS = "registered: every decision below was made before any case in the study was judged (#127, #145)"
# Sean's decisions, as #145 records them (issue #127, comment of Oct 31, 2026).
SEAN = {"wrongFix.commentOnlyLabel": "good", "wrongFix.publicSamRuleApprovedBy": "Sean, Oct 31, 2026"}
PERSON_FIELDS = tuple(f for f in mg.HUMAN_FIELDS if f != "pins" and f not in SEAN)
MANIFEST = mg.PREREGISTRATION.parent / "generated" / "manifest.json"


def _set(doc: dict, dotted: str, value) -> None:
    *parents, leaf = dotted.split(".")
    for part in parents:
        doc = doc[part]
    doc[leaf] = value


def apply_decisions(draft: dict, values: dict) -> dict:
    """The draft with a person's decisions and Sean's in it. Anything else in ``values`` is refused."""
    unknown = sorted(set(values) - set(PERSON_FIELDS))
    missing = sorted(set(PERSON_FIELDS) - set(values))
    if unknown or missing:
        raise mg.PreregistrationError(f"decisions file: not ours to set: {unknown}; missing: {missing}")
    doc = copy.deepcopy(draft)
    for dotted, value in {**values, **SEAN}.items():
        _set(doc, dotted, value)
    doc["status"] = STATUS
    return doc


def dirty_pins(repo: Path = REPO) -> list[str]:
    """Pinned material with uncommitted changes. A pin of those would name nothing in git."""
    rels = [*mg.PINNED, *mg.PINNED_TREES, "game/platformer"]
    out = subprocess.run(["git", "status", "--porcelain", "--", *rels], cwd=repo, capture_output=True, text=True,
                         check=True).stdout
    return sorted(line[3:] for line in out.splitlines())


def _write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def register(values: dict, *, write: bool, prereg_path: Path | None = None, manifest_path: Path | None = None) -> dict:
    """Check a registration and, with ``write``, make it. Returns the manifest. Nothing is written
    unless all of it passes the gates a judged run uses."""
    prereg_path, manifest_path = prereg_path or mg.PREREGISTRATION, manifest_path or MANIFEST
    draft = json.loads(Path(prereg_path).read_text(encoding="utf-8"))
    if draft.get("pins") or Path(manifest_path).exists():
        raise mg.PreregistrationError(f"{prereg_path} is already registered, and a registration is never overwritten")
    dirty = dirty_pins()
    if dirty:
        raise mg.PreregistrationError(f"commit or drop these first, a pin must name what is in git: {dirty}")
    doc = apply_decisions(draft, values)
    if "{sentence}" not in str(doc["reportTemplate"]):  # Part 3 fills it in, so no report is written by hand
        raise mg.PreregistrationError("reportTemplate needs {sentence}, the failing check's sentence")
    doc["pins"] = mg.current_pins()  # last: nothing may move after this
    with tempfile.TemporaryDirectory() as tmp:
        trial, trial_manifest = Path(tmp) / "preregistration.json", Path(tmp) / "manifest.json"
        _write_json(trial, doc)
        loaded = mg.load_preregistration(trial)
        manifest = mg.build_manifest(loaded)
        _write_json(trial_manifest, manifest)
        mg.load_manifest(loaded, trial_manifest)
    if write:
        _write_json(Path(prereg_path), doc)
        _write_json(Path(manifest_path), manifest)
    return manifest


def report(manifest: dict) -> str:
    lines = ["Class | Mutants | Sampled", "--- | --- | ---"]
    lines += [f"{c} | {manifest['enumeratedByClass'][c]} | {manifest['sampledByClass'][c]}" for c in mg.OPERATOR_CLASSES]
    lines += ["", f"{manifest['sampled']} sampled of {manifest['enumerated']} ({manifest['sampling']['method']}); "
              f"{len(manifest['excludedBeforeDraw'])} excluded before the draw."]
    if manifest["shortOfSample"]:
        lines.append(f"Short of the sample by {manifest['shortOfSample']}: {manifest['shortByClass'] or 'the game has no more'}.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--values", type=Path, required=True, help="a person's decisions, by dotted name")
    p.add_argument("--write", action="store_true", help="write the registration; without it, only check")
    args = p.parse_args(argv)
    try:
        manifest = register(json.loads(args.values.read_text(encoding="utf-8")), write=args.write)
    except (mg.PreregistrationError, OSError, ValueError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(report(manifest))
    print("Registered: commit both files in one pull request, and say it is the registration."
          if args.write else "Checked; nothing written. Add --write to register.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
