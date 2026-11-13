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
