"""Can Muse Code run without ever holding the Meta API key? An experiment.

Today the fixer passes META_API_KEY into Muse Code's sandbox, so anything that steers Muse (a
prompt injection in playtest feedback, a poisoned file) can read the key and send it anywhere
(OBAAF-GHA-005). The alternative tested here: Muse gets a placeholder key of the same shape and
an HTTPS proxy (agents/muse_gateway_addon.py, run by mitmdump) that holds the real key, swaps it in
for Meta's API only, and refuses every other host. Muse trusts the proxy's certificate authority
and nothing else.

Three runs of ``muse exec`` with a one-line prompt:

- ``control``: the placeholder and no proxy. It must fail; if it succeeds, Muse found a credential
  somewhere else and the experiment proves nothing.
- ``host``: the placeholder through the proxy, Muse on the host.
- ``bwrap``: the same inside the fixer's bubblewrap sandbox (agents/sandbox.py), as a real fix runs,
  with the installed Muse Code files bound read-only. ``muse`` is a shell launcher that keeps the
  real program under the home directory, which the sandbox replaces with an empty one; without
  these files the launcher downloads the program again on every run (from lookaside.facebook.com).
- ``bwrap-download``: the sandbox as it is today, with the proxy also passing that download host.

The real key is in this process and the proxy's environment only. Muse's output and the proxy
log are checked for it, and only the placeholder's length and the header names it travelled in
are recorded. This answers whether the CLI cooperates (proxy, certificate, placeholder); it does
not by itself clear OBAAF's finding, since the key is still in the CI job, held by the proxy.

    META_API_KEY=... python3 -m agents.muse_gateway --mitmdump "$RUNNER_TEMP/mitm/bin/mitmdump" --out runs/gateway
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import socket
import string
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from agents.keys import muse_subprocess_env
from harness.run import REPO

ADDON = REPO / "agents" / "muse_gateway_addon.py"
PROMPT = "Reply with exactly the text GATEWAY-OK and nothing else. Do not run tools or edit files."
EXPECT = "GATEWAY-OK"
CA_VARS = ("SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")
PROXY_VARS = ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy")
VARIANTS = ("control", "host", "bwrap", "bwrap-download")
DOWNLOAD_HOST = "lookaside.facebook.com"


def install_dirs(home: Path | None = None) -> list[Path]:
    """Where the Muse Code installer put the program: directories named *muse* under the usual places.

    Configuration (~/.config) is left out on purpose: it is where a stored login would live.
    """
    home = home or Path.home()
    found = []
    for root in (home / ".local" / "share", home / ".local" / "lib", home / ".cache", home):
        if root.is_dir():
            found += [p for p in root.iterdir() if p.is_dir() and "muse" in p.name.lower()
                      and p.name.lower() not in (".config",)]
    return sorted(set(found))


def bwrap_argv(work: Path, argv: list[str], binds: list[Path]) -> list[str]:
    """The fixer's bubblewrap command, plus the Muse install directories read-only (sessions stay writable)."""
    from agents.sandbox import _bwrap_cmd

    cmd = _bwrap_cmd(work, argv, network=True)
    extra: list[str] = []
    for d in binds:
        extra += ["--ro-bind", str(d), str(d)]
        if (d / "sessions").is_dir():
            extra += ["--tmpfs", str(d / "sessions")]
    cut = cmd.index("--")
    return cmd[:cut] + extra + cmd[cut:]


def placeholder_for(real: str) -> str:
    """A fake key of the same length, keeping a short prefix (up to the first - or _ in 12 characters)
    so a client that checks a key's shape before sending it is not stopped by the shape alone."""
    cut = next((i + 1 for i, ch in enumerate(real[:12]) if ch in "-_"), 0)
    alphabet = string.ascii_letters + string.digits
    while True:
        fake = real[:cut] + "".join(secrets.choice(alphabet) for _ in range(max(len(real) - cut, 24)))
        if fake != real:
            return fake


def muse_env(placeholder: str, *, proxy: str | None, ca: str | None, home: str) -> dict:
    """Muse Code's usual environment, with the placeholder for the key and, optionally, the proxy."""
    env = muse_subprocess_env()
    for var in PROXY_VARS + ("NO_PROXY", "no_proxy") + CA_VARS:
        env.pop(var, None)
    env["META_API_KEY"] = placeholder
    env["HOME"] = home
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        env.pop(var, None)
    if proxy:
        for var in PROXY_VARS:
            env[var] = proxy
    if ca:
        for var in CA_VARS:
            env[var] = ca
    return env


