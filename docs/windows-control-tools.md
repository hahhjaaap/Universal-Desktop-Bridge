# Windows control tools

> **UDB 0.12.0 documentation review (2026-11-13):** Current source targets UDB 0.12.0; installed Windows releases and deployed Cloudflare services must be verified independently. See [version/status](current-version.md).

The public catalog is generated from registered schemas and handlers; run
`udb tools` to obtain the actual count for your installed build. Two
Windows interfaces are consolidated:

| Public entry point | Actions | Legacy interface retained |
| --- | --- | --- |
| `computer_desktop` | Existing desktop/UIA actions plus clipboard_get/clipboard_set/apps/launch_app/notify | `computer_utilities` |
| `computer_process` | start/list/read/stop | `computer_execute` |

Existing names stay callable for clients with cached tool lists. Translation
preserves arguments, executes once and uses the original backend and owner grant.
Utility calls cannot also include a window target. Process start cannot include
a previous job ID or output offset. The legacy core-only API retains its original
names; the consolidated wrappers belong to the unified catalog.

Interactive project terminals, arbitrary-PID process administration, the private
browser and approved Sandbox desktop remain distinct scopes. Combining their
names would obscure ownership, permissions or input semantics.

## Open ChatGPT on the owner's Windows desktop

`open_chatgpt()` is a **new explicit MCP tool** for one task only: request
`https://chatgpt.com/` in a visible browser on the **selected device**.
It needs the owner's existing `udb --access computer` grant, an unlocked
interactive desktop, sufficient host capacity and the same user-input pause
checks as `computer_desktop`. The URL is constant; the tool accepts **no
credentials, URL, prompt, participant name or profile**.

If Google Chrome already has a visible running window, UDB reuses its existing
`open_chrome_tab` path. If Chrome has no open window, UDB asks Windows once to
launch the default browser URL handler. It does **not** create a private CDP
session, attach to another tab or examine login state.

The result reports `launch_mode=existing_chrome_tab|default_browser`,
`requested=true` and separate fields for the evidence actually observed.
A successful request is **not proof** that ChatGPT finished loading or the
user is logged in. Do not automatically replay an uncertain request;
inspect the desktop first. If user input, a locked screen, a revoked grant
or a paused desktop blocks the action, UDB refuses rather than bypassing it.
This operation does not post messages, run an AI model, or wake other chats.

Multi-machine gateways must pass a verified `device_id` and explicitly
grant the new tool in Cloudflare's owner tool allowlist. Source updates do not
install a new Windows binary or deploy the Cloudflare Worker automatically.

## ChatGPT roundtrip in a single UDB call (experimental)

`computer_desktop(action="chatgpt_roundtrip")` combines a verified send
with a **local** UI Automation reply observer, avoiding another remote MCP
call every time ChatGPT's answer changes. It is designed for an **already
open, blank Vietnamese ChatGPT conversation** on a previously observed
Chrome window. It does not open the site, authenticate an account, create a
new chat, or wake an inactive second ChatGPT instance.

```json
{
  "action": "chatgpt_roundtrip",
  "text": "Hello",
  "wait_ms": 6000
}
```

Implementation detail: the optimized path uses a targeted UI Automation
**prepare** (verify exact page, blank editor and focus) and **commit**
(verify exact typed text and invoke one Send button) around UDB's guarded
SendInput. It avoids the generic full UI snapshot and repeated UIA
read/focus/invoke processes. It still checks the same current-user access,
desktop readiness and foreground window. These optimizations affect UDB
overhead, not ChatGPT's reply-generation time. The timing report now separates
first visible reply text from full response completion; only the latter sets
`status=complete`.

For lowest remote latency, omit `window_id`: UDB locates a **single
currently foreground** window whose title is exactly `ChatGPT - Google
Chrome`, verifies its process is genuine Chrome, and binds that local
observation to this one request. If Chrome is in the background, the window
is ambiguous, or the binary cannot be verified, UDB refuses without moving
focus or submitting. A fresh `window_id` from `computer_desktop(list)` is
still supported for explicit targeting. Do not use a different URL or
browser title as a fallback.

The operation:
1. Verifies that UI Automation exposes an untruncated `ChatGPT`
   document and exactly one `Hỏi ChatGPT` editor, with no prior assistant
   response in the observed view. If it cannot verify a blank conversation,
   it refuses before modifying the page.
2. Uses the existing owner-authorized `verified_submit` path. The
   editor must be empty; typed text must match the requested text exactly
   before the uniquely named `Gửi` button is invoked **once**.
3. Polls the same window **locally** for the newly displayed response and
   completion status, for `wait_ms=500..10000`. This makes one remote tool
   request rather than a separate Cloudflare relay request for each poll.
4. Returns a best-effort visible reply (currently a single UIA text block),
   `reply_verified`, `status=complete|reply_timeout`, elapsed milliseconds
   for local submission/observer and `replay_safe=false`.

This is a UI automation experiment, not a supported ChatGPT-to-ChatGPT
agent service. It depends on the current Chrome accessibility tree,
Vietnamese labels, an unlocked interactive desktop, the existing owner's
`udb --access computer` grant, and the local user-input pause. Other
languages, UI changes, very long/structured replies and browser state
changes may cause a refusal or timeout. A timeout **after** invoking
`Gửi` does not mean the text was never sent; never automatically retry it.
Do not interpret UIA-visible text as verified account identity.

