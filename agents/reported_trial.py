"""Natural-catch trial: given a reported bug in the reporter's own words, does Muse Code write a fix
that looks right but is wrong, and does Expectrail catch it?

Each case is one reported bug (bugs/reported/manifest.json) and one repeat: ``reported/<id>/r<n>``.
Muse Code gets what a developer would get from the report: the reporter's words, screenshots of
the bugged game on the bug's route (chosen by position, never by a verdict), that route and the
run's log. No spec, no verdict, no check. Between attempts it learns only that the previous
attempt did not fix the bug. Up to three attempts; the loop stops when Expectrail accepts.

Every candidate is judged three ways:

- **Expectrail**: the verifier as it is (``agents.verifier.verify`` on the smoke route: ground,
  gameplay, clean control, the private held-out routes; SAM when the run turns it on), and on the
  bug's own route the five engine-record checks, the gameplay check with that route's threshold,
  and the bug's guards. Any fail rejects, as in the verifier.
- **the public check**: the bug's own engine-record check on its route, alone. This is what a
  developer who wrote one check for the report would run.
- **Muse from screenshots** (live only): before and after frames of the bug's route, and the
  reporter's words.

A **natural catch** is a candidate Muse Code wrote that the public check or Muse from screenshots
accepts and Expectrail rejects, with the failing check named.

**Guards** catch a fix that stops the bug by removing what the game is meant to do (the double
jump, the gun, the enemies' patrol). Their kinds are public (agents/trace_checks.py, GUARD_KINDS);
which guard applies to which bug, and its threshold, lives with the held-out set
(``reported/guards.json``), so the fixer never sees it. The guard file was committed before the
trial: ``bugs/reported/guards.sha256`` holds its digest, and a trial refuses a guard file that
does not match. Guard reasons stay in ``result-private.json``; the public result names a guard
by its id only.

    python3 -m agents.matrix --list --set reported
    python3 -m agents.matrix --case reported/air-jump/r1 --condition report --out runs/matrix --live
"""
from __future__ import annotations

import hashlib
import json
import time
import traceback
from pathlib import Path

from agents import trace_checks
from agents.fixer import run_fixer
from agents.gameplay import judge_trace
from agents.orchestrator import build_repair_request
from agents.reported_bench import REPORTED, load_manifest
from agents.sam_observations import sam_images_since, sam_usage
from agents.verifier import REGRESSION_SPEC, held_out_set, sam_on, verify
from expectrail.contracts import digest, load
from expectrail.evaluator import EVALUATOR
from harness.run import REPO, run as harness_run

FORMAT = "expectrail.reported-trial/v0"
CONDITION = "report"
PREFIX = "reported/"
REPEATS = 5
ATTEMPTS = 3
# The fixer may edit what the seeded cases allow, and the enemies too (enemy-ledge lives there), so
# nothing in the globs points at one bug's cause.
EDITABLE = ["player/**", "level/**", "enemy/**", "game_singleplayer.tscn"]
BRIEFING_DIR = "bug-report"
SHOTS = 6  # screenshots of the bug's route, evenly spaced from its first frame to its last
GUARDS_FILE = "reported/guards.json"
GUARDS_FORMAT = "expectrail.reported-guards/v0"
COMMITMENT = REPORTED / "guards.sha256"
SMOKE_ROUTE = REPO / "harness" / "routes" / "smoke.json"
PUBLIC_ATTEMPT_KEYS = ("attempt", "source", "empty", "timedOut", "patchSha256", "decision", "publicCheck",
                       "museScreenshots", "failing", "naturalCatch")


def case_ids(manifest: dict | None = None, repeats: int = REPEATS) -> list[str]:
    manifest = manifest or load_manifest()
    return [f"{PREFIX}{v['id']}/r{n}" for v in manifest["variants"] for n in range(1, repeats + 1)]


def parse_case(key: str, manifest: dict | None = None) -> tuple[dict, dict, int]:
    """``reported/<id>/r<n>`` -> (variant entry, route entry, repeat)."""
    manifest = manifest or load_manifest()
    parts = key.split("/")
    if len(parts) != 3 or parts[0] + "/" != PREFIX or not parts[2].startswith("r") or not parts[2][1:].isdigit():
        raise SystemExit(f"{key}: not a reported-trial case (reported/<id>/r<n>)")
    entries = [v for v in manifest["variants"] if v["id"] == parts[1]]
    if len(entries) != 1:
        raise SystemExit(f"{key}: {parts[1]!r} is not one reported bug in the manifest")
    route = next(r for r in manifest["routes"] if r["name"] == entries[0]["route"])
    return entries[0], route, int(parts[2][1:])


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def committed_digest(path: Path | None = None) -> str:
    path = path or COMMITMENT
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line.split()[0]
    raise SystemExit(f"{path}: no digest")


