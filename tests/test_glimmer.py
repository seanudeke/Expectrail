"""Muse Glimmer as the frame-vision backend: request, parsing, failure paths, and the full adapter."""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import agents.glimmer_client as gl
import agents.sam_observations as sam
from agents.keys import MUSE_ENV_ALLOWLIST, require_separate_sam_key
from harness.run import REPO
from expectrail.contracts import load, validate
from expectrail.evaluator import evaluate
from tests.test_sam import png_bytes

W, H = 1600, 960


def reply(objects) -> tuple[bytes, str]:
    content = json.dumps({"objects": objects})
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode(), "application/json"


class FakeGlimmer:
    """Answers like Glimmer would: the robot on screen except in ``hidden`` frames."""

    def __init__(self, hidden=()):
        self.hidden = set(hidden)
        self.bodies = []

    def __call__(self, body: dict):
        self.bodies.append(body)
        text = body["messages"][1]["content"][0]["text"]
        url = body["messages"][1]["content"][1]["image_url"]["url"]
        frame = self.frame_of(url)
        if '"blue robot"' in text and frame not in self.hidden:
            return reply([{"box": [700, 500, 740, 560], "confidence": 0.9}])
        return reply([])

    frames: dict = {}

    def frame_of(self, url: str) -> int:
        return self.frames.get(url, -1)


