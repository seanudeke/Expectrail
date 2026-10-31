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

The local and `run-<id>` records are labelled `development-reproduction`: the profile and probes were
written after the four reported bugs were known. The blind run is the first record that is not. None of this
gates a fix: these are the checks nobody wrote, beside the checks people wrote that the verifier
runs.