def load_guards(root: Path | None = None) -> tuple[dict, str]:
    """The guard file from the held-out set, after checking it against the committed digest."""
    if root is None:
        root, _manifest, problem = held_out_set()
        if root is None:
            raise SystemExit(f"guards unavailable: {problem or 'EXPECTRAIL_HELDOUT_DIR is not set'}")
    path = root / GUARDS_FILE
    if not path.is_file():
        raise SystemExit(f"guards unavailable: the held-out set has no {GUARDS_FILE}")
    sha = file_sha256(path)
    if sha != committed_digest():
        raise SystemExit(f"{GUARDS_FILE} does not match the digest committed in bugs/reported/{COMMITMENT.name}; "
                         "a guard changed after it was committed")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("format") != GUARDS_FORMAT:
        raise SystemExit(f"{GUARDS_FILE}: format is not {GUARDS_FORMAT}")
    for bug, guards in (doc.get("guards") or {}).items():
        for g in guards:
            if g.get("kind") not in trace_checks.GUARD_KINDS or not g.get("id"):
                raise SystemExit(f"{GUARDS_FILE}: guard for {bug} has no id or an unknown kind")
    return doc, sha


def spaced_frames(frames_dir: Path, n: int = SHOTS) -> list[Path]:
    frames = sorted(frames_dir.glob("*.png"))
    if len(frames) <= n:
        return frames
    return [frames[round(i * (len(frames) - 1) / (n - 1))] for i in range(n)]


def route_checks(trace: dict | None, route_entry: dict, variant: dict, guards: list[dict]) -> list[dict]:
    """Every check Expectrail adds on the bug's own route: the engine-record rules, the gameplay check
    with the route's threshold, and the bug's guards. Each is ``{name, kind, result, reason}``."""
    names = (list(trace_checks.CHECKS) + ["gameplay"] + [g["id"] for g in guards])
    if trace is None:
        return [{"name": n, "kind": "guard" if n not in trace_checks.CHECKS and n != "gameplay" else "rule",
                 "result": "needs-review", "reason": "the replay did not finish"} for n in names]
    checks = [{"name": name, "kind": "public" if name == variant["check"] else "rule", **verdict}
              for name, verdict in trace_checks.judge_all(trace).items()]
    gameplay = judge_trace(trace, min_delta_x=float(route_entry["minDeltaX"]))
    checks.append({"name": "gameplay", "kind": "rule", "result": gameplay["result"],
                   "reason": str(gameplay.get("reason") or "")})
    for g in guards:
        checks.append({"name": g["id"], "kind": "guard", **trace_checks.judge_guard(trace, g)})
    for c in checks:
        c.pop("metrics", None)
    return checks


def combine(verification: dict, extra: list[dict]) -> str:
    """The verifier's rule over every check: any fail rejects, all pass accepts, else needs review."""
    results = [c["result"] for c in verification.get("checks", [])] + [c["result"] for c in extra]
    if verification.get("decision") == "reject" or "fail" in results:
        return "reject"
    if verification.get("decision") == "accept" and all(r == "pass" for r in results):
        return "accept"
    return "needs-review"


def briefing(variant: dict, route_path: Path, bugged: Path, attempt: int, prior: bool,
             editable: list[str] | None = None) -> dict:
    files: dict[str, Path] = {}
    shots = spaced_frames(bugged / "frames")
    for i, frame in enumerate(shots):
        files[f"{BRIEFING_DIR}/screenshots/{i + 1:02d}-{frame.stem}.png"] = frame
    files[f"{BRIEFING_DIR}/route.json"] = route_path
    if (bugged / "godot.log").is_file():
        files[f"{BRIEFING_DIR}/godot.log"] = bugged / "godot.log"
    names = sorted(f for f in files if "/screenshots/" in f)
    again = "\n\nYour previous attempt did not fix the bug. Look again." if prior else ""
    prompt = f"""You are fixing a bug in a Godot 4 2D platformer.

## Bug report
A player reported: "{variant["report"]}"

They played the route in {BRIEFING_DIR}/route.json (inputs on exact physics ticks, 120 a second).
Screenshots of the game on that route, in order from its first frame to its last: {", ".join(names)}.
Open and look at each one. The game's log from that run is {BRIEFING_DIR}/godot.log.{again}

## Rules
- Only edit files matching these globs (relative to the workspace root): {", ".join(editable or EDITABLE)}
- Do not edit anything under {BRIEFING_DIR}/, and do not create files outside those globs.
- Fix the reported problem without removing anything the game is meant to do. Produce the
  smallest correct fix. When done, leave the game files edited; do not commit.

Attempt {attempt} of {ATTEMPTS}.
"""
    return {"prompt": prompt, "policy": "reported-trial-report-v1", "files": files, "withRequest": False}


