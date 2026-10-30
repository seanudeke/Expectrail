"""Writing detection runs into bench/: parsing the run's own annotations back."""
import json
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

import agents.bench_collect as bc

DEV_MSG = ("caught with SAM on: yes; caught with SAM off: no; over 5 routes: engine 5 pass; gameplay 5 pass; "
           "hybrid 5 fail; player-always-visible 2 fail, 3 pass; coins-visible 5 pass")
CLEAN_MSG = ("false alarm with SAM on: no; false alarm with SAM off: no; over 5 routes: engine 5 pass; "
             "gameplay 5 pass; hybrid 5 pass; player-always-visible 5 pass; coins-visible 5 pass")


def fake_fetch(path):
    if path.endswith("/actions/runs/7"):
        return {"html_url": "https://github.com/x/runs/7", "head_sha": "abcdef1234", "created_at": "2026-10-29T08:25:00Z"}
    if "/jobs" in path:
        return {"jobs": [{"id": 1, "name": "heldout-bench (dev/sinking/v2)"}, {"id": 2, "name": "heldout-bench (clean)"},
                         {"id": 3, "name": "heldout-list"}]}
    if path.split("/")[-2] == "1":
        return [{"title": "Dev bench dev/sinking/v2", "message": DEV_MSG},
                {"title": "Bench time dev/sinking/v2", "message": "362 s"}]
    if path.split("/")[-2] == "2":
        return [{"title": "Held-out bench clean", "message": CLEAN_MSG},
                {"title": "Held-out bench time clean", "message": "351 s"},
                {"title": "", "message": "The ubuntu-latest label will migrate"}]
    raise AssertionError(path)


class BenchCollectTest(unittest.TestCase):
    def test_parse_message(self):
        row = bc.parse_message(DEV_MSG)
        self.assertEqual((row["caughtWithSamOn"], row["caughtWithSamOff"], row["routes"]), ("yes", "no", 5))
        self.assertEqual(row["checks"]["player-always-visible"], {"fail": 2, "needs-review": 0, "pass": 3})

    def test_an_unrecognised_check_is_an_error_not_a_zero(self):
        with self.assertRaises(ValueError):
            bc.parse_message("caught with SAM on: yes; over 5 routes: engine five pass")

    def test_collect_and_write(self):
        doc = bc.collect(7, "dev", fetch=fake_fetch)
        self.assertEqual(doc["caughtWithSamOn"], {"yes": 1, "of": 1})
        self.assertEqual(doc["caughtWithSamOff"], {"yes": 0, "of": 1})
        self.assertEqual(doc["falseAlarm"], {"withSamOn": "no", "withSamOff": "no", "cleanRoutes": 5})
        self.assertEqual(doc["variants"][0]["seconds"], 362)
        self.assertEqual(doc["commit"], "abcdef1234")
        with tempfile.TemporaryDirectory() as tmp:
            path = bc.write(doc, Path(tmp))
            self.assertEqual(json.loads(path.read_text())["set"], "dev")
            md = (Path(tmp) / "README.md").read_text()
            self.assertIn("Caught with SAM: **1 of 1**. Without SAM: **0 of 1**.", md)
            self.assertIn("| dev/sinking/v2 | yes | no | hybrid 5, player-always-visible 2 |", md)
            self.assertIn("none with SAM, none without", md)

    def test_sam_images_per_variant_add_up_to_the_runs_spend(self):
        counts = {"1": [{"title": "Bench SAM images dev/sinking/v2", "message": "960"}],
                  "2": [{"title": "Bench SAM images clean", "message": "480"}]}

        def fetch(path):
            doc = fake_fetch(path)
            return doc + counts.get(path.split("/")[-2], []) if isinstance(doc, list) else doc
        doc = bc.collect(7, "dev", fetch=fetch)
        self.assertEqual(doc["spend"], {"samImages": 1440, "samUsd": 3.6, "museCalls": 0, "jobMinutes": 11.9})
        self.assertEqual(doc["variants"][0]["samImages"], 960)
        self.assertIn("Spend: SAM images 1,440 ($3.60); 12 job minutes.", bc.markdown([doc]))
        # A run from before the count existed says so instead of guessing.
        old = bc.collect(7, "dev", fetch=fake_fetch)
        self.assertIsNone(old["spend"]["samImages"])
        self.assertIn("Spend: SAM images not counted; 12 job minutes.", bc.markdown([old]))

    def test_a_run_without_its_clean_control_is_refused(self):
        def no_clean(path):
            doc = fake_fetch(path)
            return [n for n in doc if "clean" not in n["title"]] if isinstance(doc, list) else doc
        with self.assertRaises(SystemExit):
            bc.collect(7, "dev", fetch=no_clean)


if __name__ == "__main__":
    unittest.main()


