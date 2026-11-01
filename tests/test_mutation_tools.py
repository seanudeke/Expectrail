"""The registration command and the results collector (agents/mutation_register.py,
agents/mutation_collect.py). The decisions below are test values, not proposals for the real ones."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents import mutate_game as mg
from agents import mutation_bench as mb
from agents import mutation_collect as mc
from agents import mutation_register as reg
from harness.run import REPO

VALUES = {"generator.seed": 11, "generator.sampleSize": 40, "generator.sampling": {"method": "uniform"},
          "generator.samplingWhy": "a test", "generator.positionStep": 8, "generator.offsetStep": 8,
          "generator.scaleStep": 0.25, "generator.zIndexStep": 1, "generator.constantScale": 2,
          "generator.collisionBits": 3, "oracle.traceThresholdPx": 1, "oracle.frameThreshold": 0, "stopRule": "x",
          "agreement.seed": 2, "agreement.minimum": 20, "reportTemplate": "x"}


def draft_of(doc: dict) -> dict:
    """The committed file as a draft, whether or not the study has been registered since."""
    doc = copy.deepcopy(doc)
    for field in mg.HUMAN_FIELDS:
        *parents, leaf = field.split(".")
        holder = doc
        for part in parents:
            holder = holder[part]
        holder[leaf] = None
    return doc


class RegisterBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.prereg, self.manifest = root / "preregistration.json", root / "generated" / "manifest.json"
        self.prereg.write_text(json.dumps(draft_of(json.loads(mg.PREREGISTRATION.read_text()))))
        patcher = mock.patch.object(reg, "dirty_pins", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def register(self, values=None, write=False):
        return reg.register(values or VALUES, write=write, prereg_path=self.prereg, manifest_path=self.manifest)


class RegisterTest(RegisterBase):
    def test_checking_writes_nothing(self):
        before = self.prereg.read_text()
        self.register()
        self.assertEqual(self.prereg.read_text(), before)
        self.assertFalse(self.manifest.exists())

    def test_writing_gives_what_a_judged_run_accepts(self):
        self.register(write=True)
        loaded = mg.load_preregistration(self.prereg)
        self.assertEqual(mg.load_manifest(loaded, self.manifest), json.loads(self.manifest.read_text()))
        self.assertTrue(loaded["status"].startswith("registered"))

    def test_seans_decisions_go_in_as_he_recorded_them(self):
        self.register(write=True)
        doc = json.loads(self.prereg.read_text())
        self.assertEqual(doc["wrongFix"]["commentOnlyLabel"], "good")
        self.assertEqual(doc["wrongFix"]["publicSamRuleApprovedBy"], "Sean, Oct 31, 2026")

    def test_the_exclusions_survive_and_the_rehearsed_mutants_are_not_drawn(self):
        values = {**VALUES, "generator.sampleSize": 3000}
        manifest = self.register(values, write=True)
        self.assertEqual(len(manifest["excludedBeforeDraw"]), 2)
        drawn = {m["id"] for m in manifest["mutants"]}
        self.assertFalse(drawn & set(manifest["excludedBeforeDraw"]))
        self.assertEqual(len(mb.study_pairs(json.loads(self.prereg.read_text()))), 47)

    def test_pins_are_the_files_as_they_stand_and_come_last(self):
        self.register(write=True)
        self.assertEqual(json.loads(self.prereg.read_text())["pins"], mg.current_pins())

    def test_a_missing_decision_is_refused_by_name(self):
        values = {k: v for k, v in VALUES.items() if k != "stopRule"}
        with self.assertRaises(mg.PreregistrationError) as caught:
            self.register(values)
        self.assertIn("stopRule", str(caught.exception))

    def test_a_number_that_cannot_do_its_job_is_refused_and_writes_nothing(self):
        for field, value, needle in (("oracle.traceThresholdPx", "abc", "traceThresholdPx"),
                                     ("oracle.traceThresholdPx", -1, "traceThresholdPx"),
                                     ("oracle.frameThreshold", 0.5, "frameThreshold"),
                                     ("generator.positionStep", 0, "positionStep"),
                                     ("generator.scaleStep", True, "scaleStep"),
                                     ("generator.zIndexStep", 0, "zIndexStep"),
                                     ("generator.zIndexStep", 1.5, "zIndexStep"),
                                     ("generator.collisionBits", 0, "collisionBits"),
                                     ("generator.constantScale", 1, "constantScale"),
                                     ("agreement.seed", "x", "agreement.seed")):
            with self.subTest(field=field, value=value), self.assertRaises(mg.PreregistrationError) as caught:
                self.register({**VALUES, field: value}, write=True)
            self.assertIn(needle, str(caught.exception))
        self.assertFalse(self.manifest.exists())

    def test_zero_thresholds_are_decisions(self):
        self.assertTrue(self.register({**VALUES, "oracle.traceThresholdPx": 0, "oracle.frameThreshold": 0}))

    def test_it_will_not_take_a_field_that_is_not_the_persons(self):
        for key in ("pins", "wrongFix.commentOnlyLabel", "excludedBeforeDraw", "generator.bogus"):
            with self.subTest(key=key), self.assertRaises(mg.PreregistrationError) as caught:
                self.register({**VALUES, key: "x"})
            self.assertIn(key, str(caught.exception))

    def test_a_bad_plan_fails_the_same_gate_as_a_judged_run_and_writes_nothing(self):
        values = {**VALUES, "generator.sampling": {"method": "stratified", "perClass": {"code": 1}}}
        with self.assertRaises(mg.PreregistrationError):
            self.register(values, write=True)
        self.assertIsNone(json.loads(self.prereg.read_text())["pins"])
        self.assertFalse(self.manifest.exists())

    def test_a_low_agreement_minimum_is_refused(self):
        with self.assertRaises(mg.PreregistrationError):
            self.register({**VALUES, "agreement.minimum": 19}, write=True)

    def test_a_registration_is_never_overwritten(self):
        self.register(write=True)
        first = self.prereg.read_text()
        with self.assertRaises(mg.PreregistrationError) as caught:
            self.register({**VALUES, "generator.seed": 12}, write=True)
        self.assertIn("never overwritten", str(caught.exception))
        self.assertEqual(self.prereg.read_text(), first)

    def test_a_stray_manifest_counts_as_registered(self):
        self.manifest.parent.mkdir()
        self.manifest.write_text("{}")
        with self.assertRaises(mg.PreregistrationError):
            self.register()

    def test_uncommitted_pinned_work_is_refused(self):
        with mock.patch.object(reg, "dirty_pins", return_value=["agents/verifier.py"]), \
                self.assertRaises(mg.PreregistrationError) as caught:
            self.register(write=True)
        self.assertIn("agents/verifier.py", str(caught.exception))

    def test_every_field_a_person_owes_is_in_the_docstring(self):
        for field in reg.PERSON_FIELDS:
            self.assertIn(f'"{field}"', reg.__doc__, field)

    def test_the_file_holds_no_decision_of_its_own(self):
        text = (REPO / "agents" / "mutation_register.py").read_text()
        self.assertNotIn("sampleSize\": 1", text)
        self.assertEqual(set(reg.PERSON_FIELDS) | set(reg.SEAN) | {"pins"}, set(mg.HUMAN_FIELDS))

    def test_the_cli_says_nothing_was_written_and_refuses_cleanly(self):
        path = Path(self.tmp.name) / "values.json"
        path.write_text(json.dumps({"generator.seed": 1}))
        with mock.patch("sys.stderr.write") as err:
            self.assertEqual(reg.main(["--values", str(path)]), 2)
        self.assertIn("missing", "".join(c.args[0] for c in err.call_args_list))


class CliTest(unittest.TestCase):
    def test_an_unreadable_decisions_file_is_an_error_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{not json")
            for path in (bad, Path(tmp) / "gone.json"):
                with self.subTest(path=path.name), mock.patch("sys.stderr.write"):
                    self.assertEqual(reg.main(["--values", str(path)]), 2)


class DirtyPinsTest(unittest.TestCase):
    def test_it_asks_git_about_every_pinned_path(self):
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout=" M agents/verifier.py\n")) as run:
            self.assertEqual(reg.dirty_pins(), ["agents/verifier.py"])
        asked = run.call_args.args[0]
        for rel in (*mg.PINNED, *mg.PINNED_TREES, "game/platformer"):
            self.assertIn(rel, asked)

    def test_clean_is_empty(self):
        with mock.patch("subprocess.run", return_value=mock.Mock(stdout="")):
            self.assertEqual(reg.dirty_pins(), [])


class CollectBase(unittest.TestCase):
    PREREG = {"sha256": "ab" * 32, "excludedBeforeDraw": {"pairs": [{"case": "dev/physics-fall-through/v1",
                                                                     "operator": "freeze"}]},
              "agreement": {"seed": 3, "minimum": 2}}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "recorded"

    @staticmethod
    def row(name: str, **fields) -> dict:
        return {"format": mb.FORMAT, "label": "bad", "preregistrationSha256": "ab" * 32, "samImages": 0, **fields, "_": name}

    def fetch_of(self, by_run: dict):
        def fetch(run, dest):
            for name, row in by_run[run].items():
                d = dest / "runs" / "mutation" / name
                d.mkdir(parents=True, exist_ok=True)
                (d / "result.json").write_text(json.dumps(row))

        return fetch

    def pairs(self):
        return {f"{c}+{o}".replace("/", "_"): self.row("p", kind="wrong-fix", case=c, operator=o, outcome="caught-cheap")
                for c, o in mb.study_pairs(self.PREREG)}

    def record(self, by_run, part="wrong-fix"):
        return mc.record(list(by_run), part, self.out, prereg=self.PREREG, fetch=self.fetch_of(by_run))


class RecordTest(CollectBase):
    def test_a_complete_part_is_recorded_with_its_run_and_spend(self):
        rows = self.pairs()
        next(iter(rows.values()))["samImages"] = 400
        doc = self.record({7: rows})
        self.assertEqual((doc["cases"], doc["missingCases"], doc["unexpectedCases"]), (47, [], []))
        text = (self.out / "README.md").read_text()
        self.assertIn("Recorded from run 7", text)
        self.assertIn("400 images, $1.00", text)
        self.assertEqual(json.loads((self.out / "summary.json").read_text())["runs"], [7])

    def test_missing_cases_are_reported_never_filled_in(self):
        rows = self.pairs()
        rows.pop(next(iter(rows)))
        doc = self.record({7: rows})
        self.assertEqual(len(doc["missingCases"]), 1)
        self.assertIn("Not complete: 1 cases missing", (self.out / "README.md").read_text())

    def test_the_excluded_pair_turning_up_is_flagged(self):
        rows = self.pairs()
        rows["x"] = self.row("x", kind="wrong-fix", case="dev/physics-fall-through/v1", operator="freeze",
                             outcome="caught-cheap")
        self.assertEqual(self.record({7: rows})["unexpectedCases"], ["dev/physics-fall-through/v1 freeze"])

    def test_a_cheap_phase_is_not_a_score(self):
        """It cannot produce a survivor, so it would always read as near 100%."""
        cheap = {"m1": self.row("m", kind="mutant", id="m1", tier="cheap", outcome="awaiting-sam"),
                 "m2": self.row("m", kind="mutant", id="m2", tier="cheap", outcome="caught-cheap")}
        with mock.patch.object(mg, "load_manifest", return_value={"mutants": [{"id": "m1"}, {"id": "m2"}]}):
            doc = self.record({7: cheap}, part="generated")
        self.assertIsNone(doc["score"])
        text = (self.out / "README.md").read_text()
        self.assertIn("Not a score yet", text)
        self.assertNotIn("100.0%", text)

    def test_a_rehearsal_cheap_row_cannot_hide_behind_a_sam_row(self):
        cheap = {"m": self.row("m", kind="mutant", id="m", tier="cheap", outcome="awaiting-sam", rehearsal=True)}
        sam = {"m": self.row("m", kind="mutant", id="m", tier="sam", outcome="caught-sam")}
        with self.assertRaises(SystemExit) as caught:
            self.record({7: cheap, 8: sam}, part="generated")
        self.assertIn("rehearsal", str(caught.exception))

    def test_a_foreign_cheap_row_cannot_hide_behind_a_sam_row(self):
        cheap = {"m": self.row("m", kind="mutant", id="m", tier="cheap", outcome="awaiting-sam",
                               preregistrationSha256="cd" * 32)}
        sam = {"m": self.row("m", kind="mutant", id="m", tier="sam", outcome="caught-sam")}
        with self.assertRaises(SystemExit) as caught:
            self.record({7: cheap, 8: sam}, part="generated")
        self.assertIn("not from this registration", str(caught.exception))

    def test_two_overlapping_runs_are_refused_not_counted_twice(self):
        with self.assertRaises(SystemExit) as caught:
            self.record({7: self.pairs(), 8: self.pairs()})
        self.assertIn("appear twice", str(caught.exception))

    def test_a_repeated_sam_phase_is_refused(self):
        sam = {"m": self.row("m", kind="mutant", id="m", tier="sam", outcome="caught-sam")}
        with self.assertRaises(SystemExit):
            self.record({7: sam, 8: sam}, part="generated")

    def test_recording_again_leaves_no_stale_finding_and_keeps_the_manifest(self):
        self.out.mkdir()
        (self.out / "manifest.json").write_text("{}")
        (self.out / "findings" / "old").mkdir(parents=True)
        (self.out / "findings" / "old" / "finding.json").write_text("{}")
        self.record({7: self.pairs()})
        self.assertFalse((self.out / "findings").exists())
        self.assertTrue((self.out / "manifest.json").is_file())

    def test_a_refused_record_leaves_nothing_on_disk(self):
        rows = self.pairs()
        next(iter(rows.values()))["error"] = "sk-abcdefghijklmnopqrstuvwxyz123456"
        with self.assertRaises(SystemExit):
            self.record({7: rows})
        self.assertFalse(self.out.exists())

    def test_the_exit_code_says_when_a_record_is_not_clean(self):
        base = {"cases": 1, "missingCases": [], "unexpectedCases": [], "error": 0, "awaiting-sam": 0,
                "spend": {"samUsd": 0.0}}
        for change, code in (({}, 0), ({"missingCases": ["a"]}, 1), ({"unexpectedCases": ["a"]}, 1), ({"error": 1}, 1),
                             ({"awaiting-sam": 3}, 0)):
            with self.subTest(change=change), mock.patch.object(mc, "record", return_value={**base, **change}):
                self.assertEqual(mc.main(["--part", "wrong-fix", "--run", "1", "--out", str(self.out)]), code)

    def test_a_failed_download_is_an_error_not_a_traceback(self):
        import subprocess

        with mock.patch.object(mc, "record", side_effect=subprocess.CalledProcessError(1, ["gh"], stderr="no such run")), \
                mock.patch("sys.stderr.write"):
            self.assertEqual(mc.main(["--part", "wrong-fix", "--run", "1", "--out", str(self.out)]), 2)

    def test_a_rehearsal_is_refused(self):
        rows = {"a": self.row("a", kind="wrong-fix", rehearsal=True, case="c", operator="o", outcome="caught-cheap")}
        with self.assertRaises(SystemExit) as caught:
            self.record({7: rows})
        self.assertIn("rehearsal", str(caught.exception))
        self.assertFalse(self.out.exists())

    def test_another_registration_is_refused(self):
        rows = {"a": self.row("a", kind="wrong-fix", case="c", operator="o", outcome="survived",
                              preregistrationSha256="cd" * 32)}
        with self.assertRaises(SystemExit) as caught:
            self.record({7: rows})
        self.assertIn("not from this registration", str(caught.exception))

    def test_the_wrong_part_is_refused(self):
        rows = {"a": self.row("a", kind="mutant", id="m", outcome="survived")}
        with self.assertRaises(SystemExit) as caught:
            self.record({7: rows}, part="wrong-fix")
        self.assertIn("records wrong-fix rows", str(caught.exception))

    def test_no_results_are_refused(self):
        with self.assertRaises(SystemExit):
            self.record({7: {}})

    def test_a_run_named_twice_is_refused(self):
        with self.assertRaises(SystemExit):
            mc.record([7, 7], "wrong-fix", self.out, prereg=self.PREREG, fetch=lambda run, dest: None)

    def test_two_phases_count_a_mutant_once_as_its_sam_phase(self):
        manifest = Path(self.tmp.name) / "manifest.json"
        manifest.write_text("{}")
        cheap = {"m1": self.row("m", kind="mutant", id="m1", tier="cheap", outcome="awaiting-sam"),
                 "m2": self.row("m", kind="mutant", id="m2", tier="cheap", outcome="caught-cheap")}
        sam = {"m1": self.row("m", kind="mutant", id="m1", tier="sam", outcome="caught-sam")}
        with mock.patch.object(mg, "load_manifest", return_value={"mutants": [{"id": "m1"}, {"id": "m2"}]}):
            doc = self.record({8: sam, 7: cheap}, part="generated")  # last in, so a shared folder would lose the SAM row
        self.assertEqual((doc["cases"], doc["caught-sam"], doc["caught-cheap"], doc["awaiting-sam"]), (2, 1, 1, 0))
        self.assertEqual(doc["missingCases"], [])
        self.assertEqual(doc["runs"], [8, 7])

    def test_findings_are_kept(self):
        rows = self.pairs()
        name = next(iter(rows))

        def fetch(run, dest):
            self.fetch_of({7: rows})(run, dest)
            (dest / "runs" / "mutation" / name / "finding.json").write_text("{}")

        mc.record([7], "wrong-fix", self.out, prereg=self.PREREG, fetch=fetch)
        self.assertTrue((self.out / "findings" / name / "finding.json").is_file())

    def test_a_key_in_the_results_stops_the_record(self):
        rows = self.pairs()
        next(iter(rows.values()))["error"] = "sk-abcdefghijklmnopqrstuvwxyz123456"
        with self.assertRaises(SystemExit) as caught:
            self.record({7: rows})
        self.assertIn("export scan refused", str(caught.exception))


class PlanTest(CollectBase):
    def rows(self):
        out = {f"c{i}": self.row("c", kind="mutant", id=f"c{i}", tier="cheap", outcome="caught-cheap") for i in range(5)}
        out["s"] = self.row("s", kind="mutant", id="left", tier="cheap", outcome="awaiting-sam")
        return out

    def plan(self, rows=None):
        ids = [r["id"] for r in (rows or self.rows()).values()]
        with mock.patch.object(mg, "load_manifest", return_value={"mutants": [{"id": i} for i in ids]}):
            return mc.plan(7, prereg=self.PREREG, fetch=self.fetch_of({7: rows or self.rows()}))

    def test_a_tool_error_stops_the_plan_since_the_sample_depends_on_the_catches(self):
        rows = self.rows()
        rows["c0"]["outcome"] = "error"
        with self.assertRaises(SystemExit) as caught:
            self.plan(rows)
        self.assertIn("1 tool errors", str(caught.exception))

    def test_a_missing_case_stops_the_plan(self):
        rows = self.rows()
        with mock.patch.object(mg, "load_manifest", return_value={"mutants": [{"id": "gone"}]}), \
                self.assertRaises(SystemExit) as caught:
            mc.plan(7, prereg=self.PREREG, fetch=self.fetch_of({7: rows}))
        self.assertIn("1 cases missing", str(caught.exception))

    def test_a_sam_run_is_not_a_cheap_run(self):
        rows = self.rows()
        rows["s"]["tier"] = "sam"
        with self.assertRaises(SystemExit) as caught:
            self.plan(rows)
        self.assertIn("cheap phase's run", str(caught.exception))

    def test_it_takes_every_survivor_and_the_seeded_sample(self):
        chosen = self.plan()
        self.assertEqual(chosen["survivors"], ["left"])
        self.assertEqual(len(chosen["agreement"]), 2)
        self.assertEqual(chosen, self.plan())

    def test_it_gives_an_upper_bound_for_the_estimate_127_asks_for(self):
        chosen = self.plan()
        self.assertEqual((chosen["maxImages"], chosen["maxUsd"]), (1440, 3.6))

    def test_only_the_agreement_sample_forces_sam(self):
        lines = mc.dispatch_lines({"survivors": ["a", "b"], "agreement": ["c"]})
        self.assertEqual(len(lines), 2)
        self.assertIn("-f force_sam=off -f mutants='a,b'", lines[0])
        self.assertIn("-f force_sam=on -f mutants='c'", lines[1])
        self.assertTrue(all("--ref main" in line for line in lines))

    def test_an_empty_list_dispatches_nothing(self):
        self.assertEqual(len(mc.dispatch_lines({"survivors": [], "agreement": ["c"]})), 1)

    def test_the_cli_takes_one_run_for_a_plan(self):
        with self.assertRaises(SystemExit):
            mc.main(["--plan-sam", "--run", "1", "--run", "2"])


class NothingPinnedTest(unittest.TestCase):
    def test_these_tools_are_not_pinned_so_they_can_change_after_registration(self):
        for rel in ("agents/mutation_register.py", "agents/mutation_collect.py"):
            self.assertNotIn(rel, mg.PINNED)


if __name__ == "__main__":
    unittest.main()
