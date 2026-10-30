"""The Gate 2 fix matrix: what each condition is told, the attempt loop, and the bookkeeping."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agents.fixer as fixer
import agents.matrix as m
from harness.run import REPO
from expectrail.contracts import digest, load
from expectrail.evaluator import EVALUATOR

GROUND = load(m.REGRESSION_SPEC, "test-spec")


def fail_verdict(spec: dict) -> dict:
    return {"format": "expectrail.verdict/v0", "spec": {"id": spec["id"], "sha256": digest(spec)},
            "observations": {"sha256": "1" * 64}, "result": "fail",
            "reason": "SECRET-REASON player is 50px past the boundary", "firstFrame": 8,
            "evidence": [{"frame": 8, "detail": "SECRET-EVIDENCE"}], "framesJudged": 120,
            "evaluator": dict(EVALUATOR)}


class MatrixTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        frames = self.root / "bugged" / "frames"
        frames.mkdir(parents=True)
        for n in range(120):
            (frames / f"f{n:08d}.png").write_bytes(b"\x89PNG fake " + str(n).encode())
        (self.root / "bugged" / "godot.log").write_text("log line\n")
        self.detection = {"spec": GROUND, "verdict": fail_verdict(GROUND), "frames": frames,
                          "runDir": self.root / "bugged"}
        self.prompts, self.workspaces, self.verifies = [], [], []
        self.patches = [
            mock.patch.object(m, "detect", side_effect=lambda *a, **k: self.detection),
            mock.patch.object(m, "reference_surfaces", return_value=None),
            mock.patch.object(fixer, "muse_code_ready", return_value=True),
            mock.patch.object(fixer, "guard_enabled", return_value=False),
            mock.patch.object(fixer, "detect_sandbox", return_value="none"),
            mock.patch.object(fixer, "muse_subprocess_env", return_value={}),
            mock.patch.object(fixer, "run_muse_sandboxed", side_effect=self.fake_muse),
        ]
        for p in self.patches:
            p.start()
        self.verdicts = ["reject", "reject", "accept"]

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def fake_muse(self, prompt, *, work, **_kw):
        self.prompts.append(prompt)
        self.workspaces.append(sorted(p.relative_to(work).as_posix() for p in work.rglob("*") if p.is_file()))
        scene = work / "player" / "player.tscn"
        scene.write_text(scene.read_text() + f"\n; attempt {len(self.prompts)}\n")
        return subprocess.CompletedProcess(["muse"], 0, "ok", ""), {"kind": "none"}

    def fake_verify(self, request, candidate, out, attempt=1, **_kw):
        self.verifies.append({"request": request, "patch": Path(candidate).read_text(), "attempt": attempt})
        decision = self.verdicts[len(self.verifies) - 1]
        return {"decision": decision, "reasons": [f"SECRET-VERIFIER-REASON {attempt}"],
                "checks": [{"kind": "regression", "spec": "player-stays-above-ground", "result":
                            "pass" if decision == "accept" else "fail"}]}

    def case(self, condition, live=True, key="dev/physics-fall-through/v1"):
        with mock.patch.object(m, "verify", side_effect=self.fake_verify):
            return m.run_case(key, condition, self.root / "out", live=live, use_sam=False)

    def test_eight_cases_each_with_its_family_spec(self):
        ids = list(m.dev_variants())
        self.assertEqual(len(ids), 8)
        self.assertEqual(m.case_spec("dev/missing-texture/v1")["id"], "coins-visible")
        self.assertEqual(m.case_spec("dev/layering/v2")["id"], "player-always-visible")
        self.assertEqual(m.case_spec("dev/sinking/v1")["id"], GROUND["id"])

    def test_editable_covers_every_file_a_dev_bug_touches(self):
        from agents.patchutil import path_allowed
        for key, patch in m.dev_variants().items():
            for line in patch.read_text().splitlines():
                if line.startswith("+++ b/"):
                    self.assertTrue(path_allowed(line[6:], m.EDITABLE), (key, line))

    def test_screenshots_condition_never_sees_the_spec_verdict_or_reasons(self):
        row = self.case("screenshots")
        self.assertEqual(row["outcome"], "fixed")
        self.assertEqual(row["attemptsUsed"], 3)
        for prompt, files in zip(self.prompts, self.workspaces):
            self.assertNotIn("repair-request.json", files)
            for secret in ("SECRET-REASON", "SECRET-EVIDENCE", "SECRET-VERIFIER-REASON", GROUND["id"], "never-crosses"):
                self.assertNotIn(secret, prompt)
            self.assertIn(GROUND["instruction"], prompt)
            self.assertIn("bug-report/screenshots/frame-000.png", files)
            self.assertIn("bug-report/screenshots/frame-119.png", files)
            self.assertIn("bug-report/route.json", files)
        self.assertIn("previous attempt did not fix", self.prompts[1])
        self.assertNotIn("previous attempt", self.prompts[0])

    def test_expectrail_condition_gets_the_request_and_the_verifiers_reasons(self):
        row = self.case("expectrail")
        self.assertEqual(row["outcome"], "fixed")
        self.assertIn("repair-request.json", self.workspaces[0])
        self.assertIn(GROUND["id"], self.prompts[0])
        self.assertIn("SECRET-VERIFIER-REASON 1", self.prompts[1])  # reasons fed back after a reject
        self.assertIn("bug-report/screenshots/frame-060.png", self.prompts[0])

    def test_both_conditions_get_the_same_files_and_verifier(self):
        self.case("screenshots")
        shots = self.workspaces[0]
        req = self.verifies[0]["request"]
        self.prompts, self.workspaces, self.verifies = [], [], []
        self.case("expectrail")
        self.assertEqual(set(shots), set(self.workspaces[0]) - {"repair-request.json"})
        self.assertEqual(req["editable"], self.verifies[0]["request"]["editable"])
        self.assertEqual(req["base"], self.verifies[0]["request"]["base"])

    def test_the_candidate_never_includes_the_briefing_files(self):
        self.case("screenshots")
        for v in self.verifies:
            self.assertNotIn("bug-report", v["patch"])
            self.assertIn("player/player.tscn", v["patch"])

    def test_expectrail_does_not_repair_what_it_did_not_catch(self):
        self.detection["verdict"] = dict(self.detection["verdict"], result="pass", reason="no violation")
        row = self.case("expectrail")
        self.assertEqual(row["outcome"], "not-detected")
        self.assertEqual(self.prompts, [])
        row = self.case("screenshots")  # the screenshots condition is told about the bug regardless
        self.assertEqual(row["outcome"], "fixed")

    def test_a_timed_out_attempt_is_an_attempt_and_its_edits_are_verified(self):
        calls = []

        def slow_muse(prompt, *, work, **_kw):
            calls.append(prompt)
            if len(calls) == 1:  # ran out of time before changing anything
                raise subprocess.TimeoutExpired(["muse"], 900, output=b"thinking", stderr=b"")
            scene = work / "player" / "player.tscn"
            scene.write_text(scene.read_text() + "\n; edited before the clock ran out\n")
            raise subprocess.TimeoutExpired(["muse"], 900, output="partial", stderr=None)

        self.verdicts = ["accept"]
        with mock.patch.object(fixer, "run_muse_sandboxed", side_effect=slow_muse):
            row = self.case("expectrail")
        self.assertEqual(row["outcome"], "fixed")
        self.assertEqual([a["decision"] for a in row["attempts"]], ["timeout", "accept"])
        self.assertTrue(all(a.get("timedOut") for a in row["attempts"]))
        self.assertIn("edited before the clock ran out", self.verifies[0]["patch"])
        self.assertIn("ran out of time", calls[1])  # the reason reaches the next attempt (Expectrail)

    def test_each_case_records_the_sam_images_it_used(self):
        import agents.sam_observations as sam

        def fake_verify_with_sam(request, candidate, out, attempt=1, **kw):
            with sam._usage_lock:
                sam._usage["images"] += 7  # what a verification with SAM on would have sent
            return self.fake_verify(request, candidate, out, attempt=attempt, **kw)

        with mock.patch.object(m, "verify", side_effect=fake_verify_with_sam):
            row = m.run_case("dev/physics-fall-through/v1", "expectrail", self.root / "out", live=True, use_sam=False)
        self.assertEqual(row["samImages"], 21)  # three verifications
        self.assertNotIn("_samBefore", row)
        saved = json.loads((self.root / "out" / "dev_physics-fall-through_v1" / "expectrail" / "result.json").read_text())
        self.assertEqual(saved["samImages"], 21)

    def test_budget_runs_out_without_an_accept(self):
        self.verdicts = ["reject", "reject", "reject"]
        row = self.case("expectrail")
        self.assertEqual((row["outcome"], row["attemptsUsed"]), ("not-fixed", 3))

    def test_a_crash_is_an_error_never_a_fix(self):
        with mock.patch.object(m, "detect", side_effect=RuntimeError("godot died")):
            row = self.case("expectrail")
        self.assertEqual(row["outcome"], "error")
        self.assertIn("godot died", row["detail"])

    def test_offline_stops_after_one_attempt(self):
        row = self.case("expectrail", live=False)
        self.assertEqual((row["outcome"], row["attemptsUsed"]), ("not-fixed", 1))
        self.assertEqual(self.prompts, [])  # offline never calls Muse

    def test_summary_counts_outcomes_per_condition(self):
        self.case("screenshots")
        self.verdicts = ["reject", "reject", "reject"]
        self.verifies = []
        self.case("expectrail", key="dev/sinking/v1")
        doc = m.summarize(self.root / "out")
        self.assertEqual(doc["conditions"]["screenshots"]["fixed"], 1)
        self.assertEqual(doc["conditions"]["expectrail"]["notFixed"], 1)
        self.assertIn("| dev/sinking/v1 | expectrail | fail | not-fixed | 3 |", m.markdown(doc))


class HeldOutMatrixTest(MatrixTest):
    """A private case: same loop, but only ids, outcomes and decisions leave the runner."""

    def setUp(self):
        super().setUp()
        held = self.root / "held"
        (held / "bugs" / "sinking").mkdir(parents=True)
        (held / "routes").mkdir()
        (held / "routes" / "r.json").write_text("{}\n")
        (held / "bugs" / "sinking" / "v9.patch").write_text((REPO / "bugs/sinking/v1.patch").read_text())
        manifest = {"format": "expectrail.held-out-set/v0",
                    "routes": [{"name": "r", "file": "routes/r.json", "minDeltaX": 300}],
                    "variants": [
                        {"family": "sinking", "id": "v9", "patch": "bugs/sinking/v9.patch",
                         "spec": "player-stays-above-ground", "mechanism": "SECRET-MECHANISM"},
                        {"family": "sinking", "id": "v8", "patch": "bugs/sinking/v9.patch",
                         "spec": "player-stays-above-ground", "mechanism": "x", "retired": "published"}]}
        (held / "manifest.json").write_text(json.dumps(manifest))
        self.held = held
        self.env = mock.patch.dict("os.environ", {"EXPECTRAIL_HELDOUT_DIR": str(held)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        super().tearDown()

    def test_held_out_set_lists_active_ids_only(self):
        self.assertEqual(list(m.heldout_cases()), ["sinking/v9"])
        with self.assertRaises(SystemExit):
            m.resolve_case("sinking/v8")  # retired

    def test_a_held_out_case_publishes_only_ids_outcomes_and_decisions(self):
        row = self.case("expectrail", key="sinking/v9")
        self.assertEqual(row["outcome"], "fixed")
        self.assertTrue(row["private"])
        self.assertEqual(self.verifies[0]["request"]["base"]["patch"], str(self.held / "bugs/sinking/v9.patch"))
        work = self.root / "out" / "sinking_v9" / "expectrail"
        public = (work / "result.json").read_text()
        for secret in ("SECRET", "reasons", "checks", "patchSha256", "detail", str(self.held)):
            self.assertNotIn(secret, public)
        self.assertEqual([a["decision"] for a in json.loads(public)["attempts"]], ["reject", "reject", "accept"])
        self.assertEqual(json.loads(public)["samImages"], 0)  # a count, not a description of the bug
        private = json.loads((work / "result-private.json").read_text())
        self.assertIn("SECRET-VERIFIER-REASON 1", json.dumps(private))

    def test_a_held_out_crash_keeps_its_message_private(self):
        with mock.patch.object(m, "detect", side_effect=RuntimeError("SECRET crash text")):
            row = self.case("screenshots", key="sinking/v9")
        self.assertEqual(row["outcome"], "error")
        self.assertNotIn("detail", row)
        self.assertIn("SECRET crash text", (self.root / "out" / "sinking_v9" / "screenshots" / "result-private.json").read_text())


if __name__ == "__main__":
    unittest.main()
