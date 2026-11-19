# Owner maintenance checklist

- [ ] Enable a ruleset or branch protection on `main`. Require pull requests and
      required checks for the latest exact HEAD, block force-pushes and branch
      deletion, and require at least one review where the repository supports
      it. Verify stale checks cannot qualify an updated PR.
- [ ] After enforcement is active, review removing PR #218's temporary
      unprotected manual-release exception. Preserve the exact-revision CI
      and owner publication checks when retiring the exception.
- [ ] Review the Cloudflare Worker currently named `staging`. Decide whether
      the live gateway connected to a real Windows machine should be renamed
      or separated from a test-only gateway. Verify bindings and device access
      before changing either environment.

These steps require the repository or Cloudflare owner's decision and access.

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
