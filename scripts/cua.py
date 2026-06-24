#!/usr/bin/env python3
"""CUA Skill CLI — the single entrypoint an agent calls to drive CUA.

    python3 <skill_dir>/scripts/cua.py <command> [options]

Every invocation prints exactly one JSON object:

    {"ok": true,  "action": "<command>", "data": {...}, "next": {...}}
    {"ok": false, "action": "<command>", "error": {"code": "...", "message": "..."}}

Stdlib only. Tokens, the user's objective, the user's answers, CUA's final text,
and screenshot bytes are never printed. See references/ for full command and
error documentation.
"""

import argparse
import base64
import json
import os
import sys
import tempfile
from pathlib import Path

import cua_auth
from cua_state import AuthState, SessionState
from cua_util import SkillError, emit_error, emit_success, login_retry_command, now_epoch, script_path

TERMINAL_OUTCOMES = ("completed", "failed", "cancelled")
RESULT_POLL_WAIT_MS = 60000


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    action = getattr(args, "action", None)
    if not action:
        parser.print_help(sys.stderr)
        return 2
    try:
        state = AuthState.load()
        session = SessionState.load()
        data = args.handler(args, state, session)
        emit_success(action, data)
    except SkillError as exc:
        emit_error(action, exc)
    except BrokenPipeError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface unexpected errors as JSON, not tracebacks
        emit_error(action, SkillError("INTERNAL", str(exc)))


# -- base URL --------------------------------------------------------------


def resolve_base_url(args, state, persist=False):
    base_url = (
        args.api_base_url
        or os.environ.get("CUA_SKILL_API_BASE_URL")
        or state.api_base_url
        or bundled_base_url()
    )
    if not base_url:
        raise SkillError(
            "VALIDATION_ERROR",
            "No CUA gateway configured. Set api_base_url in the skill's config.json, "
            "pass --api-base-url, or set CUA_SKILL_API_BASE_URL.",
        )
    base_url = base_url.rstrip("/")
    if persist and state.api_base_url != base_url:
        state.set_api_base_url(base_url)
    return base_url


def bundled_base_url():
    """Gateway URL shipped with the skill in config.json (publisher-set, once)."""
    try:
        cfg_path = Path(__file__).resolve().parent.parent / "config.json"
        if not cfg_path.exists():
            return None
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    url = data.get("api_base_url") if isinstance(data, dict) else None
    if not isinstance(url, str):
        return None
    url = url.strip()
    if not url or url.startswith("<") or "REPLACE" in url or "example.com" in url:
        return None
    return url


# -- auth commands ---------------------------------------------------------


def cmd_auth_status(args, state, session):
    base_url = resolve_base_url(args, state)
    return {"data": cua_auth.auth_status(state, base_url)}


def cmd_auth_login(args, state, session):
    base_url = resolve_base_url(args, state, persist=True)
    return {"data": cua_auth.login(
        state, base_url,
        open_browser=not args.no_browser,
        timeout=args.timeout,
        session_id=args.session_id,
    )}


def cmd_auth_logout(args, state, session):
    base_url = resolve_base_url(args, state)
    return {"data": cua_auth.logout(state, base_url)}


# -- CUA commands ----------------------------------------------------------


def cmd_ping(args, state, session):
    base_url = resolve_base_url(args, state)
    return {"data": cua_auth.authorized_call(state, base_url, "GET", "/v1/ping")}


def cmd_delegate(args, state, session):
    base_url = resolve_base_url(args, state)
    body = {"objective": args.objective, "wait_ms": args.wait_ms}
    envelope = cua_auth.authorized_call(
        state, base_url, "POST", "/v1/invocations", body=body, timeout=_call_timeout(args.wait_ms)
    )
    return _envelope_result("delegate", envelope, session)


def cmd_watch(args, state, session):
    base_url = resolve_base_url(args, state)
    invocation_id = _resolve_invocation_id(args, session)
    body = {"wait_ms": args.wait_ms}
    envelope = cua_auth.authorized_call(
        state, base_url, "POST", f"/v1/invocations/{invocation_id}/watch",
        body=body, timeout=_call_timeout(args.wait_ms)
    )
    return _envelope_result("watch", envelope, session)


def cmd_answer(args, state, session):
    base_url = resolve_base_url(args, state)
    invocation_id = _resolve_invocation_id(args, session)
    body = {"answer": args.answer, "wait_ms": args.wait_ms}
    envelope = cua_auth.authorized_call(
        state, base_url, "POST", f"/v1/invocations/{invocation_id}/answer",
        body=body, timeout=_call_timeout(args.wait_ms)
    )
    return _envelope_result("answer", envelope, session)


