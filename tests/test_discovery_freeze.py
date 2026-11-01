"""The discovery freeze: any change to a file that decides a finding breaks it."""
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail.discovery import freeze

REPO = Path(__file__).resolve().parents[1]


class FreezeHoldsOnMain(unittest.TestCase):
    """While fresh set 2 is in use for blind runs (docs/discovery.md, The blind run), no file that
    decides a finding may change: this is freeze 2, the one set 2 is written against. Remove or
    re-pin this test, deliberately, only when the team retires set 2; a changed discoverer needs a
    new freeze and a new fresh set."""

    def test_the_frozen_files_and_the_clean_game_are_unchanged(self):
        ok, problems, digest = freeze.verify(REPO)
        self.assertTrue(ok, f"discovery is frozen for the blind run: {problems}")
        self.assertEqual(digest, "9af1f621c33ce4668eb8ad356a3220ea352d106595b0bc1b4cf877eead5e3053")


class FreezeOne(unittest.TestCase):
    def test_freeze_one_is_kept_and_differs_only_in_the_planner_request(self):
        import json
        one = json.loads((REPO / "discovery" / "freeze-1.json").read_text())
        two = json.loads((REPO / "discovery" / "freeze.json").read_text())
        self.assertEqual(one["sha256"], "6e9ca2bda1c0cf3d0d491ae411bbeb54e18c6701ebd1ed6274c742c02a644824")
        changed = sorted(f for f in one["files"] if one["files"][f] != two["files"].get(f))
        self.assertEqual(changed, ["expectrail/discovery/planner.py"])
        self.assertEqual(one["gameTree"], two["gameTree"])


class Freeze(unittest.TestCase):
    def copy(self):
        root = Path(tempfile.mkdtemp())
        for f in freeze.FROZEN:
            (root / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(REPO / f, root / f)
        (root / freeze.GAME / "player").mkdir(parents=True)
        (root / freeze.GAME / "player" / "player.gd").write_text("extends Node\n")
        (root / "discovery").mkdir(exist_ok=True)
        self.assertEqual(freeze.main(["write", "--root", str(root)]), 0)
        return root

    def test_an_untouched_checkout_verifies(self):
        ok, problems, digest = freeze.verify(self.copy())
        self.assertTrue(ok, problems)
        self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_a_changed_rule_or_game_breaks_it(self):
        root = self.copy()
        (root / "expectrail/discovery/templates.py").write_text("# tuned after the defects were written\n")
        (root / freeze.GAME / "player" / "player.gd").write_text("extends Node2D\n")
        ok, problems, _ = freeze.verify(root)
        self.assertFalse(ok)
        self.assertIn("expectrail/discovery/templates.py changed", problems)
        self.assertIn("game/platformer changed", problems)

    def test_the_digest_covers_its_own_record(self):
        root = self.copy()
        path = root / freeze.FREEZE
        path.write_text(path.read_text().replace('"command": "python', '"command": "python3'))
        ok, problems, _ = freeze.verify(root)
        self.assertFalse(ok)
        self.assertIn("the blind command changed", problems)


if __name__ == "__main__":
    unittest.main()
