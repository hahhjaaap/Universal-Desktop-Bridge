// Cloudflare Access Managed OAuth authenticates the client at the edge.
// An authenticated Worker invocation may provide ctx.access; on other supported
// paths Cloudflare forwards a signed Cf-Access-Jwt-Assertion to the origin.
// Never use an unverified header, opaque OAuth token, cookie or email as identity.
import { AuthError, deviceGrant } from "./oauth.js";
import { ownerToolGrant } from "./owner-tools.js";

const MAX_ASSERTION = 8192;
const MAX_JWKS = 16384;
const TEAM = /^https:\/\/[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.cloudflareaccess\.com$/;
let cachedJwks = { url: "", until: 0, keys: [] };

export function accessConfig(env) {
  const aud = env?.UDB_ACCESS_AUD;
  if (typeof aud !== "string" || aud.length < 12 || aud.length > 256 ||
      aud.trim() !== aud) return null;
  const team = env?.UDB_ACCESS_TEAM_DOMAIN;
  // ctx.access alone does not need JWKS. Signed-header verification, however,
  // is impossible unless the configured team domain is pinned.
  if (team !== undefined && (typeof team !== "string" || !TEAM.test(team)))
    return null;
  return { aud, team: team || null };
}

function decode(segment) {
  if (typeof segment !== "string" || !segment || !/^[A-Za-z0-9_-]+$/.test(segment))
    throw new AuthError();
  try {
    const ascii = atob(segment.replace(/-/g, "+").replace(/_/g, "/")
      .padEnd(Math.ceil(segment.length / 4) * 4, "="));
    return Uint8Array.from(ascii, (c) => c.charCodeAt(0));
  } catch { throw new AuthError(); }
}

function claims(segment) {
  try {
    const obj = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(decode(segment)));
    if (!obj || typeof obj !== "object" || Array.isArray(obj)) throw new Error();
    return obj;
  } catch { throw new AuthError(); }
}

async function getKeys(url, fetchImpl) {
  if (cachedJwks.url === url && Date.now() < cachedJwks.until)
    return cachedJwks.keys;
  let response;
  try {
    response = await fetchImpl(url, { redirect: "error", signal: AbortSignal.timeout(3000),
      headers: { accept: "application/json" } });
    if (response.status !== 200 ||
        !response.headers.get("content-type")?.includes("application/json"))
      throw new Error();
    const reader = response.body?.getReader();
    if (!reader) throw new Error();
    const chunks = [];
    let size = 0;
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > MAX_JWKS) throw new Error();
        chunks.push(value);
      }
    } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    const parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
    if (!Array.isArray(parsed?.keys) || parsed.keys.length > 16) throw new Error();
    cachedJwks = { url, until: Date.now() + 30000, keys: parsed.keys };
    return parsed.keys;
  } catch { throw new AuthError(); }
}

function emailSubject(subject) {
  return typeof subject === "string" && subject.length >= 3 &&
    subject.length <= 200 && subject.includes("@");
}

// This function does not trust a client-supplied header. The header must be a
// valid RS256 JWT signed by the pinned Cloudflare Access team signing key.
export async function verifyAccessAssertion(request, env, fetchImpl = fetch) {
  const config = accessConfig(env);
  if (!config?.team) throw new AuthError();
  const token = request?.headers?.get("Cf-Access-Jwt-Assertion") || "";
  if (token.length > MAX_ASSERTION || token.split(".").length !== 3)
    throw new AuthError();
  const parts = token.split(".");
  const head = claims(parts[0]);
  const payload = claims(parts[1]);
  const now = Math.floor(Date.now() / 1000);
  if (head.alg !== "RS256" || !head.kid || typeof head.kid !== "string" ||
      head.kid.length > 128 || head.crit !== undefined ||
      payload.iss !== config.team ||
      !(payload.aud === config.aud ||
        (Array.isArray(payload.aud) && payload.aud.includes(config.aud))) ||
      !Number.isSafeInteger(payload.exp) || payload.exp <= now ||
      (payload.nbf !== undefined &&
        (!Number.isSafeInteger(payload.nbf) || payload.nbf > now + 60)) ||
      (payload.iat !== undefined &&
        (!Number.isSafeInteger(payload.iat) || payload.iat > now + 60)) ||
      !emailSubject(payload.email)) throw new AuthError();
  const url = config.team + "/cdn-cgi/access/certs";
  const keys = await getKeys(url, fetchImpl);
  const match = keys.filter((key) => key && key.kid === head.kid &&
    key.kty === "RSA" && (key.alg === undefined || key.alg === "RS256") &&
    (key.use === undefined || key.use === "sig") &&
    typeof key.n === "string" && typeof key.e === "string");
  if (match.length !== 1) throw new AuthError();
  let valid = false;
  try {
    const key = await crypto.subtle.importKey("jwk", match[0],
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
    valid = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, decode(parts[2]),
      new TextEncoder().encode(parts[0] + "." + parts[1]));
  } catch { throw new AuthError(); }
  if (!valid) throw new AuthError();
  return payload.email;
}

export async function authorizeAccess(access, env, deviceId, request = null,
    fetchImpl = fetch) {
  const cfg = accessConfig(env);
  if (!cfg) throw new AuthError();
  let subject = null;
  if (access) {
    // A conflicting runtime app audience must not be silently bypassed using
    // a different header, even if the latter carries a valid signed assertion.
    if (access.aud !== cfg.aud) throw new AuthError();
    try {
      if (typeof access.getIdentity === "function") {
        const identity = await access.getIdentity();
        if (emailSubject(identity?.email)) subject = identity.email;
      }
    } catch { /* WARP/runtime identity may be unavailable: verify signed header */ }
  }
  if (!subject) subject = await verifyAccessAssertion(request, env, fetchImpl);
  const readTools = deviceGrant(env, deviceId, subject);
  // Owner tools never replace the independently granted read identity.
  if (readTools.length === 0) throw new AuthError();
  const ownerTools = ownerToolGrant(env, deviceId, subject);
  // Preserve the legacy read-only authorization response exactly when the
  // opt-in profile is absent; existing Access integrations remain unchanged.
  return ownerTools.length
    ? { subject, allowTools: [...readTools, ...ownerTools], ownerTools }
    : { subject, allowTools: readTools };
}
