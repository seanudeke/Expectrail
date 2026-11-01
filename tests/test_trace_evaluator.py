"""The trace-contract interpreter: boundaries, the five outcomes, relations, and strict records."""
import json
import math
import unittest

from expectrail.contracts import ContractError, strict_loads, validate_v1
from expectrail.trace import signals
from expectrail.trace.evaluator import evaluate
from expectrail.trace.normalize import EpisodeError, normalize

CAPS = {"enemies": "initial-instances", "projectiles": "complete", "facing": True, "onFloor": True}


def episode(rows, inputs=(), caps=CAPS, eid="e1"):
    trace = {"physicsTicksPerSecond": 120, "rows": rows}
    if caps is not None:
        trace["capabilities"] = caps
    return normalize(trace, {"name": "t", "events": list(inputs)}, episode_id=eid)


def rows(n, *, player=lambda t: [100.0, 600.0], floor=lambda t: True, facing=lambda t: 1,
         enemies=lambda t: [], projectiles=lambda t: []):
    return [{"tick": t, "player": player(t), "onFloor": floor(t), "facing": facing(t),
             "enemies": enemies(t), "projectiles": projectiles(t)} for t in range(n)]


def spec(op, cls="player", sid="test-spec", window=None, evidence=None):
    return {"format": "expectrail.trace-spec/v1", "id": sid, "origin": "AUTO_TRACE", "statement": "test",
            "expectationRef": {"claimId": "test.claim", "authority": "inferred_code"},
            "scope": {"class": cls}, "window": window or {"kind": "episode"}, "operation": op,
            "evidenceRequirement": evidence or {"minimumTriggers": 1, "minimumEvaluations": 1, "completeWindow": True},
            "guards": []}


def shots(ticks, n=240, travel=6.0):
    """Bullets that appear at the given ticks and fly right."""
    def at(t):
        return [[i, 100.0 + (t - s) * travel, 590.0] for i, s in enumerate(ticks) if s <= t < s + 60]
    return episode(rows(n, projectiles=at), inputs=[x for s in ticks for x in
                                                     ({"tick": s, "action": "shoot", "pressed": True},
                                                      {"tick": s + 2, "action": "shoot", "pressed": False})])


def jump(rise, n=200, start=20, length=80):
    """One parabolic hop of the given height from a floor at y=600."""
    def y(t):
        if start <= t < start + length:
            u = (t - start) / length
            return [100.0, 600.0 - 4 * rise * u * (1 - u)]
        return [100.0, 600.0]
    return episode(rows(n, player=y, floor=lambda t: not (start <= t < start + length)))


class MinEventInterval(unittest.TestCase):
    OP = {"type": "min_event_interval", "event": "projectile_spawn", "seconds": 0.25}  # 30 ticks

    def test_exact_bound_passes_and_one_tick_less_fails(self):
        self.assertEqual(evaluate(spec(self.OP, "projectile"), shots([20, 50, 80]))["result"], "pass")
        v = evaluate(spec(self.OP, "projectile"), shots([20, 49]))
        self.assertEqual(v["result"], "fail")
        self.assertEqual(v["metrics"]["shortestGapTicks"], 29)
        self.assertEqual(v["evidence"][0]["fromTick"], 20)

    def test_no_bullets_or_one_bullet_is_not_exercised(self):
        self.assertEqual(evaluate(spec(self.OP, "projectile"), shots([]))["result"], "not_exercised")
        self.assertEqual(evaluate(spec(self.OP, "projectile"), shots([20]))["result"], "not_exercised")

    def test_unknown_collection_is_insufficient_never_pass(self):
        ep = episode(rows(120, projectiles=lambda t: []), caps=None)  # a legacy trace
        self.assertEqual(ep["capabilities"]["projectiles"], "unknown")
        self.assertEqual(evaluate(spec(self.OP, "projectile"), ep)["result"], "insufficient_observation")

    def test_seconds_to_ticks_rounds_minimums_up(self):
        op = dict(self.OP, seconds=0.2501)  # 30.012 ticks: a 30-tick gap is too short
        self.assertEqual(evaluate(spec(op, "projectile"), shots([20, 50]))["result"], "fail")


