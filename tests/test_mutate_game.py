"""The generator and the oracle (agents/mutate_game.py, #127): nobody picks a case, and the same seed
gives the same mutants. The steps below are test values, not the pre-registered ones."""
from __future__ import annotations

import copy
import json
import math
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agents.mutate_game as mg
from harness.run import REPO, tree_digest

PARAMS = {"positionStep": 8, "offsetStep": 8, "scaleStep": 0.25, "zIndexStep": 1, "constantScale": 2,
          "collisionBits": 3, "seed": 11, "sampleSize": 40, "sampling": {"method": "uniform"}, "samplingWhy": "a test"}


def prereg() -> dict:
    return {"generator": dict(PARAMS)}


class EnumerateTest(unittest.TestCase):
    def setUp(self):
        self.every = mg.enumerate_mutants(PARAMS)

    def test_ids_are_unique_and_order_is_fixed(self):
        self.assertEqual(len({m["id"] for m in self.every}), len(self.every))
        self.assertEqual(self.every, mg.enumerate_mutants(PARAMS))

    def test_every_listed_class_that_has_sites_is_reached(self):
        self.assertEqual({m["class"] for m in self.every}, set(mg.OPERATOR_CLASSES))

    def test_every_mutant_changes_its_line_and_touches_one_listed_file(self):
        for m in self.every:
            self.assertNotEqual(m["before"], m["after"], m["id"])
            self.assertTrue(m["file"].endswith(".tscn") or m["file"] in mg.CODE_FILES, m["id"])

    def test_numeric_moves_one_axis_by_the_step(self):
        out = mg._scene_mutants("x.tscn", 1, "position = Vector2(10, -2.5)", PARAMS)
        self.assertEqual([m["after"] for m in out], ["position = Vector2(18, -2.5)", "position = Vector2(2, -2.5)",
                                                     "position = Vector2(10, 5.5)", "position = Vector2(10, -10.5)"])

    def test_z_index_both_ways(self):
        self.assertEqual([m["after"] for m in mg._scene_mutants("x.tscn", 1, "z_index = -3", PARAMS)],
                         ["z_index = -2", "z_index = -4"])

    def test_a_boolean_flips(self):
        self.assertEqual(mg._scene_mutants("x.tscn", 1, "one_way_collision = true", PARAMS)[0]["after"],
                         "one_way_collision = false")

    def test_collision_bits_flip_one_at_a_time(self):
        self.assertEqual([m["after"] for m in mg._scene_mutants("x.tscn", 1, "collision_mask = 3", PARAMS)],
                         ["collision_mask = 2", "collision_mask = 1", "collision_mask = 7"])

    def test_a_broken_resource_loses_its_uid_too(self):
        line = '[ext_resource type="Texture2D" uid="uid://abc" path="res://level/coin.webp" id="1"]'
        after = mg._scene_mutants("x.tscn", 1, line, PARAMS)[0]["after"]
        self.assertEqual(after, '[ext_resource type="Texture2D" path="res://level/coin.webp.missing" id="1"]')

    def test_code_operators(self):
        tags = lambda line: [m["after"] for m in mg._code_mutants("p.gd", 1, line, PARAMS)]  # noqa: E731
        self.assertEqual(tags("const WALK_SPEED = 300.0"), ["const WALK_SPEED = -300", "const WALK_SPEED = 600"])
        self.assertEqual(tags("\tif velocity.x > 0.0:"), ["\tif velocity.x < 0.0:"])
        self.assertEqual(tags("\t\tvelocity.x = -WALK_SPEED"), ["\t\tvelocity.x = WALK_SPEED"])

    def test_a_return_arrow_and_a_comment_are_left_alone(self):
        self.assertEqual(mg._code_mutants("p.gd", 1, "func f() -> void:", PARAMS), [])
        self.assertEqual(mg._code_mutants("p.gd", 1, "\t# if a > b:", PARAMS), [])


