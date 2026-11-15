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

## Isolated staging resources provisioned (2026-11-15)

Cloudflare Access application **UDB Fleet Isolated Staging MCP** was created
with application ID `d6c82311-ce00-4709-ae2a-61c3e4005a8f`.
It exclusively targets
`udb-fleet-isolated-staging.hkhoinguyen72.workers.dev/v1/account/mcp`.
A fresh read-back confirmed Managed OAuth, ChatGPT DCR callback patterns,
a one-hour Access session, and a single Access policy. On 2026-11-15,
the owner explicitly approved one test login. The previously deny-everyone
policy was updated in place to **Allow exactly that email**, with no Bypass,
Everyone, wildcard domain or additional login. All other identities remain
denied by Cloudflare Access's default-deny behavior. Do not commit the personal
email address or Access identifiers for that identity into public source.
The application remains hidden from the app launcher.

The separate browser-owner approval application
**UDB Fleet Isolated Device Approval** was also created on
`udb-fleet-isolated-staging.hkhoinguyen72.workers.dev/v1/setup/enrollments/*/approval`
with ID `b443dd85-179d-4ea5-b42d-92ff486bdba2`. This is a distinct
non-OAuth Access application with its own audience. Its single policy
was likewise updated in place to allow only the same owner-approved test
login, with all other identities denied. Both apps were read back after
the change to verify their independent audiences, exact path scopes,
single-email allowlists, and absence of Bypass or Everyone allow rules.

**Isolated Worker now deployed, not production accepted:** On 2026-11-15,
`udb-fleet-isolated-staging` was deployed from source commit
`6a5496e7f8b565f60447ff912d36cdf535e1d576` using a Wrangler 4.162.0
dry-run bundle verified as SHA-256
`7d90943920449fc8670e497df43bb9c714ec7cdc79a974e39db0bd982a4e08fd`.
Cloudflare deployment ID: `404bef3a-95d1-41cf-87d8-ae2994ce2dbb`,
version: `70fa032d-093d-484e-b85c-f154f6c4046b`. The new
`udb-fleet-isolated-staging_DeviceRelay` DO namespace has a different ID
from the existing `udb-private-relay-staging_DeviceRelay` namespace, and
its admin credential was generated independently at deployment.

This is **staging-only account discovery**, not a live Windows enrollment or
a proven ChatGPT OAuth session. `UDB_ENABLE_ACCOUNT_FLEET=true`,
but `UDB_ENABLE_PRIVATE_ENROLLMENT=false`: the request endpoint is intentionally
unavailable until a separately approved, non-public enrollment plan exists.
Owner/Companion execution switches are also false. The old
`udb-private-relay-staging` Worker and its device/approval Access apps,
permissions, secrets and Durable Objects remain unchanged.

Read-only remote smoke checks after enabling only this isolated Worker's
`workers.dev` subdomain: `GET /health` 200; protected-resource metadata
200, matching the exact account resource; OAuth issuer matches, PKCE S256,
authorization-code and refresh grants are advertised; unauthenticated GET
and POST `/v1/account/mcp` both 401 with `WWW-Authenticate`;
`POST /v1/enrollments` 404. The setup capabilities report
`browser_enrollment=false` and `account_fleet=true`. No OAuth client was
registered, no account signed in, and no device paired during this check.

**Rollback:** disable the new script's `workers.dev` subdomain or disable its
isolated Fleet flag. Do not roll back or delete any data in the existing
`udb-private-relay-staging` Worker or namespace.

The reviewed candidate file
`cloudflare/wrangler.fleet-isolated-staging.jsonc` uses the independent
Worker name `udb-fleet-isolated-staging` and its own
`new_sqlite_classes: ["DeviceRelay"]` migration. It does **not** inherit
the live staging Worker name or Durable Object namespace, and contains no
runtime secrets, approvals, routes or implicit Fleet-enabled flags.
Run the offline guard `python -m tools.check_fleet_isolated_config`
before any separately approved deployment. Do not deploy using the default
`wrangler.staging.jsonc`, which deliberately targets the live relay.

