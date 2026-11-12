# Staging gateway: source and deployment

The single active UDB Worker is `udb-private-relay-staging`. The earlier
`udb-private-relay` Worker was deleted. Do not redeploy that legacy Worker.

## Recovered source

The six changed `cloudflare/src` modules in this branch were recovered from
**deployed staging Worker v31**, version
`d14f6259-03d0-4df5-8869-0768624b6646` (2026-11-11 08:09 UTC).
The other seven JS modules matched `main` exactly. The deployment may evolve:
recheck Cloudflare before making another release. This snapshot does not include
secret values or Cloudflare Access app configuration.

## Safe release process

1. Review PR, verify CI and owner/Companion grant tests. Never merge unreviewed
   changes to authentication, device permissions or the Live UI.
2. Configure the GitHub **udb-staging** environment with required reviewers and
   its own `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` secrets, restricted
   to staging. No Cloudflare tokens belong in the repository or logs.
3. Manually dispatch `UDB staging gateway deploy (manual)` from `main`.
   It runs tests and a local config check before using `npm run deploy`.
4. Deployment explicitly uses `wrangler.staging.jsonc --keep-vars --strict`
   to avoid recreating the deleted legacy Worker, preserve dashboard vars and
   fail on conflicting remote changes. Existing Worker secrets remain secret.
5. Verify Cloudflare Access authentication, the real ChatGPT MCP catalog,
   `bridge_status`, `list_projects`, authorized `read_file`, and rejection
   of unauthorized paths and devices. Record the deployed version.

Both `wrangler.jsonc` (the implicit Wrangler default) and
`wrangler.staging.jsonc` now name the **same existing staging Worker**. The
offline validator requires identical permitted configuration in both files
and rejects the deleted legacy Worker identity. Run the reviewed `npm run
deploy` or the manual GitHub workflow instead of bare Wrangler, because the
reviewed command includes `--keep-vars --strict` to protect remote settings.

## Security boundaries

The UDB catalog contains 59 tools, but catalog visibility is not authorization.
Cloudflare Access and per-device grants are required; Windows permissions,
local approvals, and scoped projects remain independent enforcement layers.
In particular, enabling `computer` access exposes current-user file,
execution and desktop capabilities that are not sandboxed. Review those grants
locally before using such tools.
