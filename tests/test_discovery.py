"""Advisory discovery: the route compiler, the probe library, the template factory, the planner, and
one whole job on a small simulated platformer (no Godot)."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from expectrail.contracts import load_strict, validate_v1
from expectrail.discovery import cli
from expectrail.discovery import planner as planner_mod
from expectrail.discovery.probes import library, pairs
from expectrail.discovery.route_compiler import MAX_TICKS, ProgramError, compile_route
from expectrail.discovery.run import discover
from expectrail.discovery.templates import applies_to, instantiate

REPO = Path(__file__).resolve().parents[1]
PROFILE = REPO / "discovery" / "platformer.profile.json"
ACTIONS = ["move_left", "move_right", "jump", "shoot"]


def tap(action, d=4):
    return {"op": "tap", "action": action, "durationTicks": d}


class RouteCompiler(unittest.TestCase):
    def test_exact_schedule(self):
        route = compile_route({"op": "sequence", "steps": [tap("jump"), {"op": "wait", "durationTicks": 6},
                                                           {"op": "hold", "action": "move_right", "durationTicks": 30}]},
                              name="p", description="d", actions=ACTIONS)
        self.assertEqual(route["events"], [{"tick": 10, "action": "jump", "pressed": True},
                                           {"tick": 14, "action": "jump", "pressed": False},
                                           {"tick": 20, "action": "move_right", "pressed": True},
                                           {"tick": 50, "action": "move_right", "pressed": False}])
        self.assertEqual(route["ticks"], 110)

    def test_parallel_and_repeat(self):
        program = {"op": "parallel", "branches": [
            {"op": "hold", "action": "move_right", "durationTicks": 50},
            {"op": "repeat", "count": 3, "body": {"op": "sequence", "steps": [tap("shoot"),
                                                                             {"op": "wait", "durationTicks": 8}]}}]}
        route = compile_route(program, name="p", description="d", actions=ACTIONS)
        presses = [e["tick"] for e in route["events"] if e["action"] == "shoot" and e["pressed"]]
        self.assertEqual(presses, [10, 22, 34])
        self.assertEqual(route["ticks"], 60 + 60)

    def test_refusals(self):
        bad = [
            tap("fly"),                                                       # not in the catalog
            {"op": "tap", "action": "jump", "durationTicks": 0},              # non-positive
            {"op": "tap", "action": "jump", "durationTicks": 4, "x": 1},      # extra field
            {"op": "eval", "src": "1"},                                       # unknown instruction
            {"op": "sequence", "steps": [tap("jump"), tap("jump")]},          # released and pressed on one tick
            {"op": "parallel", "branches": [tap("jump"), tap("jump")]},       # both branches drive jump
            {"op": "repeat", "count": 33, "body": tap("jump")},              # over the repeat cap
            {"op": "wait", "durationTicks": MAX_TICKS},                       # over the tick cap
            {"op": "sequence", "steps": [{"op": "sequence", "steps": [{"op": "sequence", "steps": [
                {"op": "sequence", "steps": [tap("jump")]}]}]}]},             # nesting
        ]
        for program in bad:
            with self.subTest(program=program), self.assertRaises(ProgramError):
                compile_route(program, name="p", description="d", actions=ACTIONS)


class Library(unittest.TestCase):
    def test_every_probe_compiles_and_twins_exist(self):
        probes = library(ACTIONS)
        self.assertEqual(len(probes), 22)
        for p in probes:
            compile_route(p["program"], name=p["id"], description=p["description"], actions=ACTIONS)
        twins = pairs(probes)
        self.assertEqual(len(twins["extra-air-presses"]), 4)
        self.assertEqual(twins["faster-taps"], [("shoot-right-every48", "shoot-right-every12"),
                                                ("shoot-left-every48", "shoot-left-every12")])

    def test_library_follows_the_catalog(self):
        ids = {p["id"] for p in library(["move_left", "move_right"])}
        self.assertEqual(ids, {"wait-long", "hold-right", "hold-left", "reverse"})

    def test_templates_are_advisory_until_approved(self):
        profile = load_strict(PROFILE, "mechanics-profile")
        probes = library(profile["actions"])
        entries = instantiate(profile, probes)
        self.assertTrue(entries)
        self.assertFalse(any(e["approved"] for e in entries))
        for e in entries:
            validate_v1(e["spec"], "trace-spec")
        drop = next(e for e in entries if e["spec"]["id"] == "enemy-max-drop")
        shooting = next(p for p in probes if p["id"] == "shoot-right-every12")
        self.assertFalse(applies_to(drop, shooting))  # bullets kill enemies: no drop rule while shooting


# --- a small simulated platformer -----------------------------------------------------------------

TPS = 120


class FakeGame:
    """Enough of the platformer for every template: walking, jumping, a gun with a cooldown, enemies.

    Patches are recognized by file name: air-jump (unlimited air jumps), gun-cooldown (no cooldown),
    body-flip (the sprite faces the wrong way), enemy-ledge (one enemy falls), flaky-air-jump
    (unlimited air jumps on the first replay of each route only), crash (the runner fails).
    """

    def __init__(self):
        self.calls: dict[str, int] = {}

    def __call__(self, route_path, run_dir, patches=()):
        bugs = {Path(p).stem for p in patches}
        route = json.loads(Path(route_path).read_text())
        n = self.calls[route["name"] + str(sorted(bugs))] = self.calls.get(route["name"] + str(sorted(bugs)), 0) + 1
        if "crash" in bugs:
            raise RuntimeError("godot exited with code 1")
        if "flaky-air-jump" in bugs and n == 1:
            bugs.add("air-jump")
        by_tick: dict[int, list] = {}
        for e in route["events"]:
            by_tick.setdefault(e["tick"], []).append(e)
        held, x, y, vy, floor, air, facing, cool = set(), 100.0, 600.0, 0.0, True, 1, 1, 0
        bullets, next_id, rows = {}, 100, []
        for t in range(route["ticks"]):
            pressed = set()
            for e in by_tick.get(t, []):
                (held.add if e["pressed"] else held.discard)(e["action"])
                if e["pressed"]:
                    pressed.add(e["action"])
            move = ("move_right" in held) - ("move_left" in held)
            x += move * 250 / TPS
            if move:
                facing = -move if "body-flip" in bugs else move
            if "jump" in pressed and (floor or air > 0 or "air-jump" in bugs):
                if not floor:
                    air -= 1
                vy, floor = -725.0, False
            if not floor:
                vy += 2100 / TPS
                y += vy / TPS
                if y >= 600.0:
                    y, vy, floor, air = 600.0, 0.0, True, 1
            cool = max(0, cool - 1)
            if "shoot" in pressed and cool == 0:
                bullets[next_id] = [x, y - 10, facing * 600 / TPS, 0]
                next_id += 1
                cool = 0 if "gun-cooldown" in bugs else 36
            for b in list(bullets):
                bullets[b][0] += bullets[b][2]
                bullets[b][3] += 1
                if bullets[b][3] > 60:
                    del bullets[b]
            phase = (t * 22 / TPS) % 220
            ex = phase if phase <= 110 else 220 - phase
            enemies = [[i, 400.0 + 200 * i + ex, 500.0 + (150 if ("enemy-ledge" in bugs and i == 2 and t > 300)
                                                          else 0)] for i in (1, 2, 3)]
            rows.append({"tick": t, "player": [round(x, 3), round(y, 3)], "onFloor": floor, "facing": facing,
                         "enemies": enemies, "projectiles": [[b, round(v[0], 3), round(v[1], 3)]
                                                             for b, v in sorted(bullets.items())]})
        run_dir = Path(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        caps = {"enemies": "initial-instances", "projectiles": "complete", "facing": True, "onFloor": True}
        (run_dir / "trace.json").write_text(json.dumps({"physicsTicksPerSecond": TPS, "capabilities": caps,
                                                        "rows": rows}))
        (run_dir / "replay.json").write_text(json.dumps({"capture": {"fps": 60}}))


def snaps(tmp, *bases, reference=True):
    out = [{"name": "clean", "role": "reference", "patch": None}] if reference else []
    for name in bases:
        p = Path(tmp) / f"{name}.patch"
        p.write_text(f"fake patch {name}\n")
        out.append({"name": name, "role": "base", "patch": p})
    return out


class Job(unittest.TestCase):
    def run_job(self, *bases, **kw):
        tmp = tempfile.mkdtemp()
        doc = discover(PROFILE, snaps(tmp, *bases, reference=kw.pop("reference", True)), Path(tmp) / "out",
                       runner=FakeGame(), **kw)
        validate_v1(json.loads((Path(tmp) / "out" / "discovery-run.json").read_text()), "discovery-run")
        return doc

    def test_the_healthy_game_has_no_findings_and_no_rejections(self):
        doc = self.run_job()
        self.assertEqual(doc["findings"], [])
        self.assertFalse([c for c in doc["candidates"] if c["lifecycle"] == "rejected"])
        self.assertEqual(doc["completion"], "complete")
        self.assertEqual(doc["coverage"]["clean"]["results"]["fail"], 0)

    def test_each_seeded_defect_is_found_and_reproduced(self):
        doc = self.run_job("air-jump", "gun-cooldown", "body-flip", "enemy-ledge")
        found = {(f["snapshot"], f["specId"]) for f in doc["findings"] if f["lifecycle"] == "reproduced"}
        self.assertIn(("air-jump", "jump-max-rise"), found)
        self.assertIn(("gun-cooldown", "weapon-min-interval"), found)
        self.assertIn(("body-flip", "facing-follows-motion"), found)
        self.assertIn(("enemy-ledge", "enemy-max-drop"), found)
        for f in doc["findings"]:
            self.assertEqual(f["reproduction"], {"runs": 3, "failures": 3})
        # Each finding stays on its own build.
        self.assertFalse({s for s, sid in found if sid.startswith("jump")} - {"air-jump"})

    def test_flaky_failure_is_a_candidate_not_a_finding(self):
        doc = self.run_job("flaky-air-jump", probe_ids=["jump-w0-x1", "jump-w0-x2", "jump-w0-x8"])
        rise = next(f for f in doc["findings"] if f["specId"] == "jump-max-rise")
        self.assertEqual(rise["lifecycle"], "flaky_candidate")
        self.assertEqual(rise["reproduction"], {"runs": 3, "failures": 1})

    def test_a_contract_that_fails_on_the_reference_is_rejected(self):
        tmp = tempfile.mkdtemp()
        profile = json.loads(PROFILE.read_text())
        jump = next(c for c in profile["claims"] if c["claimId"] == "player.jump")
        jump["parameters"]["jumpVelocity"]["value"] = 400  # a miscalibrated claim
        path = Path(tmp) / "p.json"
        path.write_text(json.dumps(profile))
        doc = discover(path, snaps(tmp, "air-jump"), Path(tmp) / "out", runner=FakeGame(),
                       probe_ids=["jump-w0-x1", "jump-w0-x2", "jump-w0-x8"])
        rejected = {c["specId"] for c in doc["candidates"] if c["lifecycle"] == "rejected"}
        self.assertIn("jump-max-rise", rejected)
        self.assertNotIn("jump-max-rise", {f["specId"] for f in doc["findings"]})

    def test_without_a_reference_nothing_is_falsified(self):
        doc = self.run_job("air-jump", reference=False, probe_ids=["jump-w0-x2", "jump-w0-x8"])
        self.assertEqual(next(s for s in doc["stages"] if s["name"] == "reference check")["status"], "skipped")
        self.assertTrue(doc["findings"])
        self.assertIsNone(doc["candidates"][0]["referenceResult"])

    def test_runner_failure_is_recorded_never_a_pass(self):
        doc = self.run_job("crash", probe_ids=["hold-right"])
        self.assertEqual(doc["coverage"]["crash"]["episodes"], 0)
        self.assertEqual(doc["coverage"]["crash"]["results"]["pass"], 0)
        self.assertTrue(any("godot exited" in d for d in doc["diagnostics"]))

    def test_report_renders_findings_and_rejections(self):
        tmp = tempfile.mkdtemp()
        discover(PROFILE, snaps(tmp, "air-jump"), Path(tmp) / "out", runner=FakeGame(),
                 probe_ids=["jump-w0-x1", "jump-w0-x2", "jump-w0-x8"])
        out = Path(tmp) / "report.md"
        self.assertEqual(cli.main(["report", str(Path(tmp) / "out" / "discovery-run.json"), "--out", str(out)]), 0)
        text = out.read_text()
        self.assertIn("| air-jump | `jump-no-extra-air-jumps-jump-w0-x8` (inferred_code) |", text)
        self.assertIn("3/3 (reproduced)", text)
        self.assertIn("development-reproduction", text)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["discover", "--profile", str(PROFILE), "--snapshot", "clean:healthy", "--out", tmp])

    def test_annotations_round_trip_through_the_collector(self):
        tmp = tempfile.mkdtemp()
        notes = []
        for name, ref in (("clean", False), ("air-jump", False)):
            doc = discover(PROFILE, snaps(tmp, name, reference=ref), Path(tmp) / name, runner=FakeGame(),
                           probe_ids=["jump-w0-x1", "jump-w0-x2", "jump-w0-x8"])
            title, _, message = cli.annotation(doc).partition("::")[2].partition("::")
            notes.append({"title": title.removeprefix("notice title="), "message": message})
        notes[0:0] = [{"title": "Discovery time clean", "message": "123 s"}]

        def fetch(path):
            if path.endswith("/annotations?per_page=100"):
                return [notes.pop(0)] + ([notes.pop(0)] if len(notes) == 2 else [])
            if "/jobs" in path:
                return {"jobs": [{"name": "discovery (clean)", "id": 1}, {"name": "discovery (air-jump)", "id": 2}]}
            return {"html_url": "https://example.invalid/run", "head_sha": "abc", "created_at": "2026-10-31"}

        doc = cli.collect(7, Path(tmp) / "bench", fetch=fetch)
        self.assertEqual(len(doc["jobs"]), 2)
        mine = {(r["snapshot"], r["specId"]) for r in doc["findings"]}
        self.assertIn(("air-jump", "jump-no-extra-air-jumps-jump-w0-x8"), mine)
        self.assertFalse(any(r["snapshot"] == "clean" for r in doc["findings"]))
        self.assertTrue((Path(tmp) / "bench" / "run-7.json").is_file())

    def test_budget_stops_the_job_as_partial(self):
        doc = self.run_job("air-jump", budget={"maxEpisodes": 5})
        self.assertEqual(doc["completion"], "partial")
        self.assertIn("episode cap 5", doc["stopReason"])


# --- the planner ----------------------------------------------------------------------------------


def reply(doc, usage=None):
    return {"choices": [{"message": {"content": json.dumps(doc)}}], "usage": usage or {"prompt_tokens": 10,
                                                                                         "completion_tokens": 5}}


class Transport:
    def __init__(self, response):
        self.response, self.bodies = response, []

    def __call__(self, body):
        self.bodies.append(body)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


PLAN = {
    "probes": [
        {"id": "Jump Walk Long", "description": "walk then jump 6 times",
         "program": {"op": "sequence", "steps": [{"op": "hold", "action": "move_right", "durationTicks": 200},
                                                 {"op": "repeat", "count": 6, "body": {"op": "sequence", "steps": [
                                                     tap("jump"), {"op": "wait", "durationTicks": 16}]}}]}},
        {"id": "bad", "description": "uses an action that does not exist",
         "program": {"op": "tap", "action": "teleport", "durationTicks": 4}},
    ],
    "candidates": [
        {"id": "rise", "statement": "Jumping while walking takes the player no higher than standing.",
         "claimId": "player.jump", "class": "player",
         "operation": {"type": "relation", "signal": "max_rise_px", "comparator": "lte", "toleranceAbs": 16,
                       "left": "jump-w0-x8", "right": "Jump Walk Long"}},
        {"id": "approved", "statement": "a model cannot approve itself", "claimId": "player.jump", "class": "player",
         "operation": {"type": "max_episode_rise", "maxPx": 300}, "appliesTo": ["plan-jump-walk-long"]},
        {"id": "code", "statement": "x", "claimId": "player.jump", "class": "player",
         "operation": {"type": "python", "src": "import os"}},
        {"id": "ghost", "statement": "x", "claimId": "player.jump", "class": "player",
         "operation": {"type": "relation", "signal": "max_rise_px", "comparator": "lte", "toleranceAbs": 1,
                       "left": "nope", "right": "jump-w0-x8"}},
    ],
}


class Planner(unittest.TestCase):
    def test_only_validated_probes_and_contracts_survive(self):
        profile = load_strict(PROFILE, "mechanics-profile")
        plan = planner_mod.spark_planner(Transport(reply(PLAN)))(profile, library(ACTIONS), {"build-1": {}}, {})
        self.assertEqual([p["id"] for p in plan["probes"]], ["plan-jump-walk-long"])
        ids = [e["spec"]["id"] for e in plan["candidates"]]
        self.assertEqual(ids, ["model-rise", "model-approved"])
        for e in plan["candidates"]:
            self.assertEqual(e["spec"]["expectationRef"]["authority"], "model_prior")
            self.assertFalse(e["approved"])
        self.assertEqual(plan["candidates"][0]["applies"], {"kind": "pair", "left": "jump-w0-x8",
                                                            "right": "plan-jump-walk-long"})
        self.assertEqual(len(plan["diagnostics"]), 3)
        self.assertTrue(all(d.startswith("MODEL_OUTPUT_INVALID") for d in plan["diagnostics"]))

    def test_request_carries_no_bug_context(self):
        profile = load_strict(PROFILE, "mechanics-profile")
        transport = Transport(reply({"probes": [], "candidates": []}))
        planner_mod.spark_planner(transport)(profile, library(ACTIONS), {"build-1": {"hold-right": {"facing_flips": 0}}},
                                             {})
        body = transport.bodies[0]
        self.assertEqual(body["model"], "muse-spark-1.3")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        text = json.dumps(body).lower()
        for leaked in ("patch", "air-jump", "gun-cooldown", "body-flip", "enemy-ledge", "bug report"):
            self.assertNotIn(leaked, text)
        self.assertNotRegex(text, r"\bdiff\b")

    def test_job_numbers_builds_and_runs_planner_probes(self):
        tmp = tempfile.mkdtemp()
        transport = Transport(reply(PLAN))
        doc = discover(PROFILE, snaps(tmp, "air-jump"), Path(tmp) / "out", runner=FakeGame(),
                       planner=planner_mod.spark_planner(transport),
                       probe_ids=["jump-w0-x1", "jump-w0-x2", "jump-w0-x8"])
        sent = json.loads(transport.bodies[0]["messages"][1]["content"])
        self.assertEqual(list(sent["measurements"]), ["build-1"])
        self.assertIn("plan-jump-walk-long", {p["id"] for p in doc["probes"] if p["source"] == "planner"})
        self.assertEqual(next(s for s in doc["stages"] if s["name"] == "planner")["status"], "complete")
        sources = {c["specId"]: c["source"] for c in doc["candidates"]}
        self.assertEqual(sources["model-rise"], "model")

    def test_unavailable_planner_is_a_recorded_stage(self):
        tmp = tempfile.mkdtemp()
        doc = discover(PROFILE, snaps(tmp, "air-jump"), Path(tmp) / "out", runner=FakeGame(),
                       planner=planner_mod.spark_planner(Transport(RuntimeError("HTTP 412: account suspended"))),
                       probe_ids=["jump-w0-x2", "jump-w0-x8"])
        stage = next(s for s in doc["stages"] if s["name"] == "planner")
        self.assertEqual(stage["status"], "unavailable")
        self.assertIn("412", stage["detail"])
        self.assertTrue(doc["findings"])  # the deterministic part still ran

    def test_an_empty_answer_names_its_finish_reason(self):
        profile = load_strict(PROFILE, "mechanics-profile")
        empty = {"choices": [{"message": {"content": None}, "finish_reason": "length"}]}
        with self.assertRaisesRegex(ValueError, "finish_reason 'length'"):
            planner_mod.spark_planner(Transport(empty))(profile, [], {}, {})
        transport = Transport(reply({"probes": [], "candidates": []}))
        planner_mod.spark_planner(transport)(profile, [], {}, {})
        self.assertNotIn("max_tokens", transport.bodies[0])

    def test_non_json_answer_is_refused(self):
        profile = load_strict(PROFILE, "mechanics-profile")
        bad = {"choices": [{"message": {"content": "Sure! Here are some ideas"}}]}
        with self.assertRaises(ValueError):
            planner_mod.spark_planner(Transport(bad))(profile, [], {}, {})


if __name__ == "__main__":
    unittest.main()
