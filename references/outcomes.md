# Outcome state machine

`delegate`, `watch`, `answer`, and `result` all return the same invocation
envelope under `data`:

```json
{
  "invocation_id": "cua_inv_...",
  "outcome": "in_progress | needs_input | completed | failed | cancelled",
  "result": { "text": null, "artifacts": [] },
  "input_request": { "question": "...", "choices": [] } ,
  "progress": { "summary": "...", "step_count": 2, "updated_at": "..." },
  "next_action": { "type": "...", "agent_hint": "..." },
  "diagnostics": { "trace_id": null }
}
```

The CLI also adds a top-level `next` block with a ready-to-run `command`.

## Transitions

```
delegate ──> in_progress ──watch──> in_progress   (loop)
                         └────────> needs_input ──answer──> in_progress
                         └────────> completed
                         └────────> failed
                         └────────> cancelled
```

## How to handle each outcome

| outcome | what it means | what to do |
| --- | --- | --- |
| `in_progress` | CUA is still working | Run `next.command` (a `watch`). Do not answer the task yourself. Do not cancel for slowness. |
| `needs_input` | CUA needs the user | Relay `input_request.question` to the user verbatim, then `answer`. |
| `completed` | Done | Use `result.text` as the authoritative final answer. Mention `result.artifacts` if relevant. |
| `failed` | CUA could not finish | Explain the failure. Retry only if the user asks. |
| `cancelled` | Stopped | Tell the user it was cancelled. |

## Rules

- `result.text` is authoritative ONLY when `outcome == completed`. In every other
  state `result.text` is `null` — never fabricate a result from `progress` or a
  screenshot.
- A timeout is NOT an outcome. If a `watch`/`delegate` returns `in_progress`
  because its `wait_ms` elapsed, just `watch` again.
- `watch` default wait is 60s; the server caps a single wait at 10 minutes.
