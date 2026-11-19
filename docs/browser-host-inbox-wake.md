# Faster owned-browser command admission on Windows

## The bottleneck

The UDB host service formerly scanned its inbox and then waited for a
backoff interval of up to 250 ms while idle. When a browser RPC wrote a new
command during that interval, the file could sit untouched until the next
poll. The local RPC caller also polls for the reply at 40 ms intervals.

The new Windows-only `InboxWake` uses the OS
`FindFirstChangeNotificationW` / `WaitForSingleObject` /
`FindNextChangeNotification` directory change APIs. A new mailbox
filename or atomic rename wakes the worker immediately, avoiding the idle
wait *when the notification path is available*.

This is a **host-to-worker** optimization, distinct from network RTT and
Chrome CDP/rendering. It does not reduce the number of remote tool calls.

## Correctness and security

- The watcher receives only a filename-change signal. It does not read
  payloads, mutate files, grant access or consume results.
- The existing `pending_inbox_commands`, atomic claim, session checks,
  resource governor, permissions, expiry checks, reply validation and
  no-replay policy remain authoritative.
- The watcher is armed **before** the first inbox scan. A filename change
  between scanning and waiting remains signalled until the OS notification
  is rearmed. The worker always performs a complete scan on the next loop.
- Signals can be coalesced or spurious; the full directory scan remains the
  source of truth. Watcher init/rearm/wait failures close the handle and
  fall back to the previous polling behavior.
- Idle periodic timeout remains capped at 250 ms, ensuring maintenance,
  capture ticks and stop requests keep their old bounded cadence.
- No third-party watcher package, OS service, global event name, driver,
  Cloudflare setting, local agent grant, personal browser or user cursor
  is introduced. Non-Windows systems retain polling.

## Evidence

A simulated Win32 watcher test checks immediate notification and rearming,
timeout/failure fallback, and close idempotence. Windows CI also checks a
real directory notification after an atomic rename and a notification queued
before the first wait.

The configured baseline worst-case idle scan delay was 250 ms. With working
native notifications, file creation can wake the worker before that delay.
This is **not** a measured p50/p95 improvement in end-to-end UDB browser
operations; the device browser grant is not enabled in the observed local
machine, so no private-browser latency test has been run there.

Before claiming an end-to-end speedup, collect at least 30 owner-approved
read-only requests and compare `host.mailbox`, `host.dispatch` and edge RTT
p50/p95 against a build without the watcher, on the same machine.
