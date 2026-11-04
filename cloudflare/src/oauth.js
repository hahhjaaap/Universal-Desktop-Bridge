// Fail-closed OAuth resource-server validation for the optional UDB MCP gateway.
// The OAuth authorization-code + PKCE flow is owned by the configured external IdP.
// This module never issues tokens or substitutes an admin/device key for user identity.
import { READ_TOOLS, isReadTool } from "./read-tools.js";
const ID = /^[a-f0-9]{32}$/;
// Strictly project-scoped read-only tools. Writes, host operations, desktop
// control and legacy aliases are never permitted by the udb:read scope.
// The owner's per-device/per-subject UDB_DEVICE_GRANTS must still name each tool.
const MAX_TOKEN = 8192;
const MAX_JWKS = 16384;
let cachedJwks = { url: "", until: 0, keys: [] };

export class AuthError extends Error {
  constructor(reason = "access_denied") {
    super(reason);
    this.name = "AuthError";
  }
}

function originUrl(value) {
  if (typeof value !== "string" || value.length > 500 || value.trim() !== value) return null;
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "https:" || parsed.username || parsed.password ||
        parsed.search || parsed.hash) return null;
    return parsed;
  } catch { return null; }
}

export function oauthConfig(env) {
  const issuer = originUrl(env?.UDB_OAUTH_ISSUER);
  const jwks = originUrl(env?.UDB_OAUTH_JWKS_URL);
  if (!issuer || !jwks || issuer.hostname !== jwks.hostname) return null;
  // RFC 8414 issuer identifiers are compared verbatim. For example Auth0
  // requires a trailing slash; silently stripping it invalidates signed JWTs.
  // Reject URL normalization surprises instead of changing the issuer identity.
  if (env.UDB_OAUTH_ISSUER !== issuer.href &&
      env.UDB_OAUTH_ISSUER !== issuer.origin) return null;
  return { issuer: env.UDB_OAUTH_ISSUER, jwksUrl: jwks.href };
}

function decode(segment) {
  if (typeof segment !== "string" || !/^[A-Za-z0-9_-]+$/.test(segment)) throw new AuthError();
  const ascii = atob(segment.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(segment.length / 4) * 4, "="));
  return Uint8Array.from(ascii, (x) => x.charCodeAt(0));
}

function jsonPart(segment) {
  try {
    const data = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(decode(segment)));
    if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error();
    return data;
  } catch { throw new AuthError(); }
}

async function boundedJwks(url, fetchImpl) {
  if (cachedJwks.url === url && Date.now() < cachedJwks.until) return cachedJwks.keys;
  let response;
  try {
    response = await fetchImpl(url, { redirect: "error", signal: AbortSignal.timeout(3000),
      headers: { accept: "application/json" } });
    if (response.status !== 200 || !response.headers.get("content-type")?.includes("application/json")) throw new Error();
    const reader = response.body?.getReader();
    if (!reader) throw new Error();
    const chunks = [];
    let total = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        total += value.byteLength;
        if (total > MAX_JWKS) throw new Error();
        chunks.push(value);
      }
    } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
    const buffer = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) { buffer.set(chunk, offset); offset += chunk.length; }
    const parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(buffer));
    if (!Array.isArray(parsed?.keys) || parsed.keys.length > 16) throw new Error();
    cachedJwks = { url, until: Date.now() + 30000, keys: parsed.keys };
    return parsed.keys;
  } catch { throw new AuthError(); }
}

export function deviceGrant(env, deviceId, subject) {
  if (!ID.test(deviceId) || typeof subject !== "string" || !subject || subject.length > 200)
    return [];
  const raw = env?.UDB_DEVICE_GRANTS;
  if (typeof raw !== "string" || raw.length > 16384) return [];
  try {
    const config = JSON.parse(raw);
    if (!config || typeof config !== "object" || Array.isArray(config) ||
        !Object.hasOwn(config, deviceId)) return [];
    const users = config[deviceId];
    if (!users || typeof users !== "object" || Array.isArray(users) ||
        !Object.hasOwn(users, subject)) return [];
    const tools = users[subject];
    if (!Array.isArray(tools) || tools.length > READ_TOOLS.length) return [];
    return [...new Set(tools.filter((name) => typeof name === "string" && isReadTool(name)))];
  } catch { return []; }
}

export async function authorize(request, env, deviceId, fetchImpl = fetch) {
  const config = oauthConfig(env);
  if (!config) throw new AuthError();
  const header = request.headers.get("Authorization") || "";
  if (!/^Bearer [A-Za-z0-9_.-]+$/.test(header)) throw new AuthError();
  const token = header.slice(7);
  if (token.length > MAX_TOKEN) throw new AuthError();
  const parts = token.split(".");
  if (parts.length !== 3) throw new AuthError();
  const head = jsonPart(parts[0]);
  const payload = jsonPart(parts[1]);
  if (head.alg !== "RS256" || typeof head.kid !== "string" || head.kid.length > 128 ||
      head.crit !== undefined) throw new AuthError();
  const target = new URL(request.url);
  const audience = target.origin + target.pathname;
  const now = Math.floor(Date.now() / 1000);
  if (payload.iss !== config.issuer ||
      !(payload.aud === audience || (Array.isArray(payload.aud) && payload.aud.includes(audience))) ||
      typeof payload.sub !== "string" || payload.sub.length < 1 || payload.sub.length > 200 ||
      !Number.isSafeInteger(payload.exp) || payload.exp <= now || payload.exp > now + 3600 ||
      (payload.nbf !== undefined && (!Number.isSafeInteger(payload.nbf) || payload.nbf > now + 60)) ||
      (payload.iat !== undefined && (!Number.isSafeInteger(payload.iat) || payload.iat > now + 60)))
    throw new AuthError();
  const scopes = typeof payload.scope === "string" ? payload.scope.split(" ") : [];
  if (!scopes.includes("udb:read")) throw new AuthError();
  const keys = await boundedJwks(config.jwksUrl, fetchImpl);
  const match = keys.filter((k) => k?.kid === head.kid && k.kty === "RSA" &&
    (k.alg === undefined || k.alg === "RS256") &&
    (k.use === undefined || k.use === "sig") &&
    typeof k.n === "string" && typeof k.e === "string");
  if (match.length !== 1) throw new AuthError();
  let verified = false;
  try {
    const key = await crypto.subtle.importKey("jwk", match[0],
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
    verified = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, decode(parts[2]),
      new TextEncoder().encode(parts[0] + "." + parts[1]));
  } catch { throw new AuthError(); }
  if (!verified) throw new AuthError();
  const allowTools = deviceGrant(env, deviceId, payload.sub);
  if (allowTools.length === 0) throw new AuthError();
  return { subject: payload.sub, allowTools };
}
