# UDB command-line simplification and safe migration

> Status: merged into `main` via PR #167 on 2026-11-13. This is **not** an
> installed or published Windows release. Check `udb version --json` before relying on new commands.
> This document does not authorize updating Windows, pairing devices, deploying
> Cloudflare Workers, merging into main, or changing any owner permission.

## Everyday usage

The supported, easy-to-remember surface is:

| Task | Command | Side effects |
| --- | --- | --- |
| Start | `udb` or `udb start` | Starts local agent; first attended start may offer pairing |
| Connect | `udb setup` | Attended owner pairing; never unattended |
| Stop | `udb stop` | Stops headless manager |
| Open manager | `udb gui` | Opens local GUI; no remote permission grant |
| Status | `udb status --json` | Read-only |
| Diagnose | `udb doctor --cloud --json` | Local and public unauthenticated Cloudflare checks |
| Watch calls | `udb live` or `udb live --gui` | Read-only activity metadata |
| Check update | `udb update --check` | Read-only release check |
| Show version | `udb --version` | Read-only |
| Help | `udb help` or `udb --help` | Read-only |
| More commands | `udb help advanced` | Read-only |
| Command options | `udb help status` or `udb status --help` | Read-only |

Running `udb update` **without** `--check` is not a read-only operation.
Check current release provenance and retain rollback/backup options first.

## Terminal-first ergonomics

- `udb help vi` shows a Vietnamese everyday command reference.
- A typo such as `udb statu` suggests `udb status` without loading
  configuration, starting the Agent, or exposing a long list of internal verbs.
- In an attended console, `udb update` requires typing `UPDATE`;
  `udb rollback` requires typing `ROLLBACK`. The confirmation occurs before
  launching the updater. Canceling leaves the installation unchanged.
- `udb update --check` is read-only and never prompts.
- `--yes` intentionally bypasses that human prompt; machine-readable
  `--json` and noninteractive scripts retain their existing behavior for
  backward compatibility. Security does **not** depend on this new prompt:
  independent owner, installer, release and process-ancestry checks remain.
- `udb allow-source`, `udb revoke-source`, and broad desktop permission
  grants continue to use their existing separate attended approval checks.

## Migration and compatibility

| Historic / advanced command | Preferred usage | Removal decision |
| --- | --- | --- |
| `udb logs` | `udb live` | Keep alias: scripts parse `--once --json` output |
| `udb setup --edit` | `udb setup` | Keep parser compatibility and warn; no old Tunnel wizard |
| `udb cloud-pair` | `udb setup` | Keep attended low-level pairing until migration accepted |
| `udb cloud-agent` | `udb start` | Keep direct Cloud Agent CLI used by integration and support |
| `udb runtime`, `udb manifest`, `udb build-info` | `udb help advanced` | Keep as diagnostics/build-provenance interfaces |
| `udb init` and `udb build` | Developer-only | Keep: source build and portable layout tests use them |
| `udb reconnect` | Recovery action | Keep; reconnects Cloud Agent without restarting worker |
| `udb rollback` | Recovery action | Never remove during migration |
| `udb revoke-access`, `udb allow-source`, `udb revoke-source` | Owner-only security actions | Never hide the ability to revoke or review a grant |
| `udb autostart`, `udb quickstart`, `udb test`, `udb mcp-config`, `udb tools`, `udb version` | Advanced diagnostics and automation | Keep executable and documented |

**Compatibility guarantee for this PR:** all pre-existing public subcommands and
flags remain parseable. No argument is silently remapped to a more privileged
action. The `--edit` flag is accepted but ignored as before, now with a warning
on stderr. Legacy log output and JSON stay unchanged.

Internal `_worker` roles, installer/bootstrap entry points, and source
compatibility adapters are **not** part of the user CLI cleanup. They require
separate callers/installer audits before any removal.

## Installer dependency — do not regress

The Windows installer historically identified Cloudflare-only releases by
matching the long `udb --help` subcommand list. The simplified help replaces
that list, so the installer must recognize **both**:

- old help containing `{...,live,...}`;
- new concise help containing an indented `udb live` entry.

`Test-CloudflareOnlyHelp` / `Test-CloudflareOnlyRelease` in `install.ps1`
implement this compatibility bridge without starting an agent. The synthetic
PowerShell regression `tests/test_installer_help_probe.py` guards both formats.

## Acceptance gates before publishing anything

1. Ruff check and format plus Linux/Windows Python 3.11/3.12 regression suites.
2. Windows frozen executable acceptance: version, help, MCP configuration,
   provider discovery, and offline/headless startup without owner grants.
3. Windows installer: fresh install, retained user state, upgrade, rollback,
   failure rollback and Start Menu shortcuts against disposable test homes.
4. Confirm current protected-main/release policy, exact build commit, and
   release signature limitations. A successful CI run does **not** authorize
   a merge or release on its own.
5. After explicit approval, publish a **new** signed or clearly identified
   unsigned release with validated checksums, then test on a disposable
   Windows profile before the owner's primary installation.
6. Verify actual installed version with `udb version --json`, status with
   `udb status --json`, and a separately granted read-only ChatGPT tool
   call. Cloudflare Worker and device permissions are independent of CLI help.

### Recovery if a subsequent authorized update fails

Stop issuing new tool requests, capture redacted diagnostics with
`udb status --json` and `udb live --once`, and inspect the installed build.
For a managed installation, run `udb rollback` **in an attended local
terminal outside UDB's own tool jobs**, after checking the previous managed
release is available. Rollback restores the previous executable, **not**
owner state snapshots; maintain separate backups of owner data. A portable
build requires an independently retained previous ZIP.

Do **not** delete compatibility code or owner state simply because
searches found no current usage. A subsequent major-version removal would
require explicit deprecation notice, installer + script inventory, migration
tests for old profiles, and an approved recovery plan.
