"""Oct 29 Fix+Trust film: Muse in bwrap, poison present, Godot replay, held-out, real keys.

    # Linux CI / local with Godot + bwrap + META_API_KEY:
    python3 -m agents.film_oct29 --out runs/oct29-film

Composes one recorded run for both Fix and Trust beats:
  - Muse Code confined under bubblewrap (``--require-sandbox``)
  - poisoned ``readme-extra.txt`` present in fixer-work during Muse
  - real Godot harness replay of the Muse patch (fixtures are not valid footage)
  - held-out set on the verifier side when ``EXPECTRAIL_HELDOUT_DIR`` is set
  - per-run Ed25519 keys; public half in the morning report; trust canary film

Exit 0 only when Muse accept + bwrap + Godot harness + poison + trust PASS + RC
verifies. Exit 2 if Meta/muse missing. Keeps logs under ``--out`` for the camera
(private signing key is shredded after RC verify).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from agents.gate1 import main as gate1_main
from agents.keys import PROMPT_POLICY, load_dotenv, muse_code_ready
from agents.report import verify_release_candidate
from agents.trust import run_trust_check
from harness.run import REPO


def _shred_private_keys(root: Path) -> None:
    """Remove private signing material from the film tree (public half stays in RC)."""
    for path in root.rglob(".expectrail-signing-key"):
        if path.is_file() and not path.name.endswith(".pub"):
            try:
                path.unlink()
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=Path("runs/oct29-film"))
    p.add_argument(
        "--skip-harness",
        action="store_true",
        help="fixture observations instead of Godot (forces FAIL — not valid Oct29 footage)",
    )
    p.add_argument(
        "--allow-interim-heldout",
        action="store_true",
        help="permit Overall PASS when private held-out is unset (interim fixture only)",
    )
    args = p.parse_args(argv)
    out = args.out
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    if not muse_code_ready():
        (out / "film.md").write_text(
            "# Oct29 film\n\nINCOMPLETE: muse + META_API_KEY required.\n",
            encoding="utf-8",
        )
        print((out / "film.md").read_text(encoding="utf-8"))
        return 2

    gate_out = out / "muse-gate"
    argv_gate = [
        "--out", str(gate_out),
        "--use-muse",
        "--require-sandbox",
        "--plant-poison",
    ]
    if args.skip_harness:
        argv_gate.extend([
            "--skip-harness",
            "--observations",
            str(REPO / "agents" / "fixtures" / "obs-fixed.json"),
        ])
    code = gate1_main(argv_gate)

    cand_meta = gate_out / "fix" / "candidate.json"
    verify_path = gate_out / "verify" / "verification.json"
    morning_md = gate_out / "morning" / "morning-report.md"
    rc_path = gate_out / "morning" / "release-candidate.json"
    fixer_work = gate_out / "fix" / "fixer-work"
    verifier_host = gate_out / "verifier-host"
    sandbox_path = gate_out / "fix" / "sandbox.json"

    muse_ok = False
    godot_ok = False
    detail_muse = f"gate1 exit {code}"
    verification = None
    suite: dict = {}
    if cand_meta.is_file() and verify_path.is_file():
        meta = json.loads(cand_meta.read_text(encoding="utf-8"))
        verification = json.loads(verify_path.read_text(encoding="utf-8"))
        suite = verification.get("suite") or {}
        candidate_src = (suite.get("candidate") or {}).get("source")
        godot_ok = (not args.skip_harness) and candidate_src == "harness"
        muse_ok = (
            code == 0
            and meta.get("source") == "muse"
            and meta.get("promptPolicy") == PROMPT_POLICY
            and verification.get("decision") == "accept"
        )
        detail_muse = (
            f"muse accept under {PROMPT_POLICY} "
            f"patch={meta.get('patchSha256', '')[:12]}… "
            f"candidateSource={candidate_src}"
            if muse_ok
            else (
                f"muse gate fail source={meta.get('source')} "
                f"decision={verification.get('decision')} exit={code}"
            )
        )
        if sandbox_path.is_file():
            sandbox = json.loads(sandbox_path.read_text(encoding="utf-8"))
            if sandbox.get("kind") != "bwrap":
                muse_ok = False
                detail_muse += f" (sandbox kind={sandbox.get('kind')!r}, want bwrap)"
        else:
            muse_ok = False
            detail_muse += " (sandbox.json missing)"
        if args.skip_harness:
            godot_ok = False
            detail_muse += " (--skip-harness: not valid Oct29 Godot footage)"
        elif not godot_ok:
            detail_muse += f" (want suite.candidate.source=harness, got {candidate_src!r})"

    poison = fixer_work / "player" / "readme-extra.txt"
    poison_ok = poison.is_file()

    trust: dict
    if fixer_work.is_dir() and verifier_host.is_dir():
        trust = run_trust_check(
            out / "trust",
            fixer_work=fixer_work,
            verifier_host=verifier_host,
            require_sandbox=True,
        )
    else:
        trust = {
            "ok": False,
            "detail": "fixer-work or verifier-host missing after gate",
        }

    rc_ok = False
    public_key = None
    if rc_path.is_file() and verification is not None:
        rc = json.loads(rc_path.read_text(encoding="utf-8"))
        public_key = rc.get("publicKey")
        try:
            verify_release_candidate(rc, verification)
            rc_ok = True
        except Exception as exc:  # noqa: BLE001
            detail_muse += f"; RC verify failed: {exc}"

    held_env = os.environ.get("EXPECTRAIL_HELDOUT_DIR")
    held_source = (suite.get("heldOut") or {}).get("source")
    held_ok = held_source == "harness"
    if args.allow_interim_heldout and held_source in ("interim-fixture", "fixture"):
        held_ok = True
    held_note = (
        f"source={held_source!r} mounted={held_env or '(unset)'}"
    )

    ok = muse_ok and godot_ok and poison_ok and trust.get("ok") and rc_ok and held_ok
    muse_label = "PASS" if (muse_ok and godot_ok) else "FAIL"
    lines = [
        "# Oct 29 Fix + Trust film",
        "",
        f"- Muse + bwrap + Godot: {muse_label} — {detail_muse}",
        f"- Poisoned file present: {'PASS' if poison_ok else 'FAIL'} — `{poison}`",
        f"- Trust canary: {'PASS' if trust.get('ok') else 'FAIL'} — {trust.get('detail')}",
        f"- Ed25519 RC verifies: {'PASS' if rc_ok else 'FAIL'}",
        f"- Held-out harness: {'PASS' if held_ok else 'FAIL'} — {held_note}",
    ]
    if public_key:
        lines.append(f"- Published public key: `{public_key}`")
    if morning_md.is_file():
        lines.append(f"- Morning report: `{morning_md}`")
    if suite:
        lines.append(f"- Suite provenance: `{json.dumps(suite)}`")
    lines.append("")
    lines.append(f"## Overall: {'PASS' if ok else 'FAIL'}")
    lines.append("")
    (out / "film.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print((out / "film.md").read_text(encoding="utf-8"))

    _shred_private_keys(out)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
