"""The demo page (docs/demo/) shows only what the repository can back up.

- Every clip in docs/demo/assets/manifest.json is the file it says it is, made from the patches it
  names (each still in the repository with the digest the manifest recorded), with one timeline row
  per frame. The clips themselves come from `python3 -m harness.demo_clips`.
- Every clip a case on the page plays is in the manifest.
- Every line in a case's Code Diff is copied from the public patch it names: a bug's patch reversed
  (what a correct fix undoes), or a fixture's or Muse Code's recorded patch as it is.
"""
from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEMO = REPO / "docs" / "demo"
PAGE = DEMO / "index.html"
MANIFEST = DEMO / "assets" / "manifest.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch_lines(path: Path) -> dict[str, set[str]]:
    """{file: every '-' and '+' line the patch changes in it}."""
    out: dict[str, set[str]] = {}
    current = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("+++ "):
            current = line[4:].removeprefix("b/")
            out.setdefault(current, set())
        elif line.startswith("--- "):
            continue
        elif current and line[:1] in "+-":
            out[current].add(line)
    return out


def page_cases(text: str) -> dict[str, dict]:
    """The page's CASES, as {case: {"clips": [...], "diff": {...}}}, read from its script."""
    body = text[text.index("const CASES = {"):text.index("let currentCaseKey")]
    cases = {}
    for m in re.finditer(r"\n      '([a-z0-9-]+)': \{", body):
        end = body.find("\n      },", m.end())
        block = body[m.end():end if end != -1 else len(body)]
        diff = re.search(r"diff: \{source: '([^']+)', reversed: (true|false), files: \[", block)
        files = []
        for f in re.finditer(r"\{file: '([^']+)', lines: ", block):
            lines, _ = json.JSONDecoder().raw_decode(block, f.end())
            files.append((f.group(1), lines))
        clips = re.search(r"clips: \[('[a-z0-9-]+'|null), ('[a-z0-9-]+'|null)\]", block)
        cases[m.group(1)] = {
            "diff": {"source": diff.group(1), "reversed": diff.group(2) == "true", "files": files} if diff else None,
            "clips": [None if c == "null" else c.strip("'") for c in clips.groups()] if clips else None,
        }
    return cases


class DemoPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.clips = {c["id"]: c for c in cls.manifest["clips"]}
        cls.cases = page_cases(PAGE.read_text(encoding="utf-8"))

    def test_the_page_has_its_twelve_cases(self):
        self.assertEqual(len(self.cases), 12, sorted(self.cases))
        for name, case in self.cases.items():
            self.assertIsNotNone(case["diff"], name)
            self.assertIsNotNone(case["clips"], name)

    def test_every_clip_is_the_file_the_manifest_names(self):
        route = REPO / self.manifest["route"]["path"]
        self.assertEqual(sha256(route), self.manifest["route"]["sha256"])
        for clip in self.manifest["clips"]:
            video = DEMO / "assets" / clip["video"]
            self.assertTrue(video.is_file(), clip["id"])
            self.assertEqual(sha256(video), clip["videoSha256"], clip["id"])
            self.assertEqual(len(clip["timeline"]), clip["frames"], clip["id"])
            for patch in clip["patches"]:
                self.assertEqual(sha256(REPO / patch["path"]), patch["sha256"], (clip["id"], patch["path"]))

    def test_no_clip_on_the_page_is_missing_from_the_manifest(self):
        videos = {p.name for p in (DEMO / "assets" / "videos").glob("*.mp4")}
        self.assertEqual(videos, {Path(c["video"]).name for c in self.manifest["clips"]})
        for name, case in self.cases.items():
            before, after = case["clips"]
            self.assertIn(before, self.clips, name)
            if after is not None:
                self.assertIn(after, self.clips, name)
            self.assertEqual(after is None, name.startswith("exploit-"), name)

    def test_every_diff_line_is_copied_from_its_patch(self):
        for name, case in self.cases.items():
            diff = case["diff"]
            changed = patch_lines(REPO / diff["source"])
            for file, lines in diff["files"]:
                self.assertIn(file, changed, (name, file))
                for line in lines:
                    original = ({"+": "-", "-": "+"}[line[0]] + line[1:]) if diff["reversed"] else line
                    self.assertIn(original, changed[file], (name, file, line))

    def test_the_page_says_nothing_headless(self):
        # Godot's headless mode draws nothing; the clips are rendered with opengl3 (harness/run.py).
        self.assertNotIn("headless", PAGE.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()
