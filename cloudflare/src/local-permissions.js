// Discovery is metadata, not an execution grant. Only authenticated enrolled
// owners use this policy; legacy/tenant grants remain independently enforced.
import { READ_TOOLS } from "./read-tools.js";
import { OWNER_TOOLS } from "./owner-tools.js";
import { COMPANION_TOOLS } from "./companion-tools.js";

export const ENROLLED_CATALOG = Object.freeze([...new Set([
  ...READ_TOOLS, ...OWNER_TOOLS, ...COMPANION_TOOLS,
])]);

export function windowsPermissionReport(result) {
  if (result?.isError || !Array.isArray(result?.content)) return null;
  const reports = [];
  for (const block of result.content) {
    if (block?.type !== "text" || typeof block.text !== "string") continue;
    let value;
    try { value = JSON.parse(block.text); } catch { continue; }
    if (value?.name === "Universal Desktop Bridge" && value.platform === "nt" &&
        value.computer_access && typeof value.computer_access === "object" &&
        value.host_background && typeof value.host_background === "object") reports.push(value);
  }
  return reports.length === 1 ? reports[0] : null;
}

export function relayToolEnabled(env, name) {
  if (READ_TOOLS.includes(name)) return true;
  if (OWNER_TOOLS.includes(name)) return env.UDB_ENABLE_OWNER_TOOLS === "true";
  if (COMPANION_TOOLS.includes(name)) return env.UDB_ENABLE_COMPANION_TOOLS === "true";
  return false;
}

export function locallyAllowedTools(report, env) {
  const computer = report?.computer_access;
  const broad = computer?.enabled === true && computer.scope === "current_windows_user" &&
    Array.isArray(computer.capabilities) &&
    ["files", "execute", "desktop"].every(name => computer.capabilities.includes(name));
  const background = report?.host_background?.enabled === true;
  const projects = Number.isSafeInteger(report?.readiness?.readable_projects) &&
    report.readiness.readable_projects > 0;
  return ENROLLED_CATALOG.filter(name => {
    if (name === "bridge_status") return true;
    if (!relayToolEnabled(env, name)) return false;
    if (name.startsWith("host_")) return background || (name === "host_status" && broad);
    if (READ_TOOLS.includes(name)) return broad || projects;
    return broad;
  });
}

export async function checkLocalPermission(stub, name, env) {
  // Exactly one read, never a target-command probe or mutation retry. Do not
  // cache permission evidence: local revocation must affect the next call.
  const id = "udb-permission-" + crypto.randomUUID();
  let response, reply;
  try {
    response = await stub.fetch(new Request("https://internal/rpc", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id, method: "tools/call",
        params: { name: "bridge_status", arguments: {} } }),
    }));
    if (!response.ok) return { verified: false };
    reply = await response.json();
  } catch { return { verified: false }; }
  if (reply?.jsonrpc !== "2.0" || reply.id !== id || reply.error) return { verified: false };
  const report = windowsPermissionReport(reply.result);
  if (!report) return { verified: false };
  return { verified: true, allowed: locallyAllowedTools(report, env).includes(name) };
}

export function permissionRequired(name) {
  const background = name.startsWith("host_") && name !== "host_status";
  const action = background
    ? "Enable background access in the local UDB manager."
    : "On this Windows device, run udb --access computer in your own terminal and review the local permission prompt. Project read tools can also use existing local project permissions.";
  return { isError: true, content: [{ type: "text", text:
    "This tool is available, but the Windows owner has not granted its local permission. " + action }],
  structuredContent: { code: "local_owner_permission_required", dispatched: false,
    permission_source: "windows_owner", next_action: action } };
}
