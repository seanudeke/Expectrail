"""Muse Spark between episodes: propose more probes and more contracts, in the closed languages only.

One call per job (the specification's competition slice: one hypothesis call per episode batch). Spark
sees the mechanics profile, the action catalog, the probes already run, and the signal summaries of the
base snapshots: numbers such as the highest rise above the floor, bullets fired, sprite turns. It never
sees a bug report, a patch, a diff, the reported bugs' routes, or the reference snapshot's results.

Its answer is data, never code. Each probe must compile (expectrail/discovery/route_compiler.py) and
each contract must validate as an expectrail.trace-spec/v1 with one of the interpreter's operations;
anything else is dropped and recorded. Whatever it says, a model contract carries ``model_prior``
authority: a claim does not become approved by being repeated by a model.
"""
from __future__ import annotations

import json
import re

from expectrail.contracts import ContractError, validate_v1
from expectrail.discovery.route_compiler import ProgramError, compile_route

MODEL = "muse-spark-1.3"
ID_RE = re.compile(r"[^a-z0-9-]+")

SYSTEM = """You are the planner of a game-testing system. You propose experiments and checks for a 2D \
platformer from its mechanics profile and from measurements of probes that were already run. You do not \
know of any particular bug. Answer with one JSON object and nothing else:

{"probes": [{"id": "...", "description": "...", "program": PROGRAM}],
 "candidates": [{"id": "...", "statement": "...", "claimId": "...", "class": "player|enemy|projectile",
                 "operation": OPERATION, "appliesTo": "all" | ["probe-id", ...]}]}

PROGRAM is a bounded action program, one of:
  {"op": "tap", "action": A, "durationTicks": n}   {"op": "hold", "action": A, "durationTicks": n}
  {"op": "wait", "durationTicks": n}   {"op": "sequence", "steps": [PROGRAM, ...]}
  {"op": "parallel", "branches": [PROGRAM, PROGRAM]}   {"op": "repeat", "count": n, "body": PROGRAM}
A is one of the actions in the profile. Ticks are physics ticks, 120 a second. At most three levels of \
nesting, at most 1,700 ticks, and an action is pressed and released before it is pressed again.

OPERATION is one of:
  {"type": "max_episode_rise", "maxPx": x}       highest rise above the floor last stood on
  {"type": "min_event_interval", "event": "projectile_spawn", "seconds": s}
  {"type": "direction_agreement", "subject": "actor"|"projectile", "maxMismatchCount": n,
   "minSpeedPxPerSec": v, "graceTicks": n, "minTravelPx": d, "horizonTicks": n}
  {"type": "max_entity_drop", "settleTicks": n, "maxDropPx": x}
  {"type": "event_response", "trigger": {"action": A, "pressed": true}, "response": "projectile_spawn",
   "withinSeconds": s, "refractorySeconds": s}
  {"type": "min_event_count", "event": "projectile_spawn", "min": n}
  {"type": "min_motion_extent", "minPx": x}
  {"type": "entity_present"}
  {"type": "relation", "signal": SIGNAL, "comparator": "lte"|"gte"|"lt"|"gt"|"eq", "toleranceAbs": t,
   "left": "probe-id", "right": "probe-id"}     signal(right) compared with signal(left)
SIGNAL is one of the names in the measurements you are given.

Rules: propose at most 4 probes and 8 candidates. Each candidate states, in one plain sentence, a rule \
the profile's claims imply, and cites the claimId it comes from. Prefer relations between two probes \
that differ in one thing, because they need no threshold. Prefer probes that exercise mechanics the \
existing probes did not, or that would show a measurement looks wrong."""


def _slug(text: str) -> str:
    return ID_RE.sub("-", str(text).lower()).strip("-")[:48] or "x"


def prompt(profile: dict, probes: list[dict], summaries: dict) -> str:
    claims = [{"claimId": c["claimId"], "statement": c["statement"],
               "parameters": {k: f"{v['value']} {v['unit']}" for k, v in c["parameters"].items()},
               "exceptions": c["exceptions"]} for c in profile["claims"]]
    return json.dumps({
        "game": profile["game"]["description"],
        "actions": profile["actions"],
        "claims": claims,
        "probesAlreadyRun": [{"id": p["id"], "description": p["description"]} for p in probes],
        "measurements": summaries,
    }, indent=1)


