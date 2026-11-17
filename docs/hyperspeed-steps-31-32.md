# HyperSpeed 2.0 — experimental UIA snapshot property cache (step 31)

**Status: draft canary; not enabled or released.** This patch is limited to
the existing allowlisted read-only `snapshot` action. The installed UDB
instance, owner permission, persistent-worker default and Cloudflare deployment
are unchanged.

## Mechanism

`computer_uia.ps1` now supports a private, per-request
`CacheRequest` for the seven fields already included in snapshots:
name, automation ID, control type, enabled, offscreen, password flag, and
bounding rectangle. It uses the .NET `TreeWalker` overloads that explicitly
accept a `CacheRequest` and `TreeScope.Element`. Pattern availability and
pattern-specific fields remain **live** reads; no mutation mode uses the cache.

The cache is enabled only in the UDB process when a trusted local test
environment sets `UDB_UIA_SNAPSHOT_CACHE=1`. It is **off by default**.
Each request re-obtains the HWND root and verifies PID before building a new
cache. No element, selector, password value, owner grant, or cache instance
survives the request. Existing 200-row and queue bounds remain.

## Verification completed

- Windows PowerShell parser accepted the modified helper.
- Both flag values rejected a zero HWND and impossible PID.
- `git diff --check` passed on the disposable worktree.
- Independent Microsoft .NET API references confirm cache-aware
  `TreeWalker.GetFirstChild` and `TreeWalker.GetNextSibling` overloads.

## Release blockers — step 32 not complete

Before activating in any real application, compare cache **on/off** for at
least 30 runs on owned Windows GUI fixtures with 50, 500 and 1,000 controls.
Compare every emitted field and password redaction, including ControlView to
RawView fallback, removed controls, recycled HWND/PID and mutable values.
Measure p50/p95/p99, CPU/RSS, truncation and error rate. Repeat with a
consented standard editor and browser; keep this flag off for users until
results establish correctness and improvement. Synthetic rejected-HWND
microbenchmarks do not count as real GUI acceptance.
