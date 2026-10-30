"""mitmproxy addon: the Muse Code key gateway (experiment; see agents/muse_gateway.py).

Muse Code is given a placeholder key and this proxy as HTTPS_PROXY. For hosts on the allowlist
(Meta's API, ``*.meta.ai`` by default) the proxy replaces the placeholder, wherever it appears in a
request header, with the real key, which only this process holds. Every other host is refused, so
the agent can reach nothing else through it. Header values are never logged: each flow is recorded
as host, method, path, status and the names of the headers that carried the placeholder.

Loaded by mitmdump (``mitmdump -s agents/muse_gateway_addon.py``) in mitmproxy's own environment,
so it imports only the standard library and mitmproxy, and mitmproxy only inside the hooks.
"""
from __future__ import annotations

import json
import os
import time

PLACEHOLDER = os.environ.get("MUSE_GATEWAY_PLACEHOLDER", "")
REAL_KEY = os.environ.get("MUSE_GATEWAY_KEY", "")
ALLOW = tuple(s.strip().lower() for s in os.environ.get("MUSE_GATEWAY_HOSTS", ".meta.ai").split(",") if s.strip())
LOG = os.environ.get("MUSE_GATEWAY_LOG", "gateway-log.jsonl")


def host_allowed(host: str, allow: tuple[str, ...] = ALLOW) -> bool:
    """``.meta.ai`` allows meta.ai and every subdomain; ``api.example.com`` allows that host only."""
    host = (host or "").lower().rstrip(".")
    for rule in allow:
        if rule.startswith("."):
            if host == rule[1:] or host.endswith(rule):
                return True
        elif host == rule:
            return True
    return False


def swap(headers: list[tuple[str, str]], placeholder: str, real: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Headers with every occurrence of the placeholder replaced by the real key; and which names had it."""
    if not placeholder or not real:
        return list(headers), []
    out, names = [], []
    for name, value in headers:
        if placeholder in value:
            value = value.replace(placeholder, real)
            if name.lower() not in names:
                names.append(name.lower())
        out.append((name, value))
    return out, names


def _record(entry: dict) -> None:
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


class Gateway:
    def request(self, flow) -> None:
        from mitmproxy import http

        host = flow.request.pretty_host
        entry = {"t": round(time.time(), 3), "host": host, "method": flow.request.method,
                 "path": flow.request.path.split("?", 1)[0][:200]}
        if not host_allowed(host):
            flow.response = http.Response.make(403, b"blocked by the Muse key gateway: host not allowed",
                                               {"content-type": "text/plain"})
            entry.update(status=403, blocked=True)
            _record(entry)
            return
        keys = list(dict.fromkeys(k.lower() for k in flow.request.headers))  # get_all ignores case
        pairs = [(k, v) for k in keys for v in flow.request.headers.get_all(k)]
        new, names = swap(pairs, PLACEHOLDER, REAL_KEY)
        if names:
            for name in names:
                flow.request.headers.set_all(name, [v for k, v in new if k.lower() == name])
        entry["swapped"] = names
        entry["placeholderInBody"] = bool(PLACEHOLDER) and PLACEHOLDER.encode() in (flow.request.raw_content or b"")
        flow.metadata["gateway"] = entry

    def responseheaders(self, flow) -> None:
        flow.response.stream = True  # server-sent events reach Muse as they arrive

    def response(self, flow) -> None:
        entry = flow.metadata.get("gateway")
        if entry is not None:
            entry["status"] = flow.response.status_code
            _record(entry)

    def error(self, flow) -> None:
        entry = flow.metadata.get("gateway") or {"host": flow.request.pretty_host if flow.request else None}
        entry["error"] = str(flow.error)[:200] if flow.error else "unknown"
        _record(entry)


addons = [Gateway()]
