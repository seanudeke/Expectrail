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
    python3 -m agents.mutation_bench --dry-run mutants --out runs/dry   # three stand-ins, cheap phase, no SAM

To report both phases of Part 2 together, download each run's artifacts into its own folder under one
parent and summarize the parent: a mutant judged in both phases counts once, as its SAM phase.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
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
# Rehearsals run the real paths before anything is registered, on cases the study can never draw, so
# that nothing in the population is judged early. The pair is the judge benchmark's comment-only
# fixture on an unfixed bug (public in bench/judge): the robot still falls. Every one of the 48 starts
# from the correct undo, so this game can never be one of them, which a test holds by comparing the
# game trees. The stand-ins edit files the generator never touches.
DRY_RUN = ("dev/physics-fall-through/v1", REPO / "agents" / "fixtures" / "fix-comment-only.patch")
DRY_PREREG = {"sha256": None, "oracle": {"traceThresholdPx": 0, "frameThreshold": 0}}
# id: (file, the line as it stands, what it becomes)
DRY_STAND_INS = {
    "rehearsal:plays-differently": ("project.godot", "2d/default_gravity=2100", "2d/default_gravity=1400"),
    "rehearsal:runs-with-a-load-failure": (
        "level/tileset.tres", '[ext_resource type="Texture2D" uid="uid://8bv0mysvxgle" path="res://level/tiles.webp" id="1"]',
        '[ext_resource type="Texture2D" path="res://level/tiles.webp.missing" id="1"]'),
    "rehearsal:cannot-start": ("project.godot", 'run/main_scene="res://game_singleplayer.tscn"',
                               'run/main_scene="res://game_singleplayer.tscn.missing"'),
}
# A failed load in Godot's log. A game that still runs is judged as usual: a missing texture is the
# very bug a resource-path mutant makes. These lines are recorded, and only a game that does not run,
# or never loads a player, is a crash.
LOAD_FAILURE = re.compile(r"Failed loading resource|Cannot open file|Failed to load|File not found")

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


def excluded_pairs(prereg: dict) -> set[tuple[str, str]]:
    return {(p["case"], p["operator"]) for p in (prereg.get("excludedBeforeDraw") or {}).get("pairs") or []}


def study_pairs(prereg: dict) -> list[tuple[str, str]]:
    """The pairs the study judges: every pair but those excluded before registration."""
    excluded = excluded_pairs(prereg)
    unknown = sorted(excluded - set(pairs()))
    if unknown:
        raise mutate_game.PreregistrationError(f"excludedBeforeDraw names pairs that do not exist: {unknown}")
    return [p for p in pairs() if p not in excluded]


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
        checkResults={f"{c['kind']}/{c['spec']}": c["result"] for c in verification.get("checks") or []
                      if c.get("kind") not in ("held-out", "clean")},
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
    if (case, operator) in excluded_pairs(prereg):
        raise SystemExit(f"{case} {operator} was excluded before registration, so the study never judges it")
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
                 "rehearsal": prereg["sha256"] is None,
                 "commit": os.environ.get("GITHUB_SHA")}
    try:
        patch = work / "mutant.patch"
        patch.write_text(mutate_game.patch_text(mutant), encoding="utf-8")
        empty = work / "empty.patch"
        empty.write_text("", encoding="utf-8")
        request = _request(f"rr-mutant-{_safe(mutant_id)}"[:80], load(REGRESSION_SPEC, "test-spec"), str(patch.resolve()))
        clean_trace, clean_frames = _render_replay(SMOKE_ROUTE, work / "clean", [])
        trace, frames, replay = _render_mutant(work, patch)
        row["loadFailures"] = load_failures(work / "clean" / "godot.log", replay / "godot.log")
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
        if row.get("outcome") == "survived" and not row["rehearsal"]:
            _write_finding(work, row, None)
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        _record_failure(row, work, exc)
    _finish(row, work, t0, images)
    return row


def load_failures(clean_log: Path, log: Path) -> int | None:
    """How many load-failure lines this replay's log has that the clean game's does not; None when
    either log is missing, since the clean game's own lines could not be told apart."""
    def lines(path):
        return {line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
                if LOAD_FAILURE.search(line)}

    return len(lines(log) - lines(clean_log)) if clean_log.is_file() and log.is_file() else None