def cmd_cancel(args, state, session):
    base_url = resolve_base_url(args, state)
    invocation_id = _resolve_invocation_id(args, session)
    data = cua_auth.authorized_call(state, base_url, "POST", f"/v1/invocations/{invocation_id}/cancel")
    return {"data": data}


def cmd_result(args, state, session):
    base_url = resolve_base_url(args, state)
    invocation_id = _resolve_invocation_id(args, session)
    deadline = now_epoch() + max(1, args.timeout)
    envelope = cua_auth.authorized_call(state, base_url, "GET", f"/v1/invocations/{invocation_id}")
    while envelope.get("outcome") == "in_progress" and now_epoch() < deadline:
        envelope = cua_auth.authorized_call(
            state, base_url, "POST", f"/v1/invocations/{invocation_id}/watch",
            body={"wait_ms": RESULT_POLL_WAIT_MS}, timeout=_call_timeout(RESULT_POLL_WAIT_MS)
        )
    return _envelope_result("result", envelope, session)


def cmd_observe(args, state, session):
    base_url = resolve_base_url(args, state)
    invocation_id = args.invocation_id or (session.last_invocation_id if args.last else None)
    leaf = "screenshot" if args.include_screenshot else "access"
    if invocation_id:
        path = f"/v1/invocations/{invocation_id}/desktop/{leaf}"
    else:
        path = f"/v1/desktop/{leaf}"
    data = cua_auth.authorized_call(state, base_url, "GET", path, timeout=120)

    if args.include_screenshot:
        screenshot = data.get("screenshot") or {}
        b64 = screenshot.pop("base64", None)
        if b64:
            screenshot_file = _save_screenshot(b64, screenshot.get("mime_type"))
            data["screenshot_file"] = screenshot_file
            data["screenshot"] = screenshot
    return {"data": data, "next": {
        "agent_hint": "access_url is a temporary cloud-desktop link; if it expires, run observe again. "
                      "Do not use observe to decide whether the task is done — use watch.",
    }}


def cmd_self_test(args, state, session):
    """Local-only checks. Does not create CUA tasks or call backends."""
    checks = {
        "python_version": sys.version.split()[0],
        "python_ok": sys.version_info >= (3, 8),
        "auth_file": str(state.path),
        "logged_in": bool(state.access_token),
        "api_base_url": resolve_base_url(args, state) if _has_base_url(args, state) else None,
        "last_invocation_id": session.last_invocation_id,
    }
    next_hint = None
    if not checks["logged_in"]:
        next_hint = {"command": login_retry_command(), "agent_hint": "Not logged in yet. Run auth login before real work."}
    return {"data": checks, "next": next_hint} if next_hint else {"data": checks}


# -- helpers ---------------------------------------------------------------


def _has_base_url(args, state):
    return bool(args.api_base_url or os.environ.get("CUA_SKILL_API_BASE_URL")
                or state.api_base_url or bundled_base_url())


def _resolve_invocation_id(args, session):
    if getattr(args, "invocation_id", None):
        return args.invocation_id
    if getattr(args, "last", False) and session.last_invocation_id:
        return session.last_invocation_id
    raise SkillError(
        "VALIDATION_ERROR",
        "invocation_id is required. Pass --invocation-id <id> or --last to reuse the most recent invocation.",
    )


def _call_timeout(wait_ms):
    """HTTP timeout must outlast the server-side wait window.

    When wait_ms is None the server applies its own default wait (up to a minute
    or so), so give a generous floor rather than timing out early.
    """
    if wait_ms is None:
        return 120
    return int(wait_ms / 1000.0) + 30


def _envelope_result(action, envelope, session):
    invocation_id = envelope.get("invocation_id")
    if invocation_id:
        session.set_last_invocation_id(invocation_id)
    return {"data": envelope, "next": _next_for_envelope(envelope)}


def _next_for_envelope(envelope):
    outcome = envelope.get("outcome")
    invocation_id = envelope.get("invocation_id")
    script = script_path()
    next_action = envelope.get("next_action") or {}
    hint = next_action.get("agent_hint", "")
    if outcome == "in_progress":
        return {
            "command": f"python3 {script} watch --invocation-id {invocation_id} --wait-ms 60000",
            "agent_hint": hint or "Keep watching until completed, needs_input, failed, or cancelled. Do not answer the task from progress.",
        }
    if outcome == "needs_input":
        return {
            "command": f'python3 {script} answer --invocation-id {invocation_id} --answer "<USER_ANSWER>"',
            "agent_hint": hint or "Relay input_request.question to the user verbatim, then submit their reply with answer.",
        }
    if outcome == "completed":
        return {"agent_hint": hint or "Use data.result.text as the authoritative final result."}
    if outcome == "failed":
        return {"agent_hint": hint or "CUA could not complete the task. Explain the failure; retry only if the user asks."}
    if outcome == "cancelled":
        return {"agent_hint": hint or "The task was cancelled."}
    return None


