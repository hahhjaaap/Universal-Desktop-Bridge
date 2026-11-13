# Compact local controls

> **UDB 0.12.0 docs review (2026-11-13):** **Current UDB 0.12.0 source guidance.** Verify the installed executable, Cloudflare Worker, OAuth and owner grants separately; source changes do not update them. See [version/status](current-version.md).

Launch with `udb gui`. When Windows provides a system tray, the GUI opens a small
control panel and registers a UDB tray icon. Click that icon to reopen controls;
its menu also offers pause, background-session closure and **Thoát UDB**.

The full manager remains available from **Mở UDB đầy đủ** for projects,
local permissions, reviews and configuration. Its **Thu gọn** button returns
to the small panel. If a system tray is unavailable, the full manager opens
first; closing the compact panel returns to it.

**Source GUI on UDB v0.12.x (verify your installed `udb --version`):** The full manager
has a collapsible **200 px → 72 px** left sidebar with stable accessible route
names and tooltips. Under **Kết nối → Giao diện ứng dụng**, choose
**Theo hệ thống Windows**, **Sáng**, or **Tối**. The choice is a local
appearance preference; no owner permissions or Cloudflare pairing credentials are changed.
The Windows system color scheme is checked at startup and when Qt reports
a color-scheme change; unsupported platforms retain startup detection. See the
[Desktop GUI guide](gui-user-guide.md) for details.

## What each action does

| Action | Scope |
| --- | --- |
| Kết nối / Ngắt kết nối | For a paired device, start/stop its Cloud Agent; for an unpaired device, open attended Cloudflare pairing. Does not grant Windows access or verify a ChatGPT tool call |
| Tạm dừng / Tiếp tục Windows | The local input-pause latch; grants remain unchanged |
| Tôi đăng nhập browser / Trả về cho AI | The existing UDB-owned browser handoff; disabled during unavailable capacity or another local operation |
| Đóng phiên nền | Disable new host sessions and close UDB browser/workspace sessions |
| Thoát UDB | Close the GUI-owned runtime and its resources; incomplete cleanup remains visible and can be retried |

Browser work and other background jobs may continue during Windows input pause.
Closing background sessions does not imply every terminal/Sandbox job was stopped.
The full manager retains their existing controls.

Closing windows in tray mode hides them. The compact panel explains this behavior
and how to exit. A failed or busy exit keeps the tray and controls reachable.
The UI does not silently discard an unfinished cleanup.

## Recent activity

The panel reads the existing local activity database in a background worker.
It correlates call/result records by tool and call ID, keeps at most 40 entries
and displays the latest eight. Parallel results do not hide another unanswered
call. Tool and action names are shown as literal text; tooltips escape markup.
Payloads, scripts, field values and credential contents are not displayed.

Connection readiness is separate from activity. A returned `RUNNING` result is
labelled **Đã giao tác vụ nền**, rather than claiming the task is finished or
still alive. An unanswered call older than a minute becomes **Chưa nhận được kết
quả**. This is recent tool-call history, not a percentage or the full ChatGPT task
plan. A failed log read is shown as unknown and does not block local pause.

## Runtime modes and checks

The windowless `udb start` workflow remains available without a GUI or tray.
The GUI and windowless manager share one runtime lease: a second runtime is not
started beside an existing one. If UDB is already running windowless, `udb gui`
explains that mode. To switch, explicitly stop it with `udb stop`, then run
`udb gui`; stopping closes its existing owned sessions. The GUI does not attach
to or silently restart a running windowless manager.

Qt tests use disposable owner state and cover pause failures, busy/failed exit,
tray fallback, concurrent activity, slow/failed log reads and literal metadata.
The GUI self-test exercises full pages and compact controls without granting
computer access. Windows CI also runs that self-test from the frozen executable
and uploads preview images. Tray registration is checked when the test desktop
provides a tray; manual review is still needed for the user's Explorer layout,
notification-area overflow and display scaling.

## Native Chrome tab identity

`computer_desktop(action="open_chrome_tab")` compares Windows UI Automation tab
runtime IDs before and after requesting a tab in existing Chrome. Only one
unambiguous new tab is registered; `native_tab_marker_verified` reports whether
registration succeeded. It does not inspect tab titles, URLs, page content or
browser profiles, and needs no extension or CDP attachment.

The compact mint AI badge appears on registered tabs in the foreground window.
The independent AI pointer appears only when exactly one tab is selected and
that tab is registered. It hides on ordinary tabs, other applications and
ambiguous split views. The overlay is click-through and does not activate a
window or move the system mouse. The normal Windows control tools remain
available regardless of overlay visibility.

At most eight runtime identities are retained locally. Restarting Chrome,
transferring a tab, unavailable UIA or unsupported tab layouts can prevent
identification; reopen the tab through UDB to register it again. The badge is an
OS overlay, not a favicon. Native CI tests use an isolated synthetic tab strip;
Chrome-version-specific appearance still needs review on the user's machine.
