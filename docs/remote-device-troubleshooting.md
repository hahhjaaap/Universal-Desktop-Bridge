# Remote-device connection diagnostics

UDB can accept requests from a connected ChatGPT workspace on a different device
or network while the original Windows computer is online and the owner-approved
agent remains running. **A locally ready tunnel does not prove that the current
ChatGPT plugin session can call its tools.**

## First identify your transport

On a Windows profile with an existing `cloud-pairing.json`, Cloudflare is
the preferred connection path. Start Cloud Agent explicitly in UDB Manager;
`udb setup --edit` is not a place to paste a workers.dev URL. Verify the
Worker deployment, Cloudflare Access OAuth, per-device subject grant, live
Cloud Agent and the exact MCP plugin catalog separately. See
[Cloudflare project-read acceptance](cloudflare-project-read-acceptance.md).

The Tunnel ID and `local_tunnel_ready` checks below apply only to the
**legacy OpenAI Tunnel** compatibility mode on unpaired profiles. A local
Tunnel failure does not diagnose an existing Cloudflare pairing, and Cloud
Agent process readiness does not prove an authenticated ChatGPT tool call.

## When the plugin displays Connected but calls fail

1. On the original Windows computer, run `udb status --json` and
   `udb doctor --json` in a local terminal. Neither command creates grants.
2. Check `manager_running`, `local_tunnel_ready`, and the
   `chatgpt_session` doctor check separately. A successful local health probe
   cannot validate the ChatGPT session from another device.
3. From the remote device, call `bridge_status` in ChatGPT. When it succeeds,
   verify the reported version and project scope before attempting other tools.
4. If a plugin reports **Connected** but tool calls return
   `Session terminated`, reconnect/refresh that ChatGPT plugin session and
   retry the **read-only** `bridge_status` check. If it still fails, inspect
   `udb doctor --json` and redacted `udb logs --details` on the original
   computer. Do not share keys or raw private logs in chat.
5. If the local tunnel is unavailable, troubleshoot the Windows agent and
   network first. A plugin UI badge alone is not sufficient evidence of
   connectivity.

## When two computers use the same ChatGPT account

The ChatGPT **account**, an MCP **plugin connection**, a **Tunnel ID**, and a
Windows **host machine** are different identities. A green local UDB status on
two computers does **not** establish that one ChatGPT connection can
distinguish them.

For the currently published UDB release, prefer this isolation test:

1. On each PC, run `udb status --json` and `udb doctor --json` locally.
   Confirm each machine's agent and local tunnel readiness separately.
2. In the attended `udb setup --edit` connection settings, verify that each
   intended machine has its **own** Tunnel ID. Do not paste any Tunnel ID or
   API key into a public issue or chat.
3. Create two distinguishable MCP connections in the appropriate ChatGPT
   workspace, each pointing to its matching tunnel. Enable the intended
   connection in the new conversation before discovery.
4. Call `bridge_status` as a read-only test on *each connection*.
   Confirm machine identity separately in local redacted UDB activity logs;
   the current `bridge_status` payload does not guarantee a unique public
   machine ID.
5. If only PC A responds while PC B says `Session terminated`, check PC B's
   tunnel, plugin binding and discovery. The symptom alone does **not**
   establish a specific collision in OpenAI's infrastructure.

Do not run two UDB installations with the same Tunnel ID and assume that ChatGPT
will load-balance, switch or choose the intended machine. Do not turn off
endpoint authentication or share credentials as a workaround.

For a single plugin selecting machines on different Wi-Fi networks, see
[experimental Multi-PC work in draft PR #34](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/34).
Its Tailscale-based router is **not** in the published installer or current
`main`; use only after separate Windows and two-host verification. Tailscale
networking alone does not implement MCP routing.

A computer that is powered off, asleep or disconnected from the Internet
cannot serve remote requests. Network access from a second device is a
separate test from accessing UDB across two devices on the same network.

**Safety:** A failed call can have an unknown outcome. Never blindly replay
file writes, shell commands, browser actions, downloads or other mutations.
Inspect state before repeating them. UDB never uses a remote ChatGPT request
to enable computer-access permissions; the owner must activate any such grant
attended on the original computer.

This guide covers diagnosis, not a guarantee of automatic remote recovery.
