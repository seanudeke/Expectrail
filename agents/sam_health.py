"""Ask SAM one question before a run spends anything on an answer it may never get.

The likeliest real failure is SAM running out of credit, not a passing outage, and a 30-second retry
fixes a rate limit, not an empty balance. So a run sends SAM one image first. If SAM does not answer,
the run stops there and says why (docs/fallbacks.md).

The request goes straight to the client, past the answer cache: a cached answer says SAM answered
once, not that it answers today. It looks at one committed frame, so it needs no replay. Whether SAM
finds anything in it does not matter, only that it answers. Exactly one image, unless the client
retries a rate limit or a server error.

    EXPECTRAIL_OBS_PROVIDER=sam python3 -m agents.sam_health
"""
from __future__ import annotations

import sys
from pathlib import Path

from agents.observations import judge_drill, resolve_provider
from agents.sam_observations import MetaSamClient, SamError, vision_backend

PROBE_FRAME = Path(__file__).resolve().parent / "fixtures" / "frames" / "after-fixed.png"
PROBE_PROMPT = "blue robot"
SAM_BACKENDS = ("sam", "both")  # the backends that send frames to SAM at all


def check(client=None) -> dict | None:
    """None when SAM answered or is not the judge here; else ``{"kind", "error"}``."""
    if resolve_provider() != "sam":
        return None
    try:
        if vision_backend() not in SAM_BACKENDS:
            return None
    except SamError as exc:
        return {"kind": exc.kind, "error": str(exc)[:300]}
    drill = judge_drill("preflight")
    if drill:
        return {"kind": "drill", "error": drill}
    try:
        (client or MetaSamClient()).segment(PROBE_FRAME, PROBE_PROMPT)
    except SamError as exc:
        return {"kind": exc.kind, "error": str(exc)[:300]}
    except Exception as exc:  # noqa: BLE001 - anything else is still no answer, and never a crash here
        return {"kind": "unknown", "error": f"{type(exc).__name__}: {exc}"[:300]}
    return None


def reason(problem: dict) -> str:
    """The line the morning report carries."""
    return f"SAM did not answer before the run: {problem['kind']} ({' '.join(problem['error'].split())})"


def main() -> int:
    from agents.keys import load_dotenv

    load_dotenv()
    problem = check()
    print(reason(problem) if problem else "SAM answered, or it is not the judge here")
    return 1 if problem else 0


if __name__ == "__main__":
    sys.exit(main())