class ParseTest(unittest.TestCase):
    def test_pixels_and_grids(self):
        got = gl.parse_boxes(json.dumps({"objects": [{"box": [10, 20, 50, 80], "confidence": 0.7},
                                                     {"box": [100, 100, 140, 160], "confidence": 0.95}]}), (W, H))
        self.assertEqual([d["score"] for d in got], [0.95, 0.7])  # best first, like SAM
        self.assertEqual(got[1]["box"], [10.0, 20.0, 50.0, 80.0])
        grid = gl.parse_boxes(json.dumps({"objects": [{"box": [500, 500, 525, 562.5], "confidence": 0.8}]}),
                              (W, H), "norm1000")
        self.assertEqual(grid[0]["box"], [800.0, 480.0, 840.0, 540.0])
        unit = gl.parse_boxes(json.dumps({"objects": [{"box": [0.5, 0.5, 0.525, 0.5625], "confidence": 0.8}]}),
                              (W, H), "norm1")
        self.assertEqual(unit[0]["box"], [800.0, 480.0, 840.0, 540.0])
        self.assertEqual(gl.parse_boxes('{"objects": []}', (W, H)), [])

    def test_edges(self):
        # a box a few pixels past the edge (inside the 2% margin) is clipped to the frame
        got = gl.parse_boxes(json.dumps({"objects": [{"box": [1580, 900, 1620, 970], "confidence": 0.6}]}), (W, H))
        self.assertEqual(got, [{"box": [1580.0, 900.0, 1600.0, 960.0], "score": 0.6}])
        for box in ([1580, 900, 1650, 980],   # well past the edge
                    [1601, 10, 1620, 40],     # only in the margin: no area inside the frame
                    [700, 500, 40, 60]):      # [x, y, w, h], not corners: refused, not reordered
            with self.subTest(box=box), self.assertRaises(sam.SamError):
                gl.parse_boxes(json.dumps({"objects": [{"box": box, "confidence": 0.9}]}), (W, H))

    def test_score_is_never_rounded_over_the_threshold(self):
        got = gl.parse_boxes(json.dumps({"objects": [{"box": [1, 1, 9, 9], "confidence": 0.49996}]}), (W, H))
        self.assertEqual(got[0]["score"], 0.49996)

    def test_hostile_shapes_are_samerror(self):
        for text in ('{"objects": [{"box": [1, 1, 1' + "0" * 400 + ', 9], "confidence": 0.5}]}',
                     "[" * 100000 + "]" * 100000,
                     '{"objects": [{"box": [1, 1, NaN, 9], "confidence": 0.5}]}',
                     '{"objects": [{"box": [true, 1, 5, 9], "confidence": 0.5}]}',
                     '{"objects": ["box"]}'):
            with self.subTest(text=text[:40]), self.assertRaises(sam.SamError):
                gl.parse_boxes(text, (W, H))
        parts = json.dumps({"choices": [{"message": {"content": [{"type": "text", "text": 7}]}}]}).encode()
        with self.assertRaises(sam.SamError):
            gl.answer_text(parts)
        deep = b'{"choices": ' + b"[" * 100000 + b"]" * 100000 + b"}"
        with self.assertRaises(sam.SamError):
            gl.answer_text(deep)

    def test_surprises_are_needs_review_never_pass(self):
        bad = [
            "the robot is near the middle",
            json.dumps({"boxes": []}),
            json.dumps({"objects": [{"box": [1, 2, 3, 4]}]}),
            json.dumps({"objects": [{"box": [1, 2, 3], "confidence": 0.5}]}),
            json.dumps({"objects": [{"box": [1, 2, 3, "4"], "confidence": 0.5}]}),
            json.dumps({"objects": [{"box": [1, 2, 3, 4], "confidence": 1.5}]}),
            json.dumps({"objects": [{"box": [100, 100, 5000, 5000], "confidence": 0.9}]}),
        ]
        for text in bad:
            with self.subTest(text=text), self.assertRaises(sam.SamError):
                gl.parse_boxes(text, (W, H))
        with self.assertRaises(sam.SamError):
            gl.parse_boxes('{"objects": []}', (W, H), "inches")
        with self.assertRaises(sam.SamError):
            gl.GlimmerClient(key="k", coords="inches")  # checked before any request is spent

    def test_cut_off_answers_say_so(self):
        cut = json.dumps({"choices": [{"finish_reason": "length",
                                       "message": {"content": '{"objects": [{"box": [1, 2, 3, 4], "confidence": 0.9}, {"box":'}}]}).encode()
        with self.assertRaisesRegex(sam.SamError, "cut off at max_tokens"):
            gl.answer_text(cut)

    def test_answer_budget_and_reasoning_setting(self):
        body = gl.request_body("gold coin", "data:image/png;base64,AAAA", (W, H))
        self.assertGreaterEqual(body["max_tokens"], 8192)
        self.assertNotIn("reasoning_effort", body)
        self.assertEqual(body["response_format"]["json_schema"]["schema"]["properties"]["objects"]["maxItems"], 30)
        self.assertIn("at most 30 entries", body["messages"][1]["content"][0]["text"])
        with mock.patch.dict(os.environ, {"EXPECTRAIL_GLIMMER_REASONING": "low"}):
            self.assertEqual(gl.request_body("gold coin", "u", (W, H))["reasoning_effort"], "low")

    def test_answer_text_unwraps_fences_and_parts(self):
        fenced = json.dumps({"choices": [{"message": {"content": "```json\n{\"objects\": []}\n```"}}]}).encode()
        self.assertEqual(gl.answer_text(fenced), '{"objects": []}')
        parts = json.dumps({"choices": [{"message": {"content": [{"type": "text", "text": "{}"}]}}]}).encode()
        self.assertEqual(gl.answer_text(parts), "{}")
        with self.assertRaises(sam.SamError):
            gl.answer_text(b"<html>")


class ErrorKindTest(unittest.TestCase):
    """The held-out verify run reports these kinds, never the error text (it can quote a held-out frame)."""

    def raised(self, fn) -> str:
        with self.assertRaises(sam.SamError) as ctx:
            fn()
        return f"sam observations unavailable: {ctx.exception}"

    def test_the_client_s_own_errors_get_their_kind(self):
        box = lambda b: json.dumps({"objects": [{"box": b, "confidence": 0.9}]})  # noqa: E731
        cases = {
            "inverted or malformed box (strict parse)": lambda: gl.parse_boxes(box([815, 165, 780, 120]), (W, H)),
            "box outside the frame (strict parse)": lambda: gl.parse_boxes(box([780, 120, 2 * W, 165]), (W, H)),
            "answer not JSON": lambda: gl.parse_boxes('{"objects": [{"box": [780, 120, 815, 165], "con', (W, H)),
            "answer cut off at max_tokens": lambda: gl.answer_text(json.dumps(
                {"choices": [{"message": {"content": "{"}, "finish_reason": "length"}]}).encode()),
            "reply not a chat completion": lambda: gl.answer_text(b"<html>"),
        }
        for kind, fn in cases.items():
            with self.subTest(kind):
                self.assertEqual(gl.error_kind(self.raised(fn)), kind)

    def test_http_unreachable_sam_and_unknown(self):
        self.assertEqual(gl.error_kind('sam observations unavailable: glimmer HTTP 412: {"error": "x"}'),
                         "glimmer HTTP 412")
        self.assertEqual(gl.error_kind("glimmer unreachable after 4 tries: TimeoutError"),
                         "glimmer unreachable after retries (timeouts or resets)")
        self.assertEqual(gl.error_kind("sam observations unavailable: sam-3.1 unreachable after 4 tries"), "SAM error")
        self.assertEqual(gl.error_kind("something new"), "other error")

    def test_no_content_from_the_answer_survives(self):
        text = self.raised(lambda: gl.parse_boxes('{"objects": [{"box": [780, 120, 815, 165], "con', (W, H)))
        self.assertIn("780", text)
        self.assertNotIn("780", gl.error_kind(text))


