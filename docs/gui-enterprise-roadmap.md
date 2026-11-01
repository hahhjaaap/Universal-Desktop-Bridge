# UDB Enterprise Desktop UI — design, security and delivery roadmap

**Status (2026-11-01):** incremental implementation underway in source; the full enterprise GUI and hardening plan remain **unfinished**.
**Baseline:** UDB `main` 0.10.1; latest published Windows installer v0.10.0. GUI changes merged after that release do **not** update the installer.
**Target:** a polished Windows desktop product with verifiable controls, not an AI-styled dashboard.

### Implementation ledger (source, not released installer)

| Slice | Code status | Evidence / boundary |
| --- | --- | --- |
| Architecture/roadmap | Merged PR #41 | Planning document and security requirements |
| Appearance foundation | Merged PR #42 | Strict `system`/`light`/`dark` palette, allow-listed local persistence, visual/contrast regressions |
| Collapsible navigation | Merged PR #44 (supersedes #43) | 200 px/72 px sidebar, six existing routes and accessible labels |
| Connection health strip (Phase 3 partial) | Merged PR #46 | Separate Agent/Tunnel/ChatGPT badges; errors revert to unknown; still no authenticated ChatGPT invocation proof |
| Task filters / audit timeline / approval impact (Phases 4/5 partial) | Merged PR #51 | Local metadata search, read-only MCP activity timeline, explicit consent and no-overwrite audit export, keyboard navigation, operation-specific approval review and connection diagnostics |
| Reduced-motion accessibility preference | In source follow-up PR | Native Qt settings toggle, safe allow-listed persistence, immediate effect and rollback on save failure |
| New full dashboard / complete enterprise shell | Not implemented | No claimed task percentages or multi-machine router |
| Security privilege disclosure (Phase 5 partial) | Merged PR #48 | Read-only broad Windows grant status and explicit unsandboxed warning; no owner grant setter exposed |
| Native three-step connection onboarding (Phase 6 partial) | In source follow-up PR | Worker and tunnel status are local-only; ChatGPT tool discovery stays unverified without external read-only call |
| Release signature verifier (Phase 7 partial) | Merged PR #50 | Windows-only Authenticode signer-pin checker; **no certificate or signed installer** |
| Local security posture overview (Phase 5 partial) | Merged PR #52 | Pending owner approvals, Windows input pause, scoped auto-source grants; independently fail-closed, no new access methods |
| Audit metadata redaction | Merged PR #53 | Unknown MCP tool names use a generic label; untrusted identifiers are not displayed or exported |
| Advanced security center and signed release | Not implemented | Existing owner-only approvals retained; supply-chain work, independent security audit and actual signing remain separate |

