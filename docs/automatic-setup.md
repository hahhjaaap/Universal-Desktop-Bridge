# Automatic private Windows setup

Run this once from an attended PowerShell console:

~~~powershell
udb setup
~~~

The same command resumes interrupted setup and verifies an existing pairing.
Windows never asks for an invitation, admin key, device token, relay URL or MCP
URL in PowerShell. Existing advanced pairing/connect commands remain supported.

## What the owner sees

1. UDB checks its build identity and available EXE checksum manifest. A checksum
   match is not a publisher signature. Source and unmanaged builds report their
   integrity limitations.
2. A fresh device opens a Cloudflare Access protected approval page. Compare its
   device ID and fingerprint with PowerShell, then approve or reject. Approval
   explicitly permits this owner to read only bridge status through MCP. It
   grants no Windows terminal, desktop, project or file permission.
3. UDB stores the device token in Windows Credential Manager, reuses or starts
   its local support process and Cloud Agent, and offers Windows sign-in startup
   once. Declining is remembered. Existing startup configuration is preserved.
4. A handoff page offers **Copy MCP URL** and **Open ChatGPT Plugins**. Add a custom
   MCP server once, paste that URL in ChatGPT, and personally approve OAuth.
   If account Fleet is enabled, this is the shared `/v1/account/mcp` URL; use
   that same URL for every linked Windows device. Otherwise it is the device URL.
   If the server already exists, use it to call `bridge_status` or `list_devices`;
   do not add a duplicate. Account/workspace availability is controlled by ChatGPT.
5. UDB waits for a successful authenticated MCP read from the actual agent.
   After OAuth, use the connected ChatGPT server to invoke `bridge_status`.
   In Fleet mode, call `list_devices` first and then `bridge_status` with the
   selected `device_id`. Static tool discovery, an open browser, Agent online
   and device-token diagnostics are insufficient evidence.
6. On an opted-in Fleet staging relay, the account MCP endpoint publishes the
   versioned 40-tool catalog even when every Windows device is offline.
   `list_devices` remains available; a call targeting an offline device returns
   an explicit offline error. Discovery does not grant execution. Each operation
   still checks the selected device's ownership, online state and current Windows
   permission; a denied call explains the required local approval without running it.

## Tool discovery and local permission synchronization

`UDB_ENABLE_LOCAL_TOOL_SYNC=true` opts enrolled devices into full discovery.
For one-plugin account Fleet, `UDB_ENABLE_ACCOUNT_FLEET=true` must also be set;
Fleet additionally requires browser enrollment, Cloudflare Access mode and no
`UDB_TENANT_POLICY`. All switches remain off in checked-in Wrangler configs.
Both checked-in Wrangler entrypoints still target staging and retain the
existing deployment configuration guard. Set flags only in an isolated,
authorized staging deployment after acceptance; the existing `--keep-vars`
deployment path preserves them. No production configuration is changed.
Without the flag, enrollment retains its
original status-only behavior. Explicit legacy grants, tenant policies and the
strict issuer-sub pilot remain authoritative and are never widened.
The existing relay-wide `UDB_ENABLE_OWNER_TOOLS` and
`UDB_ENABLE_COMPANION_TOOLS` switches still gate their respective executions;
full discovery does not bypass either opt-out. `udb mcp-config` intentionally
continues to print the legacy per-device URL; in Fleet mode, use the shared
account URL printed by `udb setup`.

Only the immutable enrolled owner can discover this device's full catalog.
Catalog names and schemas come from the actual Windows backend and are filtered
through UDB's existing allowlists/family map. Deprecated aliases and unknown
tools are excluded. Credentials, identity, pairing and Windows permissions are
not modified by discovery.

Before dispatching a newly available operation, the relay reads `bridge_status`
from that same device through its authenticated connection. It validates the
JSON-RPC reply and the Windows permission report. No permission evidence is
cached or persisted as an execution grant.

| Local evidence | Operations admitted by the relay |
| --- | --- |
| No local grants | `bridge_status`; other tools remain visible but blocked |
| Existing readable projects | Registered-project read tools; Windows still checks each requested project/path |
| Attended current-user computer grant with files/execute/desktop capabilities | Computer and companion operations; their existing Windows scope, terminal enablement, project, consent and resource checks still apply |
| Separately approved background access | Background browser/workspace tools; their own Windows checks still apply |