class MaxEpisodeRise(unittest.TestCase):
    OP = {"type": "max_episode_rise", "maxPx": 120.0}

    def test_bound_is_inclusive(self):
        self.assertEqual(evaluate(spec(self.OP), jump(100))["result"], "pass")
        v = evaluate(spec(self.OP), jump(140))
        self.assertEqual(v["result"], "fail")
        self.assertGreater(v["metrics"]["maxRisePx"], 120)

    def test_never_leaving_the_floor_is_not_exercised(self):
        self.assertEqual(evaluate(spec(self.OP), episode(rows(120)))["result"], "not_exercised")

    def test_no_floor_state_is_insufficient(self):
        r = [{k: v for k, v in row.items() if k != "onFloor"} for row in rows(120)]
        self.assertEqual(evaluate(spec(self.OP), episode(r))["result"], "insufficient_observation")

    def test_a_gap_in_the_window_is_insufficient_unless_a_counterexample(self):
        r = [row for row in jump(100)["samples"] if row["tick"] != 150]
        raw = [{"tick": s["tick"], "player": s["player"], "onFloor": s["onFloor"], "facing": 1,
                "enemies": [], "projectiles": []} for s in r]
        self.assertEqual(evaluate(spec(self.OP), episode(raw))["result"], "insufficient_observation")
        self.assertEqual(evaluate(spec(dict(self.OP, maxPx=50.0)), episode(raw))["result"], "fail")

    def test_tick_window_limits_the_spans(self):
        window = {"kind": "ticks", "fromTick": 150, "toTick": 199}
        self.assertEqual(evaluate(spec(dict(self.OP, maxPx=50.0), window=window), jump(140))["result"],
                         "not_exercised")


class DirectionAgreement(unittest.TestCase):
    def walk(self, facing):
        return episode(rows(120, player=lambda t: [100.0 + 2 * t, 600.0], facing=facing))

    def test_actor_facing_the_way_it_moves_passes(self):
        op = {"type": "direction_agreement", "subject": "actor", "maxMismatchCount": 0}
        self.assertEqual(evaluate(spec(op), self.walk(lambda t: 1))["result"], "pass")

    def test_actor_moonwalking_fails_after_the_grace(self):
        op = {"type": "direction_agreement", "subject": "actor", "maxMismatchCount": 6, "graceTicks": 6}
        v = evaluate(spec(op), self.walk(lambda t: -1))
        self.assertEqual(v["result"], "fail")
        self.assertEqual(v["excludedCount"], 6)

    def test_standing_still_is_not_exercised(self):
        op = {"type": "direction_agreement", "subject": "actor", "maxMismatchCount": 0}
        self.assertEqual(evaluate(spec(op), episode(rows(120)))["result"], "not_exercised")

    def test_bullets_against_facing_fail_and_short_lived_ones_are_excluded(self):
        op = {"type": "direction_agreement", "subject": "projectile", "maxMismatchCount": 0, "horizonTicks": 6}
        good = shots([20, 60])
        self.assertEqual(evaluate(spec(op, "projectile"), good)["result"], "pass")
        backwards = episode(rows(120, facing=lambda t: -1, projectiles=lambda t: [[0, 100.0 + 6 * (t - 20), 590.0]]
                                 if t >= 20 else []))
        self.assertEqual(evaluate(spec(op, "projectile"), backwards)["result"], "fail")
        blip = episode(rows(120, projectiles=lambda t: [[0, 100.0, 590.0]] if 20 <= t < 23 else []))
        v = evaluate(spec(op, "projectile"), blip)
        self.assertEqual((v["result"], v["excludedCount"]), ("not_exercised", 1))


