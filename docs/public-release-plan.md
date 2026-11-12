# UDB public-release readiness plan (proposal)

**Date:** 2026-11-04  
**Status:** Historical proposal based on UDB 0.11.0; not an approved date or claim of production readiness  
**Baseline (historical, 2026-11-04):** `main` at `913b338658c898df64502f307ade4ed5c65d8df3`; source package `0.11.0`  
**Current source/release note (2026-11-12):** UDB v0.12.0 is the latest published Windows release; Cloudflare-only remote MCP replaced the former OpenAI Tunnel path. `SECURITY.md`, `CONTRIBUTING.md`, and `PRIVACY.md` now exist, but security and privacy approvals remain separate release gates. See [release notes](release-notes.md), [release security](release-security.md), and [staging operations](../cloudflare/STAGING-OPERATIONS.md).

This is a release-gated plan to make Universal Desktop Bridge usable by people
outside the developer's own Windows machine. It is **not** authorization to
deploy a production Cloudflare Worker, enroll users, change grants or publish
an unrestricted desktop-control service.

## 1. Product promise and v1 scope

**Audience for v1:** a Windows 11 x64 user who wants an AI/MCP client to
inspect one or more **explicitly registered** local projects and optionally
propose a change under an attended owner approval. Prioritize a reproducible
first-run experience over adding more tools.

**In v1 scope:**
- Signed, verifiable Windows installer, clean uninstall and signed updates
  with rollback; real user and configuration data remain separate from binaries.
- Windows GUI and CLI for setup, project selection, device/session status,
  owner permission review, diagnostics, stop/pause and recovery.
- Local MCP read tools and an **authenticated, strictly read-only** hosted
  Cloudflare project-read gateway, after the actual Worker/Access/owner
  grant/ChatGPT acceptance tests succeed.
- Local guarded edits/terminal/browser tools only where their already existing
  separately scoped owner authorizations apply. Do **not** equate their local
  existence to remote Cloudflare access.
- Reproducible build/provenance evidence, documentation, privacy disclosures,
  crash reporting **opt-in**, tested support/incident process.

**Out of initial public v1 scope:** anonymous remote tool access,
remote unsandboxed `computer_*`/shell/desktop access through `udb:read`,
automatic remote approvals, general-purpose remote file writes, a
production multi-PC auto-router, enterprise administration/billing, native
macOS/Linux desktop clients, and an AI-powered feature expansion before
release hardening. Keep these behind separate threat-model/architecture gates.

**Positioning:** Windows-first and local-first, not "all data stays on your
machine." Data sent to a connected AI provider/Cloudflare relay crosses a
network. Disclose this clearly before the user authorizes a connection.

## 2. Evidence-based baseline (checked in repository)

- MIT `LICENSE` exists. Public GitHub repository, canonical Python code
  under `src/udb`, Windows application, MCP tool catalog and source GUI.
- Windows standalone packaging with SHA-256, release workflow
  `.github/workflows/one-command-release.yml`, CI matrix and installer/
  rollback tests are implemented. The binary currently documented is
  **not Authenticode-signed**. A SHA-256 published by the same pipeline
  is not sufficient proof of publisher identity.
- Cloudflare OAuth-aware gateway and scoped-read tool list exist in **source**.
  A Worker health HTTP 200, a local `udb cloud-agent` process or green
  mocked tests do **not** prove an authenticated end-to-end ChatGPT read.
  Production Worker deployment and owner-specific grants are separate.
- Cloudflare `UDB_DEVICE_GRANTS` is an operator-managed private JSON policy,
  not an end-user signup/account system designed for arbitrary tenants.
- Common Room source GUI, Edge/Chrome fallback, browser workflow and
  snapshot improvements are merged; source compatibility does not guarantee
  that a user's installed executable or plugin reflects every merge.
