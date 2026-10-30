"""Engine-record checks: each rule passes the clean shape, fails the bug's shape, and never passes a missing record."""
import unittest

from agents import trace_checks as tc

GROUND = 637.0


def trace(rows, tps=120):
    return {"physicsTicksPerSecond": tps, "rows": rows}


def row(tick, x, y, on_floor=True, facing=1, enemies=None, projectiles=None):
    r = {"tick": tick, "player": [x, y], "onFloor": on_floor, "facing": facing}
    if enemies is not None:
        r["enemies"] = enemies
    if projectiles is not None:
        r["projectiles"] = projectiles
    return r


def jump(peak_rise, ticks=40, start=0, x=100.0):
    """On the floor, up to peak_rise above it, back down."""
    rows = [row(start, x, GROUND)]
    half = ticks // 2
    for i in range(1, ticks):
        rise = peak_rise * (i / half if i <= half else (ticks - i) / half)
        rows.append(row(start + i, x, GROUND - rise, on_floor=False))
    rows.append(row(start + ticks, x, GROUND))
    return rows


def walk(direction, facing, ticks=20, start=0, x0=100.0, speed=2.0):
    return [row(start + i, x0 + direction * speed * i, GROUND, facing=facing) for i in range(ticks)]


class JumpHeightTest(unittest.TestCase):
    def test_a_double_jump_passes(self):
        self.assertEqual(tc.jump_height(trace(jump(250)))["result"], "pass")

    def test_climbing_far_above_the_last_floor_fails(self):
        verdict = tc.jump_height(trace(jump(486)))
        self.assertEqual(verdict["result"], "fail")
        self.assertGreater(verdict["metrics"]["maxRise"], 260)

    def test_the_rise_is_measured_from_the_last_floor_not_the_first(self):
        # Two ordinary jumps, the second from a ledge 300 px higher: never more than 250 above its floor.
        rows = jump(250) + [dict(r, tick=r["tick"] + 100, player=[r["player"][0], r["player"][1] - 300])
                            for r in jump(250)]
        self.assertEqual(tc.jump_height(trace(rows))["result"], "pass")

    def test_a_trace_that_never_stands_is_not_a_pass(self):
        rows = [row(i, 100, 500 - i, on_floor=False) for i in range(10)]
        self.assertEqual(tc.jump_height(trace(rows))["result"], "needs-review")


class FacingTest(unittest.TestCase):
    def test_facing_the_way_it_walks_passes(self):
        rows = walk(1, 1) + walk(-1, -1, start=20, x0=140)
        self.assertEqual(tc.facing_follows_motion(trace(rows))["result"], "pass")

    def test_facing_flipping_every_tick_while_walking_left_fails(self):
        rows = [row(i, 100 - 2 * i, GROUND, facing=(1 if i % 2 else -1)) for i in range(40)]
        self.assertEqual(tc.facing_follows_motion(trace(rows))["result"], "fail")

    def test_a_turn_takes_a_few_ticks(self):
        # Five ticks facing the old way after the walk turns: under the limit of six.
        rows = walk(1, 1) + walk(-1, 1, ticks=5, start=20, x0=140) + walk(-1, -1, start=25, x0=130)
        self.assertEqual(tc.facing_follows_motion(trace(rows))["result"], "pass")

    def test_standing_still_is_not_judged(self):
        rows = [row(i, 100, GROUND, facing=-1) for i in range(40)]
        verdict = tc.facing_follows_motion(trace(rows))
        self.assertEqual(verdict["result"], "pass")
        self.assertEqual(verdict["metrics"]["movingTicks"], 0)

    def test_no_facing_record_is_not_a_pass(self):
        rows = [{"tick": i, "player": [100 + 2 * i, GROUND], "onFloor": True} for i in range(20)]
        self.assertEqual(tc.facing_follows_motion(trace(rows))["result"], "needs-review")


def shot(tick, facing, bullet_dx, pid=1, ticks=8, x0=100.0):
    """The robot stands facing one way; a bullet appears at `tick` and moves bullet_dx per tick."""
    rows = []
    for i in range(ticks):
        t = tick + i
        rows.append(row(t, x0, GROUND, facing=facing, projectiles=[[pid, x0 + bullet_dx * i, 600.0]]))
    return rows


