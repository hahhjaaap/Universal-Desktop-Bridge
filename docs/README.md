# UDB documentation index — source 0.12.0

> **Reviewed 2026-11-14:** This index organizes the current source docs.
> The published v0.12.0 Windows installer, source commits and live Cloudflare
> Worker are not automatically synchronized. See [version/status](current-version.md).

## Setup and opt-in multi-device candidate

- [Automatic Windows setup and recovery](automatic-setup.md) — `udb setup`,
  owner approval, Credential Manager recovery, autostart and authenticated MCP proof.
- [Account Fleet MCP](account-fleet-mcp.md) — opt-in shared `/v1/account/mcp`
  endpoint, explicit per-call `device_id`, catalog and rollout gates. Not deployed.
- [Pairing checklist (Vietnamese)](pairing-checklist-vi.md) — owner and operator
  steps, exact endpoint selection, permission boundaries and rollback.
- [Legacy private enrollment command](private-device-enrollment-vi.md) —
  compatibility-only `udb connect --enroll` procedure.

## Start here (supported UDB 0.12.0 user procedures)

- [Version and support matrix](current-version.md) — source versus published EXE,
  open migration/security work and release gating
- [Windows Cloudflare quickstart (Vietnamese)](standalone-quickstart-vi.md)
- [Device pairing and ChatGPT verification](pairing-checklist-vi.md)
- [GUI user guide](gui-user-guide.md) and [compact controls](compact-controls.md)
- [Remote troubleshooting](remote-device-troubleshooting.md)
- [Windows control tools](windows-control-tools.md), [Windows workflows](windows-workflows.md)
- [Accounting XLSX review](accounting-worktools.md), [build identity](build-identity.md)
- [Security policy](../SECURITY.md) and [published v0.12 release notes](release-notes.md)

## Current maintenance boundaries

- [Branch protection / release safety issue #147](https://github.com/hahhjaaap/Universal-Desktop-Bridge/issues/147):
  release publication fails closed, but GitHub branch rules still require
  administrator enforcement.
- [Tunnel migration / rollback issue #162](https://github.com/hahhjaaap/Universal-Desktop-Bridge/issues/162):
  public Tunnel onboarding is retired; referenced internal compatibility paths
  and previously installed Windows releases have not been bulk-deleted.
- Developer CI for Windows runs `tools/run_windows_pytest.py` to clean up
  test-only Qt resources without overriding failure exit codes.
- [GitHub merged-branch cleanup](../.github/workflows/prune-merged-branches.yml)
  keeps `main`, backup/release/protected refs and active PR branches untouched.
  After review and merge, use **Actions → Prune merged feature branches safely
  → Run workflow** with `apply=false` first to preview old merged refs. To
  actually prune only verified unchanged heads, set `apply=true` and enter
  `PRUNE-MERGED-BRANCHES`. Future merged PR heads are checked one at a time
  for safe automatic deletion. This does **not** rewrite commits/tags, erase
  published releases or purge GitHub's historical PR records.

## Controlled staging and security review (not production enablement)

- [Cloudflare staging operations](../cloudflare/STAGING-OPERATIONS.md)
- [Project-read acceptance](cloudflare-project-read-acceptance.md)
- [Access Managed OAuth](cloudflare-access-managed-oauth.md)
- [Device isolation](owner-device-isolation.md)
- [Release verification and signing](release-security.md)
- [Staging fixture](staging-fixture.md), [P0-B evidence](p0b-staging-acceptance-evidence.md)

## Historical research / dated engineering evidence (not current setup)

The remaining historical records support regression analysis and threat
model review. They do **not** supersede the current Cloudflare pairing flow:
[earlier Cloudflare relay prototype](cloudflare-relay-prototype.md),
[enterprise GUI design roadmap](gui-enterprise-roadmap.md),
[old public-release proposal](public-release-plan.md),
[staging migration design](cloudflare-staging-deployment.md),
[current tool families and migration](tool-families.md),
[simulation evidence](simulation-report.md) and
[dated performance benchmarks](performance.md).

Three **unreferenced historical-only** Markdown pages were pruned from the
active checkout (not from Git history): the discontinued Tailscale Multi-PC
experiment, the obsolete 59-tool catalog and the 2026-11-09 audit snapshot.
For investigation, their immutable versions remain accessible in the
[2026-11-14 pre-cleanup source tree](https://github.com/hahhjaaap/Universal-Desktop-Bridge/tree/9b06d611f62a4c71eb190c872c52d0b3653590bc/docs).
Cleanup does **not** remove release tags, security audits embedded in
commits, migration checkpoints, or user rollback data.

UDB Aura Chrome extension and its installation instructions have been retired
from source. Browser automation uses an owner-scoped private browser; opening
an existing Chrome tab uses a validated URL and Windows UIA observation only.
A previously installed Chrome extension must be removed manually by its owner.
