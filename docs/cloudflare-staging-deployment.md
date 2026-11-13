# Dedicated Cloudflare staging deployment for TD-02 (#94)

> **UDB 0.12.0 docs review (2026-11-13):** **Historical design/evidence, not a current runbook.** Earlier experiments, metrics and version-specific status do not establish current v0.12.0 behavior; never execute obsolete deployment/transport instructions. See [version/status](current-version.md).

> **Current single-gateway setup (11/11/2026):** The former production
> `udb-private-relay` Worker and its Access application have been removed.
> Both `cloudflare/wrangler.jsonc` and `wrangler.staging.jsonc` now target
> `udb-private-relay-staging`. The staging/production separation described
> below is historical. Refer to [current deployment operations](../cloudflare/STAGING-OPERATIONS.md)
> and run the manual `UDB staging gateway deploy (manual)` workflow. Do not
> follow the older production-worker deployment steps below.

**Archived two-Worker design:** The sections below originally described a
separate staging deployment alongside a now-deleted `udb-private-relay`
Worker. They are kept as historical acceptance context, not instructions to
recreate that Worker. The current owner-controlled deployment uses only
`udb-private-relay-staging` as documented in
[STAGING-OPERATIONS.md](../cloudflare/STAGING-OPERATIONS.md). A successful
deployment alone does not grant ChatGPT read access.

## Safe configuration and owner-controlled deploy

Both `cloudflare/wrangler.jsonc` and `cloudflare/wrangler.staging.jsonc`
now target the **same** `udb-private-relay-staging` Worker, retaining the
reviewed `DeviceRelay` class and SQLite migration history. Neither file
contains routes, credentials, OAuth audiences, user identities or device
tokens. Do not recreate the deleted production-named Worker.

Run first from the repository root:

```shell
python tools/check_staging_worker_config.py
```

The validator is entirely offline. It checks both Wrangler files for the
same staging identity, forbids alternate Worker names, routes, environment
variables and custom account IDs, and enforces expected Durable Object
bindings/migrations. It outputs only fixed non-secret status fields.

Before any deployment, the owner must review the Cloudflare account, existing
Worker revision, grants and separate `udb-staging` GitHub environment approval.
For source/config validation only, from the reviewed checkout:

```shell
python tools/check_staging_worker_config.py
cd cloudflare
npx wrangler deploy --dry-run --config wrangler.staging.jsonc
```

**Do not deploy from the historical command sequence in this document.** The
current approved deployment entry point is the manually dispatched GitHub
workflow **UDB staging gateway deploy (manual)** on reviewed `main` (with its
required environment protection). Its package script explicitly uses
`wrangler deploy --config wrangler.staging.jsonc --keep-vars --strict`.
Never infer approval from a successful dry run. Record the deployed revision
privately and preserve existing Durable Object state and grants.

The staged code defaults to denying authenticated MCP requests until its
separate authentication and grants have been explicitly configured. In the
staging account only, create a **device-path-scoped** Cloudflare Access MCP
application with Managed OAuth; do not protect the whole Worker (the device
WebSocket uses a different path). Configure the intended issuer/audience,
reviewed owner identity and **read-only** per-device tools through private
Cloudflare settings. Never place those values or tokens in GitHub, public
artifacts, the staging config, logs or a conversation.

Pair a **disposable staging device** rather than reusing the current production
device token. The local test project should be generated with
`tools/prepare_staging_fixture.py` and registered with read-only permission;
no real owner directory or full-computer grant should be exposed. Keep
`UDB_ENABLE_DEV_ADMIN_RPC` disabled.

## Access metadata compatibility

A path-specific Cloudflare Access application may challenge an unauthenticated
MCP request with a **path-scoped** resource metadata URL, not only the generic
origin-level `/.well-known/cloudflare-access-protected-resource/` document.
The public preflight accepts either shape **only on the paired HTTPS Worker
origin**. For the path-scoped form, it requires the exact paired device MCP
path and checks that the returned resource equals that MCP URL; another
device, URL query, external origin or broadened resource is rejected.

This confirms an edge challenge and public metadata only. It cannot establish
that the approved owner authenticated, that the Worker has a valid application
AUD/grant, or that ChatGPT can read a file. Keep the authenticated-read and
denial/revocation steps below separate.

## Evidence gates (do not collapse them)

1. **Source/CI:** full Linux/Windows/Node tests pass for the exact reviewed
   source; staging configuration validator passes.
2. **Deployment:** verify the separate staging Worker and exact version.
   If using the dedicated read-only preflight, configure reviewed *non-secret*
   `UDB_STAGING_RELAY` and `UDB_STAGING_DEVICE_ID` in its approved environment.
   Run the `Cloudflare staging read-only preflight` workflow manually. Success
   proves metadata and unauthenticated rejection only, not live ChatGPT access.
3. **Authenticated live call:** sign into the staging device MCP connection
   in ChatGPT with the approved owner identity. Discover the granted subset
   of `bridge_status`, `list_projects`, `list_files`, `read_file`,
   `search_files`, `check_python_syntax`. Verify the synthetic README
   content and SHA-256 against the fixture manifest. No write, terminal,
   desktop or approval method may be discovered or called.
4. **Denied and lifecycle calls:** another subject and device, protected
   `.env`, out-of-project `../outside.txt`, expired OAuth, revoked grant,
   disconnected and reconnected agent must behave as in
   [the acceptance runbook](cloudflare-project-read-acceptance.md).
   Do not replay an uncertain mutation.
5. **Repeatability:** capture 30 allowed read outcomes on at least three
   network conditions, all expected denials and a reviewed security sign-off.
   Record only pass/fail codes, the reviewed deployment SHA and synthetic
   hashes; never publish access tokens, identities or user files.

A ChatGPT UDB plugin advertising only metadata tools is **not** proof that
project-read tools are available. The owner must refresh the actual MCP
connection/tool catalog and test reads after the reviewed Worker, Access
policy, device permissions and local project have been verified.

Regardless of GitHub issue status, do **not** treat this acceptance gate as
passed until real OAuth consent, successful read, denial, revoke/reconnect
and repeatability have been independently observed and recorded. If any gate
fails, do not change owner permissions or redeploy the deleted Worker.
