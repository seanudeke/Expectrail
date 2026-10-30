"""The SAM video experiment: request shape, per-frame parsing, billing and the frame-by-frame comparison."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agents.sam_observations as sam
import agents.sam_video as sv
from expectrail.contracts import load
from tests.test_sam import H, W, box_token, png_bytes

VISIBLE = load(Path(__file__).resolve().parents[1] / "specs" / "player-always-visible.json", "test-spec")
ROBOT = (40, 30, 60, 70)


def sse(text: str) -> bytes:
    events = [{"type": "response.output_text.delta", "delta": line + "\n"} for line in text.splitlines()]
    events.append({"type": "response.completed"})
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


class VideoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Path(self.tmp.name) / "clean"
        (self.run / "frames").mkdir(parents=True)
        for i in range(4):
            (self.run / "frames" / f"f{i:08d}.png").write_bytes(png_bytes(W, H, i))
        self.bodies = []

    def tearDown(self):
        self.tmp.cleanup()

    def image_transport(self, body):
        self.bodies.append(body)
        return json.dumps({"output_text": "<0f>" + box_token(0, ROBOT, 0.9)}).encode(), "application/json"

    def video_transport(self, missing=()):
        def transport(body):
            self.bodies.append(body)
            lines = [f"<{k}f>" + box_token(0, ROBOT, 0.85) for k in range(4) if k not in missing]
            return sse("\n".join(lines)), "text/event-stream"
        return transport

    def test_the_request_names_one_concept_and_one_video_and_asks_for_confidence(self):
        body = sv.video_body("blue robot", "data:video/mp4;base64,AAAA")
        content = body["input"][0]["content"]
        self.assertEqual([c["type"] for c in content], ["input_text", "input_video"])
        self.assertEqual(content[1]["video_url"], "data:video/mp4;base64,AAAA")
        self.assertEqual(body["metadata"]["include_confidence"], "true")

    def test_every_frame_gets_an_answer_and_the_video_is_billed_per_frame(self):
        mp4 = Path(self.tmp.name) / "v.mp4"
        mp4.write_bytes(b"not really a video")
        client = sam.MetaSamClient(transport=self.video_transport(missing={2}), sleep=lambda s: None)
        before = sam.sam_usage()
        found = sv.segment_video(client, mp4, "blue robot", [10, 11, 12, 13], (W, H))
        self.assertEqual(sorted(found), [10, 11, 12, 13])
        self.assertEqual(found[12], [])  # no line for a frame means nothing was found there
        self.assertEqual(found[10][0]["score"], 0.85)
        after = sam.sam_usage()
        self.assertEqual(after["videoFrames"] - before["videoFrames"], sam.MIN_VIDEO_FRAMES)  # 4 frames, billed as 50
        self.assertEqual(sam.sam_images_since(before), 0)
        self.assertAlmostEqual(sam.sam_usd_since(before), 50 * 0.0002)

    def test_an_answer_for_a_frame_the_video_does_not_have_is_an_error(self):
        mp4 = Path(self.tmp.name) / "v.mp4"
        mp4.write_bytes(b"x")

        def transport(body):
            return sse("<9f>" + box_token(0, ROBOT, 0.8)), "text/event-stream"
        with self.assertRaises(sam.SamError):
            sv.segment_video(sam.MetaSamClient(transport=transport), mp4, "blue robot", [0, 1], (W, H))

    def test_a_frame_the_video_misses_is_counted_as_a_difference(self):
        image = sam.MetaSamClient(transport=self.image_transport, sleep=lambda s: None)
        video = sam.MetaSamClient(transport=self.video_transport(missing={2}), sleep=lambda s: None)
        out = Path(self.tmp.name) / "out"

        def fake_encode(frames, path, **_kw):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"mp4")
            return sorted(frames)
        with mock.patch.object(sv, "encode_mp4", side_effect=fake_encode):
            row = sv.compare_run(self.run, [VISIBLE], image, video, sam.Cache(None), out)
        s = row["specs"]["player-always-visible"]
        self.assertEqual((s["images"], s["video"]), ("pass", "fail"))
        self.assertEqual(s["framesThatDiffer"], [2])
        self.assertEqual(row["objects"]["player"]["onlyImages"], [2])
        self.assertEqual((row["images"], row["videoFrames"]), (4, 50))
        self.assertFalse((out / "clean.mp4").exists())  # the video is not kept
        self.assertIn("frames that differ 1", sv.annotation(row))
        self.assertIn("| clean | player-always-visible | pass | fail | 1 |", sv.markdown([row]))

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is not installed")
    def test_frames_encode_in_order(self):
        frames = sam.frame_files(self.run / "frames")
        order = sv.encode_mp4(frames, Path(self.tmp.name) / "v.mp4")
        self.assertEqual(order, [0, 1, 2, 3])
        self.assertGreater((Path(self.tmp.name) / "v.mp4").stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