**Latency SLO (goal, not a promise):** 5–6 seconds measured by the
requesting client from tool start to usable reply on an already prepared
ChatGPT tab. The actual completion time includes Cloudflare/MCP transport
and ChatGPT generation; local `timings_ms` exclude that transport. Compare
median/p95 over repeated authorized tests. For a new tab or cold page,
measure and report initialization separately.

## Fast verified desktop submission

Use `computer_desktop(action="verified_submit")` when a visible owner-controlled
Windows application has one unique UI Automation `Edit` control and one unique
`Button` with a known exact label. It combines editor inspection, focus,
typing, exact readback and one submit invocation into **one MCP call**.
This avoids several remote round trips, but does not bypass the original
local computer grant, desktop user-activity checks or UIA protections.

Example for a ChatGPT page already open in a Chrome window (Vietnamese UI):

```json
{
  "action": "verified_submit",
  "window_id": "freshly-observed-window-id",
  "name": "Hỏi ChatGPT",
  "submit_name": "Gửi",
  "text": "Hello"
}
```

Call `computer_desktop(action="list")` first and use the returned fresh
`window_id`; verify the destination and correct account in the visible
window before submitting. If Chrome is not on ChatGPT, open it via the
separate approved `open_chrome_tab` action. Exact UIA names vary by
app, locale and version. The new action refuses to overwrite a draft:
the existing editor must be empty (or expose its exact UIA label as the
placeholder). If the readback differs even by one character, it does not
press the button. A failed/uncertain action is **not replay-safe**;
inspect the window rather than automatically retrying.

Successful return means the exact input text was confirmed and the
uniquely named button was invoked. It does **not** verify server-side
delivery, login or model response. Observe those separately when needed.
This is **not** headless DOM control, a second ChatGPT agent or permission
to read/send arbitrary private chats. A human can interrupt; local pause
or physical-input handoff always remains authoritative.

## Native UI Automation

List windows, retain a fresh `window_id`, then inspect `snapshot`. Snapshot reports
supported UIA patterns, toggle/selection/expansion state and readonly flags.
Listing omits DWM-cloaked shell windows and reports `minimized` and `class_name`,
so hidden UWP content hosts are not mistaken for the visible application frame.
Snapshot retries a root-only Control View using Raw View under the same verified
window; `children_exposed=false` means the provider still exposes no child controls.
Use an exact `automation_id` or `name`; add a supported `control_type` to narrow
the match. Both `Edit` and the observed `ControlType.Edit` notation work.

| Action | Parameters and result |
| --- | --- |
| `read_text` | `limit=1..5000` UTF-16 units; TextPattern/ValuePattern only. Never returns half a surrogate pair; `truncated` indicates more text. Flagged password controls are refused. |
| `set_checked` | Explicit `checked=true/false`; observes first, toggles at most once, then checks the result. |
| `select` | Select a SelectionItem directly, or provide `text` as an exact item name inside the uniquely located container. Ambiguous/missing/disabled items fail. |
| `expand` / `collapse` | ExpandCollapsePattern; already matching state avoids another change. |
| `scroll_into_view` | ScrollItemPattern; reports the observed offscreen state after the request. |
| `close_window` | One ordinary WM_CLOSE request; observes for at most one second. `closed_observed=false` may mean a save prompt is open. No force termination or automatic save/discard. |

Examples (replace IDs with observations):

```json
{"action":"set_checked","window_id":"observed","automation_id":"Choice","checked":true}
{"action":"expand","window_id":"observed","automation_id":"Country"}
{"action":"select","window_id":"observed","automation_id":"Country","text":"Vietnam"}
{"action":"read_text","window_id":"observed","automation_id":"Editor","limit":5000}
{"action":"close_window","window_id":"observed"}
```

Pattern actions do not force foreground focus or fall back to physical input.
Applications may activate windows or open dialogs in response to their own UIA
handlers. Mutations retain cooperative input yielding, local pause and grant
checks; inspection remains available under the existing light-memory budget.
Unsupported patterns, changed controls and uncertain outcomes require inspection,
not automatic replay. The short postcondition polls repeat observations only.

## Window screenshots

The default `screenshot` captures the **visible screen region** of the selected
window, not an isolated compositor frame. It requires a restored foreground
window and rejects overlapping windows, including untitled overlays. It neither
focuses the target nor falls back to a display capture. Visibility and identity
are checked again after capture; a changed target causes the image to be discarded.
The result reports `source=visible_window_region`, `occlusion_checked=true` and
`window_content_isolated=false`. These are best-effort observations, not exclusive
desktop ownership. Explicit `display_index` or `region` captures retain screen scope.

## Utilities and jobs

Use `computer_desktop(action="apps")`, then `launch_app` with an exact observed
`name` or app ID in `name`. Clipboard writes require the `expected_version` from
an explicitly requested `clipboard_get`; conflicts remain errors.

```json
{"action":"start","program":"C:\\Windows\\System32\\whoami.exe","arguments":[],"cwd":"C:\\work","timeout_seconds":30}
{"action":"read","job_id":"returned-job-id","offset":0}
{"action":"stop","job_id":"returned-job-id"}
```

These are `computer_process` calls, with the same current-user, unsandboxed job
limits as before. Stop still permits cleanup after access revocation. No tool
grants access, resumes a local pause or automatically repeats a command.

## Verification scope

Routing and policy tests use fake backends and disposable state. The native
Windows test uses one Job-owned WPF fixture for selection, expansion, checkbox
readback, text limits, password refusal and graceful close. It observes no other
application's contents, creates no computer-access grant and does not move the
physical mouse. Personal applications and protected/elevated desktop surfaces
require separate attended validation; no elevation bypass is provided.
