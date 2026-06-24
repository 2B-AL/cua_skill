# Troubleshooting

All errors arrive as `{ "ok": false, "action": "...", "error": { "code", "message", ... } }`.
Branch on `error.code`.

| code | HTTP | cause | what to do |
| --- | --- | --- | --- |
| `AUTH_REQUIRED` | 401 | no/invalid session | run `error.retry_command` (login), show `login_url`/`user_code`, then retry the original command |
| `TOKEN_EXPIRED` | 401 | access token expired | the script auto-refreshes; if it persists, treat as `REFRESH_FAILED` |
| `REFRESH_FAILED` | 401 | refresh token invalid/expired/reused | log in again |
| `FORBIDDEN` | 403 | missing scope | tell the user they lack permission for this action |
| `DESKTOP_NOT_BOUND` | 403 | no CUA desktop allocated | tell the user CUA is not provisioned; contact an admin |
| `INVOCATION_NOT_FOUND` | 404 | wrong/unknown invocation id | re-check the id; do not guess. Use `--last` or the id from `delegate` |
| `INVOCATION_NOT_WAITING_INPUT` | 409 | `answer` sent but CUA is not asking | run `watch` first to see the real state |
| `CUA_BACKEND_UNAVAILABLE` | 503 | CUA backend down | wait and retry, or report the outage |
| `RATE_LIMITED` | 429 | too many requests | wait, then retry |
| `VALIDATION_ERROR` | 400 | bad/missing argument | fix the argument and retry |
| `NETWORK` | — | cannot reach the gateway | check connectivity / `--api-base-url`; retry |
| `INTERNAL` | 500 | unexpected | retry once; if it persists, report it |

## Common situations

- **"No CUA gateway configured."** The bundled `config.json` still has the
  REPLACE placeholder. Pass `--api-base-url <url>` or set
  `CUA_SKILL_API_BASE_URL`, or have the publisher fill in `config.json`.
- **Login never completes.** The user must finish SSO in a browser at
  `login_url`. Re-run `auth login --session-id <id>` (from `retry_command`) to
  keep polling. Default poll timeout is 300s; extend with `--timeout`.
- **Task seems stuck.** `in_progress` after a wait window just means it is still
  running — `watch` again. Do not `cancel` unless the user asks.
- **`access_url` won't open / expired.** Run `observe` again for a fresh URL.
- **Unsafe permissions on the auth file.** The script repairs to `0600`
  automatically; if it cannot, fix the filesystem and retry.
