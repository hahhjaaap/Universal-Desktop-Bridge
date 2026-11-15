# UDB Desktop Bridge — ChatGPT plugin

> **UDB 0.12.0 documentation review (2026-11-13):** Staging/opt-in instructions do not change live Worker, OAuth, owner permissions or secrets. See [version/status](../../docs/current-version.md).

This optional package targets a reviewed **staging** Streamable HTTP MCP server. The listed staging device ID is an example of that integration, not an automatically configured device for other installations. `udb mcp-config` prints a per-device URL for compatibility. When the opt-in Fleet feature is enabled and the device is linked, use the shared `/v1/account/mcp` URL printed by `udb setup` instead. The Fleet candidate is not deployed to the current staging Worker or production; verify OAuth and owner grants independently.

- **Transport:** Streamable HTTP
- **Authentication:** Cloudflare Access Managed OAuth with Dynamic Client Registration (DCR)
- **Requested resource scope:** `udb:read`
- **Staging device:** `54841a965bb6405c9408137a1e2eb650`
- **User action:** complete Cloudflare Access sign-in and OAuth consent before tools can be used.

The package contains no credentials, tokens, or pairing secrets. It does not deploy or change the UDB server. Production is intentionally not configured in this package.
