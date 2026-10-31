"""Mutation bench (#127): how much does the tiered checker catch, and what does it miss?

Two kinds of case, judged the same way, on public checks only. This job never sets
EXPECTRAIL_HELDOUT_DIR and never checks out the private set.

  - wrong fix (Part 1): the exact undo of a development bug with one operator stacked on it (hide,
    sink, freeze, scale-to-zero, behind-scenery, comment-only);
  - generated mutant (Part 2): one edit of the clean game from agents/mutate_game.py, judged as the
    seed of a request with an empty candidate, so the verifier's editable-file gate never judges it.

The tier: the checks with SAM off first, and a cheap rejection is final; SAM looks only at what the
cheap tier would accept. ``--force-sam`` also asks SAM about a cheap rejection, for the agreement
table (#129 item 1). This tier is this bench's policy: the verifier itself runs SAM on every candidate.

Every case ends in exactly one outcome, and only a rejection is a catch:

  caught-cheap, caught-sam  a check ran to completion and failed
  survived                  every public check passed (a finding, published with its catch-spec)
  undecided                 a check needs review, SAM did not answer, or a control is not to be trusted
  crash                     the case's own game failed to load or run, twice
  error                     the tooling failed; this says nothing about the case
  awaiting-sam              a mutant the cheap phase passed, before its SAM phase

Public decision: the verifier's held-out arm is left out. Without the private set it is a constant
fixture with SAM off and a forced needs-review with SAM on, so counting it would make every SAM-off
survivor look caught and make a finding impossible. Nothing here changes what the verifier decides.

Nothing is judged until bench/mutation/preregistration.json is complete, and every result names it.

    python3 -m agents.mutation_bench --list
    python3 -m agents.mutation_bench --case dev/sinking/v2 --operator hide --out runs/mutation [--force-sam]
    python3 -m agents.mutation_bench --mutant "<id>" --tier cheap --out runs/generated
    python3 -m agents.mutation_bench --mutant "<id>" --tier sam --out runs/generated [--force-sam]
    python3 -m agents.mutation_bench --plan-sam runs/generated
    python3 -m agents.mutation_bench --summarize runs/mutation

Rehearsals need no pre-registration, run on any branch, and are never a result:

    python3 -m agents.mutation_bench --dry-run --out runs/dry           # one known pair, no SAM
    python3 -m agents.mutation_bench --dry-run sam --out runs/dry       # the same pair through forced SAM (spends SAM)
    python3 -m agents.mutation_bench --dry-run mutants --out runs/dry   # two mutants through the cheap phase, no SAM

To report both phases of Part 2 together, download each run's artifacts into its own folder under one
parent and summarize the parent: a mutant judged in both phases counts once, as its SAM phase.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

from agents import mutate_game, sam_health, trace_checks
from agents.judge_bench import provider, undo_patch
from agents.matrix import EDITABLE, SMOKE_ROUTE, case_spec, dev_variants
from agents.orchestrator import build_repair_request
from agents.sam_observations import sam_images_since, sam_usage
from agents.verifier import REGRESSION_SPEC, verify
from expectrail.contracts import digest, load
from expectrail.evaluator import EVALUATOR
from harness.run import REPO, apply_patches
from harness.run import run as harness_run

FORMAT = "expectrail.mutation-bench/v0"
OPERATORS_DIR = REPO / "agents" / "fixtures" / "operators"
CATCH_DIR = REPO / "agents" / "fixtures" / "catch-specs"
GAME = REPO / "game" / "platformer"
HELDOUT_ENV = "EXPECTRAIL_HELDOUT_DIR"
MANIFEST = REPO / "bench" / "mutation" / "generated" / "manifest.json"

OPERATORS = ("hide", "sink", "freeze", "scale-to-zero", "behind-scenery", "comment-only")
OUTCOMES = ("caught-cheap", "caught-sam", "survived", "undecided", "crash", "error", "awaiting-sam")
CAUGHT = ("caught-cheap", "caught-sam")
GROUND_SPEC = "player-stays-above-ground"
DRY_RUN = ("dev/physics-fall-through/v1", "freeze")
# Stand-ins for a rehearsal, so the mutant path runs for real before anything is registered. They
# are not the pre-registered steps or thresholds, and nothing rehearsed is ever recorded as a result.
DRY_PREREG = {"sha256": None, "wrongFix": {"commentOnlyLabel": None},
              "oracle": {"traceThresholdPx": 0, "frameThreshold": 0}}
DRY_PARAMS = {"positionStep": 1, "offsetStep": 1, "scaleStep": 1, "zIndexStep": 1, "constantScale": 2,
              "collisionBits": 1}

# Spec that would catch the operator when public checks miss it (finding publish target).
CATCH_SPECS = {
    "hide": REPO / "specs" / "player-always-visible.json",
    "sink": REPO / "specs" / "player-stays-above-ground.json",
    "freeze": CATCH_DIR / "player-motion-required.json",
    "scale-to-zero": REPO / "specs" / "player-always-visible.json",
    "behind-scenery": REPO / "specs" / "player-always-visible.json",
    "comment-only": CATCH_DIR / "comment-only-delta.json",
}
# Freeze is caught by the gameplay check in the verifier suite, not a visual spec file.
CATCH_NOTES = {
    "freeze": "public gameplay check player-motion-on-smoke (SAM off is enough when motion is gone)",
    "comment-only": "proposed process check: candidate must change non-comment tokens",
}


class CaseCrashed(Exception):
    """The case's own game failed to load or run, on both tries."""


