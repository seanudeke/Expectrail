"""agents.export_scan: nothing private, no key and no signing key leaves a run, and the scan's own
output never repeats what it found. The private set here is synthetic; the real one is only ever
read in CI on the verifier's side."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from agents.export_scan import main, private_items, scan
from harness.run import REPO

ROUTE = "quarry-gap-sprint"
DESCRIPTION = "The robot's collision layer is cleared on the third platform only; it falls there."
ADDED = "collision_layer = 0x7f1e  # synthetic held-out mechanism"


class ExportScanTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        private = self.tmp / "private"
        (private / "routes").mkdir(parents=True)
        (private / "bugs" / "physics").mkdir(parents=True)
        (private / "routes" / f"{ROUTE}.json").write_text("{}")
        clean_line = next(l for l in (REPO / "game" / "platformer" / "player" / "player.tscn").read_text().splitlines()
                          if len(l.strip()) >= 12)
        (private / "bugs" / "physics" / "v9.patch").write_text(
            f"--- a/player/player.tscn\n+++ b/player/player.tscn\n-{clean_line}\n+{ADDED}\n+{clean_line}\n")
        (private / "manifest.json").write_text(json.dumps({
            "routes": [{"name": ROUTE, "file": f"routes/{ROUTE}.json", "minDeltaX": 300}],
            "variants": [{"family": "physics", "id": "v9", "patch": "bugs/physics/v9.patch",
                          "spec": "ground", "description": DESCRIPTION}],
        }))
        self.private = private
        self.clean_line = clean_line
        self.out = self.tmp / "keep"
        self.out.mkdir()

    def run_main(self, *args: str) -> tuple[int, str]:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([str(self.out), "--private", str(self.private), *args])
        return code, buf.getvalue()

    def write(self, name: str, text: str) -> None:
        (self.out / name).parent.mkdir(parents=True, exist_ok=True)
        (self.out / name).write_text(text)

    def test_a_clean_export_passes_and_ids_counts_and_verdicts_may_leave(self):
        self.write("result.json", json.dumps({"case": "physics/v9", "outcome": "fixed", "attempts": 2}))
        self.assertEqual(self.run_main()[0], 0)

    def test_private_material_fails_and_the_output_never_repeats_it(self):
        for name, text in (("a.md", f"replayed on {ROUTE}"), ("b.txt", DESCRIPTION),
                           ("c.patch", f"+{ADDED}\n")):
            self.write(name, text)
        code, out = self.run_main()
        self.assertEqual(code, 1)
        for kind in ("private route names", "private variant descriptions", "private patch lines"):
            self.assertIn(kind, out)
        for secret in (ROUTE, DESCRIPTION, ADDED, "collision_layer = 0x7f1e"):
            self.assertNotIn(secret, out)

    def test_a_line_the_clean_game_already_has_is_not_private(self):
        self.write("diff.patch", f"-{self.clean_line}\n+{self.clean_line}\n")
        self.assertEqual(self.run_main()[0], 0)
        self.assertNotIn(self.clean_line.strip(), private_items(self.private)["patch lines"])

    def test_a_route_name_inside_another_word_is_not_a_match(self):
        self.write("a.md", f"pre{ROUTE}post and {ROUTE}-extended")
        self.assertEqual(self.run_main()[0], 0)

    def test_keys_and_signing_keys_fail_without_being_printed(self):
        self.write("log.txt", "used msk-" + "Q" * 40)
        self.write("verifier-host/.expectrail-signing-key", "anything")
        self.write("verifier-host/.expectrail-signing-key.pub", "public half is fine")
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn("key-like strings", out)
        self.assertIn("a signing key file", out)
        self.assertNotIn("Q" * 20, out)
        self.assertEqual(out.count("signing key file"), 1)

    def test_frames_from_private_routes_fail(self):
        (self.out / "held-out" / "r1" / "frames").mkdir(parents=True)
        (self.out / "held-out" / "r1" / "frames" / "f00000008.png").write_bytes(b"\x89PNG")
        (self.out / "review" / "assets").mkdir(parents=True)
        (self.out / "review" / "assets" / "base.png").write_bytes(b"\x89PNG")  # public route frame: fine
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(out.count("an image from the private routes"), 1)

    def test_machine_paths_warn_unless_asked_to_fail(self):
        self.write("report.md", "path=`/Users/someone/work/x` and /home/runner/work/ok")
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("::warning title=Export scan::report.md: 1 machine home paths", out)
        self.assertEqual(self.run_main("--paths", "error")[0], 1)

    def test_without_the_private_set_the_rest_is_still_checked(self):
        self.write("log.txt", "used msk-" + "Q" * 40)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([str(self.out), "--private", str(self.tmp / "absent")])
        self.assertEqual(code, 1)
        self.assertIn("no private set here", buf.getvalue())

    def test_the_public_repository_has_no_errors(self):
        findings = scan([REPO / p for p in ("bench", "docs", "README.md", "apps")],
                        private=private_items(self.private), base=REPO)
        self.assertEqual([f for f in findings if f["level"] == "error"], [])


class PublicLinesTest(unittest.TestCase):
    def test_a_line_a_public_patch_also_adds_is_not_private(self):
        public = next(l[1:].strip() for l in (REPO / "bugs" / "layering" / "v1.patch").read_text().splitlines()
                      if l.startswith("+") and not l.startswith("+++") and len(l[1:].strip()) >= 12)
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp)
            (private / "v9.patch").write_text(f"+{public}\n+{ADDED}\n")
            (private / "manifest.json").write_text(json.dumps({"variants": [{"family": "layering", "id": "v9",
                                                                               "patch": "v9.patch"}]}))
            items = private_items(private)
        self.assertEqual(items["patch lines"], [ADDED])


if __name__ == "__main__":
    unittest.main()
