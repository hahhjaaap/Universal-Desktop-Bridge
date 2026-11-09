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


## Continuous public OAuth regression check

Run this read-only diagnostic from a machine with Python and network access:

```powershell
python tools/check_cloudflare_deployment.py --relay https://udb-private-relay-staging.hkhoinguyen72.workers.dev --device-id 54841a965bb6405c9408137a1e2eb650 --auth-mode cloudflare-access --require-project-read --require-standard-metadata
```

The optional `--require-standard-metadata` check verifies that the RFC 9728
document identifies the exact device-scoped MCP URL, the same pinned Access team
issuer as the Cloudflare-managed OAuth challenge, and only the declared
`udb:read` scope. It fails closed on absent, wrong-device, or unrelated issuer
metadata. It intentionally never reads browser cookies, bearer tokens, local
credentials, or device pairing secrets. `chatgpt_oauth: not_tested` in this
report is deliberate; successful consent and tool execution require an
authenticated client acceptance test.


## 2026-11-09: ChatGPT callback compatibility and replayable preflight

An additional **independent** OAuth connectivity blocker was reproduced on the
**staging-only** Cloudflare Access application. DCR registration using
\`https://chatgpt.com/connector_platform_oauth_redirect\` failed with HTTP 400,
\`invalid_client_metadata\`, and \`redirect_uri is not allowed by the account
configuration\`. Previously only the callback-ID wildcard was allowed.
Per [OpenAI OAuth callback documentation](https://developers.openai.com/plugins/build/auth),
different existing ChatGPT connector instances may use either callback format.

In Access > Applications > **UDB Staging MCP** > Managed OAuth > Dynamic
Client Registration, allow precisely these two ChatGPT callback patterns:

- \`https://chatgpt.com/connector/oauth/*\`
- \`https://chatgpt.com/connector_platform_oauth_redirect\`

The Cloudflare staging Access app was updated using the same existing policy,
device-scoped paths, token TTL, and DCR settings. **Do not** allow arbitrary
redirect hosts, remove RFC 8707 \`resource\` enforcement, or permit unauthenticated
MCP requests. The production Worker/Access app was not changed.

Verified against live staging Access on 2026-11-09:

| Test | Observed |
| --- | --- |
| RFC 9728 metadata bound to exact staging device | HTTP 200, correct resource/issuer |
| Unauthenticated MCP GET and initialize POST | HTTP 401 and WWW-Authenticate |
| DCR: exact ChatGPT callback-ID URI | HTTP 201 |
| DCR: stable ChatGPT callback URI after allowlist change | HTTP 201 (previously 400) |
| Authorization with registered client and correct RFC 8707 resource | HTTP 302 to Access login |
| Authorization with wrong resource | HTTP 400 |
| Cloudflare authorization server advertises PKCE | S256 |
| Cloudflare authorization server advertises refresh-token grant | Yes |
| Authenticated ChatGPT tool discovery / Windows fixture read | **NOT TESTED** |

The DCR probes create disposable public OAuth client registrations, not access
tokens. Cloudflare Access's registration endpoint did not expose a cleanup
endpoint in these probes; run registration tests only when needed.

### Safe repeatable preflight

Run read-only discovery and denied-unauthenticated checks (no client registration):

\`\`\`powershell
python tools/check_chatgpt_oauth.py --relay https://udb-private-relay-staging.hkhoinguyen72.workers.dev --device-id 54841a965bb6405c9408137a1e2eb650
\`\`\`

If the administrator needs to test the real ChatGPT redirect allowlist, add
\`--register-client --callback https://chatgpt.com/connector_platform_oauth_redirect\`.
Use the *exact* redirect shown in the ChatGPT MCP connection management page
when checking a specific app. This optional flag creates one disposable
OAuth client, then verifies login initiation and wrong-resource rejection.
It never authenticates a user, requests an access token, or executes a Windows
tool. The script rejects non-staging relay hosts and non-ChatGPT callback URIs.

Remaining integration acceptance requires the owner to enable the **UDB
Staging** ChatGPT connector and personally complete the Cloudflare Access OAuth
consent. Use the exact scoped MCP resource and verify (1) \`tools/list\`,
(2) \`bridge_status\` or a permitted equivalent, (3) a synthetic fixture file
read whose hash is known, and (4) wrong identity, device, revoke and mutation
denials. A successful public preflight or DCR registration **must not** be
presented as authenticated end-to-end success. The existing \`udb_cloudflare\`
connector errors target another production endpoint and do not prove a staging
OAuth failure.
