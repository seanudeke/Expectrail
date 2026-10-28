import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness.run import (
    DEFAULT_CACHE_DIR,
    REPO,
    apply_patches,
    cache_key,
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
        with mock.patch.dict(os.environ):
            os.environ.pop("NIGHTSHIFT_GODOT_CACHE", None)  # a developer may have it set
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

    def _fake_godot_import(self, calls):
        """subprocess.run stand-in: '--import' creates .godot/imported in the target project."""
        def fake(cmd, **kw):
            calls.append(cmd)
            if "--import" in cmd:
                project = Path(cmd[cmd.index("--path") + 1])
                (project / ".godot" / "imported").mkdir(parents=True, exist_ok=True)
                (project / ".godot" / "imported" / "x.ctex").write_bytes(b"ctex")
            return mock.Mock(returncode=0, stdout="", stderr="")
        return fake

    def _game(self, root: Path) -> Path:
        game = root / "game"
        game.mkdir()
        (game / "project.godot").write_text("[application]\nname=\"Test\"\n", encoding="utf-8")
        return game

    def test_import_cache_inside_the_clean_game_is_never_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = self._game(root)
            (game / ".godot" / "imported").mkdir(parents=True)  # e.g. left by the editor
            godot = root / "fake-godot"
            godot.touch()
            calls = []
            with mock.patch.dict(os.environ, {"NIGHTSHIFT_GODOT_CACHE": str(root / "cache")}):
                with mock.patch("subprocess.run", side_effect=self._fake_godot_import(calls)):
                    found = ensure_import_cache(game, godot, {})
            self.assertEqual(found, root / "cache" / ".godot")
            self.assertNotEqual(found, game / ".godot")
            self.assertEqual(len([c for c in calls if "--import" in c]), 1)
            self.assertTrue((found / "imported" / "x.ctex").is_file())

    def test_matching_key_reuses_cache_and_a_changed_game_rewarms_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = self._game(root)
            godot = root / "fake-godot"
            godot.touch()
            calls = []
            with mock.patch.dict(os.environ, {"NIGHTSHIFT_GODOT_CACHE": str(root / "cache")}):
                with mock.patch("subprocess.run", side_effect=self._fake_godot_import(calls)):
                    first = ensure_import_cache(game, godot, {})
                    again = ensure_import_cache(game, godot, {})
                    self.assertEqual(len([c for c in calls if "--import" in c]), 1,
                                     "same game + same Godot must reuse the cache")
                    (game / "level.tscn").write_text("changed\n", encoding="utf-8")
                    third = ensure_import_cache(game, godot, {})
                    self.assertEqual(len([c for c in calls if "--import" in c]), 2,
                                     "a changed game must rebuild the cache")
            self.assertEqual(first, again)
            self.assertEqual(third, first)
            self.assertEqual((root / "cache" / ".godot.key").read_text().strip(), cache_key(game, godot))
            leftovers = [p.name for p in (root / "cache").iterdir() if p.name.startswith("staging-")]
            self.assertEqual(leftovers, [], "staging folders must be cleaned up")

    def test_failed_warm_falls_back_to_a_normal_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = self._game(root)
            godot = root / "fake-godot"
            godot.touch()
            boom = subprocess.CalledProcessError(1, ["godot", "--import"])
            with mock.patch.dict(os.environ, {"NIGHTSHIFT_GODOT_CACHE": str(root / "cache")}):
                with mock.patch("subprocess.run", side_effect=boom):
                    self.assertIsNone(ensure_import_cache(game, godot, {}))

    def test_run_skips_import_on_clean_cached_run(self):
        from harness.run import run

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = self._game(root)
            route = root / "route.json"
            route.write_text('{"name": "test", "ticks": 10}', encoding="utf-8")
            out = root / "out"
            godot_mock = root / "fake-godot"
            godot_mock.touch()

            calls = []
            fake_import = self._fake_godot_import(calls)

            def fake_subp(cmd, **kw):
                if "--write-movie" in cmd:
                    calls.append(cmd)
                    frames = out / "frames"
                    frames.mkdir(parents=True, exist_ok=True)
                    (frames / "f00000000.png").write_bytes(b"dummy")
                    (out / "trace.json").write_text('{"physicsTicksPerSecond": 60, "rows": []}', encoding="utf-8")
                    return mock.Mock(returncode=0, stdout="Godot Engine v4.7.2 Using Device: test", stderr="")
                return fake_import(cmd, **kw)

            with mock.patch.dict(os.environ, {"NIGHTSHIFT_GODOT_CACHE": str(root / "cache")}):
                with mock.patch("subprocess.run", side_effect=fake_subp):
                    ensure_import_cache(game, godot_mock, {})  # warm once
                    calls.clear()
                    # 1. Clean run with a warm, matching cache: no --import
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

