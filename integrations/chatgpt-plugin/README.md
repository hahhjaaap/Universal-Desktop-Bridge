# UDB Desktop Bridge — ChatGPT plugin

This package connects ChatGPT to the existing UDB staging Streamable HTTP MCP server.

- **Transport:** Streamable HTTP
- **Authentication:** Cloudflare Access Managed OAuth with Dynamic Client Registration (DCR)
- **Requested resource scope:** `udb:read`
- **Staging device:** `54841a965bb6405c9408137a1e2eb650`
- **User action:** complete Cloudflare Access sign-in and OAuth consent before tools can be used.

The package contains no credentials, tokens, or pairing secrets. It does not deploy or change the UDB server. Production is intentionally not configured in this package.
