// The desktop wheel and the gateway use exactly the same action-to-grant map.
import spec from "../../src/udb/tool_families.json" with { type: "json" };

export const FAMILIES = Object.freeze(spec.families.map(group => Object.freeze({
  ...group, actions: Object.freeze({ ...group.actions }),
})));
const legacyAliases = new Set(spec.legacyAliases);
const record = value => value !== null && typeof value === "object" && !Array.isArray(value);
const annotations = group => ({ readOnlyHint: group.readOnly,
  destructiveHint: !group.readOnly, idempotentHint: group.readOnly,
  openWorldHint: group.openWorld });

function compactSchema(value) {
  const schema = structuredClone(value);
  delete schema.title;
  if (schema.default === "") delete schema.default;
  for (const key of ["properties", "$defs"]) if (schema[key])
    schema[key] = Object.fromEntries(Object.entries(schema[key]).map(([k, v]) => [k, compactSchema(v)]));
  for (const key of ["items", "additionalProperties"]) if (record(schema[key]))
    schema[key] = compactSchema(schema[key]);
  for (const key of ["oneOf", "anyOf", "allOf"]) if (schema[key])
    schema[key] = schema[key].map(compactSchema);
  return schema;
}

export function resolveFamily(name, args) {
  const group = FAMILIES.find(group => group.name === name);
  if (!group) return { name, arguments: args };
  if (Object.keys(args).length !== 2 || !Object.hasOwn(args, "action") ||
      !Object.hasOwn(args, "params") || !record(args.params) ||
      typeof args.action !== "string" || !Object.hasOwn(group.actions, args.action))
    throw new Error("invalid_family_arguments");
  return { name: group.actions[args.action], arguments: structuredClone(args.params) };
}

export function publicToolNames(names) {
  const result = new Set(names.filter(name => !legacyAliases.has(name)));
  for (const group of FAMILIES) {
    let found = false;
    for (const target of Object.values(group.actions)) {
      if (result.delete(target)) found = true;
    }
    if (found) result.add(group.name);
  }
  return [...result];
}

// Accept old 59-tool Windows catalogs and new family catalogs during migration.
// Calls always go to the original tool, so a gateway upgrade works with old EXEs.
export function consolidateFamilies(tools) {
  const catalog = new Map(tools.filter(tool => tool && typeof tool.name === "string")
    .map(tool => [tool.name, structuredClone(tool)]));
  for (const group of FAMILIES) {
    const existing = catalog.get(group.name);
    if (existing) continue;
    const actions = Object.entries(group.actions).filter(([, target]) => catalog.has(target));
    if (!actions.length) continue;
    const branches = actions.map(([action, target]) => {
      const original = catalog.get(target);
      const schema = compactSchema(original.inputSchema || { type: "object" });
      delete schema.type; // The common params schema already enforces object type.
      schema.additionalProperties = false;
      return { properties: { action: { const: action }, params: schema },
        description: original.description || target };
    });
    catalog.set(group.name, { name: group.name, description: group.description,
      inputSchema: { type: "object", properties: {
        action: { type: "string", enum: actions.map(([a]) => a) }, params: { type: "object" },
      }, oneOf: branches, required: ["action", "params"], additionalProperties: false },
      annotations: annotations(group) });
    for (const [, target] of actions) catalog.delete(target);
  }
  return [...catalog.values()];
}

export function authorizedFamilyCatalog(tools, allowedNames) {
  const allowed = new Set(allowedNames);
  return consolidateFamilies(tools).flatMap(tool => {
    const group = FAMILIES.find(group => group.name === tool.name);
    if (!group || !tool.inputSchema?.oneOf)
      return allowed.has(tool.name) ? [tool] : [];
    const branches = tool.inputSchema.oneOf.filter(branch => {
      const action = branch.properties?.action?.const;
      if (typeof action === "string" && Object.hasOwn(group.actions, action))
        return allowed.has(group.actions[action]);
      return false;
    });
    if (!branches.length) return [];
    const properties = {
      action: { type: "string", enum: branches.map(b => b.properties.action.const) },
      params: { type: "object" },
    };
    return [{ ...tool, inputSchema: { ...tool.inputSchema, properties, oneOf: branches } }];
  });
}
