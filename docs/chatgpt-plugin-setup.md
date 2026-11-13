# ChatGPT UDB Desktop Bridge setup

> **Docs reviewed 2026-11-13 — UDB 0.12.0:** **Staging/opt-in scope.** Features and grants described below are not enabled for arbitrary devices and are not proof of a live ChatGPT connection. Check [current-version.md](current-version.md) and the installed `udb --version` before using commands.

## Staging example — obtain your own current device endpoint

The ChatGPT plugin package is maintained in `integrations/chatgpt-plugin/`. The following staging configuration is an example, not a universal current endpoint. Obtain the real device-scoped URL with `udb mcp-config` after attended pairing and confirm the actual Worker/Access configuration separately.

- **Plugin name:** UDB Desktop Bridge
- **MCP transport:** Streamable HTTP
- **MCP endpoint:** the reviewed, device-specific URL from `udb mcp-config`
- **OAuth:** Cloudflare Access Managed OAuth with Dynamic Client Registration
- **Requested resource scope:** `udb:read`
- **Environment:** staging only

The package contains no client secret, access token, refresh token, pairing secret, or Cloudflare credential. The endpoint is device-scoped and remains protected by Cloudflare Access. Production is not configured in this package.

## Cloudflare Access callback allowlist

The staging Access application `UDB Staging MCP` allows both official ChatGPT callback patterns:

- `https://chatgpt.com/connector/oauth/*`
- `https://chatgpt.com/connector_platform_oauth_redirect`

The stable callback was added after a real DCR request returned HTTP 400 with `invalid_client_metadata` because it was not on the allowlist. The existing callback-ID pattern remains enabled. The Access policy, device-scoped domains, and 10-minute token lifetime were preserved.

## Owner connection and acceptance

1. Open the private **UDB Desktop Bridge** plugin in ChatGPT.
2. Select Connect and complete the Cloudflare Access sign-in and OAuth consent.
3. Confirm that the MCP server exposes `tools/list` after authentication.
4. Call `bridge_status` if exposed and confirm that the active Windows device is online.
5. Read one synthetic fixture file that the owner has explicitly allowed; compare its SHA-256 with the known expected hash.
6. Verify wrong-device, revoked-session, and unauthorized-write denials.

Public metadata checks, DCR registration, and an HTTP 302 to the Access login page are pre-authentication checks only. They do not prove a user has authenticated or that a Windows tool call works. Do not report end-to-end connectivity as complete until the owner completes the steps above.

## Safe diagnostic

Run the read-only preflight from a machine with Python and network access:

```powershell
python tools/check_chatgpt_oauth.py --relay https://YOUR-REVIEWED-STAGING-RELAY.workers.dev --device-id YOUR-DEVICE-ID
```

To test DCR callback compatibility explicitly, add:

```powershell
--register-client --callback https://chatgpt.com/connector_platform_oauth_redirect
```

The optional DCR check creates one disposable public OAuth client, starts but does not complete login, requests no token, and executes no MCP tool. Use it sparingly. Never disable Cloudflare Access, weaken resource binding, expose a bearer token, or create an unauthenticated fallback to make the connection appear healthy.
