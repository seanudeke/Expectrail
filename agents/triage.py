"""Muse Wonder triage: turn failure evidence into a bug report, then a repair-request.

    python3 -m agents.triage --verdict ... --spec ... --route ... --out runs/triage \\
        [--log godot.log] [--frames-dir runs/fall/frames] [--offline]

With MODEL_API_KEY, calls muse-wonder-1.0 over Meta Model API. With --offline (or no key),
writes a deterministic bug report from the verdict reason and still emits a repair-request.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from agents.orchestrator import build_repair_request
from harness.run import REPO
from nightshift.contracts import load

WONDER_MODEL = "muse-wonder-1.0"
API_BASE = os.environ.get("META_API_BASE", "https://api.meta.ai/v1")


def _bug_report_offline(spec: dict, verdict: dict, route: dict, log_text: str) -> str:
    return "\n".join([
        f"# Bug report: {spec.get('id', 'unknown')}",
        "",
        f"Instruction: {spec.get('instruction', '')}",
        f"Assertion: {json.dumps(spec.get('assertion', {}), sort_keys=True)}",
        f"Verdict: {verdict.get('result')} — {verdict.get('reason')}",
        f"First fail frame: {verdict.get('firstFrame')}",
        f"Route: {route.get('name')} ({route.get('ticks')} ticks)",
        "",
        "## Evidence",
        json.dumps(verdict.get("evidence", [])[:3], indent=2),
        "",
        "## Log tail",
        "\n".join(log_text.strip().splitlines()[-40:]) or "(no log)",
        "",
        "Suggested fix direction: restore Player collision_mask so the ground layer is included.",
    ])


def call_wonder(prompt: str, api_key: str) -> str:
    body = json.dumps({
        "model": WONDER_MODEL,
        "messages": [
            {"role": "system", "content": "You triage game bugs for Nightshift. Be concise."},
            {"role": "user", "content": prompt},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def triage(
    *,
    spec: dict,
    verdict: dict,
    route: dict,
    out: Path,
    base_patch: str = "bugs/physics-fall-through/v1.patch",
    log_text: str = "",
    key_frames: list[str] | None = None,
    offline: bool = False,
) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    prompt = _bug_report_offline(spec, verdict, route, log_text)
    api_key = os.environ.get("MODEL_API_KEY") or os.environ.get("META_API_KEY")
    if offline or not api_key:
        report = prompt
        source = "offline"
    else:
        try:
            report = call_wonder(prompt + "\n\nWrite a short actionable bug report for Muse Code.", api_key)
            source = WONDER_MODEL
        except (urllib.error.URLError, KeyError, TimeoutError) as exc:
            report = prompt + f"\n\n(Wonder call failed: {exc}; using offline report.)"
            source = "offline-fallback"

    (out / "bug-report.md").write_text(report + "\n", encoding="utf-8")
    triage_meta = {"source": source, "model": WONDER_MODEL}
    request = build_repair_request(
        request_id=f"rr-triage-{spec.get('id', 'bug')}",
        spec=spec,
        verdict=verdict,
        route=route,
        base_patch=base_patch,
        key_frames=key_frames,
        notes=f"Triage source: {source}. See bug-report.md.",
        triage=triage_meta,
    )
    (out / "repair-request.json").write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
    (out / "triage.json").write_text(json.dumps(triage_meta, indent=2) + "\n", encoding="utf-8")
    return request


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--spec", type=Path, default=REPO / "agents" / "specs" / "player-stays-above-ground.json")
    p.add_argument("--verdict", type=Path, default=REPO / "contracts" / "examples" / "verdict.json")
    p.add_argument("--route", type=Path, default=REPO / "harness" / "routes" / "smoke.json")
    p.add_argument("--base-patch", default="bugs/physics-fall-through/v1.patch")
    p.add_argument("--log", type=Path)
    p.add_argument("--key-frame", action="append", default=[])
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--offline", action="store_true")
    args = p.parse_args(argv)
    log_text = args.log.read_text(encoding="utf-8") if args.log and args.log.exists() else ""
    triage(
        spec=load(args.spec, "test-spec"),
        verdict=load(args.verdict, "verdict"),
        route=load(args.route, "route"),
        out=args.out,
        base_patch=args.base_patch,
        log_text=log_text,
        key_frames=args.key_frame or ["frames/f00000008.png", "frames/f00000016.png"],
        offline=args.offline,
    )
    print(f"wrote {args.out / 'repair-request.json'} and bug-report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
