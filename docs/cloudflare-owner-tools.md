# Cloudflare owner-gated tool catalog (opt-in)

UDB's Windows MCP server defines 36 tools in the current source, but the
original Cloudflare `udb:read` gateway intentionally exposed only six of
them. The extra tools include file changes, sandbox jobs, UDB-owned browser
sessions and optional Windows host/desktop operations. **Discoverability is
not authorization and authorizing a cloud identity is not local desktop
consent.**

This profile is *disabled by default*. It is not a replacement for
the read-only staging acceptance in [issue #94](cloudflare-project-read-acceptance.md).
It must not be enabled for a public or multi-tenant deployment without a
separate security review.

## Independent gates

1. The client must pass the **existing** path-scoped Cloudflare Access Managed
   OAuth application and its exact audience; the per-device owner identity is
   verified at the Cloudflare Worker. Legacy generic JWT OAuth is **read-only**.
2. The subject/device must already have a nonempty `UDB_DEVICE_GRANTS`
   **read grant**. An unknown user, device or revoked read grant cannot gain
   owner tools.
3. `UDB_ENABLE_OWNER_TOOLS` must equal the literal string `true`, and the
   distinct, privately stored `UDB_OWNER_TOOL_GRANTS` secret must explicitly
   name each additional tool for the exact device ID and owner email. Any
   malformed, unknown, duplicate or out-of-catalog tool entry is rejected.
4. The optional centrally managed `UDB_TENANT_POLICY` remains authoritative:
   if it is defined, owner-tool grants are ignored. Never use this owner-only
   mode to circumvent tenant isolation.
5. **Windows authorization is still separate.** Individual UDB project roots,
   proposed writes, sandbox execution, host-browser sessions and
   `computer_*` tools continue to require the existing local owner-reviewed
   grants, approvals and pause controls. No MCP tool may issue, forge or
   approve such a grant.

The Worker neither changes local permissions nor bypasses the UDB Manager.
Operation calls are **never auto-retried or queued**; a disconnect can leave an
outcome unknown, so inspect state before doing anything else.

## Configuration (isolated staging only)

Review the complete list in `cloudflare/src/owner-tools.js` against
`src/udb/server.py` before choosing tools. Configure through a
secret-safe, attended owner workflow:

- Preserve existing `UDB_DEVICE_GRANTS` (six read tools or a smaller subset).
- Privately store `UDB_OWNER_TOOL_GRANTS` as a JSON object mapping the
  exact staging device ID to the exact Access identity email to the **selected
  additional tool names**. Do not use a wildcard, all-users policy, a
  production device ID or a production project.
- Set `UDB_ENABLE_OWNER_TOOLS` to `true` **only** on the isolated staging
  Worker after reviewing the permission list. The two settings must be absent
  on production unless a separate owner-approved production rollout occurs.
- Revoke by removing `UDB_ENABLE_OWNER_TOOLS` or the exact
  `UDB_OWNER_TOOL_GRANTS` entry; the next authenticated call is denied.

**Do not** paste secrets, Access subjects, device tokens, OAuth codes or grant
JSON into chat, source control, CI logs or unprotected terminal history.

The gateway describes non-read tools with the existing Access OAuth login but
**does not** falsely label them `udb:read`: they require the additional
server-side owner grant and local approval. Cloudflare Managed OAuth handles
client authentication; the custom UDB owner grant is **not** an OAuth scope
or a substitute for re-consent.

## Verify functionality and safe denial

For the exact, already paired staging device:

1. Verify `udb doctor --cloud --json` passes public Access routing first.
2. Start only the isolated staging Cloud Agent and owner-authorize the local
   test resources.
3. Complete the **owner's** ChatGPT OAuth consent on that staging MCP endpoint.
4. Check `tools/list`: previously approved read tools plus **only** explicitly
   owner-granted operation tools should appear with their input schemas.
5. Request a low-impact status operation, then a deliberate synthetic
   file-edit proposal. Verify a local approval is required where no local
   autonomous grant exists. Do not test destructive host actions on real
   owner files or programs.
6. Check unlisted/unknown operation tools, another identity/device, invalid
   metadata and revoked grants are blocked **before** reaching Windows.
7. Check disconnect/reconnect, timeout/unknown outcome handling and ensure no
   mutation was automatically replayed.

**The ChatGPT connector may cache a fixed tool catalog.** Reconnect or
recreate the **owner-approved staging MCP connection** after these tests;
deploying a Worker alone does not install 36 tools in an existing ChatGPT
connector. Do not claim complete remote tool availability until the client
actually lists and invokes the approved tools.

The default public `udb:read` gateway remains unchanged. To remove this
feature, delete its two owner-tool Worker settings and redeploy the previously
reviewed Worker version if necessary. This does not remove local owner grants;
they must be managed separately in UDB.
