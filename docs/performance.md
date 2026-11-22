# Runtime costs and maintenance

> **Historical evidence:** Earlier run counts/benchmarks are not current UDB 0.12.0 CI results. The UDB Aura extension is retired from source. See [version/status](current-version.md).

## Low-memory Cloud RPC admission profile (opt-in)

For 4-core/4-thread Intel i5-6500 Windows customers with approximately 8 GiB
RAM, start with **two** concurrent Cloud RPC workers rather than assuming the
10-worker ceiling is desirable. The correct count is workload-dependent:
compare 1, 2 and 3 read-only workers on an actual target PC before calling
any setting optimal. CPU and RAM alone cannot predict network, Windows
Defender, Excel/browser memory, or downstream UDB worker costs.

Set `UDB_CLOUD_WORKER_PROFILE=auto` in the **Cloud Agent process
environment** to choose a bounded value once per WebSocket connection.
The Windows-only startup snapshot uses total/available physical memory
and logical CPU count; missing/invalid measurements fall back conservatively
to at most two workers. The policy starts 8 GiB hosts at two workers and
reduces to one if available RAM is below 2 GiB. It reserves one logical CPU
for other work, caps 16 GiB hosts at four workers, and never exceeds the
existing hard ceiling of ten. The chosen count bounds **both** ThreadPoolExecutor
threads and DeviceTaskScheduler admission.

An explicit `UDB_CLOUD_MAX_RPC_WORKERS=1..10` always takes precedence over
the auto profile, allowing controlled 1/2/3-worker benchmark runs. Without
either setting, the original ten-worker upper bound remains unchanged.
Invalid profile values fail during initialization rather than falling back
silently. This controls Cloud RPC dispatch only; it is **not** a global memory
limit on subprocesses, background jobs, browser tabs or Excel workloads,
nor does it alter owner permissions or the exclusive desktop lane.

On an 8 GiB device, keep `UDB_CLOUD_PREWARM` disabled initially; optionally
test `UDB_SHARED_STATUS_PROXY=1` when repeated `bridge_status` requests
would otherwise launch separate stdio workers. Shared status trades some
status-request concurrency for lower process startup/memory pressure.
Do not enable all optimizations at once before testing separately.

**Acceptance on an actual customer-equivalent 8 GiB Windows machine:** test
1/2/3 RPC budgets on identical read-only fixtures with the same build and
Cloudflare path, 30–50 measured trials for each, randomized or interleaved.
Compare verified p50/p95, RSS/commit peak, available RAM minimum, CPU load,
rejected/busy responses and failures. Choose the fastest **safe** count that
leaves the desktop responsive and avoids paging, not the largest count.
No live 8 GiB result or 5–6 second speed claim is implied by the unit tests.

## Optional Cloud Agent prewarm (experimental)

On `HAHHJAAAP` (2026-11-15), an isolated MCP sidecar took **2,960 ms**
to initialize but only **20 ms, 3 ms, 3 ms and 3 ms** for successive
read-only `computer_desktop(control_status)` calls within the same worker.
Three equivalent calls over the connected ChatGPT/UDB path took
**4,645 ms, 3,983 ms and 5,601 ms**. These measurements include
different transport and runtime layers; they do not prove that the
difference is entirely due to cold initialization.

The owner may opt in to warming one local stdio proxy after a private
Cloudflare WebSocket connects by setting `UDB_CLOUD_PREWARM=1` in the
**Cloud Agent process environment** before starting it. The warmup uses
only a read-only MCP `ping`; it never opens a browser, sends text,
performs a remote tool action or changes grants. Other parallel workers
remain lazy. If the ping fails, that connection fails closed and retries
after the existing reconnect backoff, rather than sending a mutation
through an unverified child.

The flag is **off by default** to avoid idle process and RAM overhead on
resource-constrained machines. It can improve the first call after a
connection is established, but does **not** reduce ChatGPT model
generation time, guarantee 5–6 second answers or remove network/UI
latency from later calls. Measure cold and warm p50/p95 under the
same device, request and network conditions before claiming improvement.

## Current optimization sweep (2026-11-14)

The latest audit separates source optimizations from benchmarked Windows
releases and Cloudflare deployments. It covers memory-bounded release hashing,
GUI idle reads, oversized activity metadata and a prioritized full-system
performance plan. See [optimization audit](optimization-audit-2026-11-14.md).

