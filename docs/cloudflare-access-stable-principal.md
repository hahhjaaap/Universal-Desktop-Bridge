# Cloudflare Access issuer-qualified principals (optional staging pilot)

> **Docs reviewed 2026-11-13 — UDB 0.12.0:** **Staging/opt-in scope.** Features and grants described below are not enabled for arbitrary devices and are not proof of a live ChatGPT connection. Check [current-version.md](current-version.md) and the installed `udb --version` before using commands.

**Status:** Source-level P0-A hardening only. Not enabled by default, not an
owner-enrollment service, and not a claim of approved multi-tenant security.

## Why this is distinct from an email grant

A verified Cloudflare Access email identifies an email address, not an
immutable user account. Email reassignment or a user being removed and
recreated can change who possesses the address. Cloudflare Access
application JWTs also carry a `sub` user identifier. Cloudflare documents
this identifier as unique to the email *within an account*; it may change
after the user is deleted and re-added or when moving between organizations.

The optional mode chooses a more narrowly scoped grant principal:
`<verified Cloudflare Access issuer>#<signed app JWT sub>`.

The issuer is the **exact pinned** `UDB_ACCESS_TEAM_DOMAIN` and the subject
must be a signed 36-character UUID. Never derive this from an unverified
client header, claim pasted by a user, or a URL/query parameter.

## Configuration and migration boundary

For a separately reviewed **staging** deployment only:

- Set `UDB_AUTH_MODE="cloudflare-access"`.
- Configure an exact Access application `UDB_ACCESS_AUD`.
- Pin `UDB_ACCESS_TEAM_DOMAIN` to the correct HTTPS
  `<team>.cloudflareaccess.com` origin.
- Set `UDB_ACCESS_PRINCIPAL_MODE="issuer-sub"`.
- Configure **explicit** per-device read grants under the exact
  `<issuer>#<sub>` principal in `UDB_TENANT_POLICY` (or under a
  separately audited legacy `UDB_DEVICE_GRANTS` in a pilot).
- Review the non-secret grant shape and signed assertion data locally;
  do **not** copy Access JWTs, full private grants, device tokens or real
  user identifiers into GitHub issues or CI logs.

When this mode is set, even a legitimate `ctx.access.getIdentity().email`
**cannot** authorize a tool without a verified
`Cf-Access-Jwt-Assertion` JWT. The signed assertion must match the pinned
team issuer and Access audience, pass expiry/signature checks and contain
a valid `sub`. A missing assertion or ungranted subject is denied.
Another person logging in with the *same* email but a *different* `sub`
does not inherit the original grant. Unknown principal modes are rejected.

When the flag is **unset** or `"email"`, the existing email-based
Cloudflare Access behavior is unchanged for compatibility. Enabling the
new mode against historical email-only grants intentionally denies access
until an owner reviews a migration; no automatic principal mapping or
fallback is provided.

**Owner/desktop tools are intentionally excluded in this pilot:** their
separate legacy grant mechanism requires an email-shaped subject. A stable
read principal is not a path to remote host access. The tenant policy remains
authoritative.

## Test and rollback requirements

```sh
node --test cloudflare/tests/access-assertion.test.js
node --test cloudflare/tests/*.test.js render/tests/*.test.mjs
```

Synthetic cases verify signature/audience/team pinning, identical emails
with distinct subject IDs, revoked grants, missing/invalid subjects and
failure to downgrade into old email or owner-tool grants.

Do not activate this mode in production until a two-owner/two-device
Access staging test and independent security review confirm how Access
reissues user IDs, revocation behavior, enrollment and recovery. Reverting
the **flag** is a deliberate operator migration back to email grants, not
a security-preserving rollback for an already released multi-user system;
do not switch it off automatically after an authorization failure.

## Important limitations

This does **not** prove device ownership, solve tenant signup, implement
reliable suspension across already admitted in-flight requests or replace
proof of signed Windows binaries. It affects only per-request authorization
in the Worker when correctly configured. See Issue #95 and the private-beta
roadmap for those separate security gates.

References:
- https://developers.cloudflare.com/workers/configuration/cloudflare-access/
- https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/application-token/
- https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/
