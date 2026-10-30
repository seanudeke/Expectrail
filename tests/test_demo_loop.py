"""The live demo-path wrapper: one loop run per process, recorded; and the tally across runs."""
import json
import tempfile
import unittest
from pathlib import Path

import agents.demo_loop as dl
import agents.sam_observations as sam


def fake_loop(decision="accept", raise_exc=None, images=0):
    seen = {}

    def loop_main(argv):
        seen["argv"] = argv
        if raise_exc:
            raise raise_exc
        with sam._usage_lock:
            sam._usage["images"] += images
        out = Path(argv[argv.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        result = {"decision": decision, "attempts": [{"decision": "reject"}, {"decision": decision}],
                  "triageSource": "muse-wonder-1.0", "fixerSource": "muse", "trust": {"ok": True},
                  "verificationProvenance": "harness", "morning": {"signature": "abc"} if decision == "accept" else None}
        (out / "summary.json").write_text(json.dumps({"results": [result]}))
        return 0 if decision == "accept" else 1
    return loop_main, seen


class DemoLoopTest(unittest.TestCase):
    def test_one_live_run_is_recorded_with_its_sam_use(self):
        loop_main, seen = fake_loop(images=1164)
        with tempfile.TemporaryDirectory() as tmp:
            row = dl.one(3, Path(tmp), loop_main=loop_main)
            saved = json.loads((Path(tmp) / "run-03" / "result.json").read_text())
        self.assertEqual(seen["argv"][2:], dl.LOOP_ARGS)  # live, the real harness, bubblewrap required
        self.assertIn("--mode", seen["argv"])
        self.assertEqual((row["decision"], row["attempts"], row["samImages"], row["signed"]),
                         ("accept", ["reject", "accept"], 1164, True))
        self.assertEqual(saved["run"], 3)
        self.assertIn("decision accept; attempts 1: reject; 2: accept; triage muse-wonder-1.0", dl.annotation(row))

    def test_a_crash_is_recorded_and_never_an_accept(self):
        loop_main, _ = fake_loop(raise_exc=RuntimeError("muse not on PATH"))
        with tempfile.TemporaryDirectory() as tmp:
            row = dl.one(1, Path(tmp), loop_main=loop_main)
        self.assertEqual(row["decision"], "error")
        self.assertIn("muse not on PATH", row["error"])
        self.assertIn("::warning title=Demo run 1 error::", dl.annotation(row))

    def test_the_tally_counts_accepts_against_the_runs_asked_for(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i, decision in ((1, "accept"), (2, "reject"), (3, "accept")):
                loop_main, _ = fake_loop(decision=decision, images=100)
                dl.one(i, Path(tmp) / f"artifact-{i}", loop_main=loop_main)
            doc, md = dl.summarize(Path(tmp), expected=4)
        self.assertEqual((doc["accepted"], doc["recorded"], doc["samImages"]), (2, 3, 300))
        self.assertIn("**2 of 4 runs accepted** (3 recorded)", md)


if __name__ == "__main__":
    unittest.main()