def redact(text: str, *secrets_: str) -> str:
    for s in secrets_:
        if s:
            text = text.replace(s, "[redacted]")
    return text


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_gateway(mitmdump: str, conf: Path, log: Path, real: str, placeholder: str,
                  hosts: str) -> tuple[subprocess.Popen, str, Path]:
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if k not in ("META_API_KEY", "MODEL_API_KEY")}
    env.update(MUSE_GATEWAY_KEY=real, MUSE_GATEWAY_PLACEHOLDER=placeholder, MUSE_GATEWAY_LOG=str(log),
               MUSE_GATEWAY_HOSTS=hosts)
    with open(conf / "mitmdump.err", "w") as err:  # the child keeps its own copy of the descriptor
        proc = subprocess.Popen([mitmdump, "-q", "-s", str(ADDON), "--listen-host", "127.0.0.1",
                                 "--listen-port", str(port), "--set", f"confdir={conf}"],
                                env=env, stdout=subprocess.DEVNULL, stderr=err)
    ca = conf / "mitmproxy-ca-cert.pem"
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"mitmdump exited ({proc.returncode}); see {conf / 'mitmdump.err'}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                if ca.is_file():
                    return proc, f"http://127.0.0.1:{port}", ca
        except OSError:
            pass
        time.sleep(0.5)
    proc.terminate()
    raise SystemExit("mitmdump did not start listening within 60 s")


def read_log(log: Path, since: float) -> list[dict]:
    if not log.is_file():
        return []
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if r.get("t", since) >= since]


