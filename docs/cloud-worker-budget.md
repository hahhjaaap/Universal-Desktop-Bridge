# Bounded Cloud RPC workers (experimental, default unchanged)

The installed onefile UDB v0.13.0 on the owner's Windows PC spawns
independent, short-lived PyInstaller extraction trees for local MCP
stdio proxies. The baseline observed 10 `udb.exe` processes and five live
`_MEI*` extraction roots during an active connection. Each of those
roots held approximately 340 MiB of extracted files. This is an
**observational process and disk footprint**, not evidence of a memory
leak or a guaranteed performance improvement.

## Opt-in limit

The Cloud Agent supports `UDB_CLOUD_MAX_RPC_WORKERS` to bound **admitted
Cloud RPCs and executor threads together** on one authenticated device
WebSocket. It defaults to **10**, the current historical behavior.
For staging only, set an ASCII integer from **1 through 10**, e.g.:

```powershell
$env:UDB_CLOUD_MAX_RPC_WORKERS = '3'
# Launch only a disposable, owner-approved staging Cloud Agent, not an
# additional process against the actively paired production identity.
```

Invalid values fail at Cloud Agent pool creation rather than silently
increasing capacity. The existing resource scheduler's exclusive mutation,
physical desktop lane, owned browser lane, grant checks, deadline handling,
unknown-outcome poisoning, and cleanup are unchanged. Requests beyond the
limit receive `DeviceBusy` **before dispatch**, rather than being accepted
into an unbounded executor queue. No retries, privilege grants, or OS
input commands are introduced.

A lower limit trades parallel throughput for fewer simultaneously active
RPC threads. It does **not** enforce a strict total process count: one
connection may retain per-thread proxies alongside separate desktop and
opt-in shared-status proxies. Some proxies persist until WebSocket close.
Even when the status-proxy opt-in is enabled, the two options are independent.

## Performance validation needed before enabling

1. Use the same **isolated** Windows staging device/identity, source build
   and workload. Do not run two agents against one live pairing.
2. Compare default 10 against 2, 3, 4 and 6 on at least 30 serial
   read-only `bridge_status` RPCs and 8-way concurrent calls, with a
   warm-up period and separate fresh WebSockets.
3. Record p50/p95 end-to-end latency, total and peak `udb.exe` count,
   `_MEI` extraction directories, working set/private bytes, blocked
   requests, RSS/commit, and end-to-end reply ID matching. Compare both
   first-connection and warmed call behavior; do not infer performance
   from source-only tests.
4. Verify that an admitted mutation finishes or reports its true unknown
   outcome without replay; `DeviceBusy` means no dispatch. Test
   desktop/browser isolated lanes and explicit WebSocket shutdown.
5. Run the existing Windows **onefile versus onedir** benchmark as the
   more direct way to avoid repeated onefile extraction. Keep onefile as
   rollback until the Windows install/rollback acceptance matrix passes.

Do not deploy this setting or change `UDB_BUILD_LAYOUT` on the owner's
production machine based on unit tests alone. An owner-visible, reviewed
staging rollout and failure recovery are required.
