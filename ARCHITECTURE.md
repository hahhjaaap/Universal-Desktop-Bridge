# UDB architecture and module ownership

UDB has **one canonical Python implementation** under `src/udb/`.
The source checkout, installed wheel and frozen Windows executable use the
same code. The root-level `bridge.py` and `udb_*.py` files are
**compatibility launchers**, not independent backends. Do not duplicate logic
inside them.

## Request path

```text
ChatGPT / MCP client
        |
        v
udb.cli / udb.proxy (single client-facing MCP transport)
        |
        +--> udb.server (registered-project permissions, proposals, Sandbox)
        |
        +--> udb.companion.runtime (worker lifecycle and sessions)
                    |
                    v
              companion.dispatch (single companion tool router)
                    |
                    +--> companion.files + terminal (bounded local operations)
                    +--> companion.extensions (optional file/terminal helpers)
                    +--> companion.features (jobs, documents, processes)
                                |
                                +--> companion.background (job coordinator)
                                |       +--> companion.jobs (task state/cancellation)
                                |       +--> companion.search (bounded worker)
                                |       +--> companion.journal (durable checkpoints)
                                +--> companion.documents
                                +--> companion.system_processes
```

`udb.catalog` translates/consolidates public tool schemas and `udb.registry`
publishes them. The companion's `dispatch.validate_catalog()` rejects schema
names that lack a handler, unexpected handlers and duplicate schemas.
`udb.proxy` owns backend routing, concurrency and response normalization.
Keep this separate from file permissions and owner approvals.

## Connection identity and Multi-PC status

The released source's `udb.desktop` starts a tunnel client using one locally
configured `tunnel_id`. That identifies an MCP endpoint, **not** an arbitrary
set of Windows agents. `udb.proxy` routes tool calls to its own machine's
core and companion workers; it has no built-in per-call `computer_id` router
on `main`. A ChatGPT account using two computers does not by itself alter
that routing boundary.

