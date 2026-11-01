"""The judge benchmark: known-answer candidates, the undo patch, and the per-judge tally."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agents.judge_bench as jb
from harness.run import apply_patches


class JudgeBenchTest(unittest.TestCase):
    def test_eight_good_and_seven_bad_cases(self):
        cs = jb.cases()
        self.assertEqual(sum(c["label"] == "good" for c in cs.values()), 8)
        self.assertEqual(sum(c["label"] == "bad" for c in cs.values()), 7)
        for c in cs.values():
            self.assertIn(c["bug"].split("/")[1], jb.REPORTS)

    def test_every_bad_fixture_applies_on_its_bug(self):
        for bug, fixture, _why in jb.BAD.values():
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
            return {"decision": decisions[os.environ["EXPECTRAIL_OBS_PROVIDER"]], "reasons": ["r"]}

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
            self.assertEqual(row["decisions"], {"expectrailNoSam": "accept", "expectrailSam": "reject",
                                                "museScreenshots": "accept"})
            self.assertEqual(row["correct"], {"expectrailNoSam": False, "expectrailSam": True, "museScreenshots": False})
            self.assertEqual(len(judged["before"]), 5)
            self.assertTrue(judged["sandboxed"])
            self.assertIn("The player falls through the ground.", judged["instruction"])
            self.assertNotIn("hide", judged["instruction"].lower())  # the judge is never told what the fixture did
            doc = jb.summarize(out)
            self.assertEqual(doc["judges"]["expectrailSam"]["badAccepted"], 0)
            self.assertEqual(doc["judges"]["museScreenshots"]["badAccepted"], 1)
            self.assertIn("| Muse from screenshots | 0 of 0 | 1 of 1 | 0 |", jb.markdown(doc))

    def test_outside_judges_see_the_frames_and_instruction_muse_sees(self):
        def fake_harness(route, out, patches):
            (out / "frames").mkdir(parents=True, exist_ok=True)
            for n in range(120):
                (out / "frames" / f"f{n:08d}.png").write_bytes(f"png{n}".encode())

        def verify_with_frames(request, candidate, o, **kw):
            fake_harness(None, o / "replay", None)
            return {"decision": "accept", "reasons": []}

        seen = {}

        def fake_muse(o, *, before, after, instruction, sandboxed):
            seen["muse"] = (before, after, instruction)
            return {"decision": "accept", "detail": "screenshot judge accept"}

        def fake_outside(o, *, before, after, instruction, names, passes):
            seen["outside"] = (before, after, instruction, names, passes)
            return {"claude": {"model": "m", "decisions": ["reject"] * passes, "details": [], "reasons": [],
                               "usage": [], "usd": 0.0}}

        import agents.outside_judge as oj
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(jb, "verify", side_effect=verify_with_frames), \
                mock.patch.object(jb, "harness_run", side_effect=fake_harness), \
                mock.patch.object(jb, "run_muse_judge", side_effect=fake_muse), \
                mock.patch.object(oj, "judge_frames", side_effect=fake_outside):
            row = jb.run_case("bad/fall-through-sink-player", Path(tmp), live=True, sam=False,
                              outside=("claude",), passes=3)
        self.assertEqual(seen["outside"][:3], seen["muse"])  # identical frames and instruction
        self.assertEqual(seen["outside"][3:], (["claude"], 3))
        self.assertEqual(row["outside"]["claude"]["decisions"], ["reject"] * 3)
        self.assertNotIn("expectrailSam", row["decisions"])  # SAM skipped
        self.assertNotIn("claude", row["decisions"])  # kept apart from the recorded judges

    def test_outside_judges_need_a_live_run_and_a_known_name(self):
        with self.assertRaises(SystemExit):
            jb.main(["--case", "bad/fall-through-freeze", "--outside", "claude"])
        with self.assertRaises(SystemExit):
            jb.main(["--case", "bad/fall-through-freeze", "--live", "--outside", "gemini"])

    def _glimmer_case(self, case, *, glimmer_decision="reject", down=False, problem=None):
        """run_case with the fourth judge; verify answers by provider and, under Glimmer, by backend."""
        import os

        from agents.sam_observations import BACKEND_ENV

        def fake_verify(request, candidate, out, **_kw):
            if os.environ.get(BACKEND_ENV) == "glimmer-engine":
                self.assertEqual(os.environ["EXPECTRAIL_OBS_PROVIDER"], "sam")  # as the ladder's fallback runs it
                return {"decision": glimmer_decision, "reasons": ["candidate check player-always-visible failed on smoke"]}
            return {"decision": {"trace": "accept", "sam": "reject"}[os.environ["EXPECTRAIL_OBS_PROVIDER"]],
                    "reasons": ["r"]}

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        with mock.patch.object(jb, "verify", side_effect=fake_verify), \
                mock.patch("agents.judge_ladder.glimmer_problem", return_value=problem), \
                mock.patch("agents.judge_ladder.judge_unavailable", return_value=down):
            row = jb.run_case(case, out, live=False, glimmer=True)
        return row, out

    def test_glimmer_is_a_fourth_judge_run_as_the_ladder_runs_it(self):
        row, out = self._glimmer_case("bad/fall-through-sink-player", glimmer_decision="accept")
        self.assertEqual(row["decisions"]["expectrailGlimmer"], "accept")
        self.assertIs(row["correct"]["expectrailGlimmer"], False)  # a bad fix accepted
        self.assertEqual(row["reasons"]["expectrailGlimmer"], ["candidate check player-always-visible failed"])
        self.assertIn("glimmerSeconds", row)
        doc = jb.summarize(out)
        self.assertEqual(doc["judges"]["expectrailGlimmer"], {"goodAccepted": 0, "good": 0, "badAccepted": 1,
                                                              "bad": 1, "undecided": 0})
        self.assertIn("| Expectrail, Glimmer+engine | 0 of 0 | 1 of 1 | 0 |", jb.markdown(doc))
        self.assertNotIn("museScreenshots", doc["judges"])  # not run here, so not shown as 0 of 0

    def test_a_glimmer_outage_is_undecided_never_a_rejection(self):
        for kwargs in ({"down": True}, {"problem": "the Fireworks account is suspended"}):
            row, out = self._glimmer_case("bad/fall-through-sink-player", **kwargs)
            self.assertIsNone(row["decisions"]["expectrailGlimmer"])
            self.assertIsNone(row["correct"]["expectrailGlimmer"])
            self.assertTrue(row["reasons"]["expectrailGlimmer"][0].startswith("Glimmer"))
            s = jb.summarize(out)["judges"]["expectrailGlimmer"]
            self.assertEqual((s["badAccepted"], s["bad"], s["undecided"]), (0, 0, 1))

    def test_without_glimmer_the_three_judges_are_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(jb, "verify", return_value={"decision": "accept", "reasons": []}):
            row = jb.run_case("good/sinking/v1", Path(tmp), live=False)
        self.assertNotIn("expectrailGlimmer", row["decisions"])
        self.assertNotIn("glimmerSeconds", row)

    def test_a_crash_is_recorded_not_judged(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(jb, "verify", side_effect=RuntimeError("godot died")):
            row = jb.run_case("good/sinking/v1", Path(tmp), live=False)
        self.assertIn("godot died", row["error"])
        self.assertNotIn("correct", row)


if __name__ == "__main__":
    unittest.main()


class MuseReasonTest(unittest.TestCase):
    def test_the_reason_is_what_muse_wrote_before_its_last_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "muse.log"
            log.write_text("tool: read frames/after-0.png\nDECISION: accept\nOn second look the robot\n"
                           "  still sinks into the floor in after-2.\nDECISION: reject\ntrailing noise\n")
            self.assertEqual(jb.muse_reason({"museLog": str(log), "detail": "d"}),
                             "tool: read frames/after-0.png DECISION: accept On second look the robot "
                             "still sinks into the floor in after-2.")
            self.assertTrue(jb.muse_reason({"museLog": str(log)}, limit=20).startswith("..."))
            log.write_text("no decision here")
            self.assertEqual(jb.muse_reason({"museLog": str(log), "detail": "d"}), "d")
            self.assertEqual(jb.muse_reason({"detail": "d"}), "d")