def _render_mutant(work: Path, patch: Path) -> tuple[dict, list[str], Path]:
    """The mutant's replay. Failing twice is the mutant's own crash; once is a flake, and is recorded."""
    for name in ("mutant", "mutant-retry"):
        try:
            return (*_render_replay(SMOKE_ROUTE, work / name, [patch]), work / name)
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
    """The stand-ins, as mutants. Each edits a file the generator never touches."""
    found = []
    for mutant_id, (rel, before, after) in DRY_STAND_INS.items():
        lines = (GAME / rel).read_text(encoding="utf-8").splitlines()
        found.append({"id": mutant_id, "class": "rehearsal", "file": rel, "line": lines.index(before) + 1,
                      "before": before, "after": after})
    return found


def _rehearse_pair(out: Path, *, force_sam: bool, cheap_only: bool) -> dict:
    case, fixture = DRY_RUN
    work = out / "rehearsal-pair"
    work.mkdir(parents=True, exist_ok=True)
    t0, images = time.perf_counter(), sam_usage()
    row: dict = {"format": FORMAT, "kind": "rehearsal", "rehearsal": True, "case": case, "operator": "rehearsal",
                 "label": "bad", "preregistrationSha256": None, "commit": os.environ.get("GITHUB_SHA")}
    try:
        request = _request("rr-mutation-rehearsal", case_spec(case), str(dev_variants()[case].relative_to(REPO)))
        judge_tiers(request, fixture, work, row, force_sam=force_sam, cheap_only=cheap_only)
    except (Exception, SystemExit) as exc:  # noqa: BLE001
        _record_failure(row, work, exc)
    return _finish(row, work, t0, images)


def rehearse(kind: str, out: Path) -> list[dict]:
    """A rehearsal of one path, real Godot and all, on cases the study cannot draw. Its rows name no
    registration and say they are rehearsals, so a summary can never mix them with a judged run."""
    _public_only()
    if kind == "pair":
        return [_rehearse_pair(out, force_sam=False, cheap_only=True)]
    if kind == "sam":
        return [_rehearse_pair(out, force_sam=True, cheap_only=False)]
    mutants = dry_mutants()
    return [run_mutant(m["id"], "cheap", out, prereg=DRY_PREREG, manifest={"mutants": mutants}) for m in mutants]


def rehearsal_passed(kind: str, rows: list[dict]) -> bool:
    """Whether the path really ran. A rehearsal that never reached what it rehearses has failed,
    whatever its outcome: a cheap catch says nothing about the SAM arm."""
    if len(rows) != (3 if kind == "mutants" else 1) or any(r.get("outcome") == "error" for r in rows):
        return False
    if kind == "pair":
        return rows[0].get("outcome") in ("caught-cheap", "awaiting-sam")
    if kind == "sam":
        row = rows[0]
        return ("sam" in (row.get("arms") or {}) and not row.get("samPreflight") and not row.get("samArmFailed")
                and row.get("outcome") != "crash")
    by_id = {r.get("id"): r for r in rows}
    if set(by_id) != set(DRY_STAND_INS):
        return False
    plays = by_id["rehearsal:plays-differently"]
    loads = by_id["rehearsal:runs-with-a-load-failure"]
    return (plays.get("category") == "visible" and plays.get("outcome") != "crash"
            and loads.get("category") == "visible" and int(loads.get("loadFailures") or 0) > 0
            and by_id["rehearsal:cannot-start"].get("outcome") == "crash")


def plan_sam(root: Path, prereg: dict) -> dict:
    """Which mutants the SAM phase looks at, from the cheap phase's results: every one the cheap tier
    passed, and the pre-registered seeded sample of its rejections for the agreement table."""
    rows = _rows(root)
    foreign = sum(r.get("preregistrationSha256") != prereg["sha256"] for r in rows)
    if foreign:
        raise SystemExit(f"{root}: {foreign} results are not from this registration")
    waiting = sorted(r["id"] for r in rows if r.get("outcome") == "awaiting-sam")
    caught = sorted(r["id"] for r in rows if r.get("outcome") == "caught-cheap")
    size = min(int(prereg["agreement"]["minimum"]), len(caught))
    return {"survivors": waiting, "agreement": sorted(random.Random(prereg["agreement"]["seed"]).sample(caught, size))}


def all_rows(out: Path) -> list[dict]:
    """Every result under ``out``, before a mutant judged in both phases is counted once."""
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(out).rglob("result.json"))]
    return [r for r in rows if r.get("format") == FORMAT]