class PatchTest(unittest.TestCase):
    def test_a_sample_of_every_class_applies_and_reverses(self):
        every = mg.enumerate_mutants(PARAMS)
        picks = [next(m for m in every if m["class"] == c) for c in mg.OPERATOR_CLASSES] + mg.sample(every, 3, 25)
        with tempfile.TemporaryDirectory() as tmp:
            for m in picks:
                game, patch = Path(tmp) / "game", Path(tmp) / "m.patch"
                shutil.rmtree(game, ignore_errors=True)
                shutil.copytree(mg.GAME, game, ignore=shutil.ignore_patterns(".godot"))
                patch.write_text(mg.patch_text(m))
                self.assertIn(f"--- a/{m['file']}", patch.read_text())
                base = ["patch", "-p1", "--batch", "-d", str(game), "-i", str(patch)]
                subprocess.run(base + ["--forward"], check=True, capture_output=True)
                self.assertIn(m["after"], (game / m["file"]).read_text(), m["id"])
                subprocess.run(base + ["--reverse"], check=True, capture_output=True)
                self.assertEqual(tree_digest(game), tree_digest(mg.GAME), m["id"])

    def test_a_stale_mutant_is_refused(self):
        m = dict(mg.enumerate_mutants(PARAMS)[0], before="not this line")
        with self.assertRaises(ValueError):
            mg.patch_text(m)


class SampleTest(unittest.TestCase):
    def test_the_same_seed_gives_a_byte_identical_manifest(self):
        with mock.patch.object(mg, "_sha", return_value="x"):
            self.assertEqual(json.dumps(mg.build_manifest(prereg())), json.dumps(mg.build_manifest(prereg())))

    def test_a_different_seed_differs(self):
        every = mg.enumerate_mutants(PARAMS)
        self.assertNotEqual(mg.sample(every, 1, 40), mg.sample(every, 2, 40))

    def test_a_sample_larger_than_the_generator_gives_everything(self):
        self.assertEqual(len(mg.sample([{"id": "a"}], 1, 5)), 1)

    def test_the_manifest_counts_reconcile(self):
        with mock.patch.object(mg, "_sha", return_value="x"):
            doc = mg.build_manifest(prereg())
        self.assertEqual(sum(doc["sampledByClass"].values()), doc["sampled"])
        self.assertEqual(doc["sampled"], len(doc["mutants"]))
        self.assertEqual(sum(doc["enumeratedByClass"].values()), doc["enumerated"])

    def test_the_cli_gives_counts_at_the_registered_steps_with_nothing_else_filled_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.json"
            path.write_text(json.dumps({"generator": PARAMS}))
            with mock.patch("sys.stdout.write") as out:
                self.assertEqual(mg.main(["--mutants-by-class", "--prereg", str(path)]), 0)
        printed = json.loads("".join(c.args[0] for c in out.call_args_list))
        self.assertEqual(sum(printed.values()), len(mg.enumerate_mutants(PARAMS)))

    def test_nothing_private_can_be_mutated(self):
        self.assertFalse(any("held" in m["file"] for m in mg.enumerate_mutants(PARAMS)))


class StratifiedTest(unittest.TestCase):
    PER_CLASS = {"numeric": 10, "boolean": 1, "collision-bit": 5, "code": 8, "resource-path": 6}

    def gen(self, **over):
        return {**PARAMS, "sampleSize": 30, "sampling": {"method": "stratified", "perClass": dict(self.PER_CLASS)}, **over}

    def counts(self, gen):
        out = {}
        for m in mg.draw(mg.enumerate_mutants(gen), gen):
            out[m["class"]] = out.get(m["class"], 0) + 1
        return out

    def test_each_class_gets_exactly_its_count(self):
        self.assertEqual(self.counts(self.gen()), self.PER_CLASS)

    def test_the_draw_is_seeded_and_in_enumeration_order(self):
        gen = self.gen()
        every = mg.enumerate_mutants(gen)
        first = mg.draw(every, gen)
        self.assertEqual(first, mg.draw(every, gen))
        self.assertEqual([m["id"] for m in first], [m["id"] for m in every if m in first])
        self.assertNotEqual(first, mg.draw(every, self.gen(seed=12)))

    def test_changing_one_class_leaves_the_others_draws_alone(self):
        ids = lambda gen, cls: [m["id"] for m in mg.draw(mg.enumerate_mutants(gen), gen) if m["class"] == cls]  # noqa: E731
        other = self.gen(sampleSize=31)
        other["sampling"]["perClass"]["numeric"] = 11
        self.assertEqual(ids(self.gen(), "code"), ids(other, "code"))

    def test_a_short_class_gives_all_it_has_and_the_manifest_says_so(self):
        gen = self.gen(sampleSize=32)
        gen["sampling"]["perClass"]["boolean"] = 3
        with mock.patch.object(mg, "_sha", return_value="x"):
            doc = mg.build_manifest({"generator": gen})
        self.assertEqual(doc["sampledByClass"]["boolean"], 1)
        self.assertEqual(doc["shortByClass"], {"boolean": 2})
        self.assertEqual(doc["sampled"], 30)  # the shortfall never moves to another class

    def test_a_uniform_draw_is_unchanged_by_this(self):
        every = mg.enumerate_mutants(PARAMS)
        self.assertEqual(mg.draw(every, PARAMS), mg.sample(every, 11, 40))

    def test_bad_plans_are_named(self):
        for gen, needle in ((self.gen(sampleSize=29), "adds up to 30"),
                            ({**PARAMS, "sampling": {"method": "by-vibes"}}, "uniform or stratified"),
                            ({**PARAMS, "sampling": {"method": "uniform", "perClass": {}}}, "takes no perClass"),
                            (self.gen(sampling={"method": "stratified", "perClass": {"scenery": 30}}), "scenery"),
                            (self.gen(sampling={"method": "stratified", "perClass": {"numeric": -1, "code": 31}}),
                             "whole number"),
                            (self.gen(sampling={"method": "stratified", "perClass": {"numeric": True, "code": 29}}),
                             "whole number"),
                            (self.gen(sampling={"method": "stratified"}), "no classes")):
            with self.subTest(needle=needle):
                self.assertIn(needle, mg.sampling_problem(gen))

    def test_good_plans_pass(self):
        self.assertIsNone(mg.sampling_problem(self.gen()))
        self.assertIsNone(mg.sampling_problem(PARAMS))