def _save_screenshot(b64, mime_type):
    ext = ".jpg"
    if mime_type:
        if "png" in mime_type:
            ext = ".png"
        elif "webp" in mime_type:
            ext = ".webp"
    try:
        raw = base64.b64decode(b64)
    except (ValueError, TypeError) as exc:
        raise SkillError("INTERNAL", f"Screenshot was not valid base64: {exc}")
    fd, path = tempfile.mkstemp(prefix="cua-screenshot-", suffix=ext)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
    return path


# -- argument parser -------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(prog="cua.py", description="CUA Skill CLI")
    parser.add_argument("--api-base-url", help="CUA gateway base URL (overrides env and cache).")
    sub = parser.add_subparsers(dest="command")

    auth = sub.add_parser("auth", help="Authentication commands").add_subparsers(dest="auth_command")

    p = auth.add_parser("status", help="Check the current login state.")
    p.set_defaults(handler=cmd_auth_status, action="auth status")

    p = auth.add_parser("login", help="Log in via Bytedance SSO device flow.")
    p.add_argument("--no-browser", action="store_true", help="Do not try to open a browser.")
    p.add_argument("--timeout", type=int, default=cua_auth.DEFAULT_LOGIN_TIMEOUT_SEC,
                   help="Seconds to wait for login to complete.")
    p.add_argument("--session-id", help="Resume polling an existing login session.")
    p.set_defaults(handler=cmd_auth_login, action="auth login")

    p = auth.add_parser("logout", help="Revoke the refresh token and clear the local cache.")
    p.set_defaults(handler=cmd_auth_logout, action="auth logout")

    p = sub.add_parser("ping", help="Read-only auth and desktop-binding check. Creates no task.")
    p.set_defaults(handler=cmd_ping, action="ping")

    p = sub.add_parser("delegate", help="Delegate the user's original objective to CUA.")
    p.add_argument("--objective", required=True, help="The user's original request. Do not pre-plan or add constraints.")
    p.add_argument("--wait-ms", type=int, default=None, help="Max ms to wait before returning. Does not cancel the task.")
    p.set_defaults(handler=cmd_delegate, action="delegate")

    p = sub.add_parser("watch", help="Wait for or check an invocation's next state.")
    _add_invocation_args(p)
    p.add_argument("--wait-ms", type=int, default=None, help="Max ms to wait before returning. Does not cancel the task.")
    p.set_defaults(handler=cmd_watch, action="watch")

    p = sub.add_parser("answer", help="Submit the user's answer when outcome is needs_input.")
    _add_invocation_args(p)
    p.add_argument("--answer", required=True, help="The user's answer to input_request.question.")
    p.add_argument("--wait-ms", type=int, default=None, help="Max ms to wait before returning.")
    p.set_defaults(handler=cmd_answer, action="answer")

    p = sub.add_parser("cancel", help="Request cancellation. Only when the user asks to stop.")
    _add_invocation_args(p)
    p.set_defaults(handler=cmd_cancel, action="cancel")

    p = sub.add_parser("result", help="Wait until terminal and return the authoritative result.")
    _add_invocation_args(p)
    p.add_argument("--timeout", type=int, default=600, help="Total seconds to keep waiting for a terminal outcome.")
    p.set_defaults(handler=cmd_result, action="result")

    p = sub.add_parser("observe", help="Get a temporary desktop access URL and optional screenshot.")
    p.add_argument("--invocation-id", help="Observe the desktop bound to this invocation.")
    p.add_argument("--last", action="store_true", help="Use the most recent invocation id.")
    p.add_argument("--include-screenshot", action="store_true", help="Also capture a screenshot (saved to a local file).")
    p.set_defaults(handler=cmd_observe, action="observe")

    p = sub.add_parser("self-test", help="Local-only checks. Creates no CUA task.")
    p.set_defaults(handler=cmd_self_test, action="self-test")

    return parser


def _add_invocation_args(p):
    p.add_argument("--invocation-id", help="The invocation id returned by delegate.")
    p.add_argument("--last", action="store_true", help="Use the most recent invocation id from local session cache.")


if __name__ == "__main__":
    sys.exit(main())
