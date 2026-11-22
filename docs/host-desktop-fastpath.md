# Host Desktop FastPath — owner-controlled Windows workflow (experimental)

FastPath has two separate execution modes.

- Owned-browser FastPath: host_browser(action="fastpath") operates in UDB's
  separate browser profile using DOM selectors and durable one-shot receipts.
  It never attaches to the user's Chrome.
- Host Desktop FastPath: computer_desktop(action="fastpath") operates only on
  the existing locally owner-authorized Windows desktop, using the same bounded
  native engine as computer_desktop(action="batch"). It supports user-visible
  Chrome, Explorer, Excel and other native apps with UI Automation.

These modes do not share permissions, sessions, DOM state or identities.
Host Desktop FastPath runs only an explicit validated plan. It never treats
application text as new instructions or grants permission.

## Durable no-replay receipts

Host Desktop FastPath now **requires a stable request_id** supplied by the
caller, unique per intended workflow and scoped to the current locally issued
computer-access grant. The runner persists a payload-free `running` receipt
**before Windows input** and finalizes the receipt after the batch returns.

- Reissuing the **same request_id and same plan** returns receipt metadata
  (completed/failed/unknown), **never runs input a second time**.
- Reusing a request_id with a different plan is rejected.
- Concurrent callers with the same request ID cannot enter the input lane twice: the first caller creates the exclusive `running` receipt before dispatch; a concurrent duplicate only observes that receipt and is reported as uncertain until the first caller finalizes it.
- The receipt stores plan digests and bounded status only — never UI text,
  screenshots, typed content or URLs.
- A crash, lost reply or uncertain mutation leaves an outcome-unknown receipt
  until independently inspected. Do not invent a fresh ID to replay writes.
- A subprocess-crash regression now terminates immediately after the fixture enters its input callback, then starts a new process with the same request ID and proves the durable `running` receipt prevents a second dispatch.
- This protects against the dangerous replay case but is **not transaction
  rollback** and cannot itself determine whether an external app committed.
- Each grant has a bounded count of receipts; a new grant does not confer
  additional scope over that owner's Windows session.


## Changes

Host FastPath preserves the 1–12 step / 20-second desktop batch budget and
existing when, depends_on, verify, and window_ref rules. It adds:

1. Public computer_desktop(action="fastpath", steps=[...]) using existing
   owner-granted Windows desktop permissions.
2. A single open_chrome_tab step within FastPath only, to open a supplied
   public HTTP(S) URL in already-running personal Chrome; no CDP attachment.
3. Batch-only find_window and wait_window locators with either exact title
   or title_prefix (8–300 characters), PLUS the previously observed PID and
   native window class. wait_window polls read-only for at most 10 seconds.
4. window_ref may reference either locator; the returned window_id binds
   to the actual, complete observed title, PID and class.

A prefix alone is never enough to identify a target. Ambiguous matches,
changed PID/class/title, locked Windows, revoked grants, or user activity
must stop action before input.

## Example: Chrome and Excel in one remote call

First call computer_desktop(action="list") and use its actual PID, class and
title. The sample values below are placeholders, not real device identities.

~~~json
{
  "action": "fastpath",
  "request_id": "youtube-and-excel-unique-001",
  "steps": [
    {
      "action": "open_chrome_tab",
      "text": "https://www.youtube.com/",
      "verify": {"field": "requested", "equals": true}
    },
    {
      "action": "wait_window",
      "pid": 1234,
      "class_name": "Chrome_WidgetWin_1",
      "title_prefix": "YouTube -",
      "wait_ms": 5000,
      "verify": {"field": "found", "equals": true}
    },
    {
      "action": "focus",
      "window_ref": 1,
      "verify": {"field": "foreground", "equals": true}
    },
    {
      "action": "find_window",
      "pid": 5678,
      "class_name": "XLMAIN",
      "title": "Book1 - Excel",
      "verify": {"field": "found", "equals": true}
    },
    {
      "action": "read_text",
      "window_ref": 3,
      "name": "Status"
    }
  ]
}
~~~

This example intentionally performs no Excel edits. First inspect and
verify the unique UIA name/automation_id and desired result before a
mutating app step. Reobserve any window after its title changes.

