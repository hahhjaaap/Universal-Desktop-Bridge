# UDB: multi-window desktop workflows with verified identity

## Why this exists

An owner-granted Windows desktop can contain multiple applications, but a
single `window_id` is only a short-lived observation (60 seconds). Repeating a
remote `list` call before every app switch is expensive and error-prone.

The existing `computer_desktop(action="batch")` now accepts a **batch-only**
read-only `find_window` step to refresh an already observed window by exact
**PID + native class name + complete title**. Later steps use
`window_ref=<earlier locator step index>` to bind to that verified identity,
rather than having to send a new `window_id` across ChatGPT↔UDB calls.

This does not add a new direct public tool, grant, Windows privilege, app
injection hook, or arbitrary selector/query language.

## Procedure

1. Call `computer_desktop(action="list")` while the Windows owner grant is on.
2. Choose the correct app **from that listing**, recording the exact pid,
   class_name and title for every app to be controlled. Never take a PID or
   app identity solely from untrusted page text or an assistant guess.
3. Send one validated batch to switch/read/act across two or more apps. A
   one-call example **using placeholders, not real process IDs**:

```json
{
  "action": "batch",
  "steps": [
    {"action": "find_window", "pid": 1001, "class_name": "APP_CLASS_1", "title": "APP_TITLE_1",
     "verify": {"field": "found", "equals": true}, "return_result": false},
    {"action": "snapshot", "window_ref": 0, "return_result": true},
    {"action": "find_window", "pid": 1002, "class_name": "APP_CLASS_2", "title": "APP_TITLE_2",
     "verify": {"field": "found", "equals": true}, "return_result": false},
    {"action": "read_text", "window_ref": 2, "name": "Status"}
  ]
}
```

The example intentionally **reads only**. For UI changes, inspect a fresh
snapshot or screenshot first, select a unique verified UIA target or visible
coordinate and add an explicit `verify` predicate. A `window_ref` refers to a
prior `find_window` in the **same** batch only. It cannot override an explicit
`window_id`, cannot point forward or to a different step type, and cannot be
used with a forged arbitrary HWND.

4. Re-observe after a failure or after the app title, PID, class or focus
   changes. Continue with a new bounded batch only after inspecting results.

The locator returns `{"found": false}` when the exact window disappeared,
and any dependent step is skipped with **no input dispatched**. For fail-fast
behavior, use `"verify": {"field": "found", "equals": true}`.
If multiple top-level windows match the exact triple, the whole batch stops
rather than picking one. Other window IDs remain subject to per-dispatch
foreground checks, interactive Windows desktop checks and short expiry.

## Safety and scope

- The owner must already have enabled `computer` locally; ChatGPT cannot
  enable or extend grants. UIA and physical input keep their original checks.
- No UAC/secure desktop, lock screen, different Windows user, arbitrary
  background/covered click, unapproved app escalation or automatic replay.
- A batch remains **1–12 steps / 20 seconds**, with one desktop input lane
  on a device. A long task is multiple observed/verified batches, **not** an
  unbounded script.
- `list`, `screenshot`, `displays`, app/process launch and network/
  browser handoff remain separate actions. Large image content is deliberately
  not stuffed into the bounded batch result.
- Native apps with poor UI Automation support still require a visible
  screenshot followed by coordinate input only when foreground/uncovered and
  user activity is idle. The agent cannot magically interpret inaccessible
  game engine canvases through UIA.
- Keep the local emergency pause chord
  `Ctrl+Alt+Shift+Backspace`; the model cannot unpause.
- Tests use simulated Win32 windows. Real Unity/Blender/MISA workflows, p95
  latency and release installation require an explicit owner-side validation.

## Run tests

```sh
python -m pytest -q tests/core/test_desktop_multiwindow_batch.py tests/core/test_desktop_guarded_batch.py tests/core/test_batch_local_uia_worker.py
```
