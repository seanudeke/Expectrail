"""The engine cross-check: Glimmer's boxes count only where the engine put that object."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agents.glimmer_client as gl
import agents.sam_observations as sam
from agents.engine_check import MAX_SIZE_RATIO, EngineCheck, agrees, check_for_trace
from agents.keys import require_separate_sam_key
from agents.observations import COIN_HALF, engine_refs_by_frame, from_trace
from harness.run import REPO
from expectrail.contracts import load, validate
from expectrail.evaluator import evaluate
from tests.test_sam import png_bytes

W, H = 1600, 960
N = 12  # captured frames; the trace has two physics ticks per frame
VIEW = [2.0, 0.0, 0.0, 2.0, 0.0, 0.0]  # world to frame pixels, as the harness logs it
PLAYER = (360.0, 250.0)  # world origin of the robot
COIN = (500.0, 200.0)  # world centre of a coin

# Where the engine puts them in frame pixels (see agents.observations): the robot's body is 40x60
# world pixels ending at its feet (origin + FEET_OFFSET), the coin 2 * COIN_HALF square.
ROBOT_BOX = [680.0, 406.5, 760.0, 526.5]
COIN_BOX = [979.2, 379.2, 1020.8, 420.8]

HONEST_ROBOT = [690, 400, 750, 540]  # Glimmer's own box: taller, narrower, on the robot
HONEST_COIN = [985, 385, 1015, 425]
ELSEWHERE = [100, 100, 160, 240]  # "the robot is here", where the engine never put it
WHOLE_FRAME = [0, 0, W, H]  # contains everything's centre


def trace(player=PLAYER, coins=(COIN,), view=VIEW, frames: int = N) -> dict:
    rows = []
    for tick in range(frames * 2):
        row = {"tick": tick, "player": list(player), "onFloor": True, "ground": 300.0}
        if coins:
            row["coins"] = [list(c) for c in coins]
        if view:
            row["view"] = list(view)
        rows.append(row)
    return {"format": "expectrail.trace/v0", "ticks": len(rows), "physicsTicksPerSecond": 120, "rows": rows}


class FakeGlimmer:
    """Answers each prompt with the boxes given for that frame (default: none)."""

    def __init__(self, robot=None, coin=None):
        self.robot, self.coin = robot or {}, coin or {}
        self.frames: dict = {}

    def __call__(self, body):
        text = body["messages"][1]["content"][0]["text"]
        frame = self.frames.get(body["messages"][1]["content"][1]["image_url"]["url"], -1)
        table = self.robot if '"blue robot"' in text else self.coin if '"gold coin"' in text else {}
        boxes = table.get(frame, [])
        # Glimmer answers on a 0-1000 grid over the image; the boxes above are in frame pixels.
        grid = [[b[0] * 1000 / W, b[1] * 1000 / H, b[2] * 1000 / W, b[3] * 1000 / H] for b in boxes]
        content = json.dumps({"objects": [{"box": g, "confidence": 0.95} for g in grid]})
        return json.dumps({"choices": [{"message": {"content": content}}]}).encode(), "application/json"


def every_frame(box) -> dict:
    return {i: [box] for i in range(N)}


class RuleTest(unittest.TestCase):
    def test_a_box_on_the_object_agrees(self):
        self.assertTrue(agrees(HONEST_ROBOT, ROBOT_BOX))
        self.assertTrue(agrees(HONEST_COIN, COIN_BOX))

    def test_a_box_beside_or_over_everything_does_not(self):
        self.assertFalse(agrees(ELSEWHERE, ROBOT_BOX))
        self.assertFalse(agrees(WHOLE_FRAME, ROBOT_BOX))  # contains the centre, but says nothing
        self.assertFalse(agrees([761, 400, 830, 540], ROBOT_BOX))  # beside: starts past its right edge (760)
        self.assertTrue(agrees([721, 400, 790, 540], ROBOT_BOX))  # a few pixels off, still on the robot
        self.assertTrue(agrees([1012, 385, 1042, 425], COIN_BOX))  # a coin box 12 px off its centre
        w = ROBOT_BOX[2] - ROBOT_BOX[0]
        big = [720 - MAX_SIZE_RATIO * w / 2 - 1, 400, 720 + MAX_SIZE_RATIO * w / 2 + 1, 540]
        self.assertFalse(agrees(big, ROBOT_BOX))

    def test_the_engine_places_the_robot_and_the_coins_in_frame_pixels(self):
        refs = engine_refs_by_frame(trace(), (W, H), [0, N - 1])
        self.assertEqual(refs[0]["player"], [ROBOT_BOX])
        self.assertEqual(refs[0]["coin"], [COIN_BOX])
        self.assertAlmostEqual(COIN_BOX[2] - COIN_BOX[0], 4 * COIN_HALF, places=3)
        self.assertEqual(engine_refs_by_frame(trace(coins=()), (W, H), [0])[0]["coin"], [])
        self.assertEqual(engine_refs_by_frame(trace(view=None), (W, H), [0]), {})  # cannot place: left out
        self.assertNotIn(N, engine_refs_by_frame(trace(), (W, H), [N]))  # past the trace

    def test_unplaceable_frames_and_unknown_objects_are_errors_not_passes(self):
        check = EngineCheck({0: {"player": [ROBOT_BOX], "coin": []}})
        kept = check({0: {"player": [{"box": HONEST_ROBOT, "score": 0.9}, {"box": ELSEWHERE, "score": 0.99}]}})
        self.assertEqual([d["box"] for d in kept[0]["player"]], [HONEST_ROBOT])
        self.assertEqual(check.summary()["dropped"], {"player": 1})
        with self.assertRaisesRegex(sam.SamError, "frame 1"):
            check({1: {"player": []}})
        with self.assertRaisesRegex(sam.SamError, "enemy"):
            check({0: {"enemy": []}})
        with self.assertRaisesRegex(sam.SamError, "trace"):
            check_for_trace(None, [0])
        with self.assertRaisesRegex(sam.SamError, "camera"):
            check_for_trace(trace(view=None), [0])


class AdapterTest(unittest.TestCase):
    """from_replay with Glimmer checked against the engine, as the verifier runs it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.frames = Path(self.tmp.name) / "frames"
        self.frames.mkdir()
        self.urls = {}
        for i in range(N):
            path = self.frames / f"f{i:08d}.png"
            path.write_bytes(png_bytes(W, H, i))
            self.urls[sam.data_url(path)] = i

    def tearDown(self):
        self.tmp.cleanup()

    def spec(self, name: str) -> dict:
        spec = load(REPO / "specs" / f"{name}.json", "test-spec")
        spec["window"] = {"fromFrame": 0, "toFrame": N - 1}
        return spec

    def observe(self, spec, fake, the_trace=None):
        fake.frames = self.urls
        client = gl.EngineCheckedGlimmer(transport=fake, key="k", sleep=lambda s: None)
        return sam.from_replay(the_trace if the_trace is not None else trace(), frames_dir=self.frames,
                               spec=spec, client=client, cache=sam.Cache(None), workers=2)

    def test_honest_answers_pass_and_say_they_were_checked(self):
        robot = self.observe(self.spec("player-always-visible"), FakeGlimmer(robot=every_frame(HONEST_ROBOT)))
        coins = self.observe(self.spec("coins-visible"), FakeGlimmer(coin=every_frame(HONEST_COIN)))
        for name, doc in (("player-always-visible", robot), ("coins-visible", coins)):
            validate(doc, "observations")
            self.assertEqual(evaluate(self.spec(name), doc)["result"], "pass", name)
            self.assertIn("checked against the engine", doc["model"]["provider"])
            self.assertEqual(sum(doc["model"]["engineCheck"]["dropped"].values()), 0)
        self.assertEqual(robot["model"]["engineCheck"]["kept"], {"player": N})

    def test_a_hidden_robot_still_fails_whatever_glimmer_is_talked_into(self):
        # Frames 6 on: the robot is hidden. Glimmer answers "it's there" somewhere else, or over the
        # whole frame (both contain no information about where the robot is); both are dropped.
        for injected in (ELSEWHERE, WHOLE_FRAME):
            answers = {i: [HONEST_ROBOT] if i < 6 else [injected] for i in range(N)}
            doc = self.observe(self.spec("player-always-visible"), FakeGlimmer(robot=answers))
            verdict = evaluate(self.spec("player-always-visible"), doc)
            self.assertEqual(verdict["result"], "fail", injected)
            looked = {f["frame"] for f in doc["frames"]}  # sampled, then refined around the first fail
            self.assertEqual(doc["model"]["engineCheck"]["dropped"]["player"], len({i for i in looked if i >= 6}))
            self.assertGreater(doc["model"]["engineCheck"]["dropped"]["player"], 0)

    def test_coins_drawn_where_the_engine_has_none_do_not_count(self):
        doc = self.observe(self.spec("coins-visible"), FakeGlimmer(coin=every_frame(HONEST_COIN)),
                           trace(coins=((900.0, 400.0),)))  # the engine's coin is elsewhere
        self.assertEqual(evaluate(self.spec("coins-visible"), doc)["result"], "fail")
        doc = self.observe(self.spec("coins-visible"), FakeGlimmer(coin=every_frame(HONEST_COIN)), trace(coins=()))
        self.assertEqual(evaluate(self.spec("coins-visible"), doc)["result"], "fail")

    def test_without_a_trace_that_places_objects_it_is_needs_review(self):
        fake = FakeGlimmer(robot=every_frame(HONEST_ROBOT))
        fake.frames = self.urls
        client = gl.EngineCheckedGlimmer(transport=fake, key="k", sleep=lambda s: None)
        for bad in (None, trace(view=None), trace(frames=N // 2)):
            with self.assertRaises(sam.SamError):
                sam.from_replay(bad, frames_dir=self.frames, spec=self.spec("player-always-visible"),
                                client=client, cache=sam.Cache(None))

    def test_the_verifier_path_hands_the_trace_to_the_check(self):
        # agents.observations.from_trace is what the verifier calls; the check must see the trace there.
        fake = FakeGlimmer(robot={i: [ELSEWHERE] for i in range(N)})
        fake.frames = self.urls
        client = gl.EngineCheckedGlimmer(transport=fake, key="k", sleep=lambda s: None)
        with mock.patch.object(sam, "default_client", return_value=client):
            doc = from_trace(trace(), provider="sam", frames_dir=str(self.frames),
                             spec=self.spec("player-always-visible"))
        self.assertEqual(doc["model"]["engineCheck"]["dropped"]["player"], doc["analysis"]["framesAnalyzed"])
        self.assertEqual(evaluate(self.spec("player-always-visible"), doc)["result"], "fail")


class BackendTest(unittest.TestCase):
    def test_glimmer_engine_decides_verdicts_without_sam(self):
        env = {"EXPECTRAIL_VISION_BACKEND": "glimmer-engine", "EXPECTRAIL_GLIMMER_ALONE": "",
               "EXPECTRAIL_GLIMMER_API_KEY": "glimmer-key", "EXPECTRAIL_OBS_PROVIDER": "sam",
               "MODEL_API_KEY": "", "META_API_KEY": "muse-key"}
        with mock.patch.dict(os.environ, env):
            client = sam.default_client(verdict=True)
            self.assertIsInstance(client, gl.EngineCheckedGlimmer)
            self.assertTrue(client.engine_checked)
            self.assertEqual(sam.vision_label(), "Muse Glimmer checked against the engine")
            require_separate_sam_key()  # no SAM key needed
            os.environ["EXPECTRAIL_GLIMMER_API_KEY"] = "muse-key"
            with self.assertRaises(SystemExit):
                require_separate_sam_key()  # but never the fixer's key

    def test_the_cache_holds_raw_answers_shared_with_plain_glimmer(self):
        # The check depends on the trace, so it runs after the cache, never inside it.
        plain, checked = gl.GlimmerClient(key="k"), gl.EngineCheckedGlimmer(key="k")
        self.assertEqual(plain.base + plain.cache_tag, checked.base + checked.cache_tag)


if __name__ == "__main__":
    unittest.main()
