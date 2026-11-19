# Browser batch: inspected terminal fast click

Owned-browser batches already consolidate up to 12 allowlisted operations
into one Cloudflare/MCP request. They ordinarily wait up to 1000 ms after
every click to detect navigation. For a **previously observed control that
does not navigate**, the final click of a normal batch can now optionally
use the fast click navigation observation window from PR #233, while
returning the bounded redacting observation in that same batch response.

Example `host_browser(action="batch")` steps:

```json
[
  {"action": "wait_for", "selector": "#panel-toggle", "state": "visible"},
  {
    "action": "click",
    "selector": "#panel-toggle",
    "observe_after": "snapshot",
    "click_navigation_observe_ms": 100
  }
]
```

The surrounding browser request still needs the previously authorized
`session_id`, owned `tab_id` and stable `request_id`. Its one-shot receipt
is persisted **before** any page mutation. Repeating a request ID returns
the previous result or an uncertain receipt; it never resends a click.

## Intentional safety restrictions

- The shortened `click_navigation_observe_ms` value is an **integer from
  100 to 1000**, default 1000.
- Values below 1000 require `observe_after="read"` or `"snapshot"`,
  and the observed click MUST be the **last** step of a regular batch.
  No follow-up mutation is permitted in the same batch while delayed
  navigation may still occur.
- `FastPath` declarative verification semantics are **unchanged**.
  FastPath rejects these two new fields; ordinary batches continue
  to use their exact legacy behavior unless the caller opts in.
- All nested fields/positions are validated before any step is dispatched.
- If post-click observation fails, the batch is marked
  `state="outcome_unknown"`, not completed. The click may already have
  succeeded and **must not be retried**.
- A successful short click still reports
  `navigation_observation_limited=true` if no navigation is detected in
  the short window. A snapshot/read is evidence of immediate page state
  only, **not** proof no delayed navigation can occur.

The change does not add caller scripting, browser profile access, Windows
input, permissions, external endpoints or new runtime dependencies.

## Performance validation

For a non-navigating button, the *configured post-click navigation
observation budget* decreases from 1000 ms to as little as 100 ms, a
potential reduction of 900 ms for the final click of a batch. This does
not establish actual end-to-end p50/p95 speedups: network, CDP, page
rendering and Windows host scheduling also contribute.

Tests assert preflight rejection before any earlier mutation, correct
terminal observation, durable no-replay behavior, and fail-closed
post-observation errors. The direct click behavior is separately exercised
by PR #233 tests.
