# UDB staging – ChatGPT / Cloudflare Managed OAuth interoperability

## Incident

ChatGPT's OAuth popup showed `invalid_target`, with Cloudflare Access reporting that no application could be found for the requested OAuth resource. The staging Access app and its two device URLs already existed. Windows Cloud Agent for the active staging device was online.

## Reproduction and root cause

An isolated diagnostic registered disposable public OAuth clients against the Cloudflare Access team authorization server. The request variants produced:

| Authorization request | HTTP result |
| --- | --- |
| Omits RFC 8707 `resource` | 400 `invalid_target` |
| Adds exact `resource` for online staging MCP device | 302, continues to login |
| Adds exact `resource` for legacy staging MCP device | 302, continues to login |

Adding a `resource` value during client registration did not make it the authorization request default. This establishes Cloudflare Access's resource-parameter requirement but does **not**, by itself, prove which query parameters ChatGPT sent in the original popup: the screenshot did not contain the complete URL. Client-side evidence is still needed.

The diagnostic registration endpoint did not expose `registration_client_uri` / cleanup credentials, so two unused test client registrations may remain. They contain no user access token and used a diagnostic callback under the existing ChatGPT redirect allowlist.

## Safe server interoperability improvement

In Access mode, the standard MCP protected-resource endpoint was intentionally returning HTTP 404:

`/.well-known/oauth-protected-resource/v1/devices/<device-id>/mcp`

The Cloudflare vendor-specific metadata endpoint was already live, but some MCP clients use the standard RFC 9728 endpoint instead. The patch now publishes both the exact resource URL and the pinned team authorization server from `UDB_ACCESS_TEAM_DOMAIN`. The protected MCP route remains behind Cloudflare Access, with an OAuth challenge, per-device grants, and Windows owner's local permissions intact.

Validation: 115/115 Node regression tests, Wrangler 4.158.0 staging dry-run, then live staging metadata HTTP 200 for both registered device paths, unauthorized MCP HTTP 401, and active Windows device online. All seven bindings were inherited strictly: one Durable Object, five secrets and the plain-text catalog flag.

### Deployed version

- **Staging only:** `4bb1c314-e758-4e02-822c-12d25b8d30e3`
- Previous staging version for rollback: `c0ad8192-e6bc-4bb3-bb42-14674a94994c`
- Production Worker was not modified.

## Remaining acceptance step

The user must complete a ChatGPT OAuth linking flow using the live staging MCP resource. A standards-compliant client sends the full `resource` URL on authorization and token requests. If ChatGPT still omits it, the fix belongs in ChatGPT connector OAuth handling or a separately reviewed, security-preserving OAuth compatibility adapter; do not disable Cloudflare Access, share admin tokens or add unauthenticated direct-RPC bypasses. No successful ChatGPT `bridge_status` has been observed at the time of this patch.
