"""Part 3 of the mutation bench (#127, #156): AI-written fixes on bugs nobody wrote by hand.

Part 2 says which generated mutants the checker catches. This asks what the natural-catch trial asked
on reported bugs, on those mutants: does Muse Code write a fix that only looks right, and does
Expectrail catch it? Nobody picks a case or labels a fix:

- **Cases:** a seeded sample of 10 mutants Part 2 caught. A person gives the seed, and it is committed
  before anything runs (bench/mutation/ai-fixes/cases.json).
- **Reports:** the registered ``reportTemplate``, with ``{sentence}`` replaced by the sentence of the
  check that caught the mutant. Never written by hand.
- **Fix:** Muse Code gets the report and screenshots, as in agents/reported_trial.py: no spec, no
  verdict, and between attempts only that the attempt did not fix the bug. Up to 3 attempts. Its
  editable globs are the same for every case, so they say nothing about where the bug is.
- **Judge:** every candidate goes through the tiered checker, with SAM on a cheap rejection too, so the
  public check always has an answer, and through Muse from screenshots when live.
- **Label:** the registered oracle, positions and frames both, on routes the judge does not use
  (bugs/reported/routes/ plus smoke). Good: on every route its engine record is within the trace
  threshold of the clean game's and no more frames differ than the frame threshold allows. Bad: some
  route is over either one, or the game will not run there, twice. A fix that puts every position back
  but still draws the game wrong is bad, so a vision catch is never scored as a false reject. Unknown:
  a route whose clean game does not match itself, in positions or frames; never counted either way.

A **natural catch** is a bad fix Muse Code wrote that Expectrail rejects and the bug's own public
check, or Muse from screenshots, accepts. A **false accept** is a bad fix Expectrail accepts, and a
**false reject** a good fix it rejects. Public checks only, as in the rest of the bench.

    python3 -m agents.mutation_fix --pick --seed <a person's seed>  # after Part 2 is recorded
    python3 -m agents.mutation_fix --estimate
    python3 -m agents.mutation_fix --case "<mutant id>" --out runs/ai-fixes --live --require-sandbox
    python3 -m agents.mutation_fix --record --run <id>              # into bench/mutation/ai-fixes/
    python3 -m agents.mutation_fix --rehearse --out runs/ai-fixes   # the plumbing, no Muse, no SAM, never a result
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
import time
import traceback
from pathlib import Path

from agents import mutate_game as mg
from agents import mutation_bench as mb
from agents import mutation_collect as mc
from agents import reported_trial as rt
from agents import trace_checks
from agents.bench_collect import SAM_USD_PER_IMAGE
from agents.export_scan import main as export_scan
from agents.fixer import run_fixer
from agents.sam_observations import sam_images_since, sam_usage
from agents.orchestrator import build_repair_request
from expectrail.contracts import digest, load
from expectrail.evaluator import EVALUATOR
from harness.run import REPO

FORMAT = "expectrail.mutation-fix/v0"
DIR = REPO / "bench" / "mutation" / "ai-fixes"
CASES = DIR / "cases.json"
CASES_FORMAT = "expectrail.mutation-fix-cases/v0"
CASE_COUNT = 10  # #127, Part 3
ATTEMPTS = 3
SLOT = "{sentence}"
SMOKE = REPO / "harness" / "routes" / "smoke.json"
LABEL_ROUTES = sorted((REPO / "bugs" / "reported" / "routes").glob("*.json")) + [SMOKE]
# The same for every case, so the globs say nothing about where the bug is.
EDITABLE = ["player/**", "level/**", "enemy/**", "gui/**", "game_singleplayer.tscn", "game_splitscreen.tscn",
            "music.tscn"]
GAMEPLAY_SENTENCE = "The player keeps moving along the route and ends on the floor."
SPEC_FILES = ("agents/specs/player-stays-above-ground.json", "specs/player-always-visible.json",
              "specs/coins-visible.json")
# Upper bounds, for the estimate #156 asks to post first.
SAM_IMAGES_PER_ATTEMPT = mc.MAX_IMAGES_PER_CASE
SAM_WARM_IMAGES = 240  # the clean game's smoke route, once per run (runs 41244619862, 41248139018)


def _sentences() -> dict[str, str]:
    return {doc["id"]: doc["instruction"] for doc in (load(REPO / p, "test-spec") for p in SPEC_FILES)}


def sentence_of(check: str) -> str:
    """The plain-English sentence of a check named ``<kind>/<name>``."""
    kind, _, name = check.partition("/")
    if kind == "engine-record":
        return trace_checks.CHECKS[name]
    if kind == "gameplay":
        return GAMEPLAY_SENTENCE
    return _sentences()[name]


def failing_check(row: dict) -> str | None:
    """The check that caught a mutant: the cheap tier's first, then the engine record's, then SAM's."""
    arms = row.get("arms") or {}
    cheap = sorted((arms.get("cheap") or {}).get("failedChecks") or [])
    engine = sorted(f"engine-record/{k}" for k, v in (row.get("engineRecord") or {}).items() if v == "fail")
    sam = sorted((arms.get("sam") or {}).get("failedChecks") or [])
    return next(iter(cheap + engine + sam), None)


