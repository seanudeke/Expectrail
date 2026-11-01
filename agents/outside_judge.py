"""Outside-model screenshot judges: Claude and GPT shown exactly what Muse's screenshot judge sees.

The judge benchmark (agents.judge_bench) asks who accepts a fix that only looks right. Muse Code
judging from screenshots accepted 2 of 7 in every run so far. This asks the same of the strongest
model each of two other vendors sells, so the comparison is not "Expectrail against one model":

  - the same prompt text, byte for byte (agents.muse_judge.build_judge_prompt, policy screenshots-v1);
  - the same five before and five after frames, under the same file names, attached inline after the
    prompt, each image preceded by its file name, with one added line saying so;
  - the same decision line, parsed the same way, failing closed: no parseable DECISION line, an
    error, or a refused request is undecided, never a rejection;
  - several independent passes per case (``--passes``), each its own request, all reported.

Neither model sees Expectrail's checks, the engine's log, the held-out routes or SAM. These are API
calls made by the benchmark, outside the fixer's sandbox; the keys are never in Muse Code's
environment (agents.keys.muse_subprocess_env is an allowlist).

    python3 -m agents.outside_judge --smoke                     # one tiny text call each, no frames
    python3 -m agents.outside_judge --collect --run <id> --out bench/judge/outside-models
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agents.muse_judge import PROMPT_POLICY, build_judge_prompt, file_sha256, parse_decision, prompt_sha256

FORMAT = "expectrail.outside-judge/v0"
# Chosen before the first run (Nov 1, 2026): each vendor's most capable generally available model. A repo
# variable can name another model of the same vendor; the model that answered is recorded with every decision.
JUDGES = {
    "claude": {"vendor": "anthropic", "model": "claude-fable-5-1", "keyEnv": "ANTHROPIC_API_KEY",
               "modelEnv": "EXPECTRAIL_OUTSIDE_CLAUDE_MODEL", "label": "Claude"},
    "gpt": {"vendor": "openai", "model": "gpt-6-astra", "keyEnv": "OPENAI_API_KEY",
            "modelEnv": "EXPECTRAIL_OUTSIDE_GPT_MODEL", "label": "GPT", "effort": "high"},
}
# List prices per million tokens (input, output), from the vendors' model pages on Nov 1, 2026, used
# only to estimate spend; the bill is the record.
PRICES = {"claude-fable-5-1": (10.0, 50.0), "claude-opus-5-5": (4.0, 20.0),
          "gpt-6-astra": (10.0, 50.0), "gpt-6.1-sol": (2.0, 10.0)}
INLINE_NOTE = "The image files listed above are attached below, each after its file name."
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
OPENAI_URL = "https://api.openai.com/v1/responses"
RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 529}
TIMEOUT = 600
# A public game frame (a published review's), so the smoke check sends a real image in the real format.
SMOKE_FRAME = Path(__file__).resolve().parents[1] / "docs" / "review" / "live-demo-run-1" / "assets" / "base.png"


def model_for(name: str) -> str:
    j = JUDGES[name]
    return os.environ.get(j["modelEnv"]) or j["model"]


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def labels(before: list[Path], after: list[Path]) -> tuple[list[str], list[str]]:
    """The file names Muse's judge sees for the same frames (agents.muse_judge.run_muse_judge)."""
    return ([f"frames/before-{i + 1}.png" for i in range(len(before))],
            [f"frames/after-{i + 1}.png" for i in range(len(after))])


def anthropic_body(model: str, prompt: str, frames: list[tuple[str, Path]]) -> dict:
    content: list[dict] = [{"type": "text", "text": prompt}, {"type": "text", "text": INLINE_NOTE}]
    for label, path in frames:
        content.append({"type": "text", "text": f"{label}:"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _b64(path)}})
    return {"model": model, "max_tokens": 16000, "messages": [{"role": "user", "content": content}]}