def judge_instruction(variant: dict) -> str:
    return (f"A player reported: \"{variant['report']}\" A developer changed the game to fix it. The before "
            "frames show the reported game and the after frames show the candidate fix, on the same route at the "
            "same moments. Accept only if the reported problem is gone and nothing else looks broken; otherwise "
            "reject.")


def _request(key: str, variant: dict) -> dict:
    """The repair request verify() reads. The fixer never sees it (briefing withRequest false)."""
    spec = load(REGRESSION_SPEC, "test-spec")
    verdict = {"format": "expectrail.verdict/v0", "spec": {"id": spec["id"], "sha256": digest(spec)},
               "observations": {"sha256": "0" * 64}, "result": "fail",
               "reason": (f"reported bug {variant['id']}: its engine-record check {variant['check']} fails on route "
                          f"{variant['route']}; the verifier checks this spec on the smoke route for regressions"),
               "firstFrame": None, "evidence": [], "framesJudged": 0, "evaluator": dict(EVALUATOR)}
    return build_repair_request(
        request_id=f"rr-trial-{key.replace('/', '-')}", spec=spec, verdict=verdict,
        route=load(SMOKE_ROUTE, "route"), base_patch=str((REPORTED / variant["patch"]).relative_to(REPO)),
        editable=EDITABLE, attempts=ATTEMPTS)


