"""The reported-bug bench: its manifest, its verdicts, and that its annotations read back into bench/reported/."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agents.bench_collect as bc
import agents.reported_bench as rb
from agents import trace_checks
from harness.run import REPO

GROUND = 637.0


def flying_trace(rise: float) -> dict:
    """Stands, rises `rise` px, comes back down; three settled enemies; facing follows the walk."""
    rows = []
    for t in range(80):
        y = GROUND - (rise * (1 - abs(t - 40) / 20) if 20 < t < 60 else 0)
        rows.append({"tick": t, "player": [100 + t, y], "onFloor": not 20 < t < 60, "facing": 1,
                     "enemies": [[1, 500, 300], [2, 700, 500], [3, 900, GROUND]], "projectiles": []})
    return {"physicsTicksPerSecond": 120, "rows": rows}


def fake_judge_route(route, min_dx, patches, run_dir, ground_spec, sam_spec_docs, reference, use_sam, hybrid=True):
    run_dir.mkdir(parents=True, exist_ok=True)
    climbs = bool(patches) and Path(route).stem == "climb-gap"
    (run_dir / "trace.json").write_text(json.dumps(flying_trace(480 if climbs else 120)))
    return {"engine": "pass", "gameplay": "pass"}


class ManifestTest(unittest.TestCase):
    def test_the_repository_manifest_is_complete(self):
        manifest = rb.load_manifest()
        ids = [v["id"] for v in manifest["variants"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn(rb.CLEAN, ids)
        for v in manifest["variants"]:
            self.assertTrue((rb.REPORTED / v["patch"]).is_file(), v)
            self.assertTrue(v["source"].startswith("https://"), v)
            self.assertTrue(v["report"], v)
            # harness.check_seeded replays every bugs/*/v*.patch on the smoke route and wants it to show
            # there; most reported bugs do not, so none may be named like a seeded variant.
            self.assertFalse(Path(v["patch"]).name.startswith("v"), v)
        for r in manifest["routes"]:
            route = json.loads((rb.REPORTED / r["file"]).read_text())
            self.assertEqual(route["format"], "expectrail.route/v0")
            self.assertEqual(route["name"], r["name"])
            self.assertLess(r["minDeltaX"], r["cleanDeltaX"])
        self.assertEqual(rb.variant_ids(manifest)[0], rb.CLEAN)

    def test_a_variant_on_an_unknown_route_or_check_is_refused(self):
        manifest = rb.load_manifest()
        for field, value in (("route", "nowhere"), ("check", "not-a-check")):
            broken = json.loads(json.dumps(manifest))
            broken["variants"][0][field] = value
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "manifest.json").write_text(json.dumps(broken))
                with self.assertRaises(SystemExit):
                    rb.load_manifest(Path(tmp))

    def test_routes_start_with_smoke(self):
        names = [name for name, _route, _dx in rb.routes(rb.load_manifest())]
        self.assertEqual(names[0], "smoke")
        self.assertEqual(len(names), 1 + len(rb.load_manifest()["routes"]))


class BenchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        patches = [mock.patch.object(rb, "judge_route", fake_judge_route),
                   mock.patch.object(rb, "reference_surfaces", lambda out: None),
                   mock.patch.object(rb, "sam_on", lambda: False)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_clean_game_raises_no_alarm(self):
        doc = rb.bench(rb.CLEAN, self.out)
        self.assertEqual((doc["caughtByTodaysChecks"], doc["caughtByTraceChecks"]), ("no", "no"))
        self.assertIsNone(doc["caughtByOwnCheck"])
        self.assertFalse(rb.undecided(doc))
        self.assertTrue((self.out / "clean" / "bench.json").is_file())

    def test_a_bug_its_own_check_fails_is_caught_by_it_and_not_by_todays(self):
        doc = rb.bench("air-jump", self.out)
        self.assertEqual(doc["expectedCheck"], "jump-height")
        self.assertEqual(doc["caughtByTodaysChecks"], "no")
        self.assertEqual(doc["caughtByTraceChecks"], "yes")
        self.assertEqual(doc["caughtByOwnCheck"], "yes")
        self.assertEqual(doc["checks"]["jump-height"], {"fail": 1, "needs-review": 0, "pass": 4})
        failed = [row for row in doc["perRoute"] if row["checks"]["jump-height"] == "fail"]
        self.assertEqual([row["route"] for row in failed], ["climb-gap"])
        self.assertIn("rose", failed[0]["reasons"]["jump-height"])

    def test_a_replay_without_a_trace_is_undecided_never_a_pass(self):
        def no_trace(route, min_dx, patches, run_dir, *args, **kwargs):
            run_dir.mkdir(parents=True, exist_ok=True)
            return {"engine": "needs-review", "gameplay": "needs-review"}

        with mock.patch.object(rb, "judge_route", no_trace):
            doc = rb.bench("air-jump", self.out)
        self.assertTrue(rb.undecided(doc))
        self.assertEqual(doc["caughtByTraceChecks"], "needs-review")
        for name in trace_checks.CHECKS:
            self.assertEqual(doc["checks"][name]["pass"], 0)

    def test_a_stale_trace_from_an_earlier_run_is_not_judged(self):
        stale = self.out / "air-jump" / "climb-gap"
        stale.mkdir(parents=True)
        (stale / "trace.json").write_text(json.dumps(flying_trace(480)))

        def no_trace(route, min_dx, patches, run_dir, *args, **kwargs):
            return {"engine": "pass", "gameplay": "pass"}

        with mock.patch.object(rb, "judge_route", no_trace):
            doc = rb.bench("air-jump", self.out)
        self.assertEqual(doc["checks"]["jump-height"]["fail"], 0)

    def test_an_unknown_variant_is_refused(self):
        with self.assertRaises(SystemExit):
            rb.bench("not-a-bug", self.out)

    def test_the_annotation_reads_back(self):
        bug, clean = rb.bench("air-jump", self.out), rb.bench(rb.CLEAN, self.out)
        lines = rb.annotation(bug).splitlines()
        title, _, message = lines[0].removeprefix("::notice title=").partition("::")
        self.assertEqual(title, "Reported bench air-jump")
        row = bc.parse_reported_message(message)
        self.assertEqual((row["caughtByTodaysChecks"], row["caughtByTraceChecks"]), ("no", "yes"))
        self.assertEqual((row["ownCheck"], row["caughtByOwnCheck"]), ("jump-height", "yes"))
        self.assertEqual(row["routes"], 5)
        self.assertEqual(row["checks"]["jump-height"]["fail"], 1)
        detail_title, _, detail = lines[1].removeprefix("::notice title=").partition("::")
        self.assertEqual(bc.REPORTED_DETAIL.match(detail_title)["result"], "fail")
        self.assertTrue(detail.startswith("jump-height on climb-gap: the robot rose"))
        clean_line = rb.annotation(clean).splitlines()[0]
        self.assertIn("false alarm with engine-record checks: no", clean_line)
        self.assertEqual(len(rb.annotation(clean).splitlines()), 1)


def fake_fetch(path):
    msg = {
        "clean": ("false alarm with today's checks (SAM off): no; false alarm with engine-record checks: no; over 5 "
                  "routes: engine 5 pass; gameplay 5 pass; jump-height 5 pass; fire-rate 5 pass"),
        "air-jump": ("caught with today's checks (SAM off): no; caught with engine-record checks: yes; caught by its "
                     "own check jump-height: yes; over 5 routes: engine 5 pass; gameplay 5 pass; jump-height 1 fail, "
                     "4 pass; fire-rate 5 pass"),
        "gun-cooldown": ("caught with today's checks (SAM off): no; caught with engine-record checks: yes; caught by "
                         "its own check fire-rate: yes; over 5 routes: engine 5 pass; gameplay 5 pass; jump-height 5 "
                         "pass; fire-rate 1 fail, 4 pass"),
    }
    if path.endswith("/actions/runs/9"):
        return {"html_url": "https://github.com/x/runs/9", "head_sha": "0123456789", "created_at": "2026-10-30T18:00:00Z"}
    if "/jobs" in path:
        return {"jobs": [{"id": i, "name": f"reported-bench ({v})"} for i, v in enumerate(msg, start=1)]
                + [{"id": 99, "name": "reported-list"}]}
    job = int(path.split("/")[-2])
    if job == 99:
        raise AssertionError("the list job's annotations are not read")
    vid = list(msg)[job - 1]
    notes = [{"title": f"Reported bench {vid}", "message": msg[vid]},
             {"title": f"Reported bench time {vid}", "message": "180 s"}]
    if vid == "air-jump":
        notes.append({"title": "Reported bench air-jump fail",
                      "message": "jump-height on climb-gap: the robot rose 486 px above the floor it left (max 260)"})
    return notes


class CollectTest(unittest.TestCase):
    def test_collect_and_write(self):
        doc = bc.collect_reported(9, fetch=fake_fetch)
        self.assertEqual(doc["caughtByTodaysChecks"], {"yes": 0, "of": 2})
        self.assertEqual(doc["caughtByTraceChecks"], {"yes": 2, "of": 2})
        self.assertEqual(doc["falseAlarm"]["traceChecks"], "no")
        self.assertFalse(doc["sam"])
        self.assertEqual([v["id"] for v in doc["variants"]], ["air-jump", "gun-cooldown"])
        self.assertEqual(doc["variants"][0]["details"][0]["result"], "fail")
        self.assertEqual(doc["spend"]["jobMinutes"], 9.0)
        md = bc.reported_markdown(doc)
        self.assertIn("| Engine-record checks (agents/trace_checks.py) | **2 of 2** | none |", md)
        self.assertIn("| Today's verifier, SAM off (engine ground, gameplay) | **0 of 2** | none |", md)
        self.assertIn("jump-height on climb-gap: the robot rose 486 px", md)
        self.assertIn("does not show that the checks would have found the bugs blind", md)
        real = bc.collect_reported
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(bc, "collect_reported",
                                                                     lambda run: real(run, fake_fetch)):
            self.assertEqual(bc.main(["--reported", "--run", "9", "--out", tmp]), 0)
            self.assertEqual(json.loads((Path(tmp) / "reported.json").read_text())["run"], 9)

    def test_a_run_without_its_clean_control_is_refused(self):
        def no_clean(path):
            if "/jobs" in path:
                return {"jobs": [{"id": 2, "name": "reported-bench (air-jump)"}]}
            return fake_fetch(path)

        with self.assertRaises(SystemExit):
            bc.collect_reported(9, fetch=no_clean)

    def test_an_unreadable_summary_is_an_error_not_a_zero(self):
        with self.assertRaises(ValueError):
            bc.parse_reported_message("caught with SAM off: no; over 5 routes: engine 5 pass")


class WorkflowTest(unittest.TestCase):
    def test_the_bench_job_names_match_what_the_collector_reads(self):
        yml = (REPO / ".github" / "workflows" / "reported-bench.yml").read_text()
        self.assertIn("name: reported-bench (${{ matrix.variant }})", yml)
        self.assertIn("python -m agents.reported_bench --list", yml)
        self.assertIn("Reported bench time ${VARIANT}", yml)


if __name__ == "__main__":
    unittest.main()
