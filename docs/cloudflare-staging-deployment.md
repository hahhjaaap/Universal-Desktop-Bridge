# Dedicated Cloudflare staging deployment for TD-02 (#94)

This runbook covers a **separate staging Worker**, not a replacement for the
current personal/production `udb-private-relay` Worker. It does not grant
remote access or establish authenticated ChatGPT reads by itself.

## Safe configuration and owner-controlled deploy

The opt-in file `cloudflare/wrangler.staging.jsonc` names
`udb-private-relay-staging`, keeps the reviewed `DeviceRelay` class and
SQLite migration history, and defines **no** routes, credentials, OAuth
audience, user identity, device token or production account. The standalone
config does not inherit the production Worker's Durable Object storage.

Run first from the repository root:

```shell
python tools/check_staging_worker_config.py
```

The validator is entirely offline. It rejects renamed production Workers,
routes, environment variables, custom account IDs and changed Durable Object
bindings/migrations. It outputs only fixed non-secret status fields.

An account owner must review the Cloudflare account and Worker before any
deployment. From the reviewed source checkout:

```shell
cd cloudflare
npx wrangler whoami
npx wrangler deploy --dry-run --config wrangler.staging.jsonc
npx wrangler deploy --config wrangler.staging.jsonc
```

**Only the final command changes Cloudflare infrastructure.** Do not run it
without an authorized staging account and explicit owner review. Never use
`wrangler deploy` without `--config wrangler.staging.jsonc` for this test.
Keep the current Worker deployment version, Durable Object data and private
grants unchanged. Record the deployed staging Worker version/commit privately
so the owner can roll it back.

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

## Evidence gates (do not collapse them)

1. **Source/CI:** full Linux/Windows/Node tests pass for the exact reviewed
   source; staging configuration validator passes.
2. **Deployment:** verify the separate staging Worker and exact version.
   Configure the GitHub `udb-staging` environment with *non-secret*
   `UDB_STAGING_RELAY` and `UDB_STAGING_DEVICE_ID`. Run the
   `Cloudflare staging read-only preflight` workflow manually. Its success
   proves metadata and unauthenticated rejection only.
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

The current ChatGPT UDB plugin advertising only two metadata tools is **not**
evidence that four new project tools are available. The owner must refresh
the actual MCP connection/tool catalog after the staged Worker, access policy,
device permissions and local project all work.

Keep issue #94 open until real OAuth consent, successful read, denial,
revoke/reconnect and repeatability have been observed. If any gate fails,
leave production untouched; restore only the isolated staging resources.
