# UDB 0.13.0 — source candidate versus released Windows build

**As of 2026-11-17**, the canonical source version on the v0.13.0 release-candidate branch is `0.13.0`. The latest **published** Windows release verified on GitHub is still **v0.12.0 (2026-11-11)** until a genuine v0.13.0 GitHub Release is published. The installed `udb.exe`, source branch, CI artifacts, and deployed Cloudflare Worker are independent and can be at different revisions.

## Current source changes

The v0.13.0 candidate includes the changes already merged into `main` through PR #216:

- Cloudflare account/device routing and tool-catalog improvements; Windows, Linux and Cloudflare regression tests.
- Browser guarded FastPath foundation and the opt-in persistent Windows UI Automation worker.
- Windows protected-path, proxy outcome and uncertain-write hardening.
- **PR #215:** the DPAPI local computer-access grant expires after **8 hours** (maximum 24 hours). Legacy grants without expiration are rejected and must be reapproved through an **attended local** `udb --access computer`; remote tools cannot reauthorize them.
- **PR #216:** experimental snapshot property cache is merged but **disabled by default**. Real UIA-tree correctness and speedup testing remain open; no end-to-end 5–6 second guarantee.

Do not infer that a source merge enables owner grants, updates Cloudflare or installs a new Windows executable.

## Release gate and current blocker

`tools/release_gate.py` requires the **exact current `main` SHA**, a successful complete **push CI** run for that revision, and a previously unpublished version. The publication workflow is now **manual-only**: the owner must run `one-command-windows-release` on `main` and explicitly confirm publication without Branch Protection. Automatic publication remains disabled. The previous default protection guard is retained unless the manual-only confirmation and trusted GitHub Actions event/ref checks both succeed. This optional route does not add code signing or independent security review.

The PR's Windows EXE build and CI artifact can be used for **candidate acceptance**, but it is not a signed or official GitHub release. Current Windows builds are not Authenticode-signed; SHA-256 alone does not authenticate the publisher.

## Check the four independent surfaces

| Surface | Verify | Interpreting the result |
| --- | --- | --- |
| Source | `git rev-parse HEAD`, `src/udb/_version.py` | Selected code and declared version |
| Windows executable | `udb version --json`, `udb doctor --json` | Installed binary revision and local health |
| Cloudflare Worker | Independent Worker/Access deployment audit | Actual deployed relay and grants |
| ChatGPT connector | Live tool list and a permitted read-only call | End-to-end tool discovery and authorization |

## Update and rollback

Run `udb update --check` only after an approved v0.13.0 public release exists. The managed installer should retain the previous known-good image and the user state in `%LOCALAPPDATA%\\UniversalDesktopBridge`. Validate `udb --version`, `udb doctor --json`, and the ChatGPT tool catalog before removing older managed releases. Use `udb rollback` on failure. Do not stop or replace the active UDB executable from inside its own remote job, as this can sever the only management connection.

Use [v0.13.0 release notes](release-notes.md), [Windows release security](release-security.md), [pairing instructions](pairing-checklist-vi.md), and [repository README](../README.md) for operational details. Historical claims about v0.12.0 still refer only to that immutable published artifact.
