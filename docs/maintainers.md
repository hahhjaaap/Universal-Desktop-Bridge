# Owner maintenance checklist

- [ ] Verify the active `main` ruleset covers `refs/heads/main`, requires pull
      requests, blocks branch deletion and force-pushes, and applies to
      administrators. An empty bypass list applies the rules to all actors.
- [ ] Require the checks below from GitHub Actions for the latest reviewed PR
      head. Keep strict status checks enabled so the PR branch must be current
      with `main`. Require at least one independent review where collaboration
      permits, dismiss stale approval on a new commit, and verify a normal PR
      can merge after the expected checks and reviews pass.
- [ ] After enforcement is active, review removing PR #218's temporary
      unprotected manual-release exception. Preserve the exact-revision CI
      and owner publication checks when retiring the exception.
- [ ] Review the Cloudflare Worker currently named `staging`. Decide whether
      the live gateway connected to a real Windows machine should be renamed
      or separated from a test-only gateway. Verify bindings and device access
      before changing either environment.
- [ ] Arrange independent human review of WS12 and the WS14 threat models.
- [ ] Decide whether to archive the `udb/p0*` branches after comparing the exact
      tips with current `main`. See the [branch inventory](audits/stale-branches.md).
- [ ] Configure code signing for Windows distribution. See [release verification](release.md).
- [ ] Rotate any token previously exposed in logs and review its scope and use.

These steps require the repository or Cloudflare owner's decision and access.

## GitHub checks for `main`

Require these check names. Verify they report on the exact current PR head.

- `cloudflare-and-observer`
- `test (ubuntu-latest, 3.11)`
- `test (ubuntu-latest, 3.12)`
- `test (windows-latest, 3.11)`
- `test (windows-latest, 3.12)`
- `windows-exe`
- `analyze (javascript-typescript)`
- `analyze (python)`
- `audit`
- `review`

The WS10 PR initially reported 16 checks. The other six are listed here so the
owner can review them without creating an impossible requirement on docs-only
PRs. `relay` and the four `benchmark-contract` checks start only on matching
paths. Keep them conditional until their workflows report an explicit result on
every PR. `CodeQL` is the aggregate report for the two required `analyze` checks.

- `CodeQL`
- `relay`
- `benchmark-contract (ubuntu-latest, 3.11)`
- `benchmark-contract (ubuntu-latest, 3.12)`
- `benchmark-contract (windows-latest, 3.11)`
- `benchmark-contract (windows-latest, 3.12)`

[Observed check list for the initial WS10 head](https://github.com/hahhjaaap/Universal-Desktop-Bridge/commit/d727a15de26b68da2dea8bdec239efec103f81c4/checks)

## Merged head branches

The branch audit workflow reports candidates and uses a read-only token. GitHub's
**Automatically delete head branches** setting is an owner choice for future
merges. It removes the need for a workflow with ref-deletion access, but its
coverage follows GitHub's rules, without the audit's backup, release, and other
prefix exclusions. Verify protected branches and archive any tips that need to be
retained before enabling it. Use the inventory to decide the fate of old refs.

## Local history retention

Run `udb retention` to preview how many generated backups and core audit
events qualify for pruning. When recovery or audit history must be retained,
export or back it up independently before pruning. From your Windows terminal,
run `udb retention --apply`, review the counts, and type `PRUNE UDB HISTORY`
to apply. The command is opt-in each time and records the removed counts in the
core audit journal. It reports changed or locked candidates as skipped.

Pruning considers records more than 90 days old by the local wall clock. It
keeps at least the newest 20 eligible-format backups per directory and the
newest 1,000 audit events. A run can remove up to 200 backups and 2,000 events.
Backup scope is limited to recognized generated files in `state/backups` and
the `.udb-recovery` folders of configured or registered projects outside
protected roots. It preserves the directories, approval records, and grants.
Event pruning frees rows for SQLite to reuse.

The standard UDB terminal tools use redirected streams and cannot satisfy
the Windows console check. Processes with unrestricted access to the owner's
Windows account retain that account's filesystem and desktop authority.
