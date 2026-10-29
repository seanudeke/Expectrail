"""Check the Glimmer deployment on Fireworks before a run, and put its scaling back after a suspension.

When the Fireworks account runs out of credits it is suspended, and the on-demand deployment comes
back with its replicas set to 0-0 and its scale-to-zero window reset to an hour (Oct 29, twice).
At 0-0 every request is a 404, the dashboard's Re-enable is greyed out, and the only way back is
Edit Deployment. This does that edit through Fireworks' control-plane API instead:

    python -m agents.fireworks_deployment --restore

It reads the deployment (GET /v1/accounts/<account>/deployments/<id>), and if its maximum replica
count is below 1 or its scale-to-zero window is longer than SCALE_TO_ZERO, it updates those three
fields (min 0, max 1, window 15 minutes) and reads the deployment back to confirm. Nothing else is
changed, and only a model id of the form accounts/<account>/deployments/<id> on api.fireworks.ai is
touched. A suspended account (HTTP 412) is reported as such: add credits, then run again.

The settings it restores are the ones Sean approved on Oct 29: min 0, max 1 (one H200, $8 an hour
while up), scale to zero after 15 idle minutes.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

CONTROL_BASE = "https://api.fireworks.ai/v1"
MIN_REPLICAS, MAX_REPLICAS = 0, 1
SCALE_TO_ZERO = "900s"  # 15 minutes
SCALE_TO_ZERO_S = 900.0
MASK_PATHS = (
    ("min_replica_count", "max_replica_count", "autoscaling_policy.scale_to_zero_window"),
    ("minReplicaCount", "maxReplicaCount", "autoscalingPolicy.scaleToZeroWindow"),
)
DEPLOYMENT_RE = re.compile(r"^accounts/([A-Za-z0-9_-]+)/deployments/([A-Za-z0-9_-]+)$")
BILLING = "https://app.fireworks.ai/account/billing"
MANUAL = ("Edit Deployment on the Fireworks dashboard: Deployment Scaling, Max Replicas 1, Min 0, "
          "Advanced Options, Scale to Zero Window 15 min, Save")


class DeploymentError(RuntimeError):
    pass


def parse_deployment(model: str) -> tuple[str, str] | None:
    m = DEPLOYMENT_RE.match((model or "").strip())
    return (m.group(1), m.group(2)) if m else None


def seconds(duration) -> float | None:
    """A protobuf/Go duration ("900s", "1h", "15m0s", "3600.000s") in seconds, or None."""
    if duration is None:
        return None
    text = str(duration).strip()
    parts = re.findall(r"(\d+(?:\.\d+)?)(h|m|s)", text)
    if not parts or "".join(n + u for n, u in parts) != text:
        return None
    return sum(float(n) * {"h": 3600, "m": 60, "s": 1}[u] for n, u in parts)


def problems(dep: dict) -> list[str]:
    out = []
    if int(dep.get("maxReplicaCount") or 0) < 1:
        out.append(f"max replicas {dep.get('maxReplicaCount', 0)} (nothing can serve; a suspension sets this)")
    window = seconds((dep.get("autoscalingPolicy") or {}).get("scaleToZeroWindow"))
    if window is None or window > SCALE_TO_ZERO_S:
        out.append(f"scale-to-zero window {(dep.get('autoscalingPolicy') or {}).get('scaleToZeroWindow', 'default 1h')} "
                   "(each run would keep the GPU up that long after it ends)")
    return out


def _call(method: str, url: str, key: str, body: dict | None, opener=None) -> dict:
    opener = opener or urllib.request.urlopen
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with opener(req, timeout=60) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as err:
        try:
            detail = " ".join(err.read().decode(errors="replace").split())[:300]
        except OSError:
            detail = ""
        if err.code == 412:
            raise DeploymentError(f"the Fireworks account is suspended (HTTP 412, out of credits or past its spend "
                                  f"limit): add credits at {BILLING}, then run again; this step restores the "
                                  f"deployment's scaling itself once the account is back") from err
        raise DeploymentError(f"{method} {urllib.parse.urlparse(url).path}: HTTP {err.code}: {detail}") from err
    except OSError as err:
        raise DeploymentError(f"{method} {urllib.parse.urlparse(url).path}: {type(err).__name__}: {err}") from err
    try:
        return json.loads(raw or b"{}")
    except ValueError as exc:
        raise DeploymentError(f"{method} {urllib.parse.urlparse(url).path}: not JSON") from exc


def get(account: str, deployment: str, key: str, opener=None) -> dict:
    return _call("GET", f"{CONTROL_BASE}/accounts/{account}/deployments/{deployment}", key, None, opener)


def restore(account: str, deployment: str, key: str, dep: dict, opener=None) -> dict:
    """Set min 0, max 1, scale to zero after 15 minutes; return the deployment as read back.

    The body is the deployment as read, with only those three values changed, and the update mask
    names only those fields, so nothing else can change whether or not the server applies the mask.
    The read-back must show the new values and the same base model and shape, or this raises.
    """
    body = copy.deepcopy(dep)
    body["minReplicaCount"], body["maxReplicaCount"] = MIN_REPLICAS, MAX_REPLICAS
    body["autoscalingPolicy"] = dict(body.get("autoscalingPolicy") or {}, scaleToZeroWindow=SCALE_TO_ZERO)
    url = f"{CONTROL_BASE}/accounts/{account}/deployments/{deployment}"
    minimal = {"minReplicaCount": MIN_REPLICAS, "maxReplicaCount": MAX_REPLICAS,
               "autoscalingPolicy": {"scaleToZeroWindow": SCALE_TO_ZERO}}
    errors = []
    # The whole deployment first (unchanged apart from the three values); only if the server refuses
    # that (e.g. for read-only fields in the body), the three values alone, always with the mask.
    for payload, paths in [(body, m) for m in MASK_PATHS] + [(minimal, m) for m in MASK_PATHS]:
        try:
            _call("PATCH", f"{url}?updateMask={','.join(paths)}", key, payload, opener)
            break
        except DeploymentError as exc:
            if "HTTP 412" in str(exc) or "suspended" in str(exc):
                raise
            errors.append(str(exc))
    else:
        raise DeploymentError("could not update the deployment's scaling (" + "; ".join(errors) + f"). {MANUAL}")
    after = get(account, deployment, key, opener)
    for field in ("baseModel", "deploymentShape", "acceleratorType"):
        if dep.get(field) != after.get(field):
            raise DeploymentError(f"after the update the deployment's {field} reads {after.get(field)!r}, was "
                                  f"{dep.get(field)!r}: check it on the dashboard before running anything")
    left = problems(after)
    if left:
        raise DeploymentError("the update was accepted but the deployment still reads " + "; ".join(left) + f". {MANUAL}")
    return after


def main(argv: list[str] | None = None) -> int:
    import os

    from agents.glimmer_client import KEY_ENVS, MODEL, api_key
    from agents.keys import load_dotenv

    p = argparse.ArgumentParser(description="Check the Glimmer deployment on Fireworks; --restore fixes its scaling.")
    p.add_argument("--restore", action="store_true", help="put min 0 / max 1 / 15-minute scale-to-zero back if needed")
    p.add_argument("--model", default=None, help="accounts/<account>/deployments/<id> (default NIGHTSHIFT_GLIMMER_MODEL)")
    args = p.parse_args(argv)
    load_dotenv()
    model = args.model or os.environ.get("NIGHTSHIFT_GLIMMER_MODEL") or MODEL
    target = parse_deployment(model)
    if target is None:
        print(f"{model} is not a Fireworks deployment id (accounts/<account>/deployments/<id>); nothing to check")
        return 0
    key = api_key()
    if not key:
        print(f"::error title=Glimmer deployment::set one of {', '.join(KEY_ENVS)}")
        return 1
    account, deployment = target
    try:
        dep = get(account, deployment, key)
        found = problems(dep)
        if not found:
            print(f"::notice title=Glimmer deployment::{model} state {dep.get('state')}, replicas "
                  f"{dep.get('minReplicaCount', 0)}-{dep.get('maxReplicaCount')}, scale to zero after "
                  f"{(dep.get('autoscalingPolicy') or {}).get('scaleToZeroWindow')}")
            return 0
        if not args.restore:
            print(f"::error title=Glimmer deployment::{model}: " + "; ".join(found) + f". Run with --restore, or {MANUAL}")
            return 1
        after = restore(account, deployment, key, dep)
        print(f"::notice title=Glimmer deployment restored::{model} had " + "; ".join(found) + ". Now replicas "
              f"{after.get('minReplicaCount', 0)}-{after.get('maxReplicaCount')}, scale to zero after "
              f"{(after.get('autoscalingPolicy') or {}).get('scaleToZeroWindow')}")
        return 0
    except DeploymentError as exc:
        print(f"::error title=Glimmer deployment::{' '.join(str(exc).split()).replace('::', ': :')[:600]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
