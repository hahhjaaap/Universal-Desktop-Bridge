// Optional owner-gated MCP operations. Every name comes from the generated
// public catalog; no stale aliases or hand-maintained allowlist is accepted.
import { TOOL_CATALOG } from "./generated/tool-catalog.js";

const DEVICE_ID = /^[a-f0-9]{32}$/;
export const OWNER_TOOLS = Object.freeze(
  TOOL_CATALOG.filter((tool) => !tool.policy.defaultEnabled)
    .map((tool) => tool.name),
);
export const isOwnerTool = (name) => OWNER_TOOLS.includes(name);
const record = (value) => value && typeof value === "object" && !Array.isArray(value);

export function ownerToolGrant(env, deviceId, subject) {
  // This legacy opt-in remains disabled whenever an authoritative tenant
  // policy is configured. Windows-side permissions remain independently enforced.
  if (env?.UDB_ENABLE_OWNER_TOOLS !== "true" ||
      env?.UDB_TENANT_POLICY !== undefined ||
      !DEVICE_ID.test(deviceId) ||
      typeof subject !== "string" || !subject.includes("@") ||
      subject.length > 200 || subject.trim() !== subject) return [];
  const raw = env?.UDB_OWNER_TOOL_GRANTS;
  if (typeof raw !== "string" || raw.length === 0 || raw.length > 32768) return [];
  try {
    const all = JSON.parse(raw);
    if (!record(all) || !Object.hasOwn(all, deviceId)) return [];
    const users = all[deviceId];
    if (!record(users) || !Object.hasOwn(users, subject)) return [];
    const names = users[subject];
    // Reject the whole grant instead of silently accepting a corrupted subset.
    if (!Array.isArray(names) || names.length === 0 ||
        names.length > OWNER_TOOLS.length ||
        new Set(names).size !== names.length ||
        !names.every((name) => typeof name === "string" && isOwnerTool(name)))
      return [];
    return [...names];
  } catch { return []; }
}