def operator_path(name: str) -> Path:
    path = OPERATORS_DIR / f"{name}.patch"
    if not path.is_file():
        raise SystemExit(f"unknown operator {name!r}: expected {path}")
    return path


def catch_spec_for(operator: str) -> dict:
    path = CATCH_SPECS[operator]
    if path.parent == CATCH_DIR:
        return json.loads(path.read_text(encoding="utf-8"))
    return load(path, "test-spec")


def pairs() -> list[tuple[str, str]]:
    return [(case, op) for case in sorted(dev_variants()) for op in OPERATORS]


def _diff_trees(before: Path, after: Path, rels: list[str]) -> str:
    chunks = []
    for rel in rels:
        a, b = before / rel, after / rel
        if not a.is_file() and not b.is_file():
            continue
        if a.is_file() and b.is_file() and a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8"):
            continue
        r = subprocess.run(["diff", "-u", str(a), str(b)], capture_output=True, text=True)
        fixed = []
        for line in r.stdout.splitlines(True):
            if line.startswith("--- "):
                fixed.append(f"--- a/{rel}\n")
            elif line.startswith("+++ "):
                fixed.append(f"+++ b/{rel}\n")
            else:
                fixed.append(line)
        chunks.append("".join(fixed))
    return "".join(chunks)


