# Project reads through Cloudflare: deployment and acceptance

> **Docs reviewed 2026-11-13 — UDB 0.12.0:** **Staging/opt-in scope.** Features and grants described below are not enabled for arbitrary devices and are not proof of a live ChatGPT connection. Check [current-version.md](current-version.md) and the installed `udb --version` before using commands.

This runbook is for the account/device owner. A merged PR, public health response,
local stdio test or simulated Worker test does not establish ChatGPT end-to-end access.
The Windows stable installation, existing SQLite data and owner grants remain in place.

## Source fixes and the four independent boundaries

PR #85 allows `list_files`, `read_file`, `search_files`, `check_python_syntax`
in addition to the two metadata tools. That source allowlist is separate from:

1. The **deployed** Worker version and its OAuth/Access policy.
2. The exact authenticated subject/email's **per-device** `UDB_DEVICE_GRANTS`.
3. The Windows local project registry, protected paths and read permission.
4. The MCP catalog cached by the ChatGPT connection/plugin.

No reconnect or code deployment automatically changes a grant. Never add write,
execution, desktop, approval or legacy tools to `udb:read`. Local project edit/test
workflows use their existing, separate owner approvals; this gateway remains read-only.

The relay uses the same six-tool classification for authorization and concurrent
read scheduling. Up to ten read RPCs can run on separate local stdio workers;
an outstanding RPC cannot move onto a replacement device socket.
After reconnect a fresh local proxy initializes and sends the initialized
notification before forwarding a resumed call, with one shared deadline. It never
replays that call. `initialize` reports the actual negotiated device protocol.

The dedicated staging Worker configuration and owner-controlled deployment
steps are documented in [the staging deployment guide](cloudflare-staging-deployment.md).

## Pairing versus staging: safe public-readiness comparison

