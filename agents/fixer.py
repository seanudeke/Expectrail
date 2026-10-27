"""Run Muse Code in an isolated worktree and emit a candidate patch.

    python3 -m agents.fixer --request rr.json --out runs/fix \\
        [--candidate-patch agents/fixtures/fix-collision-mask.patch]

Without META_API_KEY (or with --candidate-patch), uses the fixture patch so CI can
verify the loop without calling Muse. With a key, runs `muse exec` against a copy
that already has the seeded bug applied.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from agents.keys import muse_code_ready
from agents.patchutil import assert_editable, path_allowed, sha256_file
from harness.run import REPO, apply_patches, tree_digest
from nightshift.contracts import load, validate

# Muse / tooling may drop sidecar files into the worktree; never ship them as the candidate.
IGNORE_DIFF_NAMES = {
    "repair-request.json",
    "muse.log",
    ".DS_Store",
}


def _diff_worktree(clean_seeded: Path, edited: Path, editable: list[str] | None = None) -> str:
    """Diff edited tree against the seeded baseline (paths relative to game root).

    Only paths matching editable globs are included, so Muse sidecars like
    repair-request.json never become part of the candidate.
    """
    import difflib

    chunks: list[str] = []
    files = sorted(
        p.relative_to(edited).as_posix()
        for p in edited.rglob("*")
        if p.is_file() and ".godot" not in p.parts and p.name not in IGNORE_DIFF_NAMES
    )
    for rel in files:
        if editable is not None and not path_allowed(rel, editable):
            continue
        a_path, b_path = clean_seeded / rel, edited / rel
        if not a_path.exists():
            # New file outside the seeded game: skip unless it matches editable.
            if editable is None or not path_allowed(rel, editable):
                continue
            a_lines: list[str] = []
        else:
            a_lines = a_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        b_lines = b_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        if a_lines == b_lines:
            continue
        chunks.append(
            "".join(difflib.unified_diff(a_lines, b_lines, fromfile=f"a/{rel}", tofile=f"b/{rel}"))
        )
    return "".join(chunks)


def prepare_fixer_workspace(request: dict, work: Path, game: Path | None = None) -> Path:
    """Copy game, apply base seed patch, return work path. Never mounts verifier secrets."""
    game = game or REPO / "game" / "platformer"
    if request["base"]["tree"] != tree_digest(game):
        raise SystemExit(
            f"base.tree mismatch: request {request['base']['tree']} != game {tree_digest(game)}"
        )
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(game, work, ignore=shutil.ignore_patterns(".godot"))
    seed = request["base"].get("patch")
    if seed:
        seed_path = Path(seed)
        if not seed_path.is_absolute():
            seed_path = REPO / seed_path
        apply_patches(work, [seed_path])
    # Isolation marker: no signing key in fixer workspace.
    forbidden = work / ".nightshift-signing-key"
    if forbidden.exists():
        raise SystemExit("signing key must not be present in the fixer workspace")
    return work


def run_fixer(
    request: dict,
    out: Path,
    *,
    candidate_patch: Path | None = None,
    game: Path | None = None,
    attempt: int = 1,
) -> dict:
    validate(request, "repair-request")
    out.mkdir(parents=True, exist_ok=True)
    work = out / "fixer-work"
    baseline = out / "fixer-baseline"
    prepare_fixer_workspace(request, work, game)
    if baseline.exists():
        shutil.rmtree(baseline)
    shutil.copytree(work, baseline, ignore=shutil.ignore_patterns(".godot"))

    patch_path = out / "candidate.patch"
    if candidate_patch is not None:
        text = candidate_patch.read_text(encoding="utf-8")
        patch_path.write_text(text, encoding="utf-8")
        apply_patches(work, [patch_path])
        source = "fixture"
    elif muse_code_ready():
        # Keep the request outside the game tree so it cannot appear in the candidate diff.
        rr_path = out / "repair-request.json"
        rr_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
        globs = ", ".join(request["editable"])
        prompt = f"""You are fixing a Godot 4 2D platformer bug.

Read the repair request at: {rr_path.resolve()}

Rules:
- Only edit files matching these globs (relative to the workspace root): {globs}
- Do not create or edit repair-request.json, logs, or any file outside those globs.
- Do not read or search for signing keys, held-out tests, or evaluator code.
- Produce the smallest correct fix for the failing assertion.
- The seeded bug is already applied in this workspace. Restore correct physics so the
  player does not fall through the ground (Player collision_mask should include the
  ground layer again; typically collision_mask = 30 in player/player.tscn).
- When done, leave the game files edited; do not commit.

Attempt {attempt} of {request['budget']['attempts']}.
"""
        proc = subprocess.run(
            ["muse", "exec", "--disable-approval", "--trust-workspace", prompt],
            cwd=str(work),
            capture_output=True,
            text=True,
            env=dict(os.environ),
            timeout=int(request["budget"].get("minutesPerAttempt", 15) * 60),
        )
        (out / "muse.log").write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
        text = _diff_worktree(baseline, work, editable=request["editable"])
        if not text.strip():
            raise SystemExit(
                f"muse produced an empty game patch (exit {proc.returncode}); see {out / 'muse.log'}"
            )
        patch_path.write_text(text, encoding="utf-8")
        source = "muse"
    else:
        raise SystemExit(
            "muse on PATH and META_API_KEY are required for Muse Code, "
            "or pass --candidate-patch for offline/CI runs"
        )

    bad = assert_editable(patch_path.read_text(encoding="utf-8"), request["editable"])
    if bad:
        raise SystemExit(f"candidate touches paths outside editable globs: {bad}")

    meta = {
        "request": request["id"],
        "attempt": attempt,
        "source": source,
        "patchSha256": sha256_file(patch_path),
        "baseTree": request["base"]["tree"],
        "patch": "candidate.patch",
    }
    (out / "candidate.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--candidate-patch", type=Path, help="offline/CI fixture instead of muse exec")
    p.add_argument("--attempt", type=int, default=1)
    p.add_argument("--game", type=Path)
    args = p.parse_args(argv)
    request = load(args.request, "repair-request")
    meta = run_fixer(request, args.out, candidate_patch=args.candidate_patch, game=args.game,
                     attempt=args.attempt)
    print(f"candidate {meta['patchSha256'][:12]}… from {meta['source']}: {args.out / 'candidate.patch'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
