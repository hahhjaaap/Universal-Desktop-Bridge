# Project reads through Cloudflare: deployment and acceptance

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

The relay uses the same six-tool classification for authorization and bounded
read queuing. A queued request cannot move onto a replacement device socket.
After reconnect a fresh local proxy initializes and sends the initialized
notification before forwarding a resumed call, with one shared deadline. It never
replays that call. `initialize` reports the actual negotiated device protocol.

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

From a source checkout, using the real non-secret relay origin/device ID:

```sh
python tools/check_cloudflare_deployment.py --relay https://YOUR-WORKER.workers.dev --device-id YOUR_DEVICE_ID --auth-mode cloudflare-access
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
