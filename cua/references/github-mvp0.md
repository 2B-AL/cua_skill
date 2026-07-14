# GitHub MVP0: direct `gh` on CUA

This experimental command surface validates a direct Issue-to-PR workflow on
the existing CUA desktop. It adds no gateway endpoint and requires no CUA image
change beyond preinstalled `gh` and Git.

## Preconditions

- CUA Skill authentication is complete.
- The selected CUA desktop has `gh` and Git.
- Claude Code or OpenCode config-sync is verified.
- Use a test GitHub account/repository and a disposable desktop.
- The desktop can reach `github.com` and `api.github.com`.

## Happy path

```bash
# 1. Start GitHub CLI login on CUA.
python3 scripts/cua.py github-mvp0 connect

# 2. While in_progress, use the returned next.command.
python3 scripts/cua.py github-mvp0 watch --task-id <login-task-id>

# 3. Open data.verification_uri locally, enter data.user_code, authorize,
#    then and only then resume the same task.
python3 scripts/cua.py github-mvp0 connect \
  --task-id <login-task-id> --authorized

# 4. Optional independent persistence check.
python3 scripts/cua.py github-mvp0 status

# 5. Run one Issue. This automatically config-sync verifies the selected app.
python3 scripts/cua.py github-mvp0 run \
  --issue https://github.com/<owner>/<repo>/issues/<number> \
  --agent claude-code

# 6. Poll or wait for the parsed PR result.
python3 scripts/cua.py github-mvp0 watch --task-id <code-task-id>
python3 scripts/cua.py github-mvp0 result --task-id <code-task-id> --timeout 1800
```

For a blocking run, add `--wait --timeout 1800` to `run`.

## Command behavior

| Command | Behavior |
| --- | --- |
| `doctor` | Runs a read-only CUA task checking `gh`, Git, auth, and selected agent availability |
| `connect` | Starts GitHub CLI web/device flow or resumes the same login task after user authorization |
| `status` | Verifies the remote `gh` account and rebuilds the local desktop/login cache |
| `logout` | Runs remote `gh auth logout` and clears the local MVP0 connection cache |
| `run` | Validates the Issue URL, verifies config-sync, fixes workspace/branch, and starts an offline task |
| `watch` | Reads task state and parses device-action or terminal MVP0 markers |
| `result` | Polls the authoritative task result and returns only parsed allow-listed fields |
| `cancel` | Requests cancellation; use only when the user asks |

## Two-stage connect contract

The first call returns one of:

- `in_progress`: run `next.command`;
- `needs_user_action`: show `verification_uri` and `user_code` to the user;
- `connected`: the desktop was already authenticated.

`--authorized` is a statement about an external user action. An agent must never
invoke it until the user explicitly confirms authorization.

The login task asks CUA to preserve the terminal process while blocked. If the
current CUA runtime does not preserve it, obtain a temporary desktop-access URL
and complete the same `gh auth login --web` flow manually for MVP0 validation,
then run `github-mvp0 status`.

## Desktop binding

The CLI records `platform.desktop` from connect/status in its normal local
session file. Later commands default to that desktop. `run --desktop` is allowed
only when it equals the saved desktop; a mismatch fails before task creation.

If the cache was removed but the remote desktop is still authenticated, run
`status --desktop <id>` once. Remote `gh auth status` is the source of truth.

## Fixed workspace and branch

Each `run` generates a client-side 12-hex run id before task creation:

```text
workspace = C:\CUA\github-mvp0\<run-id>\repo
branch    = cua/mvp0/<run-id>-issue-<number>
```

The random run id is used instead of the task id because the task id does not
exist until after the objective has been submitted. The repository, Issue,
workspace, branch, and coding agent are embedded as fixed prompt parameters.

## Structured results

Connect success:

```json
{
  "status": "connected",
  "host": "github.com",
  "login": "cua-test",
  "git_protocol": "https",
  "desktop": "desktop-1",
  "task_id": "task-login-1"
}
```

Issue success:

```json
{
  "status": "completed",
  "repository": "acme/demo",
  "issue_number": 7,
  "branch": "cua/mvp0/012345abcdef-issue-7",
  "commit_sha": "abcdef1",
  "pull_request_number": 9,
  "pull_request_url": "https://github.com/acme/demo/pull/9",
  "tests": "go test ./... passed"
}
```

The parser requires fixed markers and validates that repository, Issue, branch,
and PR URL match the original request cached for that task. It does not expose
raw final text.

Task creation, answer, and status endpoints may return a terminal projection
without `result.text`. Before parsing a terminal MVP0 envelope, the CLI
automatically fetches the authoritative `/v1/tasks/<id>/result` projection when
the text is absent. A missing marker is reported only after that fallback.

## MVP0 verification gates

Validate in order:

1. Manual `gh` login/clone/push/PR on one disposable CUA desktop.
2. `connect` reaches `needs_user_action` and `--authorized` resumes the same
   terminal process.
3. A new `status` task on the same desktop remains connected.
4. Claude Code resolves one small Issue and creates a PR.
5. OpenCode resolves one small Issue and creates a PR.
6. `logout` makes a new status task return disconnected.

Do not interpret a Phase 1/2 failure as a GitHub protocol failure until the CUA
task pause/resume and desktop persistence behavior are checked separately.
