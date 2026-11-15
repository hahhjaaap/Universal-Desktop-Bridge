# UDB 100-step roadmap — proposed optimizations 91–100

This is the **last implementation batch** in the proposed [100-step inventory PR #194](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/194). Historical steps 31–40 still require independent audit before claiming 100 merged/verified steps. These changes are isolated source changes; no Windows machine, credentials, deployment, or release was changed.

| Step | Tool / workflow | Narrow source improvement | Mandatory invariants |
| ---: | --- | --- | --- |
| 91 | `propose_media_download` | Reject non-HLS file suffix before loading/creating local allowed-host configuration | Owner approval, HTTPS same-host allowlist, signed request scope, FFmpeg sandbox, no overwrite |
| 92 | `system_process list` | Preflight pagination once, fold filter once; on Linux fetch sysconf conversion constants once per /proc pass | Per-process owner/critical/ancestor checks remain, no command-line disclosure |
| 93 | `system_process terminate` | Reject invalid/forged observation token before OS process handle or one-use authorization lookup | Fresh 60s observed pid+creation and same user; critical/owner/managed protections, single-use observation |
| 94 | `fleet_call` | Compact JSON encoding with finite numeric validation before loading device token or opening HTTPS | Explicit device required, no cross-device fallback/retries, bearer never exposed, TLS and response identity enforced |
| 95 | `fleet_list_computers` | Pre-sort immutable configured remotes once per FleetRouter instance | Always label remotes as *configured*, not online; return a fresh non-shared response |
| 96 | MCP proxy `initialize/tools_list` | Reuse compact serialized static JSON catalog for repeated tools/list while preserving detached caller objects and backend concurrency | Same native permission routes, immutable discovery per session, no mutation of returned schema leaking to subsequent callers |
| 97 | `tool_families.resolve_family` | Direct immutable name-to-family map instead of scanning unrelated groups | Existing action mappings only; legacy aliases, strict argument checks and permission backends unchanged |
| 98 | `udb setup` | Resolve the selected private enrollment relay exactly once per attended preflight | Owner approval, pairing, challenge, saved recovery state and explicit browser OAuth remain required |
| 99 | `udb tools` | New read-only `udb tools --names` prints deterministic name/count metadata without serializing the full schema; default `udb tools` retains full JSON | No new exposed Windows tools, grants or operations; catalog is still derived from native implementations |
| 100 | `udb update/rollback` | Skip PowerShell path and installer-script resolution when an update check confirms the installed managed release is current | Attended update guard, trusted release, atomic installer/signed rollback and no-upgrade behavior unchanged |

## Acceptance and limitations

- Regression suite `tests/core/test_tool_optimization_91_100.py` uses fake process enumeration, inert Fleet requests, synthetic setup, and patched installer binaries. It must **never kill a real process, download media, send a real network request, launch a browser, update UDB, or grant access**.
- Require Ruff, Linux/Windows Python 3.11 and 3.12 regression matrix, frozen Windows EXE, rollback and security tests, catalog parity and Cloudflare relay CI on the final PR head SHA.
- This batch reduces avoidable work; it does **not** demonstrate that 5–6 seconds is achieved end to end on any user's machine. Capture authorized p50/p95 benchmarks separately and only after merge/deploy.
- Never mark 91–100 *merged* or *shipped* while this PR is Draft. The earlier batches #199, #200, #202 and #203 and roadmap #194 must independently pass, reconcile conflicts and merge before the proposed 100-step cycle can be described as complete.
