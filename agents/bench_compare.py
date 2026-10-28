"""Gate 2 scaffold: Muse Code (screenshot judge) vs Pixel Proof verifier.

Builds a comparison contract and runner shell. Does **not** invent Muse wins —
live Muse screenshot judging stays behind ``--live-muse`` and META_API_KEY.

    # Offline scaffold (CI-safe): Pixel Proof side only + empty Muse slot
    python3 -m agents.bench_compare --out runs/bench-compare

    # Later (Sean + Taofeek): fill Muse arm when the screenshot-judge prompt lands
    python3 -m agents.bench_compare --out runs/bench-compare --live-muse

Exit 0 when the comparison document validates and the Pixel Proof arm completes.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from agents.gate1 import main as gate1_main
from agents.keys import load_dotenv, muse_code_ready
from harness.run import REPO
from pixelproof.contracts import validate

FORMAT = "pixelproof.bench-compare/v0"


def _pixelproof_arm(out: Path, *, skip_harness: bool) -> dict:
    gate_out = out / "pixelproof"
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
        "name": "pixelproof",
        "ok": code == 0 and decision == "accept",
        "decision": decision,
        "exitCode": code,
        "gateOut": str(gate_out),
        "morning": str(morning) if morning.is_file() else None,
        "publicKey": public_key,
        "detail": (
            "Pixel Proof fixture fix → verifier accept + Ed25519 RC"
            if code == 0 and decision == "accept"
            else f"Pixel Proof arm failed exit={code} decision={decision}"
        ),
    }


def _muse_screenshots_arm(out: Path, *, live: bool) -> dict:
    """Placeholder for Muse Code judging its own screenshots.

    Live path is intentionally incomplete until Sean's prompt/runner lands —
    we refuse to invent a pass.
    """
    slot = out / "muse-screenshots"
    slot.mkdir(parents=True, exist_ok=True)
    note = slot / "README.md"
    note.write_text(
        "\n".join([
            "# Muse Code screenshot-judge arm",
            "",
            "Gate 2 comparison slot. Fill with Sean's Muse-screenshots baseline:",
            "- same bug / frames as the Pixel Proof arm",
            "- Muse asked to accept/reject from screenshots alone",
            "- record muse.log + decision; never forge accept offline",
            "",
        ]) + "\n",
        encoding="utf-8",
    )
    if not live:
        return {
            "name": "muse-screenshots",
            "ok": None,
            "skipped": True,
            "detail": "offline scaffold only — pass --live-muse when the judge prompt is ready",
            "slot": str(slot),
        }
    if not muse_code_ready():
        return {
            "name": "muse-screenshots",
            "ok": False,
            "skipped": True,
            "detail": "META_API_KEY + muse required for --live-muse screenshot judge",
            "slot": str(slot),
        }
    return {
        "name": "muse-screenshots",
        "ok": False,
        "skipped": False,
        "detail": (
            "live Muse screenshot judge not wired yet (Sean + Taofeek); "
            "refusing to invent a verdict"
        ),
        "slot": str(slot),
    }


def build_compare(
    out: Path,
    *,
    skip_harness: bool = True,
    live_muse: bool = False,
) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    pixelproof = _pixelproof_arm(out, skip_harness=skip_harness)
    muse = _muse_screenshots_arm(out, live=live_muse)
    doc = {
        "format": FORMAT,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "arms": [pixelproof, muse],
        "pixelproofOk": bool(pixelproof.get("ok")),
        "museOk": muse.get("ok"),
        "detail": (
            "Pixel Proof arm filmed; Muse screenshot arm is a scaffold until the judge lands"
        ),
    }
    (out / "bench-compare.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Bench compare — Muse screenshots vs Pixel Proof",
        "",
        f"- Generated: `{doc['generatedAt']}`",
        f"- Pixel Proof: {'PASS' if pixelproof.get('ok') else 'FAIL'} — {pixelproof.get('detail')}",
    ]
    if pixelproof.get("publicKey"):
        lines.append(f"- Pixel Proof RC public key: `{pixelproof['publicKey']}`")
    muse_label = "SKIPPED" if muse.get("skipped") else ("PASS" if muse.get("ok") else "FAIL")
    lines.append(f"- Muse screenshots: {muse_label} — {muse.get('detail')}")
    lines.append("")
    (out / "bench-compare.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return doc


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=Path("runs/bench-compare"))
    p.add_argument("--harness", action="store_true", help="Godot replay for Pixel Proof arm")
    p.add_argument("--live-muse", action="store_true",
                   help="attempt Muse screenshot judge (fails closed until wired)")
    args = p.parse_args(argv)
    doc = build_compare(args.out, skip_harness=not args.harness, live_muse=args.live_muse)
    print((args.out / "bench-compare.md").read_text(encoding="utf-8"))
    if not doc.get("pixelproofOk"):
        return 1
    if args.live_muse:
        muse = next(a for a in doc["arms"] if a["name"] == "muse-screenshots")
        # Refuse a green exit while the Muse arm is unwired or failed.
        if muse.get("ok") is not True:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
