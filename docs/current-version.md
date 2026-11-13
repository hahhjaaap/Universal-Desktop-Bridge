# UDB 0.12.0 — current version and documentation status

**Baseline verified on 2026-11-13.** `src/udb/_version.py` declares
**0.12.0**. The Windows **v0.12.0** release was published on
**2026-11-11**. Later `main` commits keep the same semantic version but do
not retroactively change that published ZIP or any installed Windows EXE.

| Surface | Verify with | Meaning |
| --- | --- | --- |
| GitHub source | `git rev-parse HEAD`; `src/udb/_version.py` | Source revision and declared version |
| Windows installation | `udb --version`; `udb version --json` | Installed executable and build identity |
| Local Cloud Agent | `udb status --json`; `udb doctor --cloud --json` | Local process/config diagnostics, not remote authorization |
| Deployed Cloudflare Worker | Independent Worker/Access review | Actual remote revision, credentials and grants |
| ChatGPT integration | Owner sign-in and explicit granted read-only tool call | Actual end-to-end identity/device/tool path |

## Connection model

Use the attended `udb setup` on Windows and obtain the device-specific HTTPS
MCP URL from `udb mcp-config`. UDB 0.12 uses Cloudflare; public OpenAI Tunnel
and public local stdio MCP registration are not supported v0.12 user routes.
Worker deployment, OAuth, subject/device grants and Windows permissions are
separate controls and must not be inferred from green local process status.

## Source cleanup versus released installations

- PR #161 removed the unused Tkinter Tunnel UI and admin enrollment script,
  with their obsolete tests and helper license manifest. Compatibility
  interfaces still referenced by runtime/tests were intentionally retained.
- Subsequent source cleanup retires the optional **UDB Aura Chrome extension**,
  its launcher and ZIP resources. The visible-tab action uses an existing
  owner-controlled Chrome window without a browser extension; the UDB-owned
  browser and owner-granted virtual pointer are separate features.
- Git cleanup cannot uninstall a Chrome extension already loaded in the
  owner's browser. Remove a previously installed Aura manually at
  `chrome://extensions` if needed; do not change their Chrome profile
  remotely.
- The released v0.12.0 ZIP is immutable. A merged source PR is not proof of
  any new signed/released installer or of a Windows upgrade.

## Which documentation to use

For operational steps, start with [README](../README.md),
[owner pairing](pairing-checklist-vi.md), [GUI](gui-user-guide.md),
[release notes](release-notes.md), [Cloudflare staging operations](../cloudflare/STAGING-OPERATIONS.md)
and [security](../SECURITY.md). Historical prototypes, proposals, audit logs
and benchmark results are not current setup or deployment procedures.
Older exact tool counts or CI results must not be represented as current.

**Security:** UDB v0.12.0 Windows binaries are not Authenticode-signed.
See [release security](release-security.md). Neither documentation changes
nor a passing CI gate authorize Cloudflare deployment, secret/OAuth updates,
Windows grants or installer execution on an owner's PC.
