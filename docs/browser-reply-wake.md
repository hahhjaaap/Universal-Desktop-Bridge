# Reply-side notification for owned browser RPCs

The GUI host worker has an optional Windows directory notification for
incoming commands (PR #242). The calling UDB proxy historically waited
for the corresponding reply by checking the filesystem every 40 ms. An
already-written response could therefore incur almost one additional
40 ms poll interval before it was observed.

This change uses the same `InboxWake` filename-notification primitive
for the **replies** directory. It is armed **before** the command is
published into the inbox, preventing the lost-reply race where the worker
is so fast that the reply appears before the caller subscribes.

The existing bounded 40 ms wait also remains. When the OS notification
API is unavailable, returns an error, or misses a wakeup, the original
poll cadence and 27-second outer deadline apply.

## Security/correctness invariants

- A wakeup is only a hint to recheck the **exact, unpredictable request ID**.
  Notifications do not imply success and never carry any untrusted reply data.
- The existing file path link check, JSON size and shape checks, worker error
  propagation, reply deletion, owner grant checks, session checks, command
  expiry and no-write-replay semantics remain unchanged.
- All handles close even if enqueue, reply parsing, permission checks, or
  worker status fail.
- No additional dependencies, OS services/drivers, shared named event, user
  desktop access, Cloudflare configuration, browser profiles or grants.
  Other operating systems keep the same 40 ms fallback wait.

## Measurement scope

The baseline is a **configured polling interval**, not a measured 40 ms
loss on every call. Windows directory notifications can wake before
the next poll, but the syscall and new watcher setup also incur overhead.
End-to-end p50/p95 must be measured on an owner-approved browser session
before attributing a real-world speedup.

Unit tests verify watcher registration before enqueue, no lost/duplicate
writes from fake notifications, propagation of worker errors, and closure
on publish failure. Native Windows notification behavior is exercised by
the shared `InboxWake` tests.
