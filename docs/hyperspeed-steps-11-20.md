# UDB HyperSpeed 2.0 — FastPath steps 11–20

**Implementation:** native browser action `host_browser(action="fastpath")`.
This is a new **mode** of the existing public `host_browser` tool,
not a new elevated tool or a general-purpose code/command executor.

## Steps implemented

| Step | Change and acceptance |
| ---: | --- |
| 11 | One-call `fastpath` route through the existing owner-authorized browser worker and durable BatchRunner |
| 12 | Bounded declarative DSL, no caller JavaScript: `action`, action-specific args, optional `step_id`, `depends_on`, `when`, `verify`, `return_result` |
| 13 | Whole-plan validation of an explicitly ordered DAG (edges only to earlier steps) before any page I/O or one-shot receipt |
| 14 | 1–12 allowlisted browser actions per single request, reusing the existing 20-second total deadline |
| 15 | Observe/act/verify loop local to the worker; no ChatGPT roundtrip between steps |
| 16 | Branch via a bounded prior-step result predicate; false conditions skip without mutating the page; skipped ancestors block dependent steps |
| 17 | Existing event-driven `wait_for` (MutationObserver with bounded timeout) works inside FastPath; wait failures stop the workflow |
| 18 | Never auto-retry mutations or ambiguous CDP responses, even on timeout or verification failure |
| 19 | Durable payload-free `request_id` receipt and request digest (fastpath has separate digest from legacy `batch`); subsequent calls cannot replay already dispatched actions |
| 20 | Existing pause/revoke, session-expiry, user handoff, cancel and 20-second deadline checks run before each step; status/cancel through `batch_status`/`batch_cancel` remain available concurrently |

### Example: safe, one-call browser workflow

After the local Windows owner enables UDB background browser mode and creates an
owned UDB session, send a single tool call:

```json
{
  "session_id": "AN_ACTUAL_32_HEX_OWNED_SESSION_ID",
  "tab_id": "AN_ACTUAL_OWNED_TAB_ID",
  "request_id": "unique-workflow-2026-11-15-01",
  "action": "fastpath",
  "steps": [
    {
      "step_id": "ready",
      "action": "wait_for",
      "selector": "#login-form",
      "state": "visible",
      "timeout_ms": 2000,
      "verify": {"field": "ok", "equals": true}
    },
    {
      "step_id": "fill",
      "action": "fill",
      "selector": "#search",
      "value": "public fixture text",
      "depends_on": ["ready"],
      "when": {"step_id": "ready", "field": "state", "equals": "visible"}
    },
    {
      "step_id": "confirmed",
      "action": "wait_for",
      "selector": "#search",
      "state": "enabled",
      "depends_on": ["fill"],
      "return_result": true
    }
  ]
}
```

The result defaults to **summary only per step**, avoiding unnecessary page
payload transport. A step may opt into returning its value via
`return_result=true`, still subject to the 64-KiB-per-step bound. The
existing `action=batch` mode continues to return each result as before
and keeps its historical receipt digest.

Conditional result comparison accepts only: `ok`, `state`, `matches`,
`visible`, `enabled`, `navigation_completed`,
`navigation_timed_out`, `timed_out`, `clicked`,
`changed`, `selected`, `checked`. The expectation value must be a
bounded boolean, integer or text. Missing fields and invalid predicates fail
closed. No wildcards over response objects, nested conditions, generated
program code or arbitrary CDP commands are accepted.

**Dependency graph scheduling is serial** by design because the UDB browser
worker and CDP channel share one owned session. Parallel execution on
independent tabs is a separate step 51–60 workstream and must prove correct
device/session isolation first. This PR does not modify the existing
owner-authorized Windows desktop batch route. A full cross-application
`udb_fastpath_execute` tool will require a separate, explicitly reviewed
permission contract; the initial browser route delivers the latency-reduction
mechanism with less security risk.

The browser step `verify` is an **observation check**: an unsuccessful
post-mutation verification is reported as `outcome_unknown` and never
automatically retried. It is not a transactional rollback or proof that the
site accepted server-side writes. For payments, submissions and persistent
changes inspect application state before any new attempt.

### Acceptance and deployment

- Synthetic regressions: `tests/core/test_hyperspeed_fastpath.py`, plus
  `tests/core/test_browser_fastpath.py`, owner-grant, Cloudflare schema
  parity, Windows EXE and integration tests.
- CI must pass on the same PR commit before merge. A successful CI fixture does
  **not** demonstrate 5–6 second performance on real Chrome.
- This development PR does not start Chrome, enable permissions, send page
  content, trigger a download or touch the user's Windows machine.
- Real p50/p95 gain can be assessed only once an authorized UDB Windows instance
  has HyperSpeed tracing enabled, and the owner has enabled isolated background
  browser control.