def parse(answer: dict, profile: dict, existing_probe_ids: set[str]) -> tuple[list[dict], list[dict], list[str]]:
    """(probes, contract entries, diagnostics) from the model's JSON, keeping only what validates."""
    notes: list[str] = []
    claims = {c["claimId"] for c in profile["claims"]}
    probes = []
    for raw in (answer.get("probes") or [])[:4]:
        if not isinstance(raw, dict):
            notes.append("MODEL_OUTPUT_INVALID: a probe that is not an object")
            continue
        pid = "plan-" + _slug(raw.get("id", ""))
        try:
            compile_route(raw.get("program"), name=pid, description=str(raw.get("description", ""))[:200],
                          actions=profile["actions"])
        except (ProgramError, ContractError, TypeError) as exc:
            notes.append(f"MODEL_OUTPUT_INVALID: probe {pid}: {exc}"[:200])
            continue
        probes.append({"id": pid, "family": "planner", "description": str(raw.get("description", ""))[:200],
                       "program": raw["program"], "tags": []})
    known = existing_probe_ids | {p["id"] for p in probes}
    entries = []
    for raw in (answer.get("candidates") or [])[:8]:
        if not isinstance(raw, dict):
            notes.append("MODEL_OUTPUT_INVALID: a candidate that is not an object")
            continue
        sid = "model-" + _slug(raw.get("id", ""))
        op = raw.get("operation") if isinstance(raw.get("operation"), dict) else {}
        for key in ("left", "right"):
            if op.get("type") == "relation" and key in op:
                op = dict(op, **{key: op[key] if op[key] in known else "plan-" + _slug(op[key])})
        claim = raw.get("claimId") if raw.get("claimId") in claims else "model.unbound"
        spec = {"format": "expectrail.trace-spec/v1", "id": sid, "origin": "AUTO_TRACE" if op.get("type") != "relation"
                else "AUTO_RELATION", "statement": str(raw.get("statement", ""))[:300] or sid,
                "expectationRef": {"claimId": claim, "authority": "model_prior"},
                "scope": {"class": raw.get("class")}, "window": {"kind": "episode"}, "operation": op,
                "evidenceRequirement": {"minimumTriggers": 1, "minimumEvaluations": 1, "completeWindow": True},
                "guards": []}
        try:
            validate_v1(spec, "trace-spec")
        except ContractError as exc:
            notes.append(f"MODEL_OUTPUT_INVALID: candidate {sid}: {exc}"[:200])
            continue
        if op["type"] == "relation":
            if op["left"] not in known or op["right"] not in known:
                notes.append(f"MODEL_OUTPUT_INVALID: candidate {sid} names a probe that does not exist")
                continue
            applies = {"kind": "pair", "left": op["left"], "right": op["right"]}
        else:
            target = raw.get("appliesTo", "all")
            if target == "all":
                applies = {"kind": "all"}
            elif isinstance(target, list) and target and all(t in known for t in target):
                applies = {"kind": "probes", "ids": list(target)}
            else:
                notes.append(f"MODEL_OUTPUT_INVALID: candidate {sid} applies to unknown probes")
                continue
        entries.append({"templateId": "model", "spec": spec, "approved": False, "applies": applies, "source": "model"})
    return probes, entries, notes


def spark_planner(transport=None, model: str = MODEL):
    """A planner callable for discover(): one Muse Spark call on the Meta Model API."""
    if transport is None:
        from expectrail.spec_writer import http_transport as transport

    def plan(profile: dict, probes: list[dict], summaries: dict, limits: dict) -> dict:
        # No max_tokens: Muse Spark reasons before it answers, and its reasoning counts against the
        # limit. With max_tokens 4096 every live call came back with no content at all (October 31,
        # run 41251362155). The spec writer sends no limit either.
        body = {"model": model, "temperature": 0, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": prompt(profile, probes, summaries)}]}
        response = transport(body)
        try:
            choice = response["choices"][0]
            content = choice["message"].get("content")
            if isinstance(content, list):
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
            if not isinstance(content, str) or not content.strip():
                raise ValueError(f"no content (finish_reason {choice.get('finish_reason')!r})")
            answer = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip()))
            if not isinstance(answer, dict):
                raise ValueError("the answer is not a JSON object")
        except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
            raise ValueError(f"MODEL_OUTPUT_INVALID: the planner did not return JSON ({exc})") from exc
        probes_out, entries, notes = parse(answer, profile, {p["id"] for p in probes})
        usage = response.get("usage") or {}
        return {"probes": probes_out, "candidates": entries, "diagnostics": notes,
                "usage": {"model": model, "promptTokens": usage.get("prompt_tokens"),
                          "completionTokens": usage.get("completion_tokens")}}

    return plan
