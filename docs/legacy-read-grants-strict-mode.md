# Optional strict validation of legacy read grants

> **UDB 0.12.0 docs review (2026-11-13):** **Opt-in/staging evidence.** Code, tests and staging results do not imply production access, current grants or end-to-end ChatGPT connectivity. See [version/status](current-version.md).

**Status:** Source-level staging migration feature; disabled by default.
This does not create users, enroll a Windows device or change any running
Cloudflare deployment, OAuth identity, local Windows owner permission or
remote tool surface.

## Problem and scope

The historical `UDB_DEVICE_GRANTS` parser silently discarded unrecognized
entries from a per-device/per-subject tool array and kept any recognized
read tools. It never enabled arbitrary owner/desktop tools, but a malformed
or partially migrated grant could be accepted unintentionally.

`UDB_STRICT_LEGACY_GRANTS="true"` makes the **entire matching subject grant**
invalid if its array is empty, contains a duplicate, contains an unknown tool,
contains a value other than a string, or exceeds the documented catalog size.
Only the six explicitly defined project-read tool names are accepted.

The flag is **opt-in** so a deployment with a partially invalid historical
grant is not unexpectedly disconnected by a source update. With the flag
unset or `"false"`, historical filtering remains for compatibility. If the
setting is present with any other value, the legacy grant lookup fails closed.

## Migration / staging procedure

1. Inspect the current private configuration **outside GitHub, CI logs or a
   ChatGPT prompt**. Do not paste real subject emails, device identifiers,
   tokens or entire grant JSON into an issue.
2. Normalize only the desired device/subject read arrays to unique, exact
   names from `bridge_status`, `list_projects`, `list_files`,
   `read_file`, `search_files`, `check_python_syntax`.
3. In a **separate staging** Worker, set
   `UDB_STRICT_LEGACY_GRANTS="true"` without modifying existing read
   grants, then test correctly permitted calls and unauthorized denials.
4. Check missing subject, wrong device, unknown tool, duplicate/invalid
   entry, revoke and reconnect against a disposable registered project.
   Capture only sanitized HTTP statuses and tool names.
5. For any failed legitimate call, repair the specific private grant rather
   than disabling other authorization checks. Do **not** automatically
   replay writes or desktop mutations.
6. Enable on production only after owner-reviewed staging evidence and a
   rollback plan. This is a configuration rollout, **not** a code-signing
   or multi-tenant enrollment solution.

## Precedence

An explicitly configured `UDB_TENANT_POLICY` always takes precedence and
never falls back to legacy `UDB_DEVICE_GRANTS`, regardless of this flag.
The optional separately gated owner-tool profile remains independent; strict
legacy read grants do not grant `computer_*` or approval capabilities.

## Local verification

```sh
node --test cloudflare/tests/strict-legacy-grants.test.js
node --test cloudflare/tests/*.test.js render/tests/*.test.mjs
```

These tests use synthetic identities/devices and a stub relay. A passing test
does not prove production Cloudflare Access configuration, live ChatGPT
authentication or local Windows file permissions. See
[owner/device isolation](owner-device-isolation.md) and
[project-read acceptance](cloudflare-project-read-acceptance.md).
