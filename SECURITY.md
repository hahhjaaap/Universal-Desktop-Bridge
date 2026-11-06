# Security policy (maintainer review required)

> **Status:** Proposed project security guidance for a pre-1.0 Windows-first
> MCP bridge. This document does not claim an independent audit, a public
> hosted service, or a guaranteed patch response time.

## Reporting a vulnerability

Please **do not** publish usable exploit details, access tokens, device
secrets, pairing data, customer files or personal information in a public
GitHub issue, pull request or Actions log.

If GitHub's **Report a vulnerability** option is available under this
repository's **Security** tab, use it to report privately. If it is not
available, open a public issue requesting a private reporting channel
**without** including exploit instructions, secrets or sensitive data.
The repository maintainer must confirm a private channel before receiving
sensitive details. An ordinary GitHub issue is not a confidential channel.

For a useful *private* report, include the affected source commit or
installed release, operating system, minimum reproduction using synthetic
data, expected/observed authorization outcome, and potential impact.
Never attach credentials or real user files.

## Supported releases and response expectations

UDB is pre-1.0. The source branch and a locally installed executable can
differ materially, and there is **no published security-support lifetime
or patch SLA**. Check
[GitHub Releases](https://github.com/hahhjaaap/Universal-Desktop-Bridge/releases),
[release trust](docs/release-security.md) and
[release readiness](docs/public-release-plan.md) independently.

A successful CI run is not a security audit. The documented standalone
Windows installer is checksum-checked but **not Authenticode-signed**;
do not interpret a checksum published by the same build pipeline as proof of
publisher identity.

## Security boundaries that must remain intact

- Local UDB tools act with the Windows account's authority. Owner grants,
  protected paths and local approvals matter; an authenticated AI client
  is still untrusted input.
- The Cloudflare Worker/Durable Object path is an optional relay. Authenticated
  access requires device-specific grants and local project permissions.
  A healthy Worker or paired device is **not** proof of authorization.
- Cloudflare `udb:read` must remain **read-only**: never enable remote
  desktop, shell, unsandboxed computer control or file writes through it.
- Cloudflare and connected AI providers may process relayed file contents.
  UDB does **not** provide end-to-end confidentiality from the relay operator.
- No failed or timed-out write/execution call should be automatically
  replayed: the outcome could be unknown.
- A lost/stolen device or exposed device token requires owner-attended
  revocation and recovery. Production signup/device ownership proof and
  independent tenant isolation are **not yet verified**.

See [owner/device isolation](docs/owner-device-isolation.md) and
[Cloudflare read acceptance](docs/cloudflare-project-read-acceptance.md).

## Release gate

Do not describe UDB as security-reviewed, publicly ready, remotely writable
or safely multi-tenant until the explicitly documented acceptance gates pass,
including authenticated read/deny/revoke/reconnect tests on separate owner
identities and real devices, signer-verified Windows distribution and an
independent security review.
