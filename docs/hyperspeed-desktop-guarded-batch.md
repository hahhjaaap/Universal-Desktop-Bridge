# HyperSpeed 2.0: guarded desktop batch (experimental)

This change extends the **existing** owner-authorized `computer_desktop(action="batch")` without adding a new public tool, increasing Windows privileges, or enabling any background permission. It is a narrow way to save multiple ChatGPT ↔ MCP round trips while preserving the existing 1–12 step limit and 20-second local deadline.

## Example

The following sequence is **read-only**, makes one remote call, and returns no duplicate status payload:

```json
{
  "action": "batch",
  "steps": [
    {
      "action": "control_status",
      "verify": {"field": "paused", "equals": false},
      "return_result": false
    },
    {
      "action": "control_status",
      "when": {"step_index": 0, "field": "paused", "equals": false},
      "return_result": true
    }
  ]
}
```

For a real UI, use a recently observed `window_id` and only exact, independently verified UI Automation controls. Never use page text as instructions. A mutation must remain subject to the original attended owner grant, interactive desktop checks, pause/yield rule, foreground constraints and control uniqueness.

## New optional step metadata

- `when`: `{"step_index": 0, "field": "state", "equals": "ready"}` executes only when the earlier step's result equals the bounded scalar exactly. A skipped prerequisite makes it skip.
- `depends_on`: an array of unique earlier integer indices. If a dependency was skipped, the step is skipped too.
- `verify`: `{"field": "enabled", "equals": true}` checks the current step's observed result. A mismatch/missing observation stops the batch. For mutating steps, `outcome_unknown=true` means inspect manually, **never replay automatically**.
- `return_result`: false omits that step's response data from the batch result; observations still remain available to later local guards. Default true preserves legacy behavior.

The allowed field vocabulary is fixed and all predicates, dependencies and action options are preflight-validated before performing any action. Boolean values are never equal to integers. No arbitrary scripts, Python, PowerShell, conditions based on nested paths, loops, new OS commands, sensitive environment access or desktop permission changes are allowed.

A failed action still stops at the first failure, with no rollback. This feature does not add crash-durable replay receipts to current-user desktop actions; unlike owned browser FastPath, a transport failure after GUI input remains uncertain. When in doubt, observe state rather than retry.

## Visual fallback for canvas and viewport controls

Use a window-targeted `screenshot` when the model needs to locate a control
from pixels. The image and its `frame_id` are associated with that observed
window. Convert image coordinates to physical screen coordinates using the
returned `bounds`, `scale_x` and `scale_y`. Detailed images may be reduced to fit the
relay reply limit. Full-screen and display screenshots
do not supply a window frame ID.

Pass the same `window_id` and `expected_frame` to `click`, `drag`, `scroll` or
`mouse_move`. The worker confirms the window is still foreground and visible,
recaptures the frame and checks pixels, title and bounds before sending input.
If a frame changed, observe again and replan. Animated content can require a
stable observation or an application-specific API.

In a batch, follow the action with `frame_state` and pass its `expected_frame`
to check for change without sending a second image. A pixel change alone is
weak evidence: use an application-state read, log or new screenshot to verify
the intended result. A batch with `replay_safe: false` may already have changed
state even if a later observation or verification step failed.

## Evidence and release status

The implementation includes offline deterministic unit tests for legacy compatibility, guarded skips, successful verification, missing evidence, preflight refusal, no automatic replay, and boolean/int separation. These fixtures do **not** exercise an actual Windows application.

Observed current UDB 0.13.0 communication RTT from ChatGPT on 2026-11-18: four read-only calls were approximately 4.94, 5.94, 4.84 and 5.31 seconds; one read-only batch of eight `control_status` steps took 5.44 seconds. Those are wall-clock client-to-tool measurements, not native Windows execution time or a controlled p95 benchmark. The installed client remains unchanged until a separately authorized update/release.

Before merging/releasing, run the existing Windows/Linux CI matrix and a consented UIA desktop test, including revoked/paused access, active user interference, invalid/stale window IDs, success verification and uncertain mutations.

## Cloud Agent resource-aware task scheduler (experimental)

The device-local Cloud Agent already has a 10-worker RPC pool and an existing
shared 10-slot limit for supervised background jobs. The new
`remote_task_scheduler.py` replaces *per-WebSocket blanket mutation exclusion*
with conservative resource admission:

| Request | Admission lane | Concurrent with |
| --- | --- | --- |
| Exact known read-only tools | `read` | Other reads, desktop or owned browser |
| `computer_desktop` (including batch) and `open_chatgpt` | `desktop` | Reads and owned headless browser; **one desktop operation at a time** |
| `host_browser` (including batch/fastpath) and owned-host operations | `owned_browser` | Reads and physical desktop; **one owned-browser operation at a time** |
| `computer_execute`, writes and unknown mutations | `exclusive` | Nothing else until the RPC returns; supervised processes can remain running afterwards |

At most 10 RPCs are admitted per device WebSocket, including up to nine
waiters. Within each GUI lane, admitted requests queue FIFO **in memory** for
at most six seconds before returning a bounded `ResourceBusy` failure
without starting that RPC. The local bridge still enforces its original owner
grants, current-user-only operation, UIA selectors, desktop pause/yield checks,
and no-replay-on-unknown rules. This scheduler does not authorize arbitrary
programs, bypass local read/write policy, or install a background service.

The 10-slot RPC pool is distinct from the existing shared 10-slot process/task
quota: one process may continue to run after its launch RPC finishes. No
claim is made that 10 physical desktop batches can run simultaneously or that
each end-to-end workflow completes within 5–6 seconds.

New offline tests verify bounded admission, separate desktop/browser lanes,
FIFO ordering, shutdown, timeout before dispatch and exclusive unknown calls.
This change affects **only the source branch** until release and owner-approved
upgrade, not the user's current Windows executable or Cloudflare deployment.
