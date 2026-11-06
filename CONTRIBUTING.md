# Contributing to Universal Desktop Bridge

UDB is a Windows-first MCP bridge with a canonical Python implementation in
`src/udb/`. The compatibility launchers in the repository root are not
independent implementations. Contributions should preserve local owner
permission boundaries and not silently grant remote access.

## Before opening a change

- Check existing GitHub issues and pull requests; describe the exact bug,
  feature and scope. Prefer a small focused branch and pull request.
- Keep **production** Cloudflare Worker policies, grants, user data and local
  Windows installations untouched during development unless a separate,
  explicitly owner-approved deployment/test plan exists.
- Reproduce problems with *synthetic* projects and accounts rather than real
  personal files, passwords, tokens or customer data.
- Document which observation comes from source tests versus a deployed
  Worker and installed Windows release. Do not claim end-to-end success
  from a health endpoint or mocked test.

## Python development

Python 3.11+ is required. In a dedicated environment:

```shell
python -m pip install -e ".[dev]"
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
```

Windows release checks, the frozen EXE, updater/rollback, and integration
tests must also pass in GitHub Actions before merging changes that affect
packaging, native controls or the installer. Linux Python tests alone do not
validate Windows native behavior.

For the optional Cloudflare relay:

```shell
cd cloudflare
npm install
npm test
```

A local Node test never substitutes for real Cloudflare OAuth, a per-device
owner grant, or live ChatGPT → Worker → Windows authorization acceptance.

## Security-sensitive changes

Keep existing **fail-closed** policy, explicit per-device/per-subject
permissions, project-scoped reads, protected paths and owner-attended
approvals. No `udb:read` scope may expose remote shell, desktop, writes
or approval tools. Never retry a mutation after an uncertain result.

Changes involving identity, enrollment, shared-device grants, browser
access, binaries, signing, updates or secrets require an explicit threat
and rollback assessment plus denial tests. Do not log device tokens,
private OAuth information, synthetic fixture secret-marker contents or
real project text in issues/actions.

Follow [SECURITY.md](SECURITY.md) for reporting suspected vulnerabilities,
the [architecture](ARCHITECTURE.md) for component ownership and
[public release gates](docs/public-release-plan.md) for acceptance.

## Pull request checklist

- [ ] Scoped description and related issue
- [ ] Appropriate tests for successful paths **and denial/failure paths**
- [ ] `ruff check` and `ruff format --check` pass
- [ ] Python and (if relevant) Node/Windows CI pass
- [ ] Documentation states source/installed/deployed boundaries accurately
- [ ] No credentials, private file content, production grant change or
      undeclared privilege expansion
- [ ] Rollback plan for affected security/release behavior

New license and branding arrangements are outside a normal code PR;
consult the repository maintainer rather than assuming MIT covers
project trademarks.
