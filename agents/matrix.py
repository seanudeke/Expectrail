"""Gate 2 fix matrix: does Muse Code fix each seeded bug, and does the verifier accept only real fixes?

For each public development variant (``bugs/<family>/vN.patch``) and each condition, the matrix
renders the bugged game, briefs Muse Code, and judges every candidate with the same verifier
(``agents.verifier.verify``, SAM on in the live run). Conditions (docs/evaluation.md):

  - ``screenshots``: Muse Code gets screenshots of the bugged run, the route, the run's log and
    the expected behaviour in plain English. No spec, no verdict, no evidence. Between attempts it
    learns only that the previous attempt did not fix the bug.
  - ``nightshift``: the same files, plus the repair request: the approved spec, the evaluator's
    verdict on the bugged run with its evidence and first failing frame, and the verifier's reasons
    after a rejected attempt. Nightshift only opens a repair when its own check caught the bug.

"Existing checks" (the game's build) catches none of the seeded bugs; it needs no run.

Both conditions get the same editable globs (``EDITABLE``: the player, the level and the game
scene, since dev layering v1 lives in ``game_singleplayer.tscn``), the same attempt budget and the
same verifier, and nothing in either briefing names the cause.

    python3 -m agents.matrix --list
    python3 -m agents.matrix --case dev/sinking/v2 --condition nightshift --out runs/matrix --live
    python3 -m agents.matrix --summarize runs/matrix
    NIGHTSHIFT_HELDOUT_DIR=... python3 -m agents.matrix --list --set held-out

Held-out cases (``<family>/vN`` from the private manifest) run the same way, once, after the code
freeze. What they write publicly is sanitized: ``result.json`` keeps ids, outcomes and per-attempt
decisions only; reasons, candidate patches and Muse's log stay in ``result-private.json`` and the
attempt folders on the runner, since a fix or a reason would describe the bug.

Offline (no ``--live``) the fixer is given an empty candidate, or ``--fixture-candidate`` (a known
patch, e.g. agents/fixtures/fix-collision-mask.patch for dev/physics-fall-through/v1), so the
verifier and the bookkeeping run without spending anything; offline numbers are never fix rates.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import traceback
from pathlib import Path

from agents.fixer import build_muse_prompt, run_fixer
from agents.observations import from_trace
from agents.orchestrator import build_repair_request
from agents.patchutil import sha256_file
from agents.verifier import (
    REGRESSION_SPEC, _ground_observations, held_out_set, reference_surfaces, sam_on, verify,
)
from harness.run import REPO, run as harness_run
from nightshift.contracts import digest, load, validate
from nightshift.evaluator import EVALUATOR, evaluate

FORMAT = "nightshift.fix-matrix/v0"
CONDITIONS = ("screenshots", "nightshift")
EDITABLE = ["player/**", "level/**", "game_singleplayer.tscn"]
SMOKE_ROUTE = REPO / "harness" / "routes" / "smoke.json"
ATTEMPTS = 3
# Frames shown to Muse in both conditions: chosen by position, never by the verdict, so the
# screenshots condition gets no hint of where a check failed.
SCREENSHOT_FRAMES = (0, 30, 60, 90, 119)
BRIEFING_DIR = "bug-report"
FAMILY_SPECS = {
    "physics-fall-through": REGRESSION_SPEC,
    "sinking": REGRESSION_SPEC,
    "missing-texture": REPO / "specs" / "coins-visible.json",
    "layering": REPO / "specs" / "player-always-visible.json",
}


SPEC_FILES = {
    "player-stays-above-ground": REGRESSION_SPEC,
    "coins-visible": REPO / "specs" / "coins-visible.json",
    "player-always-visible": REPO / "specs" / "player-always-visible.json",
}
SETS = ("dev", "held-out")
PUBLIC_KEYS = ("format", "case", "condition", "live", "sam", "private", "detected", "outcome", "attemptsUsed",
               "wallClockSeconds")


def dev_variants() -> dict[str, Path]:
    """The public development variants, ``dev/<family>/vN`` -> patch (the ids the detection
    benchmark uses for the same patches)."""
    return {f"dev/{p.parent.name}/{p.stem}": p for p in sorted((REPO / "bugs").glob("*/v*.patch"))}


def case_spec(key: str) -> dict:
    family = key.split("/")[1]
    if family not in FAMILY_SPECS:
        raise SystemExit(f"{key}: no spec mapped for family {family!r}")
    return load(FAMILY_SPECS[family], "test-spec")


def heldout_cases() -> dict[str, tuple[Path, Path]]:
    """Active private variants, ``<family>/vN`` -> (patch, spec file). Never prints a description."""
    root, manifest, problem = held_out_set()
    if manifest is None:
        raise SystemExit(f"held-out set unavailable: {problem or 'NIGHTSHIFT_HELDOUT_DIR is not set'}")
    cases: dict[str, tuple[Path, Path]] = {}
    for v in manifest.get("variants") or []:
        if v.get("retired"):
            continue
        key = f"{v['family']}/{v['id']}"
        if v.get("spec") not in SPEC_FILES:
            raise SystemExit(f"{key}: its spec is not one the matrix knows")
        cases[key] = (root / v["patch"], SPEC_FILES[v["spec"]])
    return cases


def resolve_case(key: str) -> tuple[Path, dict, bool]:
    """(patch, spec, private) for a development id (``dev/...``) or an active held-out id."""
    if key.startswith("dev/"):
        dev = dev_variants()
        if key not in dev:
            raise SystemExit(f"{key}: no such development variant under bugs/")
        return dev[key], case_spec(key), False
    held = heldout_cases()
    if key not in held:
        raise SystemExit(f"{key}: not an active held-out variant")
    patch, spec_path = held[key]
    return patch, load(spec_path, "test-spec"), True


def _frame_files(frames_dir: Path) -> list[Path]:
    return sorted(frames_dir.glob("*.png"))


def detect(patch: Path, spec: dict, out: Path, *, use_sam: bool, reference: list | None) -> dict:
    """Render the bugged game on the smoke route and judge the case's spec, as Nightshift would.

    Returns the verdict (contract ``verdict``), the frames directory and the bugged trace path.
    A spec only SAM can judge is needs-review with SAM off: Nightshift cannot see that bug then.
    """
    run_dir = out / "bugged"
    harness_run(SMOKE_ROUTE, run_dir, patches=[patch])
    trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
    replay_sha = sha256_file(run_dir / "replay.json")
    frames = run_dir / "frames"
    if spec["id"] == load(REGRESSION_SPEC, "test-spec")["id"]:
        obs, _source = _ground_observations(spec, trace, replay_sha, frames, use_sam, reference)
        verdict = evaluate(spec, obs)
    elif use_sam:
        obs = from_trace(trace, replay_sha256=replay_sha, frames_dir=str(frames), spec=spec, provider="sam")
        verdict = evaluate(spec, obs)
    else:
        verdict = {"format": "nightshift.verdict/v0", "spec": {"id": spec["id"], "sha256": digest(spec)},
                   "observations": {"sha256": "0" * 64}, "result": "needs-review",
                   "reason": f"{spec['id']} needs SAM, and SAM is off", "firstFrame": None, "evidence": [],
                   "framesJudged": 0, "evaluator": dict(EVALUATOR)}
    validate(verdict, "verdict")
    (out / "detection.json").write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
    return {"spec": spec, "verdict": verdict, "frames": frames, "runDir": run_dir}


def briefing_files(detection: dict, out: Path) -> dict[str, Path]:
    """The files both conditions get: screenshots, the route and the bugged run's log."""
    frames = _frame_files(detection["frames"])
    files: dict[str, Path] = {}
    for n in SCREENSHOT_FRAMES:
        if n < len(frames):
            files[f"{BRIEFING_DIR}/screenshots/frame-{n:03d}.png"] = frames[n]
    files[f"{BRIEFING_DIR}/route.json"] = SMOKE_ROUTE
    log = detection["runDir"] / "godot.log"
    if log.is_file():
        files[f"{BRIEFING_DIR}/godot.log"] = log
    return files


