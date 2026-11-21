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

## Safety and limitations

- The owner must already have enabled computer access locally. The FastPath
  cannot elevate, authorize itself, disable emergency pause, or use UAC/
  secure desktops.
- Unlike the isolated browser FastPath, the current Windows FastPath is a
  desktop batch WITHOUT a persistent request receipt. Never retry an
  unknown/timed-out mutating plan; inspect first.
- open_chrome_tab success means a tab was requested, not that a page finished
  loading. Verify through wait_window and UIA observations.
- UIA invoke requires a uniquely identified control. Dynamically choosing
  the first YouTube result in personal Chrome by page DOM is not yet solved.
  This release does not attach CDP or execute caller JavaScript there.
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