Run `python tools/benchmark_optimizations.py` for synthetic, disposable-fixture
measurements. The original source observations below are historical and must
not be treated as measurements of an installed UDB v0.12.0 executable.

Run from a developer checkout installed with `python -m pip install -e ".[office,dev]"`:

```sh
python tools/benchmark_runtime.py
```

The benchmark uses temporary local files, disposable state and a simulated
clock for idle loops. It starts no browser, desktop session or user process
and creates no computer-access grant. File timings include Python tracing
overhead and depend on the machine and filesystem cache.

The following measurements compare `4ed9340` with the runtime optimization
changes on the same Linux cloud environment. The input is an 8 MiB file;
the range-read response contains 200 bytes. Peak allocations are Python
`tracemalloc` values, rather than total process memory.

| Operation | Before | After |
| --- | ---: | ---: |
| SHA-256 peak bytes | 8,393,446 | about 530,000 |
| Range-read peak bytes | 8,393,834 | about 531,000 |
| Copy peak bytes | 39,148,224 | about 536,000 |
| Mailbox polls in 9 simulated idle seconds | 151 | 38 |
| Reply-directory scans in those 9 seconds | 151 | 2 |
| Maximum idle mailbox wait | 60 ms | 250 ms |

Hashing and reads stream in 256 KiB blocks. A range read computes the hash
over the entire bounded stream while retaining only the requested range.
Copies stream into a temporary file and verify its source hash before
publication. Browser downloads already have a bounded byte buffer and now
use the same binary commit path directly, avoiding a base64 round trip.
Existing overwrite checks, recovery copies and owner permission checks still
apply. Moves recheck the source hash before deletion.

The idle host worker makes fewer directory scans while allowing up to 250 ms
to notice a newly queued command. Active work returns to a shorter polling
interval. Stop events wake the worker immediately; command expiry and the
120-second stale-reply threshold remain unchanged. Reply cleanup runs every
five seconds, so a stale reply can remain for roughly 125 seconds.

GUI polling avoids a write transaction when approvals need no expiry. Its
trees update when grants, protected paths or request payloads change and
preserve the current selection. Refresh failures in one section do not stop
the other sections from updating. Large job logs use one bounded tail read.

Regression tests check memory bounds, copy conflicts, oversized/growing files,
idle polling counts, SQLite reader/writer contention, GUI state updates and
owner-grant cursor handling. Time measurements are informational; CI does
not enforce machine-dependent speed ratios.

## MCP startup and idle mailbox optimization (experimental PR)

Run the additional synthetic benchmark from a development checkout:

```sh
python tools/benchmark_hotpaths.py --samples 20 --backend-delay-ms 15
```

The unified MCP proxy can issue `initialize` and `tools/list` requests to its
**independent** core and companion subprocesses concurrently. It still
combines their results in the previous deterministic order, checks for
missing/duplicate tool definitions, and caches a defensive copy of the public
catalog. Only these two read/setup RPCs are parallelized; permission checks,
side-effecting tool calls, and recovery semantics are unchanged. Startup
latency depends on real backend work, not only these RPCs.

The idle host mailbox uses one `os.listdir` to obtain candidate command names
instead of a `pathlib.Path.glob` iterator, then retains the same sorted order
and individual path validation/atomic claim before execution. This primarily
reduces scan overhead when the inbox is empty; it does **not** change its
maximum 250 ms idle polling interval, command expiry, or owner permissions.

The benchmark reports median latency for two synthetic delayed backends and
per-scan time on an empty disposable directory. It is diagnostic, not a CI
speed threshold: Windows filesystems, antivirus, actual MCP tunnel latency,
and real application workloads must be measured separately. CI also continues
to run the existing stdio RPC benchmark and full regression suite.

## Per-request MCP response bookkeeping

Each UDB subprocess RPC has one pending response slot. The transport now uses
`queue.SimpleQueue` instead of the heavier bounded `queue.Queue(maxsize=1)`
for this **single-delivery** slot. The reader removes the slot from its map
before delivering a response, and both timeout and write failure still remove
it. This changes neither the number of concurrent RPCs nor error/permission
handling. The consolidated public tool names are also cached as a frozenset
when discovery completes, avoiding a temporary set for virtual aliases such
as `file_transfer` on each call.

`tools/benchmark_hotpaths.py` now measures the two Python queue types
side-by-side, in addition to the existing synthetic startup and inbox scans.
The waiter microbenchmark excludes JSON parsing, network, subprocess I/O and
backend processing. **Do not extrapolate queue-only speedups to UDB tool
latency.** CI performance figures remain informational rather than speed
thresholds; integration and permission regressions are required to pass.

