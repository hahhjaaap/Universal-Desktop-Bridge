# UDB privacy and data-flow disclosure (draft)

> **Status: Maintainer review required before publication as a privacy
> notice.** This draft documents known architectural boundaries and unknowns.
> It is not a claim that a hosted customer service is available, that UDB
> retains no data, or that any specific privacy-law obligation has been met.

## Where data can go

UDB is Windows-first and local-first, **not** a promise that all data stays
on the computer. Depending on features enabled by the Windows owner:

| Data or action | Known path / privacy implication |
| --- | --- |
| Project files | Remain local until an explicitly allowed tool reads or sends them; tool results may contain file text, paths and metadata |
| Local state | Managed Windows installations maintain application/user state separately from binaries, under the user's local profile |
| AI/MCP requests | Requests and resulting content may reach the connected AI/MCP provider; that provider has its own terms and retention rules |
| Cloudflare pairing | If the optional relay is enabled, Worker and Durable Object infrastructure handle device routing, identity/grant decisions and relayed MCP messages |
| Browser/desktop tools | When locally authorized, results may include page content, filenames, process/window details or screenshots depending on the requested tool |
| Diagnostics | Commands and tests can emit health/status and errors; users must review and redact logs before sharing them |

These are **possible processing paths**, not a statement that every feature is
active or that a production hosted multi-tenant service exists. Cloudflare
relay access is **not end-to-end encrypted against the relay operator**.
A connected AI provider may receive the specific content returned by tools.

## Choice and control

- The Windows owner chooses registered projects, local permissions and whether
  to enable a cloud connection; these are distinct from AI tool prompts.
- Do not authorize broad access just to fix a connection issue. Review the
  exact device and tool scopes, and stop/revoke access through the supported
  attended controls.
- Stopping an agent is different from revoking cloud/device grants. Uninstalling
  an executable is not necessarily deletion of persisted local data,
  previously sent AI content or provider-side logs.
- Do not upload credentials, pairing secrets, unrelated personal files or
  unredacted diagnostic output to public issues or chat.

## Not yet verified; required before a public privacy notice

The maintainer must explicitly determine and document, for the **actual
deployment**: responsible legal entity and contact; hosting/processor list,
geographies and cross-border transfers; user-account identity data; precise
server-side and local retention periods; deletion/export requests and
backup expiration; any error/usage telemetry; cookies and consent behavior;
minor-user considerations; lawful basis and jurisdiction-specific disclosures;
incident notification and support contact.

No values are invented here. Those details cannot be concluded from source
code or unit tests alone, and a GitHub merge does **not** provision hosting,
change Cloudflare policy or establish a legal privacy policy.

See [public release plan](docs/public-release-plan.md),
[security guidance](SECURITY.md), and
[owner/device isolation](docs/owner-device-isolation.md).
