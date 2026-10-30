"""The run's shared SAM cache: the clean game judged once, kept only when every check passes, and
reused by the verifier for frames whose bytes match exactly."""
import base64
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agents.sam_observations as sam
import agents.sam_warm as sw
from nightshift.contracts import validate
from tests.test_agents import _held_out_dir, _request
from tests.test_sam import COINS, REPO, ROBOT, H, Scene, W, box_token, png_bytes


class SharedCacheTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.scene = Scene(self.root / "scene", extra={"blue robot": ROBOT, "gold coin": COINS})

    def harness(self, route, harness_out, patches=None, **_kw):
        # Every replay renders the same frames: a correct fix looks exactly like the clean game.
        harness_out.mkdir(parents=True, exist_ok=True)
        (harness_out / "trace.json").write_text((REPO / "agents" / "fixtures" / "trace-fixed.json").read_text())
        (harness_out / "replay.json").write_text("{}\n")
        (harness_out / "frames").mkdir(exist_ok=True)
        for i in range(120):
            (harness_out / "frames" / f"f{i:08d}.png").write_bytes(png_bytes(W, H, i))

    def patches(self, transport, env):
        real = sam.MetaSamClient
        return [mock.patch.dict(os.environ, {"NIGHTSHIFT_OBS_PROVIDER": "sam", **env}),
                mock.patch("agents.verifier.harness_run", side_effect=self.harness),
                mock.patch("agents.heldout_bench.harness_run", side_effect=self.harness),
                mock.patch.object(sam, "MetaSamClient", side_effect=lambda: real(transport=transport, retries=0))]

    def warm(self, scope="public", transport=None, env=None):
        transport = transport or self.scene.transport
        ps = self.patches(transport, env or {})
        for p in ps:
            p.start()
        try:
            if "NIGHTSHIFT_HELDOUT_DIR" not in (env or {}):
                os.environ.pop("NIGHTSHIFT_HELDOUT_DIR", None)
            return sw.warm(scope, self.root / "warm", self.root / "cache")
        finally:
            for p in reversed(ps):
                p.stop()

    def verify(self, cache_dir):
        from agents.verifier import verify
        ps = self.patches(self.scene.transport, {"NIGHTSHIFT_SAM_CACHE": str(cache_dir)})
        for p in ps:
            p.start()
        try:
            os.environ.pop("NIGHTSHIFT_HELDOUT_DIR", None)
            doc = verify(_request(), REPO / "agents" / "fixtures" / "fix-collision-mask.patch", self.root / "verify")
        finally:
            for p in reversed(ps):
                p.stop()
        validate(doc, "verification")
        return doc

    def test_a_job_that_restores_the_shared_answers_asks_sam_nothing_about_frames_it_already_judged(self):
        doc = self.warm()
        self.assertTrue(doc["shared"])
        self.assertEqual((doc["routes"], doc["problems"]), (1, []))
        self.assertEqual(doc["answers"], 240)  # 120 frames, the robot and the coins
        self.assertEqual(doc["samImages"], 240)
        self.assertIn("240 answers shared", sw.annotation(doc))
        # Another job restores the cache and verifies a fix that renders exactly the clean game.
        restored = self.root / "restored"
        shutil.copytree(self.root / "cache", restored)
        asked = len(self.scene.bodies)
        before = sam.sam_usage()
        checks = {(c["kind"], c["spec"]): c["result"] for c in self.verify(restored)["checks"]}
        self.assertEqual(len(self.scene.bodies), asked)  # not one request
        self.assertEqual(sam.sam_images_since(before), 0)
        # The same verdicts as when SAM is asked: the answers are SAM's, for the same bytes.
        self.assertEqual(checks[("regression", "player-always-visible")], "pass")
        self.assertEqual(checks[("clean", "coins-visible")], "pass")

    def test_frames_that_differ_are_still_sent_to_sam(self):
        self.warm()
        restored = self.root / "restored"
        shutil.copytree(self.root / "cache", restored)
        other = self.harness

        def changed(route, harness_out, patches=None, **kw):  # the candidate draws something else
            other(route, harness_out, patches, **kw)
            if patches:
                for i in range(0, 120, 2):
                    (harness_out / "frames" / f"f{i:08d}.png").write_bytes(png_bytes(W, H, 1000 + i))
        self.harness = changed
        index = self.scene.index
        for i in range(0, 120, 2):  # the fake SAM knows the new frames too
            index[base64.b64encode(png_bytes(W, H, 1000 + i)).decode()] = i
        asked = len(self.scene.bodies)
        self.verify(restored)
        self.assertGreater(len(self.scene.bodies), asked)  # the changed frames were asked about

    def test_nothing_is_shared_when_a_check_fails_on_the_clean_game(self):
        gone = Scene(self.root / "gone", extra={"blue robot": lambda i: ROBOT(i) if i < 60 else "",
                                                 "gold coin": COINS})
        doc = self.warm(transport=gone.transport)
        self.assertFalse(doc["shared"])
        self.assertEqual(doc["answers"], 0)
        self.assertEqual(sw.count(self.root / "cache"), 0)
        self.assertEqual(doc["problems"], [{"route": 0, "check": "player-always-visible", "result": "fail"}])
        line = sw.annotation(doc)
        self.assertIn("not shared", line)
        self.assertIn("player-always-visible fail", line)

    def test_a_weak_pass_below_the_clean_floor_is_not_shared(self):
        faint = Scene(self.root / "faint", extra={"blue robot": lambda i: box_token(0, (60, 40, 80, 70), 0.55),
                                                  "gold coin": COINS})
        doc = self.warm(transport=faint.transport)
        self.assertFalse(doc["shared"])
        self.assertEqual(doc["problems"], [{"route": 0, "check": "player-always-visible", "result": "needs-review"}])

    def test_all_scope_adds_every_private_route_and_never_prints_their_names(self):
        held = _held_out_dir(self.root)
        doc = self.warm(scope="all", env={"NIGHTSHIFT_HELDOUT_DIR": str(held)})
        self.assertTrue(doc["shared"])
        self.assertEqual(doc["routes"], 2)
        self.assertEqual(doc["answers"], 240)  # the fake renders the same frames on both routes
        line = sw.annotation(doc)
        self.assertIn("the smoke route and 1 private routes", line)
        self.assertNotIn("held-out-test", line + json.dumps(doc))

    def test_all_scope_without_the_private_set_refuses(self):
        with self.assertRaises(SystemExit):
            self.warm(scope="all")

    def test_sam_off_refuses(self):
        with mock.patch.dict(os.environ, {"NIGHTSHIFT_OBS_PROVIDER": "trace"}), self.assertRaises(SystemExit):
            sw.warm("public", self.root / "warm", self.root / "cache")

    def test_count_reads_a_cache_directory(self):
        self.assertEqual(sw.count(self.root / "nothing-here"), 0)
        (self.root / "c" / "ab").mkdir(parents=True)
        (self.root / "c" / "ab" / "abcd.json").write_text("{}")
        self.assertEqual(sw.count(self.root / "c"), 1)


if __name__ == "__main__":
    unittest.main()
