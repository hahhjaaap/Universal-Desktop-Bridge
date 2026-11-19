# Click hot path: fuse origin observation into locator probe

## Before

An owned-browser click made two sequential `Runtime.evaluate` requests
before reading the main-frame loader and dispatching native CDP pointer
events:

1. `Runtime.evaluate('location.href')`
2. `Runtime.evaluate(<actionability locator expression>)`

The first URL could become stale while the second evaluation waited for
an element to become actionable.

## After

The trusted, fixed actionability locator expression returns
`{ok:true,x,y,previous_url:location.href}` only on success. The pre-input
URL is captured at the same time as the actionable click coordinates.
The separate URL request is removed, saving **one CDP roundtrip per click**.

This is a deterministic reduction in CDP command count, **not** a measured
wall-clock speedup. Depending on browser load and network, CDP calls have
variable latency. No claim is made about total 5–6 second task completion.

## Safety

- The browser still dispatches exactly one pointer gesture and still
  requests the pre-click main-frame ID/loader, rejects stale/ambiguous or
  disabled controls, and observes potential navigation afterwards.
- `previous_url` is *internal* navigation context. It is never returned
  in the tool result, logged or stored in the batch receipt.
- If the locator cannot return a valid URL, the existing
  `previous_url=None` fallback remains available. A shortened observation
  does not silently become a verified navigation.
- Fixed CDP JavaScript is unchanged in authority: no caller-provided JS or
  external browser profile is introduced. No Windows input, permissions,
  Cloudflare configuration, or browser-control grants change.

Unit tests verify exactly one pre-click actionability evaluation, the
correct origin passed into navigation detection, absence of secret query
data in the result, and bounded uncertainty when the origin is missing.
Existing isolated real-Chromium navigation/click tests remain part of the
Linux CI.
