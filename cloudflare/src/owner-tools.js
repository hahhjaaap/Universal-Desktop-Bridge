// Optional owner-gated MCP operations. This list only classifies tools;
// Cloudflare Access identity, a read grant, an *additional* device/owner secret
// and the Windows owner's existing local approvals are all still required.
// All tools outside this exact list remain unreachable through this gateway.
const DEVICE_ID = /^[a-f0-9]{32}$/;
export const OWNER_TOOLS = Object.freeze([
  "propose_file_write",
  "propose_sandbox_job",
  "propose_media_download",
  "get_request_status",
  "get_job_status",
  "list_jobs",
  "propose_desktop_session",
  "desktop_status",
  "desktop_screenshot",
  "desktop_action",
  "desktop_snapshot",
  "desktop_wait_for",
  "desktop_element_action",
  "desktop_stop",
  "read_files",
  "propose_text_edit",
  "desktop_app",
  "desktop_batch",
  "host_status",
  "host_start_session",
  "host_browser",
  "host_workspace",
  "host_screenshot",
  "host_close_session",
  "computer_status",
  "computer_utilities",
  "computer_files",
  "computer_execute",
  "computer_process",
  "computer_desktop",
]);
export const isOwnerTool = (name) => OWNER_TOOLS.includes(name);
const record = (value) => value && typeof value === "object" && !Array.isArray(value);

export function ownerToolGrant(env, deviceId, subject) {
  // Require three independent opt-ins. A configured tenant policy stays
  // authoritative; never bypass its stricter read-only limits.
  if (env?.UDB_ENABLE_OWNER_TOOLS !== "true" ||
      env?.UDB_TENANT_POLICY !== undefined ||
      !DEVICE_ID.test(deviceId) ||
      typeof subject !== "string" || !subject.includes("@") ||
      subject.length > 200 || subject.trim() !== subject) return [];
  const raw = env?.UDB_OWNER_TOOL_GRANTS;
  if (typeof raw !== "string" || raw.length === 0 || raw.length > 16384) return [];
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
