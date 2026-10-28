"""Morning report: before/after, diff summary, verification, signed-RC pointer.

    python3 -m agents.report --verification runs/verify/verification.json \\
        --candidate runs/fix/candidate.patch --out runs/morning \\
        [--before frames/f00000008.png] [--after frames/f00000008.png]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import sys
from pathlib import Path

from agents.signing import ALGORITHM, generate_run_keys, sign_payload, verify_payload
from nightshift.contracts import ContractError, digest, load, validate


def gameplay_film_stub(morning: dict | None) -> dict | None:
    """Compact per-run gameplay film for overnight summary.json / rollup."""
    if not morning:
        return None
    g = morning.get("gameplay")
    if not isinstance(g, dict):
        return None
    metrics = g.get("metrics") or {}
    return {
        "spec": g.get("spec"),
        "result": g.get("result"),
        "reason": g.get("reason"),
        "source": g.get("source"),
        "minDeltaX": g.get("minDeltaX"),
        "deltaX": metrics.get("deltaX"),
    }


def verify_release_candidate(
    rc: dict,
    verification: dict,
    *,
    key_material: bytes | None = None,
    public_key_b64: str | None = None,
) -> None:
    """Recompute verification digest and verify Ed25519 signature; fail closed on tamper.

    Prefer ``public_key_b64`` (published half). ``key_material`` may be the raw private
    key (32 bytes) for offline tests that only keep the private file.
    """
    validate(rc, "release-candidate")
    payload = json.dumps(verification, sort_keys=True, separators=(",", ":")).encode("utf-8")
    expected_sha = hashlib.sha256(payload).hexdigest()
    if rc.get("verificationSha256") != expected_sha:
        raise ContractError(
            f"release-candidate verificationSha256 mismatch: "
            f"rc={rc.get('verificationSha256')} recomputed={expected_sha}"
        )
    if rc.get("decision") != verification.get("decision"):
        raise ContractError(
            f"release-candidate decision mismatch: rc={rc.get('decision')!r} "
            f"verification={verification.get('decision')!r}"
        )
    pub = public_key_b64 or rc.get("publicKey")
    if not pub:
        raise ContractError("release-candidate missing publicKey")
    if key_material is not None:
        if len(key_material) != 32:
            raise ContractError(
                f"key_material must be 32 raw Ed25519 private bytes (got {len(key_material)})"
            )
        # Re-sign check: private must produce the same signature (wrong key fails).
        expected = sign_payload(payload, key_material)
        if rc.get("signature") != expected:
            raise ContractError("release-candidate signature mismatch for provided key material")
    if not verify_payload(payload, rc.get("signature", ""), pub):
        raise ContractError("release-candidate signature does not verify with publicKey")


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
        frame_digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        out.append({"role": prefix, "path": f"frames/{name}", "sha256": frame_digest, "source": str(src)})
    return out


def _gameplay_check(verification: dict) -> dict | None:
    """Return the single gameplay check, or None. Fail-closed if more than one."""
    found = [c for c in verification.get("checks", []) if c.get("kind") == "gameplay"]
    if len(found) > 1:
        raise ContractError(
            f"verification has {len(found)} gameplay checks; morning binds exactly one"
        )
    return found[0] if found else None


def _bind_gameplay_verdict(doc: dict, check: dict) -> dict:
    """Schema-validate and bind filmed verdict to the gameplay check digest."""
    validate(doc, "gameplay-verdict")
    metrics_min = (doc.get("metrics") or {}).get("minDeltaX")
    if metrics_min is None or float(metrics_min) != float(doc["minDeltaX"]):
        raise ContractError(
            f"gameplay-verdict: metrics.minDeltaX ({metrics_min}) != minDeltaX ({doc['minDeltaX']})"
        )
    check_spec = check.get("spec")
    if check_spec and doc.get("spec") != check_spec:
        raise ContractError(
            f"gameplay-verdict spec mismatch: filmed={doc.get('spec')!r} check={check_spec!r}"
        )
    expected = check.get("verdictSha256")
    if not expected:
        raise ContractError("gameplay check missing verdictSha256; cannot bind filmed verdict")
    actual = digest(doc)
    if actual != expected:
        raise ContractError(
            f"gameplay-verdict digest mismatch: filmed={actual} check={expected}"
        )
    return doc


def _resolve_gameplay_verdict(
    verification: dict,
    *,
    gameplay_verdict: dict | Path | None,
    verification_path: Path | None,
) -> dict | None:
    """Load gameplay verdict for morning.

    Fail-closed when a gameplay check ran but the artifact is missing, schema-invalid,
    or digest-mismatched. Ignore leftover sibling/dict when no gameplay check ran.
    """
    check = _gameplay_check(verification)
    if check is None:
        return None
    if isinstance(gameplay_verdict, dict):
        return _bind_gameplay_verdict(gameplay_verdict, check)
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
        return _bind_gameplay_verdict(load(path, "gameplay-verdict"), check)
    raise FileNotFoundError(
        "verification includes a gameplay check but no gameplay verdict was provided "
        "(pass gameplay_verdict= or place verdict-gameplay.json beside verification.json)"
    )


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

    cand = verification["candidate"]
    request_id = cand.get("request", "")
    request_sha = cand.get("requestSha256")
    lines = [
        "# Nightshift morning report",
        "",
        f"**Decision:** `{decision}`",
        f"**Request:** `{request_id}`",
    ]
    if request_sha:
        lines.append(f"**Request sha256:** `{request_sha}`")
    lines.extend([
        f"**Attempt:** {cand['attempt']}",
        f"**Candidate patch sha256:** `{cand['patchSha256']}`",
        "",
        "## Checks",
    ])
    for c in verification.get("checks", []):
        lines.append(f"- `{c['kind']}` / `{c['spec']}` on `{c['route']}` → **{c['result']}**")
    lines.extend(["", "## Reasons"])
    for r in verification.get("reasons", []):
        lines.append(f"- {r}")

    suite = verification.get("suite")
    if suite:
        early = suite.get("earlyReject")
        if early:
            lines.extend([
                "",
                "## Early reject",
                f"- gate: `{early.get('gate')}`",
                f"- detail: {early.get('detail')}",
            ])
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
    if signing_key_path is None:
        keys = generate_run_keys(out.parent / "verifier-host")
        signing_key_path = keys["privatePathObj"]
    elif not signing_key_path.exists():
        raise FileNotFoundError(
            "morning report requires a verifier-host private key "
            f"(missing {signing_key_path!s}); call agents.signing.generate_run_keys first"
        )
    key_bytes = signing_key_path.read_bytes()
    if len(key_bytes) != 32:
        raise ContractError(
            f"signing key at {signing_key_path} must be 32 raw Ed25519 private bytes "
            f"(got {len(key_bytes)})"
        )
    key_note = str(signing_key_path)
    pub_path = signing_key_path.with_name(signing_key_path.name + ".pub")
    if not pub_path.is_file():
        raise FileNotFoundError(f"public key missing next to private key: {pub_path}")
    public_b64 = base64.b64encode(pub_path.read_bytes()).decode("ascii")
    signature = sign_payload(payload, key_bytes)
    rc = {
        "format": "nightshift.release-candidate/v0",
        "verificationSha256": hashlib.sha256(payload).hexdigest(),
        "decision": decision,
        "signature": signature,
        "signingKey": key_note,
        "algorithm": ALGORITHM,
        "publicKey": public_b64,
        "candidatePatchSha256": cand["patchSha256"],
    }
    if request_id:
        rc["requestId"] = request_id
    if request_sha:
        rc["requestSha256"] = request_sha
    validate(rc, "release-candidate")
    (out / "release-candidate.json").write_text(json.dumps(rc, indent=2) + "\n", encoding="utf-8")
    lines.extend([
        "",
        "## Signed release candidate",
        f"- file: `release-candidate.json`",
        f"- verification sha256: `{rc['verificationSha256']}`",
        f"- algorithm: `{ALGORITHM}`",
        f"- signature: `{signature[:24]}…`",
        f"- public key (published half): `{public_b64}`",
        f"- private key path: `{key_note}` (never mounted into the fixer workspace)",
    ])
    if request_id:
        lines.append(f"- request id: `{request_id}`")
    if request_sha:
        lines.append(f"- request sha256: `{request_sha}`")
    lines.append("")
    text = "\n".join(lines) + "\n"
    (out / "morning-report.md").write_text(text, encoding="utf-8")
    summary = {
        "decision": decision,
        "report": "morning-report.md",
        "releaseCandidate": "release-candidate.json",
        "verificationSha256": rc["verificationSha256"],
        "candidateSha256": cand["patchSha256"],
        "requestId": request_id or None,
        "requestSha256": request_sha,
        "unresolved": unresolved,
        "frames": frame_meta,
        "signingKey": key_note,
        "algorithm": ALGORITHM,
        "publicKey": public_b64,
        "signature": signature,
        "gameplay": gameplay,
    }
    (out / "morning-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def _result_gameplay(result: dict) -> dict | None:
    stub = result.get("gameplay")
    if isinstance(stub, dict):
        return stub
    return gameplay_film_stub(result.get("morning"))


def write_loop_rollup(out: Path, *, summary: dict) -> Path:
    """Top-level filmable rollup beside summary.json after N overnight runs.

    Latest-accept frames are copied under `out/frames/` so embeds stay valid even
    when CI only packages the rollup directory (not every run-NN tree).
    Gameplay reject reasons film from per-run stubs (never invent when morning is null).
    """
    accepted = summary["accepted"]
    runs = summary["runs"]
    cost = summary.get("cost") or {}
    timing = summary.get("timing") or {}
    lines = [
        "# Nightshift overnight morning rollup",
        "",
        f"**Accepted:** {accepted} of {runs}",
        f"**Mode:** `{summary.get('mode', {}).get('mode', 'unknown')}`",
        f"**Verification provenance:** `{summary.get('verificationProvenance', 'unknown')}`",
        f"**Wall-clock ms:** `{timing.get('wallClockMs', 'n/a')}`",
        f"**Cost:** modelCalls=`{cost.get('modelCalls', 'n/a')}` "
        f"costUsd=`{cost.get('costUsd')}` provenance=`{cost.get('costProvenance', 'n/a')}`",
        "",
        "## Per-run",
    ]
    last_accept_frames: list[dict] = []
    last_accept_run = -1
    last_accept_morning: Path | None = None
    latest_reject_gameplay: tuple[int, dict] | None = None
    needs_review_runs: list[tuple[int, dict]] = []
    trust_lines: list[str] = []
    for i, result in enumerate(summary.get("results", [])):
        decision = result.get("decision")
        morning = result.get("morning")
        rel = f"run-{i:02d}/morning/morning-report.md"
        err = result.get("error")
        gameplay = _result_gameplay(result)
        trust = result.get("trust")
        run_ms = (result.get("timing") or {}).get("wallClockMs")
        triage_source = result.get("triageSource")
        fixer_source = result.get("fixerSource")
        line = f"- run-{i:02d}: `{decision}`"
        if morning:
            line += f" → [{rel}]({rel})"
        if triage_source:
            line += f" triage=`{triage_source}`"
        if fixer_source:
            line += f" fixer=`{fixer_source}`"
        if gameplay:
            line += f" gameplay=`{gameplay.get('result')}` reason={gameplay.get('reason')}"
        if run_ms is not None:
            line += f" ({run_ms}ms)"
        if isinstance(trust, dict):
            trust_ok = trust.get("ok")
            trust_label = "PASS" if trust_ok else "FAIL"
            line += f" trust=`{trust_label}`"
            trust_rel = f"run-{i:02d}/trust/trust-evidence.md"
            trust_lines.append(f"- run-{i:02d}: `{trust_label}` → [{trust_rel}]({trust_rel})")
        if err:
            line += f" ({err})"
        lines.append(line)
        if decision == "accept" and morning and morning.get("frames"):
            last_accept_frames = morning["frames"]
            last_accept_run = i
            last_accept_morning = out / f"run-{i:02d}" / "morning"
        if decision != "accept" and gameplay and gameplay.get("result") == "fail":
            latest_reject_gameplay = (i, gameplay)
        if decision == "needs-review":
            needs_review_runs.append((i, result))

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
        if latest_reject_gameplay is not None:
            idx, g = latest_reject_gameplay
            lines.extend([
                "",
                "## Gameplay",
                f"(latest gameplay fail: run-{idx:02d})",
                f"- spec: `{g.get('spec')}`",
                f"- result: `{g.get('result')}`",
                f"- reason: {g.get('reason')}",
                f"- source: `{g.get('source')}`",
                f"- minDeltaX: `{g.get('minDeltaX')}`",
                f"- deltaX: `{g.get('deltaX')}`",
            ])
        if needs_review_runs:
            lines.extend(["", "## Needs-review"])
            for idx, result in needs_review_runs:
                morning = result.get("morning") or {}
                unresolved = morning.get("unresolved") or []
                detail = unresolved[0] if unresolved else (result.get("error") or "needs review")
                lines.append(f"- run-{idx:02d}: {detail}")

    if trust_lines:
        lines.extend(["", "## Trust", *trust_lines])

    out.mkdir(parents=True, exist_ok=True)
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
