# Read-only UIA event observer

The UIA event observer is an optional acceleration for the existing read-only
`wait_for` operation. It is not enabled by default and does not change the
permissions or semantics of any input action.

## Enable only for an owner-approved Windows canary

The observer is effective only when the persistent UIA worker is enabled and
the separate event flag is explicitly set:

```powershell
$env:UDB_UIA_PERSISTENT = "1"
$env:UDB_UIA_EVENT_OBSERVER = "1"
```

Without both flags, `wait_for` uses the existing polling path. A one-shot
PowerShell invocation never enables event subscriptions, even if the event
flag is present.

## Behavior and cleanup

- `exists` and `absent` subscribe to bounded UIA structure-change events.
- `enabled` subscribes only to the `IsEnabled` property-change event.
- Every event wake is followed by a fresh query; unrelated events do not
  satisfy the selector.
- The helper reopens the HWND and revalidates PID plus UIA runtime identity
  during the wait. A changed or recycled window identity fails closed.
- Event waits use the same caller deadline and recheck at most every 100 ms,
  so missed notifications and unsupported event providers fall back to polling
  without extending the deadline.
- Handlers are removed in `finally` after success, timeout or an exception.
  If the owner grant is revoked during a persistent wait, the Python caller
  stops the worker process; closing or crashing the worker also releases its
  process-scoped UIA subscriptions.
- A cancelled or timed-out worker is never replayed. Inspect the target before
  submitting a new mutation.

## Validation

The Windows-only `tools.compare_uia_event_observer` canary uses a test-owned
WinForms form. It triggers a child-control replacement, verifies event and
polling modes both observe the new AutomationId, checks that the event handler
signals, and verifies cleanup after a timed-out wait. It does not attach to
Chrome, Excel, MISA, or any user-owned application.

This is a correctness and observer-lifecycle check, not a performance claim.
The event flag remains off by default until owner-attended real-application
canaries and CPU/RSS measurements justify a separate rollout decision.
