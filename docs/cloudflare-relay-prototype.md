# UDB Cloudflare relay — historical P0 prototype notes

> **Archived design record, not the current setup runbook (updated 2026-11-04).**
> This file describes early admin-relay and invitation experiments. It
> deliberately preserves the original design rationale but **must not** be
> used to decide whether today's deployed Worker, OAuth application or
> owner device grants are correct. The current source contains an
> authenticated device-specific MCP endpoint and a **read-only** grant
> catalog (PRs #85–#87); deployment/authorization remain separate.
> Follow [owner pairing](pairing-checklist-vi.md),
> [OAuth MCP security](cloudflare-oauth-mcp.md), and
> [project-read deployment acceptance](cloudflare-project-read-acceptance.md)
> instead. A healthy `/health` does not establish an end-to-end ChatGPT call.

This was the initial private Cloudflare Worker + Durable Object relay
proposal for a small set of devices. Its original admin-key-only architecture
predated the separate owner-attended pairing and Cloudflare Access Managed
OAuth support. It never granted Windows permissions automatically.

## Original P0 implementation (historical)

- Cloudflare Worker HTTP routing with a private administrator API and per-device routing.
- A hibernatable Durable Object WebSocket per device, with independent device token hashes.
- The Windows `udb cloud-agent` command. It connects outbound using TLS and forwards allowed MCP JSON-RPC requests to the existing local `udb serve` proxy.
- Random device tokens registered by SHA-256 digest; local credentials are not passed through command-line arguments. A second, owner-attended invitation flow now supports enrollment without sharing the global admin key.
- Bounded frame size, one in-flight RPC per device, conservative timeouts and no retries of uncertain mutations.
- The cloud agent rejects WebSocket redirects with bearer credentials and exponentially backs off quick connection closures. Malformed device replies fail closed; Durable Object outages return 503 instead of misleading 400 errors.
- Node and Python unit tests with a CI validation workflow.

## Security boundaries

- Admin calls require a 32+ character secret kept as a Wrangler secret. Do not reuse device tokens as the admin key.
- Each Windows device uses a distinct random token. The Durable Object only stores its hash and drops old sockets on rotation.
- Newly paired Windows device tokens live in Windows Credential Manager under a device-specific target, rather than a plaintext file. A device revocation UI is **not** included yet.
- Cloudflare is a trusted relay, **not** a blind end-to-end encrypted channel. RPC payloads may be visible to the relay operator.
- This prototype's single admin key can contact all enrolled devices. **Do not deploy it for unrelated users or sensitive desktop work.** The production design needs explicit user-to-device authorization and OAuth consent.
- The UDB local proxy continues enforcing its own scoped project permissions and owner grants. The cloud cannot activate local owner permissions.
- The **original P0 prototype** did not expose a public MCP endpoint. Current
source does expose the device-specific `/v1/devices/DEVICE_ID/mcp` path, but
it still requires a deployed Worker, valid OAuth/Access policy, explicit
per-device read grants and ChatGPT tool discovery.

## Short-lived pairing (second prototype milestone)

The early owner-attended invitation flow avoided sharing the global admin
secret. **Historically it had no OAuth integration**; current versions
separately support Cloudflare Access Managed OAuth on MCP paths. Do not use
this historical pairing section in place of the current checklist.

1. From a trusted developer terminal with the private Wrangler administrator key, create an invitation by issuing `POST /v1/admin/pairings` with an admin Bearer token. The response contains `device_id`, a random 256-bit `pairing_code` and `expires_in_seconds: 600`. Do not publish these values; the one-time code is a credential.
2. On the Windows device, install this branch's UDB source build. In the full UDB manager, open **Kết nối** and select **Nhập mã mời Cloud**; enter the Worker HTTPS origin, the device ID and the code (shown as a password field), then explicitly confirm the registration. The attended terminal command `udb cloud-pair` is also available as a developer fallback. No shared administrator key is required on this device.
3. The client generates an independent random device token, sends **only its SHA-256 digest** to `POST /v1/devices/{device_id}/claim` with the one-time invitation credential, and stores the device token locally after the server confirms the claim.
4. The one-time invitation expires after 10 minutes, locks after five bad attempts and cannot be replayed. The administrator can revoke it using the private authenticated `DELETE /v1/admin/devices/{device_id}` endpoint. Revocation closes the existing device WebSocket.
5. The Windows owner may run `udb cloud-agent` for a private development connection. None of these steps changes UDB owner permissions.

The Windows UDB manager now has a separate **Bật Cloud Agent / Tắt Cloud Agent**
button on the connection page. This is a manually enabled, session-only agent
process: it does not run at startup, does not grant access, and is terminated
with its owned local MCP proxy when the owner fully exits the GUI. Minimizing
the window to the tray does not count as exiting. The UI intentionally reports
only the agent process status, **not verified ChatGPT connectivity**.

On Windows, new device tokens are stored in **Windows Credential Manager**, under a unique device-scoped credential target. No plaintext cloud token file is created by the new GUI pairing or developer bootstrap. Other platforms in source-only tests use a local test token file; production UDB remains Windows-only. This protects credentials at rest using the existing UDB credential backend, but does not replace OAuth or per-user device authorization. After a successful remote claim followed by a local disk failure, the server registration must be revoked administratively before pairing again. The prototype owner must safeguard invitation codes and the global admin secret; the cloud is not encrypted end-to-end.

**Security limitation:** The GUI button only registers the device; it does not start the background agent, configure ChatGPT or grant Windows permissions. Until the ChatGPT MCP resource server authenticates per-user OAuth tokens and enforces user-to-device ownership, this developer-only relay must not be exposed to unrelated users or sensitive PCs.

## Developer-only validation

The following was an **early developer bootstrap**, not current end-user
setup. Avoid deploying or activating the old admin-only relay from these
steps; use the current reviewed Wrangler configuration and runbook instead:

1. Using a test Cloudflare account, open a terminal in the `cloudflare/` folder and run `npm install`.
2. Create a random admin secret of at least 32 characters, and run `npx wrangler secret put UDB_ADMIN_KEY`. Enter the secret only in the hidden prompt.
3. In the original test environment, deploy with `npm run deploy`; capture
   the origin. **This is historical context, not a recommendation to redeploy
   an admin-enabled Worker over a current production MCP gateway.**
4. On Windows with a source checkout, run `python tools/cloud_enroll.py --relay https://YOUR-WORKER.workers.dev`. Enter the same admin secret in the hidden prompt. The script creates the per-device token and pairing file under the current user's UDB data home.
5. With this branch installed as a local development build, run `udb cloud-agent` in a local attended terminal. This is a foreground client and does not set up autostart.
6. For a read-only check use `GET /v1/admin/devices/{device_id}/status` with the admin bearer secret. The protected RPC endpoint is `POST /v1/admin/devices/{device_id}/rpc` and accepts standard JSON-RPC for the allowed methods, e.g. `{"jsonrpc":"2.0","id":1,"method":"tools/list"}`.

Keep the owner secret and pairing files out of git, chat transcripts and release artifacts.

## Original follow-up milestones (historical)

Several items below were subsequently implemented in source, including a
device MCP frontend, OAuth/Access code and GUI pairing. They are **not**
current proof of deployment, device grant, security review or a one-click
product. Track remaining work in the current repository and acceptance
runbook rather than treating this list as today's status.

1. Implement OAuth 2.1 for ChatGPT with distinct users, explicit consent, per-device scopes, and revocation.
2. Implement owner-attended GUI device pairing without entering admin keys or tunnel IDs. Protect secrets with Windows Credential Manager.
3. Implement Streamable HTTP MCP front end, including protocol initialization, notifications, complete tool catalog and long-running operations.
4. Integrate GUI state, background startup after explicit owner opt-in, clickable installer, and published ChatGPT plugin.
5. Test with two independent Windows devices on different networks and verify security, disconnect behavior and Cloudflare Free quota.

## Unit tests

- `cd cloudflare && npm test` (Node 22).
- `python -m pytest -q tests/test_cloud_agent.py tests/test_cloud_pair.py`.
- `python -m ruff check src/udb/cloud_agent.py tests/test_cloud_agent.py tools/cloud_enroll.py`.

References: Cloudflare WebSocket Hibernation and Cloudflare MCP OAuth documentation.
