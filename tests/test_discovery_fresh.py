"""The fresh defect set's checks, digest and counts-only notices."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from expectrail.discovery import fresh

REPO = Path(__file__).resolve().parents[1]
PATCHES = ["bugs/sinking/v1.patch", "bugs/sinking/v2.patch", "bugs/layering/v1.patch", "bugs/layering/v2.patch",
           "bugs/missing-texture/v1.patch", "bugs/physics-fall-through/v1.patch", "bugs/physics-fall-through/v2.patch"]


def make_set(freeze_sha="f" * 64, set_dir="fresh", prefix="f"):
    root = Path(tempfile.mkdtemp())
    (root / set_dir / "routes").mkdir(parents=True)
    entries = []
    for i, src in enumerate(PATCHES, 1):
        fid = f"{prefix}{i:02d}"
        shutil.copy(REPO / src, root / set_dir / f"{fid}.patch")
        shutil.copy(REPO / "harness/routes/smoke.json", root / set_dir / "routes" / f"{fid}.json")
        entries.append({"id": fid, "kind": "intentional" if i == 7 else "defect", "patch": f"{set_dir}/{fid}.patch",
                        "area": "a", "description": "d", "howItShows": "h", "route": f"{set_dir}/routes/{fid}.json",
                        "traceVisible": "yes", "timing": "immediate"})
    doc = {"format": fresh.FORMAT, "frozenDiscovery": {"commit": "0" * 40, "sha256": freeze_sha},
           "createdAt": "2026-11-01T00:00:00Z", "entries": entries}
    (root / set_dir / "manifest.json").write_text(json.dumps(doc))
    return root


class FreshSet(unittest.TestCase):
    def test_a_good_set_passes(self):
        self.assertEqual(fresh.check(make_set(), freeze_sha="f" * 64), [])

    def test_set_two_lives_in_its_own_directory_with_its_own_ids(self):
        root = make_set(set_dir="fresh-2", prefix="g")
        self.assertEqual(fresh.check(root, freeze_sha="f" * 64, set_dir="fresh-2"), [])
        self.assertTrue(fresh.check(root, freeze_sha="f" * 64, set_dir="fresh"))  # not set 1
        wrong = make_set(set_dir="fresh-2", prefix="f")
        self.assertIn("ids must be unique and look like g01", fresh.check(wrong, freeze_sha="f" * 64, set_dir="fresh-2"))
        problems = fresh.check(root, freeze_sha="f" * 64, set_dir="fresh-2", require_commitment=True)
        self.assertTrue(any("fresh-2.sha256" in p for p in problems))

    def test_problems_are_named(self):
        root = make_set()
        doc = fresh.manifest(root)
        doc["entries"][0]["kind"] = "bug"
        doc["entries"][1]["patch"] = "../etc/passwd"
        (root / "fresh" / "f03.patch").write_text("--- a/nope.gd\n+++ b/nope.gd\n@@ -1 +1 @@\n-a\n+b\n")
        (root / "fresh" / "manifest.json").write_text(json.dumps(doc))
        problems = fresh.check(root, freeze_sha="0" * 64)
        text = "\n".join(problems)
        self.assertIn("frozenDiscovery.sha256", text)
        self.assertIn("no other kind", text)
        self.assertIn("f02: patch", text)
        self.assertIn("f03: the patch does not apply", text)

    def test_digest_changes_with_any_byte(self):
        root = make_set()
        before = fresh.digest(root / "fresh")
        (root / "fresh" / "f01.patch").write_text((root / "fresh" / "f01.patch").read_text() + "\n")
        self.assertNotEqual(before, fresh.digest(root / "fresh"))

    def test_notice_carries_counts_only(self):
        run = json.loads((REPO / "bench/discovery/local-oct31/discovery-run.json").read_text())
        line = fresh.notice(run, "f04", "defect")
        payload = json.loads(line.split("::", 2)[2])
        self.assertEqual((payload["flagged"], payload["reproduced"]), (True, 12))
        for leak in ("weapon", "jump", "facing", "enemy", "probe", "air-jump"):
            self.assertNotIn(leak, line)


class Collect(unittest.TestCase):
    def test_scores_defects_and_false_alarms(self):
        rows = [{"id": "clean", "kind": "clean", "flagged": False, "completion": "complete"},
                {"id": "f01", "kind": "defect", "flagged": True, "completion": "complete"},
                {"id": "f02", "kind": "defect", "flagged": False, "completion": "complete"},
                {"id": "f03", "kind": "intentional", "flagged": True, "completion": "partial"}]
        notes = [{"title": f"Blind {r['id']}", "message": json.dumps(r)} for r in rows]
        notes.append({"title": "Blind time f01", "message": "12 s"})

        def fetch(path):
            if path.endswith("annotations?per_page=100"):
                return notes
            if "/jobs" in path:
                return {"jobs": [{"name": "blind (f01)", "id": 1}]}
            return {"html_url": "u", "head_sha": "s", "created_at": "t"}

        doc = fresh.collect(9, Path(tempfile.mkdtemp()), fetch=fetch)
        self.assertEqual(doc["score"], {"defectsFlagged": 1, "defects": 2, "healthyFlagged": 1, "healthy": 2,
                                        "incomplete": 1})


if __name__ == "__main__":
    unittest.main()
