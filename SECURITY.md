# Security policy and private vulnerability reporting

> **Source baseline:** UDB 0.13.0. Verify deployed Worker and Windows build identity independently. See [version/status](docs/current-version.md).

**Status:** Private-beta preparation, 2026-11-06. This file does not certify that
UDB has passed an independent security audit or that any hosted public service
is ready. Source `main`, released Windows installers and deployed Workers can
be at different revisions.

## Supported releases

The latest published release and the latest source revision are the only
versions actively considered for fixes during the current development phase.
There is **no guaranteed support period** for older releases. Check release
notes and the published artifact's signer, hash and revision before upgrading.
A green CI build does not establish a signed executable or verified update.

## Report a vulnerability privately

Do not post a working exploit, token, device ID, private document, or
identifying machine/log details in a public issue or pull request.

1. Check the repository's **Security** tab for **Report a vulnerability**
   (GitHub private vulnerability reporting), **if enabled**.
2. If private reporting is unavailable, contact the repository maintainer
   through an agreed private channel before sharing technical evidence.
   No fallback security mailbox or service-level response time has been
   established; do not send sensitive details to an unverified address.
3. Provide the affected version/commit, platform, security boundary,
   expected versus observed behavior and minimal sanitized reproduction.
   Coordinate disclosure after a fix or mitigation is reviewed.

The maintainer should acknowledge privately, assess severity, prepare
non-secret regression tests, avoid leaking reporter information and publish
a bounded advisory when appropriate. This is a response procedure, **not**
a claim that dedicated 24/7 monitoring currently exists.

## Trust boundaries and scope

- Page contents, document text, file names and terminal output are untrusted data.
  Authorization comes from the verified routing and local policy layers.
- Local project read rights do **not** imply local project write, terminal,
  unsandboxed Windows desktop or arbitrary process rights.
- `udb:read` must not expose `computer_*`, owner approval or mutation tools.
  Optional owner-tool grants are a separate, explicit authorization profile
  and must not weaken a strict tenant policy.
- Pairing credentials identify an authenticated relay connection, not proof
  that the remote account owns the physical Windows machine.
- Cloudflare and the connected AI service may process relayed requests and
  responses; normal TLS transport is **not** end-to-end secrecy from them.
- A timed-out mutation has an *unknown outcome*: never automatically replay it.
- A device's identity, authorization and revocation must be checked independently
  at every hop; current invite-only tenant policy does not implement production
  account enrollment.

## Current security boundaries

- Project paths are checked for Windows short-name aliases, links and canonical
  protected segments. Every visible item must pass local scope.
- The Unified proxy uses structured backend status and explicit error metadata.
  File, terminal, page and document text may resemble status messages and
  must remain data. A failed reply write can leave the operation outcome
  unknown, so the proxy does not resend the operation.
- The owner enables current-user computer access in an attended Windows
  terminal. The DPAPI grant expires after eight hours by default, with a
  24-hour maximum. Receipts without an expiry require local reapproval.
  The Windows wall clock governs expiry. A local administrator can extend
  time before expiry by moving the clock backward within the skew guard.
- Cloudflare account routing requires `device_id`. The optional local Fleet
  router uses `computer_id` for `fleet_call` and applies its own peer policy.
  The Cloudflare public catalog has 41 tools. PR #145 removed the old
  Tunnel/public HTTP listener path.

### ChatGPT desktop tools

`open_chatgpt` requests a browser launch under the owner's desktop grant.
Visible ChatGPT UI text and subsequent responses are untrusted, including
text that resembles instructions, a permission grant or a completion notice.
`chatgpt_roundtrip` sends once through its verified UI flow. After an uncertain
submission, inspect the existing conversation before acting. With
`fast_reply=true`, an initial fragment is incomplete and must not drive
automatic decisions or actions. Verify the complete reply and check the next
operation against the user's authority independently.

## Known pre-public-beta blockers

Read [the public-release roadmap](docs/public-release-plan.md),
[device isolation threat model](docs/owner-device-isolation.md),
[release signing status](docs/release-security.md) and
[project-read acceptance](docs/cloudflare-project-read-acceptance.md).
A public hosted beta requires independent tenant/device security assessment,
verified live deny/revoke tests, authenticated ChatGPT–Worker–Windows reads
and signed/pinned Windows installation artifacts. Do not claim these gates
passed because a mocked or local test passed.