class EntityChecks(unittest.TestCase):
    def enemies(self, y=lambda t: 500.0, x=lambda t: 300.0 + 50 * math.sin(t / 20), drop_at=None):
        def at(t):
            return [[7, x(t), y(t) + (100 if drop_at is not None and t >= drop_at else 0)]]
        return episode(rows(240, enemies=at))

    def test_drop_bound_and_settle(self):
        op = {"type": "max_entity_drop", "settleTicks": 30, "maxDropPx": 64.0}
        self.assertEqual(evaluate(spec(op, "enemy"), self.enemies())["result"], "pass")
        self.assertEqual(evaluate(spec(op, "enemy"), self.enemies(drop_at=100))["result"], "fail")
        self.assertEqual(evaluate(spec(op, "enemy"), self.enemies(drop_at=10))["result"], "pass")  # before settling

    def test_motion_extent(self):
        op = {"type": "min_motion_extent", "minPx": 99.0}
        self.assertEqual(evaluate(spec(op, "enemy"), self.enemies())["result"], "pass")
        stuck = self.enemies(x=lambda t: 300.0)
        self.assertEqual(evaluate(spec(op, "enemy"), stuck)["result"], "fail")

    def test_presence(self):
        op = {"type": "entity_present"}
        self.assertEqual(evaluate(spec(op, "enemy"), self.enemies())["result"], "pass")
        vanish = episode(rows(240, enemies=lambda t: [[7, 300.0, 500.0]] if t < 100 else []))
        v = evaluate(spec(op, "enemy"), vanish)
        self.assertEqual(v["result"], "fail")
        self.assertIn({"type": "enemy_gone", "tick": 100, "id": 7, "x": None, "y": None}, vanish["events"])


class EventResponse(unittest.TestCase):
    OP = {"type": "event_response", "trigger": {"action": "shoot", "pressed": True},
          "response": "projectile_spawn", "withinSeconds": 0.1, "refractorySeconds": 0.35}

    def test_ready_press_without_a_bullet_fails(self):
        self.assertEqual(evaluate(spec(self.OP, "projectile"), shots([20, 80]))["result"], "pass")
        dud = episode(rows(240), inputs=[{"tick": 20, "action": "shoot", "pressed": True}])
        v = evaluate(spec(self.OP, "projectile"), dud)
        self.assertEqual(v["result"], "fail")
        self.assertEqual(v["metrics"]["deadlineTicks"], 12)

    def test_press_during_cooldown_is_excluded(self):
        ep = episode(rows(240, projectiles=lambda t: [[0, 100.0 + 6 * (t - 20), 590.0]] if t >= 20 else []),
                     inputs=[{"tick": 20, "action": "shoot", "pressed": True},
                             {"tick": 30, "action": "shoot", "pressed": True}])
        v = evaluate(spec(self.OP, "projectile"), ep)
        self.assertEqual((v["result"], v["excludedCount"]), ("pass", 1))

    def test_press_too_close_to_the_end_is_truncated_not_failed(self):
        ep = episode(rows(100), inputs=[{"tick": 95, "action": "shoot", "pressed": True}])
        self.assertEqual(evaluate(spec(self.OP, "projectile"), ep)["result"], "not_exercised")


class Relation(unittest.TestCase):
    def op(self, comparator, tol, signal="max_rise_px"):
        return {"type": "relation", "signal": signal, "comparator": comparator, "toleranceAbs": tol,
                "left": "a", "right": "b"}

    def test_comparators_at_their_boundaries(self):
        low, high = jump(100, start=20), jump(116, start=20)
        r100 = signals.SIGNALS["max_rise_px"](low)
        r116 = signals.SIGNALS["max_rise_px"](high)
        gap = r116 - r100
        self.assertEqual(evaluate(spec(self.op("lte", gap)), low, high)["result"], "pass")
        self.assertEqual(evaluate(spec(self.op("lte", gap - 0.5)), low, high)["result"], "fail")
        self.assertEqual(evaluate(spec(self.op("gt", gap - 0.5)), low, high)["result"], "pass")
        self.assertEqual(evaluate(spec(self.op("gt", gap)), low, high)["result"], "fail")
        self.assertEqual(evaluate(spec(self.op("eq", 0)), low, low)["result"], "pass")

    def test_undefined_signal_is_insufficient_and_missing_twin_is_an_error(self):
        flat = episode(rows(120))
        op = self.op("lte", 1, signal="min_projectile_interval_ticks")
        self.assertEqual(evaluate(spec(op), flat, flat)["result"], "insufficient_observation")
        self.assertEqual(evaluate(spec(op), flat)["result"], "execution_error")


