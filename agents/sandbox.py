"""OS sandbox for Muse Code / trust probes — real mount confinement when available.

Prefer bubblewrap (`bwrap`) on Linux. Docker can film a blocked canary read by mounting
only fixer-work. When neither works, kind is `none` (deny-by-absence + env scrub only).

    python3 -m agents.sandbox --probe /path/to/fixer --canary /path/to/key

`--require-sandbox` fails closed when kind is none.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Mapping

from agents.keys import muse_subprocess_env

SANDBOX_KINDS = frozenset({"bwrap", "docker", "none"})


def _bwrap_usable() -> bool:
    """True when bwrap can create a namespace (GHA often blocks uid_map until sysctl)."""
    if not shutil.which("bwrap"):
        return False
    cmd = [
        "bwrap",
        "--die-with-parent",
        "--unshare-pid",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
    ]
    for ro in ("/usr", "/bin", "/lib", "/lib64"):
        if Path(ro).exists():
            cmd.extend(["--ro-bind", ro, ro])
    cmd.extend(["--", "true"])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def detect_sandbox() -> str:
    """Return bwrap | docker | none (first usable tool)."""
    if _bwrap_usable():
        return "bwrap"
    if shutil.which("docker"):
        # Probe that docker daemon answers (cheap version check).
        try:
            proc = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc.returncode == 0:
                return "docker"
        except (OSError, subprocess.TimeoutExpired):
            pass
    return "none"


def _bwrap_cmd(work: Path, argv: list[str], *, network: bool) -> list[str]:
    """Bind only fixer-work as /fixer; ro system paths for a usable userspace."""
    work = work.resolve()
    cmd = [
        "bwrap",
        "--die-with-parent",
        "--unshare-pid",
        "--bind", str(work), "/fixer",
    ]
    if (work / ".muse").is_dir():
        # Muse Code project config and the fixer guard: readable, never writable by the agent.
        cmd.extend(["--ro-bind", str(work / ".muse"), "/fixer/.muse"])
    cmd += [
        "--chdir", "/fixer",
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
    ]
    if not network:
        cmd.append("--unshare-net")
    for ro in (
        "/usr", "/bin", "/lib", "/lib64",
        "/etc/ssl", "/etc/ca-certificates",
        # DNS + name service (without these Muse cannot reach api.meta.ai).
        "/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf",
        "/etc/protocols", "/etc/services",
    ):
        if Path(ro).exists():
            cmd.extend(["--ro-bind", ro, ro])
    # Host muse binary (Linux ELF) when present. Give Muse a writable tmpfs $HOME so
    # session locks / update stamps work; never rw-bind the real host home.
    home = Path.home()
    cmd.extend(["--tmpfs", str(home), "--setenv", "HOME", str(home)])
    muse = shutil.which("muse")
    if muse:
        muse_path = Path(muse).resolve()
        cmd.extend(["--dir", str(muse_path.parent)])
        cmd.extend(["--ro-bind", str(muse_path), str(muse_path)])
        for sub in ("lib", "share"):
            p = home / ".local" / sub
            if p.is_dir():
                cmd.extend(["--ro-bind", str(p), str(p)])
    cmd.extend(["--"] + argv)
    return cmd


def _docker_cmd(work: Path, argv: list[str], *, network: bool, image: str = "alpine:3.20") -> list[str]:
    """Mount only fixer-work at /fixer. argv runs inside the image (not host muse)."""
    work = work.resolve()
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{work}:/fixer:rw",
        "-w", "/fixer",
    ]
    if not network:
        cmd.append("--network=none")
    for k, v in muse_subprocess_env().items():
        cmd.extend(["-e", f"{k}={v}"])
    cmd.append(image)
    cmd.extend(argv)
    return cmd


def run_sandboxed(
    argv: list[str],
    *,
    work: Path,
    env: Mapping[str, str] | None = None,
    network: bool = True,
    kind: str | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run argv confined to fixer-work when a sandbox tool exists.

    - bwrap: runs host argv (e.g. muse) with only work + minimal ro binds.
    - docker: runs argv inside alpine with only work mounted (good for probes;
      not for host `muse` Mach-O on macOS).
    - none: plain subprocess with cwd=work (honesty / env scrub only).
    """
    resolved = kind if kind is not None else detect_sandbox()
    if resolved not in SANDBOX_KINDS:
        raise ValueError(f"unknown sandbox kind: {resolved}")
    run_env = dict(env) if env is not None else muse_subprocess_env()
    if resolved == "bwrap":
        cmd = _bwrap_cmd(work, argv, network=network)
        return subprocess.run(
            cmd, capture_output=True, text=True, env=run_env, timeout=timeout,
        )
    if resolved == "docker":
        # Docker injects env via -e; still pass a minimal host env for docker CLI itself.
        host_env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "DOCKER_HOST", "USER")}
        cmd = _docker_cmd(work, argv, network=network)
        return subprocess.run(
            cmd, capture_output=True, text=True, env=host_env or None, timeout=timeout,
        )
    return subprocess.run(
        argv, cwd=str(work), capture_output=True, text=True, env=run_env, timeout=timeout,
    )