The independent [draft Multi-PC PR #34](https://github.com/hahhjaaap/Universal-Desktop-Bridge/pull/34)
prototypes a hub, explicit device IDs, loopback-only agents and private
Tailscale transport. It must remain a separate, opt-in review item until
Windows CI, secure deployment and a two-network end-to-end test are verified.
Do not claim that a feature on a draft branch is installed with the latest
published release. Preserve existing per-host owner grants and protected-path
checks; never route an unavailable remote command to the local machine.

## Core policy and approval queues

- `udb.core.Agent`: stable public entry point for project registration, path
  validation, read/write proposals, audit records and diagnostics.
- `udb.core_common`: shared `PolicyError`, canonical JSON and SHA-256 helpers.
  Existing `udb.core` imports are retained for compatibility.
- `udb.core_autonomy.AutonomyMixin`: cohesive owner-only grant management and
  queued source/media/Sandbox work. These methods are inherited by `Agent`;
  they do not become new MCP or HTTP endpoints.
- `requests(status, created)` and `jobs(status)` indexes accelerate queue
  lookup on existing SQLite databases; schema initialization is idempotent.
- Source write proposals store full bounded new text, but only a bounded diff
  preview. Large/truncated diffs explicitly instruct local full-file review.
  Do not silently truncate approval context or bypass owner authorization.
- File listing filters unsupported binary extensions before expensive per-file
  policy checks; every visible entry still passes `Agent.path`.

## Desktop and isolation

- `udb.manager`: Qt MainWindow composition, event/lifecycle handling.
- `udb.manager_host`: assistant page composition and local owner-only browser,
  pause and background-session controls.
- `udb.manager_dialogs`: local source browser, connection settings, and
  owner-only approval dialogs; no remote approval API.
- `udb.manager_refresh`: status polling, project list refresh, real
  permission count updates and accessibility text for compact navigation.
- `udb.manager_widgets`: reusable Qt components, theme-aware custom-painted
  buttons and status indicators. Previous static dark constants remain as
  compatibility exports; new render paths resolve the active theme.
- `udb.ui_theme`: strict `system`/`light`/`dark` presentation preference,
  frozen light/dark tokens, Qt stylesheet/palette application and contrast
  checks. Invalid settings fall back to `system`, never interpreted as CSS.
- `udb.manager`: sidebar can collapse to 72 px while preserving all six
  routes; appearance selector lives under Connection & Settings. This changes
  only local GUI state, not project access or owner authorization.
- `udb.desktop.DesktopController.save_settings`: atomically persists only
  allow-listed GUI settings (`motion`, `autoconnect`, `theme`).
  Appearance changes cannot write credentials or issue grants.
- `udb.companion.jobs`: cancellation, task status and checkpoint lifecycle.
- `udb.companion.search`: search controller plus isolated worker entrypoint;
  `background.search_worker` remains a compatibility export.
- `udb.companion.background`: task pool, bounded transfers, uploads, copy/move
  and recovery. Tree inventory uses iterative DFS to avoid Python recursion
  limits without eagerly loading entire directories.
- `udb.desktop`: owner-side controller.
- `udb.desktop_vm` and `udb.sandbox`: Windows Sandbox orchestration.
- `udb.desktop_guest`: intentionally self-contained guest payload copied
  into an isolated Sandbox. Do not split it into imports without changing
  the guest deployment protocol and testing the resulting boundary.

## Browser and host lifecycle

- `udb.host_service` owns admission, session expiry and the serial mailbox. Session
  creation, resolution and browser opening have separate helpers; all remote
  operations still pass the same owner and resource checks in `dispatch`.
- `udb.browser_actions` is the explicit browser action router and shared public
  action catalog. It never dispatches arbitrary caller-supplied method names.
- `udb.host_browser` owns its private Chrome/Edge process, profile, tabs and
  browser-policy boundaries; public Browser methods remain stable.
  `udb.browser_cdp` owns serialized, bounded WebSocket request handling with
  redacted event markers and bounded ID-only main-frame/document lifecycle events;
  URLs, cookies, headers and request bodies are never retained. Uncertain commands
  are never automatically replayed.
  Browser startup keeps Chromium's normal GPU/rendering defaults; a Windows Job
  Object supplies memory/process limits and a conservative CPU hard cap.
  `udb.browser_input` implements CDP-only virtual mouse, keyboard and viewport-aware
  scroll without injecting operating-system input; `udb.browser_observation` holds
  fixed, bounded, redacting DOM read/snapshot programs. `udb.browser_dom` shares
  bounded traversal across open Shadow DOM roots and locator programs; closed
  shadow roots and iframe documents are not traversed. `wait_for` uses a page-local
  MutationObserver, coalesces mutation bursts and performs bounded 500 ms discovery
  checks for shadow roots, avoiding repeated CDP round trips.
  Page identity artwork lives in `udb.browser_identity`. Callers pass validated
  locators and data, not code.
- `udb.owned_process` owns Windows Job Object containment independently of browser
  and workspace code. `host_browser.OwnedProcess` remains a compatibility export.
- `udb.activity.EventReader` skips unchanged idle polls using database/WAL metadata,
  with a two-second forced rescan for deferred filesystem updates. It validates
  paths on every poll and holds no database handle between reads, allowing log
  replacement on Windows. One-shot callers retain `read_events`.
- CLI commands share an exception-safe settings scope. GUI refresh is divided
  into projects, host status, approvals, jobs and connection updates while
  keeping failures isolated between sections. Tree refreshes preserve selection
  and include visible grant/payload changes in their signatures.
- `udb.computer_files`: bounded streaming hashes, range reads and staged copies;
  internal binary writes and public encoded writes share the same atomic commit,
  expected-hash, recovery and path checks. No-replace copy publication precedes
  the final source recheck for moves.
- Idle approval polling takes no SQLite writer lock when there is nothing to
  expire. Job-log tail reads seek within one open file and keep normal offset
  reads compatible.
- The host mailbox backs off to a 250 ms idle polling interval and prunes stale
  replies every five seconds; stop events interrupt the wait immediately.
- Mailbox commands are claimed and handled independently. JSON reads are bounded,
  malformed envelopes are rejected before dispatch, and RPC waits use a monotonic
  deadline while command expiry remains tied to wall time.
- Failed session cleanup retains a closing record for maintenance/retry and
  rejects new actions for that session. Host/controller shutdown attempts all
  owned resources before reporting incomplete cleanup. Browser handoff state is
  reconciled against the surviving owned window after a transition failure.
- `computer_status` can report the local grant without a running host worker;
  process availability is explicitly unknown in that fallback. It issues no grant.

## GUI state versus security state

The GUI **observes and presents** backend state. Its Qt paint, sidebar,
appearance and focus components do not authorize file writes, launch arbitrary
programs or enable full-computer access. Owner approvals and protected-path
checks remain in the core/host policy layer; backend authorization is required
even if a GUI button is enabled. Conversely, a visual **Tunnel đã kết nối**
indicator is not end-to-end proof that ChatGPT has discovered UDB's tools.

The 200 px/72 px navigation preference is per window and not persisted.
The theme preference is persisted to bounded local `gui.json`, applying
the Qt/Windows system color scheme at launch or when reselected.
The code does not continuously listen for every Windows color-scheme event;
the remaining system-theme and accessibility QA is documented in
[Desktop GUI guide](docs/gui-user-guide.md).

The enterprise UX roadmap and threat model live in
[docs/gui-enterprise-roadmap.md](docs/gui-enterprise-roadmap.md).
Theme foundation and compact navigation are implemented in source; dashboard
redesign, advanced security center, multi-device routing and signed publishing
remain separate development tasks, **not current release guarantees**.

## Where new code belongs

1. Define the public schema in the appropriate companion schema/feature/
   extension module or in the native core server.
2. Add its handler to `companion.dispatch.NATIVE_HANDLERS`, or to the
   corresponding extension/feature registry. Avoid new dispatch branches in
   `Runtime`.
3. Add regression tests for schema parity, permissions, error responses and
   recovery behavior.
4. Run `python -m pytest`, `python -m ruff check src tools tests`,
   `python tools/audit_repository.py --strict`,
   `python tools/check_import_boundaries.py`, and the Windows wheel/EXE
   smoke tests. CI now gates the entire source/tools/tests tree on Ruff.
   `python -m ruff format --check .` also runs in CI. Use `python -m ruff format .`
   before submitting formatting changes.
   The import check guards all canonical modules against eager import cycles;
   it intentionally does not treat deferred function-local imports as cycles.

## Compatibility and safety

Do not remove root or `src/` shim modules solely because their text is
identical: direct source invocation and installed wheel imports both use them.
Do not delete third-party license notices, private owner state, backups,
credentials, datasets or checkpoints as part of source cleanup.

Existing security, browser and accounting PRs are separate. Integrate them
only after their CI gates and compatibility checks; no unreviewed replacement
of a running UDB installation.
