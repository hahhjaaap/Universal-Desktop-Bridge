# UDB 0.13.0 — Windows release candidate (2026-11-17)

> These notes describe the proposed **v0.13.0** Windows build from GitHub `main` after commit `d17f4f931663fd38aa9a4cbb05e1902103a32fa0`. The version is a **candidate until CI, the release gate, publication and installation verification pass**. The already published v0.12.0 artifacts are immutable.

## Changes since v0.12.0

- **ChatGPT and Cloudflare connection:** hardened account/device tool routing, fleet support work, owner-scoped tool catalogs, and safer handling of unexpectedly failed proxy requests. These source changes do **not** deploy Cloudflare Worker, grant account/device access or change OAuth settings.
- **Computer and browser workflows:** one-call guarded browser FastPath foundation (steps 11–20) and an **opt-in** persistent STA PowerShell UI Automation worker (steps 21–30). These paths remain under their explicit local controls; measured rejected-HWND process/IPC improvements are not claims about complete ChatGPT workflows.
- **Safety and regression work:** stricter Windows protected-path checks (including 8.3 aliases), backend outcome validation, no automatic replay of uncertain writes, plus Windows/Linux CI and Windows standalone installer/rollback tests.
- **Maintenance:** simplified current source and packaging paths. Existing local user data, device identity, pairings and approval settings should be preserved through managed update.

## Not included

- Draft PR #215 (computer grant expiry) is not merged; upgrading does not intentionally expire existing grants through that proposed change.
- Draft PR #216 (experimental UIA CacheRequest snapshot) is not merged; this release does not enable the unverified cache feature.

## Install and rollback

Publish only after the **exact v0.13.0 main commit** passes required checks and the release safety gate, including protected `main`. Once the genuine GitHub release exists, use the published HTTPS installer from `https://github.com/hahhjaaap/Universal-Desktop-Bridge/releases/tag/v0.13.0`. Run the managed installer **outside any active UDB remote-control job**; retain the previous working installation until the new Cloud Agent and ChatGPT tool catalog are verified.

On an attended Windows terminal, after publication:

```powershell
udb update --check
udb update
udb --version
udb doctor --json
udb status --json
```

Use `udb rollback` if the managed update fails. Do not delete the prior executable or owner state before end-to-end validation.

## Security and release status

The Windows ZIP and executable are built and checked by CI. SHA-256 integrity checks do **not** establish publisher authentication; this candidate is **not Authenticode-signed**. The public release workflow intentionally blocks publication when `main` is not protected. A successful candidate build is not itself a published stable release or an installed upgrade.
