# Cloudflare Access Managed OAuth (UDB read-only experimental MCP)

## Scope and safety

Optional alternative to a manually integrated RS256 JWT OAuth identity provider.
Use **Cloudflare Access Managed OAuth**, configured as a **hostname/path scoped
Access MCP application** for a single device MCP endpoint. Do not select Worker-
level Access on `udb-private-relay`: Cloudflare documents that Worker-level
Access blocks WebSocket upgrades, which would disconnect the UDB Cloud Agent.

The code remains **off by default**. The Windows device is not remotely
controllable through the MCP gateway. It exposes only owner-granted read tools
(`bridge_status`, `list_projects`).

## Required authenticated identity boundary

- The MCP endpoint is `/v1/devices/DEVICE_ID/mcp` on the existing Worker.
- Set up a path-scoped Cloudflare Access application on that URL only.
- Configure an Access policy that allows **only the intended owner identity**.
- Enable **Managed OAuth** under that application's Advanced settings.
- ChatGPT or another MCP client must perform Access OAuth login and consent.
- Access must pass an authenticated `ctx.access` to the Worker.
- The Worker requires `UDB_AUTH_MODE=cloudflare-access` and
  `UDB_ACCESS_AUD=YOUR_ACCESS_APPLICATION_AUDIENCE_TAG`.
  `UDB_ACCESS_AUD` MUST equal the application audience on `ctx.access.aud`.
- Set `UDB_DEVICE_GRANTS` as a JSON object mapping device IDs to authenticated
  Access identity **email addresses** and approved read-only tool names:

```json
{
  "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": {
    "owner@example.test": ["bridge_status"]
  }
}
```

Use the actual device ID and Access sign-in identity only in private local
configuration. Never commit secrets, personal identity grants or access tokens.

## Required deployment sequence

1. Deploy the code with mode disabled; verify existing WSS Cloud Agent remains
   online and MCP without OAuth still denies access.
2. In Cloudflare Zero Trust, create the path-specific Access MCP application
   with an owner-only identity policy, then enable Managed OAuth. An owner must
   accept Cloudflare login/consent and configure the policy.
3. Verify a request missing Access authentication receives the expected
   managed OAuth challenge from the Cloudflare edge, **not** the Worker.
4. Set `UDB_ACCESS_AUD`, `UDB_DEVICE_GRANTS`, and `UDB_AUTH_MODE` privately.
   Use Wrangler secrets or private environment settings. Do not publish access
   control configuration containing personal emails to GitHub.
5. Verify `tools/list` displays only approved read-only tools after owner
   login. Confirm a wrong user, wrong Access audience, other device ID and
   direct requests bypassing Access all fail closed.
6. From ChatGPT Plugins, add a private custom MCP server at the exact URL.
   Complete the OAuth consent in ChatGPT. Confirm a real read-only tool call.

**Not supported:** PIN-only internet authentication, auto-approving clients,
cloud admin RPC, remote writes, shell, GUI automation, using Cloudflare Access
identity from request headers, or bypassing the owner-local UDB grants.

## Rollback

Remove `UDB_AUTH_MODE` or set it to `jwt` (which remains default-deny unless
a valid external RS256 identity provider is configured). Disable the Access
application for the MCP path without changing the separate device WebSocket
path. The UDB Cloud Agent may be stopped locally at any time.

Reference: https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/managed-oauth/
