# Compact tool families and compatibility

The reviewed source groups the previous 59 public interfaces into **40 public
tools**, retaining **all 67 native implementations** and their old callable
names. Check `udb tools` for the catalog of an installed build. Source changes
do not replace the immutable v0.12.0 release, upgrade Windows or deploy a Worker.

| Public family | Actions | Original operations retained |
| --- | --- | --- |
| `terminal` | `start`, `list`, `read`, `interact`, `stop` | Five `terminal_*` interfaces; send/wait flags still resolve to their native aliases |
| `sandbox_desktop` | `status`, `screenshot`, `input`, `snapshot`, `wait_for`, `element`, `stop`, `app`, `batch` | Nine `desktop_*` operations inside the approved guest |
| `search` | `start`, `read`, `stop` | Background search worker operations |
| `system_process` | `list`, `stop` | Process observations and guarded termination by observation ID |
| `project_files` | `list`, `stat`, `read`, `read_lines` | Four read-only operations in the configured Companion project |
| `host_browser` | Existing actions plus `screenshot` | Owned headless browser actions and the original tab screenshot operation |

## Calling conventions

New families use `action` and an action-specific `params` object. The nested
object preserves the original argument names and avoids collisions between the
outer action and a guest input action:

```json
{"name":"terminal","arguments":{"action":"read","params":{"session_id":"owned","offset":0}}}
```

```json
{"name":"sandbox_desktop","arguments":{"action":"input","params":{"session_id":"guest","action":"click","x":100,"y":100}}}
```

Each schema has separate branches for action-specific required fields and
rejects unrelated fields. `host_browser` keeps its existing flat signature:

```json
{"name":"host_browser","arguments":{"action":"screenshot","session_id":"owned","tab_id":"tab","cached":false}}
```

Calls still enforce the original session/project scope, observed process IDs,
resource admission, local pause and owner permissions. A family never retries a
call, replays input, approves a request or creates a grant. The host desktop,
Sandbox guest, registered source projects and configured Companion project
remain distinct permission scopes.

## Cloudflare migration and partial grants

Keep the existing per-device/per-subject grant entries using the **original
operation names**. For example, a grant for `terminal_read` exposes only
`terminal(action=read)`; it does not permit start or interact. A `host_browser`
grant does not permit screenshot without the separate `host_screenshot` grant.
Family names are not blanket grant shortcuts.

Discovery narrows the action branches to the permitted subset. Execution
independently resolves and checks that exact original operation before one
forward to Windows. The gateway forwards original names, so updated gateway
code can accept family calls while the Windows EXE still advertises the older
59-tool catalog. Existing callers can continue using their old names. Upgrade
the reviewed gateway before requiring new remote family names; an old gateway
will reject them. Reverting either side retains the original callable routes.

## Technical debt addressed

- `src/udb/tool_families.json` is the shared action/grant mapping for Python and
  Cloudflare; a cross-language parity test checks their resulting schemas.
- Family translation is separate from execution. Python consolidation rejects
  members routed to different permission backends.
- Packaging checks compare real discovery/inventory results rather than a
  hard-coded historical count. The startup benchmark accepts valid older and
  newer inventories without weakening its ungranted-owner checks.
- The shared JSON is explicitly bundled in both frozen layouts and checked in
  the wheel. Source discovery alone cannot prove frozen resource availability.
- Tests cover partial grants, revocation, original aliases, malformed action
  wrappers, independent browser screenshot grants and old/new Windows catalogs.

The remaining legacy connection/release migration and branch-protection work
are tracked in [current status](current-version.md). This change does not claim
those separate tasks are complete. Before rollout, validate the reviewed Worker
bundle and Windows artifact; preserve grants and rollback options, and verify a
permitted call through the actual installed integration.
