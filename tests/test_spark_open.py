"""agents.spark_open: drafts compared with the approved specs, the playtest sorted, results round-trip."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents import feedback, spark_open
from tests.test_sam import LEVEL, ground_trace

FIXTURE = json.loads((spark_open.REPO / "agents" / "fixtures" / "feedback" / "spark-fixture.json").read_text())


def approved(spec_id: str) -> dict:
    return next(s for s in spark_open.approved_specs() if s["id"] == spec_id)


def fake_endpoint(renamed: bool = False, fail_specs: bool = False):
    """An OpenAI-compatible endpoint: the approved spec back for each instruction, canned sorting otherwise."""
    drafts = {s["instruction"]: {k: v for k, v in s.items() if k != "approval"} for s in spark_open.approved_specs()}
    if renamed:
        g = drafts["The player never falls through the ground."]
        g["objects"] = {"robot": {"prompt": "robot"}, "ground": {"prompt": "ground"}}
        g["assertion"] = dict(g["assertion"], object="robot")
    canned = feedback.fixture_transport(dict(FIXTURE, drafts=dict(FIXTURE["drafts"], **drafts)))

    def transport(body: dict) -> dict:
        if fail_specs and body["messages"][0]["content"] != feedback.CLASSIFIER_SYSTEM:
            raise spark_open.spec_writer.SpecDraftError("HTTP 404: model not found")
        return dict(canned(body), model="served-model", usage={"prompt_tokens": 100, "completion_tokens": 20})
    return transport


class ShapeTest(unittest.TestCase):
    def test_an_approved_spec_matches_itself(self):
        spec = approved("player-stays-above-ground")
        self.assertTrue(all(spark_open.compare(spec, spec).values()))
        self.assertEqual(spark_open.shape(spec)["tolerancePx"], 20)
        self.assertEqual(spark_open.shape(spec)["window"], "0-119")

    def test_a_draft_with_other_names_is_judged_as_drafted(self):
        spec = approved("player-stays-above-ground")
        self.assertEqual(spark_open.judge(spec, ground_trace(), LEVEL), "pass")
        renamed = json.loads(json.dumps(spec))
        renamed["objects"] = {"robot": {"prompt": "robot"}, "ground": {"prompt": "ground"}}
        renamed["assertion"]["object"] = "robot"
        self.assertFalse(spark_open.compare(renamed, spec)["sameObjectNames"])
        self.assertNotEqual(spark_open.judge(renamed, ground_trace(), LEVEL), "pass")


class RunTest(unittest.TestCase):
    def run_with(self, endpoint, meta: bool = False) -> dict:
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(spark_open, "list_models", return_value=["meta-models/muse-spark-open", "x"]), \
                mock.patch.object(spark_open.spec_writer, "open_transport", return_value=endpoint), \
                mock.patch.object(spark_open.feedback, "openai_transport", return_value=endpoint), \
                mock.patch.dict("os.environ", {"EXPECTRAIL_OPEN_MODEL": "meta-models/muse-spark-open"}):
            doc = spark_open.run(None, Path(tmp), meta=meta, key="test")
            self.assertTrue((Path(tmp) / "results.json").exists())
        return doc

    def test_drafts_sorting_and_calls_are_recorded(self):
        doc = self.run_with(fake_endpoint())
        self.assertEqual(doc["models"], {"listed": 2, "muse": ["meta-models/muse-spark-open"],
                                         "modelListed": True})
        self.assertEqual([r["valid"] for r in doc["specs"]], [True, True, True])
        self.assertTrue(all(all(r["compare"].values()) for r in doc["specs"]))
        fb = doc["feedback"]
        self.assertEqual(fb["classifier"]["provenance"], "model")
        self.assertEqual(fb["classifier"]["endpoint"], "inference.baseten.co")
        weaken = [i for i in fb["items"] if i["category"] == "weaken-check"]
        self.assertEqual([i["route"] for i in weaken], ["human-queue", "human-queue"])
        self.assertTrue(any(i["draft"] for i in fb["items"]))
        self.assertTrue(all(c["served"] == "served-model" and c["promptTokens"] == 100 for c in doc["calls"]))
        self.assertEqual(len(doc["calls"]), 3 + 1 + 2)  # three specs, one sort, two drafted bug reports

    def test_a_failing_endpoint_is_recorded_not_hidden(self):
        doc = self.run_with(fake_endpoint(fail_specs=True))
        self.assertEqual([r["valid"] for r in doc["specs"]], [False, False, False])
        self.assertIn("HTTP 404", doc["specs"][0]["problems"][0])
        self.assertTrue(any("error" in c for c in doc["calls"]))

    def test_without_the_meta_key_there_is_no_comparison(self):
        with mock.patch.dict("os.environ", {"MODEL_API_KEY": ""}):
            doc = self.run_with(fake_endpoint(), meta=True)
        self.assertEqual({r["by"] for r in doc["specs"]}, {"spark-open"})


class PublishTest(unittest.TestCase):
    def test_results_round_trip_through_the_annotations(self):
        doc = RunTest().run_with(fake_endpoint(renamed=True))
        lines: list[str] = []
        spark_open.publish(doc, write=lines.append)
        self.assertLessEqual(len(lines), 10)  # GitHub keeps 10 notices a step
        notes = []
        for line in lines:
            head, _, message = line.partition("::")[2].partition("::")
            notes.append({"title": head.split("title=", 1)[1].replace("%3A", ":").replace("%2C", ","),
                          "message": message})
        self.assertIn("names {'robot': 'robot', 'ground': 'ground'}", notes[1]["message"])

        def fetch(path):
            if path.endswith("/jobs?per_page=100"):
                return {"jobs": [{"name": "spark-open", "id": 1}]}
            if "/check-runs/" in path:
                return notes
            return {"html_url": "https://github.com/x/y/actions/runs/7", "head_sha": "abc1234def"}

        back = spark_open.collect(7, fetch=fetch)
        self.assertEqual(back["run"], 7)
        self.assertEqual(back["specs"], doc["specs"])
        text = spark_open.markdown(back)
        self.assertIn("| player-stays-above-ground | spark-open | yes | yes | no |", text)
        self.assertIn("## The scripted playtest, sorted", text)


if __name__ == "__main__":
    unittest.main()
