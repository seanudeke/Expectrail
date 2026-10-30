"""The checkout prompt probe: scoring a prompt against where the page drew the element."""
from __future__ import annotations

import unittest

from agents import web_probe
from harness.run import REPO

BUTTON = [332, 1388, 940, 1436]
BADGE = [1233, 299, 1268, 330]


def session(drawn, at, *found):
    return {"drawn": drawn, "frames": [{"at": at, "found": {"p": [{"box": b, "score": s} for b, s in found]}}]}


class ScoreTest(unittest.TestCase):
    def test_the_badge_beats_a_threshold_alone_but_not_agreement_with_the_page(self):
        sessions = [session(True, BUTTON, (BUTTON, 0.78), (BADGE, 0.74)),
                    session(True, BUTTON, (BUTTON, 0.56)),            # a correct fix with a bar just below
                    session(False, BUTTON, (BADGE, 0.80), (BUTTON, 0.2))]  # covered: only a faint match on its box
        r = web_probe.score_prompt(sessions, "button", "p")
        self.assertEqual(r["trueMin"], 0.56)
        self.assertEqual(r["alone"]["max"], 0.80)
        self.assertIsNone(r["alone"]["threshold"])
        self.assertEqual(r["agreement"]["max"], 0.2)
        self.assertEqual(r["agreement"]["threshold"], 0.38)
        self.assertTrue(r["agreement"]["safeAtDefault"])

    def test_a_cover_that_sam_reads_as_the_button_on_its_box_is_unsafe_even_in_agreement(self):
        r = web_probe.score_prompt([session(True, BUTTON, (BUTTON, 0.7)), session(False, BUTTON, (BUTTON, 0.75))],
                                   "button", "p")
        self.assertIsNone(r["agreement"]["threshold"])

    def test_missing_the_drawn_element_scores_zero(self):
        r = web_probe.score_prompt([session(True, BUTTON, (BADGE, 0.9))], "button", "p")
        self.assertEqual((r["trueMin"], r["rankedFirst"]), (0.0, 0))

    def test_the_report_names_the_best_prompt_each_way_or_warns(self):
        sessions = {"button": [session(True, BUTTON, (BUTTON, 0.9)), session(False, BUTTON, (BADGE, 0.6))]}
        sessions["button"][0]["frames"][0]["found"]["q"] = [{"box": BADGE, "score": 0.95}]
        sessions["button"][1]["frames"][0]["found"]["q"] = []
        _, lines = web_probe.report(sessions, {"button": ["p", "q"]})
        self.assertIn('"p" true 0.90 first 1/1; alone vs 0.60 split at 0.75; on the page\'s box vs 0.00 safe', lines[0])
        self.assertIn('best, SAM alone::"p"', lines[1])
        self.assertIn('best, on the page\'s box::"p"', lines[2])

    def test_every_case_names_patches_that_exist(self):
        for key, (patch_ids, _) in web_probe.CASES.items():
            for pid in patch_ids:
                self.assertTrue((REPO / "apps" / "checkout" / f"{pid}.patch").is_file(), f"{key}: {pid}")

    def test_prompts_are_object_equals_prompt(self):
        self.assertEqual(web_probe.parse_prompts(["button=wide blue button"]), {"button": ["wide blue button"]})
        with self.assertRaises(SystemExit):
            web_probe.parse_prompts(["robot=red robot"])


if __name__ == "__main__":
    unittest.main()
