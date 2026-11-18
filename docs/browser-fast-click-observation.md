# Browser click latency: bounded navigation observation

## Motivation

A UDB-owned Chrome click currently waits as long as **1000 ms** to detect
whether the clicked element initiated a navigation. This conservative default
is useful for links and submit buttons, but delays simple buttons that change
the document without navigation. The browser already supports
`observe_after="snapshot"` / `"read"`, returning the redacting page view
within one host request (PR #230).

This change adds an explicit, **opt-in** observation budget for a **single**
`host_browser(action="click")`:

```json
{
  "action": "click",
  "session_id": "<previously observed owned session>",
  "tab_id": "<previously observed owned tab>",
  "role": "button",
  "name": "Toggle panel",
  "observe_after": "snapshot",
  "click_navigation_observe_ms": 100
}
```

- Valid range: **100–1000 ms**, default **1000**. Only `click` with
  `observe_after="read"` or `"snapshot"` may shorten this window.
- Pick a short budget only for observed **non-navigating** controls such as a
  panel-toggle or a local UI button. Do **not** shorten it for unknown
  destinations, form submits, checkout or other consequential clicks.
- If navigation begins within the shortened window, the existing bounded
  document-ready verification runs as before.
- If no navigation was detected, the result retains `clicked=true` and
  `replay_safe=false`, and now explicitly carries
  `navigation_completed=false`, `navigation_observation_limited=true` and
  `navigation_observed_ms=100`. This is **not** proof that a delayed
  navigation will not occur. Read the returned observation, verify the
  expected control/page state, and inspect again before any follow-up mutation
  if state is missing, stale or contradictory.
- If no previous page URL was observable, the response records a limited
  observation window of **0 ms**. No navigation guarantee is made.
- An unavailable or failed post-click snapshot never retries the click.
  Never resubmit an uncertain input because its observation is incomplete.
- With `click_navigation_observe_ms` omitted or set to 1000, the old behavior
  is unchanged. Existing 1–12-step browser batches and FastPath keep their
  original safety/verification contract and do not accept this option.

## Safety constraints

The original owner browser grant, tab ownership, local handoff, URL blocking,
CDP-only input, timeout/deadline, redaction and no-replay behavior remain
unchanged. Input effects cannot be inferred from CDP's successful send alone.
All options are validated by the host service **before any browser action**.

## Benchmark and test design

A deterministic fake-CDP test with a virtual clock demonstrates the exact
programmed observation budgets for a non-navigating click:

| Scenario | Post-click observation budget |
| --- | ---: |
| Default | 1000 ms |
| Explicit fast observation | 100 ms |
| Programmed maximum saving | **900 ms** |

This is a **budget comparison**, not measured p50/p95 of Chrome, Cloudflare,
the user's PC, or the overall task. The actual benefit depends on CDP,
rendering, network and follow-up observation. A live user-authorized test
must measure a non-navigating button vs navigation/submit safety parity
before claiming end-to-end gains.

Run:
```sh
python -m pytest -q tests/core/test_browser_click_observation_budget.py
python -m ruff check src tools tests
python -m ruff format --check .
python tools/export_fleet_catalog.py --check
```

No deployment or owner permission changes occur when merging this code.
