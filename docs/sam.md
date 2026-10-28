# SAM 3.1 in Nightshift

SAM 3.1 turns captured frames into observations: for each object a test spec names, where it is in
each frame and how sure the model is. The evaluator then decides the spec over those boxes with
plain code. This page is the handoff for wiring SAM in for real and calibrating it.

## Status

- Built: the adapter (`agents/sam_observations.py`), the probe (`agents/sam_probe.py`), a manual
  GitHub Actions workflow (**SAM probe**), the verifier wiring, and offline tests
  (`tests/test_sam.py`).
- **Live since October 28.** The probe has run against the real API: about one second per request,
  every response parsed. Findings and the specs they led to are below.
- CI on pull requests keeps using the position-log stand-in (`trace` provider). It has no key.

## What the live probes found (October 28)

Runs 40653267793 to 40656100304 of the SAM probe workflow; per-run results are on the
`sam-probe-results` branch.

- **SAM 3.1 does not see the ground in this game's art.** It segments things, not surfaces.
  "grass-topped ground", "ground", "floor", "dirt", "terrain", "platform", "cliff" and "ledge"
  matched nothing in 13 of 13 frames; "grass" matched the grass band in 3 of 13; "rock" found the
  decorative boulders. So the ground spec (`player-stays-above-ground`) cannot be judged by SAM.
- **"small robot character" also matches the red beetle enemies**, at up to 0.84 confidence. If the
  robot fell out of view, SAM would point at an enemy and the bug would be missed.
- **"blue robot" matches only the robot**: 120 of 120 clean frames (lowest 0.64), nothing else in
  the scene ever matched. "blue and white robot", "robot boy" and "astronaut" were close behind;
  "robot" and "small robot" also match the enemies.
- **"gold coin" finds the coins**: 120 of 120 clean frames (lowest 0.69), 11 to 16 coins a frame.

That led to two specs Sean approved on October 28:

| Spec | Prompt | Clean (every frame) | Seeded bugs (every 4th frame) |
| --- | --- | --- | --- |
| `player-always-visible` | blue robot | pass, 120/120 | fall-through v1, v2: fail (robot seen in 6/31); layering v1, v2: fail (17/31); missing-texture: pass |
| `coins-visible` | gold coin | pass, 120/120 | missing-texture v1, v2: fail (0/13) |

Together they fail all six seeded bugs with no false alarm on the clean run. The ground spec stays
judged on the engine's position log, labeled that way; combining the engine's ground line with
SAM's robot box is the next step after Gate 2.

One honest limit: "always visible" cannot see a robot that sinks partway into the ground but stays
on screen. The ground spec on the position log still covers that.

## Where SAM runs

SAM 3.1 is on the Meta Model API, the same service and key type as Muse Spark. No GPU and no
Hugging Face access are needed.

| | |
| --- | --- |
| Endpoint | `POST https://api.meta.ai/v1/responses` |
| Model | `sam-3.1` |
| Key | `MODEL_API_KEY`, from the shell or the gitignored `.env`; never committed, never pasted into chat |
| One request | one concept prompt (a short noun phrase) and one frame as a base64 PNG |
| Asked for | `include_confidence` (the evaluator thresholds on it), masks in the small one-bit encoding |

`MODEL_API_KEY` is not on Muse Code's environment allowlist (`agents.keys.MUSE_ENV_ALLOWLIST`),
and a test keeps it that way. That only protects the variable, not the value: if `MODEL_API_KEY`
and `META_API_KEY` hold the same key, the fixer holds the verifier's key too. **Use a separate
key for SAM** (a second key from dev.meta.ai, stored as the `MODEL_API_KEY` secret). The adapter
prints a warning when the two are the same. The CI jobs that set `MODEL_API_KEY` from the
`META_API_KEY` secret do not run SAM today; switch them to their own secret before they do.

Check the pricing and rate limits page on dev.meta.ai before a big run. The probe's `--dry-run`
prints how many requests it would send.

## Run it

**From GitHub, no setup.** Actions, then **SAM probe**, then **Run workflow**. It renders the clean
game and every seeded bug, probes every 10th frame (13 frames a run), and puts `probe.md` in the
run summary. Overlays and contact sheets are in the `sam-probe` artifact. It uses the
`MODEL_API_KEY` secret, or `META_API_KEY` if that is the only one set. The workflow appears in the
Actions list once this file is on `main`.

**Locally:**

```sh
export MODEL_API_KEY=...                      # or put it in .env
python3 -m harness.check_seeded --out runs/seeded          # clean + seeded bugs, with frames
python3 -m agents.sam_probe --runs runs/seeded/*/ \
  --spec specs/player-stays-above-ground.json --every 10 --dry-run   # what it would send
python3 -m agents.sam_probe --runs runs/seeded/*/ \
  --spec specs/player-stays-above-ground.json --every 10 --out runs/sam-probe
open runs/sam-probe/probe.md runs/sam-probe/*-sheet.png
```

**One replay, then its verdict:**

```sh
python3 -m agents.sam_observations --run runs/seeded/physics-fall-through_v1 \
  --spec specs/player-stays-above-ground.json
```