def probe_blocked_canary_read(
    work: Path,
    canary: Path,
    *,
    kind: str | None = None,
) -> dict:
    """Attempt to read canary from inside the sandbox; expect failure when enforced.

    Uses `cat` of the absolute host canary path. When only fixer-work is mounted,
    that path is invisible → non-zero exit / no key bytes.
    """
    resolved_kind = kind if kind is not None else detect_sandbox()
    canary = canary.resolve()
    marker = "DEMO-FAKE-SIGNING-KEY-NOT-REAL"
    key_raw = canary.read_bytes() if canary.is_file() else b""
    argv = ["cat", str(canary)]

    def _leaked(blob: str | bytes, *, exit_ok: bool) -> bool:
        if isinstance(blob, str):
            data = blob.encode("utf-8", errors="surrogateescape")
            text = blob
        else:
            data = blob
            text = blob.decode("utf-8", errors="ignore")
        if marker in text:
            return True
        if key_raw and key_raw in data:
            return True
        # Successful cat of the canary path is a leak even when stdout is mangled.
        return bool(exit_ok and data)

    # Inside docker/bwrap the host absolute path usually does not exist.
    if resolved_kind == "none":
        # Honesty: host process can still read the canary.
        try:
            raw = canary.read_bytes()
            text = raw.decode("utf-8", errors="ignore")
            return {
                "kind": "none",
                "enforced": False,
                "blocked": False,
                "exitCode": 0,
                "leakedKeyBytes": _leaked(raw, exit_ok=True),
                "stdout": text[:200],
                "stderr": "",
                "detail": "no OS sandbox; host process can read canary (deny-by-absence only)",
            }
        except OSError as exc:
            return {
                "kind": "none",
                "enforced": False,
                "blocked": True,
                "exitCode": 1,
                "leakedKeyBytes": False,
                "stdout": "",
                "stderr": str(exc),
                "detail": f"host read failed unexpectedly: {exc}",
            }

    proc = run_sandboxed(argv, work=work, network=False, kind=resolved_kind, timeout=60)
    out = (proc.stdout or "") + (proc.stderr or "")
    leaked = _leaked(out, exit_ok=proc.returncode == 0)
    blocked = proc.returncode != 0 and not leaked
    return {
        "kind": resolved_kind,
        "enforced": True,
        "blocked": blocked,
        "exitCode": proc.returncode,
        "leakedKeyBytes": leaked,
        "stdout": (proc.stdout or "")[:500],
        "stderr": (proc.stderr or "")[:500],
        "detail": (
            f"{resolved_kind} blocked canary read (exit {proc.returncode})"
            if blocked
            else f"{resolved_kind} FAILED to block canary (leak or success)"
        ),
    }


def muse_kind_for(detected: str) -> str:
    """Muse runs under bwrap or not at all (docker cannot run the host muse binary)."""
    return "bwrap" if detected == "bwrap" else "none"


def muse_workspace_root(work: Path, muse_kind: str) -> str:
    """The fixer workspace path as Muse Code sees it (bwrap binds it at /fixer)."""
    return "/fixer" if muse_kind == "bwrap" else str(work.resolve())


def run_muse_sandboxed(
    prompt: str,
    *,
    work: Path,
    env: Mapping[str, str] | None = None,
    timeout: int,
    require_sandbox: bool = False,
    detected: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict]:
    """Run `muse exec` under bwrap when available; else host with env scrub.

    Docker is not used for Muse (image would need a Linux muse CLI). On Darwin,
    kind stays none unless bwrap exists. Pass ``detected`` (from detect_sandbox) when the
    caller already probed, so the workspace path it prepared matches the sandbox used.
    """
    kind = detected if detected is not None else detect_sandbox()
    # Prefer bwrap for Muse; docker cannot run the host muse binary on macOS.
    muse_kind = muse_kind_for(kind)
    if require_sandbox and muse_kind == "none":
        raise SystemExit(
            "--require-sandbox needs bubblewrap (bwrap) on PATH to confine Muse Code"
        )
    argv = ["muse", "exec", "--disable-approval", "--trust-workspace", prompt]
    meta = {"kind": muse_kind, "requireSandbox": require_sandbox, "detect": kind}
    if muse_kind == "bwrap":
        proc = run_sandboxed(argv, work=work, env=env, network=True, kind="bwrap", timeout=timeout)
    else:
        proc = subprocess.run(
            argv,
            cwd=str(work),
            capture_output=True,
            text=True,
            env=dict(env) if env is not None else muse_subprocess_env(),
            timeout=timeout,
        )
    return proc, meta


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--probe", type=Path, help="fixer-work path for canary probe")
    p.add_argument("--canary", type=Path, help="absolute canary file outside the mount")
    p.add_argument("--require-sandbox", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    kind = detect_sandbox()
    if args.require_sandbox and kind == "none":
        print("sandbox unavailable (need bwrap or docker)", file=sys.stderr)
        return 2
    if args.probe and args.canary:
        result = probe_blocked_canary_read(args.probe, args.canary, kind=kind)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(result["detail"])
        if kind != "none" and not result["blocked"]:
            return 1
        return 0
    print(f"sandbox kind={kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
