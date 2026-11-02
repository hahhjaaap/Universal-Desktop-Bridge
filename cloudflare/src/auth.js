// Only the prototype owner can call admin endpoints. No account OAuth yet.
export const DEVICE_ID = /^[a-f0-9]{32}$/;
export const HASH = /^[a-f0-9]{64}$/;
export const MAX_BODY = 256 * 1024;
export const MAX_SECRET = 256;

export function fixedEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export function bearer(request) {
  const header = request.headers.get("Authorization") || "";
  if (!header.startsWith("Bearer ")) return null;
  const value = header.slice(7);
  return value.length > 0 && value.length <= MAX_SECRET && !/\s/.test(value) ? value : null;
}

export function adminAuthorized(request, env) {
  const token = bearer(request);
  return !!(token && typeof env.UDB_ADMIN_KEY === "string" &&
    env.UDB_ADMIN_KEY.length >= 32 && fixedEqual(token, env.UDB_ADMIN_KEY));
}

export async function digest(value) {
  const bytes = new TextEncoder().encode(value);
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), (v) => v.toString(16).padStart(2, "0")).join("");
}

export async function readJson(request) {
  const size = Number(request.headers.get("Content-Length") || "0");
  if (size > MAX_BODY) throw new Error("body_too_large");
  const text = await request.text();
  if (new TextEncoder().encode(text).length > MAX_BODY) throw new Error("body_too_large");
  const value = JSON.parse(text);
  if (value === null || typeof value !== "object" || Array.isArray(value))
    throw new Error("invalid_json");
  return value;
}

export function validRpc(rpc) {
  if (!rpc || typeof rpc !== "object" || Array.isArray(rpc)) return false;
  if (rpc.jsonrpc !== "2.0" || !["initialize", "ping", "tools/list", "tools/call"].includes(rpc.method))
    return false;
  if (!(typeof rpc.id === "string" || Number.isSafeInteger(rpc.id)) || rpc.id === "") return false;
  if (rpc.params !== undefined && (rpc.params === null || typeof rpc.params !== "object" ||
      Array.isArray(rpc.params))) return false;
  if (rpc.method === "tools/call" && (!rpc.params || typeof rpc.params.name !== "string" ||
      typeof rpc.params.arguments !== "object" || rpc.params.arguments === null)) return false;
  return true;
}
