# UDB HyperSpeed 2.0 — foundation steps 01–10

This is a **new 100-step architectural speedup program**, separate from the
prior per-tool 100-step optimization inventory. It implements an opt-in,
payload-free measurement foundation; it **does not** make Chrome/desktop calls
faster on its own or prove any end-to-end 5–6 second objective.

## Delivered steps

| Step | Implementation | Acceptance |
| ---: | --- | --- |
| 01 | `tools/hyperspeed_benchmark.py` with a fixed, bounded fixture runner | Produces a JSON report; no real UI, terminal, downloads or network calls |
| 02 | `src/udb/hyperspeed_perf.py` request correlation using SHA-256 of JSON-RPC IDs | Cloud Agent / local MCP proxy correlate by RPC ID without logging IDs or arguments |
| 03 | Opt-in `queue`, `dispatch`, `execution`, `observation` and `response` spans | Local Cloud Agent, proxy, host, CDP and UIA instrumentation; semantics unchanged |
| 04 | Per-operation cold/warm tags and per-fixture first-iteration split | Cold means *first observed operation per process*, not a proven cold Chrome/Windows launch |
| 05 | `tools/hyperspeed_scenarios.json` has 30 representative shapes | 5 Chrome, 5 desktop, 5 files, 5 Office, 5 terminal, 5 transport/Fleet |
| 06 | Deterministic p50/p95/p99 interpolation and sample counts | Each scenario has cold/warm and overall timing distributions |
| 07 | CPU time, threads, optional observed RSS/child processes/read/write bytes and optional tracemalloc peak | Missing psutil fields are JSON `null`, not fabricated zeros |
| 08 | Longest dependency-chain critical-path analysis | Supports DAG branches and rejects missing/forward dependencies |
| 09 | Candidate detection for repeated polling, process startup and repeated trace operations | Flags are **investigation leads**, not proof of redundancy |
| 10 | Local static HTML dashboard, `--baseline` p95 regression checks, GitHub CI contracts | No flaky hard-coded wall-time gate on shared CI runners |

## Usage

From a checkout with `pip install -e ".[dev]"`:

```shell
python -m tools.hyperspeed_benchmark --iterations 50 --output hyperspeed-baseline.json
python -m tools.hyperspeed_dashboard --input hyperspeed-baseline.json --output hyperspeed-baseline.html
```

Optional memory-allocation observation:

```shell
python -m tools.hyperspeed_benchmark --iterations 50 --sample-allocations --output baseline-allocations.json
```

To compare two **same-mode** synthetic fixture runs (or, in future, real-workload
reports produced by an explicit authorized runner), first save the previous
JSON report. The alert threshold applies only when **both** contain at least
30 samples per scenario:

```shell
python -m tools.hyperspeed_benchmark --iterations 50 --baseline hyperspeed-baseline.json --regression-factor 1.30 --fail-on-regression --output hyperspeed-current.json
```

The report may say `mode: synthetic`: those timings measure in-memory
serialization, hashing and Python control flow. They **do not** measure
Chrome startup, UIA, full desktop screenshot, Cloudflare, ChatGPT inference,
real network RTT, or an installed Windows machine.

### Owner-only live local tracing

In the Windows terminal **before** starting the owner-authorized UDB process,
temporarily enable tracing for that process:

```powershell
$env:UDB_HYPERSPEED_TRACE = "1"
udb
```

Trace data is stored locally in `<UDB_HOME>/hyperspeed/traces.jsonl` when the
process profile allows creating the directory. Only operation identifiers
from a fixed allowlist, durations, hashed correlation IDs, pid, phase, startup
tag and success flags are recorded. No URLs, selectors, keystrokes, file
contents, RPC arguments, browser tokens or credentials are stored.

The Cloud Agent and MCP worker can correlate spans using the unchanged
JSON-RPC ID, but the host mailbox generates a separate command ID: **this
batch does not yet provide complete ChatGPT/Cloudflare-edge-to-HWND tracing**.
The hosted LLM reasoning time is outside UDB. Tracing is off by default and
is local-only; there is no telemetry upload to Cloudflare or any third party.

For local trace-stage summaries without exposing request payloads:

```shell
python -m tools.hyperspeed_benchmark --iterations 50 --trace "PATH_TO_TRACES_JSONL" --output with-trace.json
python -m tools.hyperspeed_dashboard --input with-trace.json --output with-trace.html
```

**Security and limitations:** do not share trace files externally without
review; even a hashed request ID is metadata. The static HTML dashboard embeds
only aggregated fixed-field telemetry. Runtime traces may add disk overhead and
should be disabled for uninstrumented baseline comparisons. Windows GUI, UIA,
Chrome, MISA, OAuth, owner grants and the live Cloudflare Worker are never
touched during CI fixture execution.

## CI and merge gate

The new `hyperspeed-baseline.yml` workflow tests Python 3.11 and 3.12 on
Ubuntu and Windows, using 30 synthetic scenarios, Ruff, a JSON schema/shape
contract, redaction tests and an HTML dashboard artifact. The existing
package/security/Windows EXE regressions also need to pass on the **same head
commit**. CI does not fail merely because a shared runner took longer; a real
p95 regression gate requires measured comparable baseline datasets and an
explicit `--baseline` invocation. The first owner-authorized Windows
measurement supplies that evidence, not this PR.