def _rules(attempt: int) -> str:
    return f"""## Rules
- Only edit files matching these globs (relative to the workspace root): {", ".join(EDITABLE)}
- Do not edit anything under {BRIEFING_DIR}/, and do not create files outside those globs.
- Produce the smallest correct fix. When done, leave the game files edited; do not commit.

Attempt {attempt} of {ATTEMPTS}."""


def screenshots_prompt(spec: dict, files: dict[str, Path], attempt: int, prior: bool) -> str:
    shots = sorted(f for f in files if "/screenshots/" in f)
    again = ("\n\nYour previous attempt did not fix the bug. Look again." if prior else "")
    return f"""You are fixing a bug in a Godot 4 2D platformer.

## Bug report
A player ran the route in {BRIEFING_DIR}/route.json and reports that this no longer holds:
"{spec["instruction"]}"

Screenshots of the broken game on that route: {", ".join(shots)}
(frames {", ".join(str(n) for n in SCREENSHOT_FRAMES)} of 120). Open and look at each one. The game's
log from that run is {BRIEFING_DIR}/godot.log.{again}

{_rules(attempt)}
"""


def nightshift_prompt(request: dict, files: dict[str, Path], attempt: int) -> str:
    shots = sorted(f for f in files if "/screenshots/" in f)
    base = build_muse_prompt(request, rr_relpath="repair-request.json", attempt=attempt)
    return (base + f"\nScreenshots of the failing run (open and look at each one): {', '.join(shots)}; "
            f"route and log in {BRIEFING_DIR}/. Do not edit anything under {BRIEFING_DIR}/.\n")


