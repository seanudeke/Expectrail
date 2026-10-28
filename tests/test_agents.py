"""Agents lane: orchestrator, patchutil, fixer fixtures, verifier decide paths, trust, loop."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents.fixer import run_fixer
from agents.gameplay import (
    MIN_DELTA_X_FIXTURE,
    MIN_DELTA_X_HARNESS,
    REASON_BELOW,
    REASON_DELTA,
    REASON_EMPTY,
    REASON_END_FLOOR,
    judge_trace,
)
from agents.isolation import FIXER_FORBIDDEN_BASENAMES
from agents.keys import muse_code_ready, resolve_mode, seal_mode_flags, wonder_key
from agents.loop import main as loop_main
from agents.loop import one_run
from agents.observations import from_trace
from agents.orchestrator import build_repair_request
from agents.patchutil import assert_editable, paths_touched
from agents.gate1 import main as gate1_main
from agents.report import build_report, gameplay_film_stub, verify_release_candidate, write_loop_rollup
from agents.triage import WONDER_MODEL, triage
from agents.prove_live import main as prove_live_main
from agents.trust import probe_canary_reads, run_trust_check
from agents.verifier import GAMEPLAY_SPEC_ID, verify
from harness.run import REPO, tree_digest
from nightshift.contracts import load, validate
from nightshift.evaluator import decide, evaluate

BEFORE_FRAME = REPO / "agents" / "fixtures" / "frames" / "before-fall.png"
AFTER_FRAME = REPO / "agents" / "fixtures" / "frames" / "after-fixed.png"


def _request():
    return build_repair_request(
        request_id="rr-test",
        spec=load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec"),
        verdict=load(REPO / "contracts" / "examples" / "verdict.json", "verdict"),
        route=load(REPO / "harness" / "routes" / "smoke.json", "route"),
        base_patch="bugs/physics-fall-through/v1.patch",
        key_frames=["frames/f00000008.png"],
    )


class PatchutilTest(unittest.TestCase):
    def test_paths_and_editable(self):
        fix = (REPO / "agents" / "fixtures" / "fix-collision-mask.patch").read_text()
        self.assertEqual(paths_touched(fix), ["player/player.tscn"])
        self.assertEqual(assert_editable(fix, ["player/**", "level/**"]), [])
        bad = (REPO / "agents" / "fixtures" / "out-of-glob.patch").read_text()
        self.assertTrue(assert_editable(bad, ["player/**", "level/**"]))


class OrchestratorTest(unittest.TestCase):
    def test_repair_request_validates(self):
        doc = _request()
        self.assertEqual(validate(doc), "repair-request")
        self.assertEqual(doc["base"]["tree"], tree_digest(REPO / "game" / "platformer"))


class ObservationsTest(unittest.TestCase):
    def test_from_trace_emits_frames(self):
        trace = {
            "format": "nightshift.trace/v0",
            "ticks": 4,
            "physicsTicksPerSecond": 120,
            "rows": [
                {"tick": 0, "player": [210, 452], "onFloor": True},
                {"tick": 2, "player": [220, 452], "onFloor": True},
                {"tick": 4, "player": [230, 600], "onFloor": False},
            ],
        }
        obs = from_trace(trace)
        validate(obs, "observations")
        self.assertGreaterEqual(len(obs["frames"]), 2)
        self.assertNotIn("goal", obs["frames"][0]["objects"])

    def test_from_trace_fallthrough_fails_regression_freeze_fails_gameplay(self):
        floor = 452.0
        fall = {
            "format": "nightshift.trace/v0",
            "physicsTicksPerSecond": 120,
            "rows": [
                {"tick": 0, "player": [210, floor], "onFloor": True},
                {"tick": 2, "player": [210, floor + 80], "onFloor": False},
                {"tick": 4, "player": [210, floor + 200], "onFloor": False},
            ],
        }
        walk = {
            "format": "nightshift.trace/v0",
            "physicsTicksPerSecond": 120,
            "rows": [
                {"tick": i * 2, "player": [210 + i * 50, floor], "onFloor": True}
                for i in range(0, 12)
            ],
        }
        freeze = {
            "format": "nightshift.trace/v0",
            "physicsTicksPerSecond": 120,
            "rows": [
                {"tick": i * 2, "player": [210, floor], "onFloor": True}
                for i in range(0, 12)
            ],
        }
        reg = load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec")
        reg = {**reg, "window": {"fromFrame": 0, "toFrame": 20}}

        self.assertEqual(evaluate(reg, from_trace(fall))["result"], "fail")
        self.assertEqual(evaluate(reg, from_trace(walk))["result"], "pass")
        self.assertEqual(judge_trace(walk, min_delta_x=MIN_DELTA_X_FIXTURE)["result"], "pass")
        self.assertEqual(judge_trace(freeze, min_delta_x=MIN_DELTA_X_FIXTURE)["result"], "fail")
        self.assertEqual(judge_trace(freeze, min_delta_x=MIN_DELTA_X_FIXTURE)["reason"], REASON_DELTA)

    def test_floor_uses_lowest_surface_not_median(self):
        # Ground at y=500, brief platform landings at y=300 would skew a median upward.
        rows = (
            [{"tick": i * 2, "player": [210 + i, 500.0], "onFloor": True} for i in range(8)]
            + [{"tick": 20, "player": [300, 300.0], "onFloor": True},
               {"tick": 22, "player": [310, 300.0], "onFloor": True}]
        )
        obs = from_trace({"format": "nightshift.trace/v0", "physicsTicksPerSecond": 120, "rows": rows})
        ground_top = obs["frames"][0]["objects"]["ground"][0]["box"][1]
        self.assertEqual(ground_top, 500.0)
        standing = obs["frames"][0]["objects"]["player"][0]["box"][3]
        self.assertLessEqual(standing, ground_top + 12)


class VerifierDecideTest(unittest.TestCase):
    def test_fixed_observations_accept(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc = verify(
                _request(),
                REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                out,
                observations_path=REPO / "agents" / "fixtures" / "obs-fixed.json",
                skip_harness=True,
            )
            self.assertEqual(doc["decision"], "accept")
            validate(doc, "verification")
            kinds = {c["kind"] for c in doc["checks"]}
            self.assertEqual(kinds, {"regression", "gameplay", "clean", "held-out"})
            self.assertTrue(all(c["result"] == "pass" for c in doc["checks"]))
            suite = doc["suite"]
            self.assertEqual(suite["candidate"]["source"], "fixture")
            self.assertEqual(suite["clean"]["source"], "fixture")
            self.assertEqual(suite["heldOut"]["source"], "interim-fixture")
            self.assertNotEqual(
                suite["candidate"]["observationsSha256"],
                suite["clean"]["observationsSha256"],
            )
            self.assertTrue((out / "suite-provenance.json").is_file())

    def test_freeze_player_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc = verify(
                _request(),
                REPO / "agents" / "fixtures" / "freeze-player.patch",
                out,
                observations_path=REPO / "agents" / "fixtures" / "obs-freeze.json",
                skip_harness=True,
            )
            self.assertEqual(doc["decision"], "reject")
            kinds = {c["kind"]: c["result"] for c in doc["checks"]}
            self.assertEqual(kinds.get("regression"), "pass")
            self.assertEqual(kinds.get("gameplay"), "fail")
            self.assertIn("clean", kinds)
            self.assertIn("held-out", kinds)
            gameplay = json.loads((out / "verdict-gameplay.json").read_text())
            validate(gameplay, "gameplay-verdict")
            self.assertEqual(gameplay["spec"], GAMEPLAY_SPEC_ID)
            self.assertEqual(gameplay["reason"], REASON_DELTA)
            self.assertTrue(str(gameplay["source"]).startswith("fixture-trace:"))
            from nightshift.contracts import digest as cdigest
            gp_check = next(c for c in doc["checks"] if c["kind"] == "gameplay")
            self.assertEqual(gp_check["spec"], GAMEPLAY_SPEC_ID)
            self.assertEqual(gp_check["verdictSha256"], cdigest(gameplay))

    def test_clean_fail_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = verify(
                _request(),
                REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                Path(tmp),
                observations_path=REPO / "agents" / "fixtures" / "obs-fixed.json",
                clean_observations_path=REPO / "agents" / "fixtures" / "obs-fallthrough.json",
                skip_harness=True,
            )
            self.assertEqual(doc["decision"], "reject")
            kinds = {c["kind"]: c["result"] for c in doc["checks"]}
            self.assertEqual(kinds.get("clean"), "fail")

    def test_held_out_fail_rejects_via_evaluate(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc = verify(
                _request(),
                REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                out,
                observations_path=REPO / "agents" / "fixtures" / "obs-fixed.json",
                held_out_observations_path=REPO / "agents" / "fixtures" / "obs-fallthrough.json",
                skip_harness=True,
            )
            self.assertEqual(doc["decision"], "reject")
            held = next(c for c in doc["checks"] if c["kind"] == "held-out")
            self.assertEqual(held["result"], "fail")
            from nightshift.contracts import digest
            from nightshift.evaluator import evaluate
            expected = evaluate(
                load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec"),
                load(REPO / "agents" / "fixtures" / "obs-fallthrough.json", "observations"),
            )
            self.assertEqual(held["verdictSha256"], digest(expected))
            self.assertTrue((out / "verdict-held-out.json").is_file())

    def test_held_out_unavailable_never_accepts(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "no-held-out.json"
            doc = verify(
                _request(),
                REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                Path(tmp) / "verify",
                observations_path=REPO / "agents" / "fixtures" / "obs-fixed.json",
                held_out_observations_path=missing,
                skip_harness=True,
            )
            self.assertEqual(doc["decision"], "needs-review")
            held = next(c for c in doc["checks"] if c["kind"] == "held-out")
            self.assertEqual(held["result"], "needs-review")
            self.assertEqual(doc["suite"]["heldOut"]["source"], "unavailable")
            morning = build_report(
                verification=doc,
                candidate=REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                out=Path(tmp) / "morning-nr",
                verification_path=Path(tmp) / "verify" / "verification.json",
            )
            self.assertEqual(morning["decision"], "needs-review")
            rc = json.loads((Path(tmp) / "morning-nr" / "release-candidate.json").read_text())
            validate(rc, "release-candidate")
            self.assertEqual(rc["decision"], "needs-review")
            report = (Path(tmp) / "morning-nr" / "morning-report.md").read_text()
            self.assertIn("source=`unavailable`", report)

    def test_harness_clean_abort_falls_back_and_still_decides(self):
        """Godot SIGABRT on clean-replay must not leave verification.json unwritten."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            candidate_obs = load(REPO / "agents" / "fixtures" / "obs-freeze.json", "observations")

            def harness_then_abort(_route, harness_out, patches=None, **_kw):
                if patches == []:
                    raise subprocess.CalledProcessError(-6, ["godot", "--import"], stderr="SIGABRT")
                harness_out.mkdir(parents=True, exist_ok=True)
                (harness_out / "trace.json").write_text(
                    json.dumps({
                        "rows": [{"tick": 0, "player": [0, 0], "onFloor": True}],
                        "physicsTicksPerSecond": 120,
                    }) + "\n"
                )
                (harness_out / "replay.json").write_text("{}\n")

            with mock.patch("agents.verifier.harness_run", side_effect=harness_then_abort):
                with mock.patch("agents.verifier.from_trace", return_value=candidate_obs):
                    doc = verify(
                        _request(),
                        REPO / "agents" / "fixtures" / "freeze-player.patch",
                        out,
                        skip_harness=False,
                    )
            self.assertTrue((out / "verification.json").is_file())
            self.assertTrue((out / "clean-harness-error.txt").is_file())
            self.assertEqual(doc["decision"], "reject")
            clean = next(c for c in doc["checks"] if c["kind"] == "clean")
            self.assertEqual(clean["route"], "clean-control-fixture-fallback")
            self.assertEqual(clean["result"], "pass")
            self.assertEqual(doc["suite"]["clean"]["source"], "fixture-fallback")
            self.assertEqual(doc["suite"]["candidate"]["source"], "harness")
            self.assertIn("clean harness failed", doc["suite"]["clean"].get("detail", ""))
            validate(doc, "verification")
            morning = build_report(
                verification=doc,
                candidate=REPO / "agents" / "fixtures" / "freeze-player.patch",
                out=out / "morning-fallback",
                verification_path=out / "verification.json",
            )
            report = (out / "morning-fallback" / "morning-report.md").read_text()
            self.assertIn("source=`fixture-fallback`", report)
            self.assertIn("## Suite provenance", report)
            self.assertEqual(morning["decision"], "reject")
            self.assertEqual(
                json.loads((out / "suite-provenance.json").read_text()),
                doc["suite"],
            )
            self.assertEqual(
                {c["kind"] for c in doc["checks"]},
                {"regression", "gameplay", "clean", "held-out"},
            )

    def test_fixture_fallback_same_digest_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            same = load(REPO / "agents" / "fixtures" / "obs-fixed.json", "observations")

            def harness_then_abort(_route, harness_out, patches=None, **_kw):
                if patches == []:
                    raise subprocess.CalledProcessError(-6, ["godot", "--import"])
                harness_out.mkdir(parents=True, exist_ok=True)
                (harness_out / "trace.json").write_text("{}\n")
                (harness_out / "replay.json").write_text("{}\n")

            with mock.patch("agents.verifier.harness_run", side_effect=harness_then_abort):
                with mock.patch("agents.verifier.from_trace", return_value=same):
                    with self.assertRaises(SystemExit) as cm:
                        verify(
                            _request(),
                            REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                            out,
                            clean_observations_path=REPO / "agents" / "fixtures" / "obs-fixed.json",
                            skip_harness=False,
                        )
            self.assertIn("fixture-fallback", str(cm.exception))

    def test_held_out_override_source_is_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = verify(
                _request(),
                REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                Path(tmp),
                observations_path=REPO / "agents" / "fixtures" / "obs-fixed.json",
                held_out_observations_path=REPO / "agents" / "fixtures" / "obs-held-out.json",
                skip_harness=True,
            )
            self.assertEqual(doc["decision"], "accept")
            self.assertEqual(doc["suite"]["heldOut"]["source"], "path")

    def test_same_digest_clean_obs_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                verify(
                    _request(),
                    REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                    Path(tmp),
                    observations_path=REPO / "agents" / "fixtures" / "obs-fixed.json",
                    clean_observations_path=REPO / "agents" / "fixtures" / "obs-fixed.json",
                    skip_harness=True,
                )

    def test_fallthrough_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = verify(
                _request(),
                REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                Path(tmp),
                observations_path=REPO / "agents" / "fixtures" / "obs-fallthrough.json",
                skip_harness=True,
            )
            self.assertEqual(doc["decision"], "reject")

    def test_out_of_glob_rejects_without_harness(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = verify(
                _request(),
                REPO / "agents" / "fixtures" / "out-of-glob.patch",
                Path(tmp),
                observations_path=REPO / "agents" / "fixtures" / "obs-fixed.json",
                skip_harness=True,
            )
            self.assertEqual(doc["decision"], "reject")
            self.assertIn("editable", doc["reasons"][0])
            self.assertEqual(doc["suite"]["candidate"]["source"], "not-run")
            self.assertEqual(doc["suite"]["clean"]["source"], "not-run")
            self.assertEqual(doc["suite"]["heldOut"]["source"], "not-run")
            self.assertEqual(doc["suite"]["earlyReject"]["gate"], "editable-globs")
            self.assertIn("requestSha256", doc["candidate"])
            from nightshift.contracts import digest as cdigest
            self.assertEqual(doc["candidate"]["requestSha256"], cdigest(_request()))
            morning = build_report(
                verification=doc,
                candidate=REPO / "agents" / "fixtures" / "freeze-player.patch",
                out=Path(tmp) / "morning-early",
                verification_path=Path(tmp) / "verification.json",
            )
            report = (Path(tmp) / "morning-early" / "morning-report.md").read_text()
            self.assertIn("## Early reject", report)
            self.assertIn("editable-globs", report)
            self.assertIn("source=`not-run`", report)
            self.assertEqual(morning["requestSha256"], doc["candidate"]["requestSha256"])
            self.assertIn(f"**Request:** `{doc['candidate']['request']}`", report)
            self.assertEqual(doc["candidate"]["request"], _request()["id"])
            rc = json.loads((Path(tmp) / "morning-early" / "release-candidate.json").read_text())
            validate(rc, "release-candidate")
            self.assertEqual(rc["requestSha256"], doc["candidate"]["requestSha256"])
            self.assertEqual(rc["requestId"], doc["candidate"]["request"])
            validate(doc, "verification")

    def test_base_tree_early_reject_films_morning(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = _request()
            request["base"]["tree"] = "0" * 64
            doc = verify(
                request,
                REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                Path(tmp) / "verify",
                observations_path=REPO / "agents" / "fixtures" / "obs-fixed.json",
                skip_harness=True,
            )
            self.assertEqual(doc["decision"], "reject")
            self.assertEqual(doc["suite"]["earlyReject"]["gate"], "base-tree")
            self.assertEqual(doc["suite"]["candidate"]["source"], "not-run")
            report = build_report(
                verification=doc,
                candidate=REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                out=Path(tmp) / "morning",
            )
            md = (Path(tmp) / "morning" / "morning-report.md").read_text()
            self.assertIn("## Early reject", md)
            self.assertIn("base-tree", md)
            self.assertIn("source=`not-run`", md)
            self.assertEqual(report["decision"], "reject")

    def test_morning_fails_closed_on_multiple_gameplay_checks(self):
        from nightshift.contracts import ContractError, digest as cdigest

        good = json.loads(
            (REPO / "contracts" / "examples" / "gameplay-verdict.json").read_text()
        )
        verification = {
            "format": "nightshift.verification/v0",
            "candidate": {
                "patchSha256": "a" * 64,
                "baseTree": "b" * 64,
                "attempt": 1,
                "request": "rr",
                "requestSha256": "c" * 64,
            },
            "evaluator": {"name": "x", "version": "0"},
            "checks": [
                {
                    "spec": GAMEPLAY_SPEC_ID,
                    "kind": "gameplay",
                    "route": "smoke",
                    "result": "fail",
                    "verdictSha256": cdigest(good),
                },
                {
                    "spec": "other-motion",
                    "kind": "gameplay",
                    "route": "smoke",
                    "result": "pass",
                    "verdictSha256": "d" * 64,
                },
            ],
            "decision": "reject",
            "reasons": ["ambiguous"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ContractError):
                build_report(
                    verification=verification,
                    candidate=None,
                    out=Path(tmp) / "morning",
                    gameplay_verdict=good,
                )


class FixerFixtureTest(unittest.TestCase):
    def test_fixture_candidate_enforces_editable(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            meta = run_fixer(
                _request(), out,
                candidate_patch=REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
            )
            self.assertEqual(meta["source"], "fixture")
            self.assertTrue((out / "candidate.patch").exists())
            with self.assertRaises(SystemExit):
                run_fixer(
                    _request(), out / "bad",
                    candidate_patch=REPO / "agents" / "fixtures" / "out-of-glob.patch",
                )

    def test_diff_ignores_repair_request_sidecar(self):
        from agents.fixer import _diff_worktree, prepare_fixer_workspace

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "work"
            base = root / "base"
            prepare_fixer_workspace(_request(), work)
            shutil.copytree(work, base)
            (work / "repair-request.json").write_text("{}", encoding="utf-8")
            # Muse-style game edit inside editable globs.
            tscn = work / "player" / "player.tscn"
            tscn.write_text(tscn.read_text(encoding="utf-8").replace(
                "collision_mask = 14", "collision_mask = 30"), encoding="utf-8")
            text = _diff_worktree(base, work, editable=["player/**", "level/**"])
            self.assertIn("player/player.tscn", text)
            self.assertNotIn("repair-request.json", text)


class TriageReportTrustLoopTest(unittest.TestCase):
    def test_offline_triage_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = triage(
                spec=load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec"),
                verdict=load(REPO / "contracts" / "examples" / "verdict.json", "verdict"),
                route=load(REPO / "harness" / "routes" / "smoke.json", "route"),
                out=root / "triage",
                offline=True,
            )
            validate(request, "repair-request")
            self.assertTrue((root / "triage" / "bug-report.md").exists())

            verification = verify(
                request,
                REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                root / "verify",
                observations_path=REPO / "agents" / "fixtures" / "obs-fixed.json",
                skip_harness=True,
            )
            summary = build_report(
                verification=verification,
                candidate=REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                out=root / "morning",
                verification_path=root / "verify" / "verification.json",
            )
            self.assertEqual(summary["decision"], "accept")
            self.assertTrue((root / "morning" / "release-candidate.json").exists())
            self.assertEqual(summary["gameplay"]["result"], "pass")
            validate(summary["gameplay"], "gameplay-verdict")

    def test_morning_embeds_frames_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = _request()
            verification = verify(
                request,
                REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                root / "verify",
                observations_path=REPO / "agents" / "fixtures" / "obs-fixed.json",
                skip_harness=True,
            )
            key = root / "verifier-host" / ".nightshift-signing-key"
            key.parent.mkdir(parents=True)
            key.write_text("DEMO-FAKE-SIGNING-KEY-NOT-REAL\n", encoding="utf-8")
            vpath = root / "verify" / "verification.json"
            summary = build_report(
                verification=verification,
                candidate=REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                out=root / "morning",
                before=[BEFORE_FRAME],
                after=[AFTER_FRAME],
                signing_key_path=key,
                verification_path=vpath,
            )
            self.assertEqual(summary["decision"], "accept")
            self.assertEqual(len(summary["frames"]), 2)
            self.assertTrue((root / "morning" / "frames" / "before-00.png").is_file())
            self.assertTrue((root / "morning" / "frames" / "after-00.png").is_file())
            report = (root / "morning" / "morning-report.md").read_text(encoding="utf-8")
            self.assertIn("![before](frames/before-00.png)", report)
            self.assertIn("![after](frames/after-00.png)", report)
            self.assertIn("## Gameplay", report)
            self.assertEqual(summary["gameplay"]["spec"], GAMEPLAY_SPEC_ID)
            rc = json.loads((root / "morning" / "release-candidate.json").read_text())
            validate(rc, "release-candidate")
            self.assertEqual(rc["decision"], "accept")
            self.assertEqual(rc["signingKey"], str(key))
            unsigned = build_report(
                verification=verification,
                candidate=REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                out=root / "morning-default-key",
                verification_path=vpath,
            )
            self.assertNotEqual(summary["signature"], unsigned["signature"])
            with self.assertRaises(FileNotFoundError):
                build_report(
                    verification=verification,
                    candidate=REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                    out=root / "morning-missing",
                    before=[root / "no-such.png"],
                    after=[AFTER_FRAME],
                    verification_path=vpath,
                )

    def test_morning_freeze_reject_films_gameplay_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            verification = verify(
                _request(),
                REPO / "agents" / "fixtures" / "freeze-player.patch",
                root / "verify",
                observations_path=REPO / "agents" / "fixtures" / "obs-freeze.json",
                skip_harness=True,
            )
            self.assertEqual(verification["decision"], "reject")
            validate(json.loads((root / "verify" / "verdict-gameplay.json").read_text()), "gameplay-verdict")
            summary = build_report(
                verification=verification,
                candidate=REPO / "agents" / "fixtures" / "freeze-player.patch",
                out=root / "morning",
                before=[BEFORE_FRAME],
                after=[AFTER_FRAME],
                verification_path=root / "verify" / "verification.json",
            )
            self.assertEqual(summary["decision"], "reject")
            self.assertEqual(summary["gameplay"]["spec"], GAMEPLAY_SPEC_ID)
            self.assertEqual(summary["gameplay"]["reason"], REASON_DELTA)
            self.assertEqual(summary["gameplay"]["source"], "fixture-trace:trace-freeze.json")
            report = (root / "morning" / "morning-report.md").read_text()
            self.assertIn("## Gameplay", report)
            self.assertIn(REASON_DELTA, report)
            self.assertIn("fixture-trace:trace-freeze.json", report)
            self.assertIn("deltaX:", report)
            self.assertIn("endOnFloor:", report)
            self.assertIn("belowStreak:", report)
            self.assertIn("sampleCount:", report)
            self.assertIn("minDeltaX:", report)
            rc = json.loads((root / "morning" / "release-candidate.json").read_text())
            validate(rc, "release-candidate")
            self.assertEqual(rc["decision"], "reject")
            self.assertEqual(gameplay_film_stub(summary)["reason"], REASON_DELTA)

    def test_morning_fails_closed_when_gameplay_check_without_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            verification = {
                "format": "nightshift.verification/v0",
                "candidate": {
                    "patchSha256": "a" * 64,
                    "baseTree": "b" * 64,
                    "attempt": 1,
                    "request": "rr",
                },
                "evaluator": {"name": "x", "version": "0"},
                "checks": [
                    {"spec": GAMEPLAY_SPEC_ID, "kind": "gameplay",
                     "route": "smoke", "result": "fail"},
                ],
                "decision": "reject",
                "reasons": ["gameplay failed"],
            }
            with self.assertRaises(FileNotFoundError):
                build_report(
                    verification=verification,
                    candidate=None,
                    out=root / "morning",
                )

    def test_morning_ignores_leftover_verdict_without_gameplay_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            verify_dir = root / "verify"
            verify_dir.mkdir()
            leftover = json.loads(
                (REPO / "contracts" / "examples" / "gameplay-verdict.json").read_text()
            )
            (verify_dir / "verdict-gameplay.json").write_text(
                json.dumps(leftover) + "\n", encoding="utf-8"
            )
            verification = {
                "format": "nightshift.verification/v0",
                "candidate": {
                    "patchSha256": "a" * 64,
                    "baseTree": "b" * 64,
                    "attempt": 1,
                    "request": "rr",
                },
                "evaluator": {"name": "x", "version": "0"},
                "checks": [
                    {"spec": "editable", "kind": "regression", "route": "smoke",
                     "result": "fail", "verdictSha256": "0" * 64},
                ],
                "decision": "reject",
                "reasons": ["editable paths"],
            }
            (verify_dir / "verification.json").write_text(
                json.dumps(verification) + "\n", encoding="utf-8"
            )
            summary = build_report(
                verification=verification,
                candidate=None,
                out=root / "morning",
                verification_path=verify_dir / "verification.json",
            )
            self.assertIsNone(summary["gameplay"])
            report = (root / "morning" / "morning-report.md").read_text()
            self.assertNotIn("## Gameplay", report)
            leftover_dict = build_report(
                verification=verification,
                candidate=None,
                out=root / "morning-dict",
                gameplay_verdict=leftover,
            )
            self.assertIsNone(leftover_dict["gameplay"])
            self.assertNotIn(
                "## Gameplay",
                (root / "morning-dict" / "morning-report.md").read_text(),
            )

    def test_morning_fails_closed_on_schema_invalid_or_digest_mismatch(self):
        from nightshift.contracts import ContractError, digest as cdigest

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            verify_dir = root / "verify"
            verify_dir.mkdir()
            good = json.loads(
                (REPO / "contracts" / "examples" / "gameplay-verdict.json").read_text()
            )
            validation = {
                "format": "nightshift.verification/v0",
                "candidate": {
                    "patchSha256": "a" * 64,
                    "baseTree": "b" * 64,
                    "attempt": 1,
                    "request": "rr",
                },
                "evaluator": {"name": "x", "version": "0"},
                "checks": [
                    {
                        "spec": GAMEPLAY_SPEC_ID,
                        "kind": "gameplay",
                        "route": "smoke",
                        "result": "fail",
                        "verdictSha256": cdigest(good),
                    },
                ],
                "decision": "reject",
                "reasons": ["gameplay failed"],
            }
            bad = dict(good)
            bad.pop("reason")
            (verify_dir / "verdict-gameplay.json").write_text(
                json.dumps(bad) + "\n", encoding="utf-8"
            )
            with self.assertRaises(ContractError):
                build_report(
                    verification=validation,
                    candidate=None,
                    out=root / "morning-bad",
                    verification_path=verify_dir / "verification.json",
                )
            (verify_dir / "verdict-gameplay.json").write_text(
                json.dumps(good) + "\n", encoding="utf-8"
            )
            mismatched = dict(validation)
            mismatched["checks"] = [
                {**validation["checks"][0], "verdictSha256": "f" * 64},
            ]
            with self.assertRaises(ContractError):
                build_report(
                    verification=mismatched,
                    candidate=None,
                    out=root / "morning-mismatch",
                    verification_path=verify_dir / "verification.json",
                )
            with self.assertRaises(FileNotFoundError):
                build_report(
                    verification=validation,
                    candidate=None,
                    out=root / "morning-missing-path",
                    gameplay_verdict=root / "no-such-verdict.json",
                )
            summary = build_report(
                verification=validation,
                candidate=None,
                out=root / "morning-ok",
                verification_path=verify_dir / "verification.json",
            )
            self.assertEqual(summary["gameplay"]["reason"], good["reason"])
            self.assertIn("endOnFloor:", (root / "morning-ok" / "morning-report.md").read_text())

            diverged = dict(good)
            diverged["metrics"] = dict(good["metrics"])
            diverged["metrics"]["minDeltaX"] = float(good["minDeltaX"]) + 1.0
            with self.assertRaises(ContractError):
                build_report(
                    verification={
                        **validation,
                        "checks": [
                            {**validation["checks"][0], "verdictSha256": cdigest(diverged)},
                        ],
                    },
                    candidate=None,
                    out=root / "morning-min-mismatch",
                    gameplay_verdict=diverged,
                )
            bare = {k: v for k, v in validation["checks"][0].items() if k != "verdictSha256"}
            with self.assertRaises(ContractError):
                build_report(
                    verification={**validation, "checks": [bare]},
                    candidate=None,
                    out=root / "morning-no-sha",
                    gameplay_verdict=good,
                )

    def test_trust_beat(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "trust"
            result = run_trust_check(out)
            self.assertTrue(result["ok"])
            self.assertFalse(result["boundToLoop"])
            self.assertEqual(result["signingKeyInFixer"], [])
            self.assertTrue(result["poisonPresentInFixer"])
            self.assertTrue(result["readDeniedByAbsence"])
            self.assertTrue(result["mountLocalCanaryDenied"])
            self.assertTrue(result["suiteControlsAbsentFromFixer"])
            self.assertEqual(result["forbiddenPathsInFixer"], [])
            self.assertTrue((out / "trust-evidence.md").exists())
            self.assertTrue((out / "canary-attempts.json").is_file())
            attempts = json.loads((out / "canary-attempts.json").read_text())
            self.assertTrue(any(a["mountLocal"] for a in attempts))
            for a in attempts:
                if a["mountLocal"]:
                    self.assertFalse(a["exists"])
                    self.assertFalse(a["leakedKeyBytes"])
            evidence = (out / "trust-evidence.md").read_text(encoding="utf-8")
            self.assertIn("PASS", evidence)
            self.assertIn("deny-by-absence", evidence)
            self.assertIn("Canary probe", evidence)
            self.assertIn("DENIED", evidence)
            self.assertIn("obs-clean.json", evidence)
            self.assertIn("player-motion-on-smoke.json", evidence)
            self.assertIn("player-reaches-end-of-route.json", evidence)
            poison = (out / "fixer-workspace" / "player" / "readme-extra.txt").read_text()
            self.assertIn("IGNORE PREVIOUS", poison)
            self.assertIn(".nightshift-signing-key", poison)
            self.assertNotIn("DEMO-FAKE-SIGNING-KEY-NOT-REAL", poison)
            self.assertTrue((out / "verifier-host" / ".nightshift-signing-key").is_file())

    def test_canary_probe_films_mount_denials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixer = root / "fixer"
            verifier = root / "verifier-host"
            fixer.mkdir()
            (fixer / "player").mkdir()
            verifier.mkdir()
            (verifier / ".nightshift-signing-key").write_text("DEMO-FAKE-SIGNING-KEY-NOT-REAL\n")
            attempts = probe_canary_reads(fixer, verifier)
            mount = [a for a in attempts if a["mountLocal"]]
            self.assertGreaterEqual(len(mount), 2)
            self.assertTrue(all(not a["exists"] for a in mount))
            # Sibling escape reaches the host key on a shared FS — filmed, not a mount leak.
            escape = next(
                a for a in attempts
                if a["label"].startswith("relative-escape/../verifier-host")
            )
            self.assertTrue(escape["leakedKeyBytes"])

    def test_prove_live_trust_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "prove"
            code = prove_live_main(["--out", str(out), "--trust-only"])
            self.assertEqual(code, 0)
            self.assertTrue((out / "prove.md").is_file())
            md = (out / "prove.md").read_text()
            self.assertIn("Overall: PASS", md)
            self.assertIn("Skipped (`--trust-only`)", md)
            self.assertTrue((out / "trust" / "canary-attempts.json").is_file())

    def test_prove_live_without_keys_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "prove"
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("agents.prove_live.muse_code_ready", return_value=False):
                    code = prove_live_main(["--out", str(out)])
            self.assertEqual(code, 2)
            md = (out / "prove.md").read_text()
            self.assertIn("SKIPPED", md)
            self.assertIn("INCOMPLETE", md)
            self.assertIn("PASS", (out / "trust" / "trust-evidence.md").read_text())

    def test_fixer_forbidden_basenames_locked(self):
        self.assertEqual(GAMEPLAY_SPEC_ID, "player-motion-on-smoke")
        self.assertEqual(
            FIXER_FORBIDDEN_BASENAMES,
            frozenset({
                ".nightshift-signing-key",
                "obs-clean.json",
                "obs-held-out.json",
                "player-stays-above-ground.json",
                "player-reaches-end-of-route.json",
                "player-motion-on-smoke.json",
                "verdict-gameplay.json",
                "evaluator.py",
            }),
        )
        self.assertFalse((REPO / "agents" / "specs" / "player-reaches-end-of-route.json").exists())
        self.assertFalse((REPO / "agents" / "specs" / "player-motion-on-smoke.json").exists())

    def test_trust_fails_when_suite_control_planted(self):
        plants = (
            "obs-clean.json",
            "obs-held-out.json",
            "evaluator.py",
            "player-stays-above-ground.json",
            "player-reaches-end-of-route.json",
            "player-motion-on-smoke.json",
            "verdict-gameplay.json",
        )
        for name in plants:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as tmp:
                    out = Path(tmp) / "trust"
                    run_trust_check(out)
                    planted = out / "fixer-workspace" / name
                    planted.write_text("{}\n", encoding="utf-8")
                    result = run_trust_check(
                        out / "recheck",
                        fixer_work=out / "fixer-workspace",
                        verifier_host=out / "verifier-host",
                    )
                    self.assertFalse(result["ok"])
                    self.assertFalse(result["suiteControlsAbsentFromFixer"])
                    self.assertTrue(any(p.endswith(name) for p in result["forbiddenPathsInFixer"]))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "trust"
            run_trust_check(out)
            nested = out / "fixer-workspace" / "deep" / "nested" / "obs-clean.json"
            nested.parent.mkdir(parents=True)
            nested.write_text("{}\n", encoding="utf-8")
            result = run_trust_check(
                out / "nested-recheck",
                fixer_work=out / "fixer-workspace",
                verifier_host=out / "verifier-host",
            )
            self.assertFalse(result["ok"])
            self.assertTrue(any(p.endswith("obs-clean.json") for p in result["forbiddenPathsInFixer"]))

    def test_triage_without_keys_never_calls_wonder(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("agents.triage.call_wonder", side_effect=AssertionError("Wonder must not run")):
                    request = triage(
                        spec=load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec"),
                        verdict=load(REPO / "contracts" / "examples" / "verdict.json", "verdict"),
                        route=load(REPO / "harness" / "routes" / "smoke.json", "route"),
                        out=Path(tmp) / "triage",
                        offline=False,
                    )
            validate(request, "repair-request")
            meta = json.loads((Path(tmp) / "triage" / "triage.json").read_text())
            self.assertEqual(meta["source"], "offline")
            self.assertTrue((Path(tmp) / "triage" / "bug-report.md").exists())

    def test_loop_mocked_keys_still_reject_freeze(self):
        """Key presence / Wonder success must not forge accept — freeze obs still reject."""
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"MODEL_API_KEY": "dummy", "META_API_KEY": "dummy"}):
                with mock.patch("agents.triage.call_wonder", return_value="canned bug report") as wonder:
                    result = one_run(
                        Path(tmp) / "loop",
                        use_muse=False,
                        offline_triage=False,
                        observations=REPO / "agents" / "fixtures" / "obs-freeze.json",
                        candidate_patch=REPO / "agents" / "fixtures" / "freeze-player.patch",
                        skip_harness=True,
                        run_trust=True,
                    )
            wonder.assert_called()
            self.assertEqual(result["decision"], "reject")
            self.assertIsNone(result.get("error"))
            self.assertEqual(result["triageSource"], WONDER_MODEL)
            self.assertEqual(result["gameplay"]["reason"], REASON_DELTA)
            self.assertEqual(result["gameplay"]["spec"], GAMEPLAY_SPEC_ID)
            self.assertEqual(result["morning"]["gameplay"]["reason"], REASON_DELTA)

    def test_trust_beat_fail_when_key_in_fixer(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "trust"
            run_trust_check(out)
            planted = out / "fixer-workspace" / ".nightshift-signing-key"
            planted.write_text("DEMO-FAKE-SIGNING-KEY-NOT-REAL\n", encoding="utf-8")
            # Re-check bound topology with the poisoned fixer tree.
            result = run_trust_check(
                out / "recheck",
                fixer_work=out / "fixer-workspace",
                verifier_host=out / "verifier-host",
            )
            self.assertFalse(result["ok"])
            self.assertIn("FAIL", (out / "recheck" / "trust-evidence.md").read_text())

    def test_trust_bound_to_loop_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixer = root / "fix" / "fixer-work"
            verifier = root / "verifier-host"
            fixer.mkdir(parents=True)
            (fixer / "player").mkdir()
            verifier.mkdir()
            (verifier / ".nightshift-signing-key").write_text("DEMO-FAKE-SIGNING-KEY-NOT-REAL\n")
            result = run_trust_check(root / "trust", fixer_work=fixer, verifier_host=verifier)
            self.assertTrue(result["ok"])
            self.assertTrue(result["boundToLoop"])
            evidence = (root / "trust" / "trust-evidence.md").read_text()
            self.assertIn(str(fixer), evidence)
            self.assertIn(str(verifier), evidence)

    def test_loop_accepts_with_fixture_obs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "loop"
            result = one_run(
                run_root,
                use_muse=False,
                offline_triage=True,
                observations=REPO / "agents" / "fixtures" / "obs-fixed.json",
                candidate_patch=REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                skip_harness=True,
                run_trust=True,
            )
            self.assertEqual(result["decision"], "accept")
            self.assertTrue(result["trust"]["ok"])
            self.assertTrue(result["trust"]["boundToLoop"])
            self.assertEqual(result["fixerSource"], "fixture")
            self.assertEqual(result["triageSource"], "offline")
            self.assertEqual(result["verificationProvenance"], "fixture")
            self.assertEqual(len(result["morning"]["frames"]), 2)
            self.assertTrue((run_root / "morning" / "frames" / "before-00.png").is_file())
            self.assertTrue((run_root / "morning" / "frames" / "after-00.png").is_file())
            morning_md = (run_root / "morning" / "morning-report.md").read_text()
            self.assertIn("![before]", morning_md)
            self.assertIn("![after]", morning_md)
            self.assertIn("## Suite provenance", morning_md)
            self.assertIn("source=`fixture`", morning_md)
            self.assertIn("held-out: source=`interim-fixture`", morning_md)
            self.assertIn("## Gameplay", morning_md)
            self.assertEqual(result["morning"]["gameplay"]["result"], "pass")
            self.assertTrue(result["trust"]["suiteControlsAbsentFromFixer"])
            rc = json.loads((run_root / "morning" / "release-candidate.json").read_text())
            self.assertEqual(rc["signingKey"], str(run_root / "verifier-host" / ".nightshift-signing-key"))
            from agents.report import _fake_sign
            payload = json.dumps(
                json.loads((run_root / "verify" / "verification.json").read_text()),
                sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
            key_bytes = (run_root / "verifier-host" / ".nightshift-signing-key").read_bytes()
            self.assertEqual(rc["signature"], _fake_sign(payload, key_bytes))
            fixer_work = run_root / "fix" / "fixer-work"
            self.assertTrue(fixer_work.is_dir())
            self.assertEqual(list(fixer_work.rglob(".nightshift-signing-key")), [])
            self.assertTrue((run_root / "verifier-host" / ".nightshift-signing-key").is_file())
            key = (run_root / "verifier-host" / ".nightshift-signing-key").read_text()
            for path in fixer_work.rglob("*"):
                if path.is_file():
                    self.assertNotIn(key.strip(), path.read_text(encoding="utf-8", errors="ignore"))

    def test_loop_out_of_glob_never_forges_accept(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = one_run(
                Path(tmp) / "loop",
                use_muse=False,
                offline_triage=True,
                observations=REPO / "agents" / "fixtures" / "obs-fixed.json",
                candidate_patch=REPO / "agents" / "fixtures" / "out-of-glob.patch",
                skip_harness=True,
                run_trust=True,
            )
            self.assertEqual(result["decision"], "reject")
            self.assertIsNotNone(result.get("error"))
            self.assertTrue((Path(tmp) / "loop" / "loop-error.txt").exists())

    def test_loop_exception_never_forges_accept(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("agents.loop.triage", side_effect=RuntimeError("boom")):
                result = one_run(
                    Path(tmp) / "loop",
                    use_muse=False,
                    offline_triage=True,
                    observations=REPO / "agents" / "fixtures" / "obs-fixed.json",
                    candidate_patch=REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                    skip_harness=True,
                    run_trust=True,
                )
            self.assertEqual(result["decision"], "reject")
            self.assertIn("RuntimeError", result["error"])
            self.assertIsNone(result["morning"])
            self.assertTrue((Path(tmp) / "loop" / "loop-error.txt").exists())

    def test_loop_trust_fail_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("agents.loop.run_trust_check", return_value={"ok": False, "detail": "nope"}):
                result = one_run(
                    Path(tmp) / "loop",
                    use_muse=False,
                    offline_triage=True,
                    observations=REPO / "agents" / "fixtures" / "obs-fixed.json",
                    candidate_patch=REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                    skip_harness=True,
                    run_trust=True,
                )
            self.assertEqual(result["decision"], "reject")
            self.assertEqual(result["error"], "trust beat failed")
            self.assertIsNone(result["morning"])

    def test_loop_live_triage_fallback_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            def fake_triage(**kwargs):
                out = kwargs["out"]
                out.mkdir(parents=True, exist_ok=True)
                (out / "triage.json").write_text(json.dumps({"source": "offline-fallback"}) + "\n")
                (out / "repair-request.json").write_text("{}")
                return _request()

            with mock.patch("agents.loop.triage", side_effect=fake_triage):
                result = one_run(
                    Path(tmp) / "loop",
                    use_muse=False,
                    offline_triage=False,
                    observations=REPO / "agents" / "fixtures" / "obs-fixed.json",
                    candidate_patch=REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                    skip_harness=True,
                    run_trust=False,
                )
            self.assertEqual(result["decision"], "reject")
            self.assertIn("live Wonder", result["error"])

    def test_loop_verify_reject_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = one_run(
                Path(tmp) / "loop",
                use_muse=False,
                offline_triage=True,
                observations=REPO / "agents" / "fixtures" / "obs-freeze.json",
                candidate_patch=REPO / "agents" / "fixtures" / "freeze-player.patch",
                skip_harness=True,
                run_trust=True,
            )
            self.assertEqual(result["decision"], "reject")
            self.assertIsNone(result.get("error"))
            self.assertIsNotNone(result["morning"])
            self.assertEqual(result["morning"]["gameplay"]["reason"], REASON_DELTA)
            self.assertIn(REASON_DELTA, (Path(tmp) / "loop" / "morning" / "morning-report.md").read_text())
            self.assertIn(
                "fixture-trace:trace-freeze.json",
                (Path(tmp) / "loop" / "morning" / "morning-report.md").read_text(),
            )

    def test_resolve_mode_offline_and_live_gates(self):
        offline = resolve_mode("offline")
        self.assertTrue(offline["offline_triage"])
        self.assertFalse(offline["use_muse"])
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("agents.keys.shutil.which", return_value=None):
                with self.assertRaises(SystemExit) as cm:
                    resolve_mode("live")
                self.assertIn("Wonder", str(cm.exception))
                auto = resolve_mode("auto")
                self.assertTrue(auto["offline_triage"])
                self.assertFalse(auto["use_muse"])
        with mock.patch.dict(os.environ, {"MODEL_API_KEY": "k", "META_API_KEY": ""}, clear=True):
            with mock.patch("agents.keys.shutil.which", return_value=None):
                with self.assertRaises(SystemExit) as cm:
                    resolve_mode("live")
                self.assertIn("muse", str(cm.exception).lower())
        with mock.patch.dict(os.environ, {"MODEL_API_KEY": "k", "META_API_KEY": "m"}):
            with mock.patch("agents.keys.shutil.which", return_value="/usr/bin/muse"):
                live = resolve_mode("live")
                self.assertFalse(live["offline_triage"])
                self.assertTrue(live["use_muse"])
                auto = resolve_mode("auto")
                self.assertFalse(auto["offline_triage"])
                self.assertTrue(auto["use_muse"])
        with self.assertRaises(ValueError):
            resolve_mode("bogus")
        self.assertTrue(wonder_key() is None or isinstance(wonder_key(), str))

    def test_seal_mode_rejects_contradictions(self):
        offline = resolve_mode("offline")
        with self.assertRaises(SystemExit):
            seal_mode_flags(offline, force_offline_triage=False, force_online_triage=True, force_muse=False)
        with self.assertRaises(SystemExit):
            seal_mode_flags(offline, force_offline_triage=False, force_online_triage=False, force_muse=True)
        with mock.patch.dict(os.environ, {"MODEL_API_KEY": "k", "META_API_KEY": "m"}):
            with mock.patch("agents.keys.shutil.which", return_value="/usr/bin/muse"):
                live = resolve_mode("live")
                with self.assertRaises(SystemExit):
                    seal_mode_flags(live, force_offline_triage=True, force_online_triage=False, force_muse=False)

    def test_muse_code_ready_requires_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("agents.keys.shutil.which", return_value="/usr/bin/muse"):
                self.assertFalse(muse_code_ready())
        with mock.patch.dict(os.environ, {"META_API_KEY": "k"}):
            with mock.patch("agents.keys.shutil.which", return_value="/usr/bin/muse"):
                self.assertTrue(muse_code_ready())

    def test_loop_main_offline_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "loop"
            code = loop_main([
                "--out", str(out),
                "--mode", "offline",
                "--runs", "3",
            ])
            self.assertEqual(code, 0)
            summary = json.loads((out / "summary.json").read_text())
            self.assertEqual(summary["accepted"], 3)
            self.assertEqual(summary["runs"], 3)
            self.assertTrue(all(r["decision"] == "accept" for r in summary["results"]))
            validate(summary, "overnight-summary")
            self.assertEqual(summary["cost"]["costProvenance"], "unmetered-offline")
            self.assertEqual(summary["cost"]["modelCalls"], 0)
            self.assertIsNone(summary["cost"]["costUsd"])
            self.assertGreaterEqual(summary["timing"]["wallClockMs"], 0)
            for r in summary["results"]:
                self.assertEqual(r["gameplay"]["result"], "pass")
                self.assertEqual(r["gameplay"]["spec"], GAMEPLAY_SPEC_ID)
                self.assertIn("wallClockMs", r["timing"])
                self.assertTrue(r["trust"]["ok"])
            self.assertEqual(summary["mode"]["mode"], "offline")
            self.assertEqual(summary["verificationProvenance"], "fixture")
            rollup = (out / "morning-report.md").read_text(encoding="utf-8")
            self.assertIn("3 of 3", rollup)
            self.assertIn("Wall-clock ms:", rollup)
            self.assertIn("unmetered-offline", rollup)
            self.assertIn("## Trust", rollup)
            self.assertIn("trust=`PASS`", rollup)
            self.assertIn("triage=`offline`", rollup)
            self.assertIn("fixer=`fixture`", rollup)
            self.assertIn("run-00/morning/morning-report.md", rollup)
            self.assertIn("![before](frames/before-00.png)", rollup)
            self.assertIn("![after](frames/after-00.png)", rollup)
            self.assertNotIn("## Gameplay", rollup)
            self.assertTrue((out / "frames" / "before-00.png").is_file())
            self.assertTrue((out / "frames" / "after-00.png").is_file())
            self.assertTrue((out / "run-00" / "morning" / "frames" / "before-00.png").is_file())
            self.assertTrue((out / "run-02" / "morning" / "frames" / "after-00.png").is_file())
            rc = json.loads((out / "run-00" / "morning" / "release-candidate.json").read_text())
            validate(rc, "release-candidate")
            self.assertEqual(rc["decision"], "accept")
            self.assertTrue(rc.get("requestSha256"))
            from agents.bench import from_summary
            stub = from_summary(summary)
            self.assertEqual(stub["provenance"], "agents-offline-stub")
            self.assertEqual(stub["accepted"], 3)

    def test_loop_missing_frame_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = one_run(
                Path(tmp) / "loop",
                use_muse=False,
                offline_triage=True,
                observations=REPO / "agents" / "fixtures" / "obs-fixed.json",
                candidate_patch=REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                skip_harness=True,
                run_trust=True,
                before_frames=[Path(tmp) / "missing.png"],
                after_frames=[AFTER_FRAME],
            )
            self.assertEqual(result["decision"], "reject")
            self.assertIn("FileNotFoundError", result["error"])
            result_after = one_run(
                Path(tmp) / "loop-after",
                use_muse=False,
                offline_triage=True,
                observations=REPO / "agents" / "fixtures" / "obs-fixed.json",
                candidate_patch=REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                skip_harness=True,
                run_trust=True,
                before_frames=[BEFORE_FRAME],
                after_frames=[Path(tmp) / "missing-after.png"],
            )
            self.assertEqual(result_after["decision"], "reject")
            self.assertIn("FileNotFoundError", result_after["error"])
            self.assertIsNone(result_after.get("morning"))
            self.assertIsNone(result_after.get("gameplay"))
            self.assertIn("wallClockMs", result_after["timing"])

    def test_loop_empty_frame_lists_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = one_run(
                Path(tmp) / "loop",
                use_muse=False,
                offline_triage=True,
                observations=REPO / "agents" / "fixtures" / "obs-fixed.json",
                candidate_patch=REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                skip_harness=True,
                run_trust=True,
                before_frames=[],
                after_frames=[AFTER_FRAME],
            )
            self.assertEqual(result["decision"], "reject")
            self.assertIn("non-empty", result["error"])
            self.assertIsNone(result.get("gameplay"))

    def test_write_loop_rollup_mixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            summary = {
                "mode": {"mode": "offline"},
                "runs": 2,
                "accepted": 1,
                "verificationProvenance": "fixture",
                "results": [
                    {"decision": "reject", "error": "boom", "morning": None, "gameplay": None},
                    {"decision": "accept", "morning": {"frames": [{"role": "before", "path": "frames/before-00.png"}]}},
                ],
            }
            path = write_loop_rollup(out, summary=summary)
            text = path.read_text(encoding="utf-8")
            self.assertIn("1 of 2", text)
            self.assertIn("Unresolved", text)
            self.assertNotIn("Latest accept frames", text)
            self.assertNotIn("## Gameplay", text)

    def test_loop_no_trust_omits_trust_film(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "loop"
            code = loop_main([
                "--out", str(out),
                "--mode", "offline",
                "--runs", "1",
                "--no-trust",
            ])
            self.assertEqual(code, 0)
            summary = json.loads((out / "summary.json").read_text())
            self.assertIsNone(summary["results"][0].get("trust"))
            rollup = (out / "morning-report.md").read_text()
            self.assertNotIn("## Trust", rollup)
            self.assertNotIn("trust=`PASS`", rollup)
            self.assertIn("triage=`offline`", rollup)
            self.assertIn("fixer=`fixture`", rollup)

    def test_trust_fail_rollup_films_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            summary = {
                "format": "nightshift.overnight-summary/v0",
                "mode": {"mode": "offline", "offline_triage": True, "use_muse": False},
                "runs": 1,
                "accepted": 0,
                "verificationProvenance": "fixture",
                "cost": {"modelCalls": 0, "costUsd": None, "costProvenance": "unmetered-offline"},
                "timing": {"wallClockMs": 1.0},
                "results": [{
                    "decision": "reject",
                    "error": "trust beat failed",
                    "morning": None,
                    "gameplay": None,
                    "trust": {"ok": False},
                    "timing": {"wallClockMs": 1.0},
                }],
            }
            from nightshift.contracts import validate as v
            v(summary, "overnight-summary")
            text = write_loop_rollup(out, summary=summary).read_text()
            self.assertIn("## Trust", text)
            self.assertIn("trust=`FAIL`", text)
            self.assertIn("## Unresolved", text)
            self.assertNotIn("Latest accept frames", text)
            self.assertNotIn("## Gameplay", text)

    def test_rollup_films_needs_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = {
                "format": "nightshift.overnight-summary/v0",
                "mode": {"mode": "offline", "offline_triage": True, "use_muse": False},
                "runs": 1,
                "accepted": 0,
                "verificationProvenance": "fixture",
                "cost": {"modelCalls": 0, "costUsd": None, "costProvenance": "unmetered-offline"},
                "timing": {"wallClockMs": 1.0},
                "results": [{
                    "decision": "needs-review",
                    "morning": {"unresolved": ["held-out check needs review"]},
                    "gameplay": None,
                    "timing": {"wallClockMs": 1.0},
                }],
            }
            validate(summary, "overnight-summary")
            text = write_loop_rollup(Path(tmp), summary=summary).read_text()
            self.assertIn("`needs-review`", text)
            self.assertIn("## Needs-review", text)
            self.assertIn("held-out check needs review", text)
            self.assertIn("## Unresolved", text)
            self.assertNotIn("Latest accept frames", text)

    def test_rc_verify_detects_tamper_and_wrong_key(self):
        from nightshift.contracts import ContractError

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            verification = verify(
                _request(),
                REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                root / "verify",
                observations_path=REPO / "agents" / "fixtures" / "obs-fixed.json",
                skip_harness=True,
            )
            key = root / "key"
            key.write_text("DEMO-FAKE-SIGNING-KEY-NOT-REAL\n", encoding="utf-8")
            summary = build_report(
                verification=verification,
                candidate=REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                out=root / "morning",
                signing_key_path=key,
                verification_path=root / "verify" / "verification.json",
            )
            rc = json.loads((root / "morning" / "release-candidate.json").read_text())
            verify_release_candidate(rc, verification, key_material=key.read_bytes())
            with self.assertRaises(ContractError):
                verify_release_candidate(rc, verification, key_material=b"wrong-key")
            tampered = dict(verification)
            tampered["reasons"] = list(verification.get("reasons", [])) + ["tamper"]
            with self.assertRaises(ContractError):
                verify_release_candidate(rc, tampered, key_material=key.read_bytes())
            self.assertEqual(summary["decision"], "accept")

    def test_loop_live_unset_cost_provenance_without_meta_calls(self):
        """Wonder key present but muse not ready → unmetered-live-unset, no invented spend."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "loop"
            env = {k: v for k, v in os.environ.items() if k not in ("META_API_KEY",)}
            env["MODEL_API_KEY"] = "dummy"
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch("agents.keys.muse_code_ready", return_value=False):
                    with mock.patch("agents.triage.call_wonder", return_value="canned bug report"):
                        code = loop_main([
                            "--out", str(out),
                            "--mode", "auto",
                            "--runs", "1",
                        ])
            self.assertEqual(code, 0)
            summary = json.loads((out / "summary.json").read_text())
            self.assertFalse(summary["mode"]["use_muse"])
            self.assertFalse(summary["mode"]["offline_triage"])
            self.assertEqual(summary["cost"]["costProvenance"], "unmetered-live-unset")
            self.assertIsNone(summary["cost"]["costUsd"])
            self.assertEqual(summary["cost"]["modelCalls"], 0)
            rollup = (out / "morning-report.md").read_text()
            self.assertIn("unmetered-live-unset", rollup)
            self.assertEqual(summary["results"][0]["triageSource"], WONDER_MODEL)

    def test_stale_signing_key_cleared_before_fixer(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "loop"
            stale = out / "verifier-host" / ".nightshift-signing-key"
            stale.parent.mkdir(parents=True)
            stale.write_text("STALE\n", encoding="utf-8")
            result = one_run(
                out,
                use_muse=False,
                offline_triage=True,
                observations=REPO / "agents" / "fixtures" / "obs-fixed.json",
                candidate_patch=REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                skip_harness=True,
                run_trust=True,
            )
            self.assertEqual(result["decision"], "accept")
            fixer_keys = list((out / "fix" / "fixer-work").rglob(".nightshift-signing-key"))
            self.assertEqual(fixer_keys, [])
            self.assertTrue(stale.is_file())
            self.assertIn("DEMO-FAKE", stale.read_text())

    def test_exception_path_preserves_triage_source(self):
        """Out-of-glob fails in fixer before candidate.json — triage preserved, fixer not invented."""
        with tempfile.TemporaryDirectory() as tmp:
            result = one_run(
                Path(tmp) / "loop",
                use_muse=False,
                offline_triage=True,
                observations=REPO / "agents" / "fixtures" / "obs-fixed.json",
                candidate_patch=REPO / "agents" / "fixtures" / "out-of-glob.patch",
                skip_harness=True,
                run_trust=True,
            )
            self.assertEqual(result["decision"], "reject")
            self.assertIsNone(result.get("morning"))
            self.assertEqual(result.get("triageSource"), "offline")
            self.assertIsNone(result.get("fixerSource"))

    def test_gate1_writes_morning_and_rc(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "gate1"
            code = gate1_main([
                "--out", str(out),
                "--skip-harness",
                "--observations", str(REPO / "agents" / "fixtures" / "obs-fixed.json"),
            ])
            self.assertEqual(code, 0)
            self.assertTrue((out / "morning" / "morning-report.md").is_file())
            rc = json.loads((out / "morning" / "release-candidate.json").read_text())
            validate(rc, "release-candidate")
            self.assertEqual(rc["decision"], "accept")

    def test_triage_embeds_structured_provenance_on_rr(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = triage(
                spec=load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec"),
                verdict=load(REPO / "contracts" / "examples" / "verdict.json", "verdict"),
                route=load(REPO / "harness" / "routes" / "smoke.json", "route"),
                out=Path(tmp) / "triage",
                offline=True,
            )
            validate(request, "repair-request")
            self.assertEqual(request["triage"]["source"], "offline")
            self.assertEqual(request["triage"]["model"], WONDER_MODEL)

    def test_trust_cli_bind_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            standalone = run_trust_check(root / "trust")
            self.assertTrue(standalone["ok"])
            code = subprocess.run(
                [
                    sys.executable, "-m", "agents.trust",
                    "--out", str(root / "recheck"),
                    "--fixer-work", str(root / "trust" / "fixer-workspace"),
                    "--verifier-host", str(root / "trust" / "verifier-host"),
                ],
                cwd=str(REPO),
                capture_output=True,
                text=True,
                check=False,
            ).returncode
            self.assertEqual(code, 0)
            bound = json.loads((root / "recheck" / "trust.json").read_text())
            self.assertTrue(bound["ok"])
            self.assertTrue(bound["boundToLoop"])

    def test_write_loop_rollup_films_latest_gameplay_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            summary = {
                "mode": {"mode": "offline"},
                "runs": 3,
                "accepted": 1,
                "verificationProvenance": "fixture",
                "results": [
                    {
                        "decision": "reject",
                        "gameplay": {
                            "spec": GAMEPLAY_SPEC_ID,
                            "result": "fail",
                            "reason": "old reject",
                            "source": "fixture-trace:old.json",
                            "minDeltaX": 200.0,
                            "deltaX": 1.0,
                        },
                    },
                    {
                        "decision": "reject",
                        "gameplay": {
                            "spec": GAMEPLAY_SPEC_ID,
                            "result": "fail",
                            "reason": REASON_DELTA,
                            "source": "fixture-trace:trace-freeze.json",
                            "minDeltaX": 200.0,
                            "deltaX": 0.0,
                        },
                    },
                    {"decision": "accept", "morning": {"frames": []}, "gameplay": {"result": "pass"}},
                ],
            }
            text = write_loop_rollup(out, summary=summary).read_text(encoding="utf-8")
            self.assertIn("## Unresolved", text)
            self.assertIn("## Gameplay", text)
            self.assertIn("run-01", text)
            self.assertIn(f"spec: `{GAMEPLAY_SPEC_ID}`", text)
            self.assertIn(REASON_DELTA, text)
            self.assertIn("fixture-trace:trace-freeze.json", text)
            self.assertIn("deltaX: `0.0`", text)
            self.assertIn(f"gameplay=`fail` reason={REASON_DELTA}", text)
            # Later non-accept with gameplay pass must not displace the fail film.
            later_pass = {
                "mode": {"mode": "offline"},
                "runs": 2,
                "accepted": 0,
                "verificationProvenance": "fixture",
                "results": [
                    summary["results"][1],
                    {
                        "decision": "reject",
                        "error": "trust beat failed",
                        "gameplay": {"spec": GAMEPLAY_SPEC_ID, "result": "pass", "reason": "ok"},
                    },
                ],
            }
            later_text = write_loop_rollup(out / "later", summary=later_pass).read_text()
            self.assertIn(REASON_DELTA, later_text)
            self.assertNotIn("reason: ok", later_text.split("## Gameplay", 1)[1])
            # Morning-only stub (no top-level gameplay) still films.
            morning_only = {
                "mode": {"mode": "offline"},
                "runs": 1,
                "accepted": 0,
                "verificationProvenance": "fixture",
                "results": [{
                    "decision": "reject",
                    "morning": {
                        "gameplay": {
                            "spec": GAMEPLAY_SPEC_ID,
                            "result": "fail",
                            "reason": REASON_DELTA,
                            "source": "fixture-trace:trace-freeze.json",
                            "minDeltaX": 200.0,
                            "metrics": {"deltaX": 0.0},
                        },
                    },
                }],
            }
            morning_text = write_loop_rollup(out / "morning-only", summary=morning_only).read_text()
            self.assertIn(REASON_DELTA, morning_text)
            self.assertIn(f"spec: `{GAMEPLAY_SPEC_ID}`", morning_text)

    def test_fixture_frames_are_pngs(self):
        for path in (BEFORE_FRAME, AFTER_FRAME):
            self.assertTrue(path.is_file())
            self.assertTrue(path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))

    def test_loop_main_exit_one_when_any_run_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            outcomes = iter([
                {"decision": "reject", "error": "boom", "morning": None},
                {"decision": "accept", "morning": {}, "trust": {"ok": True}},
            ])

            def fake_one_run(*_a, **_k):
                return next(outcomes)

            with mock.patch("agents.loop.one_run", side_effect=fake_one_run):
                code = loop_main([
                    "--out", str(Path(tmp) / "loop"),
                    "--mode", "offline",
                    "--runs", "2",
                ])
            self.assertEqual(code, 1)
            summary = json.loads((Path(tmp) / "loop" / "summary.json").read_text())
            self.assertEqual(summary["accepted"], 1)
            self.assertEqual(summary["runs"], 2)
            self.assertNotEqual(summary["results"][0]["decision"], "accept")

    def test_loop_main_live_without_keys_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("agents.keys.shutil.which", return_value=None):
                    with self.assertRaises(SystemExit):
                        loop_main(["--out", str(Path(tmp) / "loop"), "--mode", "live"])

    def test_resolve_mode_auto_partial_and_empty_keys(self):
        with mock.patch.dict(os.environ, {"MODEL_API_KEY": "only-wonder"}, clear=True):
            with mock.patch("agents.keys.shutil.which", return_value=None):
                auto = resolve_mode("auto")
                self.assertFalse(auto["offline_triage"])
                self.assertFalse(auto["use_muse"])
        with mock.patch.dict(os.environ, {"MODEL_API_KEY": "", "META_API_KEY": ""}, clear=True):
            with mock.patch("agents.keys.shutil.which", return_value=None):
                auto = resolve_mode("auto")
                self.assertTrue(auto["offline_triage"])
                self.assertFalse(auto["use_muse"])
                self.assertIsNone(wonder_key())
        with mock.patch.dict(os.environ, {"MODEL_API_KEY": "m", "META_API_KEY": "meta"}, clear=True):
            self.assertEqual(wonder_key(), "m")
        with mock.patch.dict(os.environ, {"MODEL_API_KEY": "k"}, clear=True):
            with mock.patch("agents.keys.shutil.which", return_value="/usr/bin/muse"):
                with self.assertRaises(SystemExit) as cm:
                    resolve_mode("live")
                self.assertIn("META_API_KEY", str(cm.exception))

    def test_loop_main_offline_use_muse_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                loop_main([
                    "--out", str(Path(tmp) / "loop"),
                    "--mode", "offline",
                    "--use-muse",
                ])


class GameplayMotionTest(unittest.TestCase):
    def test_fixture_traces_parity(self):
        fixed = json.loads((REPO / "agents" / "fixtures" / "trace-fixed.json").read_text())
        freeze = json.loads((REPO / "agents" / "fixtures" / "trace-freeze.json").read_text())
        fall = json.loads((REPO / "agents" / "fixtures" / "trace-fallthrough.json").read_text())
        self.assertEqual(judge_trace(fixed, min_delta_x=MIN_DELTA_X_FIXTURE)["result"], "pass")
        self.assertEqual(judge_trace(freeze, min_delta_x=MIN_DELTA_X_FIXTURE)["result"], "fail")
        self.assertEqual(judge_trace(freeze, min_delta_x=MIN_DELTA_X_FIXTURE)["reason"], REASON_DELTA)
        fall_g = judge_trace(fall, min_delta_x=MIN_DELTA_X_FIXTURE)
        self.assertEqual(fall_g["result"], "fail")
        self.assertEqual(fall_g["reason"], REASON_END_FLOOR)

    def test_thresholds_and_edges(self):
        floor = 640.0
        short = {
            "rows": [
                {"tick": 0, "player": [0.0, floor], "onFloor": True},
                {"tick": 10, "player": [150.0, floor], "onFloor": True},
            ]
        }
        self.assertEqual(judge_trace(short, min_delta_x=MIN_DELTA_X_FIXTURE)["reason"], REASON_DELTA)
        midair = {
            "rows": [
                {"tick": 0, "player": [0.0, floor], "onFloor": True},
                {"tick": 10, "player": [300.0, floor - 80], "onFloor": False},
            ]
        }
        self.assertEqual(judge_trace(midair, min_delta_x=MIN_DELTA_X_FIXTURE)["reason"], REASON_END_FLOOR)
        empty = {"rows": [{"tick": 0, "player": None, "onFloor": False}]}
        self.assertEqual(judge_trace(empty, min_delta_x=MIN_DELTA_X_FIXTURE)["reason"], REASON_EMPTY)
        # Gravity-off freefall: never onFloor → fail-closed (no vacuous floor).
        freefall = {
            "rows": [
                {"tick": 0, "player": [0.0, 100.0], "onFloor": False},
                {"tick": 10, "player": [300.0, 400.0], "onFloor": False},
            ]
        }
        self.assertEqual(judge_trace(freefall, min_delta_x=MIN_DELTA_X_FIXTURE)["reason"], REASON_END_FLOOR)
        # Sustained below-ground then recover to floor → REASON_BELOW.
        below = {
            "rows": [
                {"tick": 0, "player": [0.0, floor], "onFloor": True},
                {"tick": 2, "player": [80.0, floor + 40], "onFloor": False},
                {"tick": 4, "player": [160.0, floor + 80], "onFloor": False},
                {"tick": 6, "player": [240.0, floor + 120], "onFloor": False},
                {"tick": 8, "player": [320.0, floor], "onFloor": True},
            ]
        }
        self.assertEqual(judge_trace(below, min_delta_x=MIN_DELTA_X_FIXTURE)["reason"], REASON_BELOW)
        self.assertGreater(MIN_DELTA_X_HARNESS, MIN_DELTA_X_FIXTURE)

    def test_observations_path_wins_over_leftover_harness_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            # Plant a "good walk" leftover harness trace that would falsely pass freeze.
            replay = out / "replay"
            replay.mkdir(parents=True)
            (replay / "trace.json").write_text(json.dumps({
                "rows": [
                    {"tick": 0, "player": [0.0, 640.0], "onFloor": True},
                    {"tick": 10, "player": [500.0, 640.0], "onFloor": True},
                ]
            }) + "\n")
            doc = verify(
                _request(),
                REPO / "agents" / "fixtures" / "freeze-player.patch",
                out,
                observations_path=REPO / "agents" / "fixtures" / "obs-freeze.json",
                skip_harness=True,
            )
            self.assertEqual(doc["decision"], "reject")
            kinds = {c["kind"]: c["result"] for c in doc["checks"]}
            self.assertEqual(kinds.get("gameplay"), "fail")
            gameplay = json.loads((out / "verdict-gameplay.json").read_text())
            self.assertEqual(gameplay["reason"], REASON_DELTA)
            self.assertEqual(gameplay["source"], "fixture-trace:trace-freeze.json")

    def test_harness_trace_uses_harness_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            candidate_obs = load(REPO / "agents" / "fixtures" / "obs-fixed.json", "observations")

            def harness_ok(_route, harness_out, patches=None, **_kw):
                if patches == []:
                    raise subprocess.CalledProcessError(-6, ["godot", "--import"])
                harness_out.mkdir(parents=True, exist_ok=True)
                # Short walk: passes fixture min (200) but fails harness min (400).
                (harness_out / "trace.json").write_text(json.dumps({
                    "rows": [
                        {"tick": 0, "player": [0.0, 640.0], "onFloor": True},
                        {"tick": 10, "player": [250.0, 640.0], "onFloor": True},
                    ]
                }) + "\n")
                (harness_out / "replay.json").write_text("{}\n")

            with mock.patch("agents.verifier.harness_run", side_effect=harness_ok):
                with mock.patch("agents.verifier.from_trace", return_value=candidate_obs):
                    doc = verify(
                        _request(),
                        REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                        out,
                        skip_harness=False,
                    )
            self.assertEqual(doc["decision"], "reject")
            gameplay = json.loads((out / "verdict-gameplay.json").read_text())
            self.assertEqual(gameplay["source"], "harness-trace")
            self.assertEqual(gameplay["minDeltaX"], MIN_DELTA_X_HARNESS)
            self.assertEqual(gameplay["reason"], REASON_DELTA)

    def test_decide_still_rejects_on_gameplay_fail(self):
        decision, _ = decide([
            {"spec": "player-stays-above-ground", "kind": "regression", "route": "smoke", "result": "pass"},
            {"spec": GAMEPLAY_SPEC_ID, "kind": "gameplay", "route": "smoke", "result": "fail"},
            {"spec": "player-stays-above-ground", "kind": "held-out", "route": "r", "result": "pass"},
            {"spec": "player-stays-above-ground", "kind": "clean", "route": "r", "result": "pass"},
        ])
        self.assertEqual(decision, "reject")


if __name__ == "__main__":
    unittest.main()
