"""Names from before the Nightshift -> Pixel Proof rename are still accepted on input."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents.isolation import FIXER_FORBIDDEN_BASENAMES, forbidden_paths_under
from agents.keys import load_dotenv
from pixelproof.contracts import ContractError, kind_of, load, validate
from pixelproof.legacy import adopt_legacy_env, format_ids

EXAMPLES = Path(__file__).resolve().parent.parent / "contracts" / "examples"


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
        for fmt in ("niteshift.route/v0", "nightshift.route/v1", "pixelproof.route/v1", "route/v0"):
            with self.assertRaises(ContractError):
                kind_of({"format": fmt})


class LegacyEnvironment(unittest.TestCase):
    def test_legacy_variable_is_adopted_under_the_new_name(self):
        env = {"NIGHTSHIFT_SAM_CACHE": "off", "UNRELATED": "1"}
        self.assertEqual(adopt_legacy_env(env, quiet=True), ["PIXELPROOF_SAM_CACHE"])
        self.assertEqual(env["PIXELPROOF_SAM_CACHE"], "off")

    def test_new_name_wins(self):
        env = {"NIGHTSHIFT_HELDOUT_DIR": "/old", "PIXELPROOF_HELDOUT_DIR": "/new"}
        self.assertEqual(adopt_legacy_env(env, quiet=True), [])
        self.assertEqual(env["PIXELPROOF_HELDOUT_DIR"], "/new")

    def test_dotenv_legacy_key_is_read_as_the_new_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("NIGHTSHIFT_SPEC_MODEL=muse-spark-1.3\nNIGHTSHIFT_NOT_A_DOTENV_KEY=x\n",
                            encoding="utf-8")
            with mock.patch.dict("os.environ", {}, clear=True):
                adopted = load_dotenv(path)
        self.assertEqual(adopted, {"PIXELPROOF_SPEC_MODEL": "muse-spark-1.3"})


class LegacySigningKey(unittest.TestCase):
    def test_old_key_name_never_mounts_into_the_fixer(self):
        self.assertIn(".nightshift-signing-key", FIXER_FORBIDDEN_BASENAMES)
        self.assertIn(".pixelproof-signing-key", FIXER_FORBIDDEN_BASENAMES)
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "player" / ".nightshift-signing-key"
            stale.parent.mkdir()
            stale.write_text("stale", encoding="utf-8")
            self.assertEqual(forbidden_paths_under(Path(tmp)), [stale])


if __name__ == "__main__":
    unittest.main()