class GridTest(unittest.TestCase):
    """Glimmer answers on a 0-1000 grid (measured against the engine, run 40936605897): ask for it, read it."""

    def test_the_default_is_the_0_1000_grid_and_the_prompt_asks_for_it(self):
        with mock.patch.dict(os.environ, {"EXPECTRAIL_GLIMMER_COORDS": ""}):
            os.environ.pop("EXPECTRAIL_GLIMMER_COORDS")
            client = gl.GlimmerClient(key="k", transport=lambda b: reply([{"box": [470, 690, 535, 830],
                                                                           "confidence": 0.9}]))
            self.assertEqual(client.coords, "norm1000")
            png = Path(tempfile.mkdtemp()) / "f.png"
            png.write_bytes(png_bytes(W, H, 0))
            # Clean frame 0: the engine puts the robot at [760, 660, 840, 780].
            self.assertEqual(client.segment(png, "blue robot"), [{"box": [752.0, 662.4, 856.0, 796.8], "score": 0.9}])
        self.assertIn("0 to 1000 grid", gl.user_prompt("blue robot", (W, H), "norm1000"))
        self.assertNotIn(str(W), gl.user_prompt("blue robot", (W, H), "norm1000"))  # no pixel size to rescale by
        self.assertIn("pixels of this image", gl.user_prompt("blue robot", (W, H), "pixels"))
        body = gl.request_body("blue robot", "data:,", (W, H), coords="norm1000")
        self.assertIn("0 to 1000 grid", body["messages"][1]["content"][0]["text"])


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.png = Path(self.tmp.name) / "f00000000.png"
        self.png.write_bytes(png_bytes(W, H, 1))

    def tearDown(self):
        self.tmp.cleanup()

    def test_request_shape(self):
        body = gl.request_body("blue robot", "data:image/png;base64,AAAA", (W, H))
        self.assertEqual(body["model"], "accounts/fireworks/models/muse-glimmer-30b")
        self.assertEqual(body["temperature"], 0)
        user = body["messages"][1]["content"]
        self.assertIn('"blue robot"', user[0]["text"])
        self.assertIn("1600 by 960 pixels", user[0]["text"])
        self.assertEqual(user[1], {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}})
        self.assertEqual(body["response_format"]["type"], "json_schema")
        # positions stay in code: Glimmer is asked where the thing is, never whether it is "below" anything
        for word in ("below", "above", "under", "ground line"):
            self.assertNotIn(word, user[0]["text"].lower())

    def test_segment_and_schema_fallback(self):
        calls = []

        def transport(body):
            calls.append(body["response_format"]["type"])
            if body["response_format"]["type"] == "json_schema":
                raise urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b"json_schema not supported"))
            return reply([{"box": [700, 500, 740, 560], "confidence": 0.9}])

        client = gl.GlimmerClient(transport=transport, key="k", sleep=lambda s: None, coords="pixels")
        got = client.segment(self.png, "blue robot")
        self.assertEqual(got, [{"box": [700.0, 500.0, 740.0, 560.0], "score": 0.9}])
        client.segment(self.png, "blue robot")
        self.assertEqual(calls, ["json_schema", "json_object", "json_object"])  # remembered
        self.assertIn("open-weights glimmer at api.fireworks.ai", client.provider)

    def test_only_a_schema_refusal_switches_to_json_mode(self):
        def too_big(body):
            raise urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b"image exceeds the size limit"))

        client = gl.GlimmerClient(transport=too_big, key="k", sleep=lambda s: None)
        with self.assertRaisesRegex(sam.SamError, "glimmer HTTP 400"):
            client.segment(self.png, "blue robot")
        self.assertTrue(client._structured)

    def test_errors_and_retries(self):
        seen = []

        def flaky(body):
            seen.append(1)
            if len(seen) < 3:
                raise urllib.error.HTTPError("u", 503, "busy", {}, io.BytesIO(b""))
            return reply([])

        client = gl.GlimmerClient(transport=flaky, key="k", sleep=lambda s: None)
        self.assertEqual(client.segment(self.png, "gold coin"), [])
        self.assertEqual(client.calls, 3)

        def denied(body):
            raise urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO(b"bad key"))

        with self.assertRaisesRegex(sam.SamError, "glimmer HTTP 401"):
            gl.GlimmerClient(transport=denied, key="k", sleep=lambda s: None).segment(self.png, "gold coin")

    def test_key_rules(self):
        with mock.patch.dict(os.environ, {"FIREWORKS_API_KEY": "", "EXPECTRAIL_GLIMMER_API_KEY": ""}):
            with self.assertRaisesRegex(sam.SamError, "FIREWORKS_API_KEY"):
                gl.GlimmerClient()._http({})
        with mock.patch.dict(os.environ, {"FIREWORKS_API_KEY": "same", "META_API_KEY": "same"}):
            with self.assertRaisesRegex(sam.SamError, "META_API_KEY"):
                gl.GlimmerClient()._http({})
        self.assertFalse(set(gl.KEY_ENVS) & MUSE_ENV_ALLOWLIST)
        env = {"EXPECTRAIL_OBS_PROVIDER": "sam", "EXPECTRAIL_VISION_BACKEND": "glimmer", "META_API_KEY": "m",
               "FIREWORKS_API_KEY": "", "EXPECTRAIL_GLIMMER_API_KEY": "", "MODEL_API_KEY": ""}
        with mock.patch.dict(os.environ, env):
            with self.assertRaises(SystemExit):
                require_separate_sam_key()
            os.environ["FIREWORKS_API_KEY"] = "m"
            with self.assertRaises(SystemExit):
                require_separate_sam_key()
            os.environ["FIREWORKS_API_KEY"] = "g"
            require_separate_sam_key()  # no MODEL_API_KEY needed when Glimmer is the eyes

    def test_both_counts_an_object_only_when_both_see_it(self):
        sam_calls = []

        class FakeSam:
            model, base, calls, seconds = "sam-3.1", "https://api.meta.ai/v1", 0, 0.0

            def segment(self, png, prompt):
                sam_calls.append(prompt)
                return [{"box": [700.0, 500.0, 740.0, 560.0], "score": 0.8}]

        def glimmer_answer(objects):
            return gl.GlimmerClient(transport=lambda b: reply(objects), key="k", sleep=lambda s: None)

        both = gl.BothClient(FakeSam(), glimmer_answer([]))
        self.assertEqual(both.segment(self.png, "blue robot"), [])
        self.assertEqual(sam_calls, [])  # Glimmer does not see it: SAM is not asked
        both = gl.BothClient(FakeSam(), glimmer_answer([{"box": [1, 1, 9, 9], "confidence": 0.3}]))
        self.assertEqual(both.segment(self.png, "blue robot"), [])  # below the evaluator's threshold
        both = gl.BothClient(FakeSam(), glimmer_answer([{"box": [690, 495, 745, 565], "confidence": 0.9}]))
        self.assertEqual(both.segment(self.png, "blue robot"), [{"box": [700.0, 500.0, 740.0, 560.0], "score": 0.8}])
        self.assertIn("counted only where open-weights glimmer", both.provider)

        class BlindSam(FakeSam):
            def segment(self, png, prompt):
                return []

        # Glimmer talked into "it's there" (text drawn into the game): SAM still has to find it.
        fooled = gl.BothClient(BlindSam(), glimmer_answer([{"box": [700, 500, 740, 560], "confidence": 0.99}]))
        self.assertEqual(fooled.segment(self.png, "blue robot"), [])

    def test_glimmer_alone_never_decides_a_verdict(self):
        with mock.patch.dict(os.environ, {"EXPECTRAIL_VISION_BACKEND": "glimmer", "EXPECTRAIL_GLIMMER_ALONE": ""}):
            with self.assertRaisesRegex(sam.SamError, "both"):
                sam.default_client(verdict=True)
            self.assertIsInstance(sam.default_client(), gl.GlimmerClient)  # measuring is fine
            os.environ["EXPECTRAIL_GLIMMER_ALONE"] = "1"
            self.assertIsInstance(sam.default_client(verdict=True), gl.GlimmerClient)
        with mock.patch.dict(os.environ, {"EXPECTRAIL_VISION_BACKEND": "both"}):
            self.assertIsInstance(sam.default_client(verdict=True), gl.BothClient)
            self.assertEqual(sam.vision_label(), "SAM 3.1 with Muse Glimmer")
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"EXPECTRAIL_VISION_BACKEND": "glimmer", "EXPECTRAIL_GLIMMER_ALONE": ""}):
            frames = Path(tmp) / "frames"
            frames.mkdir()
            (frames / "f00000000.png").write_bytes(png_bytes(W, H, 0))
            spec = load(REPO / "specs" / "player-always-visible.json", "test-spec")
            with self.assertRaises(sam.SamError):  # the verifier turns this into needs-review
                sam.from_replay(frames_dir=frames, spec=spec, cache=sam.Cache(None))

    def test_keys_for_both_and_typos(self):
        base = {"EXPECTRAIL_OBS_PROVIDER": "sam", "META_API_KEY": "m", "FIREWORKS_API_KEY": "g",
                "EXPECTRAIL_GLIMMER_API_KEY": ""}
        with mock.patch.dict(os.environ, {**base, "EXPECTRAIL_VISION_BACKEND": "both", "MODEL_API_KEY": ""}):
            with self.assertRaises(SystemExit):
                require_separate_sam_key()  # both still needs SAM's own key
            os.environ["MODEL_API_KEY"] = "s"
            require_separate_sam_key()
        with mock.patch.dict(os.environ, {**base, "EXPECTRAIL_VISION_BACKEND": "glimer", "MODEL_API_KEY": "s"}):
            with self.assertRaises(SystemExit):
                require_separate_sam_key()  # a typo stops the run before the fixer, not after

    def test_backend_switch(self):
        with mock.patch.dict(os.environ, {"EXPECTRAIL_VISION_BACKEND": "glimmer"}):
            self.assertIsInstance(sam.default_client(), gl.GlimmerClient)
        with mock.patch.dict(os.environ, {"EXPECTRAIL_VISION_BACKEND": ""}):
            self.assertNotIsInstance(sam.default_client(), gl.GlimmerClient)
        with mock.patch.dict(os.environ, {"EXPECTRAIL_VISION_BACKEND": "llava"}):
            with self.assertRaises(sam.SamError):
                sam.default_client()


