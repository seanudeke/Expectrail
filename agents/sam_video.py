"""SAM 3.1 on a whole run sent as one video, measured against the per-frame image path.

The verifier asks sam-3.1 about one frame and one prompt at a time, at $2.50 per 1,000 images.
sam-3.1 also takes a video, at $0.20 per 1,000 frames (at least 50 a request), so a 120-frame run
costs about a tenth as much and every frame is looked at. In video mode, though, sam-3.1 tracks
objects from frame to frame. It could carry the robot through the trees, and then the layering
bugs would pass. Nothing switches on a price: this module sends the same frames both ways and
reports, per run, spec and frame, where the answers differ.

Public runs only. A video of a held-out route is the route itself, so it never leaves the runner.

    python -m agents.sam_video --spec specs/player-always-visible.json --spec specs/coins-visible.json \\
        --out runs/sam-video runs/seeded/*/
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from agents.sam_observations import (
    METADATA,
    MODEL,
    Cache,
    MetaSamClient,
    SamError,
    _document,
    default_cache_dir,
    frame_files,
    observe,
    output_text,
    parse_output,
    passing_frames,
    png_size,
    sam_usage,
    sam_usd_since,
)
from expectrail.contracts import load
from expectrail.evaluator import evaluate

FPS = 60  # the harness captures at 60 frames a second
CRF = 4  # H.264 High profile, yuv420p: near lossless and widely decodable
VIDEO_TIMEOUT = 600.0


def encode_mp4(frames: dict[int, Path], out: Path, *, fps: int = FPS, crf: int = CRF) -> list[int]:
    """The frames in order as an H.264 MP4. Returns the frame numbers in video order."""
    order = sorted(frames)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for k, i in enumerate(order):
            os.symlink(Path(frames[i]).resolve(), Path(tmp) / f"v{k:06d}.png")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(fps), "-i", str(Path(tmp) / "v%06d.png"),
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p", str(out)],
                       check=True, capture_output=True)
    return order


def video_body(prompt: str, video_url: str, model: str = MODEL) -> dict:
    """One concept prompt and one video, as the Responses API expects them (streamed, as the docs advise)."""
    return {
        "model": model,
        "stream": True,
        "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_video", "video_url": video_url},
        ]}],
        "metadata": dict(METADATA),
    }


def segment_video(client: MetaSamClient, mp4: Path, prompt: str, order: list[int],
                  frame_size: tuple[int, int]) -> dict[int, list[dict]]:
    """{frame number: [{"box", "score"}, best first]} for every frame of the video; no line means nothing found."""
    url = "data:video/mp4;base64," + base64.b64encode(Path(mp4).read_bytes()).decode("ascii")
    raw, content_type = client._call(video_body(prompt, url, client.model), video_frames=len(order))
    found: dict[int, list[dict]] = {i: [] for i in order}
    for record in parse_output(output_text(raw, content_type), frame_size=frame_size):
        k = record["frame"]
        if not 0 <= k < len(order):
            raise SamError(f"sam-3.1 answered for video frame {k}, but the video has {len(order)} frames")
        if record["score"] is None:
            raise SamError("sam-3.1 returned a video box without a confidence; a missing score is never guessed")
        found[order[k]].append({"box": record["box"], "score": record["score"]})
    return {i: sorted(d, key=lambda x: (-x["score"], x["box"])) for i, d in found.items()}


def _top(detections: list[dict]) -> dict | None:
    return detections[0] if detections else None


def object_agreement(image: dict[int, list], video: dict[int, list]) -> dict:
    """How one prompt's answers compare frame by frame: presence, best score, best box bottom and sides."""
    frames = sorted(image)
    both = [i for i in frames if image[i] and video[i]]
    only_image = [i for i in frames if image[i] and not video[i]]
    only_video = [i for i in frames if video[i] and not image[i]]
    score_diffs = [abs(_top(image[i])["score"] - _top(video[i])["score"]) for i in both]
    edge_diffs = [max(abs(a - b) for a, b in zip(_top(image[i])["box"], _top(video[i])["box"])) for i in both]
    bottom_diffs = [abs(_top(image[i])["box"][3] - _top(video[i])["box"][3]) for i in both]
    count_diffs = [abs(len(image[i]) - len(video[i])) for i in frames]
    return {
        "frames": len(frames),
        "foundByBoth": len(both),
        "onlyImages": only_image[:20],
        "onlyVideo": only_video[:20],
        "bestScoreMeanDiff": round(sum(score_diffs) / len(score_diffs), 4) if score_diffs else None,
        "bestScoreMaxDiff": round(max(score_diffs), 4) if score_diffs else None,
        "bestBoxMaxEdgeDiffPx": round(max(edge_diffs), 1) if edge_diffs else None,
        "bestBoxMaxBottomDiffPx": round(max(bottom_diffs), 1) if bottom_diffs else None,
        "framesWithBottomOver5Px": sum(d > 5 for d in bottom_diffs),
        "framesWithADifferentCount": sum(d > 0 for d in count_diffs),
    }


