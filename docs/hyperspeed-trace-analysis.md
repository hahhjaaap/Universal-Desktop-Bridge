# UDB end-to-end stage trace analysis

This report helps locate time spent in the local UDB portion of a ChatGPT →
Cloudflare → Windows request. It groups the existing opt-in, payload-free
trace events by operation/phase and correlates the same JSON-RPC call across
local UDB processes.

## Collect a trace

Tracing is disabled by default. On an owner-approved staging Windows profile,
set the environment flag in the process environment used to launch UDB and
its Cloud Agent:

```powershell
$env:UDB_HYPERSPEED_TRACE = "1"
udb
```

Run a controlled set of at least 30–50 **read-only** staging requests with
unique request IDs. Keep the device, network, build and request shape fixed.
Do not enable tracing on a production profile unless the owner explicitly
approves it.

The trace is written to:

```text
<udb-state-directory>/hyperspeed/traces.jsonl
```

The raw local trace contains fixed operation/phase names, timings, process
IDs and a truncated SHA-256 correlation token. It does not contain tool
arguments, selectors, window titles, text, URLs, file paths or credentials.
Keep the raw trace local; share the generated report instead.

## Generate the report

From a developer checkout:

```powershell
python tools/hyperspeed_trace_report.py "<udb-state-directory>/hyperspeed/traces.jsonl" --output udb-stage-report.json
```

The report contains:
- p50/p95/p99 and cold/warm timings for each fixed `operation/phase`;
- success/failure counts for each stage;
- correlated RPC span envelopes across local UDB processes;
- the union of instrumented intervals and the unattributed gap inside each
  observed RPC envelope;
- a bounded, chronological list of pseudonymous RPC indexes with per-operation
  durations. Raw trace IDs and process IDs are omitted.

The union avoids double-counting overlapping spans. `summed_stage_ms` is
provided for diagnostics only and can exceed the observed RPC envelope when
nested spans overlap. `unattributed_gap_ms` is time between instrumented
spans; it can include uninstrumented waits and is not automatically network
latency.

## Interpretation boundary

This report covers only instrumented processes on the same Windows host.
It does **not** include ChatGPT model generation, the user's client-side
waiting time, or uninstrumented Cloudflare edge time. The RPC envelope is
therefore not a substitute for a monotonic caller-side measurement from tool
submission to tool result.

Compare the stage report with a separate caller-observed p50/p95/p99 for the
same read-only workload. If caller time is high while local UDB stages are
small, investigate the uninstrumented transport/client boundary rather than
optimizing UIA code based on guesswork. Do not claim the 5–6 second target
until the exact end-to-end workload meets it with permission, navigation and
no-replay parity.

The report is diagnostic and has no speed threshold. It does not enable
persistent UIA, change grants, send input, deploy a Worker or modify an
installed UDB profile.
