// Optional owner-gated MCP operations. This list only classifies tools;
// Cloudflare Access identity, a read grant, an *additional* device/owner secret
// and the Windows owner's existing local approvals are all still required.
// All tools outside this exact list remain unreachable through this gateway.
import { exactToolGrant } from "./tool-grants.js";
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
  "open_chatgpt",
]);
export const isOwnerTool = (name) => OWNER_TOOLS.includes(name);

export function ownerToolGrant(env, deviceId, subject) {
  // A configured tenant policy remains authoritative.
  if (env?.UDB_ENABLE_OWNER_TOOLS !== "true" ||
      env?.UDB_TENANT_POLICY !== undefined) return [];
  return exactToolGrant(env.UDB_OWNER_TOOL_GRANTS, deviceId, subject, isOwnerTool);
}
