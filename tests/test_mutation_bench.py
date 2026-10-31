"""Mutation bench: only a check that ran and failed is a catch. The verifier runs for real here, with
only Godot and the SAM wire stubbed, because a mock of verify is how the old scoring passed its tests
while every SAM-off survivor would have been reported as a vision-only win."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agents.mutation_bench as mb
from agents import mutate_game
from agents import verifier
from harness.run import REPO, apply_patches

GOOD_CLEAN = {"clean": {"source": "harness"}}
ROWS = [{"tick": t, "frame": t, "player": [90.0 + 2 * t, 452.0], "onFloor": True, "facing": 1,
         "ground": 465.25, "view": [1, 0, 0, 1, 0, 0]} for t in range(240)]
TRACE = {"format": "expectrail.trace/v0", "physicsTicksPerSecond": 120, "rows": ROWS,
         "levelSurfaces": [[[-4000.0, 465.25], [4000.0, 465.25], [4000.0, 900.0], [-4000.0, 900.0]]]}


def prereg(**wrong_fix) -> dict:
    return {"sha256": "ab" * 32, "wrongFix": {"commentOnlyLabel": "good", **wrong_fix},
            "oracle": {"traceThresholdPx": 1.0, "frameThreshold": 0},
            "agreement": {"seed": 7, "minimum": 2}}


def fake_harness(route, out, patch=None, patches=None, **kwargs):
    """A replay without Godot: one PNG per frame, and the trace the real harness would write."""
    out = Path(out)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    (out / "trace.json").write_text(json.dumps(TRACE))
    (out / "replay.json").write_text(json.dumps({"frameSha256": ["00"] * 120}))
    return {}


def verification(*checks, decision="accept", suite=None) -> dict:
    return {"decision": decision, "reasons": [], "suite": suite if suite is not None else GOOD_CLEAN,
            "checks": [{"kind": k, "spec": s, "route": "smoke", "result": r} for k, s, r in checks]}


CHEAP_PASS = verification(("regression", "ground", "pass"), ("gameplay", "motion", "pass"), ("clean", "ground", "pass"),
                          ("held-out", "ground", "pass"))
SAM_PASS = verification(("regression", "ground", "pass"), ("regression", "player-always-visible", "pass"),
                        ("gameplay", "motion", "pass"), ("clean", "ground", "pass"),
                        ("held-out", "player-always-visible", "needs-review"), decision="needs-review")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        os.environ.pop(mb.HELDOUT_ENV, None)
        patcher = mock.patch("agents.mutation_bench.sam_health.check", return_value=None)
        self.check = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop(mb.HELDOUT_ENV, None)

    def run_pair(self, *answers, operator="hide", case="dev/sinking/v2", force=False):
        left = list(answers)

        def fake_verify(request, candidate, out, **kwargs):
            out.mkdir(parents=True, exist_ok=True)
            answer = left.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            return answer

        with mock.patch.object(mb, "verify", side_effect=fake_verify):
            return mb.run_case(case, operator, self.out, prereg=prereg(), force_sam=force)


class OperatorFixturesTest(unittest.TestCase):
    def test_every_operator_applies_to_the_clean_game(self):
        for name in mb.OPERATORS:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp) / "game"
                shutil.copytree(REPO / "game" / "platformer", work, ignore=shutil.ignore_patterns(".godot"))
                apply_patches(work, [mb.operator_path(name)])

    def test_pairs_cover_eight_cases_times_six_operators(self):
        pairs = mb.pairs()
        self.assertEqual(len(pairs), 8 * 6)
        self.assertEqual(len({c for c, _ in pairs}), 8)


class PublicDecisionTest(unittest.TestCase):
    def test_a_held_out_arm_decides_nothing(self):
        self.assertEqual(mb.public_decision(SAM_PASS), "accept")
        self.assertEqual(mb.public_decision(CHEAP_PASS), "accept")

    def test_only_a_failed_check_is_a_rejection(self):
        self.assertEqual(mb.public_decision(verification(("regression", "a", "fail"), ("gameplay", "b", "needs-review"))),
                         "reject")
        self.assertEqual(mb.public_decision(verification(("regression", "a", "needs-review"), ("gameplay", "b", "pass"))),
                         "needs-review")

    def test_a_held_out_failure_cannot_reject(self):
        self.assertEqual(mb.public_decision(verification(("regression", "a", "pass"), ("held-out", "b", "fail"))), "accept")

    def test_the_door_gate_is_not_a_catch(self):
        gate = verification(("regression", "editable-globs", "fail"), decision="reject",
                            suite={"earlyReject": {"gate": "editable-globs"}})
        self.assertEqual(mb.public_decision(gate), "needs-review")

    def test_a_clean_control_from_a_fixture_is_not_to_be_trusted(self):
        fallback = verification(("regression", "a", "fail"), suite={"clean": {"source": "fixture-fallback"}})
        self.assertEqual(mb.public_decision(fallback), "needs-review")

    def test_no_checks_is_never_an_accept(self):
        self.assertEqual(mb.public_decision(verification()), "needs-review")
        self.assertEqual(mb.public_decision(verification(("held-out", "a", "pass"))), "needs-review")


class RealVerifierTest(Base):
    """The Block: verify unmocked, SAM on, no private set, every check passing."""

    def run_real(self, sam_results, operator="hide"):
        def sam_checks(specs, kind, route, *args, **kwargs):
            return [{"spec": s["id"], "kind": kind, "route": route, "result": sam_results.get(s["id"], "pass"),
                     "verdictSha256": "0" * 64} for s in specs]

        with mock.patch("agents.verifier.harness_run", fake_harness), \
                mock.patch("agents.verifier.reference_surfaces", lambda out: TRACE["levelSurfaces"]), \
                mock.patch("agents.verifier._sam_checks", sam_checks), \
                mock.patch("agents.verifier._ground_observations", self.ground):
            return mb.run_case("dev/sinking/v2", operator, self.out, prereg=prereg())

    @staticmethod
    def ground(spec, trace, replay_sha, frames_dir, use_sam, reference):
        from agents.observations import from_trace_synthetic, with_reference_ground

        return from_trace_synthetic(with_reference_ground(trace, reference)), "engine"

    def test_a_survivor_is_a_finding_with_no_private_set(self):
        row = self.run_real({})
        self.assertEqual(row["arms"]["sam"]["verifierDecision"], "needs-review")  # the verifier is unchanged
        self.assertEqual(row["arms"]["sam"]["decision"], "accept")
        self.assertEqual((row["outcome"], row["finding"], row["caught"]), ("survived", True, None))

    def test_a_real_sam_failure_is_a_vision_only_win(self):
        row = self.run_real({"player-always-visible": "fail"})
        self.assertEqual((row["outcome"], row["caught"]), ("caught-sam", "sam-on"))

    def test_a_sam_outage_is_undecided_not_a_win(self):
        row = self.run_real({"player-always-visible": "needs-review"})
        self.assertEqual((row["outcome"], row["caught"], row["finding"]), ("undecided", None, False))


class OutcomeTest(Base):
    def test_cheap_rejection_is_final_and_spends_no_sam(self):
        row = self.run_pair(verification(("gameplay", "motion", "fail"), ("clean", "g", "pass"), decision="reject"))
        self.assertEqual((row["outcome"], row["caught"]), ("caught-cheap", "sam-off"))
        self.assertNotIn("sam", row["arms"])
        self.check.assert_not_called()

    def test_cheap_needs_review_is_never_caught_and_never_reaches_sam(self):
        row = self.run_pair(verification(("regression", "g", "needs-review"), ("clean", "g", "pass"),
                                         decision="needs-review"))
        self.assertEqual((row["outcome"], row["caught"], row["finding"]), ("undecided", None, False))
        self.assertNotIn("sam", row["arms"])

    def test_a_dead_sam_at_the_check_is_undecided_and_spends_nothing(self):
        self.check.return_value = {"kind": "credit", "error": "HTTP 402"}
        row = self.run_pair(CHEAP_PASS)
        self.assertEqual(row["outcome"], "undecided")
        self.assertIn("credit", row["undecidedWhy"])
        self.assertEqual(row["samPreflight"]["kind"], "credit")

    def test_a_crash_twice_is_the_cases_own_and_does_not_fail_the_job(self):
        boom = SystemExit("godot failed (134); see runs/x/sam-off/replay/godot.log")
        row = self.run_pair(boom, boom)
        self.assertEqual((row["outcome"], row["caught"], row["finding"]), ("crash", None, False))

    def test_a_flake_is_retried_and_recorded(self):
        row = self.run_pair(SystemExit("godot failed (134); see runs/x/sam-off/replay/godot.log"),
                            verification(("gameplay", "m", "fail"), ("clean", "g", "pass"), decision="reject"))
        self.assertEqual(row["outcome"], "caught-cheap")
        self.assertTrue(row["arms"]["cheap"]["retried"])

    def test_the_clean_games_crash_is_tooling_not_the_case(self):
        row = self.run_pair(SystemExit("godot failed (134); see runs/x/level-reference/replay/godot.log"))
        self.assertEqual(row["outcome"], "error")

    def test_a_patch_that_will_not_apply_is_tooling(self):
        row = self.run_pair(subprocess.CalledProcessError(1, ["patch"]))
        self.assertEqual(row["outcome"], "error")

    def test_a_tool_error_fails_the_job_and_a_crash_does_not(self):
        for outcome, code in (("error", 1), ("crash", 0), ("survived", 0), ("undecided", 0)):
            with self.subTest(outcome=outcome), mock.patch.object(mb, "run_case", return_value={"outcome": outcome}), \
                    mock.patch.object(mb.mutate_game, "load_preregistration", return_value=prereg()):
                self.assertEqual(mb.main(["--case", "dev/sinking/v1", "--operator", "hide", "--out", str(self.out)]), code)

    def test_every_case_ends_in_exactly_one_listed_outcome_and_writes_a_result(self):
        row = self.run_pair(CHEAP_PASS, SAM_PASS)
        self.assertIn(row["outcome"], mb.OUTCOMES)
        self.assertTrue((self.out / "dev_sinking_v2+hide" / "result.json").is_file())

    def test_a_survivor_gets_its_catch_spec(self):
        self.run_pair(CHEAP_PASS, SAM_PASS, operator="comment-only", case="dev/sinking/v1")
        work = self.out / "dev_sinking_v1+comment-only"
        self.assertEqual(json.loads((work / "finding.json").read_text())["catchSpec"]["id"], "comment-only-delta")
        self.assertEqual(json.loads((work / "catch-spec.json").read_text())["id"], "comment-only-delta")

    def test_comment_only_takes_its_label_from_the_pre_registration(self):
        row = self.run_pair(CHEAP_PASS, SAM_PASS, operator="comment-only", case="dev/sinking/v1")
        self.assertEqual(row["label"], "good")
        self.assertEqual(self.run_pair(CHEAP_PASS, SAM_PASS, operator="hide", case="dev/sinking/v1")["label"], "bad")

    def test_refuses_when_heldout_dir_is_set(self):
        os.environ[mb.HELDOUT_ENV] = "/tmp/private"
        with self.assertRaises(SystemExit) as ctx:
            mb.run_case("dev/sinking/v2", "hide", self.out, prereg=prereg())
        self.assertIn("public checks only", str(ctx.exception))

    def test_nothing_is_judged_before_the_pre_registration_is_complete(self):
        self.assertTrue(mutate_game.missing_decisions(json.loads(mutate_game.PREREGISTRATION.read_text())))
        with mock.patch.object(mb, "verify", side_effect=AssertionError("judged too early")):
            self.assertEqual(mb.main(["--case", "dev/sinking/v1", "--operator", "hide", "--out", str(self.out)]), 2)


class NoopTest(Base):
    def test_exactly_the_two_known_candidates_are_empty_and_every_pair_builds(self):
        empty = []
        for case, op in mb.pairs():
            cand = mb.build_candidate(mb.dev_variants()[case], mb.operator_path(op), self.out / "c.patch")
            if not cand.read_text().strip():
                empty.append((case, op))
        self.assertEqual(sorted(empty), [("dev/layering/v2", "behind-scenery"), ("dev/sinking/v2", "sink")])

    def test_an_empty_candidate_is_labelled(self):
        row = self.run_pair(verification(("regression", "g", "fail"), ("clean", "g", "pass"), decision="reject"),
                            operator="sink", case="dev/sinking/v2")
        self.assertTrue(row["noop"])

    def test_build_candidate_stacks_operator_on_undo(self):
        bug = mb.dev_variants()["dev/physics-fall-through/v1"]
        text = mb.build_candidate(bug, mb.operator_path("hide"), self.out / "c.patch").read_text()
        self.assertIn("player/", text)
        self.assertIn("visible = false", text)


class AgreementTest(Base):
    def rejected(self):
        return verification(("gameplay", "motion", "fail"), ("clean", "g", "pass"), decision="reject")

    def test_force_sam_asks_about_a_rejection_and_it_stays_a_cheap_catch(self):
        sam = verification(("regression", "player-always-visible", "fail"), ("gameplay", "motion", "fail"),
                           ("clean", "g", "pass"), decision="reject")
        row = self.run_pair(self.rejected(), sam, force=True)
        self.assertEqual((row["outcome"], row["agreement"]), ("caught-cheap", "agree"))

    def test_gameplay_alone_is_not_agreement(self):
        """Both arms share the gameplay check, so counting it would make every row agree."""
        sam = verification(("regression", "player-always-visible", "pass"), ("gameplay", "motion", "fail"),
                           ("clean", "g", "pass"), decision="reject")
        self.assertEqual(self.run_pair(self.rejected(), sam, force=True)["agreement"], "disagree")

    def test_undecided_vision_is_not_a_disagreement(self):
        sam = verification(("regression", "player-always-visible", "needs-review"), ("gameplay", "m", "fail"),
                           ("clean", "g", "pass"), decision="reject")
        self.assertEqual(self.run_pair(self.rejected(), sam, force=True)["agreement"], "undecided")

    def test_without_force_there_is_no_agreement_row(self):
        self.assertIsNone(self.run_pair(self.rejected()).get("agreement"))

    def test_a_dead_sam_keeps_the_cheap_catch_and_records_why(self):
        self.check.return_value = {"kind": "server", "error": "503"}
        row = self.run_pair(self.rejected(), force=True)
        self.assertEqual(row["outcome"], "caught-cheap")
        self.assertEqual(row["samPreflight"]["kind"], "server")
        self.assertIsNone(row.get("agreement"))


class MutantTest(Base):
    MANIFEST = {"mutants": [{"id": "code:enemy/enemy.gd:9:sign.WALK_SPEED", "class": "code", "file": "enemy/enemy.gd",
                             "line": 9, "before": "const WALK_SPEED = 22.0", "after": "const WALK_SPEED = -22.0"}]}
    ID = MANIFEST["mutants"][0]["id"]

    def run_mutant(self, frames=None, tier="cheap", answers=(), force=False, trace_extra=None):
        calls = []
        left = list(answers) or [CHEAP_PASS]

        def fake_verify(request, candidate, out, **kwargs):
            calls.append(request)
            out.mkdir(parents=True, exist_ok=True)
            return left.pop(0)

        def harness(route, out, patch=None, patches=None, **kwargs):
            fake_harness(route, out)
            if patches:
                Path(out, "replay.json").write_text(json.dumps({"frameSha256": frames or ["00"] * 120}))
                if trace_extra:
                    Path(out, "trace.json").write_text(json.dumps(trace_extra))

        with mock.patch.object(mb, "verify", side_effect=fake_verify), mock.patch.object(mb, "harness_run", harness):
            row = mb.run_mutant(self.ID, tier, self.out, prereg=prereg(), manifest=self.MANIFEST, force_sam=force)
        return row, calls

    def test_a_mutant_outside_the_editable_files_is_the_seed_never_the_candidate(self):
        row, calls = self.run_mutant(frames=["11"] * 120)
        request = calls[0]
        self.assertTrue(request["base"]["patch"].endswith("mutant.patch"))
        self.assertFalse(mb.mutate_game.CODE_FILES[1] in request["editable"])
        work = self.out / mb._safe(self.ID)
        self.assertEqual((work / "empty.patch").read_text(), "")
        self.assertEqual(row["outcome"], "awaiting-sam")

    def test_no_visible_difference_is_dropped_with_its_reason_and_never_judged(self):
        row, calls = self.run_mutant()
        self.assertEqual(calls, [])
        self.assertEqual(row["outcome"], "equivalent")
        self.assertIn("smoke route", row["dropReason"])

    def test_the_cheap_phase_never_spends_sam(self):
        self.run_mutant(frames=["11"] * 120)
        self.check.assert_not_called()

    def test_the_sam_phase_stands_alone_in_a_new_job(self):
        row, _ = self.run_mutant(frames=["11"] * 120, tier="sam", answers=[CHEAP_PASS, SAM_PASS])
        self.assertEqual(row["outcome"], "survived")

    def test_an_engine_record_failure_is_a_cheap_catch(self):
        bad = dict(TRACE, rows=[dict(r, enemies=[[1, 10.0, 100.0 + r["tick"]]]) for r in ROWS])
        row, _ = self.run_mutant(frames=["11"] * 120, trace_extra=bad)
        self.assertEqual(row["engineRecord"]["enemies-stay-up"], "fail")
        self.assertEqual(row["outcome"], "caught-cheap")

    def test_a_mutant_that_crashes_twice_is_its_own_category(self):
        def harness(route, out, patch=None, patches=None, **kwargs):
            if patches:
                raise SystemExit("godot failed (134); see x/mutant/godot.log")
            fake_harness(route, out)

        with mock.patch.object(mb, "harness_run", harness):
            row = mb.run_mutant(self.ID, "cheap", self.out, prereg=prereg(), manifest=self.MANIFEST)
        self.assertEqual(row["outcome"], "crash")


class SummaryTest(Base):
    def write(self, name, **row):
        d = self.out / name
        d.mkdir()
        (d / "result.json").write_text(json.dumps({"format": mb.FORMAT, "label": "bad", **row}))

    def test_denominators_reconcile_and_undecided_is_outside_the_score(self):
        for i, outcome in enumerate(("caught-cheap", "caught-sam", "survived", "undecided", "crash", "error")):
            self.write(f"r{i}", case=f"c{i}", operator="hide", outcome=outcome)
        doc = mb.summarize(self.out)
        self.assertEqual(sum(doc[o] for o in mb.OUTCOMES), doc["cases"])
        self.assertEqual((doc["badCaught"], doc["badSurvived"], doc["score"]), (2, 1, round(2 / 3, 4)))
        self.assertEqual(doc["byOperator"]["hide"]["cases"], 6)

    def test_a_good_fix_is_outside_the_score_and_a_rejection_of_it_is_a_false_reject(self):
        self.write("a", case="c", operator="comment-only", outcome="caught-cheap", label="good")
        doc = mb.summarize(self.out)
        self.assertIsNone(doc["score"])
        self.assertEqual(doc["falseRejects"], ["c comment-only"])

    def test_the_agreement_table_lists_every_disagreement(self):
        self.write("a", id="m1", outcome="caught-cheap", agreement="agree")
        self.write("b", id="m2", outcome="caught-cheap", agreement="disagree")
        self.write("c", id="m3", outcome="caught-cheap", agreement="undecided")
        a = mb.summarize(self.out)["agreement"]
        self.assertEqual((a["checked"], a["agree"], a["disagree"], a["undecided"]), (3, 1, 1, 1))
        self.assertEqual(a["disagreements"], ["m2"])

    def test_a_mutant_judged_in_both_phases_counts_once(self):
        self.write("a", kind="mutant", id="m", tier="cheap", outcome="awaiting-sam")
        self.write("b", kind="mutant", id="m", tier="sam", outcome="caught-sam")
        doc = mb.summarize(self.out)
        self.assertEqual((doc["cases"], doc["caught-sam"], doc["awaitingSam"]), (1, 1, 0))

    def test_equivalents_are_listed_with_reasons_and_outside_the_cases(self):
        self.write("a", kind="mutant", id="m", outcome="equivalent", dropReason="no difference")
        doc = mb.summarize(self.out)
        self.assertEqual(doc["cases"], 0)
        self.assertEqual(doc["equivalentDropped"], [{"id": "m", "reason": "no difference"}])

    def test_sam_images_are_split_by_why_they_were_spent(self):
        self.write("a", id="m1", outcome="caught-sam", samImages=100, arms={"sam": {"samImages": 100}})
        self.write("b", id="m2", outcome="caught-cheap", agreement="agree", samImages=40, arms={"sam": {"samImages": 40}})
        s = mb.summarize(self.out)["samImages"]
        self.assertEqual((s["spent"], s["tiered"], s["agreementOnly"]), (140, 100, 40))

    def test_the_report_renders(self):
        self.write("a", case="c", operator="hide", outcome="survived")
        text = mb.markdown(mb.summarize(self.out))
        self.assertIn("Mutation score", text)
        self.assertIn("## Blind spots", text)

    def test_plan_sam_takes_every_survivor_and_a_seeded_sample_of_rejections(self):
        for i in range(5):
            self.write(f"c{i}", kind="mutant", id=f"caught{i}", outcome="caught-cheap")
        self.write("s", kind="mutant", id="left", outcome="awaiting-sam")
        first = mb.plan_sam(self.out, prereg())
        self.assertEqual(first["survivors"], ["left"])
        self.assertEqual(len(first["agreement"]), 2)
        self.assertEqual(first, mb.plan_sam(self.out, prereg()))


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        import yaml

        self.doc = yaml.safe_load((REPO / ".github" / "workflows" / "mutation-bench.yml").read_text(encoding="utf-8"))

    def test_every_render_job_installs_a_display(self):
        for job in ("run", "sam-warm"):
            steps = " ".join(str(s.get("run", "")) for s in self.doc["jobs"][job]["steps"])
            with self.subTest(job=job):
                self.assertIn("xvfb", steps)
                self.assertIn("libgl1-mesa-dri", steps)

    def test_the_private_set_is_never_checked_out(self):
        text = str(self.doc)
        self.assertNotIn("Nightshift-heldout", text)
        self.assertNotIn("HELDOUT_TOKEN", text)

    def test_the_plan_refuses_an_incomplete_pre_registration(self):
        self.assertIn("load_preregistration", str(self.doc["jobs"]["plan"]["steps"]))

    def test_the_cheap_phase_holds_no_key(self):
        self.assertIn("generated-cheap", self.doc["jobs"]["run"]["env"]["MODEL_API_KEY"])

    def test_results_keep_the_trace(self):
        self.assertIn("trace.json", str(self.doc["jobs"]["run"]["steps"]))


if __name__ == "__main__":
    unittest.main()
