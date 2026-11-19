# Opt-in shared worker for read-only bridge status

On Windows, each `LocalProxy` may start a short process tree for the
one-file UDB executable. A burst of parallel `bridge_status` calls can
therefore leave several long-lived local stdio workers in the same WebSocket
session. Other tools need independent workers for parallelism, or the
connection-scoped desktop worker to retain window observations.

## Scope

This experimental optimization is **off by default**. Enable
`UDB_SHARED_STATUS_PROXY=1` only in an owner-approved staging Cloud Agent
process, not in the running production bridge without validation.

When enabled, only `tools/call` with the exact tool name `bridge_status`
uses one connection-scoped local stdio proxy. Its calls are serialized under
a lock, so responses cannot be interleaved. The normal authorization path,
MCP request envelopes, deadlines, failure poisoning, and teardown are
unchanged. `host_status`, `computer_status`, all file/process operations,
UI/desktop, browser, and mutations continue on the existing lanes. In
particular, this change **does not** share or retire the desktop proxy.

The shared proxy is created lazily, registered for the existing pool close
routine, and retained until the corresponding authenticated device WebSocket
disconnects. It does not enable idle-time retirement.

## Tradeoffs and tests

This can reduce resident worker process trees when many independent
`bridge_status` requests overlap. It also serializes those calls, which
could increase p95 at high status concurrency or if a status RPC stalls.
A failing/uncertain proxy poisons the full pool; no RPC is retried.

Dependency-injected tests require eight overlapping status requests to
create just one LocalProxy, preserve unique request IDs, restrict sharing
to bridge_status (not host_status), close all workers, and fail closed
without retrying after a poisoned result. Other pool tests still verify
ten parallel reads on the default path.

The initial owner-computer baseline at 21:38 on 2026-11-19 was 10
`udb.exe` processes and ~313.5 MiB working set; a later set of two
additional proxy trees coincided with 16 processes and ~502.7 MiB. This
observational baseline does **not** establish a leak or the savings from
this patch. Nor does it prove any end-to-end speed improvement.

Before enabling in production, compare on the **same staging machine**
at least 30 read-only status calls with option off/on, both serially
and with eight concurrent callers. Record working set, process count,
p50/p95, error rate, RPC identity integrity, and recovery after
WebSocket teardown. Never compare against synthetic timing alone.
