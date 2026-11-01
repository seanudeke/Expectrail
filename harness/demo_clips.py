"""Record the demo page's clips with the real harness, and write their provenance manifest.

    python3 -m harness.demo_clips                      # every clip, into docs/demo/assets/
    python3 -m harness.demo_clips --only physics-v1    # one clip (the manifest keeps the others)

Each clip is one harness run (harness.run.run, the same capture the verifier judges): the clean game
copied, the listed patches applied in order (seeded bug first, then any candidate), the smoke route
replayed through Godot Movie Maker at 60 fps, then the frames encoded to H.264 with ffmpeg. The
smoke route is the one agents/matrix.py renders and judges for every dev case, so a clip shows the
run the verifier looked at.

The manifest (docs/demo/assets/manifest.json, expectrail.demo-clips/v1) records, per clip, the
patches and their digests, the route digest, the engine and render device, the frame count and a
digest over the frame digests, the trace digest and the mp4 digest. It also keeps a per-frame
timeline from the engine's own trace: the robot's position, whether it was on the floor, and where
the clean game's floor was drawn in that frame (the clean run's logged floor height, placed with the
camera that frame was drawn with, by the same mapping agents/observations.py uses for the verifier).
The demo page can read the timeline to draw its ground line and readout, so neither is hand-placed.

Every clip comes from a public dev bug, Muse Code's recorded public fix, or a public rejected
fixture under agents/fixtures/. Nothing here touches held-out or fresh cases.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

from agents.observations import FEET_OFFSET, _frame_tick, _to_frame, _view_at
from harness.run import REPO, run, sha256_file

ROUTE = REPO / "harness" / "routes" / "smoke.json"
OUT = REPO / "docs" / "demo" / "assets"
FPS = 60
WIDTH = 800  # encoded width; the capture is 1600x960 and the height keeps its ratio

V1 = "bugs/physics-fall-through/v1.patch"

# id -> (what it shows, patches in order). Order is seed then candidate, as harness.run applies them.
CLIPS: dict[str, tuple[str, list[str]]] = {
    "clean": ("The clean game: no patch. What a correct fix restores.", []),
    "physics-v1-fixed": ("physics-fall-through / v1 with Muse Code's recorded fix applied",
                         [V1, "bench/live-muse-clean-v1/fix/candidate.patch"]),
    "physics-v1": ("physics-fall-through / v1, the seeded bug", [V1]),
    "physics-v2": ("physics-fall-through / v2, the seeded bug", ["bugs/physics-fall-through/v2.patch"]),
    "missing-texture-v1": ("missing-texture / v1, the seeded bug", ["bugs/missing-texture/v1.patch"]),
    "missing-texture-v2": ("missing-texture / v2, the seeded bug", ["bugs/missing-texture/v2.patch"]),
    "layering-v1": ("layering / v1, the seeded bug", ["bugs/layering/v1.patch"]),
    "layering-v2": ("layering / v2, the seeded bug", ["bugs/layering/v2.patch"]),
    "sinking-v1": ("sinking / v1, the seeded bug", ["bugs/sinking/v1.patch"]),
    "sinking-v2": ("sinking / v2, the seeded bug", ["bugs/sinking/v2.patch"]),
    "exploit-freeze": ("physics v1 plus the rejected fixture that freezes the robot",
                       [V1, "agents/fixtures/freeze-player.patch"]),
    "exploit-hide": ("physics v1 plus the rejected fixture that fixes the mask and hides the robot",
                     [V1, "agents/fixtures/fix-but-hide-player.patch"]),
    "exploit-sink": ("physics v1 plus the rejected fixture that fixes the mask and draws the robot sunk",
                     [V1, "agents/fixtures/fix-but-sink-player.patch"]),
    "exploit-floor": ("physics v1 plus the rejected fixture that fixes the mask and lowers the floor's collision",
                      [V1, "agents/fixtures/fix-and-lower-the-floor.patch"]),
}

ENCODE = ["-c:v", "libx264", "-preset", "slow", "-crf", "30", "-pix_fmt", "yuv420p", "-threads", "1",
          "-movflags", "+faststart", "-an", "-map_metadata", "-1", "-fflags", "+bitexact",
          "-flags:v", "+bitexact"]


def ffmpeg_version() -> str:
    out = subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True, text=True).stdout
    return out.splitlines()[0].split(" Copyright")[0]


def commit() -> str | None:
    """The commit the clips were recorded at, with "+dirty" if the tree had uncommitted changes."""
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, check=True, capture_output=True,
                              text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no", "--", "game", "bugs",
                                "agents/fixtures", "bench/live-muse-clean-v1", "harness"],
                               cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return head + ("+dirty" if dirty else "")


def encode(frames: Path, mp4: Path) -> None:
    mp4.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
                    "-i", str(frames / "f%08d.png"), "-vf", f"scale={WIDTH}:-2:flags=lanczos", *ENCODE,
                    str(mp4)], check=True)


def clean_floor(trace: dict) -> float:
    """The one floor height the clean run stood on along the route (world y), or fail.

    The demo's ground line is the clean game's floor, not each candidate's own: a candidate that
    lowers the floor's collision (exploit-floor) or lets the robot fall into the dirt would otherwise
    move the line it is judged against. The smoke route crosses flat ground, so the clean run logs a
    single height on every tick; if a route ever crossed a step this would need a per-x lookup.
    """
    heights = {r.get("ground") for r in trace["rows"]}
    if len(heights) != 1 or None in heights:
        raise SystemExit(f"clean run logged several ground heights {sorted(map(str, heights))}; "
                         "the demo's ground line assumes one")
    return float(heights.pop())


def timeline(trace: dict, frames: int, size: tuple[int, int], floor_y: float) -> list[list]:
    """Per captured frame: [x, y, onFloor, the clean floor's height in that frame / frame height].

    x and y are the robot's origin from the trace; the floor is placed with the camera that frame
    was drawn with (agents.observations._view_at, the verifier's own mapping)."""
    rows = trace["rows"]
    step = max(int(trace.get("physicsTicksPerSecond") or 120) // FPS, 1)
    out = []
    for n in range(frames):
        tick = _frame_tick(n, step)
        row = rows[tick] if tick < len(rows) else {}
        view = _view_at(rows, tick) if tick < len(rows) else None
        player = row.get("player")
        frac = round(_to_frame(view, float(player[0]) if player else 0.0, floor_y)[1] / size[1], 4) if view else None
        if player is None:
            out.append([None, None, None, frac])
            continue
        out.append([round(float(player[0]), 1), round(float(player[1]), 1), bool(row.get("onFloor")), frac])
    return out


def record(clip_id: str, work: Path, out: Path, floor_y: float | None = None) -> dict:
    what, patches = CLIPS[clip_id]
    run_dir = work / clip_id
    replay = run(ROUTE, run_dir, patches=[REPO / p for p in patches], fps=FPS)
    pngs = sorted((run_dir / "frames").glob("f*.png"))
    size = struct.unpack(">II", pngs[0].read_bytes()[16:24])  # width, height from the PNG header
    mp4 = out / "videos" / f"{clip_id}.mp4"
    encode(run_dir / "frames", mp4)
    trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
    if floor_y is None:  # the clean clip: its own floor is the reference
        floor_y = clean_floor(trace)
    return {
        "id": clip_id,
        "shows": what,
        "patches": [{"path": p, "sha256": sha256_file(REPO / p)} for p in patches],
        "video": f"videos/{clip_id}.mp4",
        "videoSha256": sha256_file(mp4),
        "frames": len(pngs),
        "frameSize": list(size),
        "frameDigest": hashlib.sha256("".join(replay["frameSha256"]).encode()).hexdigest(),
        "traceSha256": replay["trace"]["sha256"],
        "engine": replay["engine"],
        "timeline": timeline(trace, len(pngs), size, floor_y),
    }


def dump(manifest: dict) -> str:
    """Indented JSON, with each clip's timeline on one line per frame so the file stays readable."""
    text = json.dumps(manifest, indent=2)
    return re.sub(r"\[\n\s+(null|-?[\d.]+),\n\s+(null|-?[\d.]+),\n\s+(null|true|false),\n\s+(null|-?[\d.]+)\n\s+\]",
                  lambda m: "[" + ", ".join(m.groups()) + "]", text) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--work", type=Path, default=REPO / "runs" / "demo-clips")
    p.add_argument("--only", action="append", choices=sorted(CLIPS), help="record just these clips")
    args = p.parse_args(argv)
    manifest_path = args.out / "manifest.json"
    old = {}
    if args.only and manifest_path.exists():
        old = {c["id"]: c for c in json.loads(manifest_path.read_text(encoding="utf-8")).get("clips", [])}
    clips = dict(old)
    wanted = args.only or list(CLIPS)
    if "clean" in wanted or "clean" not in clips or not (args.work / "clean" / "trace.json").exists():
        print("recording clean", file=sys.stderr)
        clips["clean"] = record("clean", args.work, args.out)
        shutil.rmtree(args.work / "clean" / "frames", ignore_errors=True)
    floor_y = clean_floor(json.loads((args.work / "clean" / "trace.json").read_text(encoding="utf-8")))
    for clip_id in wanted:
        if clip_id == "clean":
            continue
        print(f"recording {clip_id}", file=sys.stderr)
        clips[clip_id] = record(clip_id, args.work, args.out, floor_y)
        shutil.rmtree(args.work / clip_id / "frames", ignore_errors=True)
    manifest = {
        "format": "expectrail.demo-clips/v1",
        "generatedBy": "python3 -m harness.demo_clips",
        "commit": commit(),
        "route": {"path": str(ROUTE.relative_to(REPO)), "sha256": sha256_file(ROUTE)},
        "capture": {"fps": FPS, "mode": "Godot Movie Maker (--write-movie, --fixed-fps), opengl3",
                    "encoder": ffmpeg_version(), "encodedWidth": WIDTH},
        "cleanFloor": {"worldY": floor_y, "feetOffset": FEET_OFFSET,
                       "note": "the floor the clean run stood on along the route, from its trace; "
                               "feet = origin y + feetOffset, as agents/observations.py places them"},
        "timelineFields": ["x", "y", "onFloor", "cleanFloorFrac"],
        "clips": [clips[c] for c in CLIPS if c in clips],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(dump(manifest), encoding="utf-8")
    print(f"wrote {manifest_path} ({len(manifest['clips'])} clips)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
