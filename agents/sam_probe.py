"""See what SAM 3.1 sees before trusting it: overlays, scores, and the gap to the boundary.

Runs SAM on a handful of frames from each run (the clean game and the seeded bugs) and reports,
per run and object: how often it was found at or above the spec's minScore, the score spread,
how many matches each frame had, and how stable the box size is. For a never-crosses spec it
also measures, on every probed frame, how far the object's edge is past the boundary (negative
means clear of it). On the clean run that number is what the tolerance has to allow; on the
fall-through runs it is how far the bug goes. A tolerance between the two separates them.

    python3 -m harness.check_seeded --out runs/seeded       # clean + every seeded bug, with frames
    python3 -m agents.sam_probe --runs runs/seeded/* --spec specs/player-stays-above-ground.json \\
        --every 10 --out runs/sam-probe

Writes <out>/probe.md and <out>/probe.json, plus overlay PNGs and a contact sheet per run when
Pillow is installed. Nothing here edits a spec: the numbers inform the person who re-approves it.
Boxes are in captured-frame pixels (1600x960 here, twice the 800x480 game viewport).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

from agents.observations import engine_ground_by_frame, has_engine_ground, with_reference_ground
from agents.sam_observations import (
    Cache, SamError, _document, default_cache_dir, default_client, frame_files, observe, png_size, sample,
    sha256_bytes, vision_backend, window,
)
from nightshift.evaluator import DEFAULT_MIN_SCORE, EDGE, SIDE, _overlap, evaluate

COLORS = ["#00e05a", "#2f8cff", "#ff4fd8", "#ffb000", "#00d5e0", "#ff5a36"]


def _best(detections, min_score):
    found = [d for d in detections or [] if d.get("score", 0) >= min_score]
    return max(found, key=lambda d: d["score"]) if found else None


def boundary_gap(spec: dict, objects: dict) -> tuple[float | None, str]:
    """How far the object's edge is past the never-crosses boundary in one frame.

    Same choices as the evaluator: best detection above minScore, references above minScore that
    overlap on the other axis, the reference whose edge is nearest. Positive means past the
    boundary (a fail once it exceeds tolerancePx); negative means clear of it.
    """
    assertion = spec["assertion"]
    bnd = assertion["boundary"]
    scores = {n: o.get("minScore", DEFAULT_MIN_SCORE) for n, o in spec["objects"].items()}
    obj = _best(objects.get(assertion["object"]), scores.get(assertion["object"], DEFAULT_MIN_SCORE))
    if obj is None:
        return None, f"{assertion['object']} not found"
    index, sign = SIDE[bnd["side"]]
    if "relativeTo" not in bnd:
        return round(sign * (obj["box"][index] - bnd["value"]), 3), ""
    refs = [d for d in objects.get(bnd["relativeTo"]) or []
            if d.get("score", 0) >= scores.get(bnd["relativeTo"], DEFAULT_MIN_SCORE)]
    if not refs:
        return None, f"{bnd['relativeTo']} not found"
    if bnd.get("requireOverlap", True):
        other = "x" if bnd["side"] in ("above", "below") else "y"
        refs = [d for d in refs if _overlap(obj["box"], d["box"], other)]
        if not refs:
            return None, f"no {bnd['relativeTo']} under the {assertion['object']}"
    ref = min(refs, key=lambda d: abs(d["box"][EDGE[bnd["edge"]]] - obj["box"][index]))
    return round(sign * (obj["box"][index] - ref["box"][EDGE[bnd["edge"]]]), 3), ""


def object_metrics(spec: dict, observed: dict[int, dict]) -> dict:
    out = {}
    for name, obj in spec["objects"].items():
        min_score = obj.get("minScore", DEFAULT_MIN_SCORE)
        best_scores, matches, widths, heights, found = [], [], [], [], 0
        for frame in sorted(observed):
            detections = observed[frame].get(name) or []
            top = max((d["score"] for d in detections), default=0.0)
            best_scores.append(top)
            above = [d for d in detections if d["score"] >= min_score]
            matches.append(len(above))
            if above:
                found += 1
                b = max(above, key=lambda d: d["score"])["box"]
                widths.append(b[2] - b[0])
                heights.append(b[3] - b[1])
        out[name] = {
            "prompt": obj["prompt"], "minScore": min_score, "framesFound": found, "framesProbed": len(observed),
            "bestScore": {"min": min(best_scores), "median": statistics.median(best_scores), "max": max(best_scores)}
            if best_scores else None,
            "matchesPerFrame": {"min": min(matches), "max": max(matches)} if matches else None,
            "boxWidth": _spread(widths), "boxHeight": _spread(heights),
        }
    return out


def _spread(values):
    if not values:
        return None
    return {"min": round(min(values), 1), "median": round(statistics.median(values), 1), "max": round(max(values), 1)}


def on_floor_by_frame(run: Path) -> dict[int, bool]:
    """Whether the engine says the player stood on the floor at each captured frame."""
    try:
        trace = json.loads((run / "trace.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    fps = 60
    try:
        fps = int(json.loads((run / "replay.json").read_text(encoding="utf-8"))["capture"]["fps"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    step = max(int(trace.get("physicsTicksPerSecond") or 120) // fps, 1)
    return {int(r["tick"]) // step: bool(r.get("onFloor")) for r in trace.get("rows", [])
            if int(r["tick"]) % step == 0}


def draw(run_name: str, frames: dict[int, Path], observed: dict[int, dict], spec: dict, out: Path) -> list[str]:
    """Overlay PNGs (half size) and one contact sheet; returns written paths, [] without Pillow."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return []
    names = list(spec["objects"])
    written, thumbs = [], []
    run_dir = out / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    for i in sorted(observed):
        img = Image.open(frames[i]).convert("RGB")
        pen = ImageDraw.Draw(img)
        for k, name in enumerate(names):
            color = COLORS[k % len(COLORS)]
            for d in observed[i].get(name) or []:
                b = d["box"]
                pen.rectangle(b, outline=color, width=3)
                pen.text((b[0] + 4, max(0, b[1] - 14)), f"{name} {d['score']:.2f}", fill=color)
        pen.text((8, 8), f"{run_name}  frame {i}", fill="#ffffff")
        small = img.resize((img.width // 2, img.height // 2))
        path = run_dir / f"f{i:08d}.png"
        small.save(path)
        written.append(str(path))
        thumbs.append(img.resize((img.width // 4, img.height // 4)))
    if thumbs:
        cols = min(4, len(thumbs))
        rows = -(-len(thumbs) // cols)
        tw, th = thumbs[0].size
        sheet = Image.new("RGB", (cols * tw, rows * th), "#111111")
        for n, thumb in enumerate(thumbs):
            sheet.paste(thumb, ((n % cols) * tw, (n // cols) * th))
        path = out / f"{run_name}-sheet.png"
        sheet.save(path)
        written.append(str(path))
    return written


def engine_objects_for(run: Path, name: str, frames: dict, chosen: list[int],
                       reference: list | None = None) -> dict[int, dict]:
    """{frame: {name: [ground box]}} from the run's harness trace, or {} if it has no ground line.

    With ``reference`` (the clean run's level surfaces), the ground line is recomputed from the
    clean level, as the verifier does, rather than taken from the variant's own level.
    """
    try:
        trace = json.loads((run / "trace.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if reference:
        trace = with_reference_ground(trace, reference)
    if not has_engine_ground(trace) or not chosen:
        return {}
    by_frame = engine_ground_by_frame(trace, png_size(frames[chosen[0]]), chosen)
    return {i: {name: by_frame.get(i, {}).get("ground", [])} for i in chosen}


def probe_run(run: Path, spec: dict, picked: list[int] | None, every: int, client, cache, workers: int,
              out: Path | None, engine_ground: str | None = None, reference: list | None = None) -> dict:
    frames = frame_files(run / "frames")
    if not frames:
        raise SamError(f"no frames in {run / 'frames'}")
    indices = window(list(frames), spec)
    chosen = [i for i in (picked or sample(indices, every)) if i in frames]
    engine = engine_objects_for(run, engine_ground, frames, chosen, reference) if engine_ground else {}
    prompts = {name: obj["prompt"] for name, obj in spec["objects"].items() if not (engine and name == engine_ground)}
    observed = observe(frames, chosen, prompts, client, cache, workers)
    for i, objs in engine.items():
        observed[i].update(objs)
    replay = run / "replay.json"
    doc = _document(observed, prompts, client.model, sha256_bytes(replay) if replay.is_file() else "0" * 64,
                    len(frames), len(indices), every, [], 0, engine, getattr(client, "provider", "meta-model-api"))
    verdict = evaluate(spec, doc)
    result = {"run": run.name, "framesProbed": chosen, "verdict": {k: verdict[k] for k in ("result", "reason")},
              "objects": object_metrics(spec, observed), "observations": doc}
    if spec["assertion"]["type"] == "never-crosses":
        floor = on_floor_by_frame(run)
        gaps = []
        for i in chosen:
            gap, why = boundary_gap(spec, observed[i])
            gaps.append({"frame": i, "gap": gap, "onFloor": floor.get(i), **({"why": why} if why else {})})
        result["gaps"] = gaps
    if out is not None:
        result["images"] = draw(run.name, frames, observed, spec, out)
    return result


def tolerance_hint(spec: dict, runs: list[dict], clean_names: set[str]) -> dict | None:
    if spec["assertion"]["type"] != "never-crosses":
        return None
    tol = spec["assertion"]["boundary"].get("tolerancePx", 0)

    def worst(run):
        values = [g["gap"] for g in run.get("gaps", []) if g["gap"] is not None]
        return max(values) if values else None

    clean = [(r["run"], worst(r)) for r in runs if r["run"] in clean_names]
    other = [(r["run"], worst(r)) for r in runs if r["run"] not in clean_names]
    clean_worst = max((w for _, w in clean if w is not None), default=None)
    return {"approvedTolerancePx": tol, "cleanWorstGap": clean_worst,
            "clean": dict(clean), "others": dict(other)}


def markdown(spec: dict, runs: list[dict], hint: dict | None, model: str, stats: dict) -> str:
    lines = [f"# {_label()} probe: {spec['id']}", "",
             f"Model `{model}`. Prompts: " + ", ".join(f"{n} = \"{o['prompt']}\"" for n, o in spec["objects"].items())
             + f". API calls {stats.get('calls', 0)}, cache hits {stats.get('cacheHits', 0)}.", "",
             "Verdicts below are on the probed frames only, not a full run.", "",
             "| Run | Frames | Verdict | " + " | ".join(f"{n} found" for n in spec["objects"]) + " |",
             "| --- | --- | --- | " + " | ".join("---" for _ in spec["objects"]) + " |"]
    for r in runs:
        found = [f"{m['framesFound']}/{m['framesProbed']}" for m in r["objects"].values()]
        lines.append(f"| {r['run']} | {len(r['framesProbed'])} | {r['verdict']['result']} | " + " | ".join(found) + " |")
    lines += ["", "## Per object", ""]
    for r in runs:
        lines.append(f"**{r['run']}**: {r['verdict']['reason']}")
        for name, m in r["objects"].items():
            s = m["bestScore"]
            lines.append(f"- {name}: best score min {s['min']:.2f}, median {s['median']:.2f}, max {s['max']:.2f}; "
                         f"matches per frame {m['matchesPerFrame']['min']} to {m['matchesPerFrame']['max']}; "
                         f"box width {m['boxWidth']}, height {m['boxHeight']}" if s else f"- {name}: nothing probed")
        lines.append("")
    if hint:
        lines += ["## Tolerance", "",
                  f"Approved spec: tolerancePx = {hint['approvedTolerancePx']} (set against the position-log stand-in, "
                  "whose boxes are in game-world pixels; SAM boxes are in captured-frame pixels, twice as large here).", ""]
        for name, w in {**hint["clean"], **hint["others"]}.items():
            tag = "clean" if name in hint["clean"] else "bug"
            lines.append(f"- {name} ({tag}): worst gap {w if w is not None else 'n/a'} px")
        cw = hint["cleanWorstGap"]
        lines += ["", "A gap above the tolerance is a fail. The tolerance has to sit above every clean gap and "
                  "below the gaps of the bugs this spec should catch" +
                  (f"; the clean worst here is {cw} px." if cw is not None else "; no clean run was probed.")]
    return "\n".join(lines) + "\n"


def _label() -> str:
    """Which model the probe is about, for titles: SAM, or Glimmer with NIGHTSHIFT_VISION_BACKEND=glimmer."""
    try:
        return "Glimmer" if vision_backend() == "glimmer" else "SAM"
    except SamError:
        return "SAM"


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _num(value) -> str:
    return "n/a" if value is None else f"{value:g}" if isinstance(value, (int, float)) else str(value)


def annotations(report: dict) -> list[str]:
    """One GitHub notice per run plus one for tolerance and cost (GitHub keeps 10 per step).

    Annotations are readable through the checks API, so the numbers can be read back without
    downloading the artifact or the log.
    """
    lines = []
    for run in report["runs"][:8]:
        parts = [run["verdict"]["result"]]
        for name, m in run["objects"].items():
            s, mp = m["bestScore"], m["matchesPerFrame"]
            parts.append(f"{name} {m['framesFound']}/{m['framesProbed']}"
                         + (f" score min {s['min']:.2f} med {s['median']:.2f} matches {mp['min']}-{mp['max']}"
                            f" box {_num((m['boxWidth'] or {}).get('median'))}x{_num((m['boxHeight'] or {}).get('median'))}"
                            if s else ""))
        if run.get("gaps"):
            parts.append("gaps " + " ".join(f"{g['frame']}:{_num(g['gap'])}" for g in run["gaps"]))
        lines.append(f"::notice title={_label()} probe {run['run']}::{_escape('; '.join(parts))}")
    hint, stats = report.get("tolerance") or {}, report.get("stats", {})
    calls = stats.get("calls") or 0
    summary = [f"model {report['model']}", f"calls {calls}", f"cache hits {stats.get('cacheHits', 0)}",
               f"seconds per call {stats.get('seconds', 0) / calls:.2f}" if calls else "seconds per call n/a"]
    if hint:
        summary.append(f"approved tolerance {_num(hint['approvedTolerancePx'])}")
        summary.append(f"clean worst gap {_num(hint['cleanWorstGap'])}")
        summary.append("bug worst gaps " + " ".join(f"{k}:{_num(v)}" for k, v in hint["others"].items()))
    lines.append(f"::notice title={_label()} probe summary::{_escape('; '.join(summary))}")
    return lines


def with_prompts(spec: dict, overrides: dict[str, str]) -> dict:
    """A copy of the spec with some object prompts replaced (for probing only, never saved)."""
    doc = json.loads(json.dumps(spec))
    for name, prompt in overrides.items():
        if name not in doc["objects"]:
            raise SystemExit(f"--set/--sweep names an object the spec does not have: {name!r}")
        doc["objects"][name]["prompt"] = prompt
    return doc


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-") or "prompt"


def sweep(runs: list[Path], spec: dict, name: str, candidates: list[str], picked, every: int, client, cache,
          workers: int, out: Path | None, clean_names: set[str]) -> list[dict]:
    """Probe each candidate prompt for one object over the same runs and frames.

    Other objects keep their prompts, so their answers come from the cache after the first
    candidate. Contact sheets are drawn for the clean runs only.
    """
    results = []
    for prompt in candidates:
        variant = with_prompts(spec, {name: prompt})
        per_run = []
        for run in runs:
            images = out / "sweep" / _slug(prompt) if out is not None and run.name in clean_names else None
            per_run.append(probe_run(run, variant, picked, every, client, cache, workers, images))
        results.append({"object": name, "prompt": prompt, "runs": per_run,
                        "tolerance": tolerance_hint(variant, per_run, clean_names)})
        print(f"sweep {name}={prompt!r}: " + ", ".join(f"{r['run']} {r['verdict']['result']}" for r in per_run),
              flush=True)
    return results


def sweep_annotations(results: list[dict]) -> list[str]:
    lines = []
    for item in results[:9]:
        name, parts = item["object"], []
        for run in item["runs"]:
            m = run["objects"][name]
            s, mp = m["bestScore"], m["matchesPerFrame"]
            parts.append(f"{run['run']} {run['verdict']['result']} {name} {m['framesFound']}/{m['framesProbed']}"
                         + (f" med {s['median']:.2f} matches {mp['min']}-{mp['max']}"
                            f" box {_num((m['boxWidth'] or {}).get('median'))}x"
                            f"{_num((m['boxHeight'] or {}).get('median'))}" if s else ""))
            if run.get("gaps"):
                parts.append("gaps " + " ".join(f"{g['frame']}:{_num(g['gap'])}" for g in run["gaps"]))
        hint = item.get("tolerance")
        if hint:
            parts.append(f"clean worst gap {_num(hint['cleanWorstGap'])}")
        lines.append(f"::notice title={_label()} sweep {name}={item['prompt']}::{_escape('; '.join(parts))}")
    return lines


def _pairs(values: list[str], flag: str) -> dict[str, str]:
    out = {}
    for value in values or []:
        name, sep, prompt = value.partition("=")
        if not sep or not name.strip() or not prompt.strip():
            raise SystemExit(f"{flag} expects NAME=PROMPT, got {value!r}")
        out[name.strip()] = prompt.strip()
    return out


def main(argv: list[str] | None = None) -> int:
    from agents.keys import load_dotenv
    from nightshift.contracts import load

    p = argparse.ArgumentParser(description="Probe SAM 3.1 on a few frames of each run before trusting it.")
    p.add_argument("--set", action="append", default=[], metavar="NAME=PROMPT",
                   help="probe with a different prompt for one object (the spec file is not changed)")
    p.add_argument("--sweep", metavar="NAME=P1|P2|...",
                   help="try several prompts for one object over the same runs and frames")
    p.add_argument("--engine-ground", metavar="NAME",
                   help="take this object (e.g. ground) from the harness's ground line instead of asking SAM")
    p.add_argument("--runs", type=Path, nargs="+", required=True, help="run dirs with frames/ (and trace.json)")
    p.add_argument("--spec", type=Path, required=True)
    p.add_argument("--every", type=int, default=10, help="probe every Nth frame of the window (default 10)")
    p.add_argument("--frames", help="explicit comma-separated frame numbers instead of --every")
    p.add_argument("--clean", default="clean", help="comma-separated run names that are clean (default: clean)")
    p.add_argument("--out", type=Path, default=Path("runs/sam-probe"))
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="print the frames and request count, call nothing")
    args = p.parse_args(argv)
    load_dotenv()

    spec = with_prompts(load(args.spec, "test-spec"), _pairs(args.set, "--set"))
    sweep_name, candidates = None, []
    if args.sweep:
        sweep_name, prompts = next(iter(_pairs([args.sweep], "--sweep").items()))
        candidates = [c.strip() for c in prompts.split("|") if c.strip()]
        with_prompts(spec, {sweep_name: candidates[0]})  # fails early on an unknown object
    picked = [int(x) for x in args.frames.split(",")] if args.frames else None
    runs = [r for r in args.runs if (r / "frames").is_dir()]
    if not runs:
        print("no run dirs with frames/ given", file=sys.stderr)
        return 2
    if args.dry_run:
        total = 0
        for run in runs:
            frames = frame_files(run / "frames")
            chosen = [i for i in (picked or sample(window(list(frames), spec), args.every)) if i in frames]
            total += len(chosen) * (len(spec["objects"]) + max(0, len(candidates) - 1))
            print(f"{run.name}: frames {chosen}")
        print(f"{total} requests at most (cached frames are not sent)")
        return 0

    client = default_client()
    cache = Cache(None if args.no_cache else default_cache_dir())
    args.out.mkdir(parents=True, exist_ok=True)
    clean_names = set(args.clean.split(","))
    on_github = os.environ.get("GITHUB_ACTIONS") == "true"
    reference = None
    for run in runs:  # the clean run's level is the yardstick for every run, as in the verifier
        if run.name in clean_names and (run / "trace.json").is_file():
            reference = json.loads((run / "trace.json").read_text(encoding="utf-8")).get("levelSurfaces")
            break
    results, swept = [], []
    try:
        if sweep_name:
            swept = sweep(runs, spec, sweep_name, candidates, picked, args.every, client, cache, args.workers,
                          args.out, clean_names)
        else:
            for run in runs:
                results.append(probe_run(run, spec, picked, args.every, client, cache, args.workers, args.out,
                                         args.engine_ground, reference))
                print(f"{run.name}: {results[-1]['verdict']['result']}", flush=True)
    except SamError as exc:
        print(f"{_label()} failed: {exc}", file=sys.stderr)
        if on_github:
            print(f"::error title={_label()} probe failed::{_escape(str(exc)[:500])} (after {client.calls} calls)")
        return 2
    stats = {"calls": client.calls, "cacheHits": cache.hits, "seconds": round(client.seconds, 2)}
    hint = tolerance_hint(spec, results, clean_names) if results else None
    report = {"spec": spec["id"], "model": client.model, "prompts": {n: o["prompt"] for n, o in spec["objects"].items()},
              "stats": stats, "runs": results, "tolerance": hint, "sweep": swept}
    (args.out / "probe.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if results:
        (args.out / "probe.md").write_text(markdown(spec, results, hint, client.model, stats), encoding="utf-8")
    else:
        lines = [f"# SAM prompt sweep: {sweep_name}", "", f"Calls {stats['calls']}, cache hits {stats['cacheHits']}.", "",
                 "| Prompt | " + " | ".join(r["run"] for r in swept[0]["runs"]) + " | Clean worst gap |",
                 "| --- | " + " | ".join("---" for _ in swept[0]["runs"]) + " | --- |"]
        for item in swept:
            cells = [f"{r['verdict']['result']}, found {r['objects'][sweep_name]['framesFound']}/"
                     f"{r['objects'][sweep_name]['framesProbed']}" for r in item["runs"]]
            worst = (item.get("tolerance") or {}).get("cleanWorstGap")
            lines.append(f"| {item['prompt']} | " + " | ".join(cells) + f" | {_num(worst)} |")
        (args.out / "probe.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.out / 'probe.md'}")
    if on_github:
        for line in (annotations(report) if results else sweep_annotations(swept)):
            print(line)
        if swept:
            summary = (f"model {client.model}; calls {stats['calls']}; cache hits {stats['cacheHits']}; seconds per call "
                       f"{stats['seconds'] / stats['calls']:.2f}" if stats["calls"] else "no calls")
            print(f"::notice title={_label()} probe summary::{_escape(summary)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
