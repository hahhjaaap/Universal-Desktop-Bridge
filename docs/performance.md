# Runtime costs and maintenance

> **Historical evidence:** Earlier run counts/benchmarks are not current UDB 0.12.0 CI results. The UDB Aura extension is retired from source. See [version/status](current-version.md).

## Automatic Windows Cloud RPC worker budget (staging candidate)

On Windows, UDB now selects a conservative Cloud RPC pool size **automatically**
when the Cloud Agent establishes its WebSocket, based on local total/available
physical RAM and logical CPU count. No Windows user must manually configure
worker count. The 4-core/4-thread Intel i5-6500 with 8 GiB RAM starts at
**two** workers when memory is available. The correct measured count may vary
with workloads; the values are guardrails, not claims of optimal p95.

The initial count caps both ThreadPoolExecutor capacity and
DeviceTaskScheduler admission. For each incoming RPC, the scheduler may sample
local free RAM at most once every five seconds and **reduce admission for new
requests** if pressure increases (e.g., below 2 GiB free RAM -> 1 worker).
It never cancels, interrupts or replays an in-flight RPC. Admission can return
up to the connection's original thread cap as RAM recovers, but cannot launch
more worker threads than were configured at startup. When admission is at
one or two workers, additional calls targeting an already-admitted physical
desktop or owned-browser lane return `DeviceBusy` **before dispatch** rather
than occupying a scarce executor thread while waiting on the same lane.
This leaves a slot for an independent read or a different resource lane.
One WebSocket reconnection re-evaluates startup capacity. No background
monitor, network telemetry or extra Cloudflare request is involved.

On non-Windows development platforms the original ten-worker default remains.
Set `UDB_CLOUD_WORKER_PROFILE=legacy` to restore ten-worker Windows admission
for controlled comparisons or rollback, or `UDB_CLOUD_WORKER_PROFILE=auto`
to explicitly choose resource-aware sizing on any platform. A manual integer
`UDB_CLOUD_MAX_RPC_WORKERS=1..10` takes precedence over automatic sizing and
disables RAM resampling for reproducible staging benchmarks. Invalid settings
fail at pool initialization. The existing grants, physical desktop lane,
owned-browser lane, side-effect restrictions and no-replay policy are unchanged.

This setting controls only Cloud RPC admission and its executor threads:
background tasks, browsers, retained stdio subprocesses and Office processes
have separate resource limits. A low worker budget can cause `DeviceBusy`
responses under load. Keep `UDB_CLOUD_PREWARM` off for initial 8 GiB trials.
If enabling status/catalog overlap from PR #289, test its two parallel reads
with the two-worker budget; do not assume this is faster on the target.

**Deployment gate:** validate on a *real* Windows i5-6500/8 GiB machine with
fixed read-only fixtures and identical Windows/Cloudflare builds: compare
manual budgets 1, 2 and 3 against Auto using 30–50 trials per mode. Record
p50/p95 end-to-end, peak process RAM, minimum free RAM, desktop responsiveness,
busy/error outcomes and unchanged permissions. Source tests do not prove a
specific 5–6 second target. Do not replace a production Cloud Agent merely
because this staging PR passes CI.

## Enrolled-owner status/catalog overlap (experimental opt-in)

`UDB_OWNER_STATUS_CATALOG_OVERLAP=true` in the **Cloudflare Worker
environment** enables concurrent relay of an authenticated enrolled-owner
`bridge_status` and a separate read-only `tools/list` count probe. The
primary authorized status request is still sent first. The diagnostic probe
gets a unique RPC ID, and failure to read the catalog cannot grant tools,
change permissions, replay a mutation or turn a failed status into success.

The feature is deliberately **off by default** because it can occupy two
device RPC worker slots for a single status request. On a customer i5-6500
with 8 GiB RAM and two Cloud RPC workers, enabling overlap can reduce
available capacity for independent operations, even if one status request
completes sooner. The original sequential path remains active when the
environment variable is absent.

Synthetic enrollment tests verify both disabled and opt-in behavior, with
the same catalog grants and live tool count. Evaluate on a real target with
the same transport/build: 30–50 trials, 1/2/3 worker settings, caller p50/p95,
peak RAM and busy/error rates before staging deployment. Do not claim any
latency improvement without real comparative measurements.

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
resource-constrained machines. When **both** `UDB_CLOUD_PREWARM=1` and
`UDB_SHARED_STATUS_PROXY=1` are explicitly enabled, the read-only warmup
ping now uses the same serial worker that handles later `bridge_status`
requests. Previously it warmed an unrelated thread-local worker, leaving
the first status RPC cold. Other RPCs continue using the original separate
worker lanes. No new permission, relay auth, or automatic retry is introduced.

It can improve the first call after a connection is established, but does
**not** reduce ChatGPT model generation time, guarantee 5–6 second answers
or remove network/UI latency from later calls. Run
`pytest -q tests/test_cloud_agent_prewarm.py tests/test_cloud_shared_status_proxy.py`
and measure cold and warm p50/p95 under the same device, request and network
conditions before claiming improvement.

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
