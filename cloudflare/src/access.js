// Cloudflare Access Managed OAuth authenticates the client at the edge.
// An authenticated Worker invocation may provide ctx.access; on other supported
// paths Cloudflare forwards a signed Cf-Access-Jwt-Assertion to the origin.
// Never use an unverified header, opaque OAuth token, cookie or email as identity.
import { AuthError, deviceGrant } from "./oauth.js";
import { ownerToolGrant } from "./owner-tools.js";
import { companionToolGrant } from "./companion-tools.js";
import { READ_TOOLS } from "./read-tools.js";

const MAX_ASSERTION = 8192;
const MAX_JWKS = 16384;
const TEAM = /^https:\/\/[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.cloudflareaccess\.com$/;
// Access app-token sub is an account-scoped user UUID, not an email.
const ACCESS_SUB = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
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
  let stage = "fetch";
  try {
    response = await fetchImpl(url, { redirect: "error", signal: AbortSignal.timeout(3000),
      headers: { accept: "application/json" } });
    stage = "response";
    if (response.status !== 200 ||
        !response.headers.get("content-type")?.includes("application/json"))
      throw new Error();
    const reader = response.body?.getReader();
    if (!reader) throw new Error();
    stage = "body";
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
    stage = "json";
    const parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
    if (!Array.isArray(parsed?.keys) || parsed.keys.length > 16) throw new Error();
    cachedJwks = { url, until: Date.now() + 30000, keys: parsed.keys };
    return parsed.keys;
  } catch (error) {
    console.warn(JSON.stringify({ event: "udb_access_keys_unavailable", stage,
      response_status: response?.status ?? null,
      response_json: Boolean(response?.headers.get("content-type")?.includes("application/json")),
      timed_out: error?.name === "TimeoutError" || error?.name === "AbortError" }));
    throw new AuthError("access_keys_unavailable");
  }
}

function emailSubject(subject) {
  return typeof subject === "string" && subject.length >= 3 &&
    subject.length <= 200 && subject.includes("@");
}

// This function does not trust a client-supplied header. The header must be a
// valid RS256 JWT signed by the pinned Cloudflare Access team signing key.
export async function verifiedAccessIdentity(request, env, fetchImpl = fetch) {
  const config = accessConfig(env);
  if (!config?.team) throw new AuthError();
  const token = request?.headers?.get("Cf-Access-Jwt-Assertion") || "";
  if (token.length > MAX_ASSERTION || token.split(".").length !== 3)
    throw new AuthError("access_assertion_malformed");
  const parts = token.split(".");
  let head, payload;
  try { head = claims(parts[0]); payload = claims(parts[1]); }
  catch { throw new AuthError("access_assertion_malformed"); }
  const now = Math.floor(Date.now() / 1000);
  if (head.alg !== "RS256" || !head.kid || typeof head.kid !== "string" ||
      head.kid.length > 128 || head.crit !== undefined)
    throw new AuthError("access_assertion_algorithm");
  if (payload.iss !== config.team) throw new AuthError("access_assertion_issuer");
  if (!(payload.aud === config.aud ||
      (Array.isArray(payload.aud) && payload.aud.includes(config.aud))))
    throw new AuthError("access_assertion_audience");
  if (!Number.isSafeInteger(payload.exp) || payload.exp <= now ||
      (payload.nbf !== undefined &&
        (!Number.isSafeInteger(payload.nbf) || payload.nbf > now + 60)) ||
      (payload.iat !== undefined &&
        (!Number.isSafeInteger(payload.iat) || payload.iat > now + 60)))
    throw new AuthError("access_assertion_time");
  if (!emailSubject(payload.email)) throw new AuthError("access_assertion_identity");
  const url = config.team + "/cdn-cgi/access/certs";
  const keys = await getKeys(url, fetchImpl);
  const match = keys.filter((key) => key && key.kid === head.kid &&
    key.kty === "RSA" && (key.alg === undefined || key.alg === "RS256") &&
    (key.use === undefined || key.use === "sig") &&
    typeof key.n === "string" && typeof key.e === "string");
  if (match.length !== 1) throw new AuthError("access_assertion_key");
  let valid = false;
  try {
    const key = await crypto.subtle.importKey("jwk", match[0],
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
    valid = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, decode(parts[2]),
      new TextEncoder().encode(parts[0] + "." + parts[1]));
  } catch { throw new AuthError("access_assertion_signature"); }
  if (!valid) throw new AuthError("access_assertion_signature");
  return { email: payload.email, sub: payload.sub };
}

// Preserve the legacy public API for integrations using email grants.
export async function verifyAccessAssertion(request, env, fetchImpl = fetch) {
  const identity = await verifiedAccessIdentity(request, env, fetchImpl);
  return identity.email;
}

