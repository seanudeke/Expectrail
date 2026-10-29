# Open weights in Nightshift

**Muse Glimmer 30B is a second pair of eyes in every vision check, and Muse Spark Open writes the
checks.** Both are Meta open-weight models, served through partner inference (Fireworks, Baseten) or
our own server. Muse Code (the fixer), Muse Voice Transcribe and SAM 3.1 stay on Meta's hosted API.

This page is for the infrastructure partner verifying the open-weights prize, and for us: what runs
on which model, where, and how to check it.

| Role | Model (license) | Served by | Turn it on | Code |
| --- | --- | --- | --- | --- |
| Vision checks: is the robot visible, are the coins drawn, where are the robot's feet against the level's ground line | Muse Glimmer 30B (Apache 2.0, per its model card) together with SAM 3.1 | A Fireworks on-demand deployment of `accounts/fireworks/models/muse-glimmer-30b` (Glimmer left Fireworks serverless on Sep 25, 2026); or any OpenAI-compatible server we run | `NIGHTSHIFT_OBS_PROVIDER=sam NIGHTSHIFT_VISION_BACKEND=both`, keys in `FIREWORKS_API_KEY` and `MODEL_API_KEY` | `agents/glimmer_client.py` |
| Test-spec drafting from plain English | Muse Spark Open (Muse Model License) | Baseten, `meta-models/muse-spark-open-1026` | `python3 -m nightshift.spec_writer draft "..." --endpoint open`, key in `BASETEN_API_KEY` | `nightshift/spec_writer.py` |
| Sorting playtester feedback and drafting checks from it | Muse Spark Open | Baseten | `python3 -m agents.feedback ... --sorter open` | `agents/feedback.py` |

## Serve Glimmer on Fireworks (on-demand)

Fireworks retired Glimmer from serverless on Sep 25, 2026 (its model page says so), so a request to
`accounts/fireworks/models/muse-glimmer-30b` returns HTTP 404 "Model not found, inaccessible, and/or
not deployed". It still runs as an on-demand deployment: dedicated GPUs, billed per GPU-second while
a replica is up, and able to scale to zero when idle.

1. Create the deployment, from the model's page in the Fireworks dashboard or with `firectl`:

   ```sh
   firectl deployment create accounts/fireworks/models/muse-glimmer-30b \
     --deployment-shape default --min-replica-count 0 --max-replica-count 1 \
     --scale-to-zero-window 15m --wait
   ```

   It prints `accounts/<account>/deployments/<id>`.
2. Put that string in the repository variable `GLIMMER_MODEL` (Settings → Secrets and variables →
   Actions → Variables), or in `NIGHTSHIFT_GLIMMER_MODEL` for local runs.
3. The probe workflow wakes the deployment first (`python -m agents.glimmer_client --warm`): a
   deployment at zero replicas answers 503 for a few minutes while it starts.