class SiteCountTest(unittest.TestCase):
    def test_operators_with_no_sites_are_reported_not_hidden(self):
        sites = mg.site_counts()
        self.assertEqual((sites["boolean/visible"], sites["boolean/disabled"]), (0, 0))
        self.assertEqual(sites["boolean/one_way_collision"], 1)


class PreregistrationTest(unittest.TestCase):
    def complete(self) -> dict:
        doc = json.loads(mg.PREREGISTRATION.read_text())
        doc["wrongFix"].update(commentOnlyLabel="good", publicSamRuleApprovedBy="x")
        doc["generator"] = dict(PARAMS)
        doc["oracle"].update(traceThresholdPx=1, frameThreshold=0)
        doc["agreement"].update(seed=1, minimum=20)
        doc.update(stopRule="x", reportTemplate="x", pins=mg.current_pins())
        return doc

    def load(self, doc):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.json"
            path.write_text(json.dumps(doc))
            return mg.load_preregistration(path)

    def test_the_committed_file_has_a_place_for_every_decision(self):
        """Holds for the draft and for the completed file, so completing it keeps CI green."""
        doc = json.loads(mg.PREREGISTRATION.read_text())
        for field in mg.HUMAN_FIELDS:
            head, _, tail = field.rpartition(".")
            self.assertIn(tail, mg._get(doc, head) if head else doc, field)

    def test_a_draft_is_refused_and_names_what_is_missing(self):
        doc = self.complete()
        doc["generator"]["seed"] = None
        with self.assertRaises(mg.PreregistrationError) as caught:
            self.load(doc)
        self.assertIn("generator.seed", str(caught.exception))

    def test_an_unknown_label_is_refused(self):
        doc = self.complete()
        doc["wrongFix"]["commentOnlyLabel"] = "maybe"
        with self.assertRaises(mg.PreregistrationError):
            self.load(doc)

    def test_one_missing_decision_is_enough(self):
        doc = self.complete()
        doc["oracle"]["frameThreshold"] = None
        with self.assertRaises(mg.PreregistrationError) as caught:
            self.load(doc)
        self.assertIn("oracle.frameThreshold", str(caught.exception))

    def test_zero_is_a_decision_not_a_gap(self):
        doc = self.complete()
        self.assertEqual(doc["oracle"]["frameThreshold"], 0)
        self.assertTrue(self.load(doc)["sha256"])

    def test_a_bad_sampling_plan_is_refused(self):
        doc = self.complete()
        doc["generator"]["sampling"] = {"method": "stratified", "perClass": {"numeric": 1}}
        with self.assertRaises(mg.PreregistrationError) as caught:
            self.load(doc)
        self.assertIn("adds up to", str(caught.exception))

    def test_moved_material_is_refused(self):
        doc = self.complete()
        doc["pins"] = dict(doc["pins"], **{"agents/verifier.py": "0" * 64})
        with self.assertRaises(mg.PreregistrationError) as caught:
            self.load(doc)
        self.assertIn("agents/verifier.py", str(caught.exception))

    def test_every_pin_is_a_file_or_tree_that_exists(self):
        for rel in mg.PINNED:
            self.assertTrue((REPO / rel).is_file(), rel)
        for rel in mg.PINNED_TREES:
            self.assertTrue((REPO / rel).is_dir(), rel)

    def test_everything_that_shapes_a_result_is_pinned(self):
        pins = mg.current_pins()
        for rel in ("agents/sam_observations.py", "agents/matrix.py", "agents/judge_bench.py", "agents/fixtures/operators",
                    "bugs/layering", ".github/workflows/mutation-bench.yml", "agents/mutate_game.py", "gameTree"):
            self.assertIn(rel, pins)

    def test_zayyads_files_are_not_pinned(self):
        self.assertFalse(any(k.startswith("bugs/reported") for k in mg.current_pins()))


