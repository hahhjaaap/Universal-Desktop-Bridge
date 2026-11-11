// Owner-gated public Companion MCP operations. Read-only OAuth scopes do not
// authorize these; each request also requires its own device/subject grant and
// the existing local Windows permission/approval checks.
const DEVICE_ID = /^[a-f0-9]{32}$/;
const record = value => value && typeof value === "object" && !Array.isArray(value);

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
const COMPANION_ADDITIVE = new Set(["file_mkdir", "search_start", "work_recovery"]);
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
  // Never fall back from a tenant policy or another identity or device.
  if (env?.UDB_ENABLE_COMPANION_TOOLS !== "true" ||
      env?.UDB_TENANT_POLICY !== undefined ||
      !DEVICE_ID.test(deviceId) ||
      typeof subject !== "string" || subject.length > 200 ||
      subject.trim() !== subject || !subject.includes("@")) return [];
  const raw = env?.UDB_COMPANION_TOOL_GRANTS;
  if (typeof raw !== "string" || raw.length < 1 || raw.length > 16384) return [];
  try {
    const grants = JSON.parse(raw);
    if (!record(grants) || !Object.hasOwn(grants, deviceId)) return [];
    const users = grants[deviceId];
    if (!record(users) || !Object.hasOwn(users, subject)) return [];
    const names = users[subject];
    if (!Array.isArray(names) || names.length < 1 ||
        names.length > COMPANION_TOOLS.length ||
        new Set(names).size !== names.length ||
        !names.every(name => typeof name === "string" && isCompanionTool(name)))
      return [];
    return [...names];
  } catch { return []; }
}
