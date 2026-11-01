# UDB desktop GUI — appearance, navigation and security

Applies to the **source GUI on `main` after PRs #42 and #44**. The last
published stable Windows installer may still use an earlier interface: check
[`Releases`](https://github.com/hahhjaaap/Universal-Desktop-Bridge/releases).
This guide documents implemented behavior, not a promise of a full enterprise
redesign.

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

The selection is applied immediately to the running Qt application and saved
as an allow-listed `theme` preference in the owner's bounded `gui.json`
settings. The key is one of `system`, `light`, `dark`; invalid values
fall back to `system` rather than entering a Qt stylesheet. Existing
`motion` and `autoconnect` preferences remain. No credentials are stored
in `gui.json`.

**Limitation:** The app does not yet subscribe to every live Windows theme
change while it remains open. For the `system` option, reopen the app or
reselect the option after changing Windows' appearance if the UI does not
refresh automatically. System high-contrast mode and 200% DPI still need
separate real-device review.

## Activity filters, navigation and approval review

In **Tiến trình**, search by project, language, status or job ID.
Choose **Tất cả**, **Đang chạy**, **Cần chú ý** or **Đã xong**. Filters
read only bounded task metadata and never search script or log contents.
A failed/unknown task does not automatically become **Đã xong**. Changing
filters clears hidden stale task details; no job state changes.

Keyboard shortcuts in the full manager: `Ctrl+1` through `Ctrl+6`
navigate the six pages; `Ctrl+Shift+F` opens and focuses task search.
In **Kết nối**, **Sao chép lệnh kiểm tra** copies only `udb doctor --json`
to the local clipboard; it does not execute a command or share diagnostics.

Owner approval dialogs display an operation-specific impact notice:
real file modification, host-side media download, Windows Sandbox desktop,
or Sandbox script execution. Existing full diff/script tabs, request hash,
expiry, explicit review checkbox and secondary local confirmation remain
mandatory. Untrusted request/file strings are rendered as plain text.

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

## Overview: three separate connection checks

The top of **Dự án** displays three compact indicators:

| Indicator | What it verifies | What it does not verify |
| --- | --- | --- |
| **Agent** | Host worker reported a local readiness heartbeat | Authorized computer access or ChatGPT RPC |
| **Tunnel** | Local tunnel health/transport is running and ready | Whether ChatGPT discovered any tools |
| **ChatGPT** | Always **Chưa xác minh** (unverified) in this GUI release | No GUI-side network test is invented |

On a failed status refresh, the corresponding Agent or Tunnel indicator falls
back to **Chưa xác định** rather than displaying its previous green value.
Status is read-only; this feature sends no remote probe, stores no credential
and grants no access. To verify end-to-end ChatGPT connectivity, run an actual
**read-only** UDB tool in ChatGPT.

## Connection status is not authorization

- **Local agent:** the worker is reachable on this PC.
- **Tunnel ready:** this PC's outbound tunnel is ready; this does *not* prove a
  ChatGPT workspace can discover and call UDB tools.
- **ChatGPT invocation:** confirm in ChatGPT with a *read-only* status tool.
- **Permission grant:** separately authorized by the owner on the Windows
  machine; not inferred from any connected indicator.

The current source does **not** implement production one-plugin Multi-PC
selection. Do not infer another PC from a green connection label; distinguish
separate MCP connections and tunnel IDs. See
[remote-device troubleshooting](remote-device-troubleshooting.md).

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
  the earlier v0.10.0 standalone ZIP was not code-signed.

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
