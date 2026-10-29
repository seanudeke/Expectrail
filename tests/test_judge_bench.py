"""The judge benchmark: known-answer candidates, the undo patch, and the per-judge tally."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agents.judge_bench as jb
from harness.run import REPO, apply_patches


class JudgeBenchTest(unittest.TestCase):
    def test_eight_good_and_seven_bad_cases(self):
        cs = jb.cases()
        self.assertEqual(sum(c["label"] == "good" for c in cs.values()), 8)
        self.assertEqual(sum(c["label"] == "bad" for c in cs.values()), 7)
        for c in cs.values():
            self.assertIn(c["bug"].split("/")[1], jb.REPORTS)

    def test_every_bad_fixture_applies_on_its_bug(self):
        for key, (bug, fixture, _why) in jb.BAD.items():
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp) / "g"
                shutil.copytree(jb.GAME, work, ignore=shutil.ignore_patterns(".godot"))
                apply_patches(work, [jb.dev_variants()[bug], jb.FIXTURES / f"{fixture}.patch"])

    def test_the_undo_patch_restores_the_clean_game(self):
        for key, bug in jb.dev_variants().items():
            with tempfile.TemporaryDirectory() as tmp:
                undo = jb.undo_patch(bug, Path(tmp) / "undo.patch")
                work = Path(tmp) / "g"
                shutil.copytree(jb.GAME, work, ignore=shutil.ignore_patterns(".godot"))
                apply_patches(work, [bug, undo])
                for line in bug.read_text().splitlines():
                    if line.startswith("+++ b/"):
                        rel = line[6:].strip()
                        self.assertEqual((work / rel).read_text(), (jb.GAME / rel).read_text(), (key, rel))

    def test_a_case_records_every_judge_and_its_correctness(self):
        decisions = {"trace": "accept", "sam": "reject"}

        def fake_verify(request, candidate, out, **_kw):
            import os
            return {"decision": decisions[os.environ["NIGHTSHIFT_OBS_PROVIDER"]], "reasons": ["r"]}

        def fake_harness(route, out, patches):
            (out / "frames").mkdir(parents=True, exist_ok=True)
            for n in range(120):
                (out / "frames" / f"f{n:08d}.png").write_bytes(b"png")

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            judged = {}

            def fake_judge(o, *, before, after, instruction, sandboxed):
                judged.update(before=before, after=after, instruction=instruction, sandboxed=sandboxed)
                return {"decision": "accept", "detail": "screenshot judge accept"}

            def verify_with_frames(request, candidate, o, **kw):
                fake_harness(None, o / "replay", None)
                return fake_verify(request, candidate, o)

            with mock.patch.object(jb, "verify", side_effect=verify_with_frames), \
                    mock.patch.object(jb, "harness_run", side_effect=fake_harness), \
                    mock.patch.object(jb, "run_muse_judge", side_effect=fake_judge):
                row = jb.run_case("bad/fall-through-hide-player", out, live=True)
            self.assertEqual(row["decisions"], {"nightshiftNoSam": "accept", "nightshiftSam": "reject",
                                                "museScreenshots": "accept"})
            self.assertEqual(row["correct"], {"nightshiftNoSam": False, "nightshiftSam": True, "museScreenshots": False})
            self.assertEqual(len(judged["before"]), 5)
            self.assertTrue(judged["sandboxed"])
            self.assertIn("The player falls through the ground.", judged["instruction"])
            self.assertNotIn("hide", judged["instruction"].lower())  # the judge is never told what the fixture did
            doc = jb.summarize(out)
            self.assertEqual(doc["judges"]["nightshiftSam"]["badAccepted"], 0)
            self.assertEqual(doc["judges"]["museScreenshots"]["badAccepted"], 1)
            self.assertIn("| Muse from screenshots | 0 of 0 | 1 of 1 | 0 |", jb.markdown(doc))

    def test_a_crash_is_recorded_not_judged(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(jb, "verify", side_effect=RuntimeError("godot died")):
            row = jb.run_case("good/sinking/v1", Path(tmp), live=False)
        self.assertIn("godot died", row["error"])
        self.assertNotIn("correct", row)


if __name__ == "__main__":
    unittest.main()