class WarmTest(unittest.TestCase):
    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def test_waits_through_503_until_the_deployment_answers(self):
        answers = [503, 429, 200]
        seen = []

        def opener(req, timeout):
            seen.append((req.full_url, json.loads(req.data)["model"]))
            code = answers.pop(0)
            if code != 200:
                raise urllib.error.HTTPError(req.full_url, code, "starting", {}, io.BytesIO(b"scaling up"))
            return self.Resp(b'{"choices": []}')

        t = [0.0]
        waited = gl.warm(base="https://api.fireworks.ai/inference/v1", model="accounts/me/deployments/abc",
                         key="k", opener=opener, sleep=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0])
        self.assertEqual(waited, 30.0)
        self.assertEqual(seen[0], ("https://api.fireworks.ai/inference/v1/chat/completions", "accounts/me/deployments/abc"))

    def test_setup_errors_stop_at_once_and_say_what_to_do(self):
        def missing(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b'{"error":"Model not found"}'))

        with self.assertRaisesRegex(sam.SamError, "on-demand deployment"):
            gl.warm(key="k", opener=missing, sleep=lambda s: None)

    def test_a_deployment_waking_from_zero_may_answer_404_first(self):
        # Oct 29, run 40986446779: "Model not found ... not deployed" until the replica came up.
        answers = [404, 404, 200]

        def opener(req, timeout):
            code = answers.pop(0)
            if code != 200:
                raise urllib.error.HTTPError(req.full_url, code, "nf", {}, io.BytesIO(b'{"error":"not deployed"}'))
            return self.Resp(b'{"choices": []}')

        t = [0.0]
        waited = gl.warm(base="https://api.fireworks.ai/inference/v1", model="accounts/me/deployments/abc",
                         key="k", opener=opener, sleep=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0])
        self.assertEqual(waited, 30.0)

        def never(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b'{"error":"not deployed"}'))

        t = [0.0]
        with self.assertRaisesRegex(sam.SamError, "did not wake.*HTTP 404"):
            gl.warm(model="accounts/me/deployments/abc", key="k", opener=never, timeout_s=60, every_s=15,
                    sleep=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0])

    def test_gives_up_after_the_timeout(self):
        def busy(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, io.BytesIO(b""))

        t = [0.0]
        with self.assertRaisesRegex(sam.SamError, "did not wake"):
            gl.warm(key="k", opener=busy, timeout_s=60, every_s=15,
                    sleep=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0])


