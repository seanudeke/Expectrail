"""Names from before the Nightshift -> Expectrail rename (October 30, 2026) are still accepted on input."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents.bench_collect import collect_matrix
from agents.isolation import FIXER_FORBIDDEN_BASENAMES, forbidden_paths_under
from agents.keys import load_dotenv
from expectrail.contracts import ContractError, kind_of, load, validate
from expectrail.legacy import adopt_legacy_env, current_name, format_ids

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "contracts" / "examples"


class LegacyFormatIds(unittest.TestCase):
    def test_every_example_validates_under_both_ids(self):
        for path in sorted(EXAMPLES.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            kind = kind_of(doc)
            new, old = format_ids(kind)
            self.assertEqual(doc["format"], new, path.name)  # we write the new ID
            legacy = dict(doc, format=old)
            self.assertEqual(kind_of(legacy), kind, path.name)
            self.assertEqual(validate(legacy), kind, path.name)

    def test_load_accepts_a_legacy_file(self):
        doc = json.loads((EXAMPLES / "route.json").read_text(encoding="utf-8"))
        doc["format"] = "nightshift.route/v0"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "route.json"
            path.write_text(json.dumps(doc), encoding="utf-8")
            self.assertEqual(load(path, "route")["format"], "nightshift.route/v0")

    def test_other_prefixes_and_versions_are_still_rejected(self):
        for fmt in ("niteshift.route/v0", "nightshift.route/v1", "expectrail.route/v1", "route/v0", "pixelproof.route/v0"):
            with self.assertRaises(ContractError):
                kind_of({"format": fmt})

    def test_the_recorded_spark_draft_still_reads(self):
        # bench/spec-writer-live/spec-live.json is Muse Spark's draft from before the rename, unedited.
        doc = load(REPO / "bench" / "spec-writer-live" / "spec-live.json", "test-spec")
        self.assertEqual(doc["format"], "nightshift.test-spec/v0")
        self.assertEqual(validate(doc), "test-spec")

    def test_the_harness_replays_routes_in_either_format(self):
        gd = (REPO / "harness" / "godot" / "expectrail_harness.gd").read_text(encoding="utf-8")
        self.assertIn('const ROUTE_FORMATS := ["expectrail.route/v0", "nightshift.route/v0"]', gd)


class LegacyEnvironment(unittest.TestCase):
    def test_legacy_variable_is_adopted_under_the_new_name(self):
        env = {"NIGHTSHIFT_SAM_CACHE": "off", "UNRELATED": "1"}
        self.assertEqual(adopt_legacy_env(env, quiet=True), ["EXPECTRAIL_SAM_CACHE"])
        self.assertEqual(env["EXPECTRAIL_SAM_CACHE"], "off")

    def test_new_name_wins(self):
        env = {"NIGHTSHIFT_HELDOUT_DIR": "/old", "EXPECTRAIL_HELDOUT_DIR": "/new"}
        self.assertEqual(adopt_legacy_env(env, quiet=True), [])
        self.assertEqual(env["EXPECTRAIL_HELDOUT_DIR"], "/new")

    def test_dotenv_legacy_key_is_read_as_the_new_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("NIGHTSHIFT_SPEC_MODEL=muse-spark-1.3\nNIGHTSHIFT_NOT_A_DOTENV_KEY=x\n",
                            encoding="utf-8")
            with mock.patch.dict("os.environ", {}, clear=True):
                adopted = load_dotenv(path)
        self.assertEqual(adopted, {"EXPECTRAIL_SPEC_MODEL": "muse-spark-1.3"})


class LegacySigningKey(unittest.TestCase):
    def test_old_key_name_never_mounts_into_the_fixer(self):
        self.assertIn(".nightshift-signing-key", FIXER_FORBIDDEN_BASENAMES)
        self.assertIn(".expectrail-signing-key", FIXER_FORBIDDEN_BASENAMES)
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "player" / ".nightshift-signing-key"
            stale.parent.mkdir()
            stale.write_text("stale", encoding="utf-8")
            self.assertEqual(forbidden_paths_under(Path(tmp)), [stale])


class LegacyFixMatrixCondition(unittest.TestCase):
    def test_runs_from_before_the_rename_collect_under_the_new_condition(self):
        self.assertEqual(current_name("nightshift"), "expectrail")
        self.assertEqual(current_name("screenshots"), "screenshots")
        message = "detected fail; outcome fixed; attempts 1 (1: accept); 600 s; live=True"

        def fetch(path):
            if path.endswith("/jobs?per_page=100"):
                return {"jobs": [{"name": "run (dev/sinking/v1, nightshift)", "id": 1}]}
            if "/check-runs/" in path:
                return [{"title": "Fix matrix dev/sinking/v1 nightshift", "message": message}]
            return {"html_url": "https://github.com/seanudeke/Expectrail/actions/runs/7", "head_sha": "abc"}

        doc = collect_matrix([7], "dev", fetch=fetch)
        conditions = {r["condition"] for r in doc["rows"]}
        self.assertEqual(conditions, {"expectrail"})


if __name__ == "__main__":
    unittest.main()
