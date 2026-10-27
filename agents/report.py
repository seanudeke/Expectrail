"""Morning report: before/after, diff summary, verification, signed-RC pointer.

    python3 -m agents.report --verification runs/verify/verification.json \\
        --candidate runs/fix/candidate.patch --out runs/morning \\
        [--before frames/f00000008.png] [--after frames/f00000008.png]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from nightshift.contracts import load


def _fake_sign(payload: bytes, key_material: bytes) -> str:
    """Detached signature placeholder (demo only). Real keys stay off the fixer host."""
    return hashlib.sha256(key_material + payload).hexdigest()


def build_report(
    *,
    verification: dict,
    candidate: Path | None,
    out: Path,
    before: list[Path] | None = None,
    after: list[Path] | None = None,
    unresolved: list[str] | None = None,
    signing_key_path: Path | None = None,
) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    decision = verification["decision"]
    lines = [
        "# Nightshift morning report",
        "",
        f"**Decision:** `{decision}`",
        f"**Request:** `{verification['candidate'].get('request', '')}`",
        f"**Attempt:** {verification['candidate']['attempt']}",
        f"**Candidate patch sha256:** `{verification['candidate']['patchSha256']}`",
        "",
        "## Checks",
    ]
    for c in verification.get("checks", []):
        lines.append(f"- `{c['kind']}` / `{c['spec']}` on `{c['route']}` → **{c['result']}**")
    lines.extend(["", "## Reasons"])
    for r in verification.get("reasons", []):
        lines.append(f"- {r}")

    if before or after:
        lines.extend(["", "## Before / after frames"])
        for p in before or []:
            lines.append(f"- before: `{p}`")
        for p in after or []:
            lines.append(f"- after: `{p}`")

    if candidate and candidate.exists():
        lines.extend(["", "## Candidate diff (head)", "```diff", *candidate.read_text(encoding="utf-8").splitlines()[:80], "```"])

    unresolved = unresolved or ([] if decision == "accept" else list(verification.get("reasons", [])))
    lines.extend(["", "## Unresolved for a human"])
    if unresolved:
        for u in unresolved:
            lines.append(f"- {u}")
    else:
        lines.append("- none")

    payload = json.dumps(verification, sort_keys=True, separators=(",", ":")).encode("utf-8")
    key_bytes = b"nightshift-demo-fake-signing-key"
    key_note = "demo-fake-key"
    if signing_key_path and signing_key_path.exists():
        key_bytes = signing_key_path.read_bytes()
        key_note = str(signing_key_path)
    signature = _fake_sign(payload, key_bytes)
    rc = {
        "format": "nightshift.release-candidate/v0",
        "verificationSha256": hashlib.sha256(payload).hexdigest(),
        "decision": decision,
        "signature": signature,
        "signingKey": key_note,
        "candidatePatchSha256": verification["candidate"]["patchSha256"],
    }
    (out / "release-candidate.json").write_text(json.dumps(rc, indent=2) + "\n", encoding="utf-8")
    lines.extend([
        "",
        "## Signed release candidate",
        f"- file: `release-candidate.json`",
        f"- verification sha256: `{rc['verificationSha256']}`",
        f"- signature: `{signature[:16]}…`",
        f"- signing material: `{key_note}` (never mounted into the fixer workspace)",
        "",
    ])
    text = "\n".join(lines) + "\n"
    (out / "morning-report.md").write_text(text, encoding="utf-8")
    summary = {
        "decision": decision,
        "report": "morning-report.md",
        "releaseCandidate": "release-candidate.json",
        "verificationSha256": rc["verificationSha256"],
        "candidateSha256": verification["candidate"]["patchSha256"],
        "unresolved": unresolved,
    }
    (out / "morning-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--verification", type=Path, required=True)
    p.add_argument("--candidate", type=Path)
    p.add_argument("--before", type=Path, action="append", default=[])
    p.add_argument("--after", type=Path, action="append", default=[])
    p.add_argument("--signing-key", type=Path, help="verifier-host key only; never in fixer workspace")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    summary = build_report(
        verification=load(args.verification, "verification"),
        candidate=args.candidate,
        out=args.out,
        before=args.before or None,
        after=args.after or None,
        signing_key_path=args.signing_key,
    )
    print(f"{summary['decision']}: {args.out / 'morning-report.md'}")
    return 0 if summary["decision"] == "accept" else 1


if __name__ == "__main__":
    sys.exit(main())