4. With minimum replicas at 0 and a 15-minute scale-to-zero window, it stops billing 15 minutes
   after the last request (Fireworks' default window is an hour). Fireworks deletes a deployment
   that has had no traffic for 7 days. Check the GPU price for the shape it picks before leaving it up, and
   recreate it for the judging window (Nov 4 to 9) if the partner needs to see it run.

## How Glimmer fits

The verifier asks one question per frame and object: where is "blue robot" (or "gold coin") drawn?
SAM 3.1 answers through the Meta Model API. Glimmer gets the same question, as an image plus a
JSON-only instruction, and answers with boxes in pixels of the frame.

**With `NIGHTSHIFT_VISION_BACKEND=both` (the verdict setting), an object counts as found only on
frames where both models find it.** The boxes used for geometry are SAM's. So adding Glimmer can
only make a check stricter than SAM alone: a robot Glimmer cannot see fails, even if SAM finds it.

**Glimmer never decides an accept on its own.** It reads images the way a language model reads
text, and the fixer controls the candidate's pixels: a fix could draw text into the game that talks
a vision-language model into "the robot is there". SAM is a segmenter and cannot be talked to, so it
must find the robot too. The verifier refuses `NIGHTSHIFT_VISION_BACKEND=glimmer` (every vision
check becomes needs-review) unless `NIGHTSHIFT_GLIMMER_ALONE=1` is set to measure Glimmer on known
fixtures.

Everything around the question is shared code (`agents/sam_observations.py`):

- sampling every fourth frame by default (`NIGHTSHIFT_SAM_EVERY`; the probe workflow defaults to
  every tenth);
- refining to the exact first bad frame;
- confirming every remaining frame before a pass;
- the cache, keyed by model, endpoint and prompt version;
- turning any failure into needs-review, never a pass.

The evaluator then decides each spec from the boxes, in plain code. Glimmer is never asked "is it
below the ground", only "where is it".

Why open weights matter here beyond the prize: an unreleased game build is confidential, and a
studio wants its quality gate on infrastructure it controls. Glimmer can run on the studio's own
server today. Making it safe to drop SAM entirely needs the engine cross-check in "What is not
built yet".

## How to verify it

- Every observations document records `model.name` (the model id) and `model.provider`, for example
  `open-weights glimmer at api.fireworks.ai, self-reported confidence`. The verifier keeps one per
  check in `runs/<run>/verify/`.
- **Glimmer probe** (Actions, manual): mode `probe` renders the clean game and every seeded bug and
  asks Glimmer alone what it sees. Mode `verify` runs the Gate 1 path with judge `both` (or Glimmer
  alone, as a measurement), including the private held-out routes. Results are posted as
  annotations on the run. The key is only sent over https to `api.fireworks.ai` or the host in the
  `GLIMMER_ALLOWED_HOST` repository variable.
- Self-hosting: Glimmer's model card documents OpenAI-compatible serving with vLLM and SGLang, and
  says the 4-bit weights fit a 24 GB GPU. Point `NIGHTSHIFT_GLIMMER_API_BASE` at the server's `/v1`
  URL and set `NIGHTSHIFT_GLIMMER_MODEL` to the id it serves. If the server resizes images before the
  model sees them, Glimmer's pixels are in the resized image's space: run the probe and set
  `NIGHTSHIFT_GLIMMER_COORDS` to match before trusting any box.

## What is not measured yet

- **Glimmer's accuracy on our art.** SAM 3.1 was measured on Oct 28 (docs/sam.md): "blue robot" in
  120 of 120 clean frames, and all six seeded bugs failed with no false alarm. Glimmer has not been
  run on our frames yet. The Glimmer probe measures it on the same runs. SAM stays the default
  backend until Glimmer's numbers are in.
- **Box precision.** The hybrid ground check compares the robot's box against the ground line with
  a 20-pixel tolerance. A loose box from a vision-language model could raise false alarms there. The
  probe's clean run shows this.
- **Confidence is self-reported.** Glimmer rates its own boxes from 0 to 1. The evaluator's 0.5
  threshold and the verifier's clean-score floor apply to that number, and the document says it is
  self-reported.
- **Coordinates.** The prompt asks for pixels of the image. If the probe shows Glimmer answering on
  a 0-1000 grid, set `NIGHTSHIFT_GLIMMER_COORDS=norm1000`. Boxes with corners in the wrong order, or
  more than 2% of the frame outside it, are refused (needs-review); a box a few pixels past an edge
  is clipped to it. A grid mismatch is not always detectable from one answer (on a 1600x960 frame, a
  0-1000 box also looks like pixels), which is why the probe compares Glimmer's boxes with SAM's on
  the same frames first.

## What is not built yet

- **An engine cross-check for Glimmer alone.** The harness knows where the robot is on every frame
  (the position log, projected to frame pixels). Requiring Glimmer's robot box to agree with it would
  stop an injected "it's there" without SAM, and would let a studio run the vision checks entirely on
  its own hardware. Until that exists, accepts need SAM too.

## Keys

`FIREWORKS_API_KEY` (or `NIGHTSHIFT_GLIMMER_API_KEY`) and `BASETEN_API_KEY` (or
`NIGHTSHIFT_OPEN_API_KEY`) are read from the environment or the gitignored `.env`. None of them is on
Muse Code's environment allowlist. The Glimmer key may not be the same as `META_API_KEY`, the key
the fixer holds. In CI, add the `FIREWORKS_API_KEY` repository secret; `both` also needs the SAM key
(`MODEL_API_KEY`).
