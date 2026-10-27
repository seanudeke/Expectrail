"""Morning report: before/after, diff summary, verification, signed-RC pointer.

    python3 -m agents.report --verification runs/verify/verification.json \\
        --candidate runs/fix/candidate.patch --out runs/morning \\
        [--before frames/f00000008.png] [--after frames/f00000008.png]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

from nightshift.contracts import load


def _fake_sign(payload: bytes, key_material: bytes) -> str:
    """Detached signature placeholder (demo only). Real keys stay off the fixer host."""
    return hashlib.sha256(key_material + payload).hexdigest()


def _materialize_frames(srcs: list[Path], dest_dir: Path, prefix: str) -> list[dict]:
    """Copy frames into dest_dir; fail closed if any source is missing."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    for i, src in enumerate(srcs):
        if not src.is_file():
            raise FileNotFoundError(f"morning frame missing: {src}")
        name = f"{prefix}-{i:02d}{src.suffix.lower() or '.png'}"
        dest = dest_dir / name
        shutil.copy2(src, dest)
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        out.append({"role": prefix, "path": f"frames/{name}", "sha256": digest, "source": str(src)})
    return out


def _resolve_gameplay_verdict(
    verification: dict,
    *,
    gameplay_verdict: dict | Path | None,
    verification_path: Path | None,
) -> dict | None:
    """Load gameplay verdict for morning. Fail-closed when gameplay check ran but artifact missing."""
    has_gameplay_check = any(c.get("kind") == "gameplay" for c in verification.get("checks", []))
    if isinstance(gameplay_verdict, dict):
        return gameplay_verdict
    path: Path | None = None
    if isinstance(gameplay_verdict, Path):
        path = gameplay_verdict
    elif verification_path is not None:
        sibling = verification_path.parent / "verdict-gameplay.json"
        if sibling.is_file():
            path = sibling
    if path is not None:
        if not path.is_file():
            raise FileNotFoundError(f"gameplay verdict missing: {path}")
        from nightshift.contracts import load
        return load(path, "gameplay-verdict")
    if has_gameplay_check:
        raise FileNotFoundError(
            "verification includes a gameplay check but no gameplay verdict was provided "
            "(pass gameplay_verdict= or place verdict-gameplay.json beside verification.json)"
        )
    return None


