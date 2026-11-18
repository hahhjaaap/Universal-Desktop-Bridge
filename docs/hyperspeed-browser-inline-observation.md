# HyperSpeed browser: fuse action + observation in one MCP request

This change saves a **full ChatGPT↔Cloudflare↔Windows tool round trip**
whenever an agent already knows what to do in a UDB-owned background tab
and needs to **observe the result immediately afterwards**.

The default behavior is unchanged. Call the existing public `host_browser` tool
with optional `observe_after="snapshot"` or `observe_after="read"` on:

- `open` or `new`: start/create an owned tab and include its initial accessible
  snapshot in the same response, without a separate `snapshot` tool call.
- `navigate`: navigate then return the bounded observed page state.
- `click`, `fill`, `press`, `select_option`, `check`, `uncheck`,
  `scroll`, `back`, `forward`, `reload`: perform exactly one action
  and attach the post-action snapshot or read view **in the same host worker
  request**.

For example, the first page inspection takes **one remote request** instead of
two (illustrative arguments):

```json
{
  "action": "open",
  "url": "https://example.org/",
  "observe_after": "snapshot"
}
```

For a previously observed unique button in an owned tab:

```json
{
  "action": "click",
  "session_id": "<previously returned owned session ID>",
  "tab_id": "<previously returned owned tab ID>",
  "role": "button",
  "name": "Next",
  "observe_after": "snapshot"
}
```

The response preserves the original action fields and adds:

```json
{
  "clicked": true,
  "replay_safe": false,
  "observe_after": "snapshot",
  "observation": {"url": "https://example.org/", "elements": []}
}
```

The observation structure is the existing bounded redacting
`browser.snapshot` or `browser.read`. No arbitrary page JavaScript, CDP
attachment to a personal profile, or new credentials are added.

## Safety and failure behavior

- Invalid `observe_after` values and unsupported action combinations are
  refused **before any remote browser mutation**.
- A failed or uncertain action is **not** post-observed or replayed. The
  response may include `observation_skipped="action_failed_or_uncertain"`.
- If the action completed but a post-action read failed (e.g. navigation
  destroyed the JS execution context), its original result is preserved with
  `observation_unavailable=true`. Never resend a click/submit because this
  field is present: instead issue a separate read on the existing tab.
- Full browser ownership, session expiry, local consent, resource guards,
  URL validation, download blocking, browser handoff and browser-serial
  scheduling still apply.
- Batch/fastpath remain available for multi-step operations within one owned
  tab, with their existing request receipts, verification and replay guards.
  `observe_after` is deliberately **not** accepted for batch/fastpath since
  they already accept an explicit final snapshot/read step.
- A single post-action observation consumes one local CDP read, so this
  optimization removes the **remote** round trip, not all browser processing.
- The installed UDB client and Cloudflare relay must be independently
  updated after a fully verified release; merging source alone does not upgrade
  a Windows host or enable background browser permissions.

## Verifying speed

Record from the same Windows device and page:

1. Old workflow: call open, then call snapshot; measure both tool wall times.
2. New workflow: call open with `observe_after=snapshot`; measure wall time.
3. Repeat for click + snapshot vs click with `observe_after=snapshot`,
   including navigation and non-navigating button actions.
4. Track p50/p95 tool wall time, action outcome parity, page observation parity,
   session/tab count, memory usage and any observation_unavailable result.

The saved round-trip count is a structural guarantee (two remote calls become
one). Actual milliseconds, p50/p95 and gains on real sites are **not claimed**
until measured on an owner-authorized UDB installation.
