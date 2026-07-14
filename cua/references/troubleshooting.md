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
| `INVOCATION_NOT_WAITING_INPUT` | 409 | `answer` sent but CUA is not asking | run `watch`/`task status` first to see the real state |
| `CONTEXT_NOT_FOUND` | 404 | wrong/unknown context id | re-check the id; use `context list` or `--last-context` |
| `SCHEDULE_NOT_FOUND` | 404 | wrong/unknown (or deleted) schedule id | re-check with `schedule list` |
| `ARTIFACT_NOT_FOUND` | 404 | unknown artifact, or it has no bytes | re-check with `artifact list`; a placeholder artifact has no downloadable content |
| `ACTIVE_RUN_CONFLICT` | 409 | the context already has a run in flight | wait for it (`task status`) before starting another |
| `SCHEDULE_NESTING_NOT_ALLOWED` | 409 | a scheduled task tried to manage schedules | scheduled tasks cannot create/modify other schedules; do it directly |
| `SCHEDULING_UNAVAILABLE` | 501 | this CUA backend has no scheduled-task endpoint (platform 404) | tell the user scheduling is unavailable; run the goal once with `task run`. Do NOT retry with other args or fall back to an external scheduler |
| `PAYLOAD_TOO_LARGE` | 413 | request body too large | shorten the objective/note/answer |
| `DESKTOP_NOT_FOUND` | 404 | `--desktop` id/name does not exist | run `desktop list` and use a listed id/name |
| `CUA_BACKEND_UNAVAILABLE` | 503 | CUA backend down | wait and retry, or report the outage |
| `RATE_LIMITED` | 429 | too many requests | wait, then retry |
| `VALIDATION_ERROR` | 400 | bad/missing argument (e.g. malformed `--run-at`) | fix the argument and retry |
| `NETWORK` | — | cannot reach the gateway | check connectivity / `--api-base-url`; retry |
| `INTERNAL` | 500 | unexpected | retry once; if it persists, report it |

## GitHub MVP0 errors

These are local Skill errors or fixed error markers parsed from the CUA result;
they do not require a new gateway error contract.

| code | cause | what to do |
| --- | --- | --- |
| `GITHUB_MVP0_GH_NOT_INSTALLED` | CUA image has no usable `gh` | use the expected MVP0 image |
| `GITHUB_MVP0_GIT_NOT_INSTALLED` | CUA image has no usable Git | use the expected MVP0 image |
| `GITHUB_MVP0_AUTH_REQUIRED` | no verified remote `gh` login is cached, or CUA reports logged out | run `github-mvp0 connect`; if the desktop may already be logged in, run `status` |
| `GITHUB_MVP0_AUTH_OUTPUT_INVALID` | login task did not return the fixed device URL/code marker | inspect the task with desktop access; retry connect once |
| `GITHUB_MVP0_DEVICE_CODE_EXPIRED` | one-time code expired | start a new connect task |
| `GITHUB_MVP0_AUTH_DENIED` | GitHub authorization was cancelled/denied | ask the user whether to retry connect |
| `GITHUB_MVP0_SESSION_NOT_RESUMABLE` | login process was lost while the task waited | use temporary desktop access for the MVP0 manual fallback |
| `GITHUB_MVP0_DESKTOP_CHANGED` | code task targets a different desktop from login | omit `--desktop` or use the desktop saved by connect |
| `GITHUB_MVP0_UNEXPECTED_INPUT` | an offline code/doctor/status task asked a question | stop; simplify the Issue or inspect the CUA task |
| `GITHUB_MVP0_AGENT_CONFIG_INVALID` | Claude Code/OpenCode config is unavailable | run the normal config-sync preflight |
| `GITHUB_MVP0_REPO_DENIED` | account cannot access the repository | correct the test account/repository permission |
| `GITHUB_MVP0_REPO_ARCHIVED` | repository is archived | select a writable test repository |
| `GITHUB_MVP0_ISSUE_NOT_FOUND` | Issue is missing/not usable | check the canonical Issue URL and state |
| `GITHUB_MVP0_ISSUE_NOT_OPEN` | Issue is not open | select an open test Issue |
| `GITHUB_MVP0_CLONE_FAILED` | HTTPS clone failed | check GitHub reachability, auth, and repository permission |
| `GITHUB_MVP0_NO_CHANGES` | coding agent produced no diff | inspect Issue clarity and agent output |
| `GITHUB_MVP0_TEST_FAILED` | relevant tests failed | inspect/fix; MVP0 does not push on this path |
| `GITHUB_MVP0_PUSH_FAILED` | task branch push failed | check write permission and branch policy |
| `GITHUB_MVP0_PR_FAILED` | PR create/query failed | check repository policy and whether a PR already exists |
| `GITHUB_MVP0_RESULT_INVALID` | fixed result fields/PR URL do not match the request | inspect the CUA task; never infer success |
| `GITHUB_MVP0_TASK_FAILED` | CUA failed without a recognized MVP0 marker | inspect task/desktop diagnostics |

The gateway translates the platform's raw snake_case errors (`active_run_conflict`,
`run_not_blocked`, `session_desktop_mismatch`, `nested_scheduled_task_not_allowed`,
`deleted_task`, `artifact_missing`, `payload_too_large`, …) into these stable
Skill codes, so you only ever branch on the codes above — never on raw platform codes.

## Common situations

- **"No CUA gateway configured."** The bundled `config.json` still has the
  REPLACE placeholder. Pass `--api-base-url <url>` or set
  `CUA_SKILL_API_BASE_URL`, or have the publisher fill in `config.json`.
- **Login never completes.** The user must finish CloudIdentity v2 sign-in in a browser at
  `login_url`. Re-run `auth login --session-id <id>` (from `retry_command`) to
  keep polling. Default poll timeout is 300s; extend with `--timeout`.
- **Task seems stuck.** `in_progress` after a wait window just means it is still
  running — `watch` again. Do not `cancel` unless the user asks.
- **`access_url` won't open / expired.** Run `observe` again for a fresh URL.
- **Unsafe permissions on the auth file.** The script repairs to `0600`
  automatically; if it cannot, fix the filesystem and retry.
