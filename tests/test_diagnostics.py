"""expectrail.diagnostics: a crash, a provider error and a real failure are never confused."""
from __future__ import annotations

import json
import subprocess
import unittest
import urllib.error

from agents.sam_observations import SamError
from expectrail.contracts import schema
from expectrail.diagnostics import CODES, behavior_failed, classify, make


class ClassifyTest(unittest.TestCase):
    def test_by_type(self):
        cases = [
            (TimeoutError("slow"), "EXECUTION_TIMEOUT"),
            (subprocess.TimeoutExpired(["godot"], 30), "EXECUTION_TIMEOUT"),
            (SamError("sam-3.1 reply has no output"), "PROVIDER_FAILED"),
            (urllib.error.HTTPError("https://api.example", 429, "Too Many Requests", {}, None), "PROVIDER_FAILED"),
            (FileNotFoundError("godot"), "TOOL_MISSING"),
        ]
        for exc, code in cases:
            with self.subTest(exc=type(exc).__name__):
                self.assertEqual(classify(exc, stage="base")["code"], code)

    def test_a_provider_status_is_kept(self):
        exc = urllib.error.HTTPError("https://api.example", 429, "Too Many Requests", {}, None)
        doc = classify(exc, stage="candidate")
        self.assertEqual((doc["providerStatus"], doc["exceptionType"]), (429, "HTTPError"))

    def test_the_type_decides_before_the_message(self):
        # The message mentions a base tree, but the type says timeout.
        self.assertEqual(classify(TimeoutError("base tree replay"), stage="base")["code"], "EXECUTION_TIMEOUT")

    def test_messages_are_a_fallback(self):
        cases = [
            ("base.tree does not match game/platformer", "BASE_MISMATCH"),
            ("held-out set unusable: manifest lists no held-out routes", "PRIVATE_SUITE_UNAVAILABLE"),
            ("sam observations unavailable: no frames", "PROVIDER_FAILED"),
            ("no clean-level reference for the ground line", "OBSERVATION_INVALID"),
        ]
        for message, code in cases:
            with self.subTest(message=message):
                self.assertEqual(classify(SystemExit(message), stage="base")["code"], code)

    def test_a_crash_is_never_a_behavioral_failure(self):
        crashes = [RuntimeError("player failed"), subprocess.CalledProcessError(134, ["godot"], stderr="abort"),
                   SystemExit("gameplay failed"), ValueError("fail"), KeyError("result"), OSError("disk")]
        for exc in crashes:
            with self.subTest(exc=repr(exc)):
                self.assertNotEqual(classify(exc, stage="candidate")["code"], "BEHAVIOR_FAILED")

    def test_only_a_completed_failed_check_is_a_behavioral_failure(self):
        doc = behavior_failed({"spec": "player-stays-above-ground", "route": "smoke", "result": "fail"})
        self.assertEqual(doc["code"], "BEHAVIOR_FAILED")
        for result in ("pass", "needs-review", None):
            with self.assertRaises(ValueError):
                behavior_failed({"spec": "s", "route": "smoke", "result": result})

    def test_keys_are_redacted(self):
        doc = classify(RuntimeError("request failed with msk-" + "Q" * 40), stage="candidate")
        self.assertNotIn("Q" * 20, doc["detail"])
        self.assertIn("[redacted]", doc["detail"])

    def test_every_code_has_a_fix_and_matches_the_record_schema(self):
        codes = schema("change-evidence")["properties"]["diagnostics"]["items"]["properties"]["code"]["enum"]
        self.assertEqual(sorted(codes), sorted(CODES))
        allowed = set(schema("change-evidence")["properties"]["diagnostics"]["items"]["properties"])
        for code in CODES:
            doc = make(code, stage="base", detail="x", exception_type="E", provider_status=500)
            self.assertTrue(doc["fix"])
            self.assertLessEqual(set(doc), allowed, json.dumps(doc))
        with self.assertRaises(ValueError):
            make("SOMETHING_ELSE", stage="base")


if __name__ == "__main__":
    unittest.main()
