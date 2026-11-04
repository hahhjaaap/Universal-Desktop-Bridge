# Changes merged into `main` after the UDB 0.11.0 baseline (2026-11-04)

These changes are **source changes**. The Python package still reports
`0.11.0`; a merged PR or successful Actions run is **not** evidence of a
published GitHub Release, deployed Cloudflare Worker, or updated local
installation. Check the release tag and actual installed executable separately.

- **Cloudflare-first owner setup ([PR #87](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/87)):** An existing Cloudflare pairing is recognized by `udb setup` and `udb setup --edit`. The GUI's primary Connect action targets Cloud Agent on paired profiles; `udb doctor --json` no longer treats a missing legacy Tunnel ID as an error in that case. Unpaired profiles retain explicit legacy Tunnel compatibility for rollback. No device grants, Worker deployment, OAuth or local owner privileges are changed by upgrading source.
- **Workspace browser ([PR #87](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/87)):** The optional Common Room example prefers Edge; if the Edge distribution is missing, it falls back to Chrome. Other browser launch failures are surfaced instead of being silently retried. The separate `browser_deps` install is still required for this Python example.
- **Common Room performance ([PR #88](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/88)):** Snapshot fitting uses logarithmic-sized JSON trials while retaining the previous 48,000-byte budget, preview ordering, truncation flags and cursor. The history-truncation lookup now occurs within the same SQLite read transaction. On one synthetic Windows workload (100 topics, 100 participants, 32 messages), p50 dropped from **124.174 ms to 16.493 ms**, p95 from **176.921 ms to 19.891 ms**; output remained 47,616 bytes. These are workload-specific measurements, not general UDB speedups. See [performance](performance.md).
- **Known limits:** The production Worker must be separately deployed and authorized for project reads; a working `/health` endpoint is not sufficient. The remote `udb:read` gateway does not enable writes/terminal/desktop actions. Windows packaged CLI cold-start was measured at **8.68–10.37 s** for `udb --version` on one machine; see [issue #89](https://github.com/hahhjaaap/Universal-Desktop-Bridge/issues/89).

For Cloudflare deployment and authenticated acceptance, see
[project-read runbook](cloudflare-project-read-acceptance.md) and
[owner pairing checklist](pairing-checklist-vi.md).

---

# UDB 0.11.0

Windows x64 standalone UDB. No separate Python, Node.js or Desktop Commander installation is required.

- Connection status separates a responding MCP transport, a live worker, resource pause and existing owner grants. In legacy Tunnel mode, `udb reconnect` requests a fresh tunnel for the running headless instance without changing grants or replaying tools; Cloudflare uses a separate Cloud Agent.
- Native `host_browser(action="batch")` runs up to 12 steps in one worker call with a stable `request_id`, a 20-second deadline, between-step cancellation and durable metadata receipts. It stops after failed or uncertain input; repeats return a cached result or receipt instead of resubmitting the page.
- `capture_start` maintains a bounded, in-memory screenshot cache with a best-effort target of 1 FPS. `host_screenshot(cached=true)` returns an existing fresh frame with its timestamp and age. Long actions, owner handoff and resource pauses can delay capture; stale/error frames are rejected.
- `udb status --watch --json` streams metadata-only headless status: heartbeat, uptime, connection, worker, active operation/progress, last operation and recent tool outcomes. No GUI is opened, and command/result contents are omitted.
- Windows headless status no longer mistakes a prior QtWidgets import for an owned GUI. Releases now wait for the full Linux/Windows CI matrix for the exact current main revision, then validate the standalone executable and installer before publishing. Existing versions are never overwritten.

Update from your own PowerShell terminal, outside UDB's running tool jobs:

```powershell
udb update --check
udb update
udb --version
udb status
```

For a first installation:

```powershell
irm https://github.com/hahhjaaap/Universal-Desktop-Bridge/releases/latest/download/install.ps1 | iex
```

On an unpaired legacy-Tunnel profile, the original Tunnel/account setup remains available. An already paired Cloudflare profile should use Cloud Agent and its separate device OAuth/grants; do not enter a workers.dev URL as a Tunnel ID. If ChatGPT exposes only the old tool catalog, verify the deployed Worker and refresh its MCP connection/catalog after updating. Updates preserve owner state; `udb rollback` restores the previous managed version. SHA-256 detects corruption; this edition is not Authenticode-signed. A successful CI run is separate from publication and installation on an owner's machine.
