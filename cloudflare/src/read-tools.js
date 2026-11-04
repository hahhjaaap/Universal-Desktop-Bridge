// Classification only. Every request still needs its per-device/identity grant
// and the Windows project's local permission. This list grants no access.
export const READ_TOOLS = Object.freeze([
  "bridge_status", "list_projects", "list_files", "read_file",
  "search_files", "check_python_syntax",
]);
export const isReadTool = (name) => READ_TOOLS.includes(name);