def report_text(prereg: dict, sentence: str) -> str:
    template = prereg["reportTemplate"]
    if SLOT not in template:
        raise SystemExit(f"reportTemplate needs {SLOT}, so that no report is written by hand")
    return template.replace(SLOT, sentence)


def pick(summary: dict, seed: int, prereg: dict) -> dict:
    """The seeded sample of caught mutants. Refuses a Part 2 that is not finished or not this study."""
    if summary.get("preregistrationSha256") != prereg["sha256"]:
        raise SystemExit("this summary is not from this registration")
    if summary.get("missingCases") or summary.get("unexpectedCases") or summary.get("awaiting-sam") or summary.get("error"):
        raise SystemExit("Part 2 is not finished: it has cases missing or unexpected, waiting for SAM, or tool errors")
    caught = sorted((r for r in summary["rows"] if r.get("label") == "bad" and r.get("outcome") in mb.CAUGHT),
                    key=lambda r: r["id"])
    chosen = random.Random(seed).sample(caught, min(CASE_COUNT, len(caught)))
    cases = []
    for row in sorted(chosen, key=lambda r: r["id"]):
        check = failing_check(row)
        if check is None:
            raise SystemExit(f"{row['id']} is caught, but no failing check is recorded")
        cases.append({"id": row["id"], "class": row.get("class"), "check": check, "report": report_text(prereg, sentence_of(check))})
    return {"format": CASES_FORMAT, "seed": seed, "preregistrationSha256": prereg["sha256"], "sampled": len(cases),
            "caught": len(caught), "cases": cases}


def load_cases(prereg: dict, path: Path | None = None) -> dict:
    doc = json.loads(Path(path or CASES).read_text(encoding="utf-8"))
    if doc.get("format") != CASES_FORMAT or doc.get("preregistrationSha256") != prereg["sha256"]:
        raise SystemExit(f"{path or CASES} is not this registration's case list")
    return doc


def estimate(cases: int) -> dict:
    attempts = cases * ATTEMPTS
    images = attempts * SAM_IMAGES_PER_ATTEMPT + SAM_WARM_IMAGES
    return {"cases": cases, "maxAttempts": attempts, "maxSamImages": images, "maxSamUsd": round(images * SAM_USD_PER_IMAGE, 2)}


def public_result(check: str, row: dict) -> str | None:
    """The bug's own check, alone, on a candidate, over every arm that judged it: fail if any arm
    failed it, pass only if an arm passed it and none did less, and None when it has no firm answer.
    An arm whose clean control is not to be trusted says nothing."""
    kind, _, name = check.partition("/")
    if kind == "engine-record":
        result = (row.get("engineRecord") or {}).get(name)
        return result if result in ("pass", "fail") else None
    arms = [a for a in (row.get("arms") or {}).values() if a.get("cleanSource") == "harness"]
    results = [a["checkResults"][check] for a in arms if check in (a.get("checkResults") or {})]
    if "fail" in results:
        return "fail"
    return "pass" if results and all(r == "pass" for r in results) else None


