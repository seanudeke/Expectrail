"""Capture the demo page's Godot Movie Maker clips and encode them as small MP4s.

Each clip is a real `harness.run` capture: the public dev seed patch (plus, for anti-cheat
cases, the recorded cheat fixture) on a public route. "Clean" clips are the unpatched game on
the same route: the reference a verified fix has to match.

    python3 scripts/capture_demo_clips.py            # capture every clip that is missing
    python3 scripts/capture_demo_clips.py sinking-v1 # capture named clips (overwrites)
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "demo" / "assets" / "videos"
FPS = 30
SEED_V1 = "bugs/physics-fall-through/v1.patch"

# clip name -> (route, patches in apply order)
CLIPS: dict[str, tuple[str, list[str]]] = {
    "physics-v2-before": ("smoke", ["bugs/physics-fall-through/v2.patch"]),
    "texture-v2-before": ("coins", ["bugs/missing-texture/v2.patch"]),
    "layering-v2-before": ("traversal", ["bugs/layering/v2.patch"]),
    "sinking-v1-before": ("smoke", ["bugs/sinking/v1.patch"]),
    "sinking-v2-before": ("smoke", ["bugs/sinking/v2.patch"]),
    # exploit-sink (SEED_V1 + fix-but-sink-player.patch) renders byte-identical to sinking-v2-before:
    # both end with the sprite at (0, 12) and the mask intact, so the page reuses that clip.
    "exploit-floor": ("smoke", [SEED_V1, "agents/fixtures/fix-and-lower-the-floor.patch"]),
    "clean-smoke": ("smoke", []),
    "clean-coins": ("coins", []),
    "clean-traversal": ("traversal", []),
}


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def capture(name: str) -> Path:
    route, patches = CLIPS[name]
    with tempfile.TemporaryDirectory(prefix=f"clip-{name}-") as tmp:
        cmd = [sys.executable, "-m", "harness.run", "--route", f"harness/routes/{route}.json",
               "--out", tmp, "--fps", str(FPS)]
        for p in patches:
            cmd += ["--patch", p]
        print("$", " ".join(cmd[1:]), flush=True)
        subprocess.run(cmd, cwd=REPO, check=True)
        frames = Path(tmp) / "frames"
        dest = OUT / f"{name}.mp4"
        subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-framerate", str(FPS),
                        "-i", str(frames / "f%08d.png"), "-c:v", "libx264", "-preset", "slow",
                        "-crf", "28", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                        "-vf", "scale=640:-2", str(dest)], check=True)
    print(f"  -> {dest.relative_to(REPO)} ({dest.stat().st_size // 1024} KB)", flush=True)
    return dest


def main(argv: list[str]) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    names = argv or [n for n in CLIPS if not (OUT / f"{n}.mp4").exists()]
    for n in names:
        capture(n)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

