# Runtime costs and maintenance

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
Browser-extension mark/unmark and navigation decorations run in order per
tab, preventing a late decoration from restoring an already removed badge.

Regression tests check memory bounds, copy conflicts, oversized/growing files,
idle polling counts, SQLite reader/writer contention, GUI state updates and
extension operation ordering. Time measurements are informational; CI does
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
