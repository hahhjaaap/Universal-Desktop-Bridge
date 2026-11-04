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
2. Check `manager_running`, the **selected transport** and the
   `chatgpt_session` doctor check separately. On paired Cloudflare devices,
   `local_tunnel` and `tunnel_component` are not applicable; a valid
   `connection_configuration` only confirms pairing metadata, not OAuth
   or the live connection. A local health probe cannot validate the ChatGPT
   session from another device.
3. From the remote device, call `bridge_status` in ChatGPT. When it succeeds,
   verify the reported version and project scope before attempting other tools.
4. If a plugin reports **Connected** but tool calls return
   `Session terminated`, reconnect/refresh that ChatGPT plugin session and
   retry the **read-only** `bridge_status` check. If it still fails, inspect
   `udb doctor --json` and redacted `udb logs --details` on the original
   computer. Do not share keys or raw private logs in chat.
5. If Cloudflare is selected, inspect **Cloud Agent**, Worker deployment,
   Access/OAuth grants and the current plugin catalog separately. A Worker
   `/health` 200 or a Cloud Agent running indicator is insufficient. In
   legacy Tunnel mode, troubleshoot its distinct local Tunnel state and
   network. A plugin badge alone never proves end-to-end connectivity.

## When two computers use the same ChatGPT account

The ChatGPT **account**, an MCP **plugin connection**, a **Tunnel ID**, and a
Windows **host machine** are different identities. A green local UDB status on
two computers does **not** establish that one ChatGPT connection can
distinguish them.

Use an **explicit device-based** isolation test (no automatic host routing):

1. On each computer, run `udb status --json` and `udb doctor --json`
   locally, and confirm its configured transport and paired device.
2. On Cloudflare-paired hosts, check the **distinct MCP device URL**
   (`/v1/devices/DEVICE_ID/mcp`) and the approved subject/device tool grant.
   Start only the intended Cloud Agent. Do not expose device credentials in
   chat. For unpaired legacy Tunnel hosts, use separate Tunnel IDs and
   distinguishable connections.
3. In ChatGPT, connect to the **specific** MCP endpoint and refresh its tool
   catalog; a Connected badge does not prove tool invocation.
4. Call read-only `bridge_status` and (when separately granted) scoped
   `list_projects` or `read_file` to distinguish the machines. Verify the
   actual selected project and read result rather than assuming a unique
   public machine identifier from `bridge_status`.
5. If one host responds and another does not, diagnose the failed host's
   Cloud Agent/Worker/OAuth/grant/plugin path (or legacy Tunnel binding) in
   order. Do not infer a routing collision without evidence.

Do not reuse device credentials or legacy Tunnel IDs between machines, or
disable endpoint authentication to make a test pass. **The current source
does not guarantee a production one-plugin Multi-PC router.**

A computer that is powered off, asleep or disconnected from the Internet
cannot serve remote requests. Network access from a second device is a
separate test from accessing UDB across two devices on the same network.

**Safety:** A failed call can have an unknown outcome. Never blindly replay
file writes, shell commands, browser actions, downloads or other mutations.
Inspect state before repeating them. UDB never uses a remote ChatGPT request
to enable computer-access permissions; the owner must activate any such grant
attended on the original computer.

This guide covers diagnosis, not a guarantee of automatic remote recovery.
