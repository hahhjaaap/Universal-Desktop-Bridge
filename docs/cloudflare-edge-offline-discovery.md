# Staging-only authenticated MCP discovery while Windows is offline

This proposal addresses one failure mode of a direct ChatGPT → UDB connector:
in the original Cloudflare Worker, both `initialize` and `tools/list`
required the Windows Cloud Agent to be connected. When the laptop was offline,
ChatGPT might fail connector discovery before showing the available tools.

## Opt-in

On a **reviewed, independently paired staging Worker only**, set
`UDB_EDGE_READ_CATALOG=true` to enable discovery at the Worker. The default
behavior remains unchanged and the flag must not be enabled in production
before security review and an authenticated end-to-end staging pilot.

For this mode to activate, Cloudflare Access identity must already be
validated and the subject must have a valid per-device grant. The code
supports the six known **read-only** tool signatures from
`src/udb/server.py`. It never advertises privileged host tools, does not
create permissions or change project policies, and explicitly disables the
feature when the caller has an owner-tool grant.

### What works when Windows is disconnected

- A correctly authorized `initialize` and `tools/list` can complete at
  the Cloudflare gateway. This proves **only** the gateway/Access identity
  and discovery, not a live Windows connection.
- The tool catalog is restricted to the specific caller's existing
  read-only `UDB_DEVICE_GRANTS` / tenant policy.
- Calling `bridge_status` still attempts an RPC to the actual Windows
  device. Only an explicit Durable Object `device_offline` response
  becomes a user-visible **MCP tool error** with
  `windows_device_verified=false`; it is not a fake success.
- Any other read, timeout, reconnect race or uncertain outcome continues to
  fail closed. An RPC is never replayed automatically.

### When Windows reconnects

All `tools/call` requests still go through the original Durable Object
and Cloud Agent, and Windows enforces existing local scope. The Cloud Agent
already initializes each fresh stdio proxy before forwarding the first
ordinary call, so moving edge discovery does not bypass local tool
initialization.

## Required test and deployment evidence

1. CI: Node Cloudflare unit matrix, authorization denial tests and Windows
   runtime regression pass.
2. Deploy the **exact reviewed** Worker revision to a separately provisioned
   staging name, retaining the existing Durable Object binding and secrets.
3. With the Windows staging device offline, sign into the correct staging
   UDB MCP connection in ChatGPT and check that an allowed tool catalog
   appears. A call to `bridge_status` must be an explicit offline error.
4. Start a real Windows staging Cloud Agent with its own pairing and
   authenticate the same ChatGPT connection. `bridge_status` must now
   return a live device report; read a synthetic file and verify SHA-256.
5. Revoke the grant, use another identity and device, and disconnect during
   a call. Revocation and unknown-outcome denials must remain effective.

**Limitations:** This patch does not turn on or repair the Windows Cloud
Agent, complete the user's Cloudflare Access sign-in, deploy any Worker,
or make ChatGPT inherently capable of connecting to an offline computer.
A fixed plugin-side MCP tool catalog may need refresh before newly granted
tools are visible. Any claim of actual connection must be backed by a
successful authenticated `bridge_status` from the real Windows machine.