def run_variant(name: str, *, out: Path, real: str, placeholder: str, proxy: str | None, ca: Path | None,
                log: Path, timeout: int = 240) -> dict:
    work = out / name
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    argv = ["muse", "exec", "--disable-approval", "--trust-workspace", PROMPT]
    started = time.time()
    if name.startswith("bwrap"):
        # The certificate must be readable inside the sandbox: .muse is bound read-only at /fixer/.muse.
        (work / ".muse").mkdir()
        shutil.copyfile(ca, work / ".muse" / "gateway-ca.pem")
        env = muse_env(placeholder, proxy=proxy, ca="/fixer/.muse/gateway-ca.pem", home=str(Path.home()))
        cmd = bwrap_argv(work, argv, install_dirs() if name == "bwrap" else [])
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            proc = subprocess.CompletedProcess(argv, None, str(exc.stdout or ""), str(exc.stderr or ""))
    else:
        home = tempfile.mkdtemp(prefix=f"muse-home-{name}-")
        env = muse_env(placeholder, proxy=proxy, ca=str(ca) if ca else None, home=home)
        try:
            proc = subprocess.run(argv, cwd=work, env=env, capture_output=True, text=True, timeout=timeout,
                                  check=False)
        except subprocess.TimeoutExpired as exc:
            proc = subprocess.CompletedProcess(argv, None, str(exc.stdout or ""), str(exc.stderr or ""))
    if real and real in json.dumps(env):
        raise SystemExit("the real key reached Muse's environment; stopping")
    output = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    flows = read_log(log, started) if proxy else []
    (work / "muse.log").write_text(redact(output, real, placeholder), encoding="utf-8")
    lines = [ln.strip() for ln in re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", output).splitlines() if ln.strip()]
    return {
        "variant": name,
        "exit": proc.returncode,
        "answered": EXPECT in output,
        "seconds": round(time.time() - started, 1),
        "realKeyInMuseOutput": bool(real) and real in output,
        "hosts": sorted({f["host"] for f in flows if f.get("host")}),
        "blockedHosts": sorted({f["host"] for f in flows if f.get("blocked")}),
        "swappedHeaders": sorted({n for f in flows for n in f.get("swapped") or []}),
        "requests": len(flows),
        "statuses": sorted({f.get("status") for f in flows if f.get("status") is not None}),
        "errors": sorted({f["error"] for f in flows if f.get("error")})[:3],
        "logTail": [redact(ln, real, placeholder)[:200] for ln in lines[-5:]],
    }


def verdict(results: dict[str, dict]) -> str:
    control, host, box, download = (results.get(v) for v in VARIANTS)
    if control and control["answered"]:
        return "inconclusive: Muse answered with the placeholder and no proxy, so it has another credential"
    if host and host["answered"] and host["swappedHeaders"]:
        if box and box["answered"]:
            where = "on the host and inside bubblewrap with the installed program bound read-only"
        elif download and download["answered"]:
            where = f"on the host, and inside bubblewrap only when the proxy also passes {DOWNLOAD_HOST}"
        else:
            where = "on the host only"
        return f"works {where}: Muse never held the key"
    return "does not work as tried: see each variant's log tail"


def annotation(row: dict) -> str:
    return (f"::notice title=Muse gateway {row['variant']}::exit {row['exit']}; answered {row['answered']}; "
            f"{row['requests']} requests to {', '.join(row['hosts']) or 'nothing'}; "
            f"key swapped in {', '.join(row['swappedHeaders']) or 'no header'}; "
            f"blocked {', '.join(row['blockedHosts']) or 'nothing'}; statuses {row['statuses']}; "
            f"{row['seconds']} s; log: {' | '.join(row['logTail'])[:400]}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--mitmdump", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--hosts", default=".meta.ai", help="hosts the key may go to (comma-separated)")
    p.add_argument("--variants", default=",".join(VARIANTS))
    args = p.parse_args(argv)
    real = os.environ.get("META_API_KEY", "")
    if not real:
        raise SystemExit("META_API_KEY is required (it stays in this process and the proxy)")
    if not shutil.which("muse"):
        raise SystemExit("muse is not on PATH")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    conf = out / "mitm-conf"
    conf.mkdir(exist_ok=True)
    log = out / "gateway-log.jsonl"
    placeholder = placeholder_for(real)
    version = subprocess.run(["muse", "--version"], capture_output=True, text=True, check=False)
    binary = subprocess.run(["file", "-L", shutil.which("muse")], capture_output=True, text=True, check=False)
    info = {"museVersion": version.stdout.strip()[:80],
            "museBinary": binary.stdout.split(":", 1)[-1].strip()[:200],
            "placeholderLength": len(placeholder), "keyLength": len(real), "allowedHosts": args.hosts}
    print(f"::notice title=Muse gateway setup::muse {info['museVersion']}; {info['museBinary']}; "
          f"placeholder of the key's length ({info['keyLength']}); key may go to {args.hosts}")
    dirs = install_dirs()
    print(f"::notice title=Muse install::launcher {shutil.which('muse')}; program directories bound in the "
          f"bwrap variant: {', '.join(str(d) for d in dirs) or 'none found'}")
    names = [v.strip() for v in args.variants.split(",") if v.strip()]
    unknown = sorted(set(names) - set(VARIANTS))
    if unknown:
        raise SystemExit(f"unknown variant(s) {unknown}")
    results: dict[str, dict] = {}
    # Two proxies, both holding the key: the strict one passes Meta's API only, the other also
    # passes the program download host (for bwrap-download).
    hosts_for = {name: args.hosts if name != "bwrap-download" else f"{args.hosts},{DOWNLOAD_HOST}" for name in names}
    gateways: dict[str, tuple] = {}
    try:
        for name in names:
            hosts = hosts_for[name]
            if name != "control" and hosts not in gateways:
                conf_dir = conf / f"gw{len(gateways)}"
                conf_dir.mkdir(exist_ok=True)
                gateways[hosts] = start_gateway(args.mitmdump, conf_dir, log, real, placeholder, hosts)
            _proc, proxy, ca = gateways.get(hosts, (None, None, None)) if name != "control" else (None, None, None)
            row = run_variant(name, out=out, real=real, placeholder=placeholder, proxy=proxy, ca=ca, log=log)
            results[name] = row
            print(annotation(row))
    finally:
        for gateway, _proxy, _ca in gateways.values():
            gateway.terminate()
            try:
                gateway.wait(timeout=10)
            except subprocess.TimeoutExpired:
                gateway.kill()
    leaked = any(r["realKeyInMuseOutput"] for r in results.values())
    if log.is_file() and real in log.read_text(encoding="utf-8"):
        leaked = True
    doc = {"format": "expectrail.muse-gateway/v0", **info, "installDirs": [str(d) for d in dirs], "verdict": verdict(results),
           "realKeyLeaked": leaked, "variants": list(results.values())}
    (out / "results.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    level = "error" if leaked else "notice"
    print(f"::{level} title=Muse gateway verdict::{doc['verdict']}; real key in Muse output or the proxy log: {leaked}")
    return 1 if leaked else 0


if __name__ == "__main__":
    sys.exit(main())
