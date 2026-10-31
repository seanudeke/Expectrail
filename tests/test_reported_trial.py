"""The natural-catch trial: cases, the guard commitment, the three judgments, and what is kept public."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agents.bench_collect as bc
import agents.matrix as matrix
import agents.reported_trial as rt
from agents import trace_checks
from harness.run import REPO

GROUND = 637.0
GUARDS = {"format": rt.GUARDS_FORMAT, "guards": {
    "air-jump": [{"id": "air-jump-g1", "kind": "rises-at-least", "minPx": 160, "why": "SECRET REASON"}]}}


def trace(rise: float) -> dict:
    """Walks right, rises `rise` px once, lands; three patrolling enemies; no shots."""
    rows = []
    for t in range(400):
        y = GROUND - (rise * (1 - abs(t - 200) / 40) if 160 < t < 240 else 0)
        rows.append({"tick": t, "player": [100 + t, y], "onFloor": not 160 < t < 240, "facing": 1,
                     "enemies": [[i, 500 + i * 100 + (t % 200), 300 + 100 * i] for i in range(3)]})
    return {"physicsTicksPerSecond": 120, "rows": rows}


class GuardFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "reported").mkdir()
        self.path = self.root / rt.GUARDS_FILE
        self.path.write_text(json.dumps(GUARDS))
        self.commit = self.root / "guards.sha256"
        self.commit.write_text("# comment\n" + hashlib.sha256(self.path.read_bytes()).hexdigest() + "  x\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_committed_guard_file_loads(self):
        with mock.patch.object(rt, "COMMITMENT", self.commit):
            doc, sha = rt.load_guards(self.root)
        self.assertEqual(doc["guards"]["air-jump"][0]["id"], "air-jump-g1")
        self.assertEqual(sha, hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_a_guard_changed_after_the_commitment_is_refused(self):
        self.path.write_text(json.dumps({**GUARDS, "note": "edited"}))
        with mock.patch.object(rt, "COMMITMENT", self.commit), self.assertRaises(SystemExit):
            rt.load_guards(self.root)

    def test_an_unknown_guard_kind_is_refused(self):
        bad = {"format": rt.GUARDS_FORMAT, "guards": {"air-jump": [{"id": "g", "kind": "made-up"}]}}
        self.path.write_text(json.dumps(bad))
        self.commit.write_text(hashlib.sha256(self.path.read_bytes()).hexdigest() + "\n")
        with mock.patch.object(rt, "COMMITMENT", self.commit), self.assertRaises(SystemExit):
            rt.load_guards(self.root)

    def test_without_the_held_out_set_there_are_no_guards(self):
        with mock.patch.object(rt, "held_out_set", lambda: (None, None, None)), self.assertRaises(SystemExit):
            rt.load_guards()

    def test_the_repository_commits_a_digest(self):
        self.assertRegex(rt.committed_digest(), r"^[0-9a-f]{64}$")


class CasesTest(unittest.TestCase):
    def test_five_repeats_of_every_reported_bug(self):
        ids = rt.case_ids()
        self.assertEqual(len(ids), 5 * len(rt.load_manifest()["variants"]))
        variant, route, repeat = rt.parse_case("reported/air-jump/r3")
        self.assertEqual((variant["id"], route["name"], repeat), ("air-jump", "climb-gap", 3))
        for bad in ("reported/air-jump", "reported/nope/r1", "dev/sinking/v1", "reported/air-jump/x1"):
            with self.assertRaises(SystemExit):
                rt.parse_case(bad)

    def test_the_matrix_lists_the_trial_and_runs_it_under_its_own_condition(self):
        with mock.patch("builtins.print") as out:
            self.assertEqual(matrix.main(["--list", "--set", "reported"]), 0)
        self.assertEqual(json.loads(out.call_args[0][0]), rt.case_ids())
        with self.assertRaises(SystemExit):
            matrix.run_case("reported/air-jump/r1", "screenshots", Path("/tmp/unused"), live=False)


class ChecksTest(unittest.TestCase):
    def test_spaced_frames_span_the_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(300):
                (Path(tmp) / f"f{i:08d}.png").write_bytes(b"")
            picked = [p.stem for p in rt.spaced_frames(Path(tmp))]
        self.assertEqual(picked[0], "f00000000")
        self.assertEqual(picked[-1], "f00000299")
        self.assertEqual(len(picked), rt.SHOTS)

    def test_route_checks_mark_the_public_check_and_the_guards(self):
        variant, route, _ = rt.parse_case("reported/air-jump/r1")
        guards = GUARDS["guards"]["air-jump"]
        flying = {c["name"]: c for c in rt.route_checks(trace(480), {**route, "minDeltaX": 100}, variant, guards)}
        self.assertEqual(flying["jump-height"]["kind"], "public")
        self.assertEqual(flying["jump-height"]["result"], "fail")
        self.assertEqual(flying["air-jump-g1"]["kind"], "guard")
        self.assertEqual(flying["air-jump-g1"]["result"], "pass")
        grounded = {c["name"]: c for c in rt.route_checks(trace(120), {**route, "minDeltaX": 100}, variant, guards)}
        self.assertEqual(grounded["jump-height"]["result"], "pass")
        self.assertEqual(grounded["air-jump-g1"]["result"], "fail")  # the double jump is gone
        missing = rt.route_checks(None, route, variant, guards)
        self.assertTrue(all(c["result"] == "needs-review" for c in missing))
        self.assertEqual(len(missing), len(trace_checks.CHECKS) + 2)

    def test_combine_follows_the_verifier_rule(self):
        accept = {"decision": "accept", "checks": [{"result": "pass"}]}
        self.assertEqual(rt.combine(accept, [{"result": "pass"}]), "accept")
        self.assertEqual(rt.combine(accept, [{"result": "fail"}]), "reject")
        self.assertEqual(rt.combine(accept, [{"result": "needs-review"}]), "needs-review")
        self.assertEqual(rt.combine({"decision": "reject", "checks": [{"result": "fail"}]}, [{"result": "pass"}]),
                         "reject")

    def test_the_briefing_carries_the_reporters_words_and_no_check(self):
        variant, route, _ = rt.parse_case("reported/air-jump/r1")
        with tempfile.TemporaryDirectory() as tmp:
            bugged = Path(tmp)
            (bugged / "frames").mkdir()
            for i in range(20):
                (bugged / "frames" / f"f{i:08d}.png").write_bytes(b"")
            b = rt.briefing(variant, REPO / "bugs" / "reported" / route["file"], bugged, 2, True)
        self.assertIn(variant["report"], b["prompt"])
        self.assertIn("did not fix the bug", b["prompt"])
        for word in ("jump-height", "guard", "double jump", "air-jump", "trace"):
            self.assertNotIn(word, b["prompt"])
        self.assertFalse(b["withRequest"])
        self.assertTrue(all(k.startswith(rt.BRIEFING_DIR + "/") for k in b["files"]))
        self.assertIn("enemy/**", b["prompt"])


class RunTrialTest(unittest.TestCase):
    """The whole loop with the harness, the verifier, the fixer and the judge replaced."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.rises = []

        def replay(route, out, patches):
            out.mkdir(parents=True, exist_ok=True)
            (out / "frames").mkdir(exist_ok=True)
            (out / "frames" / "f00000000.png").write_bytes(b"")
            if not patches:
                return trace(188)
            if len(patches) == 1:
                return trace(480)  # the bug
            return trace(self.rises.pop(0))

        def fixer(request, out, *, candidate_patch=None, **kwargs):
            out.mkdir(parents=True, exist_ok=True)
            (out / "candidate.patch").write_text("--- a/player/player.gd\n+++ b/player/player.gd\n")
            return {"source": "muse", "patchSha256": "0" * 64}

        patches = [mock.patch.object(rt, "_replay", replay),
                   mock.patch.object(rt, "verify", lambda *a, **k: {"decision": "accept", "checks": [
                       {"kind": "regression", "spec": "player-stays-above-ground", "result": "pass"}]}),
                   mock.patch.object(rt, "run_fixer", fixer),
                   mock.patch.object(rt, "load_guards", lambda root=None: (GUARDS, "a" * 64)),
                   mock.patch.object(rt, "sam_on", lambda: False)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def judge(self, decision):
        return lambda out, **kwargs: {"decision": decision}

    def test_a_fix_that_deletes_the_double_jump_is_a_natural_catch_then_the_real_fix_is_accepted(self):
        self.rises = [120, 188]  # attempt 1 jumps once only; attempt 2 keeps the double jump
        row = rt.run_trial("reported/air-jump/r1", self.out, live=True, judge=self.judge("accept"))
        self.assertEqual(row["detected"], "fail")
        self.assertEqual(row["cleanRoute"], "pass")
        first, second = row["attempts"]
        self.assertEqual((first["decision"], first["publicCheck"], first["museScreenshots"]),
                         ("reject", "pass", "accept"))
        self.assertTrue(first["naturalCatch"])
        self.assertEqual(first["failing"], ["guard:air-jump-g1"])
        self.assertEqual(second["decision"], "accept")
        self.assertFalse(second["naturalCatch"])
        self.assertEqual((row["outcome"], row["naturalCatches"]), ("fixed", 1))

    def test_guard_reasons_stay_private(self):
        self.rises = [120, 188]
        rt.run_trial("reported/air-jump/r1", self.out, live=True, judge=self.judge("accept"))
        work = self.out / "reported_air-jump_r1" / "report"
        public = (work / "result.json").read_text()
        private = (work / "result-private.json").read_text()
        self.assertNotIn("never rose more than", public)
        self.assertIn("never rose more than", private)
        self.assertNotIn("SECRET REASON", public + private)
        lines = rt.annotation(json.loads(public)).splitlines()
        self.assertEqual(len(lines), 2)
        self.assertNotIn("never rose", "".join(lines))

    def test_a_rejection_nobody_else_would_make_is_not_a_natural_catch(self):
        self.rises = [480, 480, 480]  # the bug is still there: everyone rejects
        row = rt.run_trial("reported/air-jump/r1", self.out, live=True, judge=self.judge("reject"))
        self.assertEqual(row["outcome"], "not-fixed")
        self.assertEqual(row["naturalCatches"], 0)
        self.assertTrue(all(a["publicCheck"] == "fail" for a in row["attempts"]))

    def test_a_crash_is_an_error_never_a_fix(self):
        with mock.patch.object(rt, "load_guards", side_effect=SystemExit("guards unavailable")):
            row = rt.run_trial("reported/air-jump/r1", self.out, live=True)
        self.assertEqual(row["outcome"], "error")
        self.assertIn("guards unavailable", row["detail"])


def trial_fetch(path):
    if path.endswith("/actions/runs/5"):
        return {"html_url": "https://github.com/x/runs/5", "head_sha": "abc1234", "created_at": "2026-10-31T01:00:00Z"}
    if "/jobs" in path:
        return {"jobs": [{"id": 1, "name": "run (reported/air-jump/r1, report)"},
                         {"id": 2, "name": "run (reported/body-flip/r1, report)"}, {"id": 3, "name": "plan"}]}
    job = int(path.split("/")[-2])
    if job == 1:
        return [{"title": "Fix matrix reported/air-jump/r1 report",
                 "message": "detected fail; outcome fixed; attempts 2 (1: reject; 2: accept); 900.5 s; live=True"},
                {"title": "Reported trial reported/air-jump/r1 attempt 1",
                 "message": "expectrail reject; public check pass; muse screenshots accept; natural catch True; "
                            "failing guard:air-jump-g1"},
                {"title": "Reported trial reported/air-jump/r1 attempt 2",
                 "message": "expectrail accept; public check pass; muse screenshots accept; natural catch False; "
                            "failing none"},
                {"title": "Reported trial reported/air-jump/r1 attempt 2",  # listed twice by the API
                 "message": "expectrail accept; public check pass; muse screenshots accept; natural catch False; "
                            "failing none"}]
    if job == 2:
        return [{"title": "Fix matrix reported/body-flip/r1 report",
                 "message": "detected fail; outcome fixed; attempts 1 (1: accept); 600.0 s; live=True"},
                {"title": "Reported trial reported/body-flip/r1 attempt 1",
                 "message": "expectrail accept; public check pass; muse screenshots None; natural catch False; "
                            "failing none"}]
    raise AssertionError(path)


class CollectTrialTest(unittest.TestCase):
    def test_collect_and_markdown(self):
        doc = bc.collect_trial([5], fetch=trial_fetch)
        self.assertEqual((doc["naturalCatches"], doc["candidates"]), (1, 3))
        self.assertEqual(doc["bugs"]["air-jump"]["naturalCatches"], 1)
        self.assertEqual(doc["bugs"]["air-jump"]["museAccepts"], 2)
        self.assertIsNone(doc["rows"][1]["candidates"][0]["museScreenshots"])
        md = bc.trial_markdown(doc)
        self.assertIn("**Natural catches: 1 of 3 candidates.**", md)
        self.assertIn("| reported/air-jump/r1 | 1 | reject (natural catch) | pass | accept | guard:air-jump-g1 |", md)

    def test_offline_trials_are_refused(self):
        def offline(path):
            notes = trial_fetch(path)
            if isinstance(notes, list):
                return [dict(n, message=n["message"].replace("live=True", "live=False")) for n in notes]
            return notes

        with self.assertRaises(SystemExit):
            bc.collect_trial([5], fetch=offline)


class WorkflowTest(unittest.TestCase):
    def test_the_fix_matrix_runs_the_reported_set_with_sam_off_and_keeps_no_guard_reason(self):
        yml = (REPO / ".github" / "workflows" / "fix-matrix.yml").read_text()
        self.assertIn("options: [dev, held-out, reported]", yml)
        self.assertIn("python -m agents.reported_trial --annotate", yml)
        self.assertIn("inputs.set != 'reported' && 'sam' || 'trace'", yml)
        self.assertNotIn("result-private.json \\", yml)


if __name__ == "__main__":
    unittest.main()
