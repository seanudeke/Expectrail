"""Fixer guard: the Muse Code PreToolUse hook, its installer, and its wiring into run_fixer."""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agents import guard
from agents.fixer import run_fixer
from agents.orchestrator import build_repair_request
from agents.patchutil import path_allowed
from harness.run import REPO
from nightshift.contracts import load

HOOK = REPO / "agents" / "fixer_guard_hook.py"
EDITABLE = ["player/**", "level/**"]


def _request():
    return build_repair_request(
        request_id="rr-guard",
        spec=load(REPO / "agents" / "specs" / "player-stays-above-ground.json", "test-spec"),
        verdict=load(REPO / "contracts" / "examples" / "verdict.json", "verdict"),
        route=load(REPO / "harness" / "routes" / "smoke.json", "route"),
        base_patch="bugs/physics-fall-through/v1.patch",
        key_frames=["frames/f00000008.png"],
    )


def call_hook(work: Path, payload) -> tuple[int, dict | None, str]:
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    proc = subprocess.run([sys.executable, str(work / guard.HOOK_REL)], input=raw, capture_output=True,
                          text=True, cwd=str(work), timeout=30)
    out = proc.stdout.strip()
    return proc.returncode, (json.loads(out) if out else None), proc.stderr


def denied(answer: dict | None) -> bool:
    return bool(answer) and answer["hookSpecificOutput"]["permissionDecision"] == "deny"


class HookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name) / "fixer-work"
        (self.work / "player").mkdir(parents=True)
        (self.work / "player" / "player.tscn").write_text("x\n")
        self.installed = guard.install_guard(self.work, EDITABLE, root_as_muse_sees_it=str(self.work))

    def tearDown(self):
        self.tmp.cleanup()

    def tool(self, name, **tool_input):
        return {"hook_event_name": "PreToolUse", "tool_name": name, "tool_input": tool_input,
                "tool_use_id": f"t-{name}", "cwd": str(self.work), "session_id": "s"}

    def test_hooks_json_has_only_the_documented_keys(self):
        cfg = json.loads((self.work / ".muse" / "hooks.json").read_text())
        self.assertEqual(list(cfg), ["hooks"])
        self.assertEqual(list(cfg["hooks"]), ["PreToolUse"])
        (group,) = cfg["hooks"]["PreToolUse"]
        self.assertEqual(list(group), ["hooks"])  # no matcher: every tool goes through the guard
        (handler,) = group["hooks"]
        self.assertEqual(set(handler), {"type", "command", "timeout"})
        self.assertEqual(handler["type"], "command")
        self.assertTrue(handler["command"].endswith(f"{self.work}/{guard.HOOK_REL}"))
        bwrap = guard.hooks_config("/fixer")["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertEqual(bwrap, "python3 /fixer/.muse/hooks/fixer_guard.py")

    def test_writes_inside_editable_globs_pass(self):
        for payload in (self.tool("write_file", path="player/player.tscn", content="y"),
                        self.tool("edit_file", path=str(self.work / "level" / "new.gd"), find="a", replace="b")):
            code, answer, _ = call_hook(self.work, payload)
            self.assertEqual(code, 0)
            self.assertEqual(answer, {})

    def test_writes_outside_are_denied(self):
        outside = Path(self.tmp.name) / "elsewhere"
        outside.mkdir()
        (self.work / "player" / "escape").symlink_to(outside)
        cases = {
            "specs/player-stays-above-ground.json": "outside the editable files",
            "../verifier-host/key": "outside the fixer workspace",
            "/etc/passwd": "outside the fixer workspace",
            "player/escape/x.gd": "outside the fixer workspace",
            ".muse/fixer-guard.json": "off limits",
            ".fixer-guard-log/fixer-guard.jsonl": "off limits",
            "player/../project.godot": "outside the editable files",
        }
        for path, why in cases.items():
            with self.subTest(path=path):
                code, answer, _ = call_hook(self.work, self.tool("write_file", path=path, content="z"))
                self.assertEqual(code, 0)
                self.assertTrue(denied(answer))
                self.assertIn(why, answer["hookSpecificOutput"]["permissionDecisionReason"])

    def test_web_tools_denied_reads_and_shell_logged(self):
        self.assertTrue(denied(call_hook(self.work, self.tool("web_fetch", url="https://example.com"))[1]))
        self.assertTrue(denied(call_hook(self.work, self.tool("web_search", query="answer"))[1]))
        self.assertEqual(call_hook(self.work, self.tool("read_file", path="specs/x.json"))[1], {})
        self.assertEqual(call_hook(self.work, self.tool("bash", command="cat player/player.tscn"))[1], {})
        # an unknown tool that names a file under any common key is judged as a write
        self.assertTrue(denied(call_hook(self.work, self.tool("apply_patch", path="specs/x.json"))[1]))
        self.assertTrue(denied(call_hook(self.work, self.tool("create_file", file_path="specs/x.json"))[1]))
        self.assertTrue(denied(call_hook(self.work, self.tool("multi_write", paths=["player/a.gd", "x.cfg"]))[1]))
        self.assertEqual(call_hook(self.work, self.tool("create_file", file_path="player/new.gd"))[1], {})
        # an unknown tool with no file key passes, and the report names it
        self.assertEqual(call_hook(self.work, self.tool("apply_diff", input="*** patch"))[1], {})
        entries = guard.read_log(self.work / guard.LOG_REL)
        self.assertEqual(len(entries), 9)
        self.assertEqual(entries[3]["command"], "cat player/player.tscn")
        summary = guard.summarize(entries, self.installed)
        self.assertEqual(summary["unknownTools"], ["apply_diff", "apply_patch", "create_file", "multi_write"])

    def test_fails_closed(self):
        code, answer, _ = call_hook(self.work, "not json")
        self.assertEqual(code, 0)
        self.assertTrue(denied(answer))
        self.assertTrue(denied(call_hook(self.work, self.tool("write_file", content="no path"))[1]))
        (self.work / guard.POLICY_REL).unlink()
        answer = call_hook(self.work, self.tool("write_file", path="player/player.tscn", content="y"))[1]
        self.assertTrue(denied(answer))
        self.assertIn("policy missing", answer["hookSpecificOutput"]["permissionDecisionReason"])

    def test_collect_summarizes_the_log(self):
        call_hook(self.work, self.tool("write_file", path="player/player.tscn", content="y"))
        call_hook(self.work, self.tool("write_file", path="specs/a.json", content="y"))
        out = Path(self.tmp.name) / "out"
        out.mkdir()
        summary = guard.collect_guard(self.work, out, self.installed)
        self.assertEqual((summary["installed"], summary["loaded"], summary["calls"]), (True, True, 2))
        self.assertEqual([b["rel"] for b in summary["blocked"]], ["specs/a.json"])
        self.assertTrue((out / "guard.json").is_file())
        self.assertTrue((out / "guard-log.jsonl").is_file())
        empty = Path(self.tmp.name) / "empty"
        (empty / ".muse").mkdir(parents=True)
        self.assertFalse(guard.collect_guard(empty, out, self.installed)["loaded"])


class BwrapGuardTest(unittest.TestCase):
    """Under bubblewrap the agent's shell cannot rewrite the guard. Runs where bwrap works (CI's
    agents-sandbox job sets NIGHTSHIFT_REQUIRE_BWRAP=1 so a skip there is a failure)."""

    def test_bwrap_mounts_muse_read_only(self):
        from agents.sandbox import _bwrap_cmd

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "fixer-work"
            (work / "player").mkdir(parents=True)
            guard.install_guard(work, EDITABLE, root_as_muse_sees_it="/fixer")
            cmd = _bwrap_cmd(work, ["true"], network=False)
            i = cmd.index("--ro-bind")
            self.assertEqual(cmd[i:i + 3], ["--ro-bind", str((work / ".muse").resolve()), "/fixer/.muse"])
            self.assertLess(cmd.index("--bind"), i)  # the read-only mount lands on top of the workspace

    def test_shell_cannot_rewrite_guard_under_bwrap(self):
        from agents.sandbox import _bwrap_cmd, _bwrap_usable

        if not _bwrap_usable():
            if os.environ.get("NIGHTSHIFT_REQUIRE_BWRAP") == "1":
                self.fail("bubblewrap is required here but not usable")
            self.skipTest("bubblewrap not usable here")
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "fixer-work"
            (work / "player").mkdir(parents=True)
            guard.install_guard(work, EDITABLE, root_as_muse_sees_it="/fixer")
            policy_before = (work / guard.POLICY_REL).read_text()
            payload = json.dumps({"tool_name": "write_file", "tool_input": {"path": "specs/x.json"},
                                  "cwd": "/fixer"})
            script = (
                "echo '{\"editable\": [\"*\"]}' > .muse/fixer-guard.json; echo policy=$?; "
                "rm -rf .muse 2>/dev/null; echo rm=$?; mv .muse moved 2>/dev/null; echo mv=$?; "
                f"echo '{payload}' | python3 /fixer/{guard.HOOK_REL}"
            )
            proc = subprocess.run(_bwrap_cmd(work, ["sh", "-c", script], network=False), capture_output=True,
                                  text=True, timeout=60, env={"PATH": "/usr/bin:/bin"})
            self.assertIn("policy=", proc.stdout, proc.stdout + proc.stderr)
            self.assertNotIn("policy=0", proc.stdout, proc.stdout + proc.stderr)  # dash says 2, bash 1
            self.assertNotIn("rm=0", proc.stdout)
            self.assertNotIn("mv=0", proc.stdout)
            self.assertIn('"permissionDecision": "deny"', proc.stdout)
            self.assertEqual((work / guard.POLICY_REL).read_text(), policy_before)
            self.assertEqual(len(guard.read_log(work / guard.LOG_REL)), 1)


class HookSourceTest(unittest.TestCase):
    def test_hook_is_stdlib_only(self):
        tree = ast.parse(HOOK.read_text())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                mods.add((node.module or "").split(".")[0])
        self.assertLessEqual(mods, {"__future__", "fnmatch", "json", "os", "sys", "time"})

    def test_glob_rule_matches_patchutil(self):
        sys.path.insert(0, str(HOOK.parent))
        try:
            import fixer_guard_hook as hook
        finally:
            sys.path.pop(0)
        for rel in ("player/player.tscn", "player/a/b.gd", "level/x", "specs/s.json", "player", "project.godot"):
            for globs in (EDITABLE, ["player/"], ["*.gd"], ["**"]):
                self.assertEqual(hook.path_allowed(rel, globs), path_allowed(rel, globs), (rel, globs))

    def test_guard_switch(self):
        self.assertTrue(guard.guard_enabled({}))
        for off in ("0", "off", "false", "no"):
            self.assertFalse(guard.guard_enabled({guard.GUARD_ENV: off}))


class FixerWiringTest(unittest.TestCase):
    def _fake_muse(self, seen):
        def fake(prompt, *, work, env=None, timeout=0, require_sandbox=False, detected=None):
            seen["detected"] = detected
            seen["hooks"] = json.loads((work / ".muse" / "hooks.json").read_text()) \
                if (work / ".muse" / "hooks.json").is_file() else None
            if seen["hooks"] is not None:
                base = {"cwd": str(work), "hook_event_name": "PreToolUse"}
                calls = [
                    {"tool_name": "edit_file", "tool_input": {"path": "player/player.tscn"}},
                    {"tool_name": "write_file", "tool_input": {"path": "specs/player-stays-above-ground.json"}},
                    {"tool_name": "web_fetch", "tool_input": {"url": "https://example.com/answer"}},
                ]
                for call in calls:
                    call_hook(work, {**base, **call})
            tscn = work / "player" / "player.tscn"
            tscn.write_text(tscn.read_text().replace("collision_mask = 14", "collision_mask = 30"))
            return mock.Mock(returncode=0, stdout="ok", stderr=""), {"kind": "none"}
        return fake

    def _run(self, out, env):
        seen: dict = {}
        with mock.patch.dict(os.environ, env):
            with mock.patch("agents.fixer.muse_code_ready", return_value=True), \
                    mock.patch("agents.fixer.detect_sandbox", return_value="none"), \
                    mock.patch("agents.fixer.run_muse_sandboxed", side_effect=self._fake_muse(seen)):
                meta = run_fixer(_request(), out, candidate_patch=None)
        return meta, seen

    def test_run_fixer_installs_guard_and_records_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fix"
            meta, seen = self._run(out, {"META_API_KEY": "k", guard.GUARD_ENV: "1"})
            self.assertEqual(seen["detected"], "none")
            cmd = seen["hooks"]["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
            self.assertIn(str((out / "fixer-work").resolve()), cmd)
            self.assertEqual(meta["guard"], {"installed": True, "loaded": True, "calls": 3, "blocked": 2})
            summary = json.loads((out / "guard.json").read_text())
            self.assertEqual(sorted(b["tool"] for b in summary["blocked"]), ["web_fetch", "write_file"])
            patch = (out / "candidate.patch").read_text()
            self.assertIn("player/player.tscn", patch)
            self.assertNotIn(".muse", patch)

    def test_guard_can_be_switched_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fix"
            meta, seen = self._run(out, {"META_API_KEY": "k", guard.GUARD_ENV: "0"})
            self.assertIsNone(seen["hooks"])
            self.assertNotIn("guard", meta)
            self.assertFalse((out / "guard.json").exists())


if __name__ == "__main__":
    unittest.main()