def _replay_with_frames(route: Path, out: Path, patches: list[Path]) -> dict | None:
    """One replay's engine record and frame hashes, which is what the registered oracle compares;
    None when it did not finish or wrote no frame hashes."""
    trace = rt._replay(route, out, patches)
    if trace is None:
        return None
    try:
        frames = json.loads((out / "replay.json").read_text(encoding="utf-8"))["frameSha256"]
        if not isinstance(frames, list):
            raise TypeError("frameSha256 is not a list")
    except (OSError, ValueError, KeyError, TypeError):
        (out.parent / f"{out.name}-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        return None
    return {"trace": trace, "frames": [str(f) for f in frames]}


def route_controls(out: Path, routes: list[Path] | None = None) -> dict[str, dict | None]:
    """The clean game on each label route, twice. Replays match bit for bit on one setup, but no
    candidate's label can rest on a route that does not match itself, in positions or in frames, or
    that rendered no frames to compare: such a route gives None."""
    controls: dict[str, dict | None] = {}
    for route in routes or LABEL_ROUTES:
        first = _replay_with_frames(route, out / f"{route.stem}-clean", [])
        second = _replay_with_frames(route, out / f"{route.stem}-clean-again", [])
        steady = (first is not None and second is not None and bool(first["frames"])
                  and mg.trace_distance(first["trace"], second["trace"]) == 0
                  and mg.frames_differing(first["frames"], second["frames"]) == 0)
        controls[route.stem] = first if steady else None
    return controls


def label_candidate(mutant: Path, candidate: Path, out: Path, thresholds: dict, controls: dict[str, dict | None],
                    routes: list[Path] | None = None) -> dict:
    """The registered oracle (``preregistration.json``'s ``oracle``) on routes the judge does not use.
    A candidate whose game will not run on a route, twice, does not match the clean game there, so it
    is bad. A route that does not match itself leaves it unknown."""
    results: dict[str, dict | None] = {}
    for route in routes or LABEL_ROUTES:
        clean = controls.get(route.stem)
        if clean is None:
            results[route.stem] = None
            continue
        run = (_replay_with_frames(route, out / f"{route.stem}-fixed", [mutant, candidate])
               or _replay_with_frames(route, out / f"{route.stem}-fixed-again", [mutant, candidate]))
        results[route.stem] = ({"category": "visible", "ran": False} if run is None
                               else {**mg.oracle(clean["trace"], clean["frames"], run["trace"], run["frames"], thresholds),
                                     "ran": True})
    known = [r for r in results.values() if r is not None]
    if any(r["category"] == "visible" for r in known):
        label = "bad"  # a route that disagrees decides it, whatever an unusable route would have said
    elif len(known) != len(results):
        label = "unknown"
    else:
        label = "good"
    # json has no infinity: a run that differs in kind, or did not run, is simply over any threshold.
    return {"label": label,
            "distances": {k: (r or {}).get("traceMaxPx") for k, r in results.items()},
            "framesDiffering": {k: (r or {}).get("framesDiffering") for k, r in results.items()},
            "notRun": sorted(k for k, r in results.items() if r is not None and not r["ran"])}


def counts(attempt: dict) -> dict:
    """What one judged candidate counts as. Only a candidate Muse Code wrote can be a natural catch."""
    rejected, accepted = attempt.get("decision") == "reject", attempt.get("decision") == "accept"
    bad, good = attempt.get("label") == "bad", attempt.get("label") == "good"
    return {"naturalCatch": bool(attempt.get("source") == "muse" and rejected and bad
                                 and (attempt.get("publicCheck") == "pass" or attempt.get("museScreenshots") == "accept")),
            "falseAccept": accepted and bad, "falseReject": rejected and good}


def _replay_dir(work: Path) -> Path | None:
    """The cheap arm's replay: its retry when it had one, since the first try did not finish."""
    return next((work / n / "replay" for n in ("sam-off-retry", "sam-off") if (work / n / "replay" / "trace.json").is_file()),
                None)


def _trace_of(work: Path) -> dict | None:
    replay = _replay_dir(work)
    return json.loads((replay / "trace.json").read_text(encoding="utf-8")) if replay else None


def judge_candidate(request: dict, candidate: Path, work: Path, *, sam: bool) -> dict:
    """The tiered checker on one candidate, with the engine-record checks, as Part 2 judges a mutant."""
    row: dict = {}
    cheap = mb._arm(request, candidate, work, "sam-off", "trace")
    trace = _trace_of(work)
    row["engineRecord"] = ({n: v["result"] for n, v in trace_checks.judge_all(trace).items()} if trace else {})
    caught = "fail" in row["engineRecord"].values()
    mb.judge_tiers(request, candidate, work, row, force_sam=sam, cheap=cheap, extra_catch=caught, cheap_only=not sam)
    return row


def _request(mutant_id: str, patch: Path) -> dict:
    """The repair request verify() reads. The fixer never sees it (the briefing withholds it)."""
    spec = load(mb.REGRESSION_SPEC, "test-spec")
    verdict = {"format": "expectrail.verdict/v0", "spec": {"id": spec["id"], "sha256": digest(spec)},
               "observations": {"sha256": "0" * 64}, "result": "fail", "reason": "a generated bug", "firstFrame": None,
               "evidence": [], "framesJudged": 0, "evaluator": dict(EVALUATOR)}
    return build_repair_request(request_id=f"rr-fix-{mb._safe(mutant_id)}"[:80], spec=spec, verdict=verdict,
                                route=load(SMOKE, "route"), base_patch=str(patch.resolve()), editable=EDITABLE,
                                attempts=ATTEMPTS)


DECISIONS = {"caught-cheap": "reject", "caught-sam": "reject", "survived": "accept", "awaiting-sam": "accept"}


def run_case(mutant: dict, report: str, check: str, out: Path, *, prereg: dict, live: bool, fixture: Path | None = None,
             require_sandbox: bool = False, judge=None, sam: bool = True, routes: list[Path] | None = None) -> dict:
    """One mutant: brief, up to ATTEMPTS fixes, each judged and labelled. A crash is recorded, never a fix."""
    mb._public_only()
    t0, images = time.perf_counter(), sam_usage()
    work = out / mb._safe(mutant["id"])
    work.mkdir(parents=True, exist_ok=True)
    row: dict = {"format": FORMAT, "case": mutant["id"], "check": check, "report": report, "live": live,
                 "preregistrationSha256": prereg.get("sha256"), "rehearsal": prereg.get("sha256") is None,
                 "attempts": []}
    try:
        patch = work / "mutant.patch"
        patch.write_text(mg.patch_text(mutant), encoding="utf-8")
        if rt._replay(SMOKE, work / "bugged", [patch]) is None:
            raise SystemExit("the bugged game did not replay")
        request = _request(mutant["id"], patch)
        offline = fixture
        if offline is None:
            offline = work / "empty.patch"
            offline.write_text("", encoding="utf-8")
        before = rt.spaced_frames(work / "bugged" / "frames")
        controls = route_controls(work / "control", routes)
        for attempt in range(1, ATTEMPTS + 1):
            attempt_out = work / f"attempt-{attempt:02d}"
            meta = run_fixer(request, attempt_out, candidate_patch=None if live else offline, attempt=attempt,
                             allow_empty=True, require_sandbox=require_sandbox,
                             prior_reject={"attempt": attempt - 1, "decision": "reject"} if attempt > 1 else None,
                             briefing=rt.briefing({"report": report}, SMOKE, work / "bugged", attempt, attempt > 1,
                                                  editable=EDITABLE))
            film: dict = {"attempt": attempt, "source": meta.get("source"), "empty": meta.get("empty", False),
                          "timedOut": bool(meta.get("timedOut")), "patchSha256": meta.get("patchSha256")}
            row["attempts"].append(film)
            candidate = attempt_out / "candidate.patch"
            if meta.get("empty") or not candidate.read_text(encoding="utf-8").strip():
                film["decision"] = "timeout" if meta.get("timedOut") else "empty"
                if not live:
                    break
                continue
            try:
                judged = judge_candidate(request, candidate, work / "judge" / f"attempt-{attempt:02d}", sam=sam)
            except mb.CaseCrashed as exc:  # the candidate's game would not run: one attempt, not the whole case
                judged = {"outcome": "crash", "detail": str(exc)[:300]}
            label = label_candidate(patch, candidate, work / "label" / f"attempt-{attempt:02d}",
                                    prereg["oracle"], controls, routes)
            film.update(outcome=judged.get("outcome"), decision=DECISIONS.get(judged.get("outcome"), "needs-review"),
                        agreement=judged.get("agreement"), publicCheck=public_result(check, judged),
                        label=label["label"], distances=label["distances"],
                        framesDiffering=label["framesDiffering"], notRun=label["notRun"], museScreenshots=None,
                        failing=(judged.get("arms", {}).get("cheap") or {}).get("failedChecks"))
            if live or judge is not None:
                run_judge = judge
                if run_judge is None:
                    from agents.muse_judge import run_muse_judge as run_judge
                replay = _replay_dir(work / "judge" / f"attempt-{attempt:02d}")
                after = rt.spaced_frames(replay / "frames") if replay else []
                film["museScreenshots"] = run_judge(attempt_out / "muse-judge", before=before, after=after, sandboxed=True,
                                                    instruction=f"A player reported: \"{report}\" A developer changed the game "
                                                    "to fix it. The before frames show the reported game and the after "
                                                    "frames show the candidate fix, on the same route at the same moments. "
                                                    "Accept only if the reported problem is gone and nothing else looks "
                                                    "broken; otherwise reject.").get("decision")
            film.update(counts(film))
            if film["decision"] == "accept" or not live:
                break
        decisions = [a.get("decision") for a in row["attempts"]]
        row["outcome"] = "fixed" if "accept" in decisions else "needs-review" if "needs-review" in decisions else "not-fixed"
    except (Exception, SystemExit) as exc:  # noqa: BLE001 - a crash is recorded, never counted as a fix
        (work / "mutation-fix-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        row.update(outcome="error", detail=f"{type(exc).__name__}: {exc}"[:300])
    row["samImages"] = sam_images_since(images)
    row["wallClockSeconds"] = round(time.perf_counter() - t0, 1)
    (work / "result.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    return row


def _mutated(mutant: dict, out: Path) -> Path:
    """A copy of the one file a mutant edits, as it stands with the mutant in, to diff the undo from."""
    game = out / "rehearsal-game"
    path = game / mutant["file"]
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = (mg.GAME / mutant["file"]).read_text(encoding="utf-8").splitlines(keepends=True)
    lines[mutant["line"] - 1] = mutant["after"] + "\n"
    path.write_text("".join(lines), encoding="utf-8")
    return game


def rehearse(out: Path) -> dict:
    """The whole path on real Godot with a stand-in the study cannot draw and its exact undo as the
    'fix': no Muse, no SAM, no registration. It should end accepted and labelled good."""
    mutant = next(m for m in mb.dry_mutants() if "load-failure" in m["id"])
    out.mkdir(parents=True, exist_ok=True)
    undo = out / "rehearsal-undo.patch"
    undo.write_text(mg.patch_text({**mutant, "before": mutant["after"], "after": mutant["before"]}, game=_mutated(mutant, out)),
                    encoding="utf-8")
    return run_case(mutant, "A rehearsal: the level's art is missing.", "regression/none", out, prereg=mb.DRY_PREREG, live=False,
                    fixture=undo, sam=False, routes=[SMOKE])


def summarize(rows: list[dict]) -> dict:
    attempts = [a for r in rows for a in r.get("attempts") or []]
    judged = [a for a in attempts if a.get("decision") in ("accept", "reject", "needs-review")]
    return {"format": FORMAT + "-summary", "cases": len(rows),
            "fixed": sum(r.get("outcome") == "fixed" for r in rows),
            "notFixed": sum(r.get("outcome") == "not-fixed" for r in rows),
            "needsReview": sum(r.get("outcome") == "needs-review" for r in rows),
            "errors": sum(r.get("outcome") == "error" for r in rows),
            "candidates": len(judged), "good": sum(a.get("label") == "good" for a in judged),
            "bad": sum(a.get("label") == "bad" for a in judged), "unknown": sum(a.get("label") == "unknown" for a in judged),
            "naturalCatches": sum(bool(a.get("naturalCatch")) for a in judged),
            "falseAccepts": sum(bool(a.get("falseAccept")) for a in judged),
            "falseRejects": sum(bool(a.get("falseReject")) for a in judged),
            "acceptedAndGood": sum(any(a.get("decision") == "accept" and a.get("label") == "good" for a in r.get("attempts") or [])
                                   for r in rows),
            "samImages": sum(int(r.get("samImages") or 0) for r in rows), "rows": rows}


def markdown(doc: dict, runs: list[int]) -> str:
    lines = ["# Mutation bench, Part 3: AI-written fixes on generated bugs", "",
             f"Recorded from run{'s' if len(runs) > 1 else ''} {', '.join(map(str, runs))}. Expectrail accepted a candidate on "
             f"{doc['fixed']} of {doc['cases']} generated bugs, {doc['acceptedAndGood']} of them labelled good by the oracle "
             f"({doc['notFixed']} with none accepted, {doc['needsReview']} needing review, {doc['errors']} errors).", "",
             f"Of {doc['candidates']} candidates, the oracle labelled {doc['good']} good, {doc['bad']} bad and {doc['unknown']} "
             "unknown, on routes the judge does not use.", "",
             "| Count | Candidates |", "| --- | --- |", f"| Natural catches | {doc['naturalCatches']} |",
             f"| False accepts | {doc['falseAccepts']} |", f"| False rejects | {doc['falseRejects']} |", "",
             f"SAM images: {doc['samImages']:,} (${doc['samImages'] * SAM_USD_PER_IMAGE:.2f}), including {doc.get('warmImages', 0)} "
             "judging the clean game once. Muse Code does not report its use per run.", "",
             "| Case | Attempt | Source | Decision | Label | Public check | Muse from screenshots |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in doc["rows"]:
        lines += [f"| {r['case']} | {a['attempt']} | {a.get('source')} | {a.get('decision')} | {a.get('label')} | "
                  f"{a.get('publicCheck')} | {a.get('museScreenshots')} |" for a in r.get("attempts") or []]
    return "\n".join(lines) + "\n"


def record(runs: list[int], out: Path, *, prereg: dict | None = None, fetch=mc.download, cases: dict | None = None) -> dict:
    prereg = prereg or mg.load_preregistration()
    cases = cases or load_cases(prereg)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "runs"
        mc.gather(runs, root, fetch)
        rows = [r for r in (json.loads(p.read_text(encoding="utf-8")) for p in sorted(root.rglob("result.json")))
                if r.get("format") == FORMAT]
        if not rows:
            raise SystemExit("these runs have no results")
        if any(r.get("rehearsal") for r in rows):
            raise SystemExit("these runs hold a rehearsal, which is never recorded as a result")
        foreign = sum(r.get("preregistrationSha256") != prereg["sha256"] for r in rows)
        if foreign:
            raise SystemExit(f"{foreign} results are not from this registration")
        names = [r["case"] for r in rows]
        if len(set(names)) != len(names):
            raise SystemExit("a case appears twice, which would count it twice")
        doc = summarize(rows)
        doc["warmImages"] = sum(int(json.loads(p.read_text(encoding="utf-8")).get("samImages") or 0)
                                for p in root.rglob("sam-warm.json"))
        doc["samImages"] += doc["warmImages"]
        doc["runs"] = runs
        doc["missingCases"] = sorted({c["id"] for c in cases["cases"]} - set(names))
        doc["unexpectedCases"] = sorted(set(names) - {c["id"] for c in cases["cases"]})
        staged = Path(tmp) / "staged"
        staged.mkdir()
        (staged / "README.md").write_text(markdown(doc, runs), encoding="utf-8")
        (staged / "summary.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        if export_scan([str(staged)]) != 0:
            raise SystemExit(f"the export scan refused this record, so nothing was written to {out}")
        out.mkdir(parents=True, exist_ok=True)
        for path in staged.iterdir():
            (out / path.name).write_bytes(path.read_bytes())
    return doc


def annotation(row: dict) -> str:
    lines = [f"::notice title=Mutation fix {row['case']} attempt {a['attempt']}::decision {a.get('decision')}; label "
             f"{a.get('label')}; public check {a.get('publicCheck')}; muse screenshots {a.get('museScreenshots')}; "
             f"natural catch {a.get('naturalCatch', False)}" for a in row.get("attempts") or []]
    return "\n".join(lines) or f"::notice title=Mutation fix {row['case']}::{row.get('outcome')}: {row.get('detail')}"


def main(argv: list[str] | None = None) -> int:
    from agents.keys import load_dotenv

    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--pick", action="store_true", help="write the case list from Part 2's record; needs --seed")
    g.add_argument("--estimate", action="store_true", help="the upper bound to post before a live run")
    g.add_argument("--case", help="a mutant id from the case list")
    g.add_argument("--record", action="store_true", help="record runs into bench/mutation/ai-fixes/; needs --run")
    g.add_argument("--rehearse", action="store_true", help="the plumbing on a stand-in: no Muse, no SAM, never a result")
    p.add_argument("--seed", type=int, help="a person's seed, committed before anything runs")
    p.add_argument("--run", type=int, action="append", default=[])
    p.add_argument("--out", type=Path, default=REPO / "runs" / "ai-fixes")
    p.add_argument("--live", action="store_true", help="run Muse Code (spends Meta credit)")
    p.add_argument("--require-sandbox", action="store_true")
    args = p.parse_args(argv)
    try:
        if args.rehearse:
            row = rehearse(args.out)
            attempt = (row.get("attempts") or [{}])[-1]
            print(f"::notice title=Mutation fix rehearsal::{row['outcome']}; {row.get('detail')}; decision {attempt.get('decision')}; "
                  f"label {attempt.get('label')}; a test of the plumbing, never a result")
            return 0 if attempt.get("decision") == "accept" and attempt.get("label") == "good" else 1
        prereg = mg.load_preregistration()
        if args.pick:
            if args.seed is None:
                p.error("--pick needs --seed: the sample's seed is a person's decision")
            if CASES.exists():
                raise SystemExit(f"{CASES} exists, and a committed sample is never redrawn")
            summary = json.loads((mg.PREREGISTRATION.parent / "generated" / "summary.json").read_text(encoding="utf-8"))
            doc = pick(summary, args.seed, prereg)
            CASES.parent.mkdir(parents=True, exist_ok=True)
            CASES.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
            print(f"{doc['sampled']} of {doc['caught']} caught mutants: {CASES}. Commit it before anything runs.")
            return 0
        if args.estimate:
            e = estimate(len(load_cases(prereg)["cases"]) if CASES.exists() else CASE_COUNT)
            print(f"At most {e['maxAttempts']} Muse Code attempts on {e['cases']} cases, and {e['maxSamImages']:,} SAM images "
                  f"(${e['maxSamUsd']:.2f}). Muse Code's own cost is not in that figure. Post this in #156: over $20 needs "
                  "Sean's go-ahead.")
            return 0
        cases = load_cases(prereg)
        if args.record:
            if not args.run:
                p.error("--record needs --run")
            doc = record(args.run, DIR)
            print(f"{DIR}: {doc['cases']} cases, {len(doc['missingCases'])} missing; {doc['naturalCatches']} natural catches")
            return 1 if doc["missingCases"] or doc["unexpectedCases"] or doc["errors"] else 0
        case = next((c for c in cases["cases"] if c["id"] == args.case), None)
        if case is None:
            raise SystemExit(f"{args.case} is not in the case list")
        manifest = mg.load_manifest(prereg, mb.MANIFEST)
        row = run_case(mg.mutant_by_id(manifest, case["id"]), case["report"], case["check"], args.out, prereg=prereg,
                       live=args.live, require_sandbox=args.require_sandbox)
        print(annotation(row))
        return 1 if row["outcome"] == "error" else 0
    except mg.PreregistrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