def build_candidate(bug: Path, operator: Path, out: Path) -> Path:
    """One candidate: the correct undo of ``bug``, then ``operator``, as a single patch on the bugged tree."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bugged = root / "bugged"
        mutant = root / "mutant"
        shutil.copytree(GAME, bugged, ignore=shutil.ignore_patterns(".godot"))
        shutil.copytree(GAME, mutant, ignore=shutil.ignore_patterns(".godot"))
        apply_patches(bugged, [bug])
        apply_patches(mutant, [bug])
        undo = undo_patch(bug, root / "undo.patch")
        apply_patches(mutant, [undo, operator])
        rels = sorted({line[6:].strip() for patch in (undo, operator)
                       for line in patch.read_text(encoding="utf-8").splitlines()
                       if line.startswith("+++ b/")})
        text = _diff_trees(bugged, mutant, rels)
    out.write_text(text, encoding="utf-8")
    return out


def _public_only() -> None:
    """Refuse to run with the private set mounted: this bench is public checks only."""
    if os.environ.get(HELDOUT_ENV, "").strip():
        raise SystemExit(f"{HELDOUT_ENV} is set; mutation_bench is public checks only — unset it")


def public_decision(verification: dict) -> str:
    """The verifier's decision on its public checks: accept, reject or needs-review (see the docstring).

    A rejection needs a check that ran and failed. A candidate turned back at the verifier's door
    (the editable-file or base-tree gate) judged nothing, so it is needs-review here, never a catch.
    A clean control says nothing about the case: one that did not come from a real replay of the
    clean game, or that did not pass there, means the judge cannot be trusted on this run. It is
    needs-review, never a catch, whatever the case's own checks said.
    """
    suite = verification.get("suite") or {}
    if suite.get("earlyReject"):
        return "needs-review"
    if (suite.get("clean") or {}).get("source") != "harness":
        return "needs-review"
    checks = [c for c in verification.get("checks") or [] if c.get("kind") != "held-out"]
    if not checks or any(c["result"] != "pass" for c in checks if c.get("kind") == "clean"):
        return "needs-review"
    if any(c["result"] == "fail" for c in checks):
        return "reject"
    return "needs-review" if any(c["result"] != "pass" for c in checks) else "accept"


def own_results(verification: dict) -> dict[str, str]:
    """What SAM alone said about this game, spec by spec. The ground check is left out as well as
    gameplay and the controls: its line comes from the engine, so it would agree with the engine."""
    return {c["spec"]: c["result"] for c in verification.get("checks") or []
            if c.get("kind") == "regression" and c.get("spec") != GROUND_SPEC}


def failed_checks(verification: dict) -> list[str]:
    """Which public checks failed on the case, for "which checks catch what"."""
    return sorted({f"{c['kind']}/{c['spec']}" for c in verification.get("checks") or []
                   if c.get("result") == "fail" and c.get("kind") not in ("held-out", "clean")})


def agreement(cheap_caught: bool, sam_arm: dict | None) -> str | None:
    """Does SAM, on its own checks, back a cheap rejection? A disagreement is a finding about the
    tier: SAM could never have overturned that rejection."""
    if not cheap_caught or sam_arm is None:
        return None
    results = list(sam_arm["ownResults"].values())
    if "fail" in results:
        return "agree"
    return "disagree" if results and all(r == "pass" for r in results) else "undecided"


def _replay_failed(exc: BaseException) -> bool:
    """True when the case's own replay is what failed: not the clean game's, and not the tooling's.
    A Godot import that fails is the game failing to load; a patch that fails is the tooling."""
    text = str(exc)
    if "level-reference" in text or "clean-replay" in text:
        return False
    if isinstance(exc, subprocess.CalledProcessError):
        return "--import" in exc.cmd
    return isinstance(exc, SystemExit) and text.startswith("godot ")


def _arm(request: dict, candidate: Path, out: Path, name: str, prov: str) -> dict:
    """One tier's verification. A replay that fails is tried once more, and the retry is recorded;
    a flake must not read as a crashing case. Failing twice raises CaseCrashed."""
    before = sam_usage()
    doc: dict = {"provider": prov, "retried": False}
    for attempt in (1, 2):
        try:
            with provider(prov):
                verification = verify(request, candidate, out / (name if attempt == 1 else f"{name}-retry"))
            break
        except (SystemExit, subprocess.CalledProcessError) as exc:
            if not _replay_failed(exc):
                raise
            if attempt == 2:
                raise CaseCrashed(str(exc)[:300]) from exc
            doc["retried"] = True
    doc.update(
        decision=public_decision(verification),
        verifierDecision=verification.get("decision"),
        reasons=list(dict.fromkeys(r.split(" on ")[0] for r in verification.get("reasons") or []
                                   if "held-out" not in r))[:6],
        ownResults=own_results(verification),
        failedChecks=failed_checks(verification),
        cleanSource=((verification.get("suite") or {}).get("clean") or {}).get("source"),
        samImages=sam_images_since(before),
    )
    return doc


def judge_tiers(request: dict, candidate: Path, work: Path, row: dict, *, force_sam: bool = False,
                cheap: dict | None = None, extra_catch: bool = False, cheap_only: bool = False) -> None:
    """The tier, on one case. Writes the outcome into ``row``. A cheap replay that fails raises
    CaseCrashed. Once the cheap tier has answered, a failure in the SAM arm never erases that answer.

    ``cheap`` is a cheap arm already judged, and ``extra_catch`` a cheap check outside the verifier
    that failed (the engine-record checks).
    """
    arms = row.setdefault("arms", {})
    cheap = cheap or _arm(request, candidate, work, "sam-off", "trace")
    arms["cheap"] = cheap
    caught = cheap["decision"] == "reject" or extra_catch
    row["cheapDecision"] = cheap["decision"]
    if caught:
        row["outcome"] = "caught-cheap"
    elif cheap["decision"] != "accept":
        row["outcome"] = "undecided"
        row["undecidedWhy"] = "the cheap tier could not decide"
    if cheap_only and not row.get("outcome"):
        row["outcome"] = "awaiting-sam"
    if cheap_only or (row.get("outcome") and not (caught and force_sam)):
        return
    with provider("sam"):
        problem = sam_health.check()
    if problem is not None:
        row["samPreflight"] = problem
        if not caught:
            row["outcome"] = "undecided"
            row["undecidedWhy"] = sam_health.reason(problem)
        return
    try:
        sam = _arm(request, candidate, work, "sam-on", "sam")
    except CaseCrashed as exc:
        # The cheap replay of this same game ran, so a dead SAM replay is not the case's own crash.
        row["samArmFailed"] = str(exc)[:300]
        if not caught:
            row["outcome"] = "undecided"
            row["undecidedWhy"] = "the SAM arm's replay failed twice, though the cheap arm's ran"
        return
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        if not caught:
            raise
        row["samArmFailed"] = f"{type(exc).__name__}: {exc}"[:300]
        return
    arms["sam"] = sam
    row["agreement"] = agreement(caught, sam)
    if caught:
        return
    if sam["decision"] == "reject":
        row["outcome"] = "caught-sam"
    elif sam["decision"] == "accept":
        row["outcome"] = "survived"
    else:
        row["outcome"] = "undecided"
        row["undecidedWhy"] = "SAM's checks did not all answer"


def _finish(row: dict, work: Path, t0: float, images: dict) -> dict:
    row.setdefault("outcome", "error")
    # A good case that passes is the checker being right, not a miss.
    row["finding"] = row["outcome"] == "survived" and row.get("label") == "bad"
    row["caught"] = {"caught-cheap": "sam-off", "caught-sam": "sam-on"}.get(row["outcome"])
    row["samImages"] = sam_images_since(images)
    row["wallClockSeconds"] = round(time.perf_counter() - t0, 1)
    (work / "result.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    return row


def _request(request_id: str, spec: dict, base_patch: str) -> dict:
    verdict = {
        "format": "expectrail.verdict/v0",
        "spec": {"id": spec["id"], "sha256": digest(spec)},
        "observations": {"sha256": "0" * 64}, "result": "fail", "reason": "seeded bug",
        "firstFrame": None, "evidence": [], "framesJudged": 0, "evaluator": dict(EVALUATOR),
    }
    return build_repair_request(request_id=request_id, spec=spec, verdict=verdict, route=load(SMOKE_ROUTE, "route"),
                                base_patch=base_patch, editable=EDITABLE, attempts=1)


def _record_failure(row: dict, work: Path, exc: BaseException) -> None:
    (work / "mutation-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    row["outcome"] = "crash" if isinstance(exc, CaseCrashed) else "error"
    row["error"] = f"{type(exc).__name__}: {exc}"[:300]


def run_case(case: str, operator: str, out: Path, *, prereg: dict | None = None, force_sam: bool = False,
             cheap_only: bool = False) -> dict:
    """Correct fix + operator, through the tier. A survivor is a finding, not a failure."""
    _public_only()
    if case not in dev_variants():
        raise SystemExit(f"{case}: not a public development variant")
    if operator not in OPERATORS:
        raise SystemExit(f"{operator}: unknown operator (want {', '.join(OPERATORS)})")
    prereg = prereg or mutate_game.load_preregistration()
    work = out / f"{case.replace('/', '_')}+{operator}"
    work.mkdir(parents=True, exist_ok=True)
    t0, images = time.perf_counter(), sam_usage()
    bug = dev_variants()[case]
    row: dict = {
        "format": FORMAT, "kind": "wrong-fix", "case": case, "operator": operator, "bug": case,
        "label": prereg["wrongFix"]["commentOnlyLabel"] if operator == "comment-only" else "bad",
        "preregistrationSha256": prereg["sha256"], "commit": os.environ.get("GITHUB_SHA"),
    }
    try:
        candidate = build_candidate(bug, operator_path(operator), work / "candidate.patch")
        shutil.copyfile(operator_path(operator), work / "operator.patch")
        row["noop"] = not candidate.read_text(encoding="utf-8").strip()  # the operator re-creates the bug
        request = _request(f"rr-mutation-{case.replace('/', '-')}-{operator}", case_spec(case),
                           str(bug.relative_to(REPO)))
        judge_tiers(request, candidate, work, row, force_sam=force_sam, cheap_only=cheap_only)
        if row.get("outcome") == "survived" and row["label"] == "bad":
            _write_finding(work, row, operator)
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        _record_failure(row, work, exc)
    _finish(row, work, t0, images)
    if row["caught"]:
        print(f"::notice title=Mutation caught {case} {operator}::caught with {row['caught']}")
    return row


def _write_finding(work: Path, row: dict, operator: str | None) -> None:
    finding: dict = {"format": FORMAT + "-finding", "id": row.get("id") or row["case"], "operator": operator,
                     "arms": row.get("arms"), "label": row.get("label")}
    if operator is not None:
        catch = catch_spec_for(operator)
        finding["case"] = row["case"]
        finding["catchSpec"] = {"id": catch.get("id"), "path": str(CATCH_SPECS[operator].relative_to(REPO)),
                                "notes": CATCH_NOTES.get(operator)}
        finding["catchSpecDoc"] = catch
        (work / "catch-spec.json").write_text(json.dumps(catch, indent=2) + "\n", encoding="utf-8")
    (work / "finding.json").write_text(json.dumps(finding, indent=2) + "\n", encoding="utf-8")
    print(f"::notice title=Mutation finding {finding['id']}::survived every public check; a finding, not a failure")


def _safe(mutant_id: str) -> str:
    return mutant_id.replace("/", "_").replace(":", "_")


def _render_replay(route: Path, out: Path, patches: list[Path]) -> tuple[dict, list[str]]:
    harness_run(route, out, patches=patches)
    return (json.loads((out / "trace.json").read_text(encoding="utf-8")),
            json.loads((out / "replay.json").read_text(encoding="utf-8"))["frameSha256"])


def run_mutant(mutant_id: str, tier: str, out: Path, *, prereg: dict | None = None, manifest: dict | None = None,
               force_sam: bool = False) -> dict:
    """One generated mutant. ``cheap``: render, ask the oracle, judge with SAM off and the engine-record
    checks. ``sam``: the second phase, for what the cheap tier left and the agreement sample."""
    _public_only()
    prereg = prereg or mutate_game.load_preregistration()
    manifest = manifest or mutate_game.load_manifest(prereg, MANIFEST)
    mutant = mutate_game.mutant_by_id(manifest, mutant_id)
    work = out / _safe(mutant_id)
    work.mkdir(parents=True, exist_ok=True)
    t0, images = time.perf_counter(), sam_usage()
    row: dict = {"format": FORMAT, "kind": "mutant", "id": mutant_id, "class": mutant["class"], "file": mutant["file"],
                 "label": "bad", "tier": tier, "preregistrationSha256": prereg["sha256"],
                 "commit": os.environ.get("GITHUB_SHA")}
    try:
        patch = work / "mutant.patch"
        patch.write_text(mutate_game.patch_text(mutant), encoding="utf-8")
        empty = work / "empty.patch"
        empty.write_text("", encoding="utf-8")
        request = _request(f"rr-mutant-{_safe(mutant_id)}"[:80], load(REGRESSION_SPEC, "test-spec"), str(patch.resolve()))
        clean_trace, clean_frames = _render_replay(SMOKE_ROUTE, work / "clean", [])
        trace, frames = _render_mutant(work, patch)
        if not any(r.get("player") for r in trace.get("rows") or []):
            raise CaseCrashed("the game ran but its scene never loaded a player")
        row["oracle"] = mutate_game.oracle(clean_trace, clean_frames, trace, frames, prereg["oracle"])
        row["category"] = row["oracle"]["category"]
        if row["category"] == "equivalent":
            row["outcome"] = "equivalent"
            row["dropReason"] = ("no difference from the clean game on the smoke route, over the pre-registered "
                                 "thresholds; the route may never reach this code")
        else:
            row["engineRecord"] = {name: v["result"] for name, v in trace_checks.judge_all(trace).items()}
            row["engineRecordCaught"] = "fail" in row["engineRecord"].values()
            cheap = _arm(request, empty, work, "sam-off", "trace")
            if tier == "sam":
                judge_tiers(request, empty, work, row, force_sam=force_sam, cheap=cheap,
                            extra_catch=row["engineRecordCaught"])
            else:
                _cheap_phase(cheap, row)
        if row.get("outcome") == "survived":
            _write_finding(work, row, None)
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        _record_failure(row, work, exc)
    _finish(row, work, t0, images)
    return row


def _render_mutant(work: Path, patch: Path) -> tuple[dict, list[str]]:
    """The mutant's replay. Failing twice is the mutant's own crash; once is a flake, and is recorded."""
    for name in ("mutant", "mutant-retry"):
        try:
            return _render_replay(SMOKE_ROUTE, work / name, [patch])
        except (SystemExit, subprocess.CalledProcessError) as exc:
            if not _replay_failed(exc):
                raise
            failure = exc
    raise CaseCrashed(str(failure)[:300]) from failure


def _cheap_phase(cheap: dict, row: dict) -> None:
    """A mutant's first phase never spends SAM: what the cheap tier passes waits for the second."""
    row["arms"] = {"cheap": cheap}
    row["cheapDecision"] = cheap["decision"]
    if cheap["decision"] == "reject" or row["engineRecordCaught"]:
        row["outcome"] = "caught-cheap"
    elif cheap["decision"] == "accept":
        row["outcome"] = "awaiting-sam"
    else:
        row["outcome"] = "undecided"
        row["undecidedWhy"] = "the cheap tier could not decide"