class ManifestTest(unittest.TestCase):
    def write(self, doc, tmp):
        path = Path(tmp) / "manifest.json"
        path.write_text(json.dumps(doc))
        return path

    def test_the_generators_own_manifest_is_accepted(self):
        doc = json.loads(json.dumps(mg.build_manifest(prereg())))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(mg.load_manifest(prereg(), self.write(doc, tmp)), doc)

    def test_a_hand_edit_a_new_seed_or_a_dropped_mutant_is_refused(self):
        base = json.loads(json.dumps(mg.build_manifest(prereg())))
        edited = copy.deepcopy(base)
        edited["mutants"][0]["after"] = "z_index = 99"
        reseeded = dict(copy.deepcopy(base), seed=12)
        dropped = copy.deepcopy(base)
        dropped["mutants"].pop()
        with tempfile.TemporaryDirectory() as tmp:
            for doc in (edited, reseeded, dropped):
                with self.assertRaises(mg.PreregistrationError):
                    mg.load_manifest(prereg(), self.write(doc, tmp))


class OracleTest(unittest.TestCase):
    THRESHOLDS = {"traceThresholdPx": 2.0, "frameThreshold": 1}
    TRACE = {"rows": [{"tick": 0, "player": [10.0, 20.0], "facing": 1, "enemies": [[1, 5.0, 5.0]]}]}

    def verdict(self, trace, frames=("a", "b")):
        return mg.oracle(self.TRACE, ["a", "b"], trace, list(frames), self.THRESHOLDS)

    def moved(self, dx):
        doc = copy.deepcopy(self.TRACE)
        doc["rows"][0]["player"][0] += dx
        return doc

    def test_clean_against_clean_is_zero(self):
        out = self.verdict(self.TRACE)
        self.assertEqual((out["category"], out["traceMaxPx"], out["framesDiffering"]), ("equivalent", 0.0, 0))

    def test_the_trace_threshold_is_strict(self):
        self.assertEqual(self.verdict(self.moved(2.0))["category"], "equivalent")
        self.assertEqual(self.verdict(self.moved(2.01))["category"], "visible")

    def test_the_frame_threshold_is_strict(self):
        self.assertEqual(self.verdict(self.TRACE, ("a", "x"))["category"], "equivalent")
        self.assertEqual(self.verdict(self.TRACE, ("x", "y"))["category"], "visible")

    def test_a_frame_only_difference_counts(self):
        out = self.verdict(self.TRACE, ("x", "y"))
        self.assertEqual((out["traceMaxPx"], out["framesDiffering"]), (0.0, 2))

    def test_a_shorter_replay_counts(self):
        self.assertEqual(mg.frames_differing(["a", "b", "c"], ["a"]), 2)
        self.assertEqual(self.verdict({"rows": []})["category"], "visible")

    def test_things_that_differ_in_kind_are_always_visible(self):
        flipped = copy.deepcopy(self.TRACE)
        flipped["rows"][0]["facing"] = -1
        gone = copy.deepcopy(self.TRACE)
        gone["rows"][0]["enemies"] = []
        shot = copy.deepcopy(self.TRACE)
        shot["rows"][0]["projectiles"] = [[9, 1.0, 1.0]]
        for trace in (flipped, gone, shot):
            out = self.verdict(trace)
            self.assertTrue(out["traceDiffersInKind"])
            self.assertEqual(out["category"], "visible")

    def test_the_result_is_json_safe(self):
        self.assertIsNone(json.loads(json.dumps(self.verdict({"rows": []})))["traceMaxPx"])
        self.assertTrue(math.isinf(mg.trace_distance(self.TRACE, {"rows": []})))


if __name__ == "__main__":
    unittest.main()