def openai_body(model: str, prompt: str, frames: list[tuple[str, Path]], effort: str | None) -> dict:
    content: list[dict] = [{"type": "input_text", "text": prompt}, {"type": "input_text", "text": INLINE_NOTE}]
    for label, path in frames:
        content.append({"type": "input_text", "text": f"{label}:"})
        content.append({"type": "input_image", "image_url": f"data:image/png;base64,{_b64(path)}", "detail": "high"})
    body: dict = {"model": model, "input": [{"role": "user", "content": content}], "max_output_tokens": 32000}
    if effort:
        body["reasoning"] = {"effort": effort}
    return body


def anthropic_text(resp: dict) -> str:
    return "\n".join(b.get("text", "") for b in resp.get("content") or [] if b.get("type") == "text")


def openai_text(resp: dict) -> str:
    parts = [c.get("text", "") for item in resp.get("output") or [] if item.get("type") == "message"
             for c in item.get("content") or [] if c.get("type") == "output_text"]
    return "\n".join(parts) or str(resp.get("output_text") or "")


def usage_of(vendor: str, resp: dict) -> dict:
    u = resp.get("usage") or {}
    return {"inputTokens": int(u.get("input_tokens") or 0), "outputTokens": int(u.get("output_tokens") or 0)}


def http_post(url: str, headers: dict, body: dict, timeout: int = TIMEOUT) -> tuple[int, dict | str]:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(text)
        except ValueError:
            return e.code, text


def _headers(name: str, key: str) -> dict:
    if JUDGES[name]["vendor"] == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    return {"authorization": f"Bearer {key}"}


def _error_text(payload: dict | str) -> str:
    if isinstance(payload, dict):
        err = payload.get("error")
        payload = err.get("message") if isinstance(err, dict) else json.dumps(payload)
    return " ".join(str(payload).split())[:300]


def call(name: str, prompt: str, frames: list[tuple[str, Path]], *, post=http_post, sleep=time.sleep,
         retries: int = 2, wait: float = 30.0) -> dict:
    """One request to one judge. Never raises for an API failure: it returns an undecided result."""
    j = JUDGES[name]
    model = model_for(name)
    key = os.environ.get(j["keyEnv"]) or ""
    base = {"judge": name, "vendor": j["vendor"], "model": model, "decision": None, "usage": None}
    if not key:
        return {**base, "ok": False, "detail": f"{j['keyEnv']} is not set"}
    if j["vendor"] == "anthropic":
        url, body, text_of = ANTHROPIC_URL, anthropic_body(model, prompt, frames), anthropic_text
    else:
        url, body, text_of = OPENAI_URL, openai_body(model, prompt, frames, j.get("effort")), openai_text
    t0 = time.perf_counter()
    status, payload, attempt = 0, "", 0
    for attempt in range(retries + 1):
        try:
            status, payload = post(url, _headers(name, key), body)
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
            status, payload = 0, f"{type(exc).__name__}: {exc}"
        if status == 200 or (status and status not in RETRYABLE):
            break
        if attempt < retries:
            sleep(wait)
    seconds = round(time.perf_counter() - t0, 1)
    if status != 200 or not isinstance(payload, dict):
        return {**base, "ok": False, "seconds": seconds, "attempts": attempt + 1,
                "detail": f"HTTP {status}: {_error_text(payload)}"}
    reply = text_of(payload)
    decision = parse_decision(reply)
    stop = payload.get("stop_reason") or payload.get("status")
    answered = payload.get("model") or model
    return {**base, "model": answered, "ok": decision is not None, "decision": decision, "reply": reply,
            "stop": stop, "seconds": seconds, "attempts": attempt + 1, "usage": usage_of(j["vendor"], payload),
            "detail": (f"{name} {decision} under {PROMPT_POLICY}" if decision
                       else f"{name} gave no DECISION line (stop {stop})")}