def dry_mutants() -> list[dict]:
    """Two mutants that exercise the mutant path's two ends: one that plays differently, and one
    whose scene has lost its script, to see what the game really does with a broken resource."""
    every = mutate_game.enumerate_mutants(DRY_PARAMS)
    plays = next(m for m in every if m["id"] == "code:player/player.gd:7:sign.WALK_SPEED")
    broken = next(m for m in every if m["class"] == "resource-path" and m["file"] == "player/player.tscn"
                  and "player.gd" in m["before"])
    return [plays, broken]


def rehearse(kind: str, out: Path) -> list[dict]:
    """A rehearsal of one path, real Godot and all. Its rows name no registration, so a summary can
    never mix them with a judged run."""
    if kind == "pair":
        return [run_case(*DRY_RUN, out, prereg=DRY_PREREG, cheap_only=True)]
    if kind == "sam":
        return [run_case(*DRY_RUN, out, prereg=DRY_PREREG, force_sam=True)]
    mutants = dry_mutants()
    return [run_mutant(m["id"], "cheap", out, prereg=DRY_PREREG, manifest={"mutants": mutants}) for m in mutants]


def plan_sam(root: Path, prereg: dict) -> dict:
    """Which mutants the SAM phase looks at, from the cheap phase's results: every one the cheap tier
    passed, and the pre-registered seeded sample of its rejections for the agreement table."""
    rows = _rows(root)
    waiting = sorted(r["id"] for r in rows if r.get("outcome") == "awaiting-sam")
    caught = sorted(r["id"] for r in rows if r.get("outcome") == "caught-cheap")
    size = min(int(prereg["agreement"]["minimum"]), len(caught))
    return {"survivors": waiting, "agreement": sorted(random.Random(prereg["agreement"]["seed"]).sample(caught, size))}


