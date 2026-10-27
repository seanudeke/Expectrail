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
- **No secrets.** API keys go in your environment or the CI secret store, never in a file.
- **Log new work.** Add a line to [docs/new-work.md](docs/new-work.md) when something lands.
- **Tests.** `python3 -m pip install -r requirements-dev.txt` once, then
  `python3 -m unittest discover -s tests -t .` before you push.