def compare_run(run_dir: Path, specs: list[dict], image_client: MetaSamClient, video_client: MetaSamClient,
                cache: Cache, out: Path) -> dict:
    """Every frame of one public run, both ways, for every prompt of ``specs``; then each spec's verdict both ways."""
    frames = frame_files(Path(run_dir) / "frames")
    if not frames:
        raise SamError(f"no frames in {run_dir}")
    size = png_size(next(iter(frames.values())))
    prompts: dict[str, str] = {}
    for spec in specs:
        for name, obj in spec["objects"].items():
            if prompts.setdefault(name, obj["prompt"]) != obj["prompt"]:
                raise SystemExit(f"object {name!r} has two prompts across the specs")
    indices = sorted(frames)

    before = sam_usage()
    image = observe(frames, indices, prompts, image_client, cache)
    image_usd = sam_usd_since(before)
    images_sent = sam_usage()["images"] - before["images"]

    mp4 = out / f"{Path(run_dir).name}.mp4"
    order = encode_mp4(frames, mp4)
    before = sam_usage()
    video: dict[int, dict] = {i: {} for i in indices}
    for name, prompt in prompts.items():
        for i, found in segment_video(video_client, mp4, prompt, order, size).items():
            video[i][name] = found
    video_usd = sam_usd_since(before)
    video_frames = sam_usage()["videoFrames"] - before["videoFrames"]
    mp4_bytes = mp4.stat().st_size
    mp4.unlink()  # ~10 MB a run; the frames are kept elsewhere

    row = {"run": Path(run_dir).name, "frames": len(indices), "mp4Bytes": mp4_bytes,
           "objects": {name: object_agreement({i: image[i][name] for i in indices},
                                              {i: video[i][name] for i in indices}) for name in prompts},
           "specs": {}, "images": images_sent, "imageUsd": round(image_usd, 4),
           "videoFrames": video_frames, "videoUsd": round(video_usd, 4)}
    for spec in specs:
        names = list(spec["objects"])
        docs = {}
        for label, seen in (("images", image), ("video", video)):
            observed = {i: {n: seen[i][n] for n in names} for i in indices}
            docs[label] = _document(observed, {n: prompts[n] for n in names}, image_client.model, "0" * 64,
                                    len(frames), len(indices), 1, [])
        verdicts = {label: evaluate(spec, doc) for label, doc in docs.items()}
        passing = {label: passing_frames(spec, doc) for label, doc in docs.items()}
        differ = sorted(passing["images"] ^ passing["video"])  # frames that pass one way and fail the other
        row["specs"][spec["id"]] = {
            "images": verdicts["images"]["result"], "video": verdicts["video"]["result"],
            "imagesFirstFrame": verdicts["images"].get("firstFrame"), "videoFirstFrame": verdicts["video"].get("firstFrame"),
            "framesFailingWithImages": len(set(indices) - passing["images"]),
            "framesFailingWithVideo": len(set(indices) - passing["video"]),
            "framesThatDiffer": differ[:30], "framesThatDifferCount": len(differ),
        }
    (out / f"{row['run']}.json").write_text(json.dumps({"row": row, "image": {str(i): image[i] for i in indices},
                                                        "video": {str(i): video[i] for i in indices}}, indent=1) + "\n",
                                           encoding="utf-8")
    return row