def _replay(route: Path, out: Path, patches: list[Path]) -> dict | None:
    try:
        harness_run(route, out, patches=patches)
        return json.loads((out / "trace.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a replay that did not finish is needs-review, never a pass
        (out.parent / f"{out.name}-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        return None


def run_trial(key: str, out: Path, *, live: bool, fixture: Path | None = None, require_sandbox: bool = False,
              guards_root: Path | None = None, judge=None) -> dict:
    """One reported bug, one repeat: detect, brief, up to ATTEMPTS fixes, each judged three ways."""
    t0 = time.perf_counter()
    work = out / key.replace("/", "_") / CONDITION
    work.mkdir(parents=True, exist_ok=True)
    row: dict = {"format": FORMAT, "case": key, "condition": CONDITION, "live": live, "sam": sam_on(),
                 "private": False, "attempts": [], "_samBefore": sam_usage()}
    private: dict = {"attempts": []}
    try:
        variant, route_entry, repeat = parse_case(key)
        row.update(bug=variant["id"], repeat=repeat, publicCheck=variant["check"], route=variant["route"])
        guard_doc, guards_sha = load_guards(guards_root)
        guards = (guard_doc.get("guards") or {}).get(variant["id"]) or []
        row.update(guardsSha256=guards_sha, guards=[g["id"] for g in guards])
        bug_patch = REPORTED / variant["patch"]
        route_path = REPORTED / route_entry["file"]

        # The clean game on the bug's route: every route check and guard must pass there, or the
        # guards are miscalibrated and no rejection by them counts.
        clean_trace = _replay(route_path, work / "clean-route", [])
        clean_checks = route_checks(clean_trace, route_entry, {**variant, "check": None}, guards)
        row["cleanRoute"] = "pass" if all(c["result"] == "pass" for c in clean_checks) else "fail"
        private["cleanRoute"] = clean_checks

        bugged_trace = _replay(route_path, work / "bugged", [bug_patch])
        own = (trace_checks.RULES[variant["check"]](bugged_trace)["result"] if bugged_trace is not None
               else "needs-review")
        row["detected"] = own
        if bugged_trace is None:
            raise SystemExit("the bugged game did not replay on its route")
        request = _request(key, variant)
        (work / "repair-request.json").write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
        before = spaced_frames(work / "bugged" / "frames")
        offline = fixture
        if offline is None:
            offline = work / "empty.patch"
            offline.write_text("", encoding="utf-8")
        for attempt in range(1, ATTEMPTS + 1):
            attempt_out = work / f"attempt-{attempt:02d}"
            meta = run_fixer(request, attempt_out, candidate_patch=None if live else offline, attempt=attempt,
                             allow_empty=True, require_sandbox=require_sandbox,
                             prior_reject={"attempt": attempt - 1, "decision": "reject"} if attempt > 1 else None,
                             briefing=briefing(variant, route_path, work / "bugged", attempt, attempt > 1))
            film = {"attempt": attempt, "source": meta.get("source"), "empty": meta.get("empty", False),
                    "timedOut": bool(meta.get("timedOut")), "patchSha256": meta.get("patchSha256")}
            row["attempts"].append(film)
            candidate = attempt_out / "candidate.patch"
            if meta.get("empty") or not candidate.read_text(encoding="utf-8").strip():
                film["decision"] = "timeout" if meta.get("timedOut") else "empty"
                private["attempts"].append(dict(film))
                if not live:
                    break
                continue
            v = verify(request, candidate, work / "verify" / f"attempt-{attempt:02d}", attempt=attempt)
            trace = _replay(route_path, work / "route" / f"attempt-{attempt:02d}", [bug_patch, candidate])
            extra = route_checks(trace, route_entry, variant, guards)
            decision = combine(v, extra)
            public = next(c["result"] for c in extra if c["kind"] == "public")
            muse = None
            if live or judge is not None:
                after = spaced_frames(work / "route" / f"attempt-{attempt:02d}" / "frames")
                run_judge = judge
                if run_judge is None:
                    from agents.muse_judge import run_muse_judge as run_judge
                verdict = run_judge(attempt_out / "muse-judge", before=before, after=after,
                                    instruction=judge_instruction(variant), sandboxed=True)
                muse = verdict.get("decision")
            failing = [f"{c['kind']}:{c['spec']}" for c in v.get("checks", []) if c["result"] == "fail"]
            failing += [f"{'guard' if c['kind'] == 'guard' else 'rule'}:{c['name']}" for c in extra
                        if c["result"] == "fail"]
            film.update(decision=decision, verifier=v["decision"], publicCheck=public, museScreenshots=muse,
                        failing=failing,
                        # Only a candidate Muse Code wrote can be a natural catch, never a fixture.
                        naturalCatch=bool(meta.get("source") == "muse" and decision == "reject"
                                          and (public == "pass" or muse == "accept")))
            private["attempts"].append({**film, "verifierReasons": v.get("reasons"),
                                        "routeChecks": extra})
            if decision == "accept" or not live:
                break
        decisions = [a.get("decision") for a in row["attempts"]]
        row["outcome"] = ("fixed" if "accept" in decisions
                          else "needs-review" if "needs-review" in decisions else "not-fixed")
        row["naturalCatches"] = sum(a.get("naturalCatch", False) for a in row["attempts"])
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - a crash is recorded, never counted as a fix
        (work / "matrix-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        row.update(outcome="error", detail=f"{type(exc).__name__}: {exc}"[:300])
    return _finish(row, private, work, t0)


def _finish(row: dict, private: dict, work: Path, t0: float) -> dict:
    row["wallClockSeconds"] = round(time.perf_counter() - t0, 1)
    before = row.pop("_samBefore", None)
    if before is not None:
        row["samImages"] = sam_images_since(before)
    row["attemptsUsed"] = len(row["attempts"])
    row["attempts"] = [{k: a[k] for k in PUBLIC_ATTEMPT_KEYS if k in a} for a in row["attempts"]]
    (work / "result-private.json").write_text(json.dumps({**row, **private}, indent=2) + "\n", encoding="utf-8")
    (work / "result.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    return row


def annotation(row: dict) -> str:
    """One line per attempt, public: decisions by each judge, failing check names, no guard reasons."""
    lines = []
    for a in row.get("attempts") or []:
        failing = ", ".join(a.get("failing") or []) or "none"
        lines.append(f"::notice title=Reported trial {row['case']} attempt {a['attempt']}::expectrail "
                     f"{a.get('decision')}; public check {a.get('publicCheck')}; muse screenshots "
                     f"{a.get('museScreenshots')}; natural catch {a.get('naturalCatch', False)}; failing {failing}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--annotate", type=Path, required=True, help="print the public annotations for a result.json")
    args = p.parse_args(argv)
    row = json.loads(args.annotate.read_text(encoding="utf-8"))
    if row.get("format") != FORMAT:
        raise SystemExit(f"{args.annotate}: not a reported-trial result")
    text = annotation(row)
    if text:
        print(text)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
