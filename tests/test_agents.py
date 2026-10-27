"""Agents lane: orchestrator, patchutil, fixer fixtures, verifier decide paths, trust, loop."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from agents.fixer import run_fixer
from agents.loop import one_run
from agents.observations import from_trace
from agents.orchestrator import build_repair_request
from agents.patchutil import assert_editable, paths_touched
from agents.report import build_report
from agents.triage import triage
from agents.trust import run_trust_check
from agents.verifier import verify
from harness.run import REPO, tree_digest
from nightshift.contracts import load, validate
from nightshift.evaluator import decide, evaluate


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
        game = load(REPO / "agents" / "specs" / "player-reaches-end-of-route.json", "test-spec")
        reg = {**reg, "window": {"fromFrame": 0, "toFrame": 20}}
        game = {**game, "window": {"fromFrame": 0, "toFrame": 20}}

        self.assertEqual(evaluate(reg, from_trace(fall))["result"], "fail")
        self.assertEqual(evaluate(reg, from_trace(walk))["result"], "pass")
        self.assertEqual(evaluate(game, from_trace(walk))["result"], "pass")
        self.assertEqual(evaluate(game, from_trace(freeze))["result"], "fail")

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
            )
            self.assertEqual(summary["decision"], "accept")
            self.assertTrue((root / "morning" / "release-candidate.json").exists())

    def test_trust_beat(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_trust_check(Path(tmp) / "trust")
            self.assertTrue(result["ok"])
            self.assertEqual(result["signingKeyInFixer"], [])

    def test_loop_accepts_with_fixture_obs(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = one_run(
                Path(tmp) / "loop",
                use_muse=False,
                offline_triage=True,
                observations=REPO / "agents" / "fixtures" / "obs-fixed.json",
                candidate_patch=REPO / "agents" / "fixtures" / "fix-collision-mask.patch",
                skip_harness=True,
            )
            self.assertEqual(result["decision"], "accept")


class SpecsEvaluateTest(unittest.TestCase):
    def test_gameplay_spec_distinguishes_freeze(self):
        spec = load(REPO / "agents" / "specs" / "player-reaches-end-of-route.json", "test-spec")
        fixed = load(REPO / "agents" / "fixtures" / "obs-fixed.json", "observations")
        freeze = load(REPO / "agents" / "fixtures" / "obs-freeze.json", "observations")
        self.assertEqual(evaluate(spec, fixed)["result"], "pass")
        self.assertEqual(evaluate(spec, freeze)["result"], "fail")
        decision, _ = decide([
            {"spec": "player-stays-above-ground", "kind": "regression", "route": "smoke", "result": "pass"},
            {"spec": "player-reaches-end-of-route", "kind": "gameplay", "route": "smoke", "result": "fail"},
        ])
        self.assertEqual(decision, "reject")


if __name__ == "__main__":
    unittest.main()
