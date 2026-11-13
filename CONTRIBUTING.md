# Contributing to Universal Desktop Bridge

> **UDB 0.12.0 documentation review (2026-11-13):** Current source targets UDB 0.12.0; installed Windows releases and deployed Cloudflare services must be verified independently. See [version/status](docs/current-version.md).

UDB is a Windows-first, owner-authorized MCP bridge. Contributions are
welcome when they preserve existing tools, device boundaries and reproducible
installation. Please read [SECURITY.md](SECURITY.md) before reporting a
security defect.

## Scope changes narrowly

Use one focused PR for a measurable change. Explain the baseline, behavior
change, regression tests, performance impact and rollback strategy. The
priorities are **speed → stability → Windows control → connection UX →
packaging**, subject to the outstanding authentication, signing and
end-to-end acceptance gates described in [security](SECURITY.md) and the
[historical readiness plan](docs/public-release-plan.md).

Do not edit a real user's owner grants, Cloudflare secrets, OAuth identity,
Windows permissions, live project registry or installed release as part of
a test. Use synthetic devices, identities and disposable project fixtures.
Never add arbitrary remote execution to the read-only gateway.

## Development and checks

With Python 3.11 or 3.12, Node.js 22 and an isolated virtual environment:

```sh
python -m pip install -e ".[office,dev]"
python -m ruff check src tools tests
python -m ruff format --check .
python tools/audit_repository.py --strict
python tools/check_import_boundaries.py
python -m pytest
node --test cloudflare/tests/*.test.js render/tests/*.test.mjs
```

The tracked-file audit uses Git and must run in a clone rather than a ZIP
without `.git`. Windows-native UI, PyInstaller/standalone packaging,
installer update/rollback, browser and OS-specific tests require their
matching Windows CI runner. Linux-only green results are insufficient for a
Windows release. The normal `main` CI matrix and build identity must be
checked for the exact commit being merged.

For performance changes, record p50/p95 and machine/test configuration before
and after; do not claim general improvement based on one warm run. For
authentication or approvals, add denied-path and revocation tests, including
no fallback to older credentials or different devices. Unknown-outcome
mutations must not be retried automatically.

## Pull request checklist

- [ ] Change is scoped; documented behavior and safety invariants preserved
- [ ] No actual credentials, device IDs, file bodies or personal data committed
- [ ] New/changed behavior covered by synthetic fixtures and regression tests
- [ ] Ruff, pytest and Node tests run; applicable Windows/build CI passes
- [ ] Authorization, signing or onboarding effects explicitly reviewed
- [ ] Feature is not presented as deployed, installed or signed unless proven
- [ ] Rollback and compatibility notes are included when relevant

Use GitHub issues for ordinary defects and feature proposals, but keep
vulnerability details out of public issues. Do not begin an account rollout,
publish a signed-release claim or change infrastructure secrets from a
documentation PR.
