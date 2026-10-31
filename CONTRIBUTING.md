# Working in this repository

- **Branches and pull requests.** Work on a branch named after your lane (`vision/...`,
  `harness/...`, `agents/...`, `product/...`) and merge through a pull request that CI passes.
  Keep pull requests small; the end-to-end loop has to work every day from October 28.
- **Contracts first.** If a change needs a field another lane reads, change the schema, the
  example and both sides in one pull request (see [docs/contracts.md](docs/contracts.md)).
- **The game stays clean.** Never edit `game/platformer` to seed a bug: add a patch under `bugs/`.
  Candidate fixes from the fixer are patches too.
- **Held-out cases stay out.** Held-out bug variants and the gameplay checks used to judge fixes
  do not go in this repository during the event; the fixer must not be able to read them.
- **Two kinds of checks.** Checks people write (specs a person approves, the gameplay check, the
  held-out cases) decide a fix. Discovery's contracts ([docs/discovery.md](docs/discovery.md)) only
  advise; never wire one into the verifier's decision without the promotion stage it describes.
- **Discovery is frozen for the blind run.** Do not change a file listed in `discovery/freeze.json`
  until the blind run is recorded in `bench/discovery/`; `tests/test_discovery_freeze.py` fails if
  you do. The fresh defect set stays in the private repository; only its digest is here.
- **No secrets.** API keys go in your environment or the CI secret store, never in a file.
- **Log new work.** Add a line to [docs/new-work.md](docs/new-work.md) when something lands.
- **Tests.** `python3 -m pip install -r requirements-dev.txt` once, then
  `python3 -m unittest discover -s tests -t .` before you push.
