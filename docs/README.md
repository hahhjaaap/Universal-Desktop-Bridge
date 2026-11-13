# UDB documentation index — source 0.12.0

> **Reviewed 2026-11-13:** This index organizes the current source docs.
> The published v0.12.0 Windows installer (2026-11-11), source commits and
> live Cloudflare Worker are not automatically synchronized.
> See [version/status](current-version.md).

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

## Controlled staging and security review (not production enablement)

- [Cloudflare staging operations](../cloudflare/STAGING-OPERATIONS.md)
- [Project-read acceptance](cloudflare-project-read-acceptance.md)
- [Access Managed OAuth](cloudflare-access-managed-oauth.md)
- [Device isolation](owner-device-isolation.md)
- [Release verification and signing](release-security.md)
- [Staging fixture](staging-fixture.md), [P0-B evidence](p0b-staging-acceptance-evidence.md)

## Historical research / dated engineering evidence (not current setup)

The repository retains records useful for regression analysis and threat
model review. They do **not** supersede the current Cloudflare pairing flow:
[earlier Cloudflare relay prototype](cloudflare-relay-prototype.md),
[Tailscale Multi-PC experiment](multi-pc-tailscale.md),
[enterprise GUI design roadmap](gui-enterprise-roadmap.md),
[old public-release proposal](public-release-plan.md),
[staging migration design](cloudflare-staging-deployment.md),
[historical 59-tool catalog](cloudflare-unified-59.md),
[simulation evidence](simulation-report.md),
[dated performance benchmarks](performance.md) and
[2026-11-09 audit](audit-status-2026-11-09.md).

UDB Aura Chrome extension and its installation instructions have been retired
from source. Browser automation uses an owner-scoped private browser; opening
an existing Chrome tab uses a validated URL and Windows UIA observation only.
A previously installed Chrome extension must be removed manually by its owner.