**Before enabling enrollment or accepting production:** the isolated
deployment has fresh credentials, a pinned owner UUID and separate Access
audiences. A user must still complete real OAuth consent for the test endpoint,
and the owner must separately approve a disposable Windows device.
To test two-account isolation, obtain a second independently approved
test identity. Keep public enrollment disabled until there is a reviewed
source restriction or explicit owner approval to accept pending requests.
Never copy live device tokens, owner grants, Credential Manager values or
Durable Object namespaces into the test Worker. Do not expand this Access
allowlist without separate, explicit owner approval.

## Safe one-machine canary enrollment without public registration

The staging Worker keeps `UDB_ENABLE_PRIVATE_ENROLLMENT=false` until an
attended Windows owner explicitly selects a **disposable UDB_HOME** and a
specific Windows request ID. Existing `udb` managed installs, device tokens,
autostart keys and Active Agents must not be overwritten for this test.

With a CI-verified canary executable in a separate folder, open a Windows
terminal as the device owner and set these variables for **this process only**:

```powershell
$env:UDB_HOME = "$env:LOCALAPPDATA\UDB-Fleet-Canary\profile"
$env:UDB_SETUP_RELAY = "https://udb-fleet-isolated-staging.hkhoinguyen72.workers.dev"
& "$env:LOCALAPPDATA\UDB-Fleet-Canary\portable\UDB\udb.exe" setup
```

The `UDB_SETUP_RELAY` override accepts only the exact built-in legacy
staging relay or this **pinned isolated Fleet test relay**. It never changes an
existing device's pairing. When browser enrollment remains locked, this
attended command stores a *new* recoverable identity in the canary profile's
Windows Credential Manager, prints only `Pending device ID` (32 hex digits),
and returns incomplete. It does not send a registration, open a browser or
grant Windows permissions at this stage.

After checking that ID against the owner-controlled machine, the operator
must update **only the isolated Worker**, atomically configuring
`UDB_FLEET_REQUIRE_REQUEST_PIN=true`,
`UDB_FLEET_ALLOWED_REQUEST_ID=<the exact pending ID>`, and
`UDB_ENABLE_PRIVATE_ENROLLMENT=true`. When the request pin is absent,
browser enrollment remains 404; when a different ID is submitted, it remains
404 without creating a pending record. The legacy anonymous
`POST /v1/enrollments` is always disabled while this staging pin gate is
active. Verify these denial paths before rerunning `udb setup`.

On the next **attended** run, the saved ID/proof/token are reused. The
owner must compare the printed fingerprint and device ID with the protected
Cloudflare Access approval page and explicitly approve or reject; ChatGPT
OAuth is a separate user action. Decline sign-in autostart for canary tests
unless explicitly requested. After approval, turn private enrollment off again
without changing any existing device credentials or Durable Object namespace.

Never copy a live `cloud-pairing.json`, Credential Manager item, device
token, UDB manager permission grant, or auto-start registry entry into the
canary. The established managed UDB process and its original relay stay live
throughout. This procedure is staging-specific and not a general public
fleet-enrollment feature.

## Read-only OAuth preflight (isolated staging only)

Once a separate owner-scoped Access application protects the **exact**
`/v1/account/mcp` path, and the isolated Worker has all Fleet flags enabled,
run the following without any login, device credentials or token registration:

```powershell
python tools/check_chatgpt_oauth.py --relay "$env:UDB_STAGING_RELAY" --account-fleet
```

This checks the account-specific RFC 9728 metadata, pinned Cloudflare Access
OAuth issuer, PKCE S256, advertised refresh-token support and the expected
unauthenticated 401 challenge on the **account** resource. A disabled Fleet
endpoint or missing Access application must fail this check, not pass on the
legacy device endpoint. The old `--device-id` mode is still supported for
independent per-device staging diagnostics.

By default, the preflight is **read-only**: no OAuth registration, login,
consent, grant, token, device enrollment or Windows action. Its explicit
`--register-client` option performs a DCR write and must only be used after
separate owner/operator approval. Even successful discovery and DCR are **not**
evidence of an authenticated ChatGPT call. Check actual `list_devices` and
`bridge_status` after the owner approves OAuth.

A temporary Cloudflare Access JWKS/key-service outage may return HTTP 503;
it is not a request to rotate device credentials or approve OAuth again.
An expired or unverifiable runtime identity still requires user sign-in.

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
