# UDB data-flow and privacy disclosure

> **UDB 0.12.0 documentation review (2026-11-13):** Current source targets UDB 0.12.0; installed Windows releases and deployed Cloudflare services must be verified independently. See [version/status](docs/current-version.md).

**Status: draft for developer and private-beta review, 2026-11-06.**
This is a technical disclosure of source capabilities, **not** a finalized
public privacy notice, a promise of retention periods or authorization to
start a commercial hosted service. The future service operator must review,
complete and approve actual processors, legal contact, retention and deletion
terms before onboarding general users.

## What the software may handle

Depending on enabled tools and the owner's permissions, UDB may process:

- Registered project names, local file paths, file contents and hashes;
  documents, spreadsheets or PDFs opened by the owner-authorized workflow.
- Device/session identifiers, connection state, tool names, call identifiers,
  error classes and timestamps required to route or diagnose requests.
- Owner-chosen permission and project configuration, device-pairing state
  and credentials needed for an authenticated connection.
- Additional browser/desktop or locally approved mutation inputs **only**
  when their separate capabilities and permissions are explicitly enabled.

A user's request to a connected AI assistant can itself reveal the content
of returned files or tool results. Do not assume a tool response disappears
when the Windows agent stops.

## Local-only versus hosted Cloudflare modes

In local-only mode the owner uses a local MCP client and locally registered
projects. Operating-system and client-side storage/logging may still apply.
Enabling a separate Cloudflare gateway changes the data boundary:

```text
Windows owner-approved project/tool
    ⇄ Windows UDB agent ⇄ Cloudflare Worker/Durable Object
    ⇄ authenticated MCP/AI client ⇄ AI service
```

The gateway can receive the routed arguments and responses, including scoped
path and file content when `read_file` is authorized. A Cloudflare health
check or a successful OAuth login does not grant file access by itself.
Transport encryption does **not** make relayed content unreadable to the
relay and AI service operators. For sensitive files, use local-only mode
unless the complete data path and linked service terms are acceptable.

## Permissions, revocation and retention

Project registration and exact tool grants are separate owner decisions.
The default hosted project-read scope is intended to be read-only. It is not
a permission to approve writes, run shell commands or operate Windows
remotely. An owner should be able to stop their local agent and revoke a
connection using the approved device/identity controls.

Stopping the agent or revoking an authorization prevents future calls through
that path; it **does not automatically delete** copies already processed by
an AI client, platform, device log or infrastructure provider. Local job
history, AI conversation history and hosted infrastructure logs may have
different storage/deletion rules.

**Retention periods, geographic processing locations, support-data access,
backup removal times and any hosted diagnostic telemetry have not been
audited or approved as an end-user policy.** Do not make a fixed-retention,
automatic-deletion or no-telemetry promise until these are documented from the
actual deployment and service contracts. Never send credential material,
document bodies or browser secrets in diagnostic uploads.

## Requirements before public release

The operator must publish: responsible legal entity/contact, actual cloud and
AI processors, permitted purposes, data locations, log fields and retention,
incident process, subject access/deletion procedures, privacy choices and any
applicable required notices. Diagnostic export must be purpose-limited,
redacted and consented to. An owner must explicitly approve final terms and
deployment; this draft does not constitute that approval.

See [security policy](SECURITY.md),
[release roadmap](docs/public-release-plan.md) and
[owner/device security model](docs/owner-device-isolation.md).
