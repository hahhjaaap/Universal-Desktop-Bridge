// Account-wide, versioned discovery metadata. Never seeded from Windows status.
// These names come from the same classification source as local authorization.
// Family action maps come from the same shared JSON as the Windows catalog.
// NOTE: non-read standalone signatures are intentionally permissive until the
// full canonical Windows schema is exported at build time; the Windows backend
// performs argument validation, and a listed tool grants no execution rights.
import { ENROLLED_CATALOG } from "./local-permissions.js";
import { edgeCatalog } from "./edge-discovery.js";
import { publicToolNames, FAMILIES } from "./tool-families.js";
import { companionAnnotations } from "./companion-tools.js";

export const FLEET_CATALOG_VERSION = "0.2.0";
const record = () => ({ type: "object", properties: {}, additionalProperties: true });
const securitySchemes = [{ type: "oauth2", scopes: ["udb:read"] }];

export function fleetCanonicalCatalog() {
  const reads = new Map(edgeCatalog(ENROLLED_CATALOG).map(t => [t.name, t]));
  const families = new Map(FAMILIES.map(f => [f.name, f]));
  return publicToolNames(ENROLLED_CATALOG).map(name => {
    if (reads.has(name)) return structuredClone(reads.get(name));
    const family = families.get(name);
    const inputSchema = family ? {
      type: "object",
      properties: {
        action: { type: "string", enum: Object.keys(family.actions) },
        params: record(),
      },
      required: ["action", "params"], additionalProperties: false,
    } : record();
    const annotations = family ? {
      readOnlyHint: family.readOnly, destructiveHint: !family.readOnly,
      idempotentHint: family.readOnly, openWorldHint: family.openWorld,
    } : companionAnnotations(name);
    return {
      name, description: family?.description ||
        "Windows UDB operation. The target device enforces local permissions and validates arguments.",
      inputSchema, ...(annotations ? { annotations } : {}),
      securitySchemes: structuredClone(securitySchemes),
    };
  });
}
