# UDB Cloudflare OAuth MCP gateway (read-only P0 foundation)

This is an **opt-in remote resource-server** layer for the private Cloudflare
relay. It does not implement an OAuth authorization server or perform a live
Cloudflare deployment. ChatGPT registration is **not** automatic.

## Security model

- The external OAuth 2.1 authorization server must implement authorization-code
  + PKCE (S256), registered client redirect URIs, metadata and Resource
  Indicators. It issues short-lived RS256 JWT access tokens with `iss`, `sub`,
  `aud` (the **exact** per-device MCP URL), `exp` and `scope: "udb:read"`.
- Configure `UDB_OAUTH_ISSUER` and `UDB_OAUTH_JWKS_URL` (HTTPS same host).
  Only signed RS256 tokens from these pinned keys are accepted; other algorithms,
  device tokens and the administrator key are **not** user identity.
- Configure `UDB_DEVICE_GRANTS` as JSON mapping device IDs to identity subjects
  to approved read-only tool names. Example with placeholder IDs:

```json
{
  "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": {
    "idp-user-123": ["bridge_status", "list_projects"]
  }
}
```

- The remote `udb:read` scope permits **only** these explicitly granted,
  registered-project read tools: `bridge_status`, `list_projects`, `list_files`,
  `read_file`, `search_files`, `check_python_syntax`. An authenticated owner must
  opt each tool into the device/subject `UDB_DEVICE_GRANTS` configuration;
  absent entries remain inaccessible. File access is scoped by the local UDB
  project registry and protected-path checks.
- Write, terminal, desktop, host-computer, legacy alias and approval tools
  remain unavailable through this read-only Cloudflare gateway. Do not bypass
  this restriction by adding them to the `udb:read` allowlist.
- All unconfigured or unauthorized requests are denied. Local UDB owner grants
  still apply independently. There is no anonymous mode or remote write access.
- A health check on Render confirms only the Cloudflare health endpoint, not
  a working device or ChatGPT OAuth exchange.

## Remote endpoint

`https://WORKER.workers.dev/v1/devices/DEVICE_ID/mcp`

OAuth discovery:

`https://WORKER.workers.dev/.well-known/oauth-protected-resource/v1/devices/DEVICE_ID/mcp`

A stateless subset of Streamable HTTP MCP (`2025-03-26`, `2025-06-18`,
`2025-11-25`) is supported using individual JSON POST requests. Only
`initialize`, `ping`, `notifications/initialized`, `tools/list` and
approved `tools/call` are implemented. GET streaming and session resumptions
are not supported. This gateway is **not** yet a general-purpose production
MCP endpoint.

## Release gate

Before exposing a real Windows PC, complete:
1. OAuth authorization server configuration with PKCE and correct resource
   audience; full ChatGPT callback/login test.
2. Real Windows ↔ Cloudflare Worker ↔ Durable Object tests on an isolated
   test device; verify token rotation, revocation, reconnect, rate limiting,
   and unknown-outcome safety.
3. Security audit for the admin-only prototype endpoints, browser/Origin
   handling, token/audience isolation and per-device permission controls.
4. CI matrix, release packaging, signed release if available and rollback test.

No secrets, API keys or actual user subjects belong in source control.

## Identity-provider interoperability

`UDB_OAUTH_ISSUER` must be copied **exactly** from the authorization server's
published `issuer` value, including any trailing slash. Token verification
compares that identifier byte-for-byte to the access token `iss` claim; it
never strips or adds a slash. The registered resource audience must be the
**full device MCP URL** (including `/v1/devices/DEVICE_ID/mcp`).

Do not enable the MCP connection by inventing an issuer or copying a Cloudflare
Access session token. Use an established OAuth 2.1 provider that can issue
RS256 JWT access tokens with the exact resource audience and `udb:read` scope,
with authorization-code PKCE and a ChatGPT-compatible client registration
mechanism. Provision the user-to-device grant locally from the authenticated
subject; never use the Cloudflare administrator key as a user token.

A separate, standards-compliant authorization server is still required; the
Worker does not issue OAuth tokens or provide a login UI.
