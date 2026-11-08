// The public catalog is generated from the actual Windows core and Companion
// schemas plus the reviewed per-tool security policy.
import { TOOL_CATALOG } from "./generated/tool-catalog.js";

export function edgeCatalog(allowed) {
  if (!Array.isArray(allowed)) return [];
  const set = new Set(allowed);
  // Only known catalog entries can be reflected. Exact grants are supplied by
  // the authenticated tenant/device authorization layer.
  return TOOL_CATALOG.filter((tool) => set.has(tool.name)).map((tool) => ({
    name: tool.name,
    description: tool.description,
    inputSchema: tool.inputSchema,
    annotations: tool.annotations,
    securitySchemes: tool.securitySchemes,
  }));
}

export function edgeCatalogSupported(env, user) {
  const readOnlyRollout = env?.UDB_EDGE_READ_CATALOG === "true" &&
    (!user.ownerTools || user.ownerTools.length === 0);
  const fullGrantRollout = env?.UDB_EDGE_TOOL_CATALOG === "true" &&
    Array.isArray(user.allowTools) && user.allowTools.length > 0;
  return readOnlyRollout || fullGrantRollout;
}
