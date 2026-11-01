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
- **Discovery stays frozen while a fresh set is in use.** Set 1 (freeze 1) is retired; set 2 is
  written against freeze 2 (`discovery/freeze.json`). Do not change a file it lists until set 2's
  runs are recorded and the team retires it; `tests/test_discovery_freeze.py` fails if you do.
  Changing the discoverer after that needs a new freeze and a new fresh set. Fresh sets stay in the
  private repository; only their digests are here.
- **No secrets.** API keys go in your environment or the CI secret store, never in a file.
- **Log new work.** Add a line to [docs/new-work.md](docs/new-work.md) when something lands.
- **Tests.** `python3 -m pip install -r requirements-dev.txt` once, then
  `python3 -m unittest discover -s tests -t .` before you push.