def _rows(out: Path) -> list[dict]:
    """Every result under ``out``. A mutant judged in both phases counts once, as its SAM phase."""
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(out).rglob("result.json"))]
    rows = [r for r in rows if r.get("format") == FORMAT]
    second = {r["id"] for r in rows if r.get("kind") == "mutant" and r.get("tier") == "sam"}
    return [r for r in rows if not (r.get("id") in second and r.get("tier") == "cheap")]


def _sam_arm_images(row: dict) -> int:
    return ((row.get("arms") or {}).get("sam") or {}).get("samImages") or 0


def _name(row: dict) -> str:
    return row.get("id") or f"{row['case']} {row['operator']}"


def _tally(rows: list[dict]) -> dict:
    counts = {o: sum(r.get("outcome") == o for r in rows) for o in OUTCOMES}
    bad = [r for r in rows if r.get("label") == "bad"]
    caught = sum(r.get("outcome") in CAUGHT for r in bad)
    cheap = sum(r.get("outcome") == "caught-cheap" for r in bad)
    survived = sum(r.get("outcome") == "survived" for r in bad)
    decided = caught + survived
    return {"cases": len(rows), **counts, "badCaught": caught, "badSurvived": survived,
            "score": round(caught / decided, 4) if decided else None,
            "cheapTierScore": round(cheap / decided, 4) if decided else None,
            "samImages": sum(int(r.get("samImages") or 0) for r in rows),
            "samImagesTiered": sum(_sam_arm_images(r) for r in rows if not r.get("agreement")),
            "samImagesFullRun": sum(_sam_arm_images(r) for r in rows)}