def judge_frames(out: Path, *, before: list[Path], after: list[Path], instruction: str, names: list[str],
                 passes: int, post=http_post, sleep=time.sleep) -> dict:
    """Every named judge, ``passes`` times each, on one case's frames. Writes one file per call."""
    before_rels, after_rels = labels(before, after)
    prompt = build_judge_prompt(before_rel=before_rels, after_rel=after_rels, instruction=instruction)
    frames = list(zip(before_rels + after_rels, before + after))
    out.mkdir(parents=True, exist_ok=True)
    (out / "prompt.txt").write_text(prompt, encoding="utf-8")
    meta = {"promptPolicy": PROMPT_POLICY, "promptSha256": prompt_sha256(prompt), "inlineNote": INLINE_NOTE,
            "frames": [{"label": lab, "sha256": file_sha256(p)} for lab, p in frames]}

    def one_judge(name: str) -> list[dict]:
        calls = []
        for n in range(1, passes + 1):  # each pass is its own request, one after another
            r = call(name, prompt, frames, post=post, sleep=sleep)
            r["pass"] = n
            (out / f"{name}-pass-{n}.json").write_text(json.dumps({"format": FORMAT, **meta, **r}, indent=2) + "\n",
                                                       encoding="utf-8")
            calls.append(r)
        return calls

    with ThreadPoolExecutor(max_workers=max(1, len(names))) as pool:  # the vendors side by side
        done = dict(zip(names, pool.map(one_judge, names)))
    results: dict = {}
    for name in names:
        calls = done[name]
        results[name] = {"model": calls[0]["model"] if calls else model_for(name),
                         "decisions": [c["decision"] for c in calls],
                         "details": [c["detail"] for c in calls],
                         "reasons": [reason(c.get("reply") or "") for c in calls],
                         "usage": [c.get("usage") for c in calls],
                         "usd": round(sum(cost(c["model"], c.get("usage")) for c in calls), 4)}
    (out / "outside.json").write_text(json.dumps({"format": FORMAT, **meta, "judges": results}, indent=2) + "\n",
                                      encoding="utf-8")
    return results


def reason(reply: str, limit: int = 400) -> str:
    """The model's own words just before its decision line, like agents.judge_bench.muse_reason."""
    text = " ".join(reply.split())
    cut = text.rfind("DECISION:")
    text = text[:cut].strip() if cut >= 0 else text
    return text if len(text) <= limit else "..." + text[-limit:]


def cost(model: str, usage: dict | None) -> float:
    if not usage or model not in PRICES:
        return 0.0
    i, o = PRICES[model]
    return usage["inputTokens"] / 1e6 * i + usage["outputTokens"] / 1e6 * o


def smoke(post=http_post, frame: Path = SMOKE_FRAME) -> int:
    """One short request per judge with one public game frame attached, in the same format as the
    benchmark's: is the key set, is the model there, does it take the image and answer? Its answer is
    not a benchmark result."""
    bad = 0
    for name, j in JUDGES.items():
        key = os.environ.get(j["keyEnv"]) or ""
        model = model_for(name)
        if not key:
            print(f"::error title=Outside judge {name}::{j['keyEnv']} is not set")
            bad += 1
            continue
        ask = "This is a connection check. Look at the attached frame, then reply with exactly: DECISION: accept"
        if j["vendor"] == "anthropic":
            url, body = ANTHROPIC_URL, anthropic_body(model, ask, [("frame.png", frame)])
        else:
            url, body = OPENAI_URL, openai_body(model, ask, [("frame.png", frame)], None)
        try:
            status, payload = post(url, _headers(name, key), body)
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
            status, payload = 0, f"{type(exc).__name__}: {exc}"
        if status != 200 or not isinstance(payload, dict):
            print(f"::error title=Outside judge {name}::{model}: HTTP {status}: {_error_text(payload)}")
            bad += 1
            continue
        text = anthropic_text(payload) if j["vendor"] == "anthropic" else openai_text(payload)
        print(f"::notice title=Outside judge {name}::{payload.get('model') or model} answered "
              f"({parse_decision(text) or 'no decision line'})")
    return 1 if bad else 0


