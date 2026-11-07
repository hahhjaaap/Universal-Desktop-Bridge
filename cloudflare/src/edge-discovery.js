// Optional read-only MCP catalog at the authenticated Cloudflare edge.
//
// A ChatGPT connector must be able to discover its *per-device grant* even if
// the Windows Cloud Agent is temporarily disconnected. This module does NOT
// authorize any user: mcp.js calls it only after Access identity + device
// grants have been verified. Tools/call still goes to the real Windows host.
//
// Keep these signatures in sync with the corresponding read-only tools in
// src/udb/server.py; do not add privileged/owner-only tools to this list.
const empty = { type: "object", properties: {}, additionalProperties: false };
const str = { type: "string" };
const nonnegative = { type: "integer", minimum: 0 };

const catalog = Object.freeze([
  {
    name: "bridge_status",
    description: "Query the real Windows UDB bridge status; requires a connected Cloud Agent.",
    inputSchema: empty,
  },
  {
    name: "list_projects",
    description: "List projects registered on the connected Windows device.",
    inputSchema: empty,
  },
  {
    name: "list_files",
    description: "List files inside a registered project with its local read permissions.",
    inputSchema: { type: "object", properties: {
      project: str, path: { type: "string", default: "." },
      offset: nonnegative, limit: { type: "integer", minimum: 1, maximum: 1000 },
    }, required: ["project"], additionalProperties: false },
  },
  {
    name: "read_file",
    description: "Read owner-approved UTF-8 source from a registered Windows project.",
    inputSchema: { type: "object", properties: { project: str, path: str },
      required: ["project", "path"], additionalProperties: false },
  },
  {
    name: "search_files",
    description: "Search files in a registered project, excluding protected paths.",
    inputSchema: { type: "object", properties: {
      project: str, path: { type: "string", default: "." },
      pattern: { type: "string", default: "*" }, text: { type: "string", default: "" },
      limit: { type: "integer", minimum: 1, maximum: 1000 },
    }, required: ["project"], additionalProperties: false },
  },
  {
    name: "check_python_syntax",
    description: "Check Python source syntax without executing it on Windows.",
    inputSchema: { type: "object", properties: { project: str, path: str },
      required: ["project", "path"], additionalProperties: false },
  },
]);

export function edgeCatalog(allowed) {
  // Do not reflect arbitrary grant strings into discovery or allow clients
  // to invent new capabilities. All metadata comes from this source list.
  if (!Array.isArray(allowed)) return [];
  const set = new Set(allowed);
  return catalog.filter(tool => set.has(tool.name)).map(tool => ({
    ...tool,
    annotations: { readOnlyHint: true, destructiveHint: false,
      idempotentHint: true, openWorldHint: false },
    securitySchemes: [{ type: "oauth2", scopes: ["udb:read"] }],
  }));
}

export function edgeCatalogSupported(env, user) {
  // Roll out on separately reviewed staging only. Never replace legacy
  // owner/desktop tool discovery with a read-only catalog by accident.
  return env?.UDB_EDGE_READ_CATALOG === "true" &&
    (!user.ownerTools || user.ownerTools.length === 0);
}
