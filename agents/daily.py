"""Daily end-to-end agents film (from Oct 28 playbook commitment).

    python3 -m agents.daily --out runs/daily --mode offline|auto|live

Exit codes:
  0 — film PASS
  1 — film FAIL (verification/trust/offline path failed)
  2 — SKIPPED (live path unavailable; no invented Meta spend)

Offline (default for automation / CI schedule): trust canary + offline loop (1 run).
Auto: live prove when muse+key ready, else offline.
Live: require muse+key; exit 2 if missing.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from agents.keys import load_dotenv, muse_code_ready, resolve_mode
from agents.loop import main as loop_main
from agents.prove_live import main as prove_live_main
from agents.sandbox import detect_sandbox
from agents.trust import run_trust_check

EXIT_CODES = {
    0: "PASS",
    1: "FAIL",
    2: "SKIPPED (no invented Meta spend)",
}


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog="Exit codes: " + "; ".join(f"{k}={v}" for k, v in EXIT_CODES.items()),
    )
    p.add_argument("--out", type=Path, default=Path("runs/daily"))
    p.add_argument("--mode", choices=("offline", "auto", "live"), default="offline")
    p.add_argument("--require-sandbox", action="store_true")
    args = p.parse_args(argv)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    mode = args.mode
    if mode == "auto":
        mode = "live" if muse_code_ready() else "offline"

    report: dict = {
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "requestedMode": args.mode,
        "effectiveMode": mode,
        "sandboxDetect": detect_sandbox(),
        "exitCodes": EXIT_CODES,
    }

    if args.require_sandbox and detect_sandbox() == "none":
        report["status"] = "skipped"
        report["detail"] = "--require-sandbox needs bwrap or docker"
        _write(out, report, "# Daily E2E\n\nSKIPPED — sandbox required but unavailable.\n")
        return 2

    if mode == "live":
        if not muse_code_ready():
            report["status"] = "skipped"
            report["detail"] = "live mode needs muse + META_API_KEY"
            _write(out, report, "# Daily E2E\n\nSKIPPED — live Muse unavailable (no invented spend).\n")
            return 2
        prove_code = prove_live_main(["--out", str(out / "prove")])
        report["proveExit"] = prove_code
        if prove_code == 2:
            report["status"] = "skipped"
            _write(out, report, "# Daily E2E\n\nSKIPPED — prove_live skipped.\n")
            return 2
        if prove_code != 0:
            report["status"] = "fail"
            _write(out, report, f"# Daily E2E\n\nFAIL — prove_live exit {prove_code}\n")
            return 1
        loop_code = loop_main(["--out", str(out / "loop"), "--mode", "offline", "--runs", "1"])
        report["loopExit"] = loop_code
        report["status"] = "pass" if loop_code == 0 else "fail"
        _write(
            out, report,
            f"# Daily E2E\n\nLIVE prove exit={prove_code}; offline loop exit={loop_code}\n"
            f"Overall: {report['status'].upper()}\n",
        )
        return 0 if loop_code == 0 else 1

    trust = run_trust_check(out / "trust", require_sandbox=args.require_sandbox)
    report["trustOk"] = trust.get("ok")
    if not trust.get("ok"):
        report["status"] = "fail"
        _write(out, report, "# Daily E2E\n\nFAIL — trust beat\n")
        return 1

    loop_argv = ["--out", str(out / "loop"), "--mode", "offline", "--runs", "1"]
    if args.require_sandbox:
        loop_argv.append("--require-sandbox")
    loop_code = loop_main(loop_argv)
    report["loopExit"] = loop_code
    resolved = resolve_mode("offline")
    report["modeResolution"] = resolved
    if resolved.get("use_muse"):
        report["status"] = "fail"
        report["detail"] = "offline mode must not use Muse"
        _write(out, report, "# Daily E2E\n\nFAIL — offline invented Muse\n")
        return 1
    report["status"] = "pass" if loop_code == 0 else "fail"
    morning = out / "loop" / "morning-report.md"
    _write(
        out, report,
        "\n".join([
            "# Daily E2E",
            "",
            "- Mode: offline",
            f"- Trust: {'PASS' if trust.get('ok') else 'FAIL'}",
            f"- Loop exit: {loop_code}",
            f"- Sandbox detect: `{report['sandboxDetect']}`",
            f"- Morning: `{morning}`" if morning.is_file() else "- Morning: (missing)",
            f"- Overall: {report['status'].upper()}",
            "",
            "Exit codes: 0=PASS, 1=FAIL, 2=SKIPPED (no invented Meta spend).",
            "",
        ]),
    )
    print((out / "daily.md").read_text(encoding="utf-8"))
    return 0 if loop_code == 0 else 1


def _write(out: Path, report: dict, md: str) -> None:
    (out / "daily.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out / "daily.md").write_text(md, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
