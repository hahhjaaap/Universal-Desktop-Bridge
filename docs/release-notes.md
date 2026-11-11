# UDB 0.12.0 — Cloudflare-only connection and UDB Live

Windows x64 standalone release.

## What's new

- **Cloudflare is the remote MCP transport.** A paired Windows Cloud Agent opens an outbound WebSocket to the configured Cloudflare Worker. ChatGPT and other supported clients connect to the device-specific HTTPS MCP endpoint using Streamable HTTP.
- **Cloudflare pairing flow.** Run `udb setup` in an attended Windows terminal to pair a device, then `udb start` to run its Cloud Agent. `udb mcp-config` prints the paired HTTPS endpoint. An unpaired profile intentionally exports an empty MCP server list.
- **UDB Live in the terminal and GUI.** Run `udb live` to follow activity in the terminal, or `udb live --gui` (also available with **Ctrl+Alt+U**) to open the read-only activity window. In UDB Manager, **Ctrl+Shift+L** opens the Live tab.
- **Readable tool-call lifecycle.** Live records `CALLING`, `PASS`, `ERROR`, and `RUNNING`, with tool labels, call IDs, and durations. The activity view reads bounded metadata and does not display tool inputs, outputs, or private file contents.
- **Local owner controls remain local.** Windows continues to hold device credentials, browser sessions, and explicit owner approvals. Installing or updating UDB does not grant computer access or new device permissions.

## Important migration note

This release changes the connection architecture from UDB 0.11.0:

- The public local stdio MCP command and legacy OpenAI Tunnel compatibility path are removed from the new Cloudflare-only build. Existing integrations that depended on either transport must be reconfigured for the paired Cloudflare HTTPS endpoint.
- Pair the Windows device using `udb setup`, then copy the endpoint printed by `udb mcp-config` into the MCP client configuration. Each device uses its own device ID and grants.
- The Cloudflare Worker deployment, Access/OAuth configuration, device grants, and ChatGPT MCP connection must be configured and verified separately. A running local Cloud Agent alone does not prove that ChatGPT has discovered the tools.
- Use `udb doctor --json` and `udb status --json` to diagnose the Windows installation and pairing. Do not paste access tokens, private keys, or owner data into issue reports.

## Install or update

For a first installation, run this in your own PowerShell terminal:

```powershell
irm https://github.com/hahhjaaap/Universal-Desktop-Bridge/releases/latest/download/install.ps1 | iex
```

For an existing managed installation, run the update outside UDB's running tool jobs:

```powershell
udb update --check
udb update
udb --version
udb status --json
udb live
```

Managed updates preserve owner state. `udb rollback` restores the previous managed release.

## Build and security

- The release is built from the exact `main` revision after the complete Windows/Linux CI matrix passes.
- The standalone Windows ZIP, installer script, and `SHA256SUMS` are validated before publication; the published installer is then tested through HTTPS on a disposable Windows runner.
- SHA-256 detects accidental corruption, not publisher identity. This build is not Authenticode-signed.
