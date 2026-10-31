"""The discovery freeze: any change to a file that decides a finding breaks it."""
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail.discovery import freeze

REPO = Path(__file__).resolve().parents[1]


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
