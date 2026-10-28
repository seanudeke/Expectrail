"""SAM 3.1 adapter and probe, offline: a scripted transport stands in for the Meta Model API."""
import base64
import io
import json
import os
import struct
import tempfile
import unittest
import urllib.error
import zlib
from pathlib import Path
from unittest import mock

import agents.sam_observations as sam
from agents.keys import MUSE_ENV_ALLOWLIST
from agents.observations import from_trace
from agents.sam_observations import (
    Cache, MetaSamClient, SamError, from_replay, output_text, parse_output, refine_targets,
    request_body, sample, sampling_plan,
)
from agents.sam_probe import boundary_gap, markdown, probe_run, tolerance_hint
from harness.run import REPO
from nightshift.contracts import load, validate
from nightshift.evaluator import evaluate

SPEC = load(REPO / "specs" / "player-stays-above-ground.json", "test-spec")
W, H = 160, 96
GROUND_TOP = 70


def png_bytes(width: int, height: int, seed: int) -> bytes:
    """A valid RGB PNG whose pixels encode ``seed`` so every frame hashes differently."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    row = bytes([seed % 256, (seed // 256) % 256, 7]) * width
    raw = b"".join(b"\x00" + row for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def box_token(oid, box, score=None, size=(W, H)):
    """Wire record for a half-open box: corners on the wire are inclusive."""
    x0, y0, x1, y1 = box
    c = f";c={score}" if score is not None else ""
    return (f"{oid}<|box;x1={x0};y1={y0};x2={x1 - 1};y2={y1 - 1};w={size[0]};h={size[1]}{c}|>"
            f"<|mask;x=0;y=0;data={y1 - y0},{x1 - x0},!Zq9+[x]'#$%^@`{{}}|>")


def player_bottom_falling(i: int) -> int:
    """Stands on the ground until frame 33, then sinks 5 px a frame: first past 12 px at 36."""
    return GROUND_TOP + max(0, i - 33) * 5


class Scene:
    """Frames on disk plus a fake sam-3.1 that answers from a script keyed by frame and prompt."""

    def __init__(self, root: Path, frames: int = 120, bottom=lambda i: GROUND_TOP, extra=None):
        self.dir = root / "frames"
        self.dir.mkdir(parents=True)
        self.index = {}
        for i in range(frames):
            data = png_bytes(W, H, i)
            (self.dir / f"f{i:08d}.png").write_bytes(data)
            self.index[base64.b64encode(data).decode()] = i
        self.bottom = bottom
        self.extra = extra or {}
        self.bodies = []

    def answer(self, i: int, prompt: str) -> str:
        if prompt == SPEC["objects"]["player"]["prompt"]:
            b = self.bottom(i)
            return box_token(0, (60, b - 20, 80, b), 0.91)
        if prompt == SPEC["objects"]["ground"]["prompt"]:
            return box_token(0, (0, GROUND_TOP, W, H), 0.88) + "," + box_token(1, (100, 30, 140, 40), 0.62)
        return self.extra.get(prompt, lambda i: "")(i)

    def transport(self, body: dict):
        self.bodies.append(body)
        content = body["input"][0]["content"]
        prompt = content[0]["text"]
        i = self.index[content[1]["image_url"].split(",", 1)[1]]
        text = self.answer(i, prompt)
        line = f"<0f>{text}" if text else ""
        doc = {"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": line}]}]}
        return json.dumps(doc).encode(), "application/json"

    def client(self) -> MetaSamClient:
        return MetaSamClient(transport=self.transport, sleep=lambda s: None)


class WireFormatTest(unittest.TestCase):
    def test_records_are_half_open_with_scores_and_ids(self):
        text = "<0f>" + box_token(0, (251, 70, 924, 854), 0.93, size=(1280, 854)) + "," + \
            box_token(1, (10, 20, 30, 40), 0.5, size=(1280, 854))
        records = parse_output(text, frame_size=(1280, 854))
        self.assertEqual([r["id"] for r in records], [0, 1])
        self.assertEqual(records[0]["box"], [251, 70, 924, 854])
        self.assertEqual(records[0]["score"], 0.93)
        self.assertEqual(records[0]["frame"], 0)

    def test_boxes_scale_to_the_frame_when_the_service_reports_another_size(self):
        records = parse_output("<0f>" + box_token(0, (100, 50, 200, 100), 0.9, size=(800, 480)), frame_size=(1600, 960))
        self.assertEqual(records[0]["box"], [200, 100, 400, 200])

    def test_no_match_is_empty_and_video_lines_keep_their_frame(self):
        self.assertEqual(parse_output(""), [])
        text = "<0f>" + box_token(0, (1, 1, 5, 5), 0.8) + "\n<1f>" + box_token(0, (2, 2, 6, 6), 0.7)
        self.assertEqual([r["frame"] for r in parse_output(text)], [0, 1])

    def test_missing_confidence_is_none_and_bad_boxes_are_errors(self):
        self.assertIsNone(parse_output("<0f>" + box_token(0, (1, 1, 5, 5)))[0]["score"])
        with self.assertRaises(SamError):
            parse_output("<0f>0<|box;x1=1;y1=oops;x2=3;y2=4;w=9;h=9|>")

    def test_json_and_streamed_replies(self):
        text = "<0f>" + box_token(0, (1, 1, 5, 5), 0.8)
        plain = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]}
        self.assertEqual(output_text(json.dumps(plain).encode(), "application/json"), text)
        self.assertEqual(output_text(json.dumps({"output_text": text}).encode()), text)
        half = len(text) // 2
        events = [{"type": "response.output_text.delta", "delta": text[:half]},
                  {"type": "response.output_text.delta", "delta": text[half:]},
                  {"type": "response.completed"}]
        sse = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()
        self.assertEqual(output_text(sse, "text/event-stream"), text)

    def test_partial_or_failed_replies_are_errors(self):
        cut = f"data: {json.dumps({'type': 'response.output_text.delta', 'delta': '<0f>0<|bo'})}\n\n".encode()
        with self.assertRaises(SamError):
            output_text(cut, "text/event-stream")
        with self.assertRaises(SamError):
            output_text(json.dumps({"status": "incomplete", "output": []}).encode())
        with self.assertRaises(SamError):
            output_text(json.dumps({"error": {"message": "model_not_found"}}).encode())

    def test_request_asks_for_confidence_and_sends_one_concept_and_one_image(self):
        body = request_body("small robot character", "data:image/png;base64,AAAA")
        self.assertEqual(body["model"], "sam-3.1")
        self.assertEqual(body["metadata"]["include_confidence"], "true")
        content = body["input"][0]["content"]
        self.assertEqual([c["type"] for c in content], ["input_text", "input_image"])
        self.assertEqual(content[0]["text"], "small robot character")


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.png = Path(self.tmp.name) / "f00000000.png"
        self.png.write_bytes(png_bytes(W, H, 1))

    def tearDown(self):
        self.tmp.cleanup()

    def test_retries_rate_limits_then_succeeds(self):
        calls = []

        def transport(body):
            calls.append(body)
            if len(calls) == 1:
                raise urllib.error.HTTPError("u", 429, "slow down", {}, io.BytesIO(b"rate limited"))
            return json.dumps({"output_text": "<0f>" + box_token(0, (1, 1, 5, 5), 0.8)}).encode(), "application/json"

        client = MetaSamClient(transport=transport, sleep=lambda s: None)
        self.assertEqual(client.segment(self.png, "x"), [{"box": [1, 1, 5, 5], "score": 0.8}])
        self.assertEqual(client.calls, 2)

    def test_bad_requests_are_not_retried(self):
        def transport(body):
            raise urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b"mixing phrase and box prompts"))
        client = MetaSamClient(transport=transport, sleep=lambda s: None)
        with self.assertRaises(SamError) as cm:
            client.segment(self.png, "x")
        self.assertIn("400", str(cm.exception))
        self.assertEqual(client.calls, 1)

    def test_a_box_without_a_confidence_is_refused(self):
        client = MetaSamClient(transport=lambda b: (json.dumps({"output_text": "<0f>" + box_token(0, (1, 1, 5, 5))})
                                                   .encode(), ""), sleep=lambda s: None)
        with self.assertRaises(SamError):
            client.segment(self.png, "x")

    def test_the_key_comes_from_the_environment_only(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MODEL_API_KEY", None)
            with self.assertRaises(SamError) as cm:
                MetaSamClient().segment(self.png, "x")
        self.assertIn("MODEL_API_KEY", str(cm.exception))

    def test_the_fixer_never_gets_the_sam_key(self):
        self.assertNotIn("MODEL_API_KEY", MUSE_ENV_ALLOWLIST)


class SamplingTest(unittest.TestCase):
    def test_every_nth_frame_plus_the_last(self):
        self.assertEqual(sample(list(range(120)), 4)[:3], [0, 4, 8])
        self.assertEqual(sample(list(range(120)), 4)[-2:], [116, 119])
        self.assertEqual(sample(list(range(10, 50)), 10), [10, 20, 30, 40, 49])
        self.assertEqual(sample(list(range(5)), 1), [0, 1, 2, 3, 4])

    def test_counting_assertions_look_at_every_frame(self):
        visible = {"assertion": {"type": "visible", "object": "coin", "minFraction": 0.9}}
        self.assertEqual(sampling_plan(visible, 4), 1)
        self.assertEqual(sampling_plan({"assertion": {"type": "visible", "object": "coin"}}, 4), 4)
        self.assertEqual(sampling_plan(SPEC, 4), 4)

    def test_refine_fills_the_gap_before_the_first_failing_sample(self):
        looked = {0, 10, 20, 30, 40}
        self.assertEqual(refine_targets(list(range(50)), looked, {"result": "fail", "firstFrame": 40}),
                         list(range(31, 40)))
        self.assertEqual(refine_targets(list(range(50)), looked, {"result": "pass"}), [])
        self.assertEqual(len(refine_targets(list(range(50)), looked, {"result": "fail", "firstFrame": None})), 45)


class FromReplayTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_scene(self, scene, every, spec=SPEC, cache=None, refine=True):
        stats = {}
        doc = from_replay(frames_dir=scene.dir, spec=spec, every=every, refine=refine, client=scene.client(),
                          cache=cache or Cache(None), workers=3, stats=stats)
        validate(doc, "observations")
        return doc, stats

    def test_sampled_and_refined_fall_through_matches_every_frame(self):
        scene = Scene(self.root, bottom=player_bottom_falling)
        full, _ = self.run_scene(scene, every=1)
        sampled, stats = self.run_scene(scene, every=10)
        v_full, v_sampled = evaluate(SPEC, full), evaluate(SPEC, sampled)
        self.assertEqual(v_full["result"], "fail")
        self.assertEqual(v_full["firstFrame"], 36)
        self.assertEqual(v_sampled["result"], "fail")
        self.assertEqual(v_sampled["firstFrame"], 36)
        self.assertEqual(stats["framesAnalyzed"], 13 + 9)
        self.assertEqual(sampled["analysis"]["refined"], {"frames": 9, "from": 31, "to": 39})
        self.assertEqual(sampled["model"]["prompts"]["player"], "small robot character")

    def test_without_refinement_the_first_frame_is_only_as_exact_as_the_sample(self):
        scene = Scene(self.root, bottom=player_bottom_falling)
        doc, stats = self.run_scene(scene, every=10, refine=False)
        self.assertEqual(evaluate(SPEC, doc)["firstFrame"], 40)
        self.assertEqual(stats["framesAnalyzed"], 13)

    def test_clean_run_passes_on_the_sample_and_absent_frames_were_not_looked_at(self):
        scene = Scene(self.root)
        doc, stats = self.run_scene(scene, every=4)
        self.assertEqual(evaluate(SPEC, doc)["result"], "pass")
        self.assertEqual(stats["framesAnalyzed"], 31)
        self.assertNotIn(1, {f["frame"] for f in doc["frames"]})
        self.assertEqual(len(scene.bodies), 31 * 2)

    def test_a_judged_frame_is_never_sent_twice(self):
        scene = Scene(self.root, bottom=player_bottom_falling)
        cache = Cache(self.root / "cache")
        first, stats1 = self.run_scene(scene, every=10, cache=cache)
        sent = len(scene.bodies)
        second, stats2 = self.run_scene(scene, every=10, cache=Cache(self.root / "cache"))
        self.assertEqual(len(scene.bodies), sent)
        self.assertEqual(stats2["calls"], 0)
        self.assertEqual(stats2["cacheHits"], 22 * 2)
        self.assertEqual(first, second)
        other = json.loads(json.dumps(SPEC))
        other["objects"]["player"]["prompt"] = "robot"
        from_replay(frames_dir=scene.dir, spec=other, every=10, client=scene.client(), cache=cache, workers=2)
        self.assertGreater(len(scene.bodies), sent)

    def test_window_is_respected(self):
        scene = Scene(self.root, frames=60)
        spec = json.loads(json.dumps(SPEC))
        spec["window"] = {"fromFrame": 10, "toFrame": 49}
        doc, _ = self.run_scene(scene, every=10, spec=spec)
        self.assertEqual([f["frame"] for f in doc["frames"]], [10, 20, 30, 40, 49])

    def test_reaches_rechecks_every_frame_when_the_sample_misses_the_moment(self):
        coin = lambda i: box_token(0, (62, 40, 70, 50), 0.8) if i == 57 else box_token(0, (140, 10, 150, 20), 0.8)
        scene = Scene(self.root, extra={"gold coin": coin})
        spec = {"format": "nightshift.test-spec/v0", "id": "reach-coin", "instruction": "x",
                "objects": {"player": {"prompt": "small robot character"}, "coin": {"prompt": "gold coin"}},
                "assertion": {"type": "reaches", "object": "player", "goal": "coin", "distancePx": 0}}
        doc, stats = self.run_scene(scene, every=10, spec=spec)
        self.assertEqual(evaluate(spec, doc)["result"], "pass")
        self.assertEqual(stats["framesAnalyzed"], 120)

    def test_missing_frames_fail_closed_through_the_seam(self):
        with self.assertRaises(SamError):
            from_replay(frames_dir=None, spec=SPEC, client=MetaSamClient(transport=lambda b: (b"", "")))
        with self.assertRaises(SystemExit):
            from_trace({"rows": []}, provider="sam", frames_dir=None, spec=SPEC)

    def test_the_seam_passes_frames_and_spec_to_sam(self):
        scene = Scene(self.root, bottom=player_bottom_falling)
        real = sam.MetaSamClient
        with mock.patch.object(sam, "MetaSamClient", side_effect=lambda: real(transport=scene.transport)), \
                mock.patch.dict(os.environ, {"NIGHTSHIFT_SAM_CACHE": "off", "NIGHTSHIFT_SAM_EVERY": "10"}):
            doc = from_trace({"rows": []}, replay_sha256="b" * 64, provider="sam", frames_dir=str(scene.dir), spec=SPEC)
        self.assertEqual(doc["model"]["name"], "sam-3.1")
        self.assertEqual(doc["replay"]["sha256"], "b" * 64)
        self.assertEqual(evaluate(SPEC, doc)["firstFrame"], 36)


class ProbeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def make_run(self, name, bottom):
        run = self.root / name
        scene = Scene(run, bottom=bottom)
        rows = [{"tick": t, "player": [0.0, 0.0], "onFloor": bottom(t // 2) == GROUND_TOP} for t in range(0, 240)]
        (run / "trace.json").write_text(json.dumps({"physicsTicksPerSecond": 120, "rows": rows}))
        return run, scene

    def test_gap_agrees_with_the_evaluator_frame_by_frame(self):
        tol = SPEC["assertion"]["boundary"]["tolerancePx"]
        scene = Scene(self.root, bottom=player_bottom_falling)
        doc = from_replay(frames_dir=scene.dir, spec=SPEC, every=1, client=scene.client(), cache=Cache(None))
        for frame in doc["frames"]:
            gap, _ = boundary_gap(SPEC, frame["objects"])
            single = dict(doc, frames=[frame])
            self.assertEqual(gap > tol, evaluate(SPEC, single)["result"] == "fail", frame["frame"])

    def test_probe_reports_clean_and_bug_gaps(self):
        clean, clean_scene = self.make_run("clean", lambda i: GROUND_TOP)
        bug, bug_scene = self.make_run("physics-fall-through_v1", player_bottom_falling)
        runs = []
        for run, scene in ((clean, clean_scene), (bug, bug_scene)):
            runs.append(probe_run(run, SPEC, None, 10, scene.client(), Cache(None), 2, None))
        self.assertEqual(runs[0]["verdict"]["result"], "pass")
        self.assertEqual(runs[1]["verdict"]["result"], "fail")
        self.assertEqual(runs[0]["objects"]["player"]["framesFound"], 13)
        self.assertTrue(all(g["onFloor"] for g in runs[0]["gaps"]))
        hint = tolerance_hint(SPEC, runs, {"clean"})
        self.assertEqual(hint["cleanWorstGap"], 0)
        self.assertGreater(hint["others"]["physics-fall-through_v1"], 12)
        md = markdown(SPEC, runs, hint, "sam-3.1", {"calls": 52, "cacheHits": 0})
        self.assertIn("| clean | 13 | pass |", md)
        self.assertIn("worst gap", md)

    @unittest.skipUnless(__import__("importlib").util.find_spec("PIL"), "Pillow not installed")
    def test_overlays_and_contact_sheet(self):
        run, scene = self.make_run("clean", lambda i: GROUND_TOP)
        out = self.root / "probe"
        result = probe_run(run, SPEC, [0, 30, 60], 10, scene.client(), Cache(None), 2, out)
        self.assertEqual(len(result["images"]), 4)
        self.assertTrue((out / "clean-sheet.png").is_file())


class VerifierTest(unittest.TestCase):
    def test_sam_failure_on_the_candidate_is_needs_review_not_a_crash(self):
        from agents.verifier import verify
        from tests.test_agents import _request

        def harness(route, harness_out, patches=None, **_kw):
            harness_out.mkdir(parents=True, exist_ok=True)
            (harness_out / "trace.json").write_text(
                (REPO / "agents" / "fixtures" / "trace-fixed.json").read_text())
            (harness_out / "replay.json").write_text("{}\n")

        clean = load(REPO / "agents" / "fixtures" / "obs-clean.json", "observations")
        outcomes = [SystemExit("sam observations unavailable: HTTP 503"), clean]

        def observations(*_a, **_kw):
            item = outcomes.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch("agents.verifier.harness_run", side_effect=harness), \
                mock.patch("agents.verifier.from_trace", side_effect=observations):
            os.environ.pop("NIGHTSHIFT_HELDOUT_DIR", None)
            out = Path(tmp)
            doc = verify(_request(), REPO / "agents" / "fixtures" / "fix-collision-mask.patch", out)
            regression = next(c for c in doc["checks"] if c["kind"] == "regression")
            self.assertEqual(regression["result"], "needs-review")
            self.assertEqual(doc["suite"]["candidate"]["source"], "unavailable")
            self.assertNotEqual(doc["decision"], "accept")
            self.assertIn("HTTP 503", (out / "observations-error.txt").read_text())
            validate(doc, "verification")


if __name__ == "__main__":
    unittest.main()
