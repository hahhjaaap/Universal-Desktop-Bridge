# P0-D — Verified Cloudflare Access principal → D1 MCP authorization (staging)

**State:** Draft-only implementation. No production deploy and **do not enable the rollout flag** without a complete staging onboarding/pairing and revocation acceptance run.

## Summary

This extends the P0-C tenant schema in PR #132 with a **separate opt-in authorization path** for the six approved project-read MCP tools. Every MCP request uses:

1. A Cloudflare Access JWT with pinned team issuer, expected Access application audience, RS256/JWKS verification, valid expiry and UUID subject.
2. An issuer-qualified principal (`issuer + immutable subject`), checked against the authenticated Access runtime where available.
3. A parameterized D1 lookup anchored by the **device ID from the Worker route**, never by a `tenantId` supplied by the MCP client.
4. Active tenant, device, device owner, requester membership and user records.
5. An explicit, unexpired, non-revoked per-tool grant for the exact requester and device.
6. A second local Windows owner/project permission check when the call reaches the agent.

No role implies permission by itself. A signed email without a signed UUID, a legacy `UDB_DEVICE_GRANTS` entry, an `UDB_OWNER_TOOL_GRANTS` entry, a stale grant or D1 outage must not authorize a request.

## Staging configuration (not activated)

The only configuration change in this PR is a **D1 binding** in `cloudflare/wrangler.staging.jsonc`:

- Binding: `UDB_TENANT_DB`
- Database: `udb-auth-staging`
- Database UUID: `fd474b23-56be-44c7-8387-615a071de824`

The pre-existing production Wrangler configuration is untouched.

The following three environment settings would be required **later**, after a verified user/device has been securely paired and explicitly granted read tools:

```text
UDB_AUTH_MODE=cloudflare-access
UDB_ACCESS_PRINCIPAL_MODE=issuer-sub
UDB_TENANT_D1_AUTH=true
```

The exact string `true` opts into D1. Omitted or `false` preserves existing access behavior. Unknown values return HTTP 503. When enabled, D1 and Access checks **never fall back** to older grants, including during outages. The D1 path is deliberately limited to the six reviewed read tools; the remaining 53 require a separate staged privilege/consent design.

**Do not set `UDB_TENANT_D1_AUTH=true` while the staging D1 has no explicitly enrolled users, devices and grants**: it will correctly deny all user MCP requests.

## Verification

```sh
node --test cloudflare/tests/*.test.js
python -m pytest -q tests/test_tenant_d1_query_integration.py tests/test_cloudflare_tenant_auth_schema.py
python -m ruff check tests/test_tenant_d1_query_integration.py
python -m ruff format --check tests/test_tenant_d1_query_integration.py
```

Validated locally against signed, test-only JWT fixtures; unlike an email-only mock, these tests generate real RS256 signatures. A second acceptance suite executes the *exact SQL text* in `tenant-store.js` against two independent SQLite tenants. Cloudflare's live staging D1 accepted `EXPLAIN QUERY PLAN` for the same statement using the correct device and issuer/subject indexes. No test account or grant was written to live D1.

## Gates before activation

- Build a real account login, consent and owner-confirmed device pairing workflow; enrollment must associate the existing DO device ID with precisely one D1 tenant and principal.
- Bind D1 to the staging Worker in an explicitly approved staged release, without turning on the flag yet.
- Enroll a disposable staging device and grant exactly the six read tools to a verified test principal.
- Verify `initialize`, `tools/list`, live `bridge_status`, `list_projects`, and an approved fixture `read_file` from the ChatGPT MCP client.
- Test wrong Access user UUID with the same email, wrong device, revoked and expired tool grants, suspended tenant, signed JWT expiry, D1 failure, reconnect, and denied protected paths.
- Revoke in both D1 **and** Durable Object: deleting a D1 row stops user MCP authorization but does **not** by itself close an existing Windows WebSocket or revoke its paired device token.
- Confirm the Windows Agent local approval policy independently; the Edge must never silently grant host shell, computer or desktop control.
- Reconcile the D1 migrations ledger: P0-C migration was initially applied directly via Cloudflare API and may not appear in Wrangler's migrations table.
- Document rollback: leave the flag off; restoring legacy authentication after a security incident must be an explicit owner decision, never an automatic fallback.

**Not yet shipped:** public OAuth registration/onboarding UI, single-click installer, real device enrollment, 59 remote tool execution, public multi-tenant SaaS, production migration.
