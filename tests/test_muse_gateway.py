"""The Muse key gateway experiment: the swap, the allowlist, and that Muse's side never gets the key."""
import json
import os
import unittest
from unittest import mock

import agents.muse_gateway as mg
import agents.muse_gateway_addon as addon

REAL = "msk-" + "R" * 40


class AddonTest(unittest.TestCase):
    def test_only_metas_hosts_are_allowed(self):
        allow = (".meta.ai",)
        for host in ("api.meta.ai", "meta.ai", "x.y.meta.ai", "API.META.AI."):
            self.assertTrue(addon.host_allowed(host, allow), host)
        for host in ("evil.com", "meta.ai.evil.com", "notmeta.ai", ""):
            self.assertFalse(addon.host_allowed(host, allow), host)
        self.assertTrue(addon.host_allowed("api.example.com", ("api.example.com",)))
        self.assertFalse(addon.host_allowed("x.api.example.com", ("api.example.com",)))

    def test_the_placeholder_is_swapped_wherever_it_appears_and_nothing_else_changes(self):
        fake = mg.placeholder_for(REAL)
        headers = [("Authorization", f"Bearer {fake}"), ("X-Api-Key", fake), ("Accept", "text/event-stream")]
        new, names = addon.swap(headers, fake, REAL)
        self.assertEqual(new, [("Authorization", f"Bearer {REAL}"), ("X-Api-Key", REAL),
                               ("Accept", "text/event-stream")])
        self.assertEqual(names, ["authorization", "x-api-key"])
        self.assertEqual(addon.swap(headers, "", REAL), (headers, []))  # no placeholder configured: no swap


class DriverTest(unittest.TestCase):
    def test_the_placeholder_has_the_keys_shape_but_not_its_secret(self):
        fake = mg.placeholder_for(REAL)
        self.assertEqual(len(fake), len(REAL))
        self.assertTrue(fake.startswith("msk-"))
        self.assertNotEqual(fake, REAL)
        self.assertNotIn("RRRRRRRR", fake)
        self.assertGreaterEqual(len(mg.placeholder_for("short")), 24)

    def test_muses_environment_holds_the_placeholder_the_proxy_and_the_ca_never_the_key(self):
        fake = mg.placeholder_for(REAL)
        with mock.patch.dict(os.environ, {"META_API_KEY": REAL, "HTTPS_PROXY": "http://elsewhere:1",
                                          "NO_PROXY": "meta.ai", "PATH": "/usr/bin"}):
            env = mg.muse_env(fake, proxy="http://127.0.0.1:9", ca="/ca.pem", home="/tmp/h")
            control = mg.muse_env(fake, proxy=None, ca=None, home="/tmp/h")
        self.assertNotIn(REAL, json.dumps(env))
        self.assertEqual(env["META_API_KEY"], fake)
        self.assertEqual(env["HTTPS_PROXY"], "http://127.0.0.1:9")
        self.assertNotIn("NO_PROXY", env)  # nothing may bypass the proxy
        self.assertEqual(env["SSL_CERT_FILE"], "/ca.pem")
        self.assertEqual(env["NODE_EXTRA_CA_CERTS"], "/ca.pem")
        self.assertNotIn("HTTPS_PROXY", control)
        self.assertNotIn("SSL_CERT_FILE", control)

    def test_the_verdict_needs_a_failing_control_and_a_swapped_answer(self):
        row = lambda name, answered, swapped=(): {"variant": name, "answered": answered,
                                                  "swappedHeaders": list(swapped)}
        self.assertIn("inconclusive", mg.verdict({"control": row("control", True)}))
        self.assertEqual(mg.verdict({"control": row("control", False), "host": row("host", True, ["authorization"]),
                                     "bwrap": row("bwrap", True, ["authorization"])}),
                         "works on the host and inside bubblewrap with the installed program bound read-only: "
                         "Muse never held the key")
        self.assertIn("host only", mg.verdict({"control": row("control", False),
                                               "host": row("host", True, ["authorization"]),
                                               "bwrap": row("bwrap", False)}))
        self.assertIn("does not work", mg.verdict({"control": row("control", False), "host": row("host", True)}))

    def test_install_dirs_find_large_native_programs_but_never_the_config(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            elf = b"\x7fELF" + b"\0" * 64
            for rel, data in ((".local/share/m/versions/1.4/prog", elf), (".local/bin/muse-core", elf),
                              (".config/x/prog", elf), ("actions-runner/cached/2.3/Runner", elf),
                              (".local/share/small/prog", elf[:20]), (".cache/big.bin", b"\0" * 128)):
                (home / rel).parent.mkdir(parents=True, exist_ok=True)
                (home / rel).write_bytes(data)
            found = [p.relative_to(home).as_posix() for p in mg.install_dirs(home, min_bytes=40)]
        # The program in ~/.local/bin as a file (sessions under ~/.local stay writable); another with its directory.
        self.assertEqual(found, [".local/bin/muse-core", ".local/share/m/versions/1.4"])

    def test_launcher_paths_pick_out_where_it_looks(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            launcher = Path(tmp) / "muse"
            launcher.write_text('#!/bin/bash\n# HOME comment\nROOT="${XDG_DATA_HOME:-$HOME/.local/share}/m"\necho hi\n')
            self.assertEqual(mg.launcher_paths(str(launcher)), ['ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/m"'])
        self.assertEqual(mg.launcher_paths(None), [])

    def test_the_bound_sandbox_adds_read_only_binds_before_the_command(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "muse"
            (d / "sessions").mkdir(parents=True)
            cmd = mg.bwrap_argv(Path(tmp), ["muse", "exec", "x"], [d])
        cut = cmd.index("--")
        self.assertEqual(cmd[cut:], ["--", "muse", "exec", "x"])
        self.assertEqual(cmd[cut - 5:cut], ["--ro-bind", str(d), str(d), "--tmpfs", str(d / "sessions")])

    def test_the_verdict_says_when_the_sandbox_needs_the_download_host(self):
        row = lambda name, answered, swapped=(): {"variant": name, "answered": answered,
                                                  "swappedHeaders": list(swapped)}
        verdict = mg.verdict({"control": row("control", False), "host": row("host", True, ["authorization"]),
                              "bwrap": row("bwrap", False), "bwrap-download": row("bwrap-download", True)})
        self.assertIn("only when the proxy also passes lookaside.facebook.com", verdict)

    def test_redact_removes_both_keys(self):
        fake = mg.placeholder_for(REAL)
        self.assertEqual(mg.redact(f"a {REAL} b {fake}", REAL, fake), "a [redacted] b [redacted]")


if __name__ == "__main__":
    unittest.main()
