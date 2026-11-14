# UDB desktop GUI — appearance, navigation and security

> **UDB 0.12.0 docs review (2026-11-13):** **Current UDB 0.12.0 source guidance.** Verify the installed executable, Cloudflare Worker, OAuth and owner grants separately; source changes do not update them. See [version/status](current-version.md).

Applies to the UDB v0.12.0 Cloudflare-connected source GUI. Check the
[installed release](https://github.com/hahhjaaap/Universal-Desktop-Bridge/releases)
separately: source on `main` does not update a previously installed EXE.
The public OpenAI Tunnel compatibility transport was removed in v0.12.0;
any legacy Tunnel UI references in earlier releases are historical, not a
supported setup path. This guide does not promise an enterprise redesign.

## Start the interface

On the owner-controlled Windows computer:

```powershell
udb --version
udb doctor
udb gui
```

`udb gui` opens compact controls if the system tray is available; otherwise it
opens the full Qt manager. In compact mode, select **Mở UDB đầy đủ** to open the
six-page manager. A separate `udb start` windowless process is not silently
replaced; stop it explicitly before switching to the GUI, understanding that
stopping closes owned sessions.

**The desktop UI is local.** It is not a remote web control panel. Opening the
GUI, switching a theme or collapsing the navigation never grants the AI
additional access.

## Appearance: light, dark and Windows

In the full manager, open **Kết nối** and look for **Giao diện ứng dụng**.
Choose:

| Preference | Behavior |
| --- | --- |
| **Theo hệ thống Windows** | Choose light/dark from the Qt/Windows system color scheme when the GUI starts or when the appearance selection is applied |
| **Sáng** | Always use UDB's light palette |
| **Tối** | Always use UDB's dark palette |

In the same **Giao diện ứng dụng** section, **Giảm chuyển động trong giao
diện** disables nonessential hover/transitional animations. Changes take
effect immediately and persist in the existing bounded `gui.json`
`motion` preference. Saving failure restores the previous choice; this
setting never grants AI access.

The selection is applied immediately to the running Qt application and saved
as an allow-listed `theme` preference in the owner's bounded `gui.json`
settings. The key is one of `system`, `light`, `dark`; invalid values
fall back to `system` rather than entering a Qt stylesheet. Existing
`motion` and `autoconnect` preferences remain. No credentials are stored
in `gui.json`.

**Limitation:** The app listens for Qt's system color-scheme change signal and updates
while it is running when supported. Some Windows themes or older platforms
may not emit the signal; reopen the app if an OS appearance change is missed. System high-contrast mode and 200% DPI still need
separate real-device review.

## Activity filters, navigation and approval review

In **Tiến trình**, search by project, language, status or job ID.
Choose **Tất cả**, **Đang chạy**, **Cần chú ý** or **Đã xong**. Filters
read only bounded task metadata and never search script or log contents.
A failed/unknown task does not automatically become **Đã xong**. Changing
filters clears hidden stale task details; no job state changes.
The separate **Hoạt động MCP** tab shows a bounded read-only timeline of
sanitized tool names, status and timestamps. Unknown tool identifiers are
rendered as **Công cụ UDB khác**, rather than revealing an arbitrary value
from untrusted metadata; recognized tools use a fixed list of display names.
It never displays request payloads, raw scripts or file bodies and cannot
be used to re-run commands.
The local **Xuất metadata đã ẩn thông tin nhạy cảm** action confirms intent,
then saves a **new** JSON file (never overwriting an existing file) with
only timestamps, tool labels and states. Inspect the destination before sharing
it because even sanitized metadata can reveal which tools were used.
A persistent header displays the current page, a **Cloud Agent process**
indicator for paired profiles and a separate **Windows privilege** indicator.
An unpaired v0.12.0 profile must be paired through `udb setup`, not through an
old Tunnel transport. Neither a running Cloud Agent nor a green local status
proves ChatGPT can invoke MCP tools. If the optional broad
current-user computer grant is active, it warns **Windows: không sandbox**
on every page. Unknown local grant status stays **chưa xác minh**, never a
green authorization or safety claim. Disabling that broad grant does not
imply project-scoped or Sandbox permissions are disabled. The header does
not authenticate a ChatGPT tool call.

Keyboard shortcuts in the full manager: `Ctrl+1` through `Ctrl+6`
navigate the six pages; `Ctrl+Shift+F` opens and focuses task search.
In **Kết nối**, **Sao chép lệnh kiểm tra** copies only `udb doctor --json`
to the local clipboard; it does not execute a command or share diagnostics.

Owner approval dialogs display an operation-specific impact notice:
real file modification, host-side media download, Windows Sandbox desktop,
or Sandbox script execution. Existing full diff/script tabs, request hash,
expiry, explicit review checkbox and secondary local confirmation remain
mandatory. Untrusted request/file strings are rendered as plain text.

## Common Room (source-only integration)

On **Dự án**, select a registered project containing an existing
`chatgpt-workspace/workspace.sqlite3` or
`examples/chatgpt-workspace/workspace.sqlite3` (source checkout), or register
the `chatgpt-workspace` folder itself. Then click **Mở Common Room**. A
native Qt window opens the existing version-3 SQLite database (no migration or
duplicate room creation), with tabs for discussion, tasks and the checked
browser-cache preview. Use **Tham gia** before posting, **Làm mới** to see
updates from other chats, and check task revisions before modifying state.

The Common Room panel does not run scripts from the registered project, start a
browser worker, grant desktop control or authenticate chat identities. Its
status labels distinguish cache freshness from live connectivity. It opens
only after the local owner chooses a project. Availability in an installed executable depends on its exact release; check
`udb --version` and the installed GUI rather than inferring it from source.

## Navigation and quick controls

The manager retains its six pages: **Dự án**, **Quyền AI**,
**Tiến trình**, **Bảo vệ**, **Kết nối**, **Máy tính**.

The sidebar's **Thu gọn menu** control switches between 200 px and 72 px.
Collapsed routes retain their tooltips and accessible names, and any
permission-request count is available through accessibility metadata. Expand
using **Mở rộng thanh điều hướng**. The collapse state lasts only for the
current window; it is not persisted across restarts.

Quick Controls retain connection, Windows input pause/resume, browser login
handoff, background-session closure and recent metadata-only tool activity.
Close/minimize-to-tray, **Đóng phiên nền** and **Thoát UDB** remain distinct
actions: none should be described as stopping all unrelated jobs.

The emergency local Windows pause is independent of the appearance controls.
The pause latch protects real desktop input, but **does not automatically stop
all background browser/terminal/Sandbox operations**. Use the appropriate
session/job controls when necessary.

## First-run onboarding in Connection settings

The **Kết nối** page distinguishes three checks: **Agent trên Windows**
(local worker heartbeat), **Cloud Agent** (requires an explicit Cloudflare
pairing), and **Xác minh tại ChatGPT** (requires a separate read-only UDB
tool call). In v0.12.0, an unpaired profile must use `udb setup`; historical
**Kết nối Tunnel** controls are not the supported remote setup route.
The Cloud Agent indicator reports its **local process** state, not a verified
remote WebSocket/OAuth session. The ChatGPT step stays **Chưa xác minh**
until tested from the actual conversation. Unreadable local status must not
retain a stale positive state. The guide does not store a password, test a remote endpoint,
start a browser, approve an operation or grant computer permissions.
The **Sao chép lệnh kiểm tra** control copies `udb doctor --cloud --json`
for Cloudflare-paired profiles, or `udb doctor --json` for unpaired
profiles. This fixes the case where a Cloudflare owner ran a local-only check
and mistakenly assumed OAuth had been tested.

A separate **Kiểm tra kết nối Cloudflare** button appears for paired devices.
When explicitly clicked, it performs public, unauthenticated Worker/Access
checks in the background and displays a fixed next action for missing pairing,
an old Worker or an invalid Managed OAuth challenge. The button never reads
device credentials, starts a Cloud Agent, changes owner grants, or logs into
ChatGPT. Even when it reports **public checks passed**, the ChatGPT step
remains unverified until a permitted read-only MCP call succeeds.

## Overview: three separate connection checks

The top of **Dự án** displays three compact indicators:

| Indicator | What it verifies | What it does not verify |
| --- | --- | --- |
| **Agent** | Host worker reported a local readiness heartbeat | Authorized computer access or ChatGPT RPC |
| **Cloud Agent** | Local Cloud Agent process state on paired profiles; unpaired devices require explicit setup | Whether Worker is deployed, OAuth/grants are valid or ChatGPT discovered tools |
| **ChatGPT** | Always **Chưa xác minh** (unverified) in this GUI release | No GUI-side network test is invented |

On a failed local status refresh, the corresponding Agent/transport indicator
must not retain a stale verified-ready state.
Automatic status refresh is local-only and grants no access. Only the
owner-clicked Cloudflare check performs a public, credential-free network
probe. To verify end-to-end ChatGPT connectivity, run an actual **read-only**
UDB tool in ChatGPT.



For an already paired device, the main **Kết nối** action starts/stops the
**Cloud Agent** flow rather than asking for an OpenAI Tunnel ID. The attended
`udb setup` command recognizes the pairing. The old `--edit` flag is only
accepted for compatibility, not as a separate Tunnel-editing workflow;
**do not paste a workers.dev URL into a legacy Tunnel prompt**. The pairing and device token
are not erased when the GUI changes transport. A missing or invalid pairing
must not silently be treated as authorized. The Cloudflare `udb:read`
gateway only exposes explicitly granted metadata/project read tools; no
write, terminal or desktop access follows automatically.

## Connection status is not authorization

- **Local agent:** the worker is reachable on this PC.
- **Cloud Agent:** process running is a local transport observation. It does
  *not* prove that Cloudflare Worker, device OAuth/grants, MCP discovery or
  ChatGPT tool invocation succeeded.
- **ChatGPT invocation:** confirm in ChatGPT with a *read-only* status tool.
- **Permission grant:** separately authorized by the owner on the Windows
  machine; not inferred from any connected indicator.

PR #183 adds an opt-in account Fleet candidate with one `/v1/account/mcp`
resource and explicit `device_id` routing. It is not deployed to the current
staging Worker or production, and does not yet constitute accepted production
one-plugin Multi-PC selection. Do not infer another PC from a green connection
label; distinguish the exact Cloudflare device ID and owner grants on paired
devices. See
[remote-device troubleshooting](remote-device-troubleshooting.md) and
[Cloudflare deployment acceptance](cloudflare-project-read-acceptance.md).

## Security page: distinguish actual protection boundaries

The **Bảo vệ** page displays a local read-only **Quyền Windows toàn diện**
indicator. It derives its state from the same local computer-grant validation
as UDB's computer API, not from a checkbox or ChatGPT connection status.

- **Đã bật · không sandbox:** the current Windows user has granted broad
  computer operations; project-protected paths are **not** an access boundary
  for this privilege. A local attended owner can revoke via `udb revoke-access`.
- **Không khả dụng:** no usable broad grant was confirmed. Project-scoped and
  Sandbox permissions are separate and may still be active.
- **Chưa xác minh:** status could not be read; the UI never reports granted or
  safe access based on a failed check.

The read-only **Tổng quan quyền và hoạt động** area has three separate
owner-local observations: (1) pending approval count, (2) Windows host-input
pause state, and (3) number of projects with scoped auto-source edits enabled.
Each indicator distinguishes unknown data from a successful read and does
not reproduce request payloads, project paths or credentials. A timestamp
identifies the last local grant-check attempt; it is not proof of a recent
ChatGPT tool invocation. Pausing host input does **not** terminate browser,
Sandbox or other background jobs. A zero approval count does not certify
overall system security.

The GUI does not offer a remote grant/revoke button. Protected-path tables
describe scoped project restrictions, **not** absolute Windows isolation.

## Security boundaries

The GUI renders status and locally requests already-supported owner actions.
It is **not** a new security boundary and must not be trusted to enforce policy
without backend checks. In particular:

- Owner-only approvals remain local, request-bound, expiring and checked in the
  core policy engine. GUI appearance changes do not auto-approve requests.
- Project-scoped file access, Windows Sandbox and broad unsandboxed
  `udb --access computer` permissions are *not interchangeable*. A broad
  computer grant can access data available to that Windows user account; it
  is not a sandbox.
- Treat webpage text, document contents, log messages and scripts as untrusted.
  Never paste runtime keys into chat, source files or issue reports.
- A timed-out file change or UI action can have an **unknown outcome**.
  Inspect the state before trying again. Never automatically replay mutations.
- Published ZIP/installer signing is a separate release-supply-chain concern;
  the latest published v0.12.0 standalone ZIP is still not Authenticode-signed
  (see [release notes](release-notes.md)).

## Quality assurance for developers

Use a disposable project and **do not** grant real computer access for GUI
preview generation.

```powershell
python -m pip install -e ".[office,dev]"
python -m ruff check src tools tests
python -m ruff format --check .
python -m pytest tests/test_ui_theme.py tests/test_manager_ui.py tests/test_quick_controls.py
python -c "from udb.manager import self_test; self_test('ui-previews')"
```

The Qt self-test captures the existing six full-manager pages in light/dark,
and separately exercises compact controls and approval dialogs with synthetic
data. Approval screenshots do **not** authorize writes. The Windows CI additionally
tests native controls, EXE packaging and managed rollback.

**Limitations:** Screenshot generation and CI passes do not prove that font
scaling, screen readers, title-bar colors or animation behave correctly on
every real Windows hardware configuration. Complete an attended Windows visual,
keyboard and accessibility pass before claiming commercial-grade UX.

## Implementation and follow-up

- [Enterprise UX / security roadmap](gui-enterprise-roadmap.md) — partially
  implemented; the remaining security center, dashboard and release-hardening
  stages are **not shipped**.
- [Compact controls](compact-controls.md) — tray and local control semantics.
- [Architecture](../ARCHITECTURE.md) — canonical module ownership and access
  boundaries.
- [Releases](https://github.com/hahhjaaap/Universal-Desktop-Bridge/releases) —
  authoritative published installer version.
