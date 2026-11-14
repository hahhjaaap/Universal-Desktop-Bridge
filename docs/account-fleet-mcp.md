# UDB account fleet MCP (opt-in)

This is a **staging-only candidate** for one Cloudflare Access-authenticated MCP resource
serving several approved Windows UDB agents, without introducing a Tailscale dependency.
Legacy `/v1/devices/{device_id}/mcp` remains supported.

## Endpoint and authenticated identity

The new resource is `/v1/account/mcp`. OAuth metadata is served at
`/.well-known/oauth-protected-resource/v1/account/mcp`; it is informational, not an
authorization grant. On each request, the Worker verifies its configured Access application
and extracts the account-scoped immutable user UUID from Cloudflare's trusted Access
runtime identity, or from a separately validated signed Access assertion. Its registry key
uses the configured team issuer and the authenticated subject, **not** email, caller-supplied
`owner_id` or request headers.

A dedicated durable account index uses the already deployed `DEVICES` Durable Object
namespace with an opaque deterministic object name. Each index entry contains an
immutable device ID, owner-approved display name and enrollment request binding.
The device DO retains its existing token hash, ownership, revocation tombstone, WebSocket,
Windows proxy concurrency, and permissions. Every dispatch re-verifies ownership in
the device DO. No cross-conversation or cross-device "selected machine" is stored.

The MCP catalog offers `list_devices` and the already approved public Windows tool
catalog with a **required string** `device_id` property. A device ID is never embedded
in an enum. `list_devices` gives `device_id`, `display_name`, `connection`
(`online`, `offline`, or `unverified`), and independent `last_seen_at` when known.
Display names are hints only; duplicated names do not affect routing.
The target `device_id` is removed before forwarding tool arguments to Windows.

The account gateway provides a stable versioned catalog even when every
machine is offline. Its 40 public schemas are generated from the authoritative
`udb.registry.catalog()` implementation, which introspects the actual Windows
MCP handlers and merges the Companion schemas and shared action families.
The generated projection is checked in at
`cloudflare/src/fleet-tool-catalog.json`; regenerate after changing a tool
signature with `python tools/export_fleet_catalog.py --write`. CI runs
`python tools/export_fleet_catalog.py --check` and fails on schema drift.
Fleet discovery appends only the required top-level `device_id`; a regression
test verifies every other schema field remains identical to the generated
Windows catalog, including action-specific family branches.

Prior persisted `fleet_catalog` snapshots are ignored: an old or
permission-limited Windows agent cannot narrow account discovery. Discovery is
metadata, not a Windows permission grant. Every call still revalidates account
ownership, device online state, Access identity and the actual local Windows
permission on that selected machine. No automatic failover or mutation replay
is introduced.

## Rollout switches and safety

The feature remains off unless **all** conditions hold:
- `UDB_ENABLE_ACCOUNT_FLEET=true`
- `UDB_ENABLE_BROWSER_ENROLLMENT=true`
- `UDB_ENABLE_LOCAL_TOOL_SYNC=true`
- `UDB_AUTH_MODE=cloudflare-access`, with valid pinned Access team/audience
- No `UDB_TENANT_POLICY` (fleet is denied while a tenant policy is configured).

Other existing relay-wide owner/companion tool switches and per-machine Windows
permissions still apply. The checked-in Wrangler configs intentionally **do not**
turn on Fleet. An operator must review and enable it in an isolated staging Access
configuration, with the existing `--keep-vars` deployment safety contract. Do not
enable it on production or broaden production Access policy without explicit approval.

To roll back, disable `UDB_ENABLE_ACCOUNT_FLEET` (or restore the previously deployed
Worker version) and continue using the unchanged per-device MCP endpoints.
Do not delete Durable Objects, change device token hashes, delete Credential Manager
entries, revoke any devices, or rewrite Windows pairing files. Existing cached account
MCP clients should be instructed to use the prior endpoint if rolled back.

## New or previously paired Windows machine

1. Install a compatible UDB build and run `udb setup` **on that Windows machine**.
2. For a new pairing, the existing versioned request is persisted and approved manually
   through its pinned Access approval application and one-use CSRF.
3. For an existing pairing, setup checks the token-authenticated Fleet status. If the
   existing device has not been linked to an account, setup reuses its existing token and
   saves a **separate** resumable Fleet-link proof in Windows Credential Manager.
   The human owner must approve the specific device/fingerprint in their Access browser.
   Linking does not rotate the token or rewrite `cloud-pairing.json`.
4. The Worker first records the authorized owner on the device DO, then indexes it
   by the same owner in the account DO. An uncertain index write is reconciled only
   by the exact same idempotent enrollment/linking operation.
5. In ChatGPT Plugins, add **one** custom MCP server using the account URL, then
   explicitly authorize OAuth. This requires the account/workspace to support custom
   MCP servers. Later machines do not require another plugin or device endpoint.
6. After OAuth, call `list_devices`, select the intended device, then call
   `bridge_status` with that exact `device_id`. This authenticated MCP read is
   the setup verification signal; `tools/list` alone is not sufficient.
7. Pass the stable returned `device_id` on every machine operation. When display
   names are ambiguous, identify the correct machine first. Local computer,
   terminal, files, desktop and background browser permissions still must be
   approved on the actual target Windows device.

`udb setup --status` and other diagnostic-only flags do not initiate approval.
A browser approval never grants local Windows computer access, and an MCP tool cannot
approve enrollment or Windows permissions. A device going offline is never substituted
by another machine. A failed or uncertain mutating call is **not** replayed.

## Verification boundary

The synthetic Node tests cover identity isolation, duplicate display names,
2+1 enrolled devices with an unchanged schema, parallel target IDs, independently
revocable per-target permission, offline/reconnect, lost registry acknowledgements,
old endpoint preservation, link-owner refusal, and no automatic mutation retry.
Python source tests cover expected setup and recovery invariants.

**Not accepted until independently verified:** two actual Windows agents under one
connected ChatGPT plugin, a third Windows enrollment, real cloud Access identity and
OAuth, real UI/Windows ACL revocation and reboot reconnect, staging deployment, and
the installed public EXE containing the new Python. A GitHub CI pass and Wrangler
dry-run are distinct from those live tests.
