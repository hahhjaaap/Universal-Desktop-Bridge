// Owner-gated public Companion MCP operations. Read-only OAuth scopes do not
// authorize these; each request also requires its own device/subject grant and
// the existing local Windows permission/approval checks.
import { exactToolGrant } from "./tool-grants.js";

export const COMPANION_TOOLS = Object.freeze([
  "terminal_start", "terminal_read", "terminal_stop",
  "file_list", "file_read", "file_write", "file_replace", "file_search",
  "file_stat", "file_mkdir", "file_read_lines", "terminal_list",
  "terminal_interact", "search_start", "search_read", "search_stop",
  "file_read_chunk", "file_upload", "file_operation", "system_process_list",
  "system_process_terminate", "work_recovery", "virtual_pointer",
  "spreadsheet", "word_document", "pdf_document", "file_transfer",
]);
export const isCompanionTool = name => COMPANION_TOOLS.includes(name);

const COMPANION_READ_ONLY = new Set([
  "terminal_read", "terminal_list", "file_list", "file_read", "file_search",
  "file_stat", "file_read_lines", "file_read_chunk", "search_read", "system_process_list",
]);
// Recovery can publish a new file when resuming a guarded create-only copy.
const COMPANION_ADDITIVE = new Set(["file_mkdir", "search_start"]);
const COMPANION_OPEN_WORLD = new Set(["terminal_start", "terminal_interact", "virtual_pointer"]);

export function companionAnnotations(name) {
  if (!isCompanionTool(name)) return undefined;
  const readOnly = COMPANION_READ_ONLY.has(name);
  return {
    readOnlyHint: readOnly,
    destructiveHint: !readOnly && !COMPANION_ADDITIVE.has(name),
    openWorldHint: COMPANION_OPEN_WORLD.has(name),
    idempotentHint: readOnly,
  };
}

export function companionToolGrant(env, deviceId, subject) {
  // A configured tenant policy remains authoritative.
  if (env?.UDB_ENABLE_COMPANION_TOOLS !== "true" ||
      env?.UDB_TENANT_POLICY !== undefined) return [];
  return exactToolGrant(env.UDB_COMPANION_TOOL_GRANTS, deviceId, subject, isCompanionTool);
}
