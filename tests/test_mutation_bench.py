"""Mutation bench: operators on the correct fix; findings are not failures."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agents.mutation_bench as mb
from harness.run import REPO, apply_patches
import shutil


class OperatorFixturesTest(unittest.TestCase):
    def test_every_operator_applies_to_the_clean_game(self):
        for name in mb.OPERATORS:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp) / "game"
                shutil.copytree(REPO / "game" / "platformer", work,
                                ignore=shutil.ignore_patterns(".godot"))
                apply_patches(work, [mb.operator_path(name)])

    def test_pairs_cover_eight_cases_times_six_operators(self):
        pairs = mb.pairs()
        self.assertEqual(len(pairs), 8 * 6)
        self.assertEqual(len({c for c, _ in pairs}), 8)


class MutationBenchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        os.environ.pop(mb.HELDOUT_ENV, None)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop(mb.HELDOUT_ENV, None)

    def test_refuses_when_heldout_dir_is_set(self):
        os.environ[mb.HELDOUT_ENV] = "/tmp/private"
        with self.assertRaises(SystemExit) as ctx:
            mb.run_case("dev/sinking/v2", "hide", self.out)
        self.assertIn("public checks only", str(ctx.exception))

    def test_sam_off_reject_is_caught_without_sam_on(self):
        def fake_verify(request, candidate, out, **kwargs):
            out.mkdir(parents=True, exist_ok=True)
            return {"decision": "reject", "reasons": ["gameplay check player-motion-on-smoke failed"]}

        with mock.patch.object(mb, "verify", side_effect=fake_verify):
            row = mb.run_case("dev/physics-fall-through/v1", "freeze", self.out)
        self.assertEqual(row["caught"], "sam-off")
        self.assertFalse(row["finding"])
        self.assertNotIn("expectrailSam", row["decisions"])
        self.assertTrue((self.out / "dev_physics-fall-through_v1+freeze" / "result.json").is_file())

    def test_survivor_is_a_finding_with_catch_spec(self):
        def fake_verify(request, candidate, out, **kwargs):
            out.mkdir(parents=True, exist_ok=True)
            return {"decision": "accept", "reasons": []}

        with mock.patch.object(mb, "verify", side_effect=fake_verify):
            row = mb.run_case("dev/sinking/v1", "comment-only", self.out)
        self.assertTrue(row["finding"])
        self.assertIsNone(row["caught"])
        work = self.out / "dev_sinking_v1+comment-only"
        finding = json.loads((work / "finding.json").read_text())
        self.assertEqual(finding["catchSpec"]["id"], "comment-only-delta")
        self.assertEqual(finding["operator"], "comment-only")
        catch = json.loads((work / "catch-spec.json").read_text())
        self.assertEqual(catch["id"], "comment-only-delta")

    def test_sam_on_reject_after_sam_off_accept(self):
        calls = {"n": 0}

        def fake_verify(request, candidate, out, **kwargs):
            out.mkdir(parents=True, exist_ok=True)
            calls["n"] += 1
            if calls["n"] == 1:
                return {"decision": "accept", "reasons": []}
            return {"decision": "reject", "reasons": ["regression check player-always-visible failed"]}

        with mock.patch.object(mb, "verify", side_effect=fake_verify):
            row = mb.run_case("dev/layering/v1", "behind-scenery", self.out)
        self.assertEqual(row["caught"], "sam-on")
        self.assertFalse(row["finding"])
        self.assertEqual(calls["n"], 2)

    def test_build_candidate_stacks_operator_on_undo(self):
        bug = mb.dev_variants()["dev/physics-fall-through/v1"]
        cand = mb.build_candidate(bug, mb.operator_path("hide"), self.out / "c.patch")
        text = cand.read_text()
        self.assertIn("player/", text)
        # Operator mark present in the stacked candidate.
        self.assertIn("visible = false", text)

    def test_summarize_counts_findings(self):
        for name, finding, caught in (("a", True, None), ("b", False, "sam-off")):
            d = self.out / name
            d.mkdir()
            (d / "result.json").write_text(json.dumps({
                "format": mb.FORMAT, "case": f"dev/x/{name}", "operator": "hide",
                "finding": finding, "caught": caught,
            }) + "\n")
        doc = mb.summarize(self.out)
        self.assertEqual(doc["findings"], 1)
        self.assertEqual(doc["caughtSamOff"], 1)
        self.assertIn("Findings: **1**", mb.markdown(doc))

    def test_exit_zero_on_finding(self):
        with mock.patch.object(mb, "run_case", return_value={
            "case": "dev/sinking/v1", "operator": "comment-only", "finding": True,
            "caught": None, "decisions": {}, "error": None, "wallClockSeconds": 1,
        }):
            code = mb.main(["--case", "dev/sinking/v1", "--operator", "comment-only",
                            "--out", str(self.out)])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
