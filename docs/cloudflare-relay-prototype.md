# UDB Cloudflare relay: security-gated prototype (not released)

This is the initial private Cloudflare Worker + Durable Object relay for 2–3 devices. **It is not yet a one-click installer, public MCP plugin, or OAuth pairing flow.** No Cloudflare deployment has been performed. This opt-in branch does not grant Windows permissions.

## Implemented

- Cloudflare Worker HTTP routing with a private administrator API and per-device routing.
- A hibernatable Durable Object WebSocket per device, with independent device token hashes.
- The Windows `udb cloud-agent` command. It connects outbound using TLS and forwards allowed MCP JSON-RPC requests to the existing local `udb serve` proxy.
- Random device tokens registered by SHA-256 digest; local credentials are not passed through command-line arguments.
- Bounded frame size, maximum four pending calls, conservative timeouts and no retries of uncertain mutations.
- Node and Python unit tests with a CI validation workflow.

## Security boundaries

- Admin calls require a 32+ character secret kept as a Wrangler secret. Do not reuse device tokens as the admin key.
- Each Windows device uses a distinct random token. The Durable Object only stores its hash and drops old sockets on rotation.
- Token files live in the local user's UDB data directory, subject to the Windows account's filesystem permissions. Windows DPAPI encryption and a device revocation UI are **not** included yet.
- Cloudflare is a trusted relay, **not** a blind end-to-end encrypted channel. RPC payloads may be visible to the relay operator.
- This prototype's single admin key can contact all enrolled devices. **Do not deploy it for unrelated users or sensitive desktop work.** The production design needs explicit user-to-device authorization and OAuth consent.
- The UDB local proxy continues enforcing its own scoped project permissions and owner grants. The cloud cannot activate local owner permissions.
- The prototype does not expose a public MCP endpoint; ChatGPT cannot simply install this as a plugin yet.

## Developer-only validation

The following is a developer bootstrap, **not final end-user setup**:

1. Using a test Cloudflare account, open a terminal in the `cloudflare/` folder and run `npm install`.
2. Create a random admin secret of at least 32 characters, and run `npx wrangler secret put UDB_ADMIN_KEY`. Enter the secret only in the hidden prompt.
3. Deploy with `npm run deploy`. Copy the HTTPS Worker origin. This document does not claim a deployment has happened.
4. On Windows with a source checkout, run `python tools/cloud_enroll.py --relay https://YOUR-WORKER.workers.dev`. Enter the same admin secret in the hidden prompt. The script creates the per-device token and pairing file under the current user's UDB data home.
5. With this branch installed as a local development build, run `udb cloud-agent` in a local attended terminal. This is a foreground client and does not set up autostart.
6. For a read-only check use `GET /v1/admin/devices/{device_id}/status` with the admin bearer secret. The protected RPC endpoint is `POST /v1/admin/devices/{device_id}/rpc` and accepts standard JSON-RPC for the allowed methods, e.g. `{"jsonrpc":"2.0","id":1,"method":"tools/list"}`.

Keep the owner secret and pairing files out of git, chat transcripts and release artifacts.

## Remaining for the real one-click product

1. Implement OAuth 2.1 for ChatGPT with distinct users, explicit consent, per-device scopes, and revocation.
2. Implement owner-attended GUI device pairing without entering admin keys or tunnel IDs. Protect secrets with Windows DPAPI.
3. Implement Streamable HTTP MCP front end, including protocol initialization, notifications, complete tool catalog and long-running operations.
4. Integrate GUI state, background startup after explicit owner opt-in, clickable installer, and published ChatGPT plugin.
5. Test with two independent Windows devices on different networks and verify security, disconnect behavior and Cloudflare Free quota.

## Unit tests

- `cd cloudflare && npm test` (Node 22).
- `python -m pytest -q tests/test_cloud_agent.py`.
- `python -m ruff check src/udb/cloud_agent.py tests/test_cloud_agent.py tools/cloud_enroll.py`.

References: Cloudflare WebSocket Hibernation and Cloudflare MCP OAuth documentation.
