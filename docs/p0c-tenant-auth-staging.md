# P0-C: Multi-tenant identity and authorization groundwork (staging only)

This additive change starts from PR #131. It does **not** modify the existing Worker routes, grant remote-control permissions, modify production, or turn on public onboarding.

## Scope

- `cloudflare/migrations/0001_tenant_auth.sql` defines D1 tables for tenants, immutable OAuth identities, memberships, Windows devices, projects, explicit tool grants, invitations, hashed login sessions and audit events.
- `cloudflare/src/tenant-store.js` provides **read-only**, fail-closed, parameterized authorization lookups.
- No implicit read grants and no role-based bypass. An owner/admin must explicitly approve the device and its tools.
- An external authentication layer must verify JWT audience, issuer, signature, expiration and subject **before** invoking the lookup. The function's input format validation does not verify a JWT.
- The Windows owner's local permissions remain authoritative; passing the database check never authorizes the machine by itself.

## Validation

Run from repository root:

```bash
python -m unittest discover -s cloudflare/tests -p 'test_tenant_auth_schema.py' -v
node --test cloudflare/tests/tenant-store.test.js
```

The migration is intended for the **dedicated** staging D1 `udb-auth-staging` only, not a production database. Confirm the database ID and keep its schema under version control. Do not grant it to a public Worker until the OAuth and per-request device-ownership integration has been independently tested.

## Mandatory end-to-end work not yet implemented

1. OAuth2.1 Authorization Code + PKCE, registered redirect URIs, user consent, session management, issuer/audience checks and client registration.
2. Secure Windows pairing that atomically binds a Durable Object device ID to a tenant and a verified principal.
3. Owner-approved grant and revocation APIs, including audit logging, rate limiting, and replay prevention.
4. Enforce authorization for every MCP tools/list **and** tools/call request using an exact trusted 59-tool catalog.
5. Revoke cached grants and disable device sessions immediately on user/device revocation.
6. Test real clients and Windows agents across two tenants before staging traffic is enabled.

**Important:** This implementation is preparation for steps 21–30, not evidence that those steps or the 100-step launch plan are complete.

## Staging D1 migration record (2026-11-08)

The 16 idempotent schema statements were applied **directly via the Cloudflare D1 API** to the dedicated `udb-auth-staging` database; nine UDB tables exist and no users, tenants, devices, or grants were created. This operation did **not** use Wrangler's migrations ledger. Before running `wrangler d1 migrations apply` in a later change, reconcile the ledger with the existing schema to prevent misleading migration status. No production D1 database was modified.