# ---- collecting a run's annotations into bench/judge/outside-models/ ----

def annotation(case: str, label: str, results: dict) -> list[str]:
    """The workflow's lines for one case: decisions per pass, then each judge's words (public cases only)."""
    parts = [f"{n} {r['model']} " + ",".join(str(d) for d in r["decisions"]) for n, r in results.items()]
    usd = sum(r.get("usd") or 0 for r in results.values())
    lines = [f"::notice title=Judge outside {case}::label {label}; " + "; ".join(parts) + f"; est ${usd:.2f}"]
    for n, r in results.items():
        words = " || ".join(f"{i}: {w}" for i, w in enumerate(r["reasons"], 1) if w)
        if words:
            lines.append(f"::notice title=Judge outside reasons {n} {case}::" + " ".join(words.split())[:900])
    return lines


def parse_annotation(message: str) -> dict:
    """'label bad; claude claude-fable-5-1 accept,reject,accept; gpt gpt-6-astra reject,reject,reject; est $1.23'"""
    fields = [f.strip() for f in message.split(";")]
    if not fields or not fields[0].startswith("label "):
        raise ValueError(f"unrecognised outside-judge annotation: {message!r}")
    label = fields[0].split()[1]
    judges, usd = {}, None
    for f in fields[1:]:
        if f.startswith("est $"):
            usd = float(f[5:])
            continue
        name, model, decisions = f.split(" ", 2)
        judges[name] = {"model": model,
                        "decisions": [d if d in ("accept", "reject", "needs-review") else None
                                      for d in decisions.split(",")]}
    return {"label": label, "judges": judges, "usd": usd}


def collect(run_id: int, fetch=None) -> dict:
    from agents import bench_collect as bc

    fetch = fetch or bc.gh_json
    run, notes = bc.run_annotations(run_id, fetch, prefix="judge-run")
    rows: dict[str, dict] = {}
    for note in notes:
        title = note.get("title") or ""
        message = " ".join((note.get("message") or "").split())
        if title.startswith("Judge outside reasons "):
            name, case = title[len("Judge outside reasons "):].split(" ", 1)
            rows.setdefault(case, {}).setdefault("reasons", {})[name] = message
        elif title.startswith("Judge outside "):
            case = title[len("Judge outside "):]
            rows.setdefault(case, {}).update(parse_annotation(message))
        else:
            m = bc.JUDGE_TITLE.match(title)
            if m:
                msg = bc.JUDGE_MSG.match(message)
                if not msg:
                    raise ValueError(f"unrecognised judge annotation: {message!r}")
                d = lambda v: v if v in ("accept", "reject", "needs-review") else None  # noqa: E731
                rows.setdefault(m["case"], {}).update({"museScreenshots": d(msg["muse"]),
                                                       "expectrailNoSam": d(msg["nosam"]),
                                                       "live": msg["live"] == "True"})
    out_rows = []
    for case, r in sorted(rows.items(), key=lambda kv: (kv[1].get("label") != "bad", kv[0])):
        if "judges" not in r:
            raise SystemExit(f"run {run_id}: {case} has no outside-judge line")
        if not r.get("live"):
            raise SystemExit(f"run {run_id}: {case} was not live, so it is a plumbing check, not a result")
        out_rows.append({"case": case, **r})
    if not out_rows:
        raise SystemExit(f"run {run_id}: no outside-judge results among its annotations")
    return {"format": FORMAT + "-bench", "run": run_id, "runUrl": run.get("html_url"),
            "commit": run.get("head_sha"), "date": run.get("created_at"), "rows": out_rows,
            "scores": scores(out_rows), "estimatedUsd": round(sum(r.get("usd") or 0 for r in out_rows), 2)}


