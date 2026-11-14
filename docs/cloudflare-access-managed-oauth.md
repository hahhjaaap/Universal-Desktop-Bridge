# Cloudflare Access Managed OAuth (UDB read-only experimental MCP)

> **Docs reviewed 2026-11-13 — UDB 0.12.0:** **Staging/opt-in scope.** Features and grants described below are not enabled for arbitrary devices and are not proof of a live ChatGPT connection. Check [current-version.md](current-version.md) and the installed `udb --version` before using commands.

## Scope and safety

Optional alternative to a manually integrated RS256 JWT OAuth identity provider.
For legacy per-device mode, use **Cloudflare Access Managed OAuth** configured
as a **hostname/path scoped Access MCP application** for the device MCP endpoint.
The opt-in account Fleet candidate uses the separate `/v1/account/mcp` resource;
protect that exact resource with the reviewed account MCP Access application.
Do not select Worker-level Access on a UDB relay: Cloudflare documents that
Worker-level Access blocks WebSocket upgrades, which would disconnect the UDB
Cloud Agent.

The code remains **off by default**. The Windows device is not remotely
controllable through the MCP gateway. It exposes only owner-granted read tools
(`bridge_status`, `list_projects` and the four explicitly granted project read
tools described in [the project-read acceptance runbook](cloudflare-project-read-acceptance.md)).

## Required authenticated identity boundary

- In legacy per-device mode, the MCP endpoint is
  `/v1/devices/DEVICE_ID/mcp` on the existing Worker. For the opt-in Fleet
  candidate, the shared MCP resource is `/v1/account/mcp`; see
  [account Fleet MCP](account-fleet-mcp.md) for its immutable owner-subject
  binding and rollout requirements.
- Set up a path-scoped Cloudflare Access application on the exact resource
  URL being used; do not assume a device-path application covers the account
  resource.
- Configure an Access policy that allows **only the intended owner identity**.
- Enable **Managed OAuth** under that application's Advanced settings.
- ChatGPT or another MCP client must perform Access OAuth login and consent.
- Cloudflare Access can pass authenticated runtime identity through `ctx.access`.
  If `ctx.access` is missing or lacks an email, UDB accepts **only a signed
  RS256 Access assertion** in `Cf-Access-Jwt-Assertion`, verified using the
  pinned team-domain public JWKS, issuer, audience, expiry and email. Merely
  supplying that header, a cookie, or an opaque OAuth token is not sufficient.
- The Worker requires `UDB_AUTH_MODE=cloudflare-access`,
  `UDB_ACCESS_AUD=YOUR_ACCESS_APPLICATION_AUDIENCE_TAG` and
  `UDB_ACCESS_TEAM_DOMAIN=https://YOUR_TEAM.cloudflareaccess.com`.
  The team domain is pinned for JWT signature verification, never read from
  request headers or an unverified token. The audience must match the Access
  application's audience tag; the signed assertion email must match an exact
  per-device grant. Do not use a personal email as the team domain.
- Set `UDB_DEVICE_GRANTS` as a JSON object mapping device IDs to authenticated
  Access identity **email addresses** and approved read-only tool names:

```json
{
  "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": {
    "owner@example.test": ["bridge_status"]
  }
}
```

This email-based `UDB_DEVICE_GRANTS` example is for the legacy per-device
resource. Fleet account membership uses the immutable Cloudflare team subject
and owner-bound device registry described in
[account Fleet MCP](account-fleet-mcp.md); do not infer account membership from
an email grant or caller-supplied device ID.

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
4. Set `UDB_ACCESS_AUD`, `UDB_ACCESS_TEAM_DOMAIN`, `UDB_DEVICE_GRANTS`, and
   `UDB_AUTH_MODE` privately.
   Use Wrangler secrets or private environment settings. Do not publish access
   control configuration containing personal emails to GitHub.
5. Verify `tools/list` displays only approved read-only tools after owner
   login. Confirm a wrong user, wrong Access audience, other device ID and
   direct requests bypassing Access all fail closed.
6. From ChatGPT Plugins, add a private custom MCP server at the exact URL.
   Complete the OAuth consent in ChatGPT. Confirm a real read-only tool call.

**Not supported:** PIN-only internet authentication, auto-approving clients,
cloud admin RPC, remote writes, shell, GUI automation, trusting **unverified**
Cloudflare Access headers, or bypassing the owner-local UDB grants.

## Rollback

Remove `UDB_AUTH_MODE` or set it to `jwt` (which remains default-deny unless
a valid external RS256 identity provider is configured). Disable the Access
application for the MCP path without changing the separate device WebSocket
path. The UDB Cloud Agent may be stopped locally at any time.

References:
- https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/managed-oauth/
- https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/
- https://developers.cloudflare.com/workers/configuration/cloudflare-access/
