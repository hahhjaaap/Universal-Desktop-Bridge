# Repository security enforcement

This document separates **repository-controlled review routing** from
**GitHub administrator settings**. A CODEOWNERS file does not itself block
merges. The default-branch ruleset must explicitly require pull requests,
required status checks, and code-owner review.

## Review routing

[.github/CODEOWNERS](../.github/CODEOWNERS) routes changes to workflow,
release, installer, computer-access, desktop-receipt, host-service, and
Cloudflare controls to the verified repository owner account
`@hahhjaaap`.

This is a routing baseline, not independent approval. A pull-request author
cannot approve their own pull request. Before requiring one approval for
owner-authored changes, add a second authorized maintainer to the relevant
CODEOWNERS patterns and verify their access. Do not add an unverified account
or team as an approver.

## Required default-branch ruleset

In **Settings → Rules → Rulesets**, configure the ruleset targeting
`refs/heads/main`:

1. Require a pull request before merging.
2. Require at least one approving review from someone other than the author.
3. Require review from Code Owners for the protected paths above.
4. Dismiss stale approvals when the pull request receives new commits.
5. Require all review conversations to be resolved.
6. Require the current successful CI contexts selected from an actual green
   pull-request run: Windows and Linux regression matrix, Windows EXE build,
   CodeQL, and dependency review. Reconfirm context names whenever workflows
   are renamed.
7. Require branches to be up to date before merging.
8. Block force pushes and branch deletion; do not configure a routine bypass
   actor. Keep any emergency bypass documented and separately audited.

If no independent reviewer is available, keep the approval requirement
pending rather than weakening CI or allowing self-approval. The owner must
arrange a second authorized maintainer before enabling the approval gate.

## Staging and release controls

- Limit the `udb-staging` environment to the intended release branch.
- Require an authorized environment reviewer for deployment.
- Keep Cloudflare staging credentials in environment-scoped secrets with
  least privilege; never expose them to pull-request jobs.
- Keep release publication on a manual, owner-triggered workflow and preserve
  the existing attestation, exact-SHA, and fail-closed release gates.
- Never commit signing keys, PFX files, tokens, or recovery material.

## Enforcement verification

After the administrator settings are saved, run both negative and positive
tests on a harmless workflow-only pull request:

- A green CI run without an independent approval must remain unmergeable.
- An approval from a non-author must satisfy the review requirement.
- A workflow change without the required code-owner review must remain
  unmergeable.
- A force-push and branch deletion attempt must be rejected.
- A normal pull request with all required checks and approvals must merge.

Record the ruleset ID, effective settings, tested check contexts, reviewer
identity, and test PR URL in issue #225. Do not close that issue based on this
file alone.

## Scope and current limitation

This change adds repository-side ownership metadata and an auditable setup
procedure. It does **not** mutate GitHub rulesets, branch protection, team
membership, or environment reviewers. Those are administrator-level settings
and must be saved and verified in GitHub Settings.