See [Desktop GUI user guide](gui-user-guide.md) for current behavior and
[Releases](https://github.com/hahhjaaap/Universal-Desktop-Bridge/releases)
for shipped installer status.

The baseline inventory below is **historical**, recorded before the GUI
foundation PRs. Do not treat every item in that inventory as current code.

## 1. Grounded baseline

Pre-redesign code and behaviors identified for preservation:

- `src/udb/manager.py`: six stacked sections (Projects, AI Permissions, Jobs, Protection, Connection, Computer), original fixed 200 px sidebar (now 200/72 px collapsible in source), 1220×820 default / 940×640 minimum size, 1500 ms refresh timer.
- `src/udb/manager_widgets.py`: original hard-coded dark QSS theme (superseded in source by `ui_theme.py` light/dark tokens); custom-painted `MotionButton`; `StatusPill`; accessibility labels are evolving.
- `src/udb/manager_quick.py`: compact 480×670 controls, tray, local pause, browser handoff, recent activity. It is not a full task progress monitor.
- `src/udb/manager_dialogs.py`: local-only approval with complete content/diff tabs, explicit checkbox, second local confirmation and expiry. Never weaken these checks to simplify UX.
- `src/udb/manager_host.py`, `manager_refresh.py`: host/workspace controls and status polling; current local/tunnel readiness is not proof of real ChatGPT end-to-end connectivity.
- `tests/test_manager_ui.py`, `tests/test_quick_controls.py`, `src/udb/manager_selftest.py`: regression and synthetic screenshot entry points. Preserve their current safety invariants.

**Non-goals:** no Electron rewrite; no QML migration without a measured reason; no remote GUI privilege setter; no replacing UDB's security engine; no Windows shell/UAC bypass; no new all-powerful `auto approve` control; no claim of 100% security.

## 2. Product direction and information architecture

Visual direction: restrained Windows 11 Fluent-inspired enterprise desktop software, **not** copied Microsoft branding. Light/dark/system themes, readable typography, neutral surfaces, limited blue emphasis, semantic warning/danger colors, 4/8 px spacing scale, consistent border/radius/elevation. Icon set is local and bundled; no runtime CDN or web fonts.

### Main shell

- Desktop-native title bar and window controls; **current implementation uses 200 px expanded / 72 px collapsed navigation**. A broader layout refactor with a contextual right-side details drawer is still proposed.
- Persistent title/header: app name, **verified target machine identity** (when available), clearly separated local agent / tunnel / ChatGPT RPC states, action to pause local Windows input.
- Do not show green Connected based on tunnel status alone; show `unknown` or `not checked` for missing RPC evidence.
- Pages: Overview, Activity & Jobs, Computers & Sessions, Projects & Files, Permissions & Approvals, Security & Audit, Connections & Devices, Settings. Existing six sections may be migrated incrementally using stable adapters.
- Search/filter within owned jobs, project files and sanitized activity metadata only; no global arbitrary computer search.
- A compact tray control remains; quitting, minimizing and closing owned background sessions retain distinct meanings.

### Key experiences

1. **Overview:** verified health and last observation time, current grants, pending approvals, real active-job counts, protected-state warnings, one visible safe Pause action. Never invent percentage completion.
2. **Activity:** event-oriented timeline with queued/running/done/failed/unknown states, timestamps, tool and machine identity; task details and retry safety guidance; sanitized output.
3. **Machines:** device identity and explicit permissions; online/offline/unknown states, session ownership, local / headless / Sandbox distinction. Multi-PC selector only after real router is released and verified; no simulated device switching.
4. **Projects:** clear root scope, capabilities, exclusions and protection, source-write review and file-hash mismatch handling.
5. **Approvals:** who/what/where/why/expiry, risk indicators, target path/domain, complete diff/script, impact preview, reject as obvious primary-safe alternative, confirm locally with existing back-end authorization. Mark truncated review clearly; never hide required content.
6. **Connections:** guided local vs tunnel vs ChatGPT diagnostics, exact failing hop, no raw tokens; human-readable recovery without blind write replay.
7. **Settings:** appearance (light/dark/system), motion reduction, scaling, log privacy/retention (within actual supported policy), diagnostics export with redaction.

## 3. Theme and component system

Theme tokens and Qt palette support are now implemented in canonical `src/udb/ui_theme.py`, with theme-aware widgets under `manager_widgets.py`. Future shared components and read-only viewmodels may be split into additional modules, but must remain compatible with packaging and backend security boundaries.

- Tokens: surfaces/text/borders/focus, semantic states, spacing/radius/typography/elevation/motion. Example palette: background `#F5F7FA`, dark background `#101828`, primary `#2D6CDF`, dark surface `#253349`; **verify actual contrast before finalizing**.
- Typography: Segoe UI Variable when installed, Segoe UI fallback; localized text at 100–200% DPI and Windows text scaling. Do not download or distribute font binaries.
- Components: `AppShell`, `SidebarNav`, `PageHeader`, `StatusCard`, `PermissionScope`, `SecurityBanner`, `EmptyState`, `EventTimeline`, `JobRow`, `ConnectionDiagnostics`, `ApprovalReview`, `ErrorDetails`, `SafeActionButton`.
- Buttons: test keyboard focus, disabled, hover, active and high contrast; custom-painted controls must provide full accessibility semantics or use styled native QPushButton.
- Fallbacks: system reduced-motion, no animation when not supported; don't depend on blur/transparency for critical information.
- Preserve genuine native window semantics and screen readers instead of creating a frameless imitation of a browser window.

## 4. GUI data model and performance

Introduce typed, immutable **read-only** view states derived from authoritative back-end operations (e.g. `AgentState`, `ConnectionHopState`, `DeviceState`, `JobState`, `ApprovalState`) with `observed_at`, `source`, `freshness` and `unknown` variants.

- The GUI **renders**, it does not grant permissions, infer task success or replay mutations.
- Deliver state changes through Qt signals and background workers; coalesce unchanged updates and disconnect listeners on window teardown.
- Keep emergency Pause and local Reject enabled even if diagnostics/logs fail or are slow; never block GUI thread for network, SQLite, filesystem, Windows or CDP calls.
- Cache visual derived data only; never cache permission authorization or use stale health as the source of trust.
- Benchmark p50/p95 click latency, cold start, UI-thread stall, RAM/CPU idle, redraw counts before and after each UX PR.

## 5. Security and privacy requirements (must be enforced below the GUI)

### Threat model

Attack inputs: untrusted MCP client payloads, malicious webpage/document text and prompt injection, compromised local app, spoofed connection status, stale/forged approval UI, symlinks/path races, endpoint changes, plugin/tunnel outage, update supply-chain compromise.

**Security invariants:**

1. Owner-only authorization remains in core back-end; no new remotely accessible grant/approve methods. Critical approval actions must bind to exact request ID, hash, scope, expiry and currently displayed details; revalidate immediately at commit.
2. Use least privilege by default and show capability boundaries: project-scoped read/write vs Windows Sandbox vs broad **unsandboxed** current-user `computer` grant. Never call all three simply “AI access”.
3. Mask secrets in UI, logs and crash reports; sanitize strings and display file/page text as plain text. Untrusted website text never alters UI actions or permission policy.
4. Separate `pending`, `running`, `success`, `failure`, `unknown outcome`; never retry unknown side-effecting operations automatically.
5. For destructive changes, show exact target, relevant before/after and an explicit local confirmation. No misleading success banners; retain denial/cancel controls and an emergency pause path.
6. Device identity must be cryptographically associated with each authorized tunnel/device in future Multi-PC work; unique device IDs alone are not authentication. Do not mix host permissions across devices or fall back to another machine on failure.
7. Safe updates: verify expected artifact hash and signature; add Windows Authenticode signing with secured CI credentials and release provenance. Existing unsigned Windows standalone builds and `irm ... | iex` install route must not be represented as signed/verified.
8. Never treat a user-level unsandboxed `computer` grant as a security sandbox. Protected-path and UI restrictions cannot guarantee confidentiality against arbitrary code in that account.
9. Store only bounded, purpose-limited and redacted audit metadata; provide explicit diagnostic export with preview and exclude tokens, personal page content and document bodies by default.
10. Protect privileged local decisions against click confusion and race conditions; verify OS ownership/focus and do not use page-rendered approval lookalikes for authorization.

Threat-model review, static/security scanning, dependency audits, manual penetration tests and incident response drills must be completed before describing a release as “security reviewed”. There is no meaningful claim of perfect security.

## 6. Phased PR delivery (do not bundle as one rewrite)

| Stage | PR scope | Deliverable | Exit criteria |
|---|---|---|---|
| 0 | Baseline | Capture 6 pages, compact/tray, approval flows in two viewport sizes and 100/150/200% DPI; document current failures and baseline performance | Reproducible screenshots, metrics, permissions inventory, no installed-state changes |
| 1 | Design foundation | Theme tokens, light/dark/system support, font/spacing/icon policy, accessible buttons, shared components | Visual snapshots in both themes, contrast audit, no permission regression |
| 2 | App shell | Responsive/collapsible sidebar, header, breadcrumb/detail region, error/empty/loading patterns, native window behavior | Keyboard-only navigation, no clipping at 940×640 and 1220×820, legacy routes intact |
| 3 | Overview + quick controls | Trustworthy connection/host cards, event-driven updates, current task summary, tray consistency | No false-connected/false-complete states, emergency controls usable during slow worker |
| 4 | Activity + sessions + projects | Unified event timeline, scoped project views, filters, session/job actions and device identity | No raw sensitive output, test real/unknown failure and cleanup scenarios |
| 5 | Approvals + Security | Impact-first approval review, source/hashes/expiry, risk-level UX, access inventory and audit exports | Owner-only authority verified; denial and expiration tested; never bypass confirmation |
| 6 | Onboarding + connections | Guided first-run, tunnel diagnosis, permission explanation, update/rollback UI | Offline mode available, no token exposure, distinguish 3 connection hops |
| 7 | Release hardening | Windows visual/a11y matrix, Win11/Win10 tests, signed installer/update strategy, supply-chain & threat-model review | CI green, real-device acceptance, rollback tested, security signoff |

### Per-PR release gate

- Ruff and full pytest + Windows native UI acceptance + frozen EXE/installer rollback must pass; add focused screenshots, keyboard and accessibility regressions.
- Permission invariants and protected path tests mandatory for approval/security changes.
- Do not silently modify credentials, owner grants, project roots, VPN/tunnel IDs or installed release.
- New features disabled by default behind explicit local settings until verified on real Windows.
- Compare p50/p95 UI latency, responsiveness and idle resources to stage-0 baseline; reject regressions unless justified.
- Review screenshots manually; automated passing tests alone do not establish professional look or accessibility.
- On a disposable owned-browser CDP screenshot failure, collect only bounded
  process-alive, tab-count, event-count and elapsed-time diagnostics. Never
  dump URLs, credentials, target/session IDs or page bodies; never retry an
  uncertain side-effecting operation. See
  [CI screenshot reliability issue #54](https://github.com/hahhjaaap/Universal-Desktop-Bridge/issues/54).
- Release/merge each PR independently after passing gates; preserve rollback and configuration migration compatibility.

## 7. Suggested acceptance targets (targets, not measured current values)

- No UI-thread stall > 200 ms during ordinary non-destructive navigation in tested reference Windows hardware; target p95 interaction response below 100 ms.
- Keyboard-only navigation to all critical controls, screen-reader names/roles/states, clearly visible focus and disabled states; WCAG 2.2 AA color/interaction principles where applicable to desktop Qt.
- Light and dark theme at 940×640, 1220×820, 1920×1080, scaling 100/150/200%; no clipped labels including Vietnamese diacritics.
- Zero UI-origin grants of owner access, zero plaintext secret values in screenshots/logs, zero approval bypass regressions, zero automatic mutation replay after unknown outcome.
- No regression to existing headless/CLI/MCP client protocols.
- Published installer release only after Windows signing/update verification and separate real-device security assessment.

## 8. First implementation slice

Start PR 1 with only (a) isolated theme tokens, (b) theme switching/persistence via existing owner settings, (c) a native accessible shared button and focus state, (d) screenshots/tests of 6 existing pages in both themes. **Do not redesign approval logic or connection routing in the same PR.**

A UI preview is a **design proposal**, not an installed release. Multi-PC and broader `computer` access are independent security workstreams.
