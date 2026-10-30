"""Muse Code screenshot judge (Gate 2 baseline arm).

Muse sees failing/fixed frames and a plain-English instruction — no Expectrail
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
    before_rel: str | list[str],
    after_rel: str | list[str],
    instruction: str,
) -> str:
    """Plain-English screenshot judge prompt (no structured Expectrail checks).

    ``before_rel`` / ``after_rel`` may each be one frame or several frames of the same route.
    """
    if not isinstance(before_rel, str):
        before_rel = ", ".join(before_rel)
    if not isinstance(after_rel, str):
        after_rel = ", ".join(after_rel)
    return f"""You are judging a Godot 2D platformer bug from screenshots alone.

## Instruction
{instruction.strip()}

## Frames (relative to this workspace)
- Before (bug): {before_rel}
- After (candidate): {after_rel}

## Rules
- Open and look at every image file listed.
- Do not invent file contents you could not open.
- Do not run the game, edit files, or search for tests, specs, keys, or evaluator code.
- Do not use Expectrail contracts, held-out routes, or SAM.

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
    before: Path | list[Path],
    after: Path | list[Path],
    instruction: str = DEFAULT_INSTRUCTION,
    fixture_log: Path | None = None,
    timeout: int = 600,
    sandboxed: bool = False,
) -> dict:
    """Run Muse Code as a screenshot-only judge; fail closed without a parseable decision.

    ``before`` / ``after`` are one frame each, or lists of frames of the same route (the judge
    then sees all of them). ``sandboxed`` runs Muse inside bubblewrap with only its frames
    mounted, as the fixer is; use it wherever anything else sits on the machine's disk.
    """
    out.mkdir(parents=True, exist_ok=True)
    befores = [before] if isinstance(before, Path) else list(before)
    afters = [after] if isinstance(after, Path) else list(after)
    if not befores or not afters or not all(p.is_file() for p in befores + afters):
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
    if len(befores) == 1 and len(afters) == 1:
        before_rels: list[str] = ["frames/before.png"]
        after_rels: list[str] = ["frames/after.png"]
    else:
        before_rels = [f"frames/before-{i + 1}.png" for i in range(len(befores))]
        after_rels = [f"frames/after-{i + 1}.png" for i in range(len(afters))]
    (work / "frames").mkdir()
    for src, rel in zip(befores + afters, before_rels + after_rels):
        shutil.copy2(src, work / rel)
    before_rel: str | list[str] = before_rels[0] if len(before_rels) == 1 else before_rels
    after_rel: str | list[str] = after_rels[0] if len(after_rels) == 1 else after_rels
    allowed = ALLOWED_WORK_RELPATHS if len(befores) == len(afters) == 1 else frozenset(before_rels + after_rels)
    inventory = _work_inventory(work)
    if set(inventory) != allowed:
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
    # Template must not name Expectrail artifact files (may say "do not use held-out").
    template_blob = build_judge_prompt(
        before_rel=before_rel, after_rel=after_rel, instruction="x",
    ).lower()
    for tok in (
        "verification.json", "repair-request.json", "obs-fixed.json",
        "release-candidate.json", "expectrail.verification",
    ):
        if tok in template_blob:
            raise AssertionError(f"screenshots-v1 template leaked {tok!r}")

    prompt_path = out / "muse-prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    meta: dict = {
        "promptPolicy": PROMPT_POLICY,
        "promptSha256": prompt_sha256(prompt),
        "before": str(befores[0]) if len(befores) == 1 else [str(p) for p in befores],
        "after": str(afters[0]) if len(afters) == 1 else [str(p) for p in afters],
        "beforeSha256": file_sha256(befores[0]) if len(befores) == 1 else [file_sha256(p) for p in befores],
        "afterSha256": file_sha256(afters[0]) if len(afters) == 1 else [file_sha256(p) for p in afters],
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
    elif sandboxed:
        from agents.sandbox import run_muse_sandboxed

        try:
            proc, sandbox_meta = run_muse_sandboxed(prompt, work=work, env=muse_subprocess_env(), timeout=timeout,
                                                    require_sandbox=True)
        except subprocess.TimeoutExpired as exc:
            text = [s.decode("utf-8", "replace") if isinstance(s, bytes) else (s or "") for s in (exc.stdout, exc.stderr)]
            proc = subprocess.CompletedProcess(exc.cmd, -1, text[0], text[1])
            sandbox_meta = {"kind": "bwrap", "timedOut": True}
        meta["sandbox"] = sandbox_meta
        log_text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        source = "muse"
        exit_code = proc.returncode
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