When a staging Worker has the project-read capability but \`udb doctor --cloud\`
still reports \`project_read_not_advertised\`, first verify that the **local
existing pairing and staging refer to the same Worker**. A successful public
staging probe cannot fix a different paired Worker.

From an isolated source checkout on the Windows owner's machine:

\`\`\`sh
python tools/compare_cloudflare_worker_readiness.py --staging-relay https://udb-private-relay-staging.example.workers.dev
\`\`\`

Replace the example hostname with the owner's separately reviewed staging
Worker (not production). The helper uses the default owner home unless
\`--home\` explicitly targets a disposable test home. It validates local
pairing with the same Cloud Agent URL checks and reads **only** the non-secret
\`cloud-pairing.json\` file. The only outgoing requests are unauthenticated
\`GET /health\` for staging and the currently paired Worker. It never sends
a device ID, device token, OAuth credential, project path, grant or mutation.
It refuses unsafe/non-staging URLs and follows no HTTP redirects.

The JSON response contains only fixed status labels, public capability flags
and a boolean \`pairing_matches_staging\`, never either hostname or a device
identifier. If the Workers differ, do **not** overwrite the working pairing:
make an independently paired disposable staging device first. If they match,
continue with a real authenticated test; public health does not prove user
authorization, ChatGPT connection or Windows file access.

## Automated staging-only preflight (manual)

The workflow [Cloudflare staging read-only preflight](../.github/workflows/cloudflare-staging-read-preflight.yml)
can be run manually after a **separate staging** Worker and disposable staging
device are provisioned by the account owner.

Configure GitHub environment `udb-staging` with the non-secret environment
variables `UDB_STAGING_RELAY` and `UDB_STAGING_DEVICE_ID` (do not put a
Windows device token or any OAuth credentials in these variables). The
staging Worker hostname must contain `staging` and end in `.workers.dev`,
to prevent this workflow from inadvertently testing a personal production
Worker. Use a dedicated disposable project and device; avoid real private
project contents.

From GitHub Actions, select **Cloudflare staging read-only preflight** →
**Run workflow**. It installs the checked-out source and runs
`check_cloudflare_deployment.py --auth-mode cloudflare-access
--require-project-read`. It makes only public health/metadata requests
and one **unauthenticated** MCP request expected to be rejected. The
workflow provides no production secret and does **not** deploy Workers,
change Access policies, start Windows UDB or update device grants.

A successful run is necessary but **not sufficient** for end-to-end
acceptance. An authorized owner must still prove authenticated ChatGPT
`tools/list` and `read_file` on the staging device, verify a local file
hash and negative access cases, and check revocation/reconnect. A failure
`project_read_not_advertised` means the deployed staging Worker is not
yet advertising the scoped-read source capability.

## Before deploying

- Review the source commit and successful **complete** CI matrix, including Node
  gateway tests and Windows Python 3.11/3.12 and EXE acceptance.
- Record the current Worker deployment/version in Cloudflare and retain its code
  revision. Save the existing private grant configuration outside the repository.
  Worker code rollback does **not** restore separately changed secrets or policies.
- Use an isolated registered test project first, with known README content/hash.
  Do not replace the stable Windows application to test this Worker change.
- If updating the Windows cloud agent is needed, test a separate source checkout
  against the isolated project first. Stop/start the existing cloud-agent process
  through its local manager; never run two agents with the same device secret.
- Use the account owner's local Cloudflare login/credential. Do not send a token,
  device secret, identity grant JSON or OAuth session to ChatGPT or GitHub.

From an authorized account terminal, in the reviewed checkout's `cloudflare/`:

```sh
npm install
npx wrangler whoami
npx wrangler versions list
npx wrangler deploy --dry-run
npx wrangler deploy
```

Check the configured Worker/account before the final command. Preserve Durable
Object binding/migration history. Do not use Worker-level Access protection on the
device WebSocket; use the existing device-MCP-path Access application. Preserve
the real issuer/audience and owner-only login policy. Keep admin RPC disabled.

Only if the owner explicitly authorizes those project reads, update their existing
device/subject entry privately to list the four approved tool names (retain other
identities/devices unchanged). Use Wrangler's interactive secret entry or the
account Dashboard. Do not put the JSON into `wrangler.jsonc`, a shell transcript,
CI logs or a committed `.dev.vars`. Use the existing policy's actual subject/email,
not an invented identity. No read grant authorizes source writes or execution.

## Diagnose before reconnecting ChatGPT

On Windows: `udb status --json`, `udb doctor --json`, and confirm the local cloud
agent has connected. Local tunnel readiness and the separate Cloudflare device
connection are different observations.

For an already-paired standalone build, run this on the original Windows machine:

```sh
udb doctor --cloud --json
```

It reads the existing `cloud-pairing.json` to select the public relay/device, so
there is no need to remember or paste the MCP URL. It does not read device tokens,
change configuration/grants, connect a device, or retry failed requests. The normal
`udb doctor --json` stays network-free. Public requests have an 8-second timeout
per request (up to three requests); redirects are refused. This diagnostic does
not need the local agent to be running. The overall doctor exit status can still
be 2 when the manager or other local checks are unhealthy; inspect the separate
`cloud_preflight` result.

The default checks Cloudflare Access Managed OAuth. For a deployment deliberately
configured with external JWT authentication, use
`udb doctor --cloud --cloud-auth-mode jwt --json`.
`passed_public_preflight` proves only public routing, advertised read capability,
and unauthenticated OAuth denial. `windows_device`, `chatgpt_oauth` and
`authenticated_project_read` stay `not_tested`; complete the staging fixture and
ChatGPT acceptance steps below before declaring the connection usable. Diagnostic
output omits the relay, device ID and raw upstream errors.

From a source checkout, using the real non-secret relay origin/device ID:

```sh
python tools/check_cloudflare_deployment.py --relay https://YOUR-WORKER.workers.dev --device-id YOUR_DEVICE_ID --auth-mode cloudflare-access --require-project-read
```

`project_read_capability=deployed` means the code advertises project-read support.
`not_advertised` can mean older code; it does not establish whether a private grant
allows reads. The preflight sends **no credentials**, verifies unauthorized denial
and Managed OAuth discovery, and explicitly reports device/ChatGPT as untested.

If initialization fails, sanitized `diagnostics.reason` distinguishes `device_offline`,
`device_busy`, `device_connection_changed`, and unknown transport outcomes. Reconnect
the local agent when offline, or let the active request finish when busy. No client
mutation or timed-out request is automatically replayed. The original
`device_initialize_unavailable` error remains for compatibility.

### Public preflight gate for staging

The `--require-project-read` flag rejects a Worker whose public `/health`
response does not advertise `X-UDB-Project-Read-Capable: 1`. A failure
prints a fixed diagnostic code, `project_read_not_advertised`, **without
printing** the relay URL, device ID, tokens or response body. An unexpected
403 or missing edge OAuth challenge reports
`oauth_challenge_missing_or_wrong_status`, and is **not** evidence that
Managed OAuth was configured successfully.

This is **only** a code/deployment and unauthenticated denial check.
A successful public preflight must still be followed by an actual
authenticated tool call from ChatGPT, on a registered test project and a
deliberately scoped owner account. Do not try to retrieve, copy or log the
ChatGPT OAuth token to make a command-line test succeed.

Required human-reviewed evidence from an isolated staging environment:

| Boundary | Acceptance evidence |
| --- | --- |
| Worker version | Reviewed deployed SHA, correct `/health` capability |
| Access policy | Authenticated identity and exact device-specific MCP path |
| Grant | Allowed tools match the owner-approved subject/device entry |
| Windows project | `read_file` returns expected fixture bytes and SHA-256 |
| Denial | Wrong subject/device, outside project and unsafe tools all denied |
| Lifecycle | Disconnect, reconnect, expiry, revoked grants checked without tool replay |
| Operational | No credentials/file contents included in shared reports |

A missing Worker capability flag is the first blocker, **not** an invitation
to add broad scopes or disable authentication. If the ChatGPT plugin catalog
lists only `bridge_status` and `list_projects`, verify Worker deployment
and per-subject grants before attempting reconnects. The Worker does not
automatically update the plugin's registered tool catalog.


For a deterministic, disposable local project and expected SHA-256/denial cases,
see [the offline staging fixture guide](staging-fixture.md). Creating the fixture
alone does not establish authenticated Cloudflare/ChatGPT access.

## Authenticated acceptance in ChatGPT

1. Refresh/reconnect the exact device MCP connection and complete the owner OAuth
   login/consent. A fixed plugin tool allowlist also needs an owner-managed catalog
   refresh; a Worker deployment cannot edit that plugin configuration.
2. Discover tools. Confirm exactly the granted subset, with complete `inputSchema`
   objects for `list_files`, `read_file`, `search_files`, `check_python_syntax`.
   A missing tool is not proof of a Windows file permission failure.
3. In the isolated registered project, list files, read `README.md`, search a known
   string, and syntax-check a known `.py` file. The read must match the expected
   relative path, text and SHA-256 from the owner's local file. Record the reviewed
   Worker version and local UDB version; do not publish file contents or tokens.
4. Verify protected files and an **existing synthetic fixture outside that project**
   are denied. Check another device and an ungranted identity fail. Inspect discovery
   to confirm no write, terminal, desktop or approval tool is exposed.
5. Disconnect the test agent: calls must fail. Reconnect: discovery/read may resume
   with a new local handshake, without replaying earlier calls. Revoke the test
   device/subject grant: new calls must be denied. Restore only the owner-approved
   prior configuration after testing.

Only those real authenticated observations establish this path. Tests in this
repository cover the Worker/DO with controlled fixtures and the actual local
stdio/project workflow separately; they do not substitute for this production test.

## Read-burst reliability gate (10 concurrent requests)

The staging reliability experiment on 2026-11-06 proved 30/30 sequential
ChatGPT reads but only 17/30 valid responses under five concurrent reads
(issue #94). Do not mark burst concurrency accepted from sequential results.

The new relay scheduler permits **up to ten active read-only requests**
for a paired device. Its Windows agent lazily starts at most ten independent
stdio proxies and runs these calls in parallel threads. The eleventh active
request returns HTTP 429. Mutation RPCs are **exclusive** and cannot overlap
with reads or another mutation; this is not unrestricted parallel desktop
control or simultaneous file writes.

Owner-gated `host_status` and `computer_status` observations also share read slots.
This is scheduling only: they still require their separate owner/device grants
and are not added to the `udb:read` authorization scope. Other owner actions remain
exclusive; busy or unknown-outcome mutations are never replayed.

The special staging fixture grant authorizes `read_file` only for `README.md`
with exactly `project` and `path`. Other fixture files and batch reads remain
denied. Both edge and Windows-backed discovery advertise this narrow signature;
a fixture denial returns static guidance for the permitted call. It does not
broaden the owner's grants to a real project.

Each RPC has a distinct correlation ID and a bounded local timeout. A
connection timeout, poisoned local worker, or socket replacement fails
outstanding calls without replaying them. Per-device identity grants and
Windows owner permission checks are unchanged. Real throughput depends
on Windows CPU, memory, the startup cost of independent stdio workers and
network conditions, so ten active calls is **not** a guarantee of 10× speed.

After source CI and a reviewed deployment **only to the isolated staging
Worker**, repeat the real owner-authenticated ChatGPT fixture test:

- 30 batches of five simultaneous `read_file` calls, each returning both
  fixture SHA-256s and expected contents; separately try a burst of ten.
- Verify the eleventh concurrent read is rejected, mutations are exclusive,
  and unexpected identities/devices, revocation and protected paths are denied.
  Concurrency must never change `UDB_DEVICE_GRANTS` or local permissions.
- Measure response success rate, p50/p95 latency, HTTP status/reason where
  available, peak active operations and reconnect behaviour. Do not log personal
  data, file content, headers, or tokens.
- Test client timeouts and network-loss cases. **No promise of 10×
  throughput:** process startup, machine load and upstream timeouts can
  still limit completion.
- Keep #94 open until owner OAuth reads, real second-identity denial,
  network-condition matrix and security review all pass.

The test harness and CI only prove deterministic queue properties. The
previous ChatGPT generic internal errors did not expose upstream status,
so their root cause is not conclusively established.

## Rollback and remaining scope

If the Worker regresses, restore the recorded previous Worker version through
Cloudflare Deployments (or `wrangler rollback PREVIOUS_VERSION_ID` from the authorized
terminal). Restore private grants/policy independently if they changed. Stop only
the test cloud agent and return to the prior local agent. Windows installation
rollback remains a separate owner operation; no automatic stable replacement is
part of this runbook.

Remote writes/execution require a separately reviewed scope/approval design.
The existing Common Room/Task Board and SQLite GUI remain the shared workspace;
no second workspace database or GUI migration is introduced by these fixes.
# MCP protocol compatibility

The gateway accepts both the existing 2025 handshake clients and the
2026-07-28 stateless tool/discovery requests. The latter must supply matching
protocol/method/name headers and per-request protocol metadata. Authentication
and per-owner/device grants apply to both paths. Modern metadata is removed
before forwarding to the existing 2025 Windows stdio proxy; its local bootstrap
and serial execution remain unchanged. Discovery/catalog responses are private
and not cacheable across identities. No additional backend RPC method is enabled.

The gateway is **dual-era**: authenticated `server/discover` accurately lists
both `2026-07-28` and the supported 2025 initialize-handshake revisions.
This is intentional and permitted by the MCP versioning specification;
it is not permission to use a newer tool or bypass the local approval rules.
After authenticating the Access identity and exact device grant, unsupported
protocol versions now return HTTP 400 with a JSON-RPC
`UnsupportedProtocolVersionError` (`-32022`) and the fixed list of
supported versions. A mismatch between the HTTP protocol version and
per-request metadata instead returns `-32020`. Malformed RPC IDs and
oversized version headers fail without reflecting the untrusted value.

During the live staging investigation, rejected requests carried
`MCP-Protocol-Version: 2026-07-28` and received HTTP 400, while legacy requests
and dispatched device RPCs returned 200. Increasing FIFO capacity alone does
not resolve protocol-version rejection. Repeat real ChatGPT burst tests after
deploying compatibility changes; do not infer live success from offline tests.

References: [versioning](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning),
[HTTP validation](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http),
and [discovery](https://modelcontextprotocol.io/specification/2026-07-28/server/discover).