To approve broad computer access locally, run `udb --access computer` and review
the attended `ALLOW COMPUTER` prompt. Revoke with `udb revoke-access`. A local
grant or revocation takes effect on the next call without editing Cloudflare
secrets or re-enrolling. Broad computer consent does not enable background
browser access. No MCP tool can set these permissions.

If the permission read is busy, unavailable, malformed or fails, the requested
operation is not dispatched. A mutating operation is never retried after an
uncertain reply. Windows independently checks permissions again at execution.
An already connected ChatGPT client may need its supported tool refresh or a
reconnection to replace a previously cached one-tool catalog; the relay cannot
force a proprietary client cache refresh or OAuth consent.

Disable `UDB_ENABLE_LOCAL_TOOL_SYNC` or roll back the Worker to restore the
status-only enrollment catalog. No data migration, device reset, token rotation
or Windows EXE update is needed for this server-side feature.

The relay currently cannot independently attest which OAuth client application
made a call. UDB reports **Authenticated MCP: verified**, never **ChatGPT
Connected** based on an Agent heartbeat or an untrusted client name/user agent.
Live ChatGPT acceptance must be recorded separately. There is no supported
programmatic custom-server installation or OAuth-consent bypass in this change.

## State and recovery

| Phase | Durable evidence | Safe rerun |
| --- | --- | --- |
| Inspect | Existing pairing and read-only checks | No credential replacement |
| Owner approval | Separate Credential Manager recovery entry, created before POST | Same request ID, proof and provisional token |
| Registering | DO owner decision and exact registration operation | Retry only identical idempotent registration |
| Cloud Agent | Existing manager and Cloud Agent lifetime lease | Reuse running process; reconnect with existing backoff |
| Autostart | Saved attended consent and existing current-user Run entry | No second prompt or duplicate configuration |
| MCP verification | Device-authenticated challenge and recent authenticated bridge read | Verify again without re-pairing |

Public state/setup.json contains phase, startup decision and a random challenge
hash only. Recovery secrets use a separate per-home Credential Manager target;
the live device credential has its own per-device target. Pairing publication is
atomic and never replaces an existing file. A failure after saving a credential
retains it for recovery; cleanup does not delete a live token.

Unknown general RPC/mutation outcomes are never replayed. The only recovery
retry is the registration operation bound to the exact request, token hash and
verified immutable owner. Device revocation stores a tombstone that prevents a
late registration retry from resurrecting the token. Revoked or missing live
credentials stop setup for owner repair; they never trigger automatic enrollment.

Approval expires after 10 minutes, CSRF after 2 minutes, recovery registration
records after 24 hours, and MCP evidence after 5 minutes within a 30-minute
challenge. Rejected enrollment remains denied for owner diagnosis. Rerunning setup can
renew an expired, never-approved request within the normal rate limit, preserving
the exact device ID, proof and token and invalidating the previous CSRF nonce.
Renewal never approves a device or revives a revoked credential. Run udb setup
again after expiry, network loss, restart or terminal cancellation. A rejected
request requires owner review; setup never silently replaces its identity.

~~~powershell
udb setup --status
udb setup --no-browser
udb setup --json
~~~

These flags are read-only: no enrollment, credential write, browser launch,
process start, autostart change or permission grant. Exit code 0 requires a valid
device credential, an online Cloud Agent and fresh authenticated MCP proof; an
online Agent without that proof remains incomplete. A nonzero result means setup
is incomplete or requires owner repair; JSON does not include secrets.

## Operator provisioning: gated, not automatic infrastructure changes

The packaged pilot relay address is pinned to the existing private staging
origin in private_enrollment.py. It is public routing information, not a shared
credential. Existing devices keep their validated saved relay origin. No CLI
fallback accepts a relay supplied by an unauthenticated response.

**No infrastructure, secret, Access policy or production permission change is
performed by this PR. Browser enrollment is OFF unless explicitly provisioned.
An operator approval and successful isolated staging acceptance are required
before enabling it.**

Provision the following in an isolated staging environment before rollout:

- Existing DEVICES Durable Object namespace, strong UDB_ADMIN_KEY and private
  enrollment opt-in. No new DO class, binding or namespace migration is needed.
- UDB_AUTH_MODE=cloudflare-access with the pinned UDB_ACCESS_TEAM_DOMAIN and a
  managed OAuth Access application for the per-device MCP resources. The
  existing single-device Access path does not cover newly enrolled devices.
