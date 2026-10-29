# Open weights in Nightshift

**Muse Glimmer 30B can be Nightshift's eyes, and Muse Spark Open can write its checks.** Both are Meta
open-weight models, served through partner inference (Fireworks, Baseten) or our own server. Muse
Code (the fixer) and Muse Voice Transcribe stay on Meta's hosted API.

This page is for the infrastructure partner verifying the open-weights prize, and for us: what runs
on which model, where, and how to check it.

| Role | Model (license) | Served by | Turn it on | Code |
| --- | --- | --- | --- | --- |
| Vision checks: is the robot visible, are the coins drawn, where are the robot's feet against the level's ground line | Muse Glimmer 30B (Apache 2.0) | Fireworks serverless, `accounts/fireworks/models/muse-glimmer-30b`; or any OpenAI-compatible server we run | `NIGHTSHIFT_OBS_PROVIDER=sam NIGHTSHIFT_VISION_BACKEND=glimmer`, key in `FIREWORKS_API_KEY` | `agents/glimmer_client.py` |
| Test-spec drafting from plain English | Muse Spark Open (Muse Model License) | Baseten, `meta-models/muse-spark-open-1026` | `python3 -m nightshift.spec_writer draft "..." --endpoint open`, key in `BASETEN_API_KEY` | `nightshift/spec_writer.py` |
| Sorting playtester feedback and drafting checks from it | Muse Spark Open | Baseten | `python3 -m agents.feedback ... --sorter open` | `agents/feedback.py` |

## How Glimmer fits

The verifier asks one question per frame and object: where is "blue robot" (or "gold coin") drawn?
With SAM 3.1 that question goes to the Meta Model API. With `NIGHTSHIFT_VISION_BACKEND=glimmer` the same
question goes to Glimmer, as an image plus a JSON-only instruction, and Glimmer answers with boxes in
pixels of the frame. Everything around the question is shared code (`agents/sam_observations.py`):

- sampling every fourth frame;
- refining to the exact first bad frame;
- confirming every remaining frame before a pass;
- the cache, keyed by model, endpoint and prompt version;
- turning any failure into needs-review, never a pass.

The evaluator then decides each spec from the boxes, in plain code. Glimmer is never asked "is it
below the ground", only "where is it".

Why it matters beyond the prize: an unreleased game build is confidential. With Glimmer on a server
the studio runs, the captured frames of a pre-release build never leave it.

## How to verify it

- Every observations document records `model.name` (the model id) and `model.provider`, for example
  `open-weights glimmer at api.fireworks.ai, self-reported confidence`. The verifier keeps one per
  check in `runs/<run>/verify/`.
- **Glimmer probe** (Actions, manual): mode `probe` renders the clean game and every seeded bug and
  asks Glimmer what it sees. Mode `verify` runs the Gate 1 path with Glimmer as the eyes, including
  the private held-out routes. Results are posted as annotations on the run.
- Self-hosting: Glimmer's model card documents OpenAI-compatible serving with vLLM and SGLang; the
  4-bit weights fit a 24 GB GPU. Point `NIGHTSHIFT_GLIMMER_API_BASE` at the server's `/v1` URL and
  set `NIGHTSHIFT_GLIMMER_MODEL` to the id it serves. Nothing else changes.

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
- **Coordinates.** The prompt asks for pixels. If the probe shows Glimmer answering on a 0-1000 grid,
  set `NIGHTSHIFT_GLIMMER_COORDS=norm1000`. A box far outside the frame is refused, never clipped
  into a pass.

## Keys

`FIREWORKS_API_KEY` (or `NIGHTSHIFT_GLIMMER_API_KEY`) and `BASETEN_API_KEY` (or
`NIGHTSHIFT_OPEN_API_KEY`) are read from the environment or the gitignored `.env`. None of them is on
Muse Code's environment allowlist. The Glimmer key may not be the same as `META_API_KEY`, the key
the fixer holds. In CI, add the `FIREWORKS_API_KEY` repository secret.
