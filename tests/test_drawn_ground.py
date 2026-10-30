"""The ground line also follows the floor as it is drawn: art moved up over its collision fails."""
from __future__ import annotations

import unittest

from agents.observations import (
    DRAWN_GROUND_OFFSET, drawn_surface_under, from_trace_synthetic, with_reference_ground,
)
from harness.run import REPO
from nightshift.contracts import load
from nightshift.evaluator import evaluate
from tests.test_sam import LEVEL, ground_trace

X0, WIDTH = -100, 800


def art(floor_top: float, platform: tuple[float, float] | None = None) -> dict:
    """levelArt for LEVEL: the floor drawn from ``floor_top`` down, optionally a platform over x 0-200."""
    columns = []
    for i in range(WIDTH):
        x = X0 + i
        runs = []
        if platform is not None and 0 <= x < 200:
            runs.append([platform[0], platform[1]])
        runs.append([floor_top, 900])
        columns.append(runs)
    return {"x0": X0, "y0": 300, "width": WIDTH, "height": 600, "columns": columns}


CLEAN_ART = art(650 - DRAWN_GROUND_OFFSET)  # the grass starts 8 px above the collision, as in the clean game


def spec() -> dict:
    return load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec")


def judged(trace: dict, level_art: dict | None) -> str:
    if level_art is not None:
        trace = dict(trace, levelArt=level_art)
    return evaluate(spec(), from_trace_synthetic(with_reference_ground(trace, LEVEL)))["result"]


class DrawnGroundTest(unittest.TestCase):
    def test_the_drawn_line_is_the_art_top_lowered_by_the_grass(self):
        self.assertEqual(drawn_surface_under(CLEAN_ART, 100.0, 636.75), 650.0)
        self.assertEqual(drawn_surface_under(art(616), 100.0, 636.75), 624.0)  # art moved 26 px up
        self.assertIsNone(drawn_surface_under(CLEAN_ART, 5000.0, 636.75))  # outside the render
        self.assertIsNone(drawn_surface_under({"columns": []}, 100.0, 636.75))

    def test_a_platform_overhead_is_not_the_floor(self):
        # A jump-through platform whose art reaches into the robot's head room is skipped, as the
        # collision search skips surfaces above the window (found on the clean smoke route).
        overhead = art(650 - DRAWN_GROUND_OFFSET, platform=(449, 494))
        self.assertEqual(drawn_surface_under(overhead, 100.0, 557.5), 650.0)
        self.assertEqual(drawn_surface_under(overhead, 100.0, 436.75), 457.0)  # standing on it
        # The overhanging end of a platform the robot jumps up beside starts inside the window but ends
        # above the feet: not a floor (found on the public combat route, a robot at y 530 beside
        # platform art from 470 to 515).
        beside = art(650 - DRAWN_GROUND_OFFSET, platform=(470, 515))
        self.assertEqual(drawn_surface_under(beside, 100.0, 530.3), 650.0)

    def test_the_clean_floor_passes_and_art_moved_up_fails(self):
        self.assertEqual(judged(ground_trace(), CLEAN_ART), "pass")
        self.assertEqual(judged(ground_trace(), art(650 - DRAWN_GROUND_OFFSET - 26)), "fail")
        # Within the grass's own spread on the clean level (art 1 to 10 px above the collision).
        self.assertEqual(judged(ground_trace(), art(640)), "pass")
        self.assertEqual(judged(ground_trace(), art(649)), "pass")

    def test_art_moved_down_leaves_the_collision_in_charge(self):
        self.assertEqual(judged(ground_trace(), art(650 + 26)), "pass")
        self.assertEqual(judged(ground_trace(sink=26), art(650 + 26)), "fail")  # a sunk body still fails

    def test_without_level_art_the_check_is_unchanged(self):
        self.assertEqual(judged(ground_trace(), None), "pass")
        self.assertEqual(judged(ground_trace(sink=26), None), "fail")
        plain = with_reference_ground(ground_trace(), LEVEL)
        self.assertEqual(plain["groundReference"], "clean level")
        drawn = with_reference_ground(dict(ground_trace(), levelArt=CLEAN_ART), LEVEL)
        self.assertEqual(drawn["groundReference"], "clean level, and the floor as drawn")


if __name__ == "__main__":
    unittest.main()
