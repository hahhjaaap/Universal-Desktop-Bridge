# HyperSpeed 2.0 — experimental UIA snapshot cache (steps 31–32)

**Status: off-by-default experimental canary; not approved for rollout.** This patch is limited to
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

## Step 32: isolated native GUI parity gate (partial)

`tests/fixtures/uia_snapshot_form.ps1` creates its **own** Windows Forms
window with 50, 500, or 1,000 controls, including a password textbox.
It does not use a personal browser, personal desktop window, credentials,
clipboard, operating-system input injection, or UDB owner permissions.

`tools/compare_uia_snapshot_cache.py` submits the same bounded read-only
`snapshot` request to a fresh PowerShell helper with
`UDB_UIA_SNAPSHOT_CACHE=0` and `=1`. It compares **all emitted JSON
fields**, checks at least one accessible child exists and confirms that the
private password sentinel is absent. The existing 200-element output limit
still applies to fixtures with 500/1,000 controls; parity does not mean that
all 1,000 elements were returned.

The dedicated Windows GitHub Actions workflow runs **one cold comparison**
per fixture size and stores an isolated JSON report. This is a correctness
gate, **not** a validated acceleration claim. The optional standalone command
is:

```powershell
python tools/compare_uia_snapshot_cache.py --samples 30 --sizes 50 500 1000 --output reports/uia-parity-canary.json
```

Its timing includes fresh PowerShell process startup, so it does **not**
measure persistent-worker warm latency. The summary p50/p95/p99 from a single
CI sample are diagnostic only.

### Still required before cache activation

- Repeat stable/dynamic field parity across removed controls, recycled
  HWND/PID, mutable values, and ControlView-to-RawView fallback.
- Measure at least 30 **warm** runs, memory/CPU/truncation/error rates, and
  real end-to-end task latency on consented Windows editor and browser fixtures.
- Keep `UDB_UIA_SNAPSHOT_CACHE` and `UDB_UIA_PERSISTENT` **off by default**.
  No permission grant, Cloudflare deployment, or user installation changes
  are part of this work.
