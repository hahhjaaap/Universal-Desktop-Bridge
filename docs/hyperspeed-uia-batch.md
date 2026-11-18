# HyperSpeed — UI Automation reuse inside a desktop batch

## Optimization scope

A single `computer_desktop(action="batch")` containing **at least two**
Windows UI Automation actions now reuses **one private PowerShell STA worker**
for the duration of that batch. It closes the helper on normal completion or
failure. UIA actions outside such batches retain the existing one-shot default.

This addresses repeated PowerShell startup/COM initialization **inside a
single cloud round trip**. Existing limits remain 12 prevalidated steps and
20 seconds; per-step local desktop grant, pause/yield, UIA HWND/PID identity,
foreground and password protections are unchanged. There is no TCP listener,
remote script executor, privilege widening, new OS command or automatic
replay after an uncertain mutation.

The separate cross-request `UDB_UIA_PERSISTENT=1` opt-in is unchanged and
remains off by default. A single UIA action never opts into batch-local reuse.

The optional `UDB_HYPERSPEED_TRACE=1` existing tracing system also measures
`desktop.batch/execution` without storing selectors, passwords, text, device
identifiers or window titles. This separates local batch time from the remote
Cloudflare and ChatGPT/tool routing overhead.

## Windows acceptance canary

```powershell
python -m tools.compare_uia_batch_worker --samples 3 --controls 50
```

This uses only a test-owned WinForms window, checks exact parity of **all
snapshot fields**, requires visible fixture controls and checks that a
password sentinel is absent. No physical input, user window, account,
credential, clipboard or owner grant is accessed.

Observed on a Windows GitHub Actions runner (2026-11-18, 50 synthetic
controls, three independent snapshots per mode):

| Component | Time |
| --- | ---: |
| One-shot UIA process, median of three | 1,042.37 ms |
| Batch worker UIA, median of warm requests 2–3 | 571.23 ms |
| Batch worker cold first request | 988.45 ms |
| Full cloud round trip to installed UDB 0.13.0 | ~5–8 seconds in a separate baseline |

This suggests **~1.8× lower UIA component time after warmup**, not 1.8×
faster ChatGPT answers or guaranteed sub-6-second full workflows. Three
measurements are only a diagnostic canary; do not extrapolate to dynamic
desktop apps, Unity, MISA, browsers, production p95 or multi-window input.

The CI checks read-only live parity and offline no-replay/cleanup contracts
on Windows/Linux. A staged owner-granted real-app Windows test and monitored
release remain prerequisites for an end-user rollout.
