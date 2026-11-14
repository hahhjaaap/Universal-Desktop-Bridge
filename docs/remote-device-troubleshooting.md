# Remote-device connection diagnostics

> **UDB 0.12.0 docs review (2026-11-13):** **Current UDB 0.12.0 source guidance.** Verify the installed executable, Cloudflare Worker, OAuth and owner grants separately; source changes do not update them. See [version/status](current-version.md).

UDB can accept requests from a connected ChatGPT workspace on a different device
or network while the original Windows computer is online and the owner-approved
agent remains running. **A locally running Cloud Agent does not prove that the current
ChatGPT plugin session can call its tools.**

## Identify the Cloudflare device connection (UDB v0.12.0+)

UDB v0.12.0 uses Cloudflare for remote MCP connections and removed the public
OpenAI Tunnel compatibility route. On the Windows computer, run `udb setup`
to pair the intended device if needed, then `udb start`. For an existing
`cloud-pairing.json`, run `udb setup` in the attended owner terminal to
inspect the existing pairing. The deprecated `--edit` flag does not provide
an independent Tunnel editing or recovery flow. Never paste a workers.dev
URL into an old Tunnel prompt. `udb mcp-config` inspects the per-device HTTPS
endpoint. If the opt-in account Fleet feature is enabled, use the shared
`/v1/account/mcp` URL printed by `udb setup` for the single ChatGPT connection.
Verify Worker deployment, Cloudflare Access OAuth, the subject/device grant,
Cloud Agent status and the actual MCP catalog independently. See
[Cloudflare project-read acceptance](cloudflare-project-read-acceptance.md).

Old Tunnel ID and `local_tunnel_ready` instructions apply only to earlier
UDB releases; do not use them to diagnose or configure UDB v0.12.0+. An
unpaired new installation requires explicit Cloudflare pairing, not a
fallback to an unauthenticated transport.

## When the plugin displays Connected but calls fail

1. On the original Windows computer, run `udb status --json` and
   `udb doctor --json` in a local terminal. Neither command creates grants.
2. Check `manager_running`, Cloud Agent state, `connection_configuration`,
   and the `chatgpt_session` doctor check separately. Pairing metadata is not
   evidence of successful OAuth or a live remote call. Old `local_tunnel`
   checks are not relevant to the v0.12.0 Cloudflare transport.
3. From the remote device, call `bridge_status` in ChatGPT. When it succeeds,
   verify the reported version and project scope before attempting other tools.
4. If a plugin reports **Connected** but tool calls return
   `Session terminated`, reconnect/refresh that ChatGPT plugin session and
   retry the **read-only** `bridge_status` check. If it still fails, inspect
   `udb doctor --json` and redacted `udb logs --details` on the original
   computer. Do not share keys or raw private logs in chat.
5. Inspect **Cloud Agent**, Worker deployment, Access/OAuth grants and the
   current plugin catalog separately. A Worker `/health` 200, a Cloud Agent
   process indicator or a Connected plugin badge alone does not prove an
   authenticated end-to-end tool call.

## When two computers use the same ChatGPT account

The ChatGPT **account**, an MCP **plugin connection**, a Cloudflare **device
ID**, and a Windows **host machine** are different identities. A green local UDB status on
two computers does **not** establish that one ChatGPT connection can
distinguish them.

Use an **explicit device-based** isolation test (never automatic host routing):

1. On each computer, run `udb status --json` and `udb doctor --json` locally;
   confirm the pairing and intended device ID. Do not copy device credentials.
2. In legacy per-device mode, each device has its own
   `/v1/devices/DEVICE_ID/mcp` URL. In Fleet mode, use the one shared
   `/v1/account/mcp` URL in ChatGPT and call `list_devices` to inspect the
   authenticated owner's devices. Do not create a separate plugin for each PC.
3. For every machine operation, pass the exact `device_id` returned by
   `list_devices`. Display names are hints only. Check `connection` first;
   an offline or unverified device must produce an explicit error, never
   automatic failover to another host.
4. Call read-only `bridge_status` and, when separately granted, scoped
   `list_projects` or `read_file` with the selected `device_id`. Verify the
   returned project and content instead of inferring identity from a display
   name or from the ChatGPT Connected badge.
5. If one host responds and another does not, diagnose that host's Cloud Agent,
   Worker, OAuth and local grant separately. Revoke or disable only the
   intended test device after the owner approves the action.

Do not reuse device credentials between machines or disable endpoint
authentication to make a test pass. PR #183 adds an opt-in Fleet candidate,
but it is not deployed to production or the current staging Worker; verify
the installed build and deployed flags before assuming one-plugin routing.

A computer that is powered off, asleep or disconnected from the Internet
cannot serve remote requests. Network access from a second device is a
separate test from accessing UDB across two devices on the same network.

**Safety:** A failed call can have an unknown outcome. Never blindly replay
file writes, shell commands, browser actions, downloads or other mutations.
Inspect state before repeating them. UDB never uses a remote ChatGPT request
to enable computer-access permissions; the owner must activate any such grant
attended on the original computer.

This guide covers diagnosis, not a guarantee of automatic remote recovery.
