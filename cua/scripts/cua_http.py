"""Minimal HTTPS client for the CUA Skill Gateway.

Stdlib only (urllib). Parses the gateway's unified `{ ok, data | error }`
envelope and converts errors into SkillError with the gateway error code.
"""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cua_util import SkillError

DEFAULT_TIMEOUT_SEC = 120


def request(method, base_url, path, token=None, body=None, query=None, timeout=DEFAULT_TIMEOUT_SEC):
    """Perform an HTTP request and return (status_code, parsed_json)."""
    url = base_url.rstrip("/") + path
    if query:
        url += "?" + urlencode(query)
    headers = {"accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["content-type"] = "application/json"
    if token:
        headers["authorization"] = "Bearer " + token
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            return resp.status, _read_json(resp)
    except HTTPError as exc:
        return exc.code, _read_json(exc)
    except URLError as exc:
        raise SkillError("NETWORK", f"Cannot reach CUA gateway at {base_url}: {exc.reason}")
    except TimeoutError:
        raise SkillError("NETWORK", f"Request to {url} timed out")


def gateway_call(method, base_url, path, token=None, body=None, query=None, timeout=DEFAULT_TIMEOUT_SEC):
    """Call the gateway and return the `data` payload, raising SkillError on error."""
    status, payload = request(method, base_url, path, token=token, body=body, query=query, timeout=timeout)
    if isinstance(payload, dict) and payload.get("ok") is True:
        return payload.get("data", {})
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        extra = {k: v for k, v in error.items() if k not in ("code", "message")}
        raise SkillError(error.get("code", "INTERNAL"), error.get("message", "request failed"), **extra)
    raise SkillError("INTERNAL", f"Unexpected gateway response (HTTP {status})")


def _read_json(response):
    try:
        raw = response.read().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "error": {"code": "INTERNAL", "message": raw[:500]}}
