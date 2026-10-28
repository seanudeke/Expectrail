import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness.run import (
    DEFAULT_CACHE_DIR,
    REPO,
    apply_patches,
    ensure_import_cache,
    get_cache_dir,
    prepare,
    tree_digest,
)


class HarnessTest(unittest.TestCase):
    def test_tree_digest_deterministic_and_ignores_godot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("hello\n", encoding="utf-8")
            (root / "sub").mkdir()
            (root / "sub" / "b.txt").write_text("world\n", encoding="utf-8")
            digest1 = tree_digest(root)

            # Creating a .godot directory must not change the tree digest
            (root / ".godot").mkdir()
            (root / ".godot" / "cache.bin").write_bytes(b"\x00\x01\x02")
            (root / "sub" / ".godot").mkdir()
            (root / "sub" / ".godot" / "other.bin").write_bytes(b"\x99")
            digest2 = tree_digest(root)

            self.assertEqual(digest1, digest2)

    def test_get_cache_dir_default_and_env(self):
        self.assertEqual(get_cache_dir(), DEFAULT_CACHE_DIR)
        with mock.patch.dict(os.environ, {"NIGHTSHIFT_GODOT_CACHE": "/custom/path"}):
            self.assertEqual(get_cache_dir(), Path("/custom/path/.godot"))
        with mock.patch.dict(os.environ, {"NIGHTSHIFT_GODOT_CACHE": "/custom/path/.godot"}):
            self.assertEqual(get_cache_dir(), Path("/custom/path/.godot"))

    def test_prepare_with_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / "game"
            work = root / "work"
            cache = root / "cache" / ".godot"

            game.mkdir(parents=True)
            (game / "project.godot").write_text("[application]\nname=\"Test\"\n", encoding="utf-8")

            cache_imported = cache / "imported"
            cache_imported.mkdir(parents=True)
            (cache_imported / "sample.ctex").write_bytes(b"dummy-ctex-data")

            prepare(game, work, cache=cache)

            self.assertTrue((work / "project.godot").is_file())
            self.assertTrue((work / "nightshift_harness.gd").is_file())
            self.assertTrue((work / "nightshift_recorder.gd").is_file())
            self.assertTrue((work / ".godot" / "imported" / "sample.ctex").is_file())
            self.assertIn("NightshiftHarness", (work / "project.godot").read_text(encoding="utf-8"))

    def test_ensure_import_cache_uses_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / "game"
            game.mkdir()
            (game / ".godot" / "imported").mkdir(parents=True)

            godot_mock = root / "fake-godot"
            godot_mock.touch()
            found = ensure_import_cache(game, godot_mock, {})
            self.assertEqual(found, game / ".godot")

    def test_run_skips_import_on_clean_cached_run(self):
        from harness.run import run

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = root / "game"
            game.mkdir()
            (game / "project.godot").write_text("[application]\nname=\"Test\"\n", encoding="utf-8")
            (game / ".godot" / "imported").mkdir(parents=True)

            route = root / "route.json"
            route.write_text('{"name": "test", "ticks": 10}', encoding="utf-8")

            out = root / "out"
            godot_mock = root / "fake-godot"
            godot_mock.touch()

            # Mock subprocess to simulate Godot movie maker run
            calls = []
            def fake_subp(cmd, **kw):
                calls.append(cmd)
                if "--write-movie" in cmd:
                    frames = out / "frames"
                    frames.mkdir(parents=True, exist_ok=True)
                    (frames / "f00000000.png").write_bytes(b"dummy")
                    (out / "trace.json").write_text('{"physicsTicksPerSecond": 60, "rows": []}', encoding="utf-8")
                return mock.Mock(returncode=0, stdout="Godot Engine v4.7.2 Using Device: test", stderr="")

            with mock.patch("subprocess.run", side_effect=fake_subp):
                # 1. Clean run: should NOT call --import
                run(route, out, game=game, godot=godot_mock)
                import_calls = [c for c in calls if "--import" in c]
                self.assertEqual(len(import_calls), 0, "Clean cached run must skip --import")

                # 2. Force import run: should call --import
                calls.clear()
                run(route, out, game=game, godot=godot_mock, force_import=True)
                import_calls = [c for c in calls if "--import" in c]
                self.assertEqual(len(import_calls), 1, "force_import must trigger --import")

                # 3. Patched run: should call --import for incremental check
                dummy_patch = root / "test.patch"
                dummy_patch.write_text("", encoding="utf-8")
                calls.clear()
                with mock.patch("harness.run.apply_patches"):
                    run(route, out, game=game, godot=godot_mock, patches=[dummy_patch])
                import_calls = [c for c in calls if "--import" in c]
                self.assertEqual(len(import_calls), 1, "Patched run must call --import incrementally")

    def test_all_seeded_bug_patches_apply_cleanly(self):
        patches = sorted((REPO / "bugs").glob("*/*.patch"))
        self.assertGreaterEqual(len(patches), 6)
        for patch in patches:
            with self.subTest(patch=patch.name):
                with tempfile.TemporaryDirectory() as tmp:
                    work = Path(tmp) / "game"
                    shutil.copytree(REPO / "game" / "platformer", work, ignore=shutil.ignore_patterns(".godot"))
                    apply_patches(work, [patch])


if __name__ == "__main__":
    unittest.main()

