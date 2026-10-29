"""The held-out detection benchmark: aggregation, verdicts, and that nothing private is printed."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import agents.heldout_bench as hb

SECRET = "the secret description of how this variant breaks the game"
MANIFEST = {
    "format": "nightshift.held-out-set/v0",
    "routes": [{"name": "private-route-one", "file": "routes/one.json", "minDeltaX": 300},
               {"name": "private-route-two", "file": "routes/two.json", "minDeltaX": 300}],
    "variants": [
        {"family": "fam", "id": "v1", "patch": "bugs/fam/v1.patch", "spec": "player-always-visible",
         "mechanism": SECRET},
        {"family": "fam", "id": "v0", "patch": "bugs/fam/v0.patch", "spec": "x", "mechanism": SECRET,
         "retired": "published"},
    ],
}


class HeldOutBenchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "set"
        (root / "routes").mkdir(parents=True)
        (root / "bugs" / "fam").mkdir(parents=True)
        for name in ("one", "two"):
            (root / "routes" / f"{name}.json").write_text("{}\n")
        (root / "bugs" / "fam" / "v1.patch").write_text("")
        (root / "manifest.json").write_text(json.dumps(MANIFEST))
        self.root = root
        self.env = mock.patch.dict(os.environ, {"NIGHTSHIFT_HELDOUT_DIR": str(root)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def run_bench(self, key, results, sam=True):
        """bench() with every route judged by a scripted ``results`` list (one dict per route)."""
        calls = []

        def fake_judge(route, min_dx, patches, run_dir, ground_spec, sam_docs, reference, use_sam, hybrid=True):
            calls.append((route, min_dx, patches, use_sam, hybrid))
            if results[len(calls) - 1].get("_error"):
                (run_dir).mkdir(parents=True, exist_ok=True)
                (run_dir / hb.ERRORS_FILE).write_text(json.dumps([results[len(calls) - 1]["_error"]]))
            return {k: v for k, v in results[len(calls) - 1].items() if k != "_error"}

        sam_docs = [{"id": "player-always-visible"}, {"id": "coins-visible"}] if sam else []
        with mock.patch.object(hb, "judge_route", fake_judge), \
                mock.patch.object(hb, "reference_surfaces", return_value=[[0, 0]]), \
                mock.patch.object(hb, "sam_on", return_value=sam), \
                mock.patch.object(hb, "sam_specs", return_value=sam_docs):
            doc = hb.bench(key, Path(self.tmp.name) / "out")
        return doc, calls

    def test_list_skips_retired_variants_and_leads_with_clean(self):
        out = io.StringIO()
        with redirect_stdout(out):
            hb.main(["--list"])
        self.assertEqual(json.loads(out.getvalue()), ["clean", "fam/v1"])

    def test_list_only_keeps_the_named_ids_and_refuses_unknown_ones(self):
        out = io.StringIO()
        with redirect_stdout(out):
            hb.main(["--list", "--only", "fam/v1"])
        self.assertEqual(json.loads(out.getvalue()), ["fam/v1"])
        with self.assertRaises(SystemExit):
            hb.main(["--list", "--only", "fam/v0"])  # retired

    def test_dev_set_lists_the_public_bugs_after_clean(self):
        out = io.StringIO()
        with redirect_stdout(out):
            hb.main(["--list", "--set", "dev"])
        ids = json.loads(out.getvalue())
        self.assertEqual(ids[0], "clean")
        self.assertEqual(ids[1:], sorted(hb.dev_variants()))
        self.assertIn("dev/physics-fall-through/v1", ids)
        self.assertTrue(all(i.startswith("dev/") for i in ids[1:]))
        self.assertNotIn("fam/v1", ids)  # private variants never appear in the dev set

    def test_a_dev_variant_runs_the_same_routes_with_its_public_patch(self):
        row = {"engine": "fail", "gameplay": "pass", "hybrid": "fail", "player-always-visible": "pass",
               "coins-visible": "pass"}
        doc, calls = self.run_bench("dev/physics-fall-through/v1", [row] * 3)
        self.assertEqual([c[0] for c in calls], [hb.SMOKE_ROUTE, self.root / "routes/one.json",
                                                 self.root / "routes/two.json"])
        self.assertTrue(all(c[2] == [hb.BUGS / "physics-fall-through" / "v1.patch"] for c in calls))
        self.assertEqual(doc["expectedSpec"], "player-stays-above-ground")
        line = hb.annotation(doc)
        self.assertTrue(line.startswith("::notice title=Dev bench dev/physics-fall-through/v1::caught with SAM on: yes"))
        self.assertTrue((Path(self.tmp.name) / "out" / "dev_physics-fall-through_v1" / "bench.json").is_file())

    def test_an_unknown_dev_variant_is_refused(self):
        with self.assertRaises(SystemExit):
            self.run_bench("dev/physics-fall-through/v9", [])

    def test_variant_runs_on_smoke_and_every_private_route_with_its_patch(self):
        row = {"engine": "pass", "gameplay": "pass", "hybrid": "pass", "player-always-visible": "pass",
               "coins-visible": "pass"}
        doc, calls = self.run_bench("fam/v1", [row] * 3)
        self.assertEqual([c[0] for c in calls], [hb.SMOKE_ROUTE, self.root / "routes/one.json",
                                                 self.root / "routes/two.json"])
        self.assertEqual(calls[0][1], hb.MIN_DELTA_X_HARNESS)
        self.assertEqual(calls[1][1], 300.0)
        self.assertTrue(all(c[2] == [self.root / "bugs/fam/v1.patch"] for c in calls))
        self.assertEqual(doc["routes"], 3)
        self.assertEqual((doc["caughtWithSamOn"], doc["caughtWithSamOff"]), ("no", "no"))

    def test_clean_control_applies_no_patch(self):
        row = {"engine": "pass", "gameplay": "pass"}
        doc, calls = self.run_bench("clean", [row] * 3, sam=False)
        self.assertTrue(all(c[2] == [] for c in calls))
        self.assertIsNone(doc["caughtWithSamOn"])
        self.assertIn("false alarm with SAM off: no", hb.annotation(doc))

    def test_a_sam_spec_failure_counts_only_with_sam_on(self):
        ok = {"engine": "pass", "gameplay": "pass", "hybrid": "pass", "player-always-visible": "pass",
              "coins-visible": "pass"}
        hidden = dict(ok, **{"player-always-visible": "fail"})
        doc, _ = self.run_bench("fam/v1", [ok, hidden, ok])
        self.assertEqual(doc["caughtWithSamOn"], "yes")
        self.assertEqual(doc["caughtWithSamOff"], "no")
        self.assertEqual(doc["checks"]["player-always-visible"], {"fail": 1, "needs-review": 0, "pass": 2})

    def test_glimmer_engine_judges_ground_on_the_engine_and_vision_on_glimmer(self):
        row = {"engine": "pass", "gameplay": "pass", "player-always-visible": "pass", "coins-visible": "pass"}
        hidden = dict(row, **{"player-always-visible": "fail"})
        with mock.patch.dict(os.environ, {"NIGHTSHIFT_VISION_BACKEND": "glimmer-engine"}):
            doc, calls = self.run_bench("fam/v1", [row, hidden, row])
            sunk, _ = self.run_bench("fam/v1", [dict(row, engine="fail")] * 3)
            secret = 'glimmer did not answer in JSON: \'{"objects": [{"box": [781, 120, 815, 165]\''
            leak, _ = self.run_bench("fam/v1", [dict(row, **{"coins-visible": "needs-review",
                                                            "_error": f"coins-visible: {secret}"})] * 3)
        self.assertFalse(any(c[4] for c in calls))  # no hybrid under glimmer-engine
        self.assertEqual(doc["judge"], "glimmer-engine")
        self.assertEqual(doc["caughtWithGlimmerEngine"], "yes")
        self.assertIsNone(doc["caughtWithSamOn"])
        self.assertFalse(doc["sam"])
        self.assertEqual(sunk["caughtWithGlimmerEngine"], "yes")  # the engine line counts here
        line = hb.annotation(doc)
        self.assertIn("caught with Glimmer+engine (no SAM): yes", line)
        self.assertNotIn("with SAM on", line)
        self.assertEqual(leak["errors"], ["coins-visible: answer not JSON"])
        self.assertNotIn("781", hb.annotation(leak))
        with mock.patch.object(hb, "bench", return_value=doc), redirect_stdout(io.StringIO()):
            self.assertEqual(hb.main(["--variant", "fam/v1"]), 0)

    def test_engine_failure_counts_only_with_sam_off(self):
        # With SAM on the verifier judges the ground spec by the hybrid, not the engine line.
        row = {"engine": "fail", "gameplay": "pass", "hybrid": "pass", "player-always-visible": "pass",
               "coins-visible": "pass"}
        doc, _ = self.run_bench("fam/v1", [row] * 3)
        self.assertEqual((doc["caughtWithSamOn"], doc["caughtWithSamOff"]), ("no", "yes"))

    def test_needs_review_is_not_a_catch(self):
        row = {"engine": "pass", "gameplay": "pass", "hybrid": "needs-review", "player-always-visible": "pass",
               "coins-visible": "pass"}
        doc, _ = self.run_bench("fam/v1", [row] * 3)
        self.assertEqual(doc["caughtWithSamOn"], "needs-review")

    def test_a_run_that_decided_nothing_fails_the_job(self):
        blind = {"engine": "pass", "gameplay": "pass", "hybrid": "needs-review",
                 "player-always-visible": "needs-review", "coins-visible": "needs-review"}
        doc, _ = self.run_bench("fam/v1", [blind] * 3)
        with mock.patch.object(hb, "bench", return_value=doc), redirect_stdout(io.StringIO()):
            self.assertEqual(hb.main(["--variant", "fam/v1"]), 1)
        doc, _ = self.run_bench("fam/v1", [{"engine": "needs-review", "gameplay": "pass"}] * 3, sam=False)
        with mock.patch.object(hb, "bench", return_value=doc), redirect_stdout(io.StringIO()):
            self.assertEqual(hb.main(["--variant", "fam/v1"]), 1)  # SAM off: the engine line decides
        seen = {"engine": "pass", "gameplay": "pass", "hybrid": "pass", "player-always-visible": "pass",
                "coins-visible": "pass"}
        doc, _ = self.run_bench("fam/v1", [seen] * 3)
        with mock.patch.object(hb, "bench", return_value=doc), redirect_stdout(io.StringIO()):
            self.assertEqual(hb.main(["--variant", "fam/v1"]), 0)  # a measured miss is a result too

    def test_annotation_carries_no_private_text(self):
        row = {"engine": "fail", "gameplay": "pass", "hybrid": "fail", "player-always-visible": "pass",
               "coins-visible": "pass"}
        doc, _ = self.run_bench("fam/v1", [row] * 3)
        line = hb.annotation(doc)
        self.assertTrue(line.startswith("::notice title=Held-out bench fam/v1::caught with SAM on: yes"))
        for private in (SECRET, "private-route-one", "private-route-two", "bugs/fam", "routes/"):
            self.assertNotIn(private, line)
        # The run's SAM spend is published as a bare count, in its own annotation.
        self.assertEqual(doc["samImages"], 0)
        self.assertEqual(line.splitlines()[-1], "::notice title=Bench SAM images fam/v1::0")
        saved = json.loads((Path(self.tmp.name) / "out" / "fam_v1" / "bench.json").read_text())
        self.assertNotIn(SECRET, json.dumps(saved))  # the description is never copied out of the set

    def test_unknown_or_retired_variant_is_refused(self):
        for key in ("fam/v9", "fam/v0"):
            with self.assertRaises(SystemExit):
                self.run_bench(key, [])

    def test_missing_set_is_refused(self):
        with mock.patch.dict(os.environ, {"NIGHTSHIFT_HELDOUT_DIR": ""}), self.assertRaises(SystemExit):
            hb.main(["--list"])


class PublicErrorTest(unittest.TestCase):
    def test_directories_are_stripped_and_the_line_is_short(self):
        msg = "HTTP 401 for /home/runner/work/x/runs/bench/fam_v1/private-route-one/frames/f0001.png\nmore"
        got = hb.public_error(msg)
        self.assertEqual(got, "HTTP 401 for f0001.png more")
        self.assertLessEqual(len(hb.public_error("x" * 500)), 200)

    def test_errors_reach_the_annotation_without_route_names(self):
        doc = {"variant": "fam/v1", "routes": 1, "sam": True, "caughtWithSamOn": "needs-review",
               "caughtWithSamOff": "no", "checks": {"hybrid": {"fail": 0, "needs-review": 1, "pass": 0}},
               "errors": ["hybrid: sam observations unavailable: HTTP 401"]}
        lines = hb.annotation(doc).splitlines()
        self.assertEqual(lines[1], "::error title=Held-out bench fam/v1 error::hybrid: sam observations unavailable: HTTP 401")


class JudgeRouteTest(unittest.TestCase):
    def test_a_render_failure_is_needs_review_for_every_check(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(hb, "harness_run", side_effect=OSError("godot died")):
            got = hb.judge_route(Path("r.json"), 300, [], Path(tmp), {"id": "g"}, [{"id": "s"}], None, True)
        self.assertEqual(got, {"engine": "needs-review", "gameplay": "needs-review", "hybrid": "needs-review",
                               "s": "needs-review"})


if __name__ == "__main__":
    unittest.main()
