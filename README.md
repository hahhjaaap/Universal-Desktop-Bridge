# Universal Desktop Bridge (UDB)

**Windows-first MCP bridge for ChatGPT and other supported MCP clients.** UDB provides one Python package, one `udb` CLI and a derived public tool catalog (`udb tools` reports the actual count) for guarded local computer work. Its source of truth is `src/udb/`; the root-level `bridge.py` and `udb_*.py` files are compatibility launchers, not separate implementations.

**Tiếng Việt:** UDB kết nối trợ lý AI với máy tính Windows theo quyền do chủ máy cấp. Hỗ trợ thao tác tệp, terminal, ứng dụng, trình duyệt riêng biệt và rà soát hóa đơn Excel. **Không tự cấp quyền, không tự kê khai thuế, không tự sửa dữ liệu kế toán gốc.**

> **UDB 0.12.0 (2026-11-11):** Cloudflare is the remote MCP transport for paired Windows devices, and UDB Live adds terminal and read-only GUI activity views (`udb live`, `udb live --gui`). The new build removes the public local stdio MCP command and legacy OpenAI Tunnel compatibility; pair with `udb setup`, then use `udb mcp-config` for the device-specific HTTPS endpoint. Check [GitHub Releases](https://github.com/hahhjaaap/Universal-Desktop-Bridge/releases), [release notes](docs/release-notes.md), and your installed `udb --version` separately. Worker deployment, Access/OAuth, device grants, and ChatGPT catalog discovery are still configured and verified separately.

## What UDB does

| Area | Supported functionality | Important boundary |
| --- | --- | --- |
| Files and terminals | Scoped reads, guarded writes, search, background jobs, Windows terminal/ConPTY | Owner permissions, protected paths, quotas and no uncertain-write replay |
| Desktop and applications | Owner-enabled Windows UI and process operations | Windows session/UAC limits; local owner consent |
| Browser | Isolated Chrome/Edge, CDP virtual input, bounded DOM snapshots, open Shadow DOM locators, mutation-based waits and navigation | Own profile, local login handoff; explicit same-origin file transfers require separate file access |
| Accounting work tools | Read-only Vietnamese XLSX invoice audit and a **new** review workbook | No original-file overwrite, tax filing, MISA posting or legal tax determination |
| Operations | Activity logs, status/doctor, up to 10 concurrent remote read RPCs (separate lazy stdio workers) and 10 shared background work slots | Remote mutations remain exclusive; hardware and process startup limit throughput |
| Recovery | Saved job state, safe read/recovery paths and managed installer rollback | Uncertain mutations are **never** automatically replayed |

## Cloudflare MCP (paired devices)

Cloudflare is UDB's remote connection. The Windows agent opens an outbound
WebSocket to the existing Worker, and ChatGPT connects to the device's MCP
URL over HTTPS. Use `udb setup` to pair or display the endpoint, then
`udb start` to run the paired agent. Windows still hosts device credentials,
browser sessions, and owner approval controls. See [ARCHITECTURE.md](ARCHITECTURE.md).

### UDB Live

Run `udb live` to follow calls in the terminal. Start `udb live --gui` or
press **Ctrl+Alt+U** to open the read-only activity window while the Cloud
Agent continues running. In UDB Manager, **Ctrl+Shift+L** opens the Live tab.

Calls received by the Windows agent through Cloudflare show `CALLING` and
then `PASS`, `ERROR`, or `RUNNING`, with a call ID and duration. `RUNNING`
means the call handed off a background job. The default view displays
activity metadata and omits tool inputs and output contents.

The Cloudflare Worker deployment, OAuth configuration, device grant and ChatGPT
tool discovery must each be verified independently: see
[Cloudflare project-read acceptance](docs/cloudflare-project-read-acceptance.md)
and [owner pairing guide](docs/pairing-checklist-vi.md).

**Cloudflare connection checklist:** (1) the Windows owner starts Cloud Agent;
(2) the deployed Worker advertises the expected read-only features;
(3) Cloudflare Access/OAuth identifies the owner and `UDB_DEVICE_GRANTS` allows
the requested tool on that device; (4) ChatGPT refreshes the exact MCP catalog
and invokes a read-only tool. A green `/health` or Cloud Agent process alone
does **not** prove end-to-end readiness. See the
[deployment acceptance runbook](docs/cloudflare-project-read-acceptance.md).
The Cloudflare `udb:read` gateway does **not** authorize remote terminal,
file writes or desktop control.

### Optional Render observer (development branch only)

An optional **read-only Render Free dashboard** can check the public Cloudflare
relay health endpoint on demand, without device tokens or command access.
It is **not** a second MCP server, instant failover, or a replacement for owner
permissions. See [Render observer](docs/render-observer.md) and the root
[Render Blueprint](render.yaml). Neither platform is deployed automatically.

## Common Room in the desktop GUI (source feature)

Choose a **registered source project** containing an existing
`chatgpt-workspace/workspace.sqlite3` or
`examples/chatgpt-workspace/workspace.sqlite3` database, then click
**Mở Common Room** on **Dự án**. The Qt dialog uses the *same* Common Room v2
SQLite database as `examples/chatgpt-workspace/workspace.py` and `chain.py`:
read/search discussions, join and post messages, view/create/update tasks with
revision checks, and view verified browser-cache previews.

- No second chat database is created; an absent/outdated database shows guidance.
- No project Python script, local browser or AI process is started by this dialog.
- Chat participants are self-declared labels, not authenticated identities.
- Messages and tasks are user-initiated local edits; `done` is not execution proof.
- Browser images are cached previews, not live tool permissions or browser control.
- A source feature is not automatically present in every installed or published
  executable; verify the exact installed release and its Common Room GUI.

Windows Start/Search is populated by a **per-user Start Menu shortcut**, not by
extracting a portable ZIP. The managed installer creates/updates a UDB-owned
shortcut on successful install/rollback (opt out with `-NoStartMenu`). For
an existing portable EXE, open an attended PowerShell terminal in the
extracted UDB folder and run `.\tools\create_start_shortcut.ps1 -Exe .\udb.exe`
from the bundled portable helper (or use it from a trusted source checkout). The shortcut opens the UDB GUI; it never grants access or
starts an online session by itself. Windows Search indexing may take time.

## Quick start

On Windows, run `udb setup` and `udb start` to connect the paired Cloud Agent.
Use `udb gui` for on-device approvals and browser handoff.
`udb mcp-config` prints the paired HTTPS endpoint for clients that support
remote MCP. An unpaired profile prints an empty server list.

## Windows x64: install and start

Review the installer and [published release](https://github.com/hahhjaaap/Universal-Desktop-Bridge/releases/latest) before executing downloaded code. In your own PowerShell terminal:

```powershell
irm https://github.com/hahhjaaap/Universal-Desktop-Bridge/releases/latest/download/install.ps1 | iex
udb --version
udb doctor
udb start
```

The managed release bundles its Python runtime and workers: **Python, Node.js, Git and Desktop Commander are not required to run it**. It installs under the current user's LocalAppData and stores user state separately in `%LOCALAPPDATA%\UniversalDesktopBridge`. It does not need administrator access. The standalone ZIP is checksum-verified but **not code-signed**. A
Windows-only candidate-release checker is available in
[Release signing and verification](docs/release-security.md), but no
publisher certificate has been provisioned and no signed installer is
claimed.

The first attended start can guide Cloudflare pairing.

```powershell
udb setup
udb start
udb status --json
udb live
udb stop
```

For another Windows device, enroll it through Cloudflare and use that device's
MCP URL and grant. Troubleshoot each layer using
[remote-device diagnostics](docs/remote-device-troubleshooting.md).

### When ChatGPT cannot call UDB tools

A running Windows Cloud Agent alone does **not**
prove that the current ChatGPT conversation has discovered the MCP catalog. Troubleshoot
in order, without resetting credentials or loosening permissions:

1. Run `udb status --json` and `udb doctor --json` on the intended computer.
   Check the Windows worker, Cloudflare pairing and ChatGPT discovery separately.
2. In ChatGPT, confirm that the **intended** UDB connection is enabled and that
   UDB tools are actually available to the conversation. A Connected label alone
   is not an end-to-end tool invocation test.
3. Test a read-only UDB status tool before file writes or terminal commands.
   Record whether discovery or invocation failed; these are different problems.
4. If two computers use UDB, verify which machine the current connection targets.
   Never infer the selected host from a local readiness indicator on either PC.
5. Collect redacted `udb logs` and diagnostic output for a bug report. Never
   paste access tokens or private file contents into an issue.

Verify the Cloud Agent process and a read-only invocation in ChatGPT.


### Common commands

| Command | Purpose |
| --- | --- |
| `udb tools` | Show the actual public tool catalog |
| `udb start` / `udb stop` | Start or stop the local agent |
| `udb status` / `udb doctor --json` | Inspect health, runtime and setup |
| `udb logs --details` | Follow redacted tool activity |
| `udb setup` | Pair a Cloudflare device or display its existing endpoints |
| `udb live` / `udb live --gui` | Follow tool activity in the terminal or read-only activity window |
| `udb update --check` | Check the latest published stable release |
| `udb update` / `udb rollback` | Managed installation update / previous-release rollback |
| `udb autostart enable` / `udb autostart disable` | Opt in/out of startup at Windows sign-in |

Cloudflare-paired users can opt in to start Cloud Agent **after Windows sign-in** with `udb autostart enable --home PATH`. This must be run once from an attended local Windows terminal, with terminal access disabled; it does not grant new device permissions. `udb autostart status --json --home PATH` reports `cloud_agent_enabled`, and `udb autostart disable --home PATH` removes this user's logon entry. Auto-start is at user sign-in, not before login or under SYSTEM.


| `udb mcp-config --home PATH` | Print the paired remote MCP configuration |
| `udb --access computer` | Attended local owner opt-in to broader computer access |

Updates and rollback must be started **outside UDB's own running tool job**. They preserve the owner's state, not a snapshot of that state. Keep independent backups. Never assume a timed-out update failed; inspect `udb --version` and `udb status` first.

## Accounting-first workflow: Vietnamese invoice XLSX

The `spreadsheet` tool supports two guarded actions:

- `audit_invoices` — read an authorized XLSX file, identify missing invoice fields, possible repeated identifiers, invalid/formula amounts and differences between net + VAT and total. Up to 10,000 data rows are scanned; the source is not changed.
- `export_audit` — create a **separate** XLSX review report after checking the source's expected SHA-256. Existing destinations are rejected.

Example tool arguments (not a shell command):

```json
{"action":"audit_invoices","path":"invoices.xlsx","sheet":"Sheet1"}
```

Reports are for human review. Possible duplicates may be legitimate invoice line items; the tool does not decide VAT liabilities or submit anything to a tax authority. For column mapping, Vietnamese headers, export parameters and safeguards, see **[Accounting Work Tools](docs/accounting-worktools.md)**.

## Isolated browser workflow

With locally authorized host-browser access (**Máy tính → Cho phép mở phiên nền trên máy này** in the Windows manager), use `host_browser(action="open", url="https://example.org/")`. This starts a private headless Chrome/Edge session automatically or reuses the current unexpired browser session. Keep the returned `session_id` and `tab_id`, inspect `snapshot`, then use `click`, `wait_for`, `press`, `select_option`, `check`, `uncheck`, `back`, `forward` or `reload` as appropriate. Prefer accessible role/name locators over brittle CSS selectors. Snapshots are bounded, include supported open Shadow DOM roots and redact secret-like fields; closed shadow roots and iframe contents are not traversed. Page content is untrusted and cannot grant permissions.

For a known short sequence, send one native batch instead of one MCP round trip per action:

```python
host_browser(
    action="batch",
    session_id=sid,
    tab_id=tab,
    request_id="profile-edit-001",
    steps=[
        {
            "action": "fill",
            "role": "textbox",
            "name": "Display name",
            "value": "New name",
        },
        {"action": "click", "role": "button", "name": "Save"},
        {"action": "read"},
    ],
)
```

Only use locators already observed on the page. Batches accept 1..12 steps on one owned tab with a shared 20-second deadline, stop after failed/uncertain input, and recheck permission, resources and ownership between steps. A stable `request_id` prevents replay after a timeout or lost response: query `batch_status` first; the same ID returns cached output or metadata, never reruns the sequence. Reusing an ID for different steps is rejected. `batch_cancel` bypasses the action queue and requests a stop between steps; it cannot undo or interrupt dispatched input. Receipts contain metadata/digests only; up to 16 completed result bodies remain in worker memory and 256 receipts are retained per session. After lost/evicted output, inspect the page before any new mutation. Transfers, nested batches, session changes and arbitrary JavaScript are excluded.

Use `host_browser(action="capture_start", session_id=sid, tab_id=tab)` once, then `host_screenshot(session_id=sid, tab_id=tab, cached=True)` to read the latest fresh image. `capture_status` reports frame time/age/errors; `capture_stop` releases the cache. The worker keeps at most four streams and one base64 PNG of up to 4 MiB per stream in memory. Capture targets 1 FPS without a backlog: long actions, owner handoff, expired sessions and resource pressure can delay or stop it. Cached reads reject stale/error frames (default maximum age 3 seconds, configurable 100..10000 ms). This cache does not capture the physical desktop.

For HTML dropdowns, use `select_option` with the select locator and an option value or exact label; `fill` on a native select uses the same selection path. Values take precedence over labels, ambiguous labels are rejected, and disabled options/optgroups remain blocked. `read` and `snapshot` include up to 20 options per select (`options_truncated` flags longer lists), effective disabled state and `readonly`. A direct option click returns `use_select_option`. Disabled/readonly controls fail immediately; use `wait_for(state="enabled")` explicitly for a temporarily disabled control. Clicks observe URL and main-frame loader changes, including repeated same-URL form submissions. A navigation read may recover from a transient context/response timeout within the existing deadline; uncertain writes are never automatically replayed.

The browser uses a separate headless profile and Chrome's normal GPU/rendering defaults; UDB does not emulate a slower CPU or force software rendering. The owned process still has explicit memory/process limits and a conservative Windows CPU hard cap to protect the interactive desktop. It does not take over the user's signed-in browser or permit arbitrary caller-supplied page JavaScript. Automatic Chrome downloads stay blocked; explicit `upload`/`download` transfers are limited to 8 MiB and require separate owner-enabled computer access, an observed origin and file checks. File inputs inside supported open Shadow DOM roots can also be selected. UDB-owned pages display a compact **UDB · AI** status pill, an AI favicon and a page-local AI cursor in screenshots. The cursor follows CDP clicks inside that page, fades after the action, and never moves the physical mouse. The pill distinguishes background work from local owner control. The label is a visual aid; use session/tab IDs and `owner="UDB"` response metadata to establish ownership. No Chrome extension is required for this private-browser identity.

This is the default route for automated web tasks: it does not open a visible personal Chrome tab. Observe it through `host_screenshot(session_id=..., tab_id=...)`. Existing `host_start_session(kind="browser", task="...")` and `host_browser(action="new", session_id=..., url="...")` calls remain supported. Reusing a session does not extend its owner-authorized lifetime. Errors are returned for inspection, without retrying an uncertain action or falling back to physical desktop input.

## Headless status and connection recovery

Run locally in your owner terminal:

```powershell
udb status --watch
udb status --watch --json --interval 1 --count 10
udb reconnect --wait 30 --json
```

The status viewer opens no GUI and reports heartbeat/uptime, local tunnel and worker readiness, active action/batch progress, the last operation and recent tool outcomes. It omits command bodies, page contents, selectors and result payloads. The viewer does not start the manager or change permissions. `udb reconnect` requests a new tunnel for the exact live headless process, preserving local grants and the host worker. Use it outside active tool calls: reconnection can drop an in-flight response; inspect status/page state before retrying uncertain input. It does not update the saved offline/online startup preference.

`bridge_status.readiness` distinguishes a responding MCP transport from worker readiness, pause and owner grants, and includes the next local action. If a client exposes only status/project tools, refresh its MCP catalog after updating; a plugin with a fixed tool allowlist must also expose the canonical browser tools. Reconnection alone cannot add tools to that allowlist.

## Browser login, Windows control and utilities

In **Máy tính**, choose **Tôi đăng nhập** to use UDB's own browser window. While it is handed to you, AI browser operations and UDB desktop input pause. Choose **Trả về cho AI** when finished; pages reload and old tab IDs must be refreshed. Enable **Nhớ đăng nhập trong browser UDB** while the browser is closed to retain that profile across sessions. Disabling it forgets only UDB's saved login.

For native desktop control, UDB yields to recent user input. **Ctrl+Alt+Shift+Backspace** or the manager's pause button latches a local pause; only a local resume clears it. The manager reports when the shortcut could not be registered. This is cooperative yielding, not exclusive input ownership or cancellation of external commands already running.

The unified `computer_desktop` tool also provides text clipboard read/write with version checks, UDB notifications, and Start Menu app discovery/launch. Its UIA actions can read text, set a checkbox state, select an item, expand/collapse and scroll an item into view. `computer_process(action="start")` launches an owned job; list/read/stop use the same tool. Legacy `computer_utilities` and `computer_execute` calls remain supported. Existing `udb --access computer` activation is required. See [Windows control tools](docs/windows-control-tools.md) for the consolidated interfaces and examples.

## Visible tab in an existing Chrome window (owner computer access)

Use this separate option only when explicitly asking for a **visible personal Chrome tab**; it can activate Chrome and is not background automation. For a tab in a Chrome window that is already open, call
`computer_desktop(action="open_chrome_tab", text="https://example.org/")` after
the owner has locally enabled `udb --access computer`. UDB checks for a real
running Google Chrome process and asks Chrome to open a **new tab**, without
creating a separate automation profile or injecting mouse/keyboard input.
The action refuses to launch Chrome if no existing Chrome window is found.

This is **not** the isolated `host_browser` API: it does not attach CDP,
claim ownership of personal tabs, or provide DOM/CSS automation. To interact
with the visible tab, use the owner-granted `computer_desktop` UIA/screenshot
operations after observing a fresh window ID. Chrome may select a different
window when several Chrome windows/profiles are open; inspect the returned
window-reuse observation and the actual desktop before continuing. The tab
uses the user's current Chrome profile and signed-in website context.

### UDB Aura tab identity (optional Chrome extension)

The existing-Chrome action can use the **UDB Aura** Manifest V3 extension in
`chrome-extension/udb-aura/`. When installed and explicitly enabled, UDB
opens a local extension launch page; the extension opens the destination in
the **existing Chrome window**, groups it under **UDB • AI** (cyan), sets an
**AI** toolbar badge, and injects a compact mint AI label **only into
explicitly marked public HTTP(S) tabs**. It also adds a best-effort
UDB favicon on marked tabs, without changing their page titles. It does not
read page content or upload browsing data. Removing the mark removes the
UDB favicon; Chrome does not allow arbitrary RGB effects in its native tab strip.

1. In Chrome, visit `chrome://extensions`, turn on **Developer mode**,
   choose **Load unpacked**, and select `chrome-extension/udb-aura/`.
2. Verify that the extension ID is `ancaoelohcjcbbmncfhimpookhdelhle`.
3. In a **local owner terminal**, run
   `powershell -NoProfile -File tools/enable_chrome_aura.ps1` and confirm
   the ID displayed in Chrome. This writes an opt-in marker under
   `%LOCALAPPDATA%\UniversalDesktopBridge`.
4. After deploying a new UDB build, call `computer_desktop` with
   `action="open_chrome_tab"` and a public URL in `text`. The result
   reports `branding_requested`; actual group/badge application must be
   verified visually. Without the marker, the ordinary visible tab is used.
5. Disable via `powershell -NoProfile -File tools/enable_chrome_aura.ps1 -Disable`.

**Permissions:** The extension requests Chrome `tabs`, `tabGroups`,
`storage`, `scripting` and HTTP(S) site access to decorate only the
marked tabs. This is broader Chrome permission than the original headless
browser; review the extension source before installing. It is never
silently installed or enabled by UDB.

### Automatic independent AI cursor

When a client initializes UDB and **owner-granted desktop computer access**
is already active, the companion displays a compact, click-through **UDB • AI**
cursor overlay on the current Windows desktop. The physical system cursor is
unchanged. At rest, a small identity pill sits near the edge of the work area; the arrow appears near actions and returns to its dock after a short idle period. The overlay uses per-pixel alpha and monitor DPI scaling. It is hidden during local pause/handoff and closed when
the MCP proxy disconnects, the desktop grant is revoked, or the companion
stops. It does not grant access or perform mouse actions by itself.
`virtual_pointer(action="show")` can display it manually, and
`virtual_pointer(action="hide")` hides it for the current connection.
Existing `virtual_pointer` move/click actions remain bounded Win32
messages; compatibility depends on the application, and an independent
visual cursor is **not** a second hardware/system mouse.

## Desktop interface — source GUI (Cloudflare-first)

`udb gui` opens a compact native control panel when a system tray is
available. It offers connection, local Windows pause/resume, browser login
handoff, background-session closure and recent metadata-only activity.
Closing its windows returns to the tray; **Thoát UDB** in the tray menu
explicitly stops the GUI-owned runtime. Without a tray the full manager is
available. See [Compact controls](docs/compact-controls.md).

The **full manager** retains six pages — **Dự án**, **Quyền AI**,
**Tiến trình**, **Bảo vệ**, **Kết nối** and **Máy tính**. Its sidebar can be
collapsed from 200 px to 72 px with **Thu gọn menu** and expanded again;
tooltips and accessible route names remain available when compact. This
selection is not persisted between launches.

Under **Kết nối → Giao diện ứng dụng**, select **Theo hệ thống Windows**,
**Sáng**, or **Tối**. Appearance updates immediately in the Qt application and
is saved to the user's local, allow-listed `gui.json` preferences; the
Windows-derived choice is applied at startup and when Qt reports a system
color-scheme change; unsupported platforms retain startup detection. Theme switching never
changes computer permissions, credentials or MCP access. The desktop shell
uses shared Qt theme tokens and visible keyboard focus states, but it has not
yet completed all enterprise GUI / accessibility milestones.

The overview reports the local **Agent**, the selected **Cloud Agent or
legacy Tunnel** state, and separate **ChatGPT** verification. ChatGPT remains
**Chưa xác minh** until a read-only tool is actually invoked in the
conversation. A failed local status read cannot retain a stale green
indicator. Neither transport state proves ChatGPT tool discovery. The emergency
Windows pause controls stay distinct from background browser and job lifecycle.
For the complete user-facing behavior and security limitations, read
[Desktop GUI guide](docs/gui-user-guide.md) and the
[enterprise UI/security roadmap](docs/gui-enterprise-roadmap.md).

The **Kết nối → Giao diện ứng dụng** settings now expose a local
**Giảm chuyển động** option. This changes only animations and persists as
the existing allow-listed `motion` preference in `gui.json`; it cannot
change browser, project or computer permissions.

The full manager also includes a persistent themed page header with an
transport-specific **Cloud Agent/Tunnel** (not ChatGPT) indicator. The **Hoạt động MCP** tab
displays a bounded, sanitized tool activity timeline. Owner-triggered audit
export writes only timestamps, tool labels and statuses to a new JSON file,
after confirmation, and never overwrites an existing file.

The **Tiến trình** page now supports metadata-only search and group filters
(Đang chạy/Cần chú ý/Đã xong), shows matching counts and clears stale
details when no result matches. Ctrl+1..6 changes full-manager pages;
Ctrl+Shift+F focuses job search. The **Kết nối** page includes a
local-only button that copies `udb doctor --json` without executing it.
Owner approval dialogs now state an explicit operation-specific impact
before the existing full review and local confirmation. No filtering of
log bodies or secret content is performed.

The **Bảo vệ** page also displays read-only, locally observed status for
pending owner approvals, host-input pause and source auto-edit grants. These
signals do **not** represent ChatGPT authorization, a completed security
assessment or the state of every background process. Failed reads show
**Chưa xác minh** instead of retaining stale positive states.

The **Kết nối** page now has a native three-step onboarding panel showing
separately whether (1) the local Agent responds, (2) Cloud Agent is running
or the legacy Tunnel is ready, and (3) ChatGPT has actually called a UDB tool. The third step stays
**Chưa xác minh** until verified directly in ChatGPT; no remote grant or
invented end-to-end success state is introduced. Failed local reads clear
stale ready indicators.

The app header now also carries an always-visible, read-only **Windows
privilege** warning: an enabled broad unsandboxed computer grant is distinct
from project permissions and transport readiness. Unknown/unreadable grant
states appear neutral, never as a verified safe or authorized result.

The **Bảo vệ** page now shows a read-only indicator of optional full Windows
computer access. If enabled, it warns that this privilege is **unsandboxed**
and can reach files protected only against project-scoped tools. The GUI
cannot enable or revoke this grant; use the attended local terminal
(`udb revoke-access` to revoke).
For the complete user-facing behavior and security limitations, read
[Desktop GUI guide](docs/gui-user-guide.md) and the
[enterprise UI/security roadmap](docs/gui-enterprise-roadmap.md).

Developer-only disposable visual review:

```powershell
python -m ruff check src tools tests
python -m ruff format --check .
python -m pytest tests/test_ui_theme.py tests/test_manager_ui.py tests/test_quick_controls.py
python -c "from udb.manager import self_test; self_test('ui-previews')"
```

The GUI self-test captures six existing pages under light/dark palettes and
does not approve any file mutations. For headless Linux install
`PySide6-Essentials==6.10.2` and set `QT_QPA_PLATFORM=offscreen`.
For native Windows pointer preview use
`python tools/check_windows_workflows.py --pointer-preview PATH.png`.
Passing CI and screenshots does not replace real Windows accessibility or
security assessment. Source changes do not imply an installed release; verify the executable and its feature set.


## Build from source (developers)

Python **3.11+** is required for development. Windows is required for native desktop/GUI and frozen EXE acceptance; Linux supports source, protocol and policy tests.

```powershell
python -m pip install -e ".[office,dev]"
python -m ruff check .
python tools/check_import_boundaries.py
python tools/audit_repository.py --strict
python -m pytest
python -m build
```

The repository audit uses `git` to enumerate tracked files. For a Windows standalone build:

```powershell
python -m pip install ".[office,freeze]"
python tools/fetch_build_assets.py
udb build --exe
python tools/check_frozen.py dist/udb.exe
```

The build fetches only pinned public helper binaries with SHA-256 checks; retain their license notices in `THIRD_PARTY_NOTICES/`. CI tests Linux/Windows Python matrices and Windows EXE/installer smoke tests. An Actions success does not by itself mean a new GitHub Release was published.

Run `python tools/benchmark_runtime.py` for repeatable synthetic file-memory,
idle polling, terminal checkpoint and activity-log measurements. See
[Performance measurements](docs/performance.md) for scope, baseline and limits.
The [simulation report](docs/simulation-report.md) describes fault cases,
platform coverage and commands to reproduce the checks. CI uploads JUnit reports
for each Linux/Windows Python matrix job.

## Shared ChatGPT workspace (optional)

The [Common Room example](examples/chatgpt-workspace/README.md) adds a native
Windows dashboard for shared discussions, topic search, replies and revision-checked
task assignments. It includes batched room/browser commands and a separate
headless Edge-or-Chrome worker (Edge preferred, Chrome fallback when Edge is
missing) with a bounded 1 FPS screenshot cache. Long messages wrap
and remain readable in full.

This optional source example requires Python and its listed image/browser
dependencies; it is separate from the managed UDB executable. Copy it into an
authorized UDB project before using it. Conversation databases, image caches,
installed dependencies and machine-specific data stay local. Tasks do not wake
closed ChatGPT chats, and browser actions use a fresh owned context.

## Repository layout

```text
src/udb/             Canonical package, CLI, MCP proxy, policy, browser and manager
src/udb/companion/   Scoped files, terminals, jobs, search and accounting worker
tests/               Automated regression and platform tests
tools/               Build, verification, packaging and repository audit
.github/workflows/   CI, Windows release and public-installer acceptance
docs/                Feature documentation
build-assets/        Public helper manifest and license inputs (not private binaries)
THIRD_PARTY_NOTICES/ Bundled third-party notices required for distribution
install.ps1          Managed Windows installer
```

Compatibility launchers and import aliases are intentionally retained. Generated `build/`, `dist/`, virtual environments, credentials, private state, model checkpoints and local caches **must not be committed**. Historical 0.9.x audit reports were retired from the active tree; their commits remain available in Git history.

## Safety and limitations

- No MCP request can silently grant computer, protected-source or Sandbox access. Owner approvals are local and explicit.
- Project-scoped operations and broad computer access are different permission paths; enabling one does not bypass protected roots.
- Unknown-result writes, terminal commands and other mutations must be reviewed before retrying.
- Source work, document reviews and browser pages can contain untrusted content. Review outputs before acting.
- This project is a local bridge, **not ChatGPT Work**, a tax-compliance service or an autonomous account administrator.

**Documentation:** [Desktop GUI](docs/gui-user-guide.md) · [Enterprise GUI roadmap](docs/gui-enterprise-roadmap.md) · [Architecture](ARCHITECTURE.md) · [Accounting Work Tools](docs/accounting-worktools.md) · [Example configuration](udb.example.toml) · [MCP example](MCP_CONFIGURATION.example.json) · [Releases](https://github.com/hahhjaaap/Universal-Desktop-Bridge/releases)

**License:** [MIT](LICENSE). Third-party components retain their own licenses.

