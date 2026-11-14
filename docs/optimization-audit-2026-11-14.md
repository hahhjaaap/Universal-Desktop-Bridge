# UDB whole-system optimization audit — 2026-11-14

This audit distinguishes **source-code optimization** from a verified
Windows installation, a released artifact and a deployed Cloudflare Worker.
No result below means the installed v0.12.0 EXE or owner's permissions changed.

## Scope, evidence and release constraints

- Project: `hahhjaaap/Universal-Desktop-Bridge`, branch `main`.
- Existing performance work already streams large file operations, avoids
  frequent empty-mailbox scans, limits concurrent read RPCs, skips unchanged
  completed-job details and performs bounded activity-reader polls. See
  [performance history](performance.md).
- The historical v0.11.0 packaged Windows CLI was measured at **8.68,
  10.37 and 9.49 seconds** for `udb --version`. Those numbers do *not*
  describe the current onedir candidate. Compare freshly built onefile and
  onedir with `tools/benchmark_startup.py` before changing release defaults.
- Published Windows v0.12.0 is not source `main`; every installed, compiled,
  and deployed revision must be verified independently.
- This work cannot benchmark the owner's Windows computer while it is offline.
  Synthetic measurements below are **not** claims about on-device performance.
- Release signing and `main` branch protection remain a separate safety gate;
  do not publish or automatically upgrade an owner's device solely because
  test cases pass.

## Changes in this optimization branch

| Area | Change | Expected impact | Invariant |
| --- | --- | --- | --- |
| Windows build and ZIP | Replace all whole-file `read_bytes()` SHA-256 calls in `build.py` with bounded `hashlib.file_digest` streams | Peak Python allocation no longer grows with large runtime DLL, EXE, standalone ZIP or wheel | Identical SHA-256 and manifest format; no new file path inclusion or owner-state reads |
| GUI idle refresh | Cache only the read-only `sandbox-setup-result.json` restart hint by file identity, size and timestamps; force reread every 5 seconds | Fewer repeated JSON file opens while a window is idle | Live permissions, approvals, Windows pause, Cloudflare status and jobs still refresh normally |
| Activity logging | Refuse to process metadata strings longer than 4 KiB through three regex substitutions and a full-string character filter | Bounds CPU work and intermediate memory when malformed/untrusted metadata is very large | Normal short metadata redaction, event ordering, outcomes and SQLite retention unchanged; oversize content replaced with neutral marker |
| Testing | Add large-file memory tests, idle-cache invalidation tests, malformed metadata tests and synthetic benchmark | Prevent regression of performance and data isolation | Performance ratios are informational, not machine-independent CI assertions |

Run the *read-only*, disposable-fixture benchmark locally from a development
checkout:

```powershell
python tools/benchmark_optimizations.py
python -m pytest -q tests/test_build_streaming.py tests/test_sandbox_refresh_cache.py tests/test_activity_bounded_metadata.py
```

The benchmark reports baseline vs streaming SHA-256 on a synthetic ~32 MiB
file, 400 repeated GUI hint reads and capped log metadata. It creates no
real UDB home, doesn't grant desktop access, doesn't open a browser and
doesn't contact Cloudflare. Always report measured numbers from the
specific computer instead of reusing historical measurements.

## Next workstreams after this safe PR

| Priority | Workstream | Required validation |
| --- | --- | --- |
| P0 | Protect `main`, required checks and reviews; prepare signed Windows publisher identity | Enforce release gate and negative tests, verify publisher and checksum on a clean Windows account |
| P1 | Compare onedir vs onefile cold start, ZIP size and disk usage | Repeated actual Windows PowerShell launches including first launch, warmed launch and antivirus-sensitive scenarios |
| P1 | Profile GUI timer at 1.5 s and SQL/query counts under real load | Project/approval/permission changes remain visible without stale state, GUI remains responsive |
| P1 | Instrument Cloud Agent connect-to-MCP latency and worker count | End-to-end authenticated read-only call, retry/backoff, concurrency, no replay of uncertain mutations |
| P2 | Profile managed process memory during browser/desktop + XLSX workflows | Per-subprocess RSS and task limits, browser isolation, no removed permission boundaries |
| P2 | Audit installer retained releases and optional components | Owner-state-preserving rollback from both layouts; no deletion of existing backups or private profiles |
| P2 | Update version/status documentation after a reviewed release | Cross-check installed EXE, Git commit, Worker deployment, app identity and actual ChatGPT tool call |

## Hard exclusions

Never optimize by removing grant validation, secret redaction, file-path
containment, approval checks, uncertain-mutation protection or rollback data.
Do not shrink a bundle by deleting files in the user's existing installation
or cache an authorization outcome across permission changes. No package
installer, release or Cloudflare deployment is performed by this audit.