- A separate browser-login Access application protecting
  /v1/setup/enrollments/*/approval with a distinct application audience. Configure
  UDB_ENROLLMENT_ACCESS_AUD to that audience.
- A bounded JSON allowlist UDB_ENROLLMENT_OWNER_SUBJECTS of immutable
  https://TEAM.cloudflareaccess.com#USER-UUID subjects. An email header alone is
  never approval authority.
- Explicit `UDB_ENABLE_PRIVATE_ENROLLMENT=true`,
  `UDB_ENABLE_BROWSER_ENROLLMENT=true`, `UDB_ENABLE_LOCAL_TOOL_SYNC=true` and
  (only for the shared account endpoint) `UDB_ENABLE_ACCOUNT_FLEET=true` after
  review. Fleet also requires `UDB_AUTH_MODE=cloudflare-access` and no
  `UDB_TENANT_POLICY`. Strict tenant policy configurations cannot fall back to
  these dynamic status-only grants.
- WAF/network controls in addition to application limits of 4 new requests per
  source/hour, 50/hour overall, 20 pending and 200 recovery records. Identical
  POST recovery does not consume a second enrollment slot.

Approval requires either a signed Access JWT with the pinned issuer/audience or
Cloudflare's trusted `ctx.access` with the approval application's exact audience
and account-scoped `user_uuid`. Both bind to the allowlisted immutable subject;
email alone never grants approval. When native Access identity is available,
it is authoritative and request identity headers are ignored. This path needs
no duplicate signing-key fetch. A wrong application, missing or disallowed
runtime UUID fails closed, even with an otherwise valid assertion. Without
native identity, a signed assertion must pass every verification step.
New-device MCP status grants use the same native account UUID when available,
with the MCP application's distinct audience, and check the device's stored
owner. Existing grants and the strict issuer-sub pilot keep their own rules.
Device fingerprint, short-lived owner/device-bound
one-use CSRF and same-origin POST remain required. No administrator secret goes
to the browser or PC.
The handoff page uses a script nonce, no external script and a user gesture to
copy the public MCP URL.

Use separate staging/production Workers, namespaces, Access audiences and
profiles. A production build must pin its separately approved production relay;
this staging pilot is not a production onboarding rollout. Do not repoint an
existing paired profile or share its device token.

Before any authorized deployment, record the current Worker version/settings,
back up operator configuration without printing secrets, deploy and test the
candidate in isolation, and keep the old version for rollback. Revert the
Worker version and disable the browser opt-in to stop new enrollment; do not
revoke existing devices or delete the namespace. New token hashes use the
existing storage key, so previously paired devices remain compatible. Preserve
new approval/registration state until outcome/revocation is checked.

## Acceptance evidence and outstanding gates

Automated Python tests cover orchestration, no-write diagnostic flags, repeated
runs, existing pairing, lost enrollment responses, credential-save interruption,
agent restart, startup consent and token denial. A Windows-only test exercises
a disposable synthetic Credential Manager recovery entry and deletes only that
entry. Node integration tests use in-memory Durable Object/Windows stand-ins,
real cryptographic JWT signatures, CSRF replay, wrong audience/issuer, expiry,
denial, uncertain registration, revocation, cross-owner/device access and real
MCP handler routing.

CI separately builds Windows EXEs, validates frozen worker imports/catalogs,
checks copied standalone layouts, and exercises managed installation, upgrade
and rollback. Passing these checks is not fresh-device cloud/OAuth acceptance.

Before rollout record, with no secrets:

- Exact candidate commit, Windows build and isolated Worker version.
- Fresh Windows enrollment and explicit owner approval, refusal and expiry.
- Lost network/terminal/reboot recovery using the same pending identity.
- Agent termination/reconnect and repeated setup without duplicate processes.
- ChatGPT custom MCP creation and actual OAuth consent/failure/expiry.
- Authenticated bridge_status from that ChatGPT account to that Windows device.
- Two real accounts/devices denied cross-access, then isolated token revocation.
- Windows autostart after actual logoff/reboot, existing pairing preservation.
- Reviewer approval, rollback rehearsal and separate rollout authorization.

Live owner-PC, browser SSO, ChatGPT OAuth, reboot and real two-account acceptance
remain rollout gates until recorded; simulated checks must not be relabeled as
those live results.
