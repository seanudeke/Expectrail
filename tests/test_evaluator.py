import copy
import unittest

from nightshift.contracts import validate
from nightshift.evaluator import REQUIRED_CHECK_KINDS, decide, evaluate


def spec(assertion, objects=("player", "ground"), window=None):
    doc = {"format": "nightshift.test-spec/v0", "id": "t", "instruction": "test",
           "objects": {name: {"prompt": name} for name in objects}, "assertion": assertion}
    if window:
        doc["window"] = window
    return doc


def obs(*frames):
    return {"format": "nightshift.observations/v0", "replay": {"sha256": "0" * 64}, "model": {"name": "sam-3.1"},
            "frames": [{"frame": n, "objects": objects} for n, objects in frames]}


def det(box, score=0.9):
    return [{"box": list(box), "score": score}]


GROUND = det((0, 700, 1600, 960))
ABOVE = {"type": "never-crosses", "object": "player",
         "boundary": {"relativeTo": "ground", "edge": "top", "side": "above", "tolerancePx": 10}}


class NeverCrossesTest(unittest.TestCase):
    def test_standing_on_the_ground_passes(self):
        v = evaluate(spec(ABOVE), obs((0, {"player": det((100, 600, 160, 705)), "ground": GROUND})))
        self.assertEqual(v["result"], "pass")
        validate(v)

    def test_sinking_through_the_ground_fails_with_evidence(self):
        v = evaluate(spec(ABOVE), obs((0, {"player": det((100, 600, 160, 705)), "ground": GROUND}),
                                      (1, {"player": det((100, 680, 160, 785)), "ground": GROUND})))
        self.assertEqual(v["result"], "fail")
        self.assertEqual(v["firstFrame"], 1)
        self.assertIn("85px past the boundary", v["evidence"][0]["detail"])

    def test_a_missing_player_is_never_a_pass(self):
        v = evaluate(spec(ABOVE), obs((0, {"player": det((100, 600, 160, 705)), "ground": GROUND}),
                                      (1, {"player": [], "ground": GROUND})))
        self.assertEqual(v["result"], "needs-review")
        self.assertIn("never a pass", v["reason"])

    def test_low_confidence_detections_do_not_count(self):
        v = evaluate(spec(ABOVE), obs((0, {"player": det((100, 680, 160, 785), score=0.2), "ground": GROUND})))
        self.assertEqual(v["result"], "needs-review")

    def test_ground_that_is_not_under_the_player_is_not_judged(self):
        ledge = det((900, 300, 1200, 330))
        v = evaluate(spec(ABOVE), obs((0, {"player": det((100, 600, 160, 705)), "ground": ledge + GROUND})))
        self.assertEqual(v["result"], "pass")
        v = evaluate(spec(ABOVE), obs((0, {"player": det((100, 600, 160, 705)), "ground": ledge})))
        self.assertEqual(v["result"], "needs-review")

    def test_the_window_limits_the_frames_judged(self):
        frames = obs((0, {"player": det((100, 680, 160, 785)), "ground": GROUND}),
                     (5, {"player": det((100, 600, 160, 705)), "ground": GROUND}))
        self.assertEqual(evaluate(spec(ABOVE, window={"fromFrame": 1}), frames)["result"], "pass")
        self.assertEqual(evaluate(spec(ABOVE), frames)["result"], "fail")

    def test_absolute_boundaries(self):
        a = {"type": "never-crosses", "object": "player", "boundary": {"axis": "x", "value": 500, "side": "left-of"}}
        self.assertEqual(evaluate(spec(a, ("player",)), obs((0, {"player": det((400, 0, 490, 50))})))["result"], "pass")
        self.assertEqual(evaluate(spec(a, ("player",)), obs((0, {"player": det((450, 0, 520, 50))})))["result"], "fail")


