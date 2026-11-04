# UDB 0.11.0

Windows x64 standalone UDB. No separate Python, Node.js or Desktop Commander installation is required.

- Connection status separates a responding MCP transport, a live worker, resource pause and existing owner grants. `udb reconnect` requests a fresh Cloud Agent session for the running headless instance without changing grants or replaying tools.
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

The existing Cloudflare Access/pairing setup and local owner grants remain required. If ChatGPT exposes only the old tool catalog, refresh its MCP connection/catalog after updating. Updates preserve owner state; `udb rollback` restores the previous managed version. SHA-256 detects corruption; this edition is not Authenticode-signed. A successful CI run is separate from publication and installation on an owner's machine.
