"""Detection bench for the second domain, a web checkout page: would the verifier catch each bug?

The game's held-out bench (agents/heldout_bench.py), on a web app. For the clean page and each seeded
bug, every route is replayed in Chromium (harness/web) and every check is judged by the same
evaluator, on the same kind of evidence:

- ``layout``: every spec in apps/checkout/specs judged on the page's layout log (the game's
  ``engine`` check: what the layout says, as the engine's position log says where the robot is);
- ``behaviour``: the shopper's checkout click went through and the order was submitted (the game's
  ``gameplay`` check);
- with SAM on, each spec whose objects SAM can see judged on SAM 3.1's view of the frames, and
  ``hybrid``: the inside-the-form spec judged on SAM's box for the button against the form's layout
  box (the game's hybrid ground check: SAM's robot box against the engine's ground line).

The output and its annotation are the held-out bench's, so ``agents.bench_collect`` records a run
unchanged. Development variants are apps/checkout/bugs/<family>/vN.patch; held-out variants come
from ``$EXPECTRAIL_HELDOUT_DIR/web/manifest.json`` (patches only, ids and counts printed, nothing
else).

    python3 -m agents.web_bench --list --set dev
    python3 -m agents.web_bench --variant dev/layering/v1 --out runs/web-bench
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from agents.heldout_bench import CLEAN, DEV_PREFIX, RESULTS, annotation, caught, public_error
from expectrail.contracts import load
from expectrail.evaluator import evaluate
from harness.run import REPO
from harness.web import layout
from harness.web.run import WebHarnessError, run as web_run

APP = REPO / "apps" / "checkout"
ROUTES = sorted((REPO / "harness" / "web" / "routes").glob("*.json"))
SPECS = sorted((APP / "specs").glob("*.json"))
HYBRID_SPEC = "checkout-button-inside-form"
SAM_ON_CHECKS = ("hybrid", "behaviour")  # plus every SAM spec
SAM_OFF_CHECKS = ("layout", "behaviour")
ERRORS_FILE = "bench-errors.json"


def dev_variants() -> dict[str, Path]:
    return {f"{DEV_PREFIX}{p.parent.name}/{p.stem}": p for p in sorted((APP / "bugs").glob("*/v*.patch"))}


def held_out() -> tuple[Path | None, dict | None]:
    raw = os.environ.get("EXPECTRAIL_HELDOUT_DIR", "").strip()
    if not raw:
        return None, None
    root = Path(raw) / "web"
    manifest = root / "manifest.json"
    if not manifest.is_file():
        return root, None
    return root, json.loads(manifest.read_text(encoding="utf-8"))


def held_out_variants() -> dict[str, Path]:
    root, manifest = held_out()
    if manifest is None:
        return {}
    return {f"{v['family']}/{v['id']}": root / v["patch"] for v in manifest.get("variants") or []
            if not v.get("retired")}


def set_ids(which: str) -> list[str]:
    return [CLEAN] + sorted(dev_variants() if which == "dev" else held_out_variants())


def sam_on() -> bool:
    return os.environ.get("EXPECTRAIL_OBS_PROVIDER", "trace").strip().lower() == "sam"


def worst(results: list[str]) -> str:
    return "fail" if "fail" in results else "needs-review" if "needs-review" in results else "pass"


def sam_visible(spec: dict) -> bool:
    """A spec SAM judges on its own: every object it names is one SAM is asked to find."""
    return spec["id"] != HYBRID_SPEC


def judge_route(route: Path, patches: list[Path], run_dir: Path, specs: list[dict], use_sam: bool) -> dict[str, str]:
    names = ["layout", "behaviour"] + (["hybrid"] + [s["id"] for s in specs if sam_visible(s)] if use_sam else [])
    try:
        web_run(route, run_dir, patches)
        trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
        replay_sha = __import__("hashlib").sha256((run_dir / "replay.json").read_bytes()).hexdigest()
    except (WebHarnessError, OSError, ValueError) as exc:
        (run_dir / "bench-error.txt").write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        return {n: "needs-review" for n in names}
    results: dict[str, str] = {}
    errors: list[str] = []
    verdicts = {}
    for spec in specs:
        verdicts[spec["id"]] = evaluate(spec, layout.layout_observations(trace, spec, replay_sha))
    results["layout"] = worst([v["result"] for v in verdicts.values()])
    results["behaviour"] = layout.behaviour(trace)["result"]
    if use_sam:
        from agents.sam_observations import SamError, from_replay

        for spec in specs:
            key = "hybrid" if not sam_visible(spec) else spec["id"]
            engine = {n for n, o in spec["objects"].items() if n == "form"}
            try:
                obs = from_replay(trace, replay_sha, frames_dir=run_dir / "frames", spec=spec,
                                  engine_objects=layout.engine_objects(trace, sorted(engine)) if engine else None)
                verdict = evaluate(spec, obs)
                results[key] = verdict["result"]
                (run_dir / f"sam-{spec['id']}.json").write_text(json.dumps(obs, indent=1) + "\n", encoding="utf-8")
                (run_dir / f"verdict-sam-{spec['id']}.json").write_text(json.dumps(verdict, indent=1) + "\n",
                                                                        encoding="utf-8")
            except SamError as exc:
                results[key] = "needs-review"
                errors.append(f"{key}: {exc}")
    for spec_id, verdict in verdicts.items():
        (run_dir / f"verdict-layout-{spec_id}.json").write_text(json.dumps(verdict, indent=1) + "\n", encoding="utf-8")
    if errors:
        (run_dir / ERRORS_FILE).write_text(json.dumps(errors, indent=2) + "\n", encoding="utf-8")
    return results


def bench(key: str, out: Path) -> dict:
    dev, held = dev_variants(), held_out_variants()
    if key == CLEAN:
        patches: list[Path] = []
    elif key in dev:
        patches = [dev[key]]
    elif key in held:
        patches = [held[key]]
    else:
        raise SystemExit(f"{key}: no such web variant")
    use_sam = sam_on()
    specs = [load(p, "test-spec") for p in SPECS]
    from agents.sam_observations import sam_images_since, sam_usage

    before = sam_usage()
    work = out / key.replace("/", "_")
    per_route = [{"route": r.stem, "checks": judge_route(r, patches, work / r.stem, specs, use_sam)} for r in ROUTES]
    errors: list[str] = []
    for row in per_route:
        path = work / row["route"] / ERRORS_FILE
        if path.is_file():
            for message in json.loads(path.read_text(encoding="utf-8")):
                if public_error(message) not in errors:
                    errors.append(public_error(message))
    names = list(per_route[0]["checks"])
    per_check = {c: {r: sum(row["checks"].get(c) == r for row in per_route) for r in RESULTS} for c in names}
    sam_checks = list(SAM_ON_CHECKS) + [s["id"] for s in specs if sam_visible(s)]
    doc = {"format": "expectrail.web-bench/v0", "variant": key, "app": "checkout", "sam": use_sam, "judge": "sam" if use_sam else "layout",
           "routes": len(per_route), "checks": per_check,
           "caughtWithSamOn": caught(per_check, sam_checks) if use_sam else None,
           "caughtWithGlimmerEngine": None,
           "caughtWithSamOff": caught(per_check, list(SAM_OFF_CHECKS)),
           "errors": errors[:5], "samImages": sam_images_since(before), "perRoute": per_route}
    work.mkdir(parents=True, exist_ok=True)
    (work / "bench.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--list", action="store_true", help="print the variant ids of --set as JSON")
    p.add_argument("--set", choices=("dev", "held-out"), default="dev")
    p.add_argument("--variant", help="clean, dev/<family>/vN or a held-out <family>/<id>")
    p.add_argument("--out", type=Path, default=REPO / "runs" / "web-bench")
    args = p.parse_args(argv)
    if args.list:
        print(json.dumps(set_ids(args.set)))
        return 0
    if not args.variant:
        p.error("--variant or --list")
    start = time.monotonic()
    doc = bench(args.variant, args.out)
    print(annotation(doc))
    print(f"::notice title=Bench time {args.variant}::{round(time.monotonic() - start)} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
