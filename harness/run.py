"""Run one route through the game and capture what a player would see.

    python3 -m harness.run --route harness/routes/smoke.json --out runs/smoke [--patch bugs/x/v1.patch]

The game under test is copied into <out>/work, a seeded-bug patch is applied there if given, and the
harness autoload is added to the copy only. Godot renders every frame through Movie Maker mode
(fixed frame rate, non-real time, so a slow machine gives the same frames, more slowly). Output:
<out>/frames/f00000000.png ..., <out>/trace.json (ground truth, for checking the evaluator, never
shown to the fixer) and <out>/replay.json (nightshift.replay/v0).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GODOT_VERSION = "4.7.2-stable"
AUTOLOAD = 'NightshiftHarness="*res://nightshift_harness.gd"'


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_godot() -> Path:
    env = os.environ.get("NIGHTSHIFT_GODOT")
    if env:
        return Path(env)
    out = subprocess.run([str(REPO / "harness" / "get_godot.sh")], check=True, capture_output=True, text=True)
    return Path(out.stdout.strip().splitlines()[-1])


def tree_digest(root: Path) -> str:
    """A digest of every file under root, so a replay names the exact game it ran."""
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and ".godot" not in p.parts):
        h.update(path.relative_to(root).as_posix().encode() + b"\0" + sha256_file(path).encode() + b"\n")
    return h.hexdigest()


def apply_patches(work: Path, patches: list[Path]) -> None:
    """Apply unified diffs in order to a game copy (seed first, then candidate, …)."""
    for patch in patches:
        subprocess.run(
            ["patch", "-p1", "--forward", "--batch", "-d", str(work), "-i", str(patch.resolve())],
            check=True, capture_output=True, text=True,
        )


def prepare(game: Path, work: Path, patch: Path | None = None, patches: list[Path] | None = None) -> None:
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(game, work, ignore=shutil.ignore_patterns(".godot"))
    ordered = list(patches) if patches is not None else ([patch] if patch is not None else [])
    apply_patches(work, ordered)
    for name in ("nightshift_harness.gd", "nightshift_recorder.gd"):
        shutil.copy(REPO / "harness" / "godot" / name, work / name)
    project = (work / "project.godot").read_text(encoding="utf-8")
    if "[autoload]" in project:
        project = project.replace("[autoload]\n", "[autoload]\n\n" + AUTOLOAD + "\n", 1)
    else:
        project += "\n[autoload]\n\n" + AUTOLOAD + "\n"
    (work / "project.godot").write_text(project, encoding="utf-8")


def godot_cmd(godot: Path, display: bool) -> list[str]:
    cmd = [str(godot)]
    if not display:
        cmd = ["xvfb-run", "-a", "-s", "-screen 0 1920x1080x24"] + cmd
    return cmd


def run(route: Path, out: Path, patch: Path | None = None, game: Path | None = None, fps: int = 60,
        godot: Path | None = None, patches: list[Path] | None = None) -> dict:
    game = game or REPO / "game" / "platformer"
    godot = godot or find_godot()
    out.mkdir(parents=True, exist_ok=True)
    work, frames = out / "work", out / "frames"
    ordered = list(patches) if patches is not None else ([patch] if patch is not None else [])
    prepare(game, work, patches=ordered)
    if frames.exists():
        shutil.rmtree(frames)
    frames.mkdir()
    route_doc = json.loads(route.read_text(encoding="utf-8"))
    env = dict(os.environ, LIBGL_ALWAYS_SOFTWARE=os.environ.get("LIBGL_ALWAYS_SOFTWARE", "1"))
    subprocess.run([str(godot), "--headless", "--path", str(work), "--import"], check=True, capture_output=True,
                   text=True, env=env, timeout=600)
    display = bool(os.environ.get("DISPLAY"))
    cmd = godot_cmd(godot, display) + [
        "--path", str(work), "--audio-driver", "Dummy", "--rendering-driver", "opengl3",
        "--write-movie", str((frames / "f.png").resolve()), "--fixed-fps", str(fps),
        "--", f"--route={route.resolve()}", f"--trace={(out / 'trace.json').resolve()}",
        f"--seed={route_doc.get('seed', 1)}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=1800)
    (out / "godot.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    if proc.returncode != 0 or not (out / "trace.json").exists():
        raise SystemExit(f"godot failed ({proc.returncode}); see {out / 'godot.log'}")
    log = proc.stdout + proc.stderr
    device = re.search(r"Using Device: (.+)", log)
    version = re.search(r"Godot Engine v(\S+)", log)
    pngs = sorted(frames.glob("f*.png"))
    trace = json.loads((out / "trace.json").read_text(encoding="utf-8"))
    primary = ordered[0] if ordered else None
    replay = {
        "format": "nightshift.replay/v0",
        "route": {"name": route_doc.get("name", route.stem), "sha256": sha256_file(route)},
        "game": {"tree": tree_digest(game),
                 "patch": ",".join(str(p) for p in ordered) if ordered else None,
                 "patchSha256": sha256_file(primary) if primary and len(ordered) == 1 else (
                     None if not ordered else hashlib.sha256(
                         b"".join(sha256_file(p).encode() for p in ordered)).hexdigest())},
        "engine": {"name": "godot", "version": version.group(1) if version else GODOT_VERSION,
                   "renderer": "opengl3", "device": device.group(1).strip() if device else None},
        "capture": {"fps": fps, "physicsTicksPerSecond": trace.get("physicsTicksPerSecond"),
                    "frames": len(pngs), "pattern": "frames/f%08d.png"},
        "frameSha256": [sha256_file(p) for p in pngs],
        "trace": {"path": "trace.json", "sha256": sha256_file(out / "trace.json")},
    }
    (out / "replay.json").write_text(json.dumps(replay, indent=2) + "\n", encoding="utf-8")
    return replay


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--route", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--patch", type=Path, action="append", default=[],
                   help="patch to apply (repeatable; order is seed then candidate)")
    p.add_argument("--game", type=Path, help="game directory (default: game/platformer)")
    p.add_argument("--fps", type=int, default=60)
    args = p.parse_args(argv)
    patches = args.patch or None
    replay = run(args.route, args.out, patch=None, game=args.game, fps=args.fps, patches=patches)
    print(f"{replay['capture']['frames']} frames, device {replay['engine']['device']}: {args.out / 'replay.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