class AirJumps(unittest.TestCase):
    def hops(self, kicks):
        """Airborne from tick 10 to the end; each tick in ``kicks`` resets the upward speed, as a jump does."""
        y, vy, out = 600.0, 0.0, []
        for t in range(200):
            if t == 10 or t in kicks:
                vy = -6.0
            if t >= 10:
                vy += 0.146
                y += vy
            out.append([100.0, y])
        return episode(rows(200, player=lambda t: out[t], floor=lambda t: t < 10))

    def test_counts_kicks_in_the_air_but_not_the_take_off(self):
        self.assertEqual(signals.air_jumps(self.hops(set())), 0)
        self.assertEqual(signals.air_jumps(self.hops({40})), 1)
        self.assertEqual(signals.air_jumps(self.hops({40, 60, 80, 100})), 4)

    def test_a_cut_jump_or_a_ceiling_is_not_a_kick(self):
        def cut(t):  # rising at 6 px a tick, then the jump is released: the rise slows, it never speeds up
            return [100.0, 600.0 - (6 * t if t < 20 else 120 + 3.6 * (t - 20) - 0.07 * (t - 20) ** 2)]
        self.assertEqual(signals.air_jumps(episode(rows(60, player=cut, floor=lambda t: t == 0))), 0)
        ceiling = episode(rows(60, player=lambda t: [100.0, max(560.0, 600.0 - 6 * t)], floor=lambda t: t == 0))
        self.assertEqual(signals.air_jumps(ceiling), 0)


class Records(unittest.TestCase):
    def test_spec_language_is_closed(self):
        bad = spec({"type": "max_episode_rise", "maxPx": 10.0, "code": "import os"})
        with self.assertRaises(ContractError):
            evaluate(bad, jump(100))
        with self.assertRaises(ContractError):
            evaluate(spec({"type": "run_python", "src": "1"}), jump(100))

    def test_verdict_and_episode_validate(self):
        ep = jump(100)
        validate_v1(ep, "episode")
        v = evaluate(spec({"type": "max_episode_rise", "maxPx": 120.0}), ep)
        validate_v1(v, "trace-verdict")
        self.assertEqual(v["episodeIds"], ["e1"])

    def test_strict_json(self):
        with self.assertRaises(ValueError):
            strict_loads('{"a": 1, "a": 2}')
        with self.assertRaises(ValueError):
            strict_loads('{"a": NaN}')
        self.assertEqual(strict_loads(json.dumps({"a": 1})), {"a": 1})

    def test_malformed_traces_are_refused(self):
        with self.assertRaises(EpisodeError):
            episode([{"tick": 0, "player": [1.0, float("nan")]}])
        with self.assertRaises(EpisodeError):
            episode([{"tick": 1, "player": [1, 2]}, {"tick": 0, "player": [1, 2]}])
        with self.assertRaises(EpisodeError):
            normalize({"physicsTicksPerSecond": 120, "rows": [{"tick": 0}]}, {}, episode_id="x",
                      replay={"capture": {"fps": 50}})

    def test_absent_collections_are_empty_only_when_declared(self):
        declared = episode([{"tick": 0, "player": [1, 2], "onFloor": True, "facing": 1}])
        legacy = episode([{"tick": 0, "player": [1, 2], "onFloor": True, "facing": 1}], caps=None)
        self.assertEqual(declared["samples"][0]["projectiles"], [])
        self.assertIsNone(legacy["samples"][0]["projectiles"])


if __name__ == "__main__":
    unittest.main()