def annotation(row: dict) -> str:
    parts = []
    for sid, s in row["specs"].items():
        parts.append(f"{sid}: images {s['images']}, video {s['video']}, frames that differ {s['framesThatDifferCount']} "
                     f"(failing {s['framesFailingWithImages']} vs {s['framesFailingWithVideo']})")
    for name, o in row["objects"].items():
        parts.append(f"{name}: found by both {o['foundByBoth']}/{o['frames']}, only images {len(o['onlyImages'])}, "
                     f"only video {len(o['onlyVideo'])}, best score diff mean {o['bestScoreMeanDiff']} max "
                     f"{o['bestScoreMaxDiff']}, box bottom max diff {o['bestBoxMaxBottomDiffPx']} px")
    cost = (f"images {row['images']} (${row['imageUsd']:.2f}), video frames {row['videoFrames']} "
            f"(${row['videoUsd']:.3f})")
    return f"::notice title=Video vs images {row['run']}::" + "; ".join(parts) + "; " + cost


def markdown(rows: list[dict]) -> str:
    lines = ["# SAM 3.1: one video per run against one image per frame", "",
             ("Every frame of each public run, both ways. A spec row differs when its verdict or any frame's own "
              "verdict differs."), "",
             "| Run | Spec | Images | Video | Frames that differ | Images ($) | Video ($) |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        for sid, s in r["specs"].items():
            lines.append(f"| {r['run']} | {sid} | {s['images']} | {s['video']} | {s['framesThatDifferCount']} | "
                         f"{r['imageUsd']:.2f} | {r['videoUsd']:.3f} |")
    total_i = sum(r["imageUsd"] for r in rows)
    total_v = sum(r["videoUsd"] for r in rows)
    lines += ["", f"Total at list price: images ${total_i:.2f}, video ${total_v:.2f}."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    from agents.keys import load_dotenv

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("runs", nargs="*", type=Path, help="public run directories with frames/")
    p.add_argument("--spec", action="append", type=Path, default=[])
    p.add_argument("--out", type=Path, default=Path("runs/sam-video"))
    p.add_argument("--summarize", nargs="+", type=Path, metavar="VIDEO_JSON",
                   help="print one table from earlier runs' video.json files instead of sending anything")
    args = p.parse_args(argv)
    if args.summarize:
        rows = [row for path in args.summarize for row in json.loads(path.read_text(encoding="utf-8"))]
        print(markdown(rows), end="")
        return 0
    if not args.runs or not args.spec:
        p.error("give run directories and at least one --spec (or --summarize)")
    load_dotenv()
    specs = [load(s, "test-spec") for s in args.spec]
    args.out.mkdir(parents=True, exist_ok=True)
    image_client = MetaSamClient()
    video_client = MetaSamClient(timeout=VIDEO_TIMEOUT)
    cache = Cache(default_cache_dir())
    rows, failed = [], 0
    for run in args.runs:
        try:
            row = compare_run(run, specs, image_client, video_client, cache, args.out)
        except SamError as exc:
            failed += 1
            print(f"::error title=Video vs images {run.name}::{' '.join(str(exc).split())[:400]}")
            continue
        rows.append(row)
        print(annotation(row))
    (args.out / "video.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    (args.out / "video.md").write_text(markdown(rows), encoding="utf-8")
    return 1 if failed or not rows else 0


if __name__ == "__main__":
    sys.exit(main())