def _by_check(rows: list[dict]) -> dict:
    """How many cases each check failed on, in each tier: which checks catch what."""
    counts: dict[str, int] = {}
    for r in rows:
        arms = r.get("arms") or {}
        names = [f"cheap {c}" for c in (arms.get("cheap") or {}).get("failedChecks") or []]
        names += [f"sam {c}" for c in (arms.get("sam") or {}).get("failedChecks") or []]
        names += [f"engine-record {k}" for k, v in (r.get("engineRecord") or {}).items() if v == "fail"]
        for name in names:
            counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))


def summarize(out: Path) -> dict:
    rows = _rows(out)
    if not rows:
        raise SystemExit(f"{out}: no results, so there is nothing to summarize")
    registrations = {r.get("preregistrationSha256") for r in rows}
    if len(registrations) > 1:
        raise SystemExit(f"{out}: these results come from {len(registrations)} different registrations, so they "
                         "cannot be reported as one result")
    finals = [r for r in rows if r.get("outcome") != "equivalent"]
    bad = [r for r in finals if r.get("label") == "bad"]
    by = lambda key: {k: _tally([r for r in finals if r.get(key) == k])  # noqa: E731
                      for k in sorted({r.get(key) for r in finals if r.get(key)})}
    agreed = [r for r in finals if r.get("agreement")]
    warm = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(out).rglob("sam-warm.json"))]
    spent = sum(int(r.get("samImages") or 0) for r in rows)
    tiered = sum(_sam_arm_images(r) for r in finals if not r.get("agreement"))
    agreement_only = sum(_sam_arm_images(r) for r in agreed)
    with_sam = [r for r in finals if _sam_arm_images(r)]
    doc = {
        "format": FORMAT + "-summary",
        "preregistrationSha256": next(iter(registrations), None),
        **_tally(finals),
        "equivalentDropped": [{"id": r["id"], "reason": r.get("dropReason")}
                              for r in rows if r.get("outcome") == "equivalent"],
        "unlabelled": sum(r.get("label") not in ("bad", "good") for r in finals),
        "noopCandidates": sum(bool(r.get("noop")) for r in finals),
        "byOperator": by("operator"), "byCase": by("case"), "byClass": by("class"), "byCheck": _by_check(finals),
        "visionOnlyWins": [_name(r) for r in bad if r.get("outcome") == "caught-sam"],
        "blindSpots": [_name(r) for r in bad if r.get("outcome") == "survived"],
        "goodAccepted": sum(r.get("label") == "good" and r.get("outcome") == "survived" for r in finals),
        "falseRejects": [_name(r) for r in finals if r.get("label") == "good" and r.get("outcome") in CAUGHT],
        "agreement": {"checked": len(agreed), "agree": sum(r["agreement"] == "agree" for r in agreed),
                      "disagree": sum(r["agreement"] == "disagree" for r in agreed),
                      "undecided": sum(r["agreement"] == "undecided" for r in agreed),
                      "disagreements": [_name(r) for r in agreed if r["agreement"] == "disagree"]},
        # A full SAM run is only measured on cases SAM saw, so the figure says how many that is.
        "samImages": {"spent": spent, "tiered": tiered, "agreementOnly": agreement_only,
                      "probes": spent - tiered - agreement_only,
                      "warm": sum(int(w.get("samImages") or 0) for w in warm),
                      "fullRun": tiered + agreement_only, "fullRunCases": len(with_sam), "ofCases": len(finals)},
        "rows": rows,
    }
    if MANIFEST.is_file() and any(r.get("kind") == "mutant" for r in rows):
        sampled = [m["id"] for m in json.loads(MANIFEST.read_text(encoding="utf-8"))["mutants"]]
        doc["reconciliation"] = {"sampled": len(sampled), "judged": len(finals),
                                 "equivalent": len(doc["equivalentDropped"]),
                                 "missing": sorted(set(sampled) - {r.get("id") for r in rows})}
    (Path(out) / "mutation-summary.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def markdown(doc: dict) -> str:
    score = "not yet" if doc["score"] is None else f"{doc['score']:.1%}"
    lines = ["# Mutation bench", "",
             "Public checks only. A survivor is a finding, not a CI failure. Only a check that ran and failed "
             f"counts as a catch. Registration `{doc['preregistrationSha256']}`.", "",
             f"Mutation score: **{score}** ({doc['badCaught']} of {doc['badCaught'] + doc['badSurvived']} decided "
             f"bad cases caught). Good cases accepted: {doc['goodAccepted']}.", "",
             "| Outcome | Cases |", "| --- | --- |"]
    lines += [f"| {o} | {doc[o]} |" for o in OUTCOMES]
    lines += ["", f"Unlabelled, left out of the score: {doc['unlabelled']}. No-op candidates: {doc['noopCandidates']}. "
              f"Equivalent, dropped with a reason: {len(doc['equivalentDropped'])}.", ""]
    if doc.get("reconciliation"):
        r = doc["reconciliation"]
        lines += [f"Of {r['sampled']} sampled: {r['judged']} judged, {r['equivalent']} equivalent, "
                  f"{len(r['missing'])} missing.", ""]
    for title, key in (("Per operator", "byOperator"), ("Per class", "byClass"), ("Per case", "byCase")):
        if doc[key]:
            lines += [f"## {title}", "",
                      "| | Caught, cheap | Caught, SAM only | Survived | Undecided | Crash | Error | "
                      "SAM images, tiered | SAM images, full run |",
                      "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
            lines += [f"| {k} | {t['caught-cheap']} | {t['caught-sam']} | {t['survived']} | {t['undecided']} | "
                      f"{t['crash']} | {t['error']} | {t['samImagesTiered']} | {t['samImagesFullRun']} |"
                      for k, t in doc[key].items()]
            lines.append("")
    if doc["byCheck"]:
        lines += ["## Which checks catch what", "", "| Check | Cases it failed on |", "| --- | --- |"]
        lines += [f"| {k} | {n} |" for k, n in doc["byCheck"].items()] + [""]
    a = doc["agreement"]
    lines += ["## Agreement with the cheap tier", "",
              f"{a['checked']} cheap rejections also judged by SAM's own checks: {a['agree']} agree, "
              f"{a['disagree']} disagree, {a['undecided']} undecided.", ""]
    for title, key in (("Disagreements", None), ("Vision-only wins", "visionOnlyWins"), ("Blind spots", "blindSpots"),
                       ("False rejects", "falseRejects")):
        items = a["disagreements"] if key is None else doc[key]
        if items:
            lines += [f"## {title}", ""] + [f"- {i}" for i in items] + [""]
    s = doc["samImages"]
    lines += ["## SAM images", "", f"Spent {s['spent'] + s['warm']}: {s['warm']} judging the clean game once, "
              f"{s['tiered']} on what the cheap tier passed, {s['agreementOnly']} on the agreement check, "
              f"{s['probes']} on the pre-run check. A full SAM run, measured on {s['fullRunCases']} of "
              f"{s['ofCases']} cases: {s['fullRun']}."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    from agents.keys import load_dotenv
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true")
    g.add_argument("--case", help="dev/<family>/vN")
    g.add_argument("--mutant", help="a mutant id from bench/mutation/generated/manifest.json")
    g.add_argument("--plan-sam", type=Path, help="the cheap phase's results: print what the SAM phase must judge")
    g.add_argument("--summarize", type=Path)
    g.add_argument("--dry-run", nargs="?", const="pair", choices=("pair", "sam", "mutants"),
                   help="a rehearsal that is never a result; needs no pre-registration: pair (the default), "
                        "sam (spends SAM), or mutants")
    p.add_argument("--operator", choices=OPERATORS, help="with --case")
    p.add_argument("--tier", choices=("cheap", "sam"), default="cheap", help="with --mutant")
    p.add_argument("--force-sam", action="store_true", help="also ask SAM about a cheap rejection (agreement table)")
    p.add_argument("--out", type=Path, default=REPO / "runs" / "mutation")
    args = p.parse_args(argv)
    if args.list:
        print(json.dumps([{"case": c, "operator": o} for c, o in pairs()]))
        return 0
    if args.summarize:
        print(markdown(summarize(args.summarize)))
        return 0
    if args.plan_sam:
        print(json.dumps(plan_sam(args.plan_sam, mutate_game.load_preregistration()), indent=2))
        return 0
    if args.dry_run:
        rows = rehearse(args.dry_run, args.out)
        for row in rows:
            print(f"::notice title=Mutation dry run {args.dry_run}::{row.get('id') or row['case']}: {row['outcome']}; "
                  f"agreement {row.get('agreement')}; SAM images {row['samImages']}; a test of the plumbing, never a result")
        # A broken scene is meant to crash, so only the tooling failing fails a rehearsal of mutants.
        bad = ("error",) if args.dry_run == "mutants" else ("error", "crash", "undecided")
        return 1 if any(r["outcome"] in bad for r in rows) else 0
    try:
        if args.mutant:
            row = run_mutant(args.mutant, args.tier, args.out, force_sam=args.force_sam)
        else:
            if not args.operator:
                p.error("--case needs --operator")
            row = run_case(args.case, args.operator, args.out, force_sam=args.force_sam)
    except mutate_game.PreregistrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({k: row.get(k) for k in ("case", "operator", "id", "outcome", "agreement", "samImages",
                                               "error", "wallClockSeconds")}))
    # Findings, catches and crashes are results; only a tooling error fails the job.
    return 1 if row.get("outcome") == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
