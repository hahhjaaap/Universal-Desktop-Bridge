# UDB audit and staging verification — 2026-11-09

This is an engineering verification record, **not** a claim that ChatGPT OAuth
is complete or that all 59 tools are available remotely.

## Changes made on this audit branch

1. Reject malformed, oversized, or structured JSON-RPC IDs before generating
   protocol errors; enforce the same limit in the internal RPC validator.
2. Parse HTTP Content-Length only as a safe nonnegative decimal integer.
   Fractional, exponent, negative, and precision-losing values fail closed.
3. Accept the legacy MCP `notifications/initialized` **without an ID**, after
   the verified subject/device grant and version validation. Invalid requests,
   ID-bearing notifications and malformed parameters remain rejected.
4. Add regression tests for each case. The notifications test was observed
   failing before its implementation was fixed.

## Verification

- The original audited Windows source worktree: 1,467 Python tests passed,
  35 skipped, 29 subtests passed, approximately 8m36s. This result predates
  the final audit-branch patches; it is not a substitute for branch CI.
- The patched Cloudflare worker: 123/123 Node tests passed locally.
- GitHub Actions [audit workflow](https://github.com/hahhjaaap/Universal-Desktop-Bridge/actions/workflows/udb-audit-regressions.yml)
  checks Cloudflare/Render, Python security, full Linux Python, full Windows
  Python and Windows packaging/host smoke. Consult the *latest run* rather
  than treating past successful runs as current.
- Existing frozen UDB 0.11.0 reported exactly 59 public local MCP tools,
  including 67 internal backend routes (36 core, 31 companion).
  **Only six explicit project-read tools are currently offered by the
  Cloudflare edge catalog**. The 59-tool local inventory is not a remote
  permission grant or an end-to-end test.

## Cloudflare staging deployment

- Worker: `udb-private-relay-staging`, not the production worker.
- Audit version: `923ecf56-fa29-400c-96ec-0626a248b916`.
- Previous version for rollback: `4bb1c314-e758-4e02-822c-12d25b8d30e3`.
- Upload was accepted only after SHA-256 matched the audited Wrangler bundle,
  and Cloudflare verified strict inheritance of one Durable Object binding,
  five existing secrets and the catalog opt-in variable.
- Public staging `/health` returned OK; standard OAuth metadata matched
  the device resource and issuer; unauthenticated MCP returned HTTP 401.
- The existing paired Windows test device was observed registered and online
  after launching the read-only Cloud Agent as a separate visible, minimized
  process. This agent is **not** registered for automatic login startup.
- No production Worker, Access grants, account identity, pairing token or
  application data was changed by these fixes.

## Outstanding acceptance gates

- ChatGPT `udb-staging` OAuth consent and an authenticated
  `bridge_status → list_projects → read_file` sequence from ChatGPT have
  **not** been demonstrated.
- The standalone Windows Cloud Agent currently needs an owner-controlled
  startup; if it exits or Windows restarts, remote execution becomes
  unavailable. Do not add hidden automatic remote access without explicit
  owner opt-in.
- The full 59-tool catalog needs device-specific permission design, per-tool
  approval, schema parity and an independent security review before being
  exposed to external users.
- The installer has automated tests, but new users' true one-click onboarding
  (permissions, OAuth and signed executable reputation) needs a fresh
  acceptance run.
- Older feature branches and closed PRs have not been automatically merged
  into `main`. They remain separate work until reviewed.

## Safe rollback and acceptance

If an authenticated staging request regresses, use Cloudflare Workers
version/deployment rollback to select the previous staging version above,
preserving existing bindings. Rollbacks do **not** undo application data
changes. Do not deploy this branch to production based solely on unit tests.

After ChatGPT App OAuth becomes available, confirm that the resource URL and
Cloudflare Access application match, complete owner consent in ChatGPT, call
`bridge_status`, and read a disposable fixture through `read_file`. Compare
its returned SHA-256 with the local fixture; verify a different device/subject
is denied and revoked grants take effect.
