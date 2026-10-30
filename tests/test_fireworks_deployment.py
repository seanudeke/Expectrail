"""Checking the Glimmer deployment and restoring its scaling after a suspension (fake control plane)."""
from __future__ import annotations

import io
import json
import os
import unittest
import urllib.error
import urllib.parse
from contextlib import redirect_stdout
from unittest import mock

import agents.fireworks_deployment as fd

MODEL = "accounts/acme/deployments/abc123"
HEALTHY = {"name": MODEL, "state": "READY", "baseModel": "accounts/fireworks/models/muse-glimmer-30b",
           "deploymentShape": "glimmer-h200", "acceleratorType": "NVIDIA_H200_141GB",
           "minReplicaCount": 0, "maxReplicaCount": 1,
           "autoscalingPolicy": {"scaleToZeroWindow": "900s", "scaleUpWindow": "30s", "scaleDownWindow": "600s"}}
SUSPENDED_RESET = dict(HEALTHY, maxReplicaCount=0,
                       autoscalingPolicy=dict(HEALTHY["autoscalingPolicy"], scaleToZeroWindow="3600s"))


class Resp:
    def __init__(self, body: dict):
        self.body = json.dumps(body).encode()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeFireworks:
    """GET returns the stored deployment; PATCH applies only the fields named in updateMask."""

    def __init__(self, dep: dict, refuse=(), status: int | None = None):
        self.dep, self.refuse, self.status = json.loads(json.dumps(dep)), set(refuse), status
        self.calls = []

    def __call__(self, req, timeout=None):
        url = urllib.parse.urlparse(req.full_url)
        self.calls.append((req.get_method(), url.path, url.query))
        assert req.headers["Authorization"] == "Bearer k"
        if self.status:
            raise urllib.error.HTTPError(req.full_url, self.status, "x", {}, io.BytesIO(b'{"error":"suspended"}'))
        if req.get_method() == "GET":
            return Resp(self.dep)
        mask = urllib.parse.parse_qs(url.query)["updateMask"][0]
        if mask in self.refuse:
            raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, io.BytesIO(b'{"error":"bad mask"}'))
        body = json.loads(req.data)
        for path in mask.split(","):
            camel = path.replace("min_replica_count", "minReplicaCount").replace(
                "max_replica_count", "maxReplicaCount").replace("autoscaling_policy.scale_to_zero_window",
                                                                "autoscalingPolicy.scaleToZeroWindow")
            if "." in camel:
                outer, inner = camel.split(".")
                self.dep.setdefault(outer, {})[inner] = body[outer][inner]
            else:
                self.dep[camel] = body[camel]
        return Resp({})


class DeploymentTest(unittest.TestCase):
    def test_reads_durations_and_finds_problems(self):
        self.assertEqual(fd.seconds("900s"), 900)
        self.assertEqual(fd.seconds("1h"), 3600)
        self.assertEqual(fd.seconds("15m0s"), 900)
        self.assertIsNone(fd.seconds("soon"))
        self.assertEqual(fd.problems(HEALTHY), [])
        self.assertEqual(len(fd.problems(SUSPENDED_RESET)), 2)
        self.assertEqual(fd.parse_deployment(MODEL), ("acme", "abc123"))
        self.assertIsNone(fd.parse_deployment("accounts/fireworks/models/muse-glimmer-30b"))

    def test_restores_only_the_three_fields_after_a_suspension(self):
        fake = FakeFireworks(SUSPENDED_RESET)
        after = fd.restore("acme", "abc123", "k", fd.get("acme", "abc123", "k", fake), fake)
        self.assertEqual((after["minReplicaCount"], after["maxReplicaCount"]), (0, 1))
        self.assertEqual(after["autoscalingPolicy"]["scaleToZeroWindow"], "900s")
        self.assertEqual(after["autoscalingPolicy"]["scaleUpWindow"], "30s")  # untouched
        self.assertEqual(after["baseModel"], HEALTHY["baseModel"])
        patch = [c for c in fake.calls if c[0] == "PATCH"]
        self.assertEqual(len(patch), 1)
        self.assertEqual(patch[0][1], "/v1/accounts/acme/deployments/abc123")
        self.assertIn("updateMask=min_replica_count,max_replica_count,autoscaling_policy.scale_to_zero_window",
                      patch[0][2])

    def test_falls_back_to_the_camel_case_mask(self):
        fake = FakeFireworks(SUSPENDED_RESET, refuse={",".join(fd.MASK_PATHS[0])})
        after = fd.restore("acme", "abc123", "k", fd.get("acme", "abc123", "k", fake), fake)
        self.assertEqual(after["maxReplicaCount"], 1)

    def test_a_refused_update_says_what_to_do_by_hand(self):
        fake = FakeFireworks(SUSPENDED_RESET, refuse={",".join(m) for m in fd.MASK_PATHS})
        with self.assertRaisesRegex(fd.DeploymentError, "Max Replicas 1"):
            fd.restore("acme", "abc123", "k", fd.get("acme", "abc123", "k", fake), fake)

    def test_a_suspended_account_is_named_as_such(self):
        with self.assertRaisesRegex(fd.DeploymentError, "suspended.*add credits"):
            fd.get("acme", "abc123", "k", FakeFireworks(HEALTHY, status=412))

    def test_cli_checks_restores_and_skips_what_is_not_a_deployment(self):
        env = {"EXPECTRAIL_GLIMMER_API_KEY": "k", "EXPECTRAIL_GLIMMER_MODEL": MODEL}
        with mock.patch.dict(os.environ, env):
            fake = FakeFireworks(SUSPENDED_RESET)
            with mock.patch("urllib.request.urlopen", fake), redirect_stdout(io.StringIO()) as out:
                self.assertEqual(fd.main([]), 1)  # check only: reports, changes nothing
            self.assertIn("--restore", out.getvalue())
            self.assertFalse([c for c in fake.calls if c[0] == "PATCH"])
            with mock.patch("urllib.request.urlopen", fake), redirect_stdout(io.StringIO()) as out:
                self.assertEqual(fd.main(["--restore"]), 0)
            self.assertIn("Glimmer deployment restored", out.getvalue())
            with mock.patch("urllib.request.urlopen", fake), redirect_stdout(io.StringIO()) as out:
                self.assertEqual(fd.main(["--restore"]), 0)  # healthy now: nothing to do
            self.assertEqual(len([c for c in fake.calls if c[0] == "PATCH"]), 1)
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(fd.main(["--model", "accounts/fireworks/models/muse-glimmer-30b"]), 0)
            self.assertIn("nothing to check", out.getvalue())


if __name__ == "__main__":
    unittest.main()
