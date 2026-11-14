// Canonical schemas are generated from udb.registry.catalog() and checked in.
// This keeps Python Windows handlers, Companion schemas and Cloudflare discovery
// on one schema source. The live device is never consulted for discovery.
import canonicalTools from "./fleet-tool-catalog.json" with { type: "json" };
import { ENROLLED_CATALOG } from "./local-permissions.js";
import { publicToolNames } from "./tool-families.js";
import { isReadTool } from "./read-tools.js";
import { companionAnnotations } from "./companion-tools.js";

export const FLEET_CATALOG_VERSION = "0.3.0";
const canonical = new Map(canonicalTools.map(tool => [tool.name, tool]));
const POTENTIALLY_DESTRUCTIVE = new Set([
  "propose_file_write", "desktop_action", "desktop_element_action", "desktop_stop",
  "desktop_app", "desktop_batch", "host_browser", "host_workspace", "host_close_session",
]);

export function fleetCanonicalCatalog() {
  const names = publicToolNames(ENROLLED_CATALOG);
  const missing = names.filter(name => !canonical.has(name));
  if (missing.length) throw new Error("fleet_catalog_schema_missing:" + missing.join(","));
  return names.map(name => {
    const tool = structuredClone(canonical.get(name));
    const securitySchemes = [{ type: "oauth2", scopes: isReadTool(name) ? ["udb:read"] : [] }];
    let annotations = tool.annotations ?? companionAnnotations(name);
    if (POTENTIALLY_DESTRUCTIVE.has(name))
      annotations = { ...annotations, readOnlyHint: false, destructiveHint: true };
    return {
      ...tool,
      ...(annotations ? { annotations } : {}),
      securitySchemes,
      _meta: { ...tool._meta, securitySchemes },
    };
  });
}
