# HyperSpeed 2.0: Windows UI Automation worker (21–30)

**Status: opt-in canary implementation.** No change is made to the owner's
computer, Windows grant, Cloudflare configuration, or desktop permissions by
this PR. It is not a demonstration of 5–6-second end-to-end latency.

## Implemented work

| Roadmap | Improvement | Proof / boundary |
|---:|---|---|
| 21 | One persistent Windows PowerShell STA process, reusing the UIAutomationClient and UIAutomationTypes assemblies | Worker only starts after the existing current-user computer authorization and interactive desktop checks |
| 22 | Single-command request/reply protocol over child-process inherited stdin/stdout pipes | No local TCP listener, no named pipe exposed to other accounts, no arbitrary PowerShell/JS commands |
| 23 | Worker is reused for sequential UIA requests; process stops on close or after 90 seconds idle | One worker per Desktop instance; no background agent escalation |
| 24 | Standard client-side UIA proxies are registered once per process | Current UIA properties and patterns are still read live for each request; further CacheRequest tuning is deferred |
| 25 | Every command acquires a fresh root AutomationElement and verifies observed HWND and PID | No UIA target element, password value, selector, cached owner permission or HWND is persisted across calls |
| 26 | Fast failure on malformed, oversized, failed or late replies | Timeout/unknown outcome never automatically retries an input mutation |
| 27 | Retains the preexisting strict allowlisted UIA modes and exact-match control lookup | No arbitrary selectors, commands or relaxed error checking |
| 28 | Original one-shot PowerShell mode is left intact for the default path | Controlled opt-in via environment flag; no automatic fallback on ambiguous results |
| 29 | Single in-process lock, idle generation-guard, bounded buffers and checked worker lifecycle | Concurrent calls cannot interleave IPC or confuse response messages |
| 30 | Synthetic and Windows PowerShell regression tests | A Windows-only test submits two invalid HWND requests without observing real user windows |

### Running the canary

To opt in locally **on a trusted Windows test machine that already has the
correct grant**:

```powershell
$env:UDB_UIA_PERSISTENT = "1"
udb
```

The flag is read by the UDB process. It is **off by default** and must not be
set remotely or without the owner's explicit local authorization.

The UDB-owned headless worker starts lazily on the first legitimate UI
Automation call; subsequent UIA calls reuse it. The process has no network
port and receives only fixed JSON UIA requests from the host service.
PowerShell is invoked with `-NoProfile -NonInteractive -Sta -File`; it does
not inherit broad auto-execution of downloaded code or arguments.

The original legacy mode remains available by omitting the flag. If an
in-flight worker crashes or does not respond, UDB stops it and reports
an uncertain outcome. It **does not** run the same action again with a fresh
PowerShell process.

### Remaining 21–30 engineering before general release

The persistent process is the necessary foundation for further latency work.
The following previously proposed features are **not yet claimed as shipped**:
native UIA `CacheRequest` for larger trees, event-based change notifications,
compiled locator caches with validated invalidation, optimized composite
actions, and cross-application p50/p95 benchmarks on a consented Windows GUI.

These optimizations should only be enabled after their own focused Windows
regressions prove that they preserve exact selectors, password suppression,
foreground rules and owner control. The existing batch/checks and one-shot
receipt protections remain unchanged.

## CI acceptance

- `tests/core/test_persistent_uia.py` tests IPC bounds, worker reuse,
  unexpected EOF, malformed JSON, idempotent close, owner grant preflight,
  no replay, and a Windows-specific two-command invalid-HWND fixture.
- Full CI matrix, Windows EXE, PowerShell host validation, Ruff and catalog
  parity must pass on the final PR commit.
- Rollout and real performance metrics are explicitly separate from merge.
  Compare at least 30 warm actions per app on an approved Windows test
  instance and record p50/p95, CPU, RSS, success and perceived UI correctness.

### Warm-path microbenchmark (Windows CI/test machine only)

After installing the development dependencies in an isolated Windows checkout,
run `python tools/benchmark_uia_process.py --samples 30`. This explicitly
sends a rejected zero-HWND/PID request, compares one-shot PowerShell startup
with the existing worker's first and warm roundtrips, and reports p50/p95.
No real window, input, credentials or owner permission is accessed. It does
**not** exercise UIA element trees or measure end-to-end ChatGPT latency.

The warm path now avoids a second `AutomationElement.FromHandle` lookup
when the standard Win32 client-side providers were already registered. Every
request still obtains a fresh root and checks its observed PID. The first
registration still reacquires and re-verifies the root after provider setup.
