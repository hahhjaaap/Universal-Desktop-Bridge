// Grant entries are exact canonical tool names or explicitly scoped actions.
const DEVICE_ID = /^[a-f0-9]{32}$/;
const EMAIL = /^[a-z0-9!#$%&'*+/=?^`{|}~_-]+(?:\.[a-z0-9!#$%&'*+/=?^`{|}~_-]+)*@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/i;
const ISSUER_SUB = /^https:\/\/[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.cloudflareaccess\.com#[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}$/;
const record = value => value !== null && typeof value === "object" && !Array.isArray(value);

export function emailSubject(subject) {
  return typeof subject === "string" && subject.length <= 200 &&
    subject.trim() === subject && EMAIL.test(subject);
}

const SCOPABLE = new Map([
  ["computer_files", ["stat", "list", "read", "write", "mkdir", "copy", "move"]],
  ["file_operation", ["copy", "move", "read", "list", "cancel"]],
  ["file_upload", ["begin", "write", "status", "commit", "abort"]],
  ["work_recovery", ["list", "inspect", "resume"]],
  ["terminal_interact", ["interact"]],
  ["virtual_pointer", ["show", "hide", "stop", "status", "list", "move", "click", "drag", "scroll"]],
]);

export function exactToolGrant(raw, deviceId, subject, acceptsTool) {
  if (typeof deviceId !== "string" || !DEVICE_ID.test(deviceId) ||
      typeof subject !== "string" || subject.length > 200 ||
      subject.trim() !== subject || !(emailSubject(subject) || ISSUER_SUB.test(subject)) ||
      typeof raw !== "string" || raw.length < 1 || raw.length > 16384) return [];
  try {
    const all = JSON.parse(raw);
    if (!record(all) || !Object.hasOwn(all, deviceId)) return [];
    const users = all[deviceId];
    if (!record(users) || !Object.hasOwn(users, subject)) return [];
    const entries = users[subject];
    if (!Array.isArray(entries) || entries.length > 128 ||
        new Set(entries).size !== entries.length) return [];
    if (!entries.every(entry => {
      if (typeof entry !== "string") return false;
      const [name, action, extra] = entry.split(":");
      return acceptsTool(name) && extra === undefined &&
        (action === undefined || SCOPABLE.get(name)?.includes(action));
    })) return [];
    return [...entries];
  } catch { return []; }
}

export function toolGrantScope(entries) {
  const actions = new Map();
  const unrestricted = new Set();
  for (const entry of entries) {
    const [name, action] = entry.split(":");
    if (action === undefined) unrestricted.add(name);
    else {
      if (!actions.has(name)) actions.set(name, new Set());
      actions.get(name).add(action);
    }
  }
  for (const name of unrestricted) actions.delete(name);
  return { names: [...new Set(entries.map(entry => entry.split(":")[0]))], actions };
}

export function allowsScopedCall(scopes, resolved, original) {
  const args = resolved.arguments;
  const known = SCOPABLE.get(resolved.name);
  if (known && Object.hasOwn(args, "action") &&
      (resolved.name === "terminal_interact" || !known.includes(args.action))) return false;
  const choices = scopes?.get(resolved.name);
  if (!choices) return true;
  // terminal_interact has no backend action field. Only the validated public
  // terminal family supplies this explicit action; the legacy alias stays denied.
  if (resolved.name === "terminal_interact")
    return original.name === "terminal" && original.arguments.action === "interact" &&
      choices.has("interact");
  return Object.hasOwn(args, "action") && choices.has(args.action);
}