def scores(rows: list[dict]) -> dict:
    """Per judge and per pass: good accepted, bad accepted, undecided. Muse is one pass."""
    good = [r for r in rows if r["label"] == "good"]
    bad = [r for r in rows if r["label"] == "bad"]

    def count(get) -> dict:
        return {"goodAccepted": sum(get(r) == "accept" for r in good), "good": len(good),
                "badAccepted": sum(get(r) == "accept" for r in bad), "bad": len(bad),
                "undecided": sum(get(r) is None for r in rows)}

    out = {"museScreenshots": {"passes": [count(lambda r: r.get("museScreenshots"))]}}
    names = sorted({n for r in rows for n in r["judges"]})
    for n in names:
        k = max(len(r["judges"].get(n, {}).get("decisions") or []) for r in rows)
        models = sorted({r["judges"][n]["model"] for r in rows if n in r["judges"]})
        out[n] = {"models": models, "passes": [
            count(lambda r, i=i: ((r["judges"].get(n) or {}).get("decisions") or [None] * k)[i]) for i in range(k)]}
    return out


def markdown(doc: dict) -> str:
    def cell(p: dict, key: str) -> str:
        return f"{p[key + 'Accepted']} of {p[key]}"

    names = {"museScreenshots": "Muse Code"}
    for n, j in JUDGES.items():
        names[n] = j["label"]
    lines = ["# Outside models as screenshot judges", "",
             "Written by `python3 -m agents.outside_judge --collect` from the run's own annotations; do not edit by hand.",
             f"Run: [{doc['run']}]({doc['runUrl']}) ({(doc.get('date') or '')[:10]}, commit {(doc.get('commit') or '')[:7]}). "
             "One run; the models, prompt, passes and scoring were fixed before it.", "",
             "| Judge, from screenshots | Model | Pass | Good fixes accepted | Bad fixes accepted | Undecided |",
             "| --- | --- | --- | --- | --- | --- |"]
    for key, s in doc["scores"].items():
        model = "Muse Code" if key == "museScreenshots" else ", ".join(s.get("models") or [])
        for i, p in enumerate(s["passes"], 1):
            lines.append(f"| {names.get(key, key)} | {model} | {i} | {cell(p, 'good')} | {cell(p, 'bad')} | {p['undecided']} |")
    lines += ["", f"Estimated spend on the outside models: ${doc['estimatedUsd']:.2f} at list prices.", "",
              "| Case | Right answer | Muse Code | " + " | ".join(names.get(n, n) for n in doc["scores"] if n != "museScreenshots") + " |",
              "| --- | --- | --- | " + " | ".join("---" for n in doc["scores"] if n != "museScreenshots") + " |"]
    for r in doc["rows"]:
        right = "accept" if r["label"] == "good" else "reject"
        outs = [", ".join(str(d) for d in (r["judges"].get(n) or {}).get("decisions") or ["-"])
                for n in doc["scores"] if n != "museScreenshots"]
        lines.append(f"| {r['case']} | {right} | {r.get('museScreenshots')} | " + " | ".join(outs) + " |")
    lines += ["", "## Their words", "", "Each model's text just before its decision line, per pass.", ""]
    for r in doc["rows"]:
        for n, words in (r.get("reasons") or {}).items():
            lines.append(f"- **{r['case']}**, {names.get(n, n)}: {words}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    from agents.keys import load_dotenv

    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--smoke", action="store_true")
    g.add_argument("--collect", action="store_true")
    p.add_argument("--run", type=int)
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)
    if args.smoke:
        return smoke()
    if not (args.run and args.out):
        p.error("--collect needs --run and --out")
    doc = collect(args.run)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "outside.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    (args.out / "README.md").write_text(markdown(doc), encoding="utf-8")
    print(f"wrote {args.out}/outside.json and {args.out}/README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
