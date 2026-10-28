"""Muse Code screenshot judge (Gate 2 baseline arm).

Muse sees failing/fixed frames and a plain-English instruction — no Nightshift
specs, verdicts, held-out routes, or evaluator. Parses a single line decision.

    python3 -m agents.muse_judge --out runs/muse-judge \\
        --before agents/fixtures/frames/before-fall.png \\
        --after agents/fixtures/frames/after-fixed.png

Offline / CI: pass ``--fixture-log path`` with a canned muse transcript (never
forge accept without a log). Live requires muse + META_API_KEY.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from agents.keys import load_dotenv, muse_code_ready, muse_subprocess_env
from harness.run import REPO

PROMPT_POLICY = "screenshots-v1"
DECISION_RE = re.compile(
    r"(?im)^\s*DECISION:\s*(accept|reject|needs-review)\s*$"
)
# Work dir may only contain these relative paths (plus directories).
ALLOWED_WORK_RELPATHS = frozenset({"frames/before.png", "frames/after.png"})
DEFAULT_INSTRUCTION = (
    "The player was falling through the ground. Look only at the screenshots. "
    "Did the after frame show the player standing on solid ground instead of "
    "falling through? Answer from the images alone."
)


def prompt_sha256(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_judge_prompt(
    *,
    before_rel: str,
    after_rel: str,
    instruction: str,
) -> str:
    """Plain-English screenshot judge prompt (no structured Nightshift checks)."""
    return f"""You are judging a Godot 2D platformer bug from screenshots alone.

## Instruction
{instruction.strip()}

## Frames (relative to this workspace)
- Before (bug): {before_rel}
- After (candidate): {after_rel}

## Rules
- Open and look at both image files.
- Do not invent file contents you could not open.
- Do not run the game, edit files, or search for tests, specs, keys, or evaluator code.
- Do not use Nightshift contracts, held-out routes, or SAM.

## Output
End your reply with exactly one of these lines (lowercase):
DECISION: accept
DECISION: reject
DECISION: needs-review
"""


def parse_decision(log_text: str) -> str | None:
    """Return accept|reject|needs-review from the last well-formed DECISION line, else None.

    Last-line-wins when multiple valid lines appear (models often revise). Unknown
    tokens, punctuation, or missing lines fail closed (return None).
    """
    matches = list(DECISION_RE.finditer(log_text or ""))
    if not matches:
        return None
    return matches[-1].group(1).lower()


def _work_inventory(work: Path) -> list[str]:
    return sorted(
        p.relative_to(work).as_posix()
        for p in work.rglob("*")
        if p.is_file()
    )


def run_muse_judge(
    out: Path,
    *,
    before: Path,
    after: Path,
    instruction: str = DEFAULT_INSTRUCTION,
    fixture_log: Path | None = None,
    timeout: int = 600,
) -> dict:
    """Run Muse Code as a screenshot-only judge; fail closed without a parseable decision."""
    out.mkdir(parents=True, exist_ok=True)
    if not before.is_file() or not after.is_file():
        result = {
            "ok": False,
            "skipped": False,
            "decision": None,
            "source": None,
            "detail": f"before/after frames missing: before={before} after={after}",
            "promptPolicy": PROMPT_POLICY,
        }
        (out / "judge.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    if fixture_log is not None and not fixture_log.is_file():
        result = {
            "ok": False,
            "skipped": False,
            "decision": None,
            "source": "fixture-log",
            "detail": f"fixture log missing: {fixture_log}",
            "promptPolicy": PROMPT_POLICY,
        }
        (out / "judge.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result

    work = out / "work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    before_rel = "frames/before.png"
    after_rel = "frames/after.png"
    (work / "frames").mkdir()
    shutil.copy2(before, work / before_rel)
    shutil.copy2(after, work / after_rel)
    inventory = _work_inventory(work)
    if set(inventory) != ALLOWED_WORK_RELPATHS:
        result = {
            "ok": False,
            "skipped": False,
            "decision": None,
            "source": None,
            "detail": f"work dir leak or missing frames: {inventory}",
            "workFiles": inventory,
            "promptPolicy": PROMPT_POLICY,
        }
        (out / "judge.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result

    prompt = build_judge_prompt(
        before_rel=before_rel, after_rel=after_rel, instruction=instruction,
    )
    # Template must not name Nightshift artifact files (may say "do not use held-out").
    template_blob = build_judge_prompt(
        before_rel=before_rel, after_rel=after_rel, instruction="x",
    ).lower()
    for tok in (
        "verification.json", "repair-request.json", "obs-fixed.json",
        "release-candidate.json", "nightshift.verification",
    ):
        if tok in template_blob:
            raise AssertionError(f"screenshots-v1 template leaked {tok!r}")

    prompt_path = out / "muse-prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    meta: dict = {
        "promptPolicy": PROMPT_POLICY,
        "promptSha256": prompt_sha256(prompt),
        "before": str(before),
        "after": str(after),
        "beforeSha256": file_sha256(before),
        "afterSha256": file_sha256(after),
        "instruction": instruction,
        "workFiles": inventory,
    }

    if fixture_log is not None:
        log_text = fixture_log.read_text(encoding="utf-8")
        source = "fixture-log"
        exit_code = 0
    elif not muse_code_ready():
        detail = "muse on PATH and META_API_KEY required for live screenshot judge"
        result = {
            "ok": False,
            "skipped": True,
            "decision": None,
            "source": None,
            "detail": detail,
            **meta,
        }
        (out / "judge.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    else:
        proc = subprocess.run(
            ["muse", "exec", "--disable-approval", "--trust-workspace", prompt],
            cwd=str(work),
            capture_output=True,
            text=True,
            env=muse_subprocess_env(),
            timeout=timeout,
        )
        log_text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        source = "muse"
        exit_code = proc.returncode

    log_path = out / "muse.log"
    log_path.write_text(log_text, encoding="utf-8")
    decision = parse_decision(log_text)
    # Fail closed: need a parseable decision AND a successful muse process (live).
    process_ok = exit_code == 0
    parsed_ok = decision in ("accept", "reject", "needs-review")
    ok = parsed_ok and process_ok
    if not process_ok and parsed_ok:
        detail = (
            f"screenshot judge emitted {decision} but muse exit={exit_code} "
            f"(fail closed under {PROMPT_POLICY})"
        )
    elif ok:
        detail = f"screenshot judge {decision} under {PROMPT_POLICY}"
    else:
        detail = f"screenshot judge failed to emit DECISION (source={source} exit={exit_code})"
    result = {
        "ok": ok,
        "skipped": False,
        "decision": decision if ok else None,
        "rawDecision": decision,
        "source": source,
        "exitCode": exit_code,
        "museLog": str(log_path),
        "detail": detail,
        **meta,
    }
    (out / "judge.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=Path("runs/muse-judge"))
    p.add_argument(
        "--before", type=Path,
        default=REPO / "agents" / "fixtures" / "frames" / "before-fall.png",
    )
    p.add_argument(
        "--after", type=Path,
        default=REPO / "agents" / "fixtures" / "frames" / "after-fixed.png",
    )
    p.add_argument("--instruction", default=DEFAULT_INSTRUCTION)
    p.add_argument(
        "--fixture-log", type=Path,
        help="canned muse transcript (tests / offline replay; never forge without a log)",
    )
    args = p.parse_args(argv)
    result = run_muse_judge(
        args.out,
        before=args.before,
        after=args.after,
        instruction=args.instruction,
        fixture_log=args.fixture_log,
    )
    print(json.dumps(result, indent=2))
    if result.get("skipped"):
        return 2
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
