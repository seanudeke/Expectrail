"""Per-case spend: SAM, Muse gateway requests, Glimmer calls, job minutes."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agents.case_spend as cs
import agents.glimmer_usage as gu


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


class GlimmerUsageTest(unittest.TestCase):
    def setUp(self):
        gu.reset_for_tests()
        gu.install()

    def test_wrap_counts_each_call_attempt(self):
        from agents.glimmer_client import GlimmerClient

        client = GlimmerClient(transport=lambda body: (b"{}", "application/json"),
                               key="test-key-not-meta", retries=0)
        before = gu.glimmer_usage()
        client._call({"model": "x"})
        self.assertEqual(gu.glimmer_calls_since(before), 1)
        client._call({"model": "x"})
        self.assertEqual(gu.glimmer_calls_since(before), 2)


class CaseSpendTest(unittest.TestCase):
    def setUp(self):
        gu.reset_for_tests()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_enrich_reads_sam_minutes_and_gateway_requests(self):
        case = self.root / "dev_sinking_v2" / "expectrail"
        _write(case / "result.json", {
            "format": "expectrail.fix-matrix/v0",
            "case": "dev/sinking/v2",
            "condition": "expectrail",
            "wallClockSeconds": 120,
            "samImages": 480,
        })
        _write(case / "attempt-01" / "sandbox.json", {
            "kind": "bwrap",
            "gateway": {"mode": "on", "requests": 3, "hosts": ["api.meta.ai"],
                        "blockedHosts": [], "swappedHeaders": ["Authorization"]},
        })
        spend = cs.enrich(case, glimmer_before={"calls": 0})
        self.assertEqual(spend["samImages"], 480)
        self.assertEqual(spend["samUsd"], 1.2)
        self.assertEqual(spend["museRequests"], 3)
        self.assertEqual(spend["jobMinutes"], 2.0)
        self.assertEqual(spend["glimmerCalls"], 0)
        self.assertTrue((case / "spend.json").is_file())
        self.assertIn("SAM images 480 ($1.20)", cs.notice(spend))
        self.assertIn("Muse requests 3", cs.notice(spend))

    def test_missing_sam_and_no_gateway_docs_say_not_counted(self):
        case = self.root / "old"
        _write(case / "result.json", {
            "case": "dev/layering/v1",
            "condition": "screenshots",
            "wallClockSeconds": 60,
        })
        # No glimmer wrap in this enrich path: pass glimmer_before=None without install → null
        with mock.patch.object(gu, "_installed", False):
            spend = cs.enrich(case, glimmer_before=None)
        self.assertIsNone(spend["samImages"])
        self.assertIsNone(spend["museRequests"])
        self.assertIsNone(spend["glimmerCalls"])
        self.assertEqual(spend["jobMinutes"], 1.0)
        self.assertIn("SAM images not counted", cs.notice(spend))
        self.assertIn("Muse requests not counted", cs.notice(spend))
        self.assertIn("Glimmer calls not counted", cs.notice(spend))

    def test_gateway_docs_with_mode_off_count_zero_muse_requests(self):
        case = self.root / "offline"
        _write(case / "result.json", {"case": "good/sinking/v1", "label": "good",
                                      "wallClockSeconds": 30, "samImages": 0})
        _write(case / "muse-judge" / "judge.json", {"gateway": {"mode": "off"}})
        spend = cs.enrich(case, glimmer_before={"calls": 0})
        self.assertEqual(spend["museRequests"], 0)
        self.assertEqual(spend["samImages"], 0)

    def test_aggregate_refuses_to_sum_when_any_sam_is_missing(self):
        rows = [
            {"case": "a", "samImages": 10, "museRequests": 1, "glimmerCalls": 0, "jobMinutes": 1.0},
            {"case": "b", "samImages": None, "museRequests": 2, "glimmerCalls": 0, "jobMinutes": 2.0},
        ]
        doc = cs.aggregate(rows)
        self.assertIsNone(doc["samImages"])
        self.assertEqual(doc["museRequests"], 3)
        self.assertEqual(doc["glimmerCalls"], 0)
        self.assertEqual(doc["jobMinutes"], 3.0)
        md = cs.markdown(doc, bench="fix")
        self.assertIn("SAM images not counted", md)
        self.assertIn("| a |", md)

    def test_write_bench_and_collect_tree(self):
        case = self.root / "runs" / "c1"
        _write(case / "result.json", {"case": "dev/sinking/v1", "condition": "expectrail",
                                      "wallClockSeconds": 90, "samImages": 100})
        _write(case / "attempt-01" / "sandbox.json",
               {"gateway": {"mode": "on", "requests": 2, "hosts": ["api.meta.ai"]}})
        out = self.root / "bench"
        gu.install()
        gu.reset_for_tests()
        doc = cs.aggregate(cs.collect_tree(self.root / "runs"))
        path = cs.write_bench(doc, out, bench="fix")
        self.assertEqual(path.name, "spend.json")
        self.assertTrue((out / "spend.md").is_file())
        saved = json.loads(path.read_text())
        self.assertEqual(saved["samImages"], 100)
        self.assertEqual(saved["museRequests"], 2)
        self.assertIn("per-case spend", (out / "spend.md").read_text())

    def test_cli_case_dir(self):
        case = self.root / "cli"
        _write(case / "result.json", {"case": "x", "wallClockSeconds": 60, "samImages": 10})
        _write(case / "sandbox.json", {"gateway": {"mode": "on", "requests": 1, "hosts": []}})
        code = cs.main(["--case-dir", str(case), "--glimmer-before", "0"])
        self.assertEqual(code, 0)
        spend = json.loads((case / "spend.json").read_text())
        self.assertEqual(spend["museRequests"], 1)
        self.assertEqual(spend["samImages"], 10)


if __name__ == "__main__":
    unittest.main()
