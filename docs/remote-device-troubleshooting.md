# UDB Cloudflare-only: remote-device troubleshooting

A cloud device is connected through **ChatGPT → Cloudflare Access Managed OAuth →
Worker/Durable Object → outbound Cloud Agent → internal MCP stdio**.
There is no OpenAI Tunnel ID, runtime OpenAI key, local MCP connector or
Tailscale hub in the supported remote connection.

## Diagnosis from the original Windows PC

1. Use `udb status --json` and `udb doctor --json` to identify the
   local owner-scoped manager and Cloud Agent process. A running process is
   **not** evidence that its WebSocket is connected.
2. Check that `cloud-pairing.json` exists and points to the intended
   Cloudflare Worker/device ID. The device token belongs in Windows
   Credential Manager and must **never** be pasted into ChatGPT.
3. If pairing has been revoked, the owner must create a fresh invitation
   and re-pair in an attended local terminal. Never grant admin RPC just
   to bypass a broken OAuth login.
4. Verify Cloudflare Access protects **only** the device MCP path.
   Do not protect the Cloud Agent's `/connect` WebSocket with interactive
   Access: it authenticates with its own random device token.
5. Test `bridge_status` from the `udb-cloudflare` plugin. If tool
   discovery succeeds but the call fails, distinguish cloud/agent
   availability from ChatGPT session authentication.
6. If several PCs are paired, give each its own device ID, owner policy
   and MCP URL. A ChatGPT account does not route automatically between PCs.

The public Cloudflare MCP endpoint exposes only `bridge_status` and
`list_projects` under approved grants. Its connection is separate from
any broader **local** UDB computer-access grant. A running Cloud Agent
does not authorize shell commands or remote writes by itself.

For unknown tool outcomes, do **not** blindly retry mutations. Inspect
the application state first. Collect redacted logs only; redact relay
tokens, file contents and private user data before reporting a bug.