def run_case(key: str, condition: str, out: Path, *, live: bool, use_sam: bool | None = None,
             fixture: Path | None = None, require_sandbox: bool = False) -> dict:
    """One case under one condition: detect, brief, up to ATTEMPTS fixes, each verified."""
    if condition not in CONDITIONS:
        raise SystemExit(f"unknown condition {condition!r}")
    patch, spec, private = resolve_case(key)
    use_sam = sam_on() if use_sam is None else use_sam
    work = out / key.replace("/", "_") / condition
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    row: dict = {"case": key, "condition": condition, "live": live, "sam": use_sam, "private": private,
                 "attempts": []}
    try:
        reference = reference_surfaces(work)
        detection = detect(patch, spec, work, use_sam=use_sam, reference=reference)
        verdict = detection["verdict"]
        row["detected"] = verdict["result"]
        if condition == "nightshift" and verdict["result"] != "fail":
            row.update(outcome="not-detected", detail=f"Nightshift's check did not catch it: {verdict['reason']}")
            return _finish(row, work, t0)
        files = briefing_files(detection, work)
        request = build_repair_request(
            request_id=f"rr-matrix-{key.replace('/', '-')}-{condition}",
            spec=detection["spec"], verdict=verdict, route=load(SMOKE_ROUTE, "route"),
            base_patch=str(patch.relative_to(REPO)) if patch.is_relative_to(REPO) else str(patch),
            editable=EDITABLE,
            key_frames=[f for f in files if "/screenshots/" in f], attempts=ATTEMPTS,
        )
        (work / "repair-request.json").write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
        prior: dict | None = None
        offline_patch = fixture
        if offline_patch is None:
            offline_patch = work / "empty.patch"
            offline_patch.write_text("", encoding="utf-8")
        for attempt in range(1, ATTEMPTS + 1):
            attempt_out = work / f"attempt-{attempt:02d}"
            if condition == "screenshots":
                briefing = {"prompt": screenshots_prompt(detection["spec"], files, attempt, prior is not None),
                            "policy": "matrix-screenshots-v1", "files": files, "withRequest": False}
                feedback = {"attempt": attempt - 1, "decision": "reject"} if prior else None
            else:
                briefing = {"prompt": nightshift_prompt(request, files, attempt),
                            "policy": "matrix-nightshift-v1", "files": files, "withRequest": True}
                feedback = prior
            meta = run_fixer(request, attempt_out, candidate_patch=None if live else offline_patch,
                             attempt=attempt, allow_empty=True, prior_reject=feedback, briefing=briefing,
                             require_sandbox=require_sandbox)
            film = {"attempt": attempt, "source": meta.get("source"), "empty": meta.get("empty", False),
                    "patchSha256": meta.get("patchSha256")}
            row["attempts"].append(film)
            candidate = attempt_out / "candidate.patch"
            if meta.get("empty") or not candidate.read_text(encoding="utf-8").strip():
                film["decision"] = "empty"
                prior = {"decision": "reject", "reasons": ["the attempt changed no editable file"],
                         "attempt": attempt}
                if not live:
                    break  # offline the candidate never changes; one attempt shows the path
                continue
            v = verify(request, candidate, work / "verify" / f"attempt-{attempt:02d}", attempt=attempt)
            film["decision"] = v["decision"]
            film["reasons"] = v.get("reasons")
            film["checks"] = {f"{c['kind']}:{c['spec']}": c["result"] for c in v.get("checks", [])}
            if v["decision"] == "accept" or not live:
                break
            prior = {"decision": v["decision"], "reasons": v.get("reasons"), "attempt": attempt}
        decisions = [a.get("decision") for a in row["attempts"]]
        row["outcome"] = ("fixed" if "accept" in decisions
                          else "needs-review" if "needs-review" in decisions else "not-fixed")
        return _finish(row, work, t0)
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - a crash is recorded, never counted as a fix
        (work / "matrix-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        row.update(outcome="error", detail=f"{type(exc).__name__}: {exc}"[:300])
        return _finish(row, work, t0)


def _finish(row: dict, work: Path, t0: float) -> dict:
    row["format"] = FORMAT
    row["wallClockSeconds"] = round(time.perf_counter() - t0, 1)
    row["attemptsUsed"] = len(row["attempts"])
    if row.get("private"):
        # The full row (reasons, checks, error detail) can describe a private bug: it stays here.
        (work / "result-private.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
        row = public_row(row)
    (work / "result.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    return row


def public_row(row: dict) -> dict:
    """What may leave the runner for a private case: ids, outcomes and per-attempt decisions."""
    out = {k: row[k] for k in PUBLIC_KEYS if k in row}
    out["attempts"] = [{"attempt": a.get("attempt"), "decision": a.get("decision"), "empty": a.get("empty", False)}
                       for a in row.get("attempts", [])]
    return out


def summarize(out: Path) -> dict:
    """Every result.json under ``out``, as one table per condition."""
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.rglob("result.json"))]
    rows = [r for r in rows if r.get("format") == FORMAT]
    by_condition: dict[str, dict] = {}
    for c in CONDITIONS:
        mine = [r for r in rows if r["condition"] == c]
        by_condition[c] = {
            "cases": len(mine),
            "fixed": sum(r["outcome"] == "fixed" for r in mine),
            "notFixed": sum(r["outcome"] == "not-fixed" for r in mine),
            "notDetected": sum(r["outcome"] == "not-detected" for r in mine),
            "needsReview": sum(r["outcome"] == "needs-review" for r in mine),
            "errors": sum(r["outcome"] == "error" for r in mine),
            "attempts": sum(r.get("attemptsUsed", 0) for r in mine),
            "live": all(r.get("live") for r in mine) if mine else None,
        }
    doc = {"format": FORMAT + "-summary", "conditions": by_condition,
           "rows": [{k: r.get(k) for k in ("case", "condition", "detected", "outcome", "attemptsUsed",
                                           "wallClockSeconds", "live", "detail")} for r in rows]}
    (out / "matrix-summary.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def markdown(doc: dict) -> str:
    lines = ["| Case | Condition | Detected | Outcome | Attempts | Seconds |", "| --- | --- | --- | --- | --- | --- |"]
    for r in doc["rows"]:
        lines.append(f"| {r['case']} | {r['condition']} | {r.get('detected')} | {r['outcome']} | "
                     f"{r.get('attemptsUsed')} | {r.get('wallClockSeconds')} |")
    lines.append("")
    for c, s in doc["conditions"].items():
        lines.append(f"- **{c}**: fixed {s['fixed']} of {s['cases']}; not fixed {s['notFixed']}; "
                     f"not detected {s['notDetected']}; needs review {s['needsReview']}; errors {s['errors']}; "
                     f"{s['attempts']} attempts; live={s['live']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    from agents.keys import load_dotenv
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="print the case ids of one set as JSON")
    g.add_argument("--case", help="dev/<family>/vN, or <family>/vN for an active held-out variant")
    g.add_argument("--summarize", type=Path, help="build matrix-summary.json and print a table")
    p.add_argument("--condition", choices=CONDITIONS)
    p.add_argument("--set", choices=SETS, default="dev", dest="which", help="with --list")
    p.add_argument("--out", type=Path, default=REPO / "runs" / "matrix")
    p.add_argument("--live", action="store_true", help="run Muse Code (spends Meta credit)")
    p.add_argument("--fixture-candidate", type=Path, help="offline: verify this patch instead of an empty one")
    p.add_argument("--require-sandbox", action="store_true",
                   help="refuse to run Muse Code outside bubblewrap (CI: the verifier's private set is on disk)")
    args = p.parse_args(argv)
    if args.list:
        print(json.dumps(sorted(dev_variants()) if args.which == "dev" else sorted(heldout_cases())))
        return 0
    if args.summarize:
        print(markdown(summarize(args.summarize)))
        return 0
    if not args.condition:
        p.error("--case needs --condition")
    if args.live:
        from agents.keys import muse_code_ready, require_separate_sam_key
        if not muse_code_ready():
            raise SystemExit("--live needs muse on PATH and META_API_KEY")
        if sam_on():
            require_separate_sam_key()
    if args.live and args.fixture_candidate:
        p.error("--fixture-candidate is for offline runs")
    row = run_case(args.case, args.condition, args.out, live=args.live, fixture=args.fixture_candidate,
                   require_sandbox=args.require_sandbox)
    print(json.dumps({k: row.get(k) for k in ("case", "condition", "detected", "outcome", "attemptsUsed",
                                              "wallClockSeconds", "detail")}))
    return 1 if row["outcome"] == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