**The whole loop:** set `NIGHTSHIFT_OBS_PROVIDER=sam`. For the candidate, clean and held-out
replays, the verifier then judges:

- the ground spec on the engine's position log, as before;
- every spec in `agents.verifier.SAM_SPECS` (player always visible, coins visible) on SAM's view of
  the same frames. Override the list with `NIGHTSHIFT_SAM_SPECS=specs/a.json,specs/b.json`.

Every check must pass. The suite provenance says which source judged what. The held-out routes
have not been probed with SAM yet (their frames must not leave the verifier machine), so the
first SAM-on verifier run there is also their first SAM test.

**Prompt sweeps.** `--sweep player="blue robot|robot boy|astronaut"` tries several prompts for one
object over the same frames; `--set ground=grass` probes one other prompt without editing the spec.
Both are inputs on the SAM probe workflow, together with `runs` to probe only some runs.

## What is still open

1. **Held-out routes under SAM.** Run the verifier with `NIGHTSHIFT_OBS_PROVIDER=sam` on the
   verifier machine and read `verdict-held-out.json`: each route lists `visuals` per spec. Coins
   in particular may be off screen on some private route.
2. **The ground, properly.** Log the camera each frame in the harness, project the level's ground
   line into frame pixels, and compare it with SAM's robot box. That restores a vision-checked
   `never-crosses` and catches a robot that sinks but stays visible.
3. **Score margin.** The lowest clean scores were 0.64 (player) and 0.69 (coins) against the 0.5
   threshold. Watch it when the art or the camera changes.
4. **Sample rate.** Every 4th frame cost 31 requests a run, at about one second each with four in
   flight. A fail found on a sample is exact, but an accept rests on every 4th frame: a player who
   flickers out for two or three frames could be missed. For the recorded demo, consider
   `NIGHTSHIFT_SAM_EVERY=1` on the verifier (120 requests a replay per spec).

## How it looks at fewer frames

- **Sample.** Every Nth frame of the spec's window, plus its last frame (`NIGHTSHIFT_SAM_EVERY`,
  default 4).
- **Refine.** When the spec fails on a sampled frame, look at every frame between the last sample
  that passed on its own and the first failing one, so the first bad frame in the report is exact.
  A sample where the object was missing or the check did not apply does not count as passing, so
  the stretch reaches back past it. In the offline test, a fall that starts between samples is
  found at the same frame as looking at every frame, from 22 of 120 frames.
- **Cache.** Results are kept by frame SHA-256, prompt, model and request settings, so a frame
  that was already judged is never sent again. Replays are bit-identical, so an unchanged route
  costs nothing the second time.
- **Counting assertions are not sampled.** `visible` with a `minFraction` below 1 looks at every
  frame. `reaches` samples, and unless a sample already reaches the goal it looks at every frame
  before deciding.

Limits, plainly: a glitch shorter than the gap between samples can be missed (use
`NIGHTSHIFT_SAM_EVERY=1` for a run that must not miss one). Every verdict says how many frames it
judged, and the observations document records `framesAnalyzed` against `framesCaptured`.

**The cache is verifier state.** It lives outside the repo (`~/.cache/nightshift/sam`, or
`NIGHTSHIFT_SAM_CACHE`), so it is never in the fixer's worktree, and under bubblewrap the fixer gets
an empty home directory and cannot reach it. With no OS sandbox nothing stops a process on the same
machine from writing there, so set `NIGHTSHIFT_SAM_CACHE=off` for the recorded demo and any run
whose verdict has to be beyond question.

## When SAM fails

Any failure makes the check needs-review, never a pass and never a crash. That covers a failed,
partial or unrecognised reply, a box without a confidence, a number that is not finite, missing
frames, and anything unexpected. With SAM on in the verifier, each SAM spec is its own check:

- candidate and clean replays: that spec's check is needs-review, with the error in
  `observations-<spec>-error.txt` or `observations-clean-<spec>-error.txt`; the ground check is
  still judged on the engine's position log;
- held-out routes: the route is needs-review for that spec (see `visuals` in
  `verdict-held-out.json`);
- no frames to look at (offline fixtures, a failed clean harness run, the interim held-out fixture
  or no private set mounted): the SAM checks are needs-review, so a SAM-on accept always means SAM
  looked at the candidate, the clean game and every private route.

Rate limits, server errors and dropped connections are retried three times with backoff; bad
requests are not retried. After the first failure, queued requests for that replay are cancelled.
The parser is strict: text it does not recognise is an error, not "nothing found", so a refusal or
a format change can never be cached as a frame with no player in it.

## Not built yet

- **Video mode.** SAM 3.1 can take a whole clip in one request and track objects with stable ids
  (billed per frame, 50-frame minimum per request, up to 16 tracked objects). Worth it if
  per-frame requests are slow or costly. Trade-offs: H.264 compression of the frames, and the
  cache would work per run instead of per frame.
- **Box and point prompts from the engine.** SAM 3.1 also takes a box or point saying where to look.
  Prompting it with where the engine says the player is would make detection more reliable, and a
  missing texture or a hidden sprite would still come back empty. It also makes vision less
  independent of the engine, so if we use it we say so.
- **Masks.** Boxes are all the evaluator uses today.