class AdapterTest(unittest.TestCase):
    """The whole SAM adapter (sample, refine, confirm, cache) runs unchanged on Glimmer."""

    def _frames(self, root: Path, n: int = 40) -> tuple[Path, dict]:
        frames = root / "frames"
        frames.mkdir()
        urls = {}
        for i in range(n):
            path = frames / f"f{i:08d}.png"
            path.write_bytes(png_bytes(W, H, i))
            urls[sam.data_url(path)] = i
        return frames, urls

    def _spec(self):
        spec = load(REPO / "specs" / "player-always-visible.json", "test-spec")
        spec["window"] = {"fromFrame": 0, "toFrame": 39}
        return spec

    def test_pass_rests_on_every_frame_and_hidden_robot_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames, urls = self._frames(Path(tmp))
            fake = FakeGlimmer()
            fake.frames = urls
            client = gl.GlimmerClient(transport=fake, key="k", sleep=lambda s: None, coords="pixels")
            stats: dict = {}
            doc = sam.from_replay(frames_dir=frames, spec=self._spec(), client=client,
                                  cache=sam.Cache(None), workers=2, stats=stats)
            validate(doc, "observations")
            self.assertEqual(evaluate(self._spec(), doc)["result"], "pass")
            self.assertEqual(stats["framesAnalyzed"], 40)  # a pass is confirmed on every frame
            self.assertIn("open-weights glimmer", doc["model"]["provider"])
            self.assertEqual(doc["model"]["name"], gl.MODEL)

            hiding = FakeGlimmer(hidden=range(20, 40))
            hiding.frames = urls
            client = gl.GlimmerClient(transport=hiding, key="k", sleep=lambda s: None, coords="pixels")
            doc = sam.from_replay(frames_dir=frames, spec=self._spec(), client=client, cache=sam.Cache(None))
            verdict = evaluate(self._spec(), doc)
            self.assertEqual(verdict["result"], "fail")

    def test_cache_never_mixes_sam_and_glimmer_answers(self):
        sam_key = sam.Cache.key("f" * 64, "blue robot", sam.MODEL, sam.API_BASE)
        client = gl.GlimmerClient(key="k")
        glimmer_key = sam.Cache.key("f" * 64, "blue robot", client.model, client.base + client.cache_tag)
        self.assertNotEqual(sam_key, glimmer_key)
        other = gl.GlimmerClient(key="k", coords="pixels")
        self.assertNotEqual(glimmer_key, sam.Cache.key("f" * 64, "blue robot", other.model,
                                                       other.base + other.cache_tag))

    def test_a_glimmer_failure_is_needs_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames, urls = self._frames(Path(tmp), n=8)

            def prose(body):
                return json.dumps({"choices": [{"message": {"content": "I see a robot!"}}]}).encode(), ""

            client = gl.GlimmerClient(transport=prose, key="k", sleep=lambda s: None)
            with self.assertRaises(sam.SamError):
                sam.from_replay(frames_dir=frames, spec=self._spec(), client=client, cache=sam.Cache(None))


if __name__ == "__main__":
    unittest.main()