## Completed-job GUI refresh

The native Qt manager updates the job inventory on each refresh, but the
selected job details no longer trigger additional database/log/script reads
when the job has reached a terminal state **and** its inventory signature is
unchanged. Running, reviewing and stopping jobs still refresh their details,
and selecting another job invokes the existing selection handler. A status
transition updates the inventory signature and causes a detail refresh.

This reduces idle disk reads and unnecessary text processing when the owner
leaves the manager open on an already-completed task. It does not change job
execution or log retention. The regression suite checks that terminal jobs
skip repeated detail IO while live jobs are not throttled.

## Common Room snapshot fitting (merged PR #88, source 2026-11-04)

The optional `examples/chatgpt-workspace/fast_live.py` mirror publishes a
bounded preview (`latest.json`, at most 48,000 UTF-8 bytes; maximum 16
messages plus truncated topic/participant metadata). On large metadata, the
old trimming loop repeatedly serialized the entire snapshot after removing
**one** record at a time. The replacement searches the largest fitting
participant/topic/message count with binary search. It retains the original
priority of removal, ordering, preview flags and message cursor. The
`history_truncated` lookup is now inside the same SQLite read transaction as
the selected rows to avoid contradictory metadata when writers commit.

An isolated local benchmark on one Windows machine, with **100 topics, 100
participants and 32 synthetic messages** (large goals/roles), measured:

| Metric | Before | After |
| --- | ---: | ---: |
| Forced-snapshot time, p50 | 124.174 ms | 16.493 ms |
| Forced-snapshot time, p95 | 176.921 ms | 19.891 ms |
| JSON serializations per forced snapshot | 177 | 18 |
| Output snapshot size | 47,616 bytes | 47,616 bytes |
| Truncation/cursor/output | Baseline | Identical |

The p50 difference is about **87%** (approximately **7.5× faster**) on
this workload, **not** for all UDB operations or idle GUI updates. A
repeated patched-source run measured p50 **17.905 ms** and p95 **23.820
ms**. The benchmark created a temporary SQLite database, did not read the
owner's workspace, and timed forced rebuilds rather than ordinary no-change
polls. CI does not enforce a hardware-dependent latency threshold.

Reproducible semantic tests from a source checkout:

```sh
python -m pytest -q tests/test_workspace_mirror_budget.py
python -B examples/chatgpt-workspace/fast_live.py selftest
```

The test suite compares 50 randomized Unicode snapshots byte-for-byte
against the previous linear fitting algorithm and verifies that the history
query executes inside the read transaction. Do not substitute a green test
for an end-to-end ChatGPT/Cloudflare deployment check.

## Windows packaged CLI cold start (open issue #89)

A separate Windows 0.11.0 managed EXE check timed three `udb --version`
calls at **8.68, 10.37 and 9.49 seconds**. This is a measured usability
bottleneck, not a proven root cause. Profiling the shell launcher,
executable unpacking, imports, antivirus and process startup is required
before selecting a distribution change. See [issue #89](https://github.com/hahhjaaap/Universal-Desktop-Bridge/issues/89).
No onedir migration or sub-2-second startup is claimed yet.

## Owner-scoped source search prefilter (2026-11-10)

The project source-search operation now skips unrelated regular file names
before invoking the expensive owner/project-scoped path check.
Every directory considered for traversal and every candidate source file still
passes through existing policy validation, including symlink/junction,
protected roots and hard-link checks. Directory scan counts, match limits,
deadlines and the result shape remain unchanged.

Run the repeatable synthetic fixture benchmark (no owner files or grants):

```sh
python tools/benchmark_source_search.py --samples 3
```

On one Windows machine, 290 synthetic entries (250 `.bin`, 20 `.md`,
20 `.py`) with a `*.py` query and 20 matches produced:

| Metric | Before | After |
| --- | ---: | ---: |
| Median search duration | 553.15 ms | 69.18 ms |
| Per-file scoped-path calls | 292 | 22 |
| Entries scanned | 290 | 290 |
| Matching paths | 20 | 20 |

This is approximately an 8x speedup only for this mixed-extension,
synthetic workload. Source-heavy folders, network drives, warm file-system
caches and other machines can behave differently; the benchmark is
informational, not a CI speed threshold. Directory and permission regression
tests remain the acceptance gate.