class ShotsTest(unittest.TestCase):
    def test_bullets_that_go_the_way_the_robot_faces_pass(self):
        rows = shot(10, -1, -8, pid=1) + shot(60, 1, 8, pid=2)
        self.assertEqual(tc.shots_follow_facing(trace(rows))["result"], "pass")

    def test_a_bullet_fired_facing_left_that_goes_right_fails(self):
        verdict = tc.shots_follow_facing(trace(shot(10, -1, 8)))
        self.assertEqual(verdict["result"], "fail")
        self.assertEqual(verdict["metrics"]["wrong"], 1)

    def test_a_bullet_that_stops_at_once_is_not_judged(self):
        verdict = tc.shots_follow_facing(trace(shot(10, -1, 0)))
        self.assertEqual(verdict["result"], "pass")
        self.assertNotIn("judged", verdict["metrics"])

    def test_no_shots_is_a_pass(self):
        self.assertEqual(tc.shots_follow_facing(trace(walk(1, 1)))["result"], "pass")

    def test_shots_without_facing_are_not_a_pass(self):
        rows = [{"tick": i, "player": [100, GROUND], "projectiles": [[1, 100 + 8 * i, 600]]} for i in range(8)]
        self.assertEqual(tc.shots_follow_facing(trace(rows))["result"], "needs-review")


class FireRateTest(unittest.TestCase):
    def shots(self, gap_ticks, n=4):
        rows = []
        for k in range(n):
            rows += shot(10 + k * gap_ticks, 1, 8, pid=k + 1, ticks=4)
        return trace(sorted(rows, key=lambda r: r["tick"]))

    def test_the_cooldown_passes(self):
        self.assertEqual(tc.fire_rate(self.shots(36))["result"], "pass")  # 0.3 s at 120 ticks/s

    def test_a_shot_every_tenth_of_a_second_fails(self):
        verdict = tc.fire_rate(self.shots(12))
        self.assertEqual(verdict["result"], "fail")
        self.assertAlmostEqual(verdict["metrics"]["minIntervalS"], 0.1)

    def test_without_a_tick_rate_two_shots_cannot_be_judged(self):
        doc = self.shots(12)
        doc.pop("physicsTicksPerSecond")
        self.assertEqual(tc.fire_rate(doc)["result"], "needs-review")


class EnemiesTest(unittest.TestCase):
    def patrol(self, fall_at=None, ticks=200):
        rows = []
        for t in range(ticks):
            y = 300.0 if t >= 5 else 290.0 + 2 * t  # settles from a little above the floor
            if fall_at is not None and t >= fall_at:
                y = min(GROUND, 300.0 + 8 * (t - fall_at))
            rows.append(row(t, 100, GROUND, enemies=[[1, 500.0 + t * 0.2, y], [2, 900.0, GROUND]]))
        return trace(rows)

    def test_patrolling_on_the_ledge_passes(self):
        self.assertEqual(tc.enemies_stay_up(self.patrol())["result"], "pass")

    def test_falling_off_the_ledge_fails(self):
        verdict = tc.enemies_stay_up(self.patrol(fall_at=120))
        self.assertEqual(verdict["result"], "fail")
        self.assertGreater(verdict["metrics"]["maxDrop"], 64)

    def test_no_enemy_record_is_not_a_pass(self):
        self.assertEqual(tc.enemies_stay_up(trace(walk(1, 1)))["result"], "needs-review")


class JudgeAllTest(unittest.TestCase):
    def test_every_rule_has_a_sentence_and_a_verdict(self):
        self.assertEqual(set(tc.RULES), set(tc.CHECKS))
        verdicts = tc.judge_all(trace(walk(1, 1)))
        self.assertEqual(set(verdicts), set(tc.CHECKS))
        for v in verdicts.values():
            self.assertIn(v["result"], ("pass", "fail", "needs-review"))
            self.assertTrue(v["reason"])


if __name__ == "__main__":
    unittest.main()
