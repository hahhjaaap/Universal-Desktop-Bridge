# Owner → tenant → device → read capability: security boundary (P0-A)

**Status:** Source-level optional policy for a *controlled, invite-only pilot*.
It is not a user registration service, automated ownership proof, complete
Cloudflare production deployment or independent security assessment.

## Trust boundaries

```text
AI/MCP client (untrusted prompts and tool parameters)
    │ authenticated via Cloudflare Access Managed OAuth or pinned external JWT
    ▼
Worker MCP endpoint /v1/devices/<device-id>/mcp
    │ verified subject + matching Access app audience / exact JWT resource
    ▼
UDB_TENANT_POLICY or legacy UDB_DEVICE_GRANTS (explicit, default-deny)
    │ permitted tool list and exactly one tenant owning each device ID
    ▼
Durable Object for that device / authenticated outbound Cloud Agent socket
    │ serial RPC, bounded read queue, no retry after unknown outcome
    ▼
Windows UDB MCP proxy / local registered-project permissions
    │ protected path policy and local owner grants still apply
    ▼
Local Windows files and projects (contents may traverse relay and AI provider)
```

**Threats addressed by this slice:** mistaken assignment of the same device
to multiple tenants, authenticated user attempting another tenant's device,
legacy grants accidentally allowing an unauthorized user, unauthorized
read/write tool discovery, stale revocation entries and malformed policy
falling back to permissive configuration. Unit tests simulate two independent
owners and devices; these are **not** real Cloudflare/ChatGPT acceptance tests.

**Remaining high-risk threats / NO-GO for public multi-tenant service:**
- Enrollment ownership proof, device recovery, invitation validation and
  revocation must become an authenticated audited lifecycle, not a manually
  edited global secret.
- Access identifies email addresses; email reassignment/identity-provider
  changes, verified-email semantics and different identity issuers need a
  stable issuer-qualified subject binding before broad customer signup.
- Cloudflare Worker/DO may inspect relayed content; this is **not**
  confidentiality from the relay operator.
- Owner-wide Windows `computer_*` rights are unsandboxed and must never be
  enabled by MCP read scope, remote code/prompt or the relay.
- A stolen Windows device token can reconnect as that device unless revoked.
  A compromised Cloudflare account/operator can change config/deployments;
  audit, role separation and alerting are required.
- Cross-tenant signed Access assertion, stale JWT, replay/reconnect, Access
  application path misconfiguration, denial-of-service, prompt injection,
  path traversal and concurrent filesystem changes need security review.

## Optional strict tenant policy

In *staging only*, a trusted operator may provision
`UDB_TENANT_POLICY` privately (Cloudflare secret/environment variable)
after reviewing authorized owners. It is an **alternative** to the legacy
`UDB_DEVICE_GRANTS` policy:

```json
{
  "version": 1,
  "tenants": [
    {
      "id": "pilot-a",
      "owners": ["owner-a@example.test"],
      "members": ["owner-a@example.test", "auditor@example.test"],
      "devices": [
        {
          "id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "grants": [
            {"subject": "owner-a@example.test", "tools": ["bridge_status", "list_projects", "read_file"]},
            {"subject": "auditor@example.test", "tools": ["bridge_status"]}
          ]
        }
      ]
    },
    {
      "id": "pilot-b",
      "owners": ["owner-b@example.test"],
      "members": ["owner-b@example.test"],
      "devices": [
        {
          "id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          "grants": [
            {"subject": "owner-b@example.test", "tools": ["bridge_status", "list_projects"]}
          ]
        }
      ]
    }
  ]
}
```

All IDs and addresses above are **synthetic fixtures**. Do not commit
actual identities, secrets, tokens or owner device IDs.

The configured subject must match the **already authenticated** identity
provided by the OAuth/Access verifier; this policy never trusts a user-sent
email or "owner" field. `owners` ties each tenant to a real, explicitly
reviewed owner, `members` represents allowed participants; a member only
gets tools if they also have a **matching device-specific** grant.

- If `UDB_TENANT_POLICY` is absent, the existing single-owner
  `UDB_DEVICE_GRANTS` path remains operational for compatibility.
- Once `UDB_TENANT_POLICY` is present, it is **authoritative**. Invalid,
  empty, malformed, duplicated, unknown-field, or revoked entries result
  in **zero granted tools**. The gateway never falls back to an older
  `UDB_DEVICE_GRANTS` that might have stale rights.
- Every device ID may appear in exactly one tenant. Subjects and explicit
  grants must belong to that tenant, without wildcard or inferred access.
- A configured grant only permits the six existing read-only tool names:
  `bridge_status`, `list_projects`, `list_files`, `read_file`,
  `search_files`, `check_python_syntax`. It never authorizes
  file changes, terminal, browser control or the Windows desktop.
- Revoking a participant means updating the private policy and confirming
  a new request is denied; expiry, revocation propagation and rollback
  need an **operational** acceptance test with real OAuth identities.
- Avoid changing two production grants as one experiment: use separate
  staging Worker/Access apps and synthetic disposable projects first.

## Local acceptance before Cloudflare staging

```sh
node --test cloudflare/tests/*.test.js
python -m pytest -q tests/test_cloudflare_deployment.py
```

Unit test security matrix (all `403` or no granted tools unless allowed):

| Scenario | Expected result |
| --- | --- |
| Owner A reads granted file on device A | Allowed by edge grant; local project may still deny |
| Owner A reads device B, owner B reads device A | Denied before Windows RPC |
| Unknown person / missing authenticated identity | Denied |
| Authorized member not listed in a device grant | Denied |
| `computer_execute` / `propose_file_write` by any subject | Denied |
| Same device registered under two tenants | Entire policy rejected |
| Empty/invalid policy with legacy grants present | Denied; never downgrade |
| Removal of a grant after an earlier success | New call denied |
| Disconnect/reconnect or expired OAuth token | Requires fresh verified authentication |
| Protected path and unregistered project | Denied independently by Windows proxy |

## Required production design beyond this milestone

1. Choose stable issuer-qualified principal IDs rather than mutable email as
   the long-term identifier, with migration and explicit verified-email rules.
2. Build owner-attended claim and an audited self-service membership/device
   management workflow (invite, grant, suspend, revoke, recovery).
3. Isolate tenant metadata, secret storage, rate limits and logs in a reviewed
   service; do not scale a single manually edited JSON secret to arbitrary
   customers or pretend that `tenants` is a billing/account database.
4. Make Access OAuth audience and the bound `/mcp` path explicit per device;
   test both code and actual policy at Cloudflare edge.
5. Add abuse/rate limiting, privacy retention policy and human-reviewed
   security assessment before an open public beta.

Read [project-read deployment acceptance](cloudflare-project-read-acceptance.md),
[release-signing and security requirements](release-security.md) and the
[UDB architecture](../ARCHITECTURE.md) before considering deployment.