class OtherAssertionsTest(unittest.TestCase):
    def test_visible(self):
        a = {"type": "visible", "object": "player", "minFraction": 0.5}
        frames = obs((0, {"player": det((0, 0, 10, 10))}), (1, {"player": []}), (2, {"player": []}))
        self.assertEqual(evaluate(spec(a, ("player",)), frames)["result"], "fail")
        a["minFraction"] = 0.3
        self.assertEqual(evaluate(spec(a, ("player",)), frames)["result"], "pass")

    def test_inside_region_relative_to_another_object(self):
        a = {"type": "inside-region", "object": "text", "region": {"relativeTo": "box"}, "tolerancePx": 2}
        s = spec(a, ("text", "box"))
        inside = obs((0, {"text": det((110, 110, 290, 140)), "box": det((100, 100, 300, 150))}))
        overflow = obs((0, {"text": det((110, 110, 340, 140)), "box": det((100, 100, 300, 150))}))
        self.assertEqual(evaluate(s, inside)["result"], "pass")
        self.assertEqual(evaluate(s, overflow)["result"], "fail")

    def test_reaches(self):
        a = {"type": "reaches", "object": "player", "goal": "door", "distancePx": 5}
        s = spec(a, ("player", "door"))
        never = obs((0, {"player": det((0, 0, 10, 10)), "door": det((100, 0, 120, 30))}))
        reached = obs((0, {"player": det((0, 0, 10, 10)), "door": det((100, 0, 120, 30))}),
                      (9, {"player": det((92, 0, 102, 10)), "door": det((100, 0, 120, 30))}))
        hidden = obs((0, {"player": det((0, 0, 10, 10)), "door": []}))
        self.assertEqual(evaluate(s, never)["result"], "fail")
        self.assertEqual(evaluate(s, reached)["result"], "pass")
        self.assertEqual(evaluate(s, hidden)["result"], "needs-review")

    def test_verdicts_are_reproducible(self):
        s, o = spec(ABOVE), obs((0, {"player": det((100, 680, 160, 785)), "ground": GROUND}))
        self.assertEqual(evaluate(s, o), evaluate(copy.deepcopy(s), copy.deepcopy(o)))


class DecideTest(unittest.TestCase):
    def check(self, kind, result, spec=None):
        return {"spec": spec or kind, "kind": kind, "route": "r", "result": result}

    def four_pass(self):
        return [
            self.check("regression", "pass"),
            self.check("gameplay", "pass"),
            self.check("held-out", "pass"),
            self.check("clean", "pass"),
        ]

    def test_required_kinds_constant(self):
        self.assertEqual(REQUIRED_CHECK_KINDS, frozenset({"regression", "gameplay", "held-out", "clean"}))

    def test_four_kind_pass_accepts(self):
        self.assertEqual(decide(self.four_pass())[0], "accept")

    def test_two_kind_pass_is_needs_review_not_accept(self):
        decision, reasons = decide([
            self.check("regression", "pass"),
            self.check("gameplay", "pass"),
        ])
        self.assertEqual(decision, "needs-review")
        self.assertTrue(any("missing required check kinds" in r for r in reasons))
        self.assertTrue(any("clean" in r for r in reasons))
        self.assertTrue(any("held-out" in r for r in reasons))

    def test_any_failure_rejects(self):
        self.assertEqual(
            decide([self.check("regression", "pass"), self.check("gameplay", "fail")])[0],
            "reject",
        )
        self.assertEqual(decide(self.four_pass()[:-1] + [self.check("clean", "fail")])[0], "reject")

    def test_fail_beats_missing_kinds(self):
        self.assertEqual(decide([self.check("regression", "fail")])[0], "reject")

    def test_unclear_on_complete_suite_needs_review(self):
        checks = self.four_pass()
        checks[2] = self.check("held-out", "needs-review")
        self.assertEqual(decide(checks)[0], "needs-review")

    def test_empty_needs_review(self):
        self.assertEqual(decide([])[0], "needs-review")

    def test_kind_set_not_length(self):
        decision, reasons = decide([
            self.check("regression", "pass"),
            self.check("gameplay", "pass"),
            self.check("held-out", "pass"),
            self.check("held-out", "pass", spec="dup"),
        ])
        self.assertEqual(decision, "needs-review")
        self.assertTrue(any("clean" in r for r in reasons))

    def test_missing_kinds_beats_unclear(self):
        decision, reasons = decide([
            self.check("regression", "pass"),
            self.check("gameplay", "needs-review"),
        ])
        self.assertEqual(decision, "needs-review")
        self.assertTrue(any("missing required check kinds" in r for r in reasons))
        self.assertFalse(any("needs review on" in r for r in reasons))


if __name__ == "__main__":
    unittest.main()
