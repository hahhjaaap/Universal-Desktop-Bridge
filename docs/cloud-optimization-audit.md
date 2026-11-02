# UDB Cloud optimization audit (2026-11-02)

Scope: the experimental Cloudflare + Render + Windows cloud-agent integration
inside draft PR #60. The original UDB core has separate CI, simulation and
performance benchmarks; this audit does **not** claim a comprehensive review of
all 500+ repository paths.

## Changes in this pass

| Area | Previous behavior | Optimized behavior | Benefit |
| --- | --- | --- | --- |
| Cloudflare RPC scheduling | Up to four concurrent remote calls to a serial local stdio proxy | One outstanding call per device | Fewer uncertain timeouts and less queued work |
| Cloudflare RPC validation | Replies accepted without matching their JSON-RPC request ID | Validate request ID, JSON-RPC version and exclusive result/error | Reject mismatched or corrupted replies |
| Cloudflare WebSocket frames | String character count only | UTF-8 byte limit, fail waiting requests on oversized frames | Respect payload bounds |
| Cloudflare request parsing | Read entire body, then check size | Stream and cap input before allocation | Lower memory exposure to oversized requests |
| Windows idle agent | Start local MCP child before cloud connection | Start local MCP child only on first remote call | Lower idle CPU and memory |
| Windows disconnect | Immediate retries after clean disconnect, fixed delay after failure | Bounded backoff and minimum delay; stop on 401/403 | Reduce quota waste and unauthorized reconnects |
| Regression coverage | Tests primarily covering happy paths | Tests for concurrent RPCs, invalid replies, oversized inputs, socket closure, offline backoff | Verify failure handling |
| CI | Cloud workflow lint only; full workflow formatting caught defects later | Cloud workflow lint **and** formatting | Faster feedback and fewer wasted Windows CI runs |

The current prototype still does not provide a ChatGPT OAuth resource server,
per-user authorization scopes, published plugin, signed Windows installer,
live Cloudflare/Render deployment or real multi-machine acceptance results.
**It must not be marketed as "install once and use immediately".**

## Cost and performance tradeoffs

- One outstanding call per device matches the current Windows stdio behavior,
  but sacrifices parallel RPC throughput. To support concurrency later, use a
  bounded worker pool with explicit per-device command serialization and scoped
  per-user authorization, not merely a larger queue on Cloudflare.
- Minimal backoff starts at 5 seconds and increases to 120 seconds on repeated
  failures. This may delay recovery after long outages but prevents a failed
  agent from draining Cloudflare Free quota.
- Starting the local MCP process lazily saves idle resources, at the cost of
  one cold startup when the first tool call arrives. Measure this startup with
  the existing benchmark before changing it further.
- Render remains a read-only observer, not automatic failover. Keeping it out
  of the authorization or device-command path reduces trust boundaries.

## Release gates

- Both the cloud test workflow and cross-platform full regression pipeline pass.
- Controlled live test on a non-sensitive Windows machine against an owner
  Cloudflare Worker using only low-risk read-only tool calls.
- Device-owner authorization, per-user OAuth, token revocation, signed installer,
  end-user GUI setup and independent security review.
- A second Windows test machine with separate user/credentials verifies that
  cross-device access is denied.

Do not merge or deploy the remote-command prototype outside an isolated dev
environment until those gates are satisfied.
