# Advisory discovery records

What [docs/discovery.md](../../docs/discovery.md) reports, as the runs wrote it.

- [`local-oct31/`](local-oct31): one local job on October 31, the clean game as the reference and
  the four reported bugs as base builds, all 22 library probes, planner off. Written by
  `python -m expectrail.discovery.cli discover` (the `discovery-run.json` record and its
  `report.md`), copied here unedited. Local, so it is the record of that run, not a CI annotation.
- `run-<id>.json`: a Discovery workflow run, one job per build, written by
  `python -m expectrail.discovery.cli collect --run <id>` from the jobs' own notices. Do not edit by
  hand.
- [`blind-run-41248745687.json`](blind-run-41248745687.json): blind run 1 on the private fresh set,
  planner off: 4 of 8 defects flagged, 0 of 3 healthy builds, no incomplete job. Written by
  `python -m expectrail.discovery.fresh collect --run <id>` from the jobs' counts-only notices; do
  not edit by hand.
- [`blind-run-41250932288.json`](blind-run-41250932288.json): blind run 2, the same set dispatched
  with the planner on. Every job recorded the planner as unavailable (Muse Spark returned no
  content), so it is a second planner-off result: the same 4 of 8 and 0 of 3.
- [`blind-run-41319184209.json`](blind-run-41319184209.json) and
  [`blind-run-41319197682.json`](blind-run-41319197682.json): blind runs 3 and 4, fresh set 2 under
  freeze 2, planner off then on: 3 of 8 and 4 of 8 defects, 0 of 3 healthy builds each.
- [`run-41326269491.json`](run-41326269491.json): the thirteen public builds again, plus four
  shortcut fixes that disable a feature and two healthy retunes (`bugs/challenges/`), planner off:
  4 of 4 shortcuts flagged by their guards, neither retune flagged.
- [`run-41251642563.json`](run-41251642563.json) and [`run-41252054622.json`](run-41252054622.json):
  the planner's first live answers, on the public builds, on branch `discovery/planner-fix` before
  it merged: without a reference, then with the clean game as each job's reference.

The local and `run-<id>` records are labelled `development-reproduction`: the profile and probes were
written after the four reported bugs were known. The `blind-run-<id>` records are not. None of this
gates a fix: these are the checks nobody wrote, beside the checks people wrote that the verifier
runs.
