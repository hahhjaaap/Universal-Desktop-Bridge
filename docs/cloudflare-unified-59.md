# Unified UDB MCP — historical 59-tool milestone

> **UDB 0.12.0 docs review (2026-11-13):** **Historical design/evidence, not a current runbook.** Earlier experiments, metrics and version-specific status do not establish current v0.12.0 behavior; never execute obsolete deployment/transport instructions. See [version/status](current-version.md).

UDB has two local backends: 36 Core FastMCP tools and 31 Companion
implementations. The local proxy consolidates eight legacy operations into
public tools; file_transfer is their combined copy/move interface. The resulting
catalog contains exactly **59 public tools**.

The Cloudflare gateway can expose these tools through one authenticated MCP
endpoint, but only when the verified device owner has explicitly authorized
the names. This does not imply blanket access to the Windows desktop.

## Independent security boundaries

- UDB_DEVICE_GRANTS is the existing device-specific, identity-specific
  authorization for six read-only MCP tools.
- UDB_ENABLE_OWNER_TOOLS=true with secret UDB_OWNER_TOOL_GRANTS is the
  existing opt-in for 30 Core owner operations. Four legacy names remain
  callable for compatibility but are not in the public catalog.
- UDB_ENABLE_COMPANION_TOOLS=true with secret UDB_COMPANION_TOOL_GRANTS
  is a **new, separately reviewed** opt-in for 27 public Companion names.
  The secret must contain an exact device ID to verified subject mapping,
  with an explicit array of allowed names.
- Windows retains independent checks for local project scope, signed-in
  owner grants, terminal state, session limits and interactive approvals.
  No Cloudflare grant creates or approves those local permissions.

The Companion flag and secret are omitted from all deployment configurations
by default, so no existing owner device gains an elevated capability through
a deployment or source merge. A configured UDB_TENANT_POLICY disables
legacy Core and Companion owner grants; it never falls back.

## Discovery versus execution

When Companion or owner grants are absent, the existing six-tool read-only
Cloudflare edge discovery remains in place. When both classes of elevated
grants exist, tools/list relays the live Windows public catalog, filters
against the authenticated device/subject grant, and can return all 59 names
and their real input schemas. Tools/call rechecks the grant and forwards to
the local UDB proxy. Any local approval failure is reported as such.

The six read-only tools remain the only calls tagged with OAuth scope
udb:read. All owner/Companion calls are serialized as mutations by the
Cloudflare DeviceRelay and Windows Cloud Agent even when the underlying
operation itself is observational. Unknown call outcomes are not retried.

## Verification

In the repository:

- Run node --test tests/*.test.js from cloudflare/.
- Run pytest -q tests/test_cloudflare_unified_59.py from the repository root.
- Verify the full CI matrix for Windows and Linux, including packaging.
- Verify local udb --json tools reports exactly 59 public tool names.

Before any staging rollout, record the deployed Worker version, preserve its
secrets/bindings and keep production untouched. An opt-in grant should use
a disposable Windows staging project and an owner-reviewed subset of tools.

A complete end-to-end test requires a real authenticated ChatGPT MCP
initialize, tools/list and permitted tools/call; check that the returned
data came from the Windows fixture and that another user/device and revoked
grants are denied. A Node mock, a public OAuth preflight or a device heartbeat
alone does not establish ChatGPT-to-Windows acceptance.