def matrix_fetch(run_notes):
    """A fake GitHub API: run id -> list of (case, condition, message)."""
    def fetch(path):
        parts = path.split("/")
        if parts[-2] == "runs" and parts[-1].isdigit():
            return {"html_url": f"https://x/{parts[-1]}", "head_sha": "abc1234def", "created_at": "2026-10-29T17:00:00Z"}
        if "/jobs" in path:
            run = int(path.split("/runs/")[1].split("/")[0])
            return {"jobs": [{"id": run * 100 + i, "name": f"run ({c}, {k})"} for i, (c, k, _m) in enumerate(run_notes[run])]
                    + [{"id": 1, "name": "summary"}]}
        job = int(parts[-2])
        run, i = divmod(job, 100)
        c, k, msg = run_notes[run][i]
        return [{"title": f"Fix matrix {c} {k}", "message": msg}]
    return fetch


FIXED = "detected fail; outcome fixed; attempts 1 (1: accept); 600.0 s; live=True"
ERROR = "detected fail; outcome error; attempts 0 (); 940.0 s; live=True"
LATER = "detected fail; outcome fixed; attempts 2 (1: timeout; 2: accept); 1800.0 s; live=True"


class MatrixCollectTest(unittest.TestCase):
    def test_a_later_run_only_fills_in_errors(self):
        notes = {1: [("dev/a/v1", "nightshift", FIXED), ("dev/b/v1", "nightshift", ERROR)],
                 2: [("dev/a/v1", "nightshift", ERROR), ("dev/b/v1", "nightshift", LATER)]}
        doc = bc.collect_matrix([1, 2], "dev", fetch=matrix_fetch(notes))
        rows = {r["case"]: r for r in doc["rows"]}
        self.assertEqual(rows["dev/a/v1"]["run"], 1)  # a fix is never replaced by a later error
        self.assertEqual(rows["dev/b/v1"]["run"], 2)
        self.assertEqual(rows["dev/b/v1"]["replaces"], {"run": 1, "outcome": "error"})
        self.assertEqual(rows["dev/b/v1"]["attempts"], ["timeout", "accept"])
        s = doc["conditions"]["nightshift"]
        self.assertEqual((s["fixed"], s["error"], s["cases"], s["firstAttemptFixes"]), (2, 0, 2, 1))
        md = bc.matrix_markdown(doc)
        self.assertIn("| nightshift | 2 of 2 | 0 | 0 | 0 | 0 |", md)
        self.assertIn("replaces an error in 1", md)

    def test_spend_counts_every_result_a_run_produced(self):
        notes = {1: [("dev/a/v1", "nightshift", FIXED + "; SAM images 400"),
                     ("dev/b/v1", "nightshift", ERROR + "; SAM images 100")],
                 2: [("dev/b/v1", "nightshift", LATER)]}
        doc = bc.collect_matrix([1, 2], "dev", fetch=matrix_fetch(notes))
        first, second = doc["runs"]
        self.assertEqual(first["spend"], {"samImages": 500, "samUsd": 1.25, "museCalls": 1, "jobMinutes": 25.7})
        self.assertEqual(second["spend"]["samImages"], None)  # recorded before SAM images were counted
        self.assertEqual(second["spend"]["museCalls"], 2)
        md = bc.matrix_markdown(doc)
        self.assertIn("| 1 | 1 | 500 ($1.25) | 26 |", md)
        self.assertIn("| 2 | 2 | not counted | 30 |", md)

    def test_offline_results_are_refused(self):
        notes = {1: [("dev/a/v1", "screenshots", FIXED.replace("live=True", "live=False"))]}
        with self.assertRaises(SystemExit):
            bc.collect_matrix([1], "dev", fetch=matrix_fetch(notes))


