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

## Evidence and release status

The implementation includes offline deterministic unit tests for legacy compatibility, guarded skips, successful verification, missing evidence, preflight refusal, no automatic replay, and boolean/int separation. These fixtures do **not** exercise an actual Windows application.

Observed current UDB 0.13.0 communication RTT from ChatGPT on 2026-11-18: four read-only calls were approximately 4.94, 5.94, 4.84 and 5.31 seconds; one read-only batch of eight `control_status` steps took 5.44 seconds. Those are wall-clock client-to-tool measurements, not native Windows execution time or a controlled p95 benchmark. The installed client remains unchanged until a separately authorized update/release.

Before merging/releasing, run the existing Windows/Linux CI matrix and a consented UIA desktop test, including revoked/paused access, active user interference, invalid/stale window IDs, success verification and uncertain mutations.
