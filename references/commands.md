# CUA Skill commands

All commands: `python3 <skill_dir>/scripts/cua.py <command> [options]`.
Global option: `--api-base-url <url>` overrides the gateway URL for one call.

Every call prints one JSON object: `{ "ok": true, "action": "...", "data": {...}, "next": {...} }`
or `{ "ok": false, "action": "...", "error": { "code": "...", "message": "..." } }`.

## auth status

Verify the current session against the gateway. Creates no task.

```bash
python3 scripts/cua.py auth status
```

```json
{"ok": true, "action": "auth status", "data": {
  "status": "logged_in",
  "user": {"org_id": "org_x", "user_id": "user_x", "email": "u@bytedance.com"},
  "scopes": ["cua:read", "cua:invoke", "cua:observe", "cua:cancel"],
  "desktop_bound": true,
  "access_token_expires_at": "2026-06-23T10:15:00Z"
}}
```

If not logged in: `error.code = AUTH_REQUIRED` with `retry_command`.

## auth login

Run the SSO device-login flow and cache tokens locally (0600).

```bash
python3 scripts/cua.py auth login [--no-browser] [--timeout 300] [--session-id <id>]
```

- On start it prints (inside the error envelope, if it times out) a `login_url`
  and `user_code`. Show both to the user.
- It polls until the user finishes login or the timeout elapses. Re-run with
  `--session-id <id>` (provided in `retry_command`) to keep polling the same
  session.
- Success: `data.status = "logged_in"`.

## auth logout

Revoke the refresh token server-side and clear the local cache.

```bash
python3 scripts/cua.py auth logout
```

## ping

Read-only auth + desktop-binding check. Creates no CUA task.

```bash
python3 scripts/cua.py ping
```

```json
{"ok": true, "action": "ping", "data": {
  "ok": true,
  "server": {"name": "cua-mcp-server", "version": "0.1.0"},
  "auth": {"authenticated": true, "org_id": "org_x", "user_id": "user_x", "team_id": null, "desktop_bound": true},
  "agent_hint": "..."
}}
```

## delegate

Create an invocation from the user's original objective.

```bash
python3 scripts/cua.py delegate --objective "<user request>" [--wait-ms 30000]
```

- `--objective` (required): the user's request, unmodified.
- `--wait-ms`: max ms to wait before returning. Does NOT cancel the task.

`data` is the invocation envelope (see `outcomes.md`). `next.command` tells you
what to run next.

## watch

Wait for or check an invocation's next state.

```bash
python3 scripts/cua.py watch (--invocation-id <id> | --last) [--wait-ms 60000]
```

## answer

Submit the user's answer when `outcome == needs_input`.

```bash
python3 scripts/cua.py answer (--invocation-id <id> | --last) --answer "<reply>" [--wait-ms 60000]
```

## cancel

Request cancellation. Use only when the user asks to stop.

```bash
python3 scripts/cua.py cancel (--invocation-id <id> | --last)
```

```json
{"ok": true, "action": "cancel", "data": {
  "invocation_id": "cua_inv_...", "cancel_requested": true, "outcome": "in_progress", "agent_hint": "..."
}}
```

## result

Block until a terminal/needs_input outcome and return the authoritative result.
Internally polls `watch`.

```bash
python3 scripts/cua.py result (--invocation-id <id> | --last) [--timeout 600]
```

## observe

Get a short-lived desktop access URL, optionally a screenshot.

```bash
python3 scripts/cua.py observe [--invocation-id <id> | --last] [--include-screenshot]
```

- `access_url` is temporary; if it expires, run `observe` again.
- `--include-screenshot` saves the image to a local file and returns
  `data.screenshot_file` plus `data.screenshot` metadata. The raw image bytes are
  never printed.

## self-test

Local-only checks (Python version, cache file, login state). Creates no task.

```bash
python3 scripts/cua.py self-test
```
