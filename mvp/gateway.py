#!/usr/bin/env python3
"""Thin Anthropic Messages client over the Roche AI Gateway. Stdlib only.

Everything model-specific lives behind this one module -- the design doc commits
to being able to swap the model without touching the system, so the rest of the
code never sees a provider detail.

Auth: `build-cli auth token` (SSO, short-lived) sent as a Bearer token. The
token is fetched lazily, cached for a few minutes, and never logged.
"""
import base64
import json
import mimetypes
import os
import pathlib
import subprocess
import time
import urllib.error
import urllib.request

BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://eu.build-cli.roche.com/proxy")
BUILD_CLI = os.environ.get("BUILD_CLI_BIN",
                           str(pathlib.Path.home() / ".local/bin/build-cli"))

# Model tiers. The cheap tier does the high-volume passes; the strong tier is
# reserved for the escalation path (pixel re-read) and for verification.
FAST = os.environ.get("DI_MODEL_FAST", "claude-haiku-4-5-20251001")
MAIN = os.environ.get("DI_MODEL_MAIN", "claude-sonnet-5[1m]")
STRONG = os.environ.get("DI_MODEL_STRONG", "claude-opus-5[1m]")

_TOKEN = {"value": None, "at": 0.0}
_TOKEN_TTL = 240.0

USER_AGENT = os.environ.get("DI_USER_AGENT", "curl/8.7.1")

# Rough per-million-token prices (USD) purely so the demo can show a cost dial.
_PRICES = {FAST: (1.0, 5.0), MAIN: (3.0, 15.0), STRONG: (15.0, 75.0)}

USAGE = {"calls": 0, "in": 0, "out": 0, "usd": 0.0, "by_model": {}}


class GatewayError(RuntimeError):
    pass


def _token():
    now = time.time()
    if _TOKEN["value"] and now - _TOKEN["at"] < _TOKEN_TTL:
        return _TOKEN["value"]
    try:
        out = subprocess.run([BUILD_CLI, "auth", "token"], capture_output=True,
                             text=True, timeout=90, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise GatewayError(
            "could not obtain a gateway token via `build-cli auth token`. "
            "Run `build-cli login` and retry.") from exc
    if not out:
        raise GatewayError("`build-cli auth token` returned nothing -- run `build-cli login`.")
    _TOKEN.update(value=out, at=now)
    return out


def _account(model, usage):
    i, o = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    pin, pout = _PRICES.get(model, (3.0, 15.0))
    usd = i / 1e6 * pin + o / 1e6 * pout
    USAGE["calls"] += 1
    USAGE["in"] += i
    USAGE["out"] += o
    USAGE["usd"] += usd
    m = USAGE["by_model"].setdefault(model, {"calls": 0, "in": 0, "out": 0, "usd": 0.0})
    m["calls"] += 1
    m["in"] += i
    m["out"] += o
    m["usd"] += usd
    return usd


def image_block(path):
    """A base64 image content block for a local file."""
    p = pathlib.Path(path)
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    return {"type": "image",
            "source": {"type": "base64", "media_type": mime,
                       "data": base64.b64encode(p.read_bytes()).decode("ascii")}}


def complete(content, model=None, system=None, max_tokens=4096, temperature=None,
             tools=None, tool_choice=None, retries=3):
    """Call the Messages API. `content` is a string or a list of content blocks.

    `temperature` is left unset by default: the gateway routes some models via
    Vertex, which rejects the parameter outright.
    """
    model = model or MAIN
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    body = {"model": model, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}]}
    if temperature is not None:
        body["temperature"] = temperature
    if system:
        body["system"] = system
    if tools:
        body["tools"] = tools
    if tool_choice:
        body["tool_choice"] = tool_choice

    payload = json.dumps(body).encode("utf-8")
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(
            BASE_URL.rstrip("/") + "/v1/messages", data=payload, method="POST",
            headers={"Authorization": "Bearer " + _token(),
                     "anthropic-version": "2023-06-01",
                     "x-build-cli-tool": "claude",
                     "content-type": "application/json",
                     # The gateway sits behind Cloudflare, which rejects
                     # Python-urllib's default agent with a 403/1010.
                     "user-agent": USER_AGENT,
                     "accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.loads(r.read().decode("utf-8"))
            _account(model, data.get("usage", {}))
            return data
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            last = GatewayError("gateway %s: %s" % (exc.code, detail))
            if exc.code in (401, 403):
                _TOKEN.update(value=None, at=0.0)   # force a refresh once
            if exc.code not in (401, 408, 429, 500, 502, 503, 504, 529):
                raise last
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = GatewayError("gateway unreachable: %s" % exc)
        if attempt < retries - 1:
            time.sleep(1.6 * (attempt + 1))
    raise last


def text_of(resp):
    return "".join(b.get("text", "") for b in resp.get("content", [])
                   if b.get("type") == "text").strip()


def json_of(resp, tool_name=None):
    """Extract a JSON object: prefer a tool_use block, else parse fenced text."""
    for b in resp.get("content", []):
        if b.get("type") == "tool_use" and (tool_name is None or b.get("name") == tool_name):
            return b.get("input", {})
    raw = text_of(resp)
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()
    start = min((i for i in (raw.find("{"), raw.find("[")) if i != -1), default=-1)
    if start > 0:
        raw = raw[start:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GatewayError("model did not return JSON: %s" % raw[:300]) from exc


def structured(content, schema, name, description, model=None, system=None,
               max_tokens=4096):
    """Force a schema-valid object out of the model via a single-tool call."""
    resp = complete(content, model=model, system=system, max_tokens=max_tokens,
                    tools=[{"name": name, "description": description,
                            "input_schema": schema}],
                    tool_choice={"type": "tool", "name": name})
    return json_of(resp, tool_name=name)


def usage_report():
    return json.loads(json.dumps(USAGE))


if __name__ == "__main__":
    print(text_of(complete("Reply with exactly: gateway ok", model=FAST, max_tokens=16)))
    print(json.dumps(usage_report(), indent=2))
