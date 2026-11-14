# UDB Connect — public one-time setup contract

Status: **design plus a safe client entrypoint, NOT a finished one-click service**.
No public enrollment, production Cloudflare deployment, ChatGPT app submission,
user account or device permissions are created by this PR.

## Private deployment alternative (without public directory listing)

For a single owner or invite-only group, ChatGPT's **Add custom MCP server**
flow can connect directly to the existing per-device HTTPS MCP endpoint.
A published public UDB app and a stable cross-device `/mcp` router are **not
required** for this small private mode. The Cloudflare Worker must still
provide valid user OAuth/Access and device-specific grants; a working Agent
alone does not establish authorization. The one-time device invitation is
still administrator-issued (not public self-service).

Use `udb connect --setup` from a trusted attended Windows terminal to reuse
existing hidden one-time invitation input and Credential Manager enrollment.
`udb connect --setup --autostart` additionally opts in to Cloud Agent startup
at next Windows logon, with existing owner-attended and terminal-disabled
guards. Then run `udb start` to connect immediately. In ChatGPT, create a
private custom MCP server using the printed URL and authorize OAuth. The
ChatGPT creation/consent step is never automated.

## Actual target UX (Desktop Commander-style)

1. Download a verified **signed** UDB Windows installer.
2. Launch UDB. Local features start without Cloudflare or ChatGPT.
3. Choose **Connect UDB in ChatGPT** (or type `udb connect`).
4. Sign in to a UDB-hosted account through a browser and explicitly approve
   linking **this one** Windows device. No Worker URL, administrator API key,
   manually-issued invitation, tunnel_id, or token copy/paste.
5. In ChatGPT, choose the published **UDB app**, press Connect, and authorize
   OAuth 2.1. This authorization must remain an explicit ChatGPT user action.
6. UDB detects the resulting *real authenticated read-only MCP call* and shows
   ChatGPT connected; refreshes tokens without resubmitting old mutations.
7. Revoke device, revoke ChatGPT authorization, and disconnect from either app.

**The initial client code in this PR only handles step 3 for an already
enrolled device**. Fresh installs explicitly report `needs_enrollment`
instead of silently reusing the developer's Cloudflare Worker or secrets.
It opens the trusted ChatGPT Plugins page; it cannot install or enable a
plugin on the user's ChatGPT account or prove OAuth succeeded.

## Required architecture

```text
Windows UDB (per-device key in OS credential store)
  -> public UDB onboarding URL / browser account login
  -> device-authorization-code + expiry + proof of possession
  -> UDB service: verified owner -> tenant -> device mapping
  -> per-device outbound Cloud Agent / Durable Object
  <- OAuth-bound ChatGPT UDB app at ONE stable HTTPS /mcp resource
  -> authorize subject + device + individual tool grants
  -> Windows local consent for any sensitive write/terminal/desktop work
```

### Service prerequisites (not implemented in this PR)

- One production **stable plugin MCP URL** (not a different URL per device),
  with standards-compliant OAuth 2.1 / PKCE / refresh tokens, exact audience,
  subject binding and signed discovery metadata. Client registration and
  publisher app submission follow the actual current ChatGPT plugin rules.
- An owner-facing sign-in and device code/PKCE flow. The Windows client starts
  a short-lived pending authorization, shows human-readable device identity,
  opens browser for trusted login, and polls an authenticated result. Browser
  approval must be linked to the device's proof-of-possession secret, never
  just a six-digit code or attacker-supplied identity header.
- Server-issued identity-qualified **per-device**, per-subject records:
  no global `UDB_ADMIN_KEY` on clients; no shared device token; deny by
  default; audited claim/rotate/revoke/recover; rate-limit attempts and
  enforce short expiry / single use. Recovery must not bypass consent.
- A stable identity selector (issuer-qualified subject, not only mutable
  email), with explicit account-to-device mapping. For multiple PCs, selecting
  a specific device is an explicit supported capability; never infer device
  ownership from `device_id` alone.
- Strict least privilege. Read-only project tools require local project
  registration and grant. Full Windows computer execution/desktop control
  stays **off by default** and requires separate attended Windows approval;
  connecting ChatGPT or installing software cannot grant it.
- Separate staging and production OAuth issuers, aud, secrets, Access app,
  device DO namespaces and rate limits. Disable prototype admin enrollment
  and unsafe owner RPCs for consumer accounts. Do not reuse existing
  `udb-private-relay-staging` as the public production service.
- A published UDB plugin/app in the ChatGPT directory. A local installer
  cannot silently add it to another person's ChatGPT account.

### Minimum release gates before claiming plug-and-play

- Two distinct new Windows users and two unrelated devices: first run with
  no pre-seeded secrets, login, pair, install ChatGPT app, authenticate and
  successfully call `bridge_status` and explicitly granted `list_projects`.
- Isolation test: Alice cannot discover or call Bob's devices, files,
  owner tools or already-revoked grants. OAuth token expiration, logout,
  concurrent login and expired/replayed device codes fail closed.
- All tool discovery and permissions tested through the **real ChatGPT**
  connector, not just Worker health, static source or mock OAuth.
- Offboarding from both Windows and ChatGPT; proof of revocation for new calls,
  no automatic retry of requests with unknown mutation outcomes.
- Signed/pinned Windows installation and protected branch/release environments,
  independently verified publication/installer and rollback.
- Explicit product policy/consent explaining that data relayed through
  Cloudflare and an AI provider is not guaranteed to stay on-device.

## Current safe client behavior

```powershell
udb connect                  # Open ChatGPT Plugins only if already paired
udb connect --no-browser     # Inspect device pairing without opening a tab
udb connect --json           # Machine-readable state; never opens the browser
```

Statuses are `needs_enrollment`, `invalid_pairing` and
`ready_to_authorize_in_chatgpt`. **None means ChatGPT is connected.**
Only a real tool call can demonstrate that. Owner settings and permissions
are never modified by the new command.

## No-go decisions

Do not ship a generic installer that contains the developer's private
pairing code, UDB admin secret, device token, static Access grant or another
owner's MCP endpoint. Do not remove the user's required ChatGPT installation
and OAuth consent step. Do not open a public claim endpoint before the
authenticated per-tenant ownership and rate-limit tests pass.

Related documents: `docs/owner-device-isolation.md`,
`docs/public-release-plan.md`, `docs/release-security.md`.
