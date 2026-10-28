"""Gate 2: Muse Code (screenshot judge) vs Nightshift verifier.

    # Offline (CI-safe): Nightshift arm + Muse skipped
    python3 -m agents.bench_compare --out runs/bench-compare

    # Live Muse screenshot judge (spends Meta credit)
    python3 -m agents.bench_compare --out runs/bench-compare --live-muse

    # Replay a canned muse.log (tests / filmed offline)
    python3 -m agents.bench_compare --out runs/bench-compare \\
        --fixture-muse path/to/muse.log

Exit 0 when Nightshift passes; with --live-muse / --fixture-muse also requires a
parseable Muse decision (never invents accept).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from agents.gate1 import main as gate1_main
from agents.keys import load_dotenv
from agents.muse_judge import (
    DEFAULT_INSTRUCTION,
    PROMPT_POLICY,
    file_sha256,
    run_muse_judge,
)
from harness.run import REPO
from nightshift.contracts import validate

FORMAT = "nightshift.bench-compare/v0"
CASE_ID = "physics-fall-through/v1-fix-collision-mask"
DEFAULT_BEFORE = REPO / "agents" / "fixtures" / "frames" / "before-fall.png"
DEFAULT_AFTER = REPO / "agents" / "fixtures" / "frames" / "after-fixed.png"


def _nightshift_arm(out: Path, *, skip_harness: bool) -> dict:
    gate_out = out / "nightshift"
    argv = [
        "--out", str(gate_out),
        "--candidate-patch",
        str(REPO / "agents" / "fixtures" / "fix-collision-mask.patch"),
    ]
    if skip_harness:
        argv.extend([
            "--skip-harness",
            "--observations",
            str(REPO / "agents" / "fixtures" / "obs-fixed.json"),
        ])
    code = gate1_main(argv)
    verify_path = gate_out / "verify" / "verification.json"
    morning = gate_out / "morning" / "morning-report.md"
    rc_path = gate_out / "morning" / "release-candidate.json"
    decision = None
    public_key = None
    if verify_path.is_file():
        decision = json.loads(verify_path.read_text(encoding="utf-8")).get("decision")
    if rc_path.is_file():
        rc = json.loads(rc_path.read_text(encoding="utf-8"))
        public_key = rc.get("publicKey")
        validate(rc, "release-candidate")
    return {
        "name": "nightshift",
        "ok": code == 0 and decision == "accept",
        "decision": decision,
        "exitCode": code,
        "gateOut": str(gate_out),
        "morning": str(morning) if morning.is_file() else None,
        "publicKey": public_key,
        "detail": (
            "Nightshift fixture fix → verifier accept + Ed25519 RC"
            if code == 0 and decision == "accept"
            else f"Nightshift arm failed exit={code} decision={decision}"
        ),
    }


def _muse_screenshots_arm(
    out: Path,
    *,
    live: bool,
    fixture_log: Path | None,
    before: Path,
    after: Path,
    instruction: str,
) -> dict:
    """Muse Code judges the same before/after frames from screenshots alone."""
    slot = out / "muse-screenshots"
    slot.mkdir(parents=True, exist_ok=True)
    note = slot / "README.md"
    note.write_text(
        "\n".join([
            "# Muse Code screenshot-judge arm",
            "",
            f"- Prompt policy: `{PROMPT_POLICY}`",
            "- Same before/after frames as the Nightshift film",
            "- Muse sees images + plain English only (no Nightshift specs)",
            "- Record `muse.log` + `judge.json`; never forge accept without a log",
            "",
        ]) + "\n",
        encoding="utf-8",
    )
    if not live and fixture_log is None:
        return {
            "name": "muse-screenshots",
            "ok": None,
            "skipped": True,
            "decision": None,
            "detail": "offline — pass --live-muse or --fixture-muse to run the screenshot judge",
            "slot": str(slot),
            "promptPolicy": PROMPT_POLICY,
        }

    judge = run_muse_judge(
        slot,
        before=before,
        after=after,
        instruction=instruction,
        fixture_log=fixture_log,
    )
    if judge.get("skipped"):
        return {
            "name": "muse-screenshots",
            "ok": False,
            "skipped": True,
            "decision": None,
            "detail": judge.get("detail"),
            "slot": str(slot),
            "promptPolicy": PROMPT_POLICY,
        }
    decided = bool(judge.get("ok"))
    decision = judge.get("decision")
    return {
        "name": "muse-screenshots",
        # ok = judge completed with a valid decision (accept|reject|needs-review).
        # accept alone is not required — disagreement with Nightshift is filmed.
        "ok": decided,
        "skipped": False,
        "decision": decision,
        "accepted": decision == "accept" if decided else False,
        "source": judge.get("source"),
        "promptPolicy": judge.get("promptPolicy"),
        "promptSha256": judge.get("promptSha256"),
        "museLog": judge.get("museLog"),
        "detail": judge.get("detail"),
        "slot": str(slot),
        "workFiles": judge.get("workFiles"),
    }


def _agreement(nightshift: dict, muse: dict) -> str | None:
    if muse.get("skipped") or muse.get("decision") is None:
        return None
    nd = nightshift.get("decision")
    md = muse.get("decision")
    if nd is None or md is None:
        return None
    return "agree" if nd == md else "disagree"


def build_compare(
    out: Path,
    *,
    skip_harness: bool = True,
    live_muse: bool = False,
    fixture_muse: Path | None = None,
    before: Path | None = None,
    after: Path | None = None,
    instruction: str = DEFAULT_INSTRUCTION,
) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    before = before or DEFAULT_BEFORE
    after = after or DEFAULT_AFTER
    nightshift = _nightshift_arm(out, skip_harness=skip_harness)
    muse = _muse_screenshots_arm(
        out,
        live=live_muse,
        fixture_log=fixture_muse,
        before=before,
        after=after,
        instruction=instruction,
    )
    agreement = _agreement(nightshift, muse)
    doc = {
        "format": FORMAT,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "case": {
            "caseId": CASE_ID,
            "family": "physics-fall-through",
            "question": instruction,
            "before": str(before),
            "after": str(after),
            "beforeSha256": file_sha256(before) if before.is_file() else None,
            "afterSha256": file_sha256(after) if after.is_file() else None,
            "decisionMeans": {
                "accept": "after frame shows the bug fixed (from screenshots alone)",
                "reject": "after frame still shows the bug / not clearly fixed",
                "needs-review": "images inconclusive",
            },
        },
        "arms": [nightshift, muse],
        "nightshiftOk": bool(nightshift.get("ok")),
        "museOk": muse.get("ok"),
        "agreement": agreement,
        "detail": (
            f"Nightshift vs Muse screenshots ({PROMPT_POLICY}); agreement={agreement}"
            if agreement
            else "Nightshift arm filmed; Muse screenshot arm skipped or incomplete"
        ),
    }
    (out / "bench-compare.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Bench compare — Muse screenshots vs Nightshift",
        "",
        f"- Generated: `{doc['generatedAt']}`",
        f"- Case: `{doc['case']['caseId']}`",
        f"- Nightshift: {'PASS' if nightshift.get('ok') else 'FAIL'} — {nightshift.get('detail')}",
    ]
    if nightshift.get("publicKey"):
        lines.append(f"- Nightshift RC public key: `{nightshift['publicKey']}`")
    if muse.get("skipped"):
        muse_label = "SKIPPED"
    elif muse.get("ok"):
        # Valid decision — not a Nightshift-style "PASS win"; label the decision explicitly.
        muse_label = f"DECIDED ({muse.get('decision')})"
    else:
        muse_label = "FAIL"
    lines.append(f"- Muse screenshots: {muse_label} — {muse.get('detail')}")
    if agreement:
        lines.append(
            f"- Agreement: `{agreement}` "
            f"(Nightshift `{nightshift.get('decision')}` vs Muse `{muse.get('decision')}`)"
        )
    lines.append("")
    (out / "bench-compare.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return doc


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=Path("runs/bench-compare"))
    p.add_argument("--harness", action="store_true", help="Godot replay for Nightshift arm")
    p.add_argument("--live-muse", action="store_true",
                   help="run Muse screenshot judge (requires META_API_KEY + muse)")
    p.add_argument("--fixture-muse", type=Path,
                   help="canned muse.log for the screenshot judge (tests / offline replay)")
    p.add_argument("--before", type=Path, default=DEFAULT_BEFORE)
    p.add_argument("--after", type=Path, default=DEFAULT_AFTER)
    p.add_argument("--instruction", default=DEFAULT_INSTRUCTION)
    args = p.parse_args(argv)
    if args.live_muse and args.fixture_muse:
        print("pass only one of --live-muse / --fixture-muse", file=sys.stderr)
        return 1
    doc = build_compare(
        args.out,
        skip_harness=not args.harness,
        live_muse=args.live_muse,
        fixture_muse=args.fixture_muse,
        before=args.before,
        after=args.after,
        instruction=args.instruction,
    )
    print((args.out / "bench-compare.md").read_text(encoding="utf-8"))
    if not doc.get("nightshiftOk"):
        return 1
    if args.live_muse or args.fixture_muse:
        muse = next(a for a in doc["arms"] if a["name"] == "muse-screenshots")
        if muse.get("ok") is not True:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
