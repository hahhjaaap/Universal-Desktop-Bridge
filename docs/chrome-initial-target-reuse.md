# Chrome performance: reuse the first owned tab

## Confirmed overhead in the existing launch path

The current UDB-owned Chrome command starts with `about:blank`. When
`HostService._start_session` creates the browser it already discovers
and attaches its initial page using CDP. Previously a subsequent
`host_browser(action="open")` always invoked `Browser.new(url)`,
which used `Target.createTarget`, attached/configured that second
target and navigated it. The original blank tab remained open.

Consequences of the old path:

- One redundant blank tab occupied a slot in the existing **four-tab**
  limit for each fresh implicit browser session.
- An unnecessary target and its initialization CDP calls could consume
  renderer resources and add launch latency.
- The new tab required its own `Page.enable`, identity-script injection,
  network interception setup and download-denial calls.

## Optimization

For the **first implicit open of a newly created UDB-owned session**
only, `Browser.open_initial` inspects the existing owned page inventory.
If exactly one attached page exists and its current URL is
`about:blank`, navigate that target directly, or return it without
navigation for a blank request. Otherwise fall back to the original
`new(url)` contract. Later opens and explicit-session opens still
create new tabs, preserving the existing semantics.

Validation of HTTP(S) public destinations and the original CDP
attachment security setup are unchanged. The optimization neither
attaches to a user's Chrome profile nor changes Chrome's Site Isolation,
Safe Browsing, browser flags, cross-origin rules, authentication or
owner grants. If navigation has an uncertain result, there is **no
retry or fallback new tab** after that input.

The optimization avoids one `Target.createTarget` request and the
six per-target CDP setup calls on the common first-open path, and
prevents the spare blank target from consuming the four-tab allowance.
This is a **static, inspectable estimate** of avoided work, not a
measured speedup or a guaranteed reduction in renderer count.

## Validation and release criteria

- Pure tests verify first blank-target reuse, no-op blank opening,
  validation before any action, nonblank/multiple-tab fallback and
  strict non-replay of uncertain navigation.
- HostService tests verify first implicit open chooses reuse while
  repeated implicit and explicit opens preserve the original new-tab
  behavior.
- Existing network-blocklist, URL normalization, owned-process,
  session and cookie/handoff tests remain required.
- For a real latency result, use an **isolated Windows Chrome profile**
  with no personal browser tabs or owner data and explicit test
  authorization. Compare a baseline executable and candidate from
  identical Chrome/Windows versions: at least 30 first opens, p50/p95
  time to the first verified page, CDP call counts, target count and
  committed/private browser memory. Do not use one user's 16 Chrome
  processes as an owned-browser performance measurement.

This change makes no attempt to launch or modify the currently open
personal Chrome or the installed UDB agent on the owner's computer.