def build_report(
    *,
    verification: dict,
    candidate: Path | None,
    out: Path,
    before: list[Path] | None = None,
    after: list[Path] | None = None,
    unresolved: list[str] | None = None,
    signing_key_path: Path | None = None,
    gameplay_verdict: dict | Path | None = None,
    verification_path: Path | None = None,
) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    decision = verification["decision"]
    before = list(before or [])
    after = list(after or [])
    frame_meta: list[dict] = []
    if before or after:
        frames_dir = out / "frames"
        frame_meta.extend(_materialize_frames(before, frames_dir, "before"))
        frame_meta.extend(_materialize_frames(after, frames_dir, "after"))

    gameplay = _resolve_gameplay_verdict(
        verification,
        gameplay_verdict=gameplay_verdict,
        verification_path=verification_path,
    )

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

    suite = verification.get("suite")
    if suite:
        lines.extend(["", "## Suite provenance"])
        for label, key in (("candidate", "candidate"), ("clean", "clean"), ("held-out", "heldOut")):
            arm = suite.get(key) or {}
            src = arm.get("source", "unknown")
            path = arm.get("path")
            sha = arm.get("observationsSha256")
            detail = arm.get("detail")
            line = f"- {label}: source=`{src}`"
            if path:
                line += f" path=`{path}`"
            if sha:
                line += f" obsSha256=`{sha[:16]}…`"
            if detail:
                line += f" ({detail})"
            lines.append(line)

    if gameplay is not None:
        metrics = gameplay.get("metrics") or {}
        lines.extend([
            "",
            "## Gameplay",
            f"- result: `{gameplay.get('result')}`",
            f"- reason: {gameplay.get('reason')}",
            f"- source: `{gameplay.get('source')}`",
            f"- minDeltaX: `{gameplay.get('minDeltaX')}`",
            f"- deltaX: `{metrics.get('deltaX')}`",
        ])
        if "endOnFloor" in metrics:
            lines.append(f"- endOnFloor: `{metrics.get('endOnFloor')}`")
        if "belowStreak" in metrics:
            lines.append(f"- belowStreak: `{metrics.get('belowStreak')}`")
        if "sampleCount" in metrics:
            lines.append(f"- sampleCount: `{metrics.get('sampleCount')}`")

    if frame_meta:
        lines.extend(["", "## Before / after frames"])
        for meta in frame_meta:
            lines.append(f"- {meta['role']}: `{meta['path']}` (sha256 `{meta['sha256'][:16]}…`)")
            lines.append(f"  ![{meta['role']}]({meta['path']})")

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
        "frames": frame_meta,
        "signingKey": key_note,
        "signature": signature,
        "gameplay": gameplay,
    }
    (out / "morning-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def write_loop_rollup(out: Path, *, summary: dict) -> Path:
    """Top-level filmable rollup beside summary.json after N overnight runs.

    Latest-accept frames are copied under `out/frames/` so embeds stay valid even
    when CI only packages the rollup directory (not every run-NN tree).
    """
    accepted = summary["accepted"]
    runs = summary["runs"]
    lines = [
        "# Nightshift overnight morning rollup",
        "",
        f"**Accepted:** {accepted} of {runs}",
        f"**Mode:** `{summary.get('mode', {}).get('mode', 'unknown')}`",
        f"**Verification provenance:** `{summary.get('verificationProvenance', 'unknown')}`",
        "",
        "## Per-run",
    ]
    last_accept_frames: list[dict] = []
    last_accept_run = -1
    last_accept_morning: Path | None = None
    for i, result in enumerate(summary.get("results", [])):
        decision = result.get("decision")
        morning = result.get("morning")
        rel = f"run-{i:02d}/morning/morning-report.md"
        err = result.get("error")
        line = f"- run-{i:02d}: `{decision}`"
        if morning:
            line += f" → [{rel}]({rel})"
        if err:
            line += f" ({err})"
        lines.append(line)
        if decision == "accept" and morning and morning.get("frames"):
            last_accept_frames = morning["frames"]
            last_accept_run = i
            last_accept_morning = out / f"run-{i:02d}" / "morning"

    if accepted == runs and last_accept_frames and last_accept_morning is not None:
        rollup_frames = out / "frames"
        if rollup_frames.exists():
            shutil.rmtree(rollup_frames)
        rollup_frames.mkdir(parents=True, exist_ok=True)
        lines.extend(["", "## Latest accept frames", f"(from run-{last_accept_run:02d})"])
        for meta in last_accept_frames:
            src = last_accept_morning / meta["path"]
            if not src.is_file():
                raise FileNotFoundError(f"rollup frame missing: {src}")
            dest_name = Path(meta["path"]).name
            dest = rollup_frames / dest_name
            shutil.copy2(src, dest)
            rel = f"frames/{dest_name}"
            lines.append(f"- {meta['role']}: `{rel}`")
            lines.append(f"  ![{meta['role']}]({rel})")
    elif accepted < runs:
        lines.extend([
            "",
            "## Unresolved",
            "- overnight did not accept every run; see per-run errors and morning reports",
        ])

    path = out / "morning-report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--verification", type=Path, required=True)
    p.add_argument("--candidate", type=Path)
    p.add_argument("--before", type=Path, action="append", default=[])
    p.add_argument("--after", type=Path, action="append", default=[])
    p.add_argument("--signing-key", type=Path, help="verifier-host key only; never in fixer workspace")
    p.add_argument("--gameplay-verdict", type=Path,
                   help="trace-native gameplay verdict (default: sibling verdict-gameplay.json)")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    summary = build_report(
        verification=load(args.verification, "verification"),
        candidate=args.candidate,
        out=args.out,
        before=args.before or None,
        after=args.after or None,
        signing_key_path=args.signing_key,
        gameplay_verdict=args.gameplay_verdict,
        verification_path=args.verification,
    )
    print(f"{summary['decision']}: {args.out / 'morning-report.md'}")
    return 0 if summary["decision"] == "accept" else 1


if __name__ == "__main__":
    sys.exit(main())