- **Historical gap at the 0.11.0 baseline:** root `SECURITY.md`, `CONTRIBUTING.md`, and dedicated `PRIVACY.md` were missing at the time. These files now exist, but their existence does not constitute an independent security assessment or finalized public privacy policy.
- Windows CLI startup was measured around 8–10 seconds on one machine;
  track independently in [issue #89](https://github.com/hahhjaaap/Universal-Desktop-Bridge/issues/89).
  Root cause and target speed remain unverified.

## 3. Architecture decisions to settle before multi-user rollout

| Decision | Proposed choice | Reason/tradeoff |
| --- | --- | --- |
| Desktop platform | Windows 11 x64 first | Existing tooling and tests; Win10/macOS/Linux increase support scope |
| Cloud path | Managed **invite-only** Cloudflare beta, with optional self-host for developers | Normal users cannot be expected to configure Wrangler, Access policies and secrets |
| Owner identity | OAuth/OIDC login and independent device-bound registration | Login != owning a device; every tool needs subject/device/scope authorization |
| Multi-tenant authorization | Durable owner/device/tool policy in an auditable service, default-deny; do not reuse one manually edited global grant JSON as a general SaaS onboarding model | Prevent cross-account host access, enable revoke and support |
| Default permissions | Scoped project reads only, no remote writes/desktop by default | Computer-control UDB runs with real Windows-user authority |
| Distribution | Signed direct Windows installer + immutable GitHub Release first; evaluate Microsoft Store/MSIX later | Lowest migration cost from current installer; Store has different packaging/review requirements |
| Rollout | Private beta → public beta → stable, each gated | A green CI result alone never proves production readiness |
| Data handling | Do not persist document bodies/secret tokens in observability; explicit retention/consent controls | Cloudflare is a relay, not opaque end-to-end encryption |

If managed hosted login and its security review cannot be completed,
publish an **explicitly developer-oriented local/self-hosted beta**, not
an apparently one-click general consumer cloud product.

## 4. Workstreams and acceptance requirements

### P0-A — Threat model and tenancy (BLOCKER)

- Document trust boundaries: ChatGPT/AI content, OAuth, relay/DO, pairing,
  owner grants, scoped projects, Windows terminal/desktop, browser, updater.
- Audit authn/authz and revocation on **each** device and tool, including
  multiple identities, stale/reused tokens, offline/reconnect, subject mismatch,
  unauthorized discovery, cross-tenant access and confused-deputy actions.
- Use separate staging/production Cloudflare accounts or isolated deployments;
  distinct secrets/Access applications/DO storage; admin APIs disabled in prod.
- Replace manual static multi-user secret editing with an owner-managed
  enrollment/grants lifecycle: login → claim owned device → choose safe scopes
  → confirm locally → revoke → recover.
- Audit source/browser prompt injection, path traversal/symlink/junction
  attacks, TOCTOU, replay after timeout, local privilege escalation, logs
  and update supply-chain. Resolve critical/high findings before public beta.
- Verify AI content can never grant Windows privileges or trigger approvals.
- **Gate:** Independent security review of these paths; denial tests pass for
  two distinct accounts and two distinct Windows devices; revocation effective
  in a bounded tested window; no remote write/terminal/desktop on `udb:read`.

### P0-B — Real Cloudflare/ChatGPT proof (BLOCKER)

- From approved production-like staging deploy, verify the **actual** Worker
  version; Access Managed OAuth policy, correct device-specific URL, audience
  and owner subject/grants.
- Confirm `tools/list` contains only granted `bridge_status`,
  `list_projects` and optionally `list_files`, `read_file`,
  `search_files`, `check_python_syntax` with valid schemas.
- Test ChatGPT ↔ Worker ↔ DO ↔ Windows Cloud Agent ↔ scoped project:
  file text/path/SHA-256 matches known fixture; deny a protected and
  out-of-project fixture; deny ungranted user and other device.
- Disconnect/reconnect, OAuth expiry, revoke and multiple simultaneous
  read requests without stale-device delivery or unauthorized fallback.
- Record results with non-secret redacted logs and deployment revision.
- **Gate:** 30 repeat authenticated scoped reads on at least three distinct
  network conditions, including two owners/devices; 100% expected denials,
  no unauthorized tool exposure. This is an **acceptance target**, not a
  currently measured claim.

### P0-C — Publisher trust, installer and update (BLOCKER)

- Decide developer identity and code-signing certificate/provider, compatible
  with issuer geography/organizational eligibility. Provision keys in
  protected signing service/HSM; no PFX/token in source or general logs.
- Sign **actual** EXE/installer included in the archive before checksums;
  ensure signed updater checks signer/pinned publisher identity and file
  digest; signature verification fails closed.
- Harden the `one-command-release` pipeline: least-privilege GH tokens,
  protected environments and approvals, pinned CI dependencies/actions,
  provenance/attestation and SBOM/license inventory where applicable,
  immutable tags and exact commit-SHA regression gates.
- Provide a normal downloadable signed installer, not requiring novice users
  to copy `irm ... | iex`; straightforward uninstall, optional app data
  cleanup, backup, upgrade/downgrade and offline fallback.
- Reduce `udb --version` p50 launch to <2 s on representative hardware
  as an **engineering target** after profiling; compare single-file vs
  onedir or small launcher without weakening validation.
- **Gate:** Signed install/update/uninstall/rollback from clean Windows 11
  x64 accounts, preserved UDB data/grants on upgrade, no elevated privileges
  unexpectedly requested, no unsigned executable in signed package.

### P1-D — Setup UX and safe controls

- Treat **independent local use** and **ChatGPT remote access** as separate
  deliverables. Start a ready local manager with one command and no
  Desktop Commander, Cloudflare account or remote pairing. An explicit user
  option may enable current-user logon startup; an existing remote profile
  must not be silently switched to offline.
- For remote ChatGPT parity, provide a guided **one-time** UDB connector
  enrollment on the owner's own machine. Subsequent reconnects are automatic
  only within approved identity/device grants, never by replaying uncertain
  mutations. No normal user should manually maintain Cloudflare secrets.
  Track [the independent UDB UX gate](https://github.com/hahhjaaap/Universal-Desktop-Bridge/issues/130).
- First-run flow: install → sign in / choose local-only → pair one device →
  select a project → review each permission → enable Cloud Agent →
  run read-only connection test → open ChatGPT connection.
- Show exact failure stage (host offline, Worker, OAuth, grant, MCP
  discovery, local project), status timestamp, repair guidance, and
  "unknown" when verification is impossible.
- Keep "Stop"/pause/revoke visible and usable when the relay is offline.
- GUI responsiveness, keyboard focus, Windows DPI 100/150/200%, Vietnamese/
  English localization and accessible error messages.
- Reduce Common Room/UI feature churn until v1 release gates are stable.
- **Gate:** At least 90% of pilot non-developer testers install and reach
  first successful read-only call without CLI or private technical help;
  document remaining failure categories. This is a **target**, not measured.

### P1-E — Documentation, policy, support

- Create `SECURITY.md` with private vulnerability disclosure and
  supported versions; `PRIVACY.md` with real data flows, processors,
  purposes, retention/deletion and opt-in diagnostics; `CONTRIBUTING.md`,
  third-party license/SBOM notices and clear MIT/brand usage.
- Explain Cloudflare/AI relay is **not** end-to-end encrypted against relay
  operators; do not promise all data remains on-device.
- Product page/release notes, verified checksums/signatures, installation
  walkthrough, supported OS/hardware, feature/permission table, FAQ,
  uninstaller/update/rollback instructions.
- Give testers a private feedback/issue template, version-aware diagnostic
  export (redacted, opt-in), crash triage and vulnerability response playbook.
- **Gate:** A new user can complete onboarding from published docs and can
  revoke access and uninstall independently.

### P1-F — Stability, capacity and observability

- Add nightly Windows end-to-end smoke with disposable project/device,
  auth-expiry/reconnect tests, 24h+ idle/resume, network loss and updates.
- Establish baseline and alert thresholds: local CLI p50/p95, first read
  p50/p95, relay errors, session drops, update failures and sanitized crash
  counts. No user file contents or credentials in telemetry.
- Load-test Cloudflare Worker/DO for anticipated concurrency, queue bounds,
  rate limiting, quotas, deploy/rollback and spending alerts.
- **Gate:** 7-day pilot operation without critical data loss/unauthorized
  actions, >99% crash-free pilot sessions, and no unresolved P0/P1 bug.
  These are targets; collect evidence rather than asserting them now.

## 5. Proposed delivery order and capacity

Assume **one maintainer with AI assistance**, working on focused PRs.
These are planning ranges, not promised dates:

| Phase | Rough window | Deliverable | Gate |
| --- | --- | --- | --- |
| 0. Freeze/measure | Week 1 | Threat model, release scope, open-issue backlog, clean Win11 acceptance baseline | Critical gaps visible; no unscoped feature expansion |
| 1. Device security | Weeks 2–4 | Multi-user isolation + owner pairing/revoke + real Cloudflare/ChatGPT smoke | P0-A/B |
| 2. Trust/distribution | Weeks 4–7 | Signed installer/updater, rollback, reproducible pipeline, CLI profiling | P0-C |
| 3. Usability/policies | Weeks 6–9 | Guided setup, privacy/security/contributor docs, redacted diagnostics | P1-D/E |
| 4. Private beta | Weeks 9–11 | 10–20 invited testers on independent machines/networks | Pilot thresholds |
| 5. Public beta | Weeks 11–14 | Published signed installer, staged rollout, monitoring and support | No unresolved high risks |
| 6. v1.0 stable | After beta gates | Public stable with signed immutable artifacts and tested rollback | Formal go/no-go checklist |

Phases overlap only when they do not weaken P0 security or test capacity.
Release identifiers `0.12.0-beta`, `0.13.0-beta`, `1.0.0` are proposals,
**not** existing tags or scheduled automatic deployments.

## 6. Go / No-Go checklist

A public stable announcement is **NO-GO** unless ALL are true:

- [ ] Product scope frozen, feature flags and compatibility guarantees documented
- [ ] Real authenticated ChatGPT → Worker → Windows read/deny/revoke evidence
- [ ] Device/owner isolation independently assessed; no high/critical open findings
- [ ] Default deny for any write, shell, desktop and broad computer access
- [ ] Signed installer/EXE and signed/verified updates with publisher identity
- [ ] Clean-machine install, upgrade, uninstall and rollback pass on Windows 11 x64
- [ ] Full CI Windows 3.11/3.12 and Linux matrix, Node Cloudflare, GUI/browser tests green
- [ ] Private beta targets met and crash/connection/error diagnostics evaluated
- [ ] Support channel and private vulnerability intake active
- [ ] Privacy/security/licensing/third-party notices complete and accurate
- [ ] Production Cloudflare limits, tenant separation and cost alerts validated
- [ ] Owner explicitly approves the version, deployment, rollout and any data policy

If Cloudflare end-to-end or signing is blocked, do **not** quietly lower the
standard and label the build stable. Release a clearly marked developer-only
preview or continue the private beta.

## 7. First implementation tickets

1. **P0** `security/owner-device-tenant-threat-model` — trust boundary diagram,
   device isolation and authorization denial matrix; acceptance fixtures.
2. **P0** `cloud/e2e-authenticated-scoped-read` — real Cloudflare staging deploy,
   OAuth/grant/revoke/ChatGPT test evidence, no remote write exposure.
3. **P0** `release/authenticode-signing` — signed exact release package,
   pinned publisher verification and fail-closed CI gate.
4. **P0** `release/clean-windows-install-update-rollback` — signed installer
   cold/warm install, preservation, uninstall and downgrade matrix.
5. **P1** `performance/cli-cold-start` — existing
   [issue #89](https://github.com/hahhjaaap/Universal-Desktop-Bridge/issues/89);
   collect profiling, prototype optimizations and regressions.
6. **P1** `gui/first-run-connection-wizard` — clear local/cloud modes, project,
   scope consent, live probe and recovery states.
7. **P1** `policy/security-privacy-contributing` — `SECURITY.md`,
   `PRIVACY.md`, `CONTRIBUTING.md`, licensing and support workflow.
8. **P1** `ops/pilot-telemetry-capacity` — opt-in redacted diagnostics,
   Cloudflare spend/capacity alerting and staged beta.
9. **P2 (post-v1)** `cloud/remote-write-approval-design` — separate audited
   security model for any future remote write/execute/desktop capabilities.
10. **P2 (post-v1)** `desktop/multi-pc-router`, Windows Store/MSIX,
   enterprise policy and non-Windows desktop support.

## 8. Owner decisions required

Before building a general-user cloud service, the owner must approve:
(1) **managed Cloudflare relay** versus user self-hosting; (2) publisher and
code-signing identity; (3) beta target audience/data sensitivity and
privacy policy; (4) operational budget, support responsibility and
infrastructure credentials. None of these decisions is inferred from
the current developer's personal pairing or an existing private Worker.

## References

- [UDB architecture](../ARCHITECTURE.md)
- [UDB signing status](release-security.md)
- [UDB Cloudflare project-read acceptance](cloudflare-project-read-acceptance.md)
- [UDB pairing checklist](pairing-checklist-vi.md)
- [UDB performance measurements](performance.md)
- [UDB release notes](release-notes.md)
- [UDB enterprise GUI roadmap](gui-enterprise-roadmap.md)
- [Microsoft Windows signing options](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options)
- [Cloudflare Workers limits](https://developers.cloudflare.com/workers/platform/limits/)
- [Cloudflare Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/)