def _rows(out: Path) -> list[dict]:
    """Every result under ``out``. A mutant judged in both phases counts once, as its SAM phase."""
    rows = all_rows(out)
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
    # A rehearsal has no score, anywhere. Nor has a cheap phase with cases still waiting for SAM: it
    # cannot produce a survivor, so anything it printed would read as near 100%.
    scored = decided and not any(r.get("rehearsal") or r.get("outcome") == "awaiting-sam" for r in rows)
    return {"cases": len(rows), **counts, "badCaught": caught, "badSurvived": survived,
            "score": round(caught / decided, 4) if scored else None,
            "cheapTierScore": round(cheap / decided, 4) if scored else None,
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


def _sampling_view(manifest: dict, by_class: dict, rows: list[dict]) -> dict:
    """How the sample stands to the game, so the score can be read. With counts set per class, the
    pooled score depends on those counts, so a weighted score goes beside it. A class's score is over
    its decided cases, so it weighs what it is estimated to hold of those: its size times the share of
    its sample that was decided. Its plain size would count mutants nobody could ever catch."""
    enumerated, drawn = manifest.get("enumeratedByClass") or {}, manifest.get("sampledByClass") or {}
    dropped = {c: sum(r.get("outcome") == "equivalent" and r.get("class") == c for r in rows) for c in enumerated}
    classes, weights, visible = {}, {}, {}
    for cls, size in enumerated.items():
        sampled, tally = drawn.get(cls, 0), by_class.get(cls) or {}
        decided = tally.get("badCaught", 0) + tally.get("badSurvived", 0)
        weights[cls] = size * decided / sampled if sampled else 0.0
        visible[cls] = size * max(sampled - dropped[cls], 0) / sampled if sampled else 0.0
        classes[cls] = {"enumerated": size, "sampled": sampled, "equivalent": dropped[cls], "decided": decided,
                        "score": tally.get("score"), "estimatedVisible": round(visible[cls], 1),
                        "estimatedDecided": round(weights[cls], 1)}
    scored = {c: v["score"] for c, v in classes.items() if v["score"] is not None and weights[c] > 0}
    weight, total = sum(weights[c] for c in scored), sum(visible.values())
    return {"method": (manifest.get("sampling") or {}).get("method"), "shortByClass": manifest.get("shortByClass") or {},
            "shortOfSample": manifest.get("shortOfSample") or 0, "classes": classes,
            "weightedScore": round(sum(weights[c] * s for c, s in scored.items()) / weight, 4) if weight else None,
            "weightedCovers": round(weight / total, 4) if total else None,
            "classesWithNoScore": sorted(c for c, v in classes.items() if v["sampled"] and c not in scored),
            # Unsampled, so nothing estimates them: the coverage above says nothing about these.
            "classesNotSampled": sorted(c for c, v in classes.items() if v["enumerated"] and not v["sampled"]),
            "classesNotInManifest": sorted({r["class"] for r in rows if r.get("class") and r["class"] not in enumerated})}


def summarize(out: Path) -> dict:
    rows = _rows(out)
    if not rows:
        raise SystemExit(f"{out}: no results, so there is nothing to summarize")
    registrations = {r.get("preregistrationSha256") for r in all_rows(out)}  # a dropped row still counts here
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
        "rehearsal": any(r.get("rehearsal") for r in rows),
        **_tally(finals),
        "equivalentDropped": [{"id": r["id"], "reason": r.get("dropReason")}
                              for r in rows if r.get("outcome") == "equivalent"],
        "unlabelled": sum(r.get("label") not in ("bad", "good") for r in finals),
        "noopCandidates": sum(bool(r.get("noop")) for r in finals),
        "byOperator": by("operator"), "byCase": by("case"), "byClass": by("class"), "byCheck": _by_check(finals),
        "visionOnlyWins": [_name(r) for r in bad if r.get("outcome") == "caught-sam" and not r.get("rehearsal")],
        "blindSpots": [_name(r) for r in bad if r.get("outcome") == "survived" and not r.get("rehearsal")],
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
    doc["samplingUnknown"] = any(r.get("kind") == "mutant" for r in rows) and not doc["rehearsal"] and not MANIFEST.is_file()
    if MANIFEST.is_file() and any(r.get("kind") == "mutant" for r in rows) and not doc["rehearsal"]:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        sampled = [m["id"] for m in manifest.get("mutants") or []]
        doc["reconciliation"] = {"sampled": len(sampled), "judged": len(finals),
                                 "equivalent": len(doc["equivalentDropped"]),
                                 "missing": sorted(set(sampled) - {r.get("id") for r in rows}),
                                 "notInManifest": sorted({r["id"] for r in rows if r.get("id")} - set(sampled))}
        doc["sampling"] = _sampling_view(manifest, doc["byClass"], rows)
    (Path(out) / "mutation-summary.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def markdown(doc: dict) -> str:
    score = "not yet" if doc["score"] is None else f"{doc['score']:.1%}"
    decided = doc["badCaught"] + doc["badSurvived"]
    view = doc.get("sampling")
    lines = ["# Mutation bench", ""]
    if doc["rehearsal"]:
        lines += ["**A rehearsal of the plumbing, never a result.** It has no score, and no case in it can be drawn by "
                  "the study.", ""]
    else:
        lines += ["Public checks only. A survivor is a finding, not a CI failure. Only a check that ran and failed "
                  f"counts as a catch. Registration `{doc['preregistrationSha256']}`.", ""]
        if view and view["method"] == "stratified":
            weighted = "not yet" if view["weightedScore"] is None else f"{view['weightedScore']:.1%}"
            covers = "no" if view["weightedCovers"] is None else f"{view['weightedCovers']:.0%} of the"
            no_score = ", ".join(view["classesWithNoScore"]) or "none"
            unsampled = ", ".join(view["classesNotSampled"]) or "none"
            lines += [f"Mutation score, weighted by each class's estimated decided mutants: **{weighted}**, covering "
                      f"{covers} estimated visible mutants of the sampled classes (classes with no score: {no_score}; "
                      f"classes never sampled: {unsampled}).", "",
                      f"Over the sample as drawn: {score} ({doc['badCaught']} of {decided} decided bad cases caught). The "
                      "sample's class counts were set by hand, so this figure depends on them and is not a score "
                      "for the whole game.", ""]
        elif doc.get("samplingUnknown") or (view and view["method"] != "uniform"):
            lines += [f"Over the sample: {score} ({doc['badCaught']} of {decided} decided bad cases caught). **Nothing here "
                      "says how this sample stands to the game, so this is not a score for the whole game.**", ""]
        else:
            lines += [f"Mutation score: **{score}** ({doc['badCaught']} of {decided} decided bad cases caught).", ""]
        if doc["awaiting-sam"]:
            lines += [f"**Not a score yet.** {doc['awaiting-sam']} cases passed the cheap tier and still wait for SAM, so "
                      f"nothing can have survived. The cheap tier caught {doc['caught-cheap']}.", ""]
        outside = doc["undecided"] + doc["crash"] + doc["error"] + doc["awaiting-sam"]
        if outside:
            lines += [f"Outside the score: {outside} of {doc['cases']} cases ({doc['undecided']} undecided, {doc['crash']} "
                      f"crashed, {doc['error']} errors, {doc['awaiting-sam']} waiting for SAM).", ""]
        if view and view["classesNotInManifest"]:
            lines += [f"Classes the manifest does not know: {', '.join(view['classesNotInManifest'])}.", ""]
        lines += [f"Good cases accepted: {doc['goodAccepted']}.", ""]
    lines += ["| Outcome | Cases |", "| --- | --- |"]
    lines += [f"| {o} | {doc[o]} |" for o in OUTCOMES]
    lines += ["", f"Unlabelled, left out of the score: {doc['unlabelled']}. No-op candidates: {doc['noopCandidates']}. "
              f"Equivalent, dropped with a reason: {len(doc['equivalentDropped'])}.", ""]
    if doc.get("reconciliation"):
        r = doc["reconciliation"]
        lines += [f"Of {r['sampled']} sampled: {r['judged']} judged, {r['equivalent']} equivalent, "
                  f"{len(r['missing'])} missing, {len(r['notInManifest'])} not in the manifest.", ""]
    if view:
        lines += ["## How the sample stands to the game", "", f"Method: {view['method']}. Short of the plan by "
                  f"{view['shortOfSample']}" + (f" ({view['shortByClass']})." if view["shortByClass"] else "."), "",
                  "| Class | Mutants in the game | Sampled | Equivalent | Decided | Estimated decided | Score |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        lines += [f"| {c} | {v['enumerated']} | {v['sampled']} | {v['equivalent']} | {v['decided']} | {v['estimatedDecided']} | "
                  f"{'-' if v['score'] is None else format(v['score'], '.1%')} |" for c, v in view["classes"].items()] + [""]
    for title, key in (("Per operator", "byOperator"), ("Per class", "byClass"), ("Per case", "byCase")):
        if doc[key]:
            lines += [f"## {title}", "",
                      "| | Score | Caught, cheap | Caught, SAM only | Survived | Undecided | Crash | Error | "
                      "SAM images, tiered | SAM images, full run |",
                      "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
            lines += [f"| {k} | {'-' if t['score'] is None else format(t['score'], '.1%')} | {t['caught-cheap']} | "
                      f"{t['caught-sam']} | {t['survived']} | {t['undecided']} | "
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
                  f"category {row.get('category')}; load failures {row.get('loadFailures')}; agreement "
                  f"{row.get('agreement')}; SAM images {row['samImages']}; a test of the plumbing, never a result")
        return 0 if rehearsal_passed(args.dry_run, rows) else 1
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
