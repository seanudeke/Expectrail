"""The checkout prompt probe: scoring a prompt against where the page drew the element."""
from __future__ import annotations

import unittest

from agents import web_probe

BUTTON = [332, 1388, 940, 1436]
BADGE = [1200, 300, 1230, 322]


def session(truth, *found):
    return {"truth": truth, "found": {"p": [{"box": b, "score": s} for b, s in found]}}


class ScoreTest(unittest.TestCase):
    def test_a_prompt_that_also_matches_the_badge_is_unsafe_when_the_badge_outscores_the_button(self):
        r = web_probe.score_prompt([session(BUTTON, (BUTTON, 0.78), (BADGE, 0.74)),
                                    session(None, (BADGE, 0.80))], "button", "p")
        self.assertEqual((r["trueMin"], r["distractorMax"], r["rankedFirst"]), (0.78, 0.80, 1))
        self.assertFalse(r["safeAtDefault"])
        self.assertIsNone(r["threshold"])

    def test_a_prompt_with_a_margin_gets_a_threshold_and_is_safe_at_the_default_when_clear_of_it(self):
        r = web_probe.score_prompt([session(BUTTON, (BUTTON, 0.86), (BADGE, 0.61)), session(None)], "button", "p")
        self.assertEqual(r["threshold"], 0.73)
        self.assertFalse(r["safeAtDefault"])
        r = web_probe.score_prompt([session(BUTTON, (BUTTON, 0.86), (BADGE, 0.3)), session(None)], "button", "p")
        self.assertTrue(r["safeAtDefault"])

    def test_missing_the_drawn_element_scores_zero(self):
        r = web_probe.score_prompt([session(BUTTON, (BADGE, 0.9))], "button", "p")
        self.assertEqual((r["trueMin"], r["rankedFirst"]), (0.0, 0))

    def test_the_report_names_the_best_prompt_or_warns(self):
        sessions = {"button": [{"truth": BUTTON, "found": {"a": [{"box": BUTTON, "score": 0.9}],
                                                           "b": [{"box": BADGE, "score": 0.9}]}}]}
        _, lines = web_probe.report(sessions, {"button": ["a", "b"]})
        self.assertIn('"a" true 0.90 first 1/1 distractor 0.00 safe', lines[0])
        self.assertIn('best::"a"', lines[1])
        _, lines = web_probe.report(sessions, {"button": ["b"]})
        self.assertTrue(lines[1].startswith("::warning"))

    def test_prompts_are_object_equals_prompt(self):
        self.assertEqual(web_probe.parse_prompts(["button=wide blue button"]), {"button": ["wide blue button"]})
        with self.assertRaises(SystemExit):
            web_probe.parse_prompts(["robot=red robot"])


if __name__ == "__main__":
    unittest.main()
