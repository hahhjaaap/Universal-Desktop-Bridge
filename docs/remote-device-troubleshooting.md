# Remote-device connection diagnostics

UDB can accept requests from a connected ChatGPT workspace on a different device
or network while the original Windows computer is online and the owner-approved
agent remains running. **A locally running Cloud Agent does not prove that the current
ChatGPT plugin session can call its tools.**

## Identify the Cloudflare device connection (UDB v0.12.0+)

UDB v0.12.0 uses Cloudflare for remote MCP connections and removed the public
OpenAI Tunnel compatibility route. On the Windows computer, run `udb setup`
to pair the intended device if needed, then `udb start`. For an existing
`cloud-pairing.json`, use `udb setup --edit` only for attended configuration;
do not paste a workers.dev URL into an old Tunnel prompt. Use `udb mcp-config`
to inspect the device-specific HTTPS MCP endpoint. Verify Worker deployment,
Cloudflare Access OAuth, the subject/device grant, Cloud Agent status and the
actual MCP catalog independently. See
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

Use an **explicit device-based** isolation test (no automatic host routing):

1. On each computer, run `udb status --json` and `udb doctor --json`
   locally, and confirm the Cloudflare pairing and intended device.
2. On paired hosts, check each **distinct MCP device URL**
   (`/v1/devices/DEVICE_ID/mcp`) and the approved subject/device tool grant.
   Start only the intended Cloud Agent. Do not expose device credentials in
   chat. Pair unpaired computers separately rather than reusing a device ID.
3. In ChatGPT, connect to the **specific** MCP endpoint and refresh its tool
   catalog; a Connected badge does not prove tool invocation.
4. Call read-only `bridge_status` and (when separately granted) scoped
   `list_projects` or `read_file` to distinguish the machines. Verify the
   actual selected project and read result rather than assuming a unique
   public machine identifier from `bridge_status`.
5. If one host responds and another does not, diagnose the failed host's
   Cloud Agent/Worker/OAuth/grant/plugin path in order. Do not infer a routing
   collision without evidence.

Do not reuse device credentials between machines or disable endpoint
authentication to make a test pass. **The current source
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
