"""Writing detection runs into bench/: parsing the run's own annotations back."""
import json
import tempfile
import unittest
from pathlib import Path

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

    def test_a_run_without_its_clean_control_is_refused(self):
        def no_clean(path):
            doc = fake_fetch(path)
            return [n for n in doc if "clean" not in n["title"]] if isinstance(doc, list) else doc
        with self.assertRaises(SystemExit):
            bc.collect(7, "dev", fetch=no_clean)


if __name__ == "__main__":
    unittest.main()
