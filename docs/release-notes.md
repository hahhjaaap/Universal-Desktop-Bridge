# UDB 0.14.0 Windows release notes

Changes from v0.13.0 in the integrated source for this release.

- **Windows background access.** The `udb background` CLI lets the owner enable, inspect and revoke access for UDB-owned browser and workspace sessions. Reauthorization and revocation are local owner operations. Existing computer-access and background grants are separate. (#263)
- **Browser and desktop operations.** Faster tab startup and bounded DOM reads, Windows notification-based host mailbox wakes, and fewer RPCs for guarded browser actions. Guarded desktop batches can verify the identity of observed windows and their visual frames before sending input. (#260, #261, #242, #249, #230, #229, #232)
- **MCP and reliability.** Structured tool result contracts, sanitized backend errors, cleaner frozen stdio proxy shutdown, and better diagnostics for expiring computer-access grants. Opt-in shared status proxies and Cloud RPC worker limits are available for staging characterization. (#240, #250, #259, #236, #257, #258)
- **Security.** Browser URL validation, stricter Access identity and tool-grant handling, and additional approval and backup checks. The Windows archive carries a SHA-256 file inventory. (#224, #252, #234, #237)

- **Opt-in FastPath DOM postconditions.** Owned-browser FastPath can advance after each supported click when the expected visible text appears in the same document. The sequence stops on uncertain outcomes and uses the existing no-replay receipt. (#262)

The FastPath benchmark measures a warm Windows host and Chrome. Full-route ChatGPT → Cloudflare → Windows acceptance is pending. The staging fixture and scorer are documented in [FastPath end-to-end acceptance](fastpath-e2e-acceptance.md). (#265)

Optional prewarm, proxy reuse, RPC worker limits, and the Windows UIA snapshot cache are experimental.

## Install, update and rollback

Windows x64 builds include the Python runtime. Verify the published release assets before running the installer. Use an attended Windows terminal outside the active UDB remote-control session.

```powershell
udb update --check
udb update
udb --version
udb doctor --json
udb status --json
```

Confirm the intended device still appears in ChatGPT and validate a permitted read-only tool call. Keep the previous managed installation available for `udb rollback`. Managed updates use the existing data home. Owner grants still apply and time-limited grants can expire during an update.

GitHub build provenance and SHA-256 verification cover the ZIP, installer script and checksum file via the release workflow. The Windows executable is unsigned. See [release verification](release-security.md) for the verification policy and [v0.13.0 on GitHub](https://github.com/hahhjaaap/Universal-Desktop-Bridge/releases/tag/v0.13.0) for the previous published release.