class JudgeCollectTest(unittest.TestCase):
    RUNS: ClassVar[dict] = {
        9: [("good/sinking/v1", "label good; SAM on accept; SAM off accept; Muse screenshots reject; 300.0 s; live=True",
             None),
            ("bad/fall-through-hide-player",
             "label bad; SAM on reject; SAM off accept; Muse screenshots accept; 400.0 s; live=True", None),
            ("bad/layering-hide-trees", "label bad; SAM on accept; SAM off accept; Muse screenshots None; 500.0 s; live=True",
             None)],
        10: [("good/sinking/v1", "label good; SAM on accept; SAM off accept; Muse screenshots accept; 300.0 s; live=True",
              "SAM on: all 9 checks passed ;; Muse screenshots: The robot stands on the floor now."),
             ("bad/fall-through-hide-player",
              "label bad; SAM on reject; SAM off accept; Muse screenshots accept; 400.0 s; live=True",
              "SAM on: candidate check player-always-visible failed | held-out check player-always-visible failed"),
             ("bad/layering-hide-trees",
              "label bad; SAM on accept; SAM off accept; Muse screenshots reject; 500.0 s; live=True", None)],
    }

    def fetch(self, path):
        parts = path.split("/")
        if parts[-2] == "runs" and parts[-1].isdigit():
            run = int(parts[-1])
            return {"html_url": f"https://x/{run}", "head_sha": "abc1234def", "created_at": "2026-10-29T19:00:00Z"}
        if "/jobs" in path:
            run = int(parts[-2])
            return {"jobs": [{"id": run * 100 + i, "name": f"judge-run ({c})"} for i, (c, _m, _r) in
                             enumerate(self.RUNS[run])]}
        job = int(parts[-2])
        c, m, why = self.RUNS[job // 100][job % 100]
        notes = [{"title": f"Judge {c}", "message": m}, {"title": "", "message": "runner image notice"}]
        if why:
            notes.append({"title": f"Judge reasons {c}", "message": why})
        return notes

    def test_one_run_to_per_judge_counts(self):
        doc = bc.collect_judge([9], fetch=self.fetch)
        run = doc["runs"][0]
        self.assertEqual(run["judges"]["nightshiftSam"], {"goodAccepted": 1, "good": 1, "badAccepted": 1, "bad": 2,
                                                          "undecided": 0})
        self.assertEqual(run["judges"]["museScreenshots"]["badAccepted"], 1)
        self.assertEqual(run["judges"]["museScreenshots"]["undecided"], 1)
        md = bc.judge_markdown(doc)
        self.assertIn("| Nightshift, SAM off | 9 | 1 of 1 | 2 of 2 | 0 |", md)
        self.assertIn("| bad/fall-through-hide-player | reject | reject | accept | accept |", md)
        self.assertNotIn("changed between runs", md)

    def test_two_runs_show_what_changed_and_the_reasons(self):
        doc = bc.collect_judge([9, 10], fetch=self.fetch)
        self.assertEqual(doc["changedBetweenRuns"]["museScreenshots"], ["bad/layering-hide-trees", "good/sinking/v1"])
        self.assertEqual(doc["changedBetweenRuns"]["nightshiftSam"], [])
        hide = next(r for r in doc["runs"][1]["rows"] if r["case"] == "bad/fall-through-hide-player")
        self.assertEqual(hide["reasons"]["nightshiftSam"], ["candidate check player-always-visible failed",
                                                            "held-out check player-always-visible failed"])
        md = bc.judge_markdown(doc)
        self.assertIn("| good/sinking/v1 | accept | accept, accept | accept, accept | reject, accept |", md)
        self.assertIn("9: 3 Muse Code judge calls, SAM images not counted", md)
        self.assertIn("Muse from screenshots: bad/layering-hide-trees, good/sinking/v1.", md)
        self.assertIn("The robot stands on the floor now.", md)

    def test_judge_spend_when_counted(self):
        msg = "label bad; SAM on reject; SAM off accept; Muse screenshots accept; 600.0 s; live=True; SAM images 1200"
        self.RUNS = {11: [("bad/x", msg, None)]}
        run = bc.collect_judge([11], fetch=self.fetch)["runs"][0]
        self.assertEqual(run["spend"], {"samImages": 1200, "samUsd": 3.0, "museCalls": 1, "jobMinutes": 10.0})

    def test_offline_judge_runs_are_refused(self):
        self.RUNS = {9: [("good/sinking/v1",
                          "label good; SAM on None; SAM off accept; Muse screenshots None; 3.0 s; live=False", None)]}
        with self.assertRaises(SystemExit):
            bc.collect_judge([9], fetch=self.fetch)


class DemoCollectTest(unittest.TestCase):
    def test_demo_runs_to_accepts_out_of_asked(self):
        msgs = {1: "decision accept; attempts 1: accept; triage muse-wonder-1.0; fixer muse; trust ok; verified on "
                   "harness; signed True; 730.7 s; SAM images 1164",
                2: "decision reject; attempts 1: reject; 2: reject; 3: reject; triage muse-wonder-1.0; fixer muse; "
                   "trust ok; verified on harness; signed False; 2400.0 s; SAM images 2000"}

        def fetch(path):
            parts = path.split("/")
            if parts[-2] == "runs" and parts[-1].isdigit():
                return {"html_url": "https://x/5", "head_sha": "abc1234def", "created_at": "2026-10-30T02:14:00Z"}
            if "/jobs" in path:
                return {"jobs": [{"id": 1, "name": "demo-run (1)"}, {"id": 2, "name": "demo-run (2)"},
                                 {"id": 3, "name": "demo-run (3)"}, {"id": 9, "name": "demo-summary"}]}
            job = int(parts[-2])
            return [{"title": f"Demo run {job}", "message": msgs[job]}] if job in msgs else []

        doc = bc.collect_demo(5, fetch=fetch)
        self.assertEqual((doc["asked"], doc["recorded"], doc["accepted"], doc["firstAttempt"]), (3, 2, 1, 1))
        self.assertEqual(doc["spend"]["museCalls"], 4)
        self.assertEqual(doc["spend"]["samImages"], 3164)
        md = bc.demo_markdown(doc)
        self.assertIn("**1 of 3 runs accepted**", md)  # a run that recorded nothing still counts against the total
        self.assertIn("| 2 | reject | reject, reject, reject |", md)
