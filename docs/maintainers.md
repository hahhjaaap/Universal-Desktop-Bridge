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