## Semantic UIA selection (experimental)

For an **exact previously observed UIA container**, use a batch-only
`find_control` step. It requires:

- `name` or `automation_id`: exact identity of the *container*, not a
  free-form query against every application window.
- `text`: 4–160 character case-insensitive phrase that the target's
  accessible Name must contain.
- `control_type`: one of Hyperlink, Button, MenuItem or ListItem.
- `window_ref` or `window_id`: the already observed application frame.

The native UIA helper searches only descendants of that **unique**
container, excludes password/offscreen/disabled/non-invokable elements, and
returns the **topmost visible matching element**. It rejects excessive matches
or a tie in screen position. The next `invoke` step may supply
`element_ref` pointing to the earlier `find_control`; both steps must use
the exact **same observed window reference**. Invoke rechecks exact accessible
name, automation ID, role and current window before input. If the name is no
longer unique, the invoke fails without guessing.

A bounded example using the app and container identities obtained from a
fresh desktop listing and UIA snapshot:

~~~json
{
  "action": "fastpath",
  "request_id": "read-first-matching-link-001",
  "steps": [
    {"action": "find_window", "pid": 1234, "class_name": "Chrome_WidgetWin_1",
     "title": "nhạc hay - YouTube - Google Chrome"},
    {"action": "find_control", "window_ref": 0, "name": "Observed results container",
     "control_type": "Hyperlink", "text": "Nhạc",
     "verify": {"field": "found", "equals": true}},
    {"action": "invoke", "window_ref": 0, "element_ref": 1}
  ]
}
~~~

This is a **UI Automation** feature, not DOM/CDP attachment to personal
Chrome. Browser accessibility trees can omit or duplicate video titles;
therefore no universal guarantee of selecting YouTube's first organic result.
If the accessible container is missing or ambiguous, inspect it or use the
owned-browser DOM FastPath. Do not remove ad/Shorts filtering requirements
silently when deriving an app-specific workflow.

## Safety and limitations

- The owner must already have enabled computer access locally. The FastPath
  cannot elevate, authorize itself, disable emergency pause, or use UAC/
  secure desktops.
- The native batch execution is non-transactional, but the host FastPath
  endpoint now persists a per-grant, one-shot receipt before dispatch.
  On uncertain completion, inspect independently instead of issuing a new ID
  to re-run the input.
- open_chrome_tab success means a tab was requested, not that a page finished
  loading. Verify through wait_window and UIA observations.
- Before CDP mouse, keyboard, or wheel input, the owned browser activates the
  exact already-attached target inside its private headless profile. If target
  activation fails, input is not dispatched. This never activates or attaches
  to personal Chrome and does not move the operating-system cursor.
- Ranked UIA selection chooses the topmost eligible control inside a unique
  observed accessible container, and invoke still demands a unique exact
  control identity. It is not equivalent to arbitrary personal-Chrome DOM
  selection; inaccessible containers and ad/Shorts filtering are unsolved.
  This feature does not attach CDP or execute caller JavaScript there.
- No shell command, file writes, arbitrary process launch, cross-user session
  or implicit privilege escalation is added inside FastPath.
- Sending messages, deleting files, submitting tax forms, and posting
  accounting entries require explicit authorization for the effects,
  independently of the local computer grant.
- Maximum 12 steps / 20 seconds; split longer tasks at observed read-only
  checkpoints, never at uncertain mutations.

## Measurement

Track host-internal batch execution, MCP/Cloudflare round-trip wall time,
and verified end-to-end completion separately. Test multiple runs under
known machine load. Target p95 <= 6 seconds is a benchmark goal, not a
claim about this experimental feature.

## Native semantic UIA canary

Windows regression CI also starts a test-owned WinForms window with one exact
results container and two similarly named buttons. The native UIA helper must
select the topmost eligible result and invoke only that button. The test
performs 30 separate selection/invocation/readback cycles against the fixture,
then checks an overlapping-control case is rejected before any click. The
fixture is terminated in a `finally` block; no real user window or owner
grant is accessed.

This proves a bounded native UIA fixture path, not MISA readiness or an
end-to-end Cloudflare latency target.