export async function authorizeAccess(access, env, deviceId, request = null,
    fetchImpl = fetch, enrolledGrant = null) {
  const cfg = accessConfig(env);
  if (!cfg) throw new AuthError();
  const mode = env?.UDB_ACCESS_PRINCIPAL_MODE === undefined
    ? "email" : env.UDB_ACCESS_PRINCIPAL_MODE;
  // An unknown identity mode must never silently fall back to email grants.
  if (mode !== "email" && mode !== "issuer-sub") throw new AuthError();
  // A conflicting runtime app audience cannot be bypassed by a signed JWT.
  if (access && access.aud !== cfg.aud) throw new AuthError("access_audience_mismatch");

  let subject = null;
  let runtimeIdentity = null;
  if (mode === "issuer-sub") {
    // Opt-in staging pilot: require the signed assertion even when ctx.access
    // supplies a valid email. The authenticated issuer + account-scoped sub
    // must match an explicit grant; email and legacy grants never substitute.
    if (!cfg.team) throw new AuthError();
    const identity = await verifiedAccessIdentity(request, env, fetchImpl);
    if (typeof identity.sub !== "string" || !ACCESS_SUB.test(identity.sub))
      throw new AuthError();
    // If the Access runtime separately exposes an identity, it must not
    // disagree with the signed assertion. WARP may expose only aud; in that
    // case the signature remains the sole source of user identity.
    if (typeof access?.getIdentity === "function") {
      let observed = null;
      try { observed = await access.getIdentity(); }
      catch { /* Optional runtime identity unavailable; signed JWT required. */ }
      if (observed) {
        if ((emailSubject(observed.email) && observed.email !== identity.email) ||
            (typeof observed.user_uuid === "string" &&
              observed.user_uuid.toLowerCase() !== identity.sub.toLowerCase()))
          throw new AuthError();
      }
    }
    subject = cfg.team + "#" + identity.sub.toLowerCase();
  } else {
    if (access) {
      try {
        if (typeof access.getIdentity === "function") {
          const identity = await access.getIdentity();
          if (emailSubject(identity?.email)) {
            subject = identity.email;
            runtimeIdentity = identity;
          }
        }
      } catch { /* WARP/runtime identity may be unavailable: verify signed header */ }
    }
    if (!subject) {
      // A bearer token is not a trusted user identity at the Worker. Only
      // Cloudflare Access runtime identity or a verified signed assertion is.
      if (!request?.headers?.get("Cf-Access-Jwt-Assertion"))
        throw new AuthError("verified_identity_missing");
      subject = await verifyAccessAssertion(request, env, fetchImpl);
    }
  }
  let readTools = deviceGrant(env, deviceId, subject);
  let enrolledStatusOnly = false;
  let stagingFixtureProject;
  const fixtureGrant = env?.UDB_STAGING_FIXTURE_READ_GRANT;
  if (readTools.length === 0 && mode === "email" &&
      env?.UDB_TENANT_POLICY === undefined &&
      typeof fixtureGrant === "string" && fixtureGrant.length <= 1024) {
    let grant;
    try { grant = JSON.parse(fixtureGrant); } catch { /* Malformed grant denies access. */ }
    if (/^[a-f0-9]{32}$/.test(deviceId) && grant?.device_id === deviceId &&
        grant.subject === subject && grant.project === "udb-staging-fixture") {
      readTools = READ_TOOLS;
      stagingFixtureProject = grant.project;
    }
  }
  // Owner tools never replace the independently granted read identity.
  if (readTools.length === 0 && enrolledGrant && env.UDB_TENANT_POLICY === undefined) {
    try {
      let verified;
      if (mode === "email" && runtimeIdentity) {
        // Native Access is already authenticated. Bind the dynamic grant to
        // its account UUID, never to email or an overriding request header.
        if (!cfg.team || typeof runtimeIdentity.user_uuid !== "string" ||
            !ACCESS_SUB.test(runtimeIdentity.user_uuid)) throw new AuthError();
        verified = { email: runtimeIdentity.email, sub: runtimeIdentity.user_uuid };
      } else verified = await verifiedAccessIdentity(request, env, fetchImpl);
      if (verified.email !== (mode === "email" ? subject : verified.email))
        throw new AuthError();
      readTools = await enrolledGrant(verified);
      enrolledStatusOnly = readTools.length === 1 && readTools[0] === "bridge_status";
    } catch { readTools = []; }
  }
  if (readTools.length === 0) throw new AuthError("device_grant_missing");
  const ownerTools = enrolledStatusOnly ? [] : [
    ...ownerToolGrant(env, deviceId, subject),
    ...companionToolGrant(env, deviceId, subject),
  ];
  // Preserve the legacy read-only authorization response exactly when the
  // opt-in profile is absent; existing Access integrations remain unchanged.
  const readScope = stagingFixtureProject ? { stagingFixtureProject } : {};
  return ownerTools.length
    ? { subject, allowTools: [...readTools, ...ownerTools], ownerTools, ...readScope }
    : { subject, allowTools: readTools, ...readScope };
}
