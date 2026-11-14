// Separate Access application and immutable issuer/sub allowlist for approvals.
import { accessConfig, verifiedAccessIdentity } from "./access.js";
import { AuthError } from "./oauth.js";

const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
export function stableAccessSubject(identity, team) {
  return team && typeof identity?.sub === "string" && UUID.test(identity.sub)
    ? team + "#" + identity.sub.toLowerCase() : null;
}
export function ownerEnrollmentConfig(env) {
  if (env.UDB_ENABLE_BROWSER_ENROLLMENT !== "true") return null;
  const config = accessConfig({ ...env, UDB_ACCESS_AUD: env.UDB_ENROLLMENT_ACCESS_AUD });
  const raw = env.UDB_ENROLLMENT_OWNER_SUBJECTS;
  if (!config?.team || typeof raw !== "string" || raw.length > 8192) return null;
  try {
    const owners = JSON.parse(raw);
    if (!Array.isArray(owners) || !owners.length || owners.length > 20 ||
        new Set(owners).size !== owners.length || !owners.every(subject =>
          typeof subject === "string" && subject.startsWith(config.team + "#") &&
          UUID.test(subject.slice(config.team.length + 1)))) return null;
    return { ...config, owners: owners.map(subject => subject.toLowerCase()) };
  } catch { return null; }
}
export async function authorizeEnrollmentOwner(request, env, fetchImpl = fetch, access = null) {
  const config = ownerEnrollmentConfig(env);
  if (!config) throw new AuthError();
  // Only the Worker invocation context supplies this trusted object. Never
  // construct it from headers, cookies or request JSON. MCP uses a different app.
  if (access && access.aud !== config.aud) throw new AuthError();
  let observed = null;
  if (typeof access?.getIdentity === "function") {
    try { observed = await access.getIdentity(); }
    catch { throw new AuthError(); }
  }
  let identity;
  if (request.headers.has("Cf-Access-Jwt-Assertion")) {
    // A present but invalid assertion must not fall back to runtime identity.
    identity = await verifiedAccessIdentity(request, {
      ...env, UDB_ACCESS_AUD: config.aud,
    }, fetchImpl);
    if (observed && ((typeof observed.email === "string" && observed.email !== identity.email) ||
        (typeof observed.user_uuid === "string" &&
          observed.user_uuid.toLowerCase() !== identity.sub?.toLowerCase()))) throw new AuthError();
  } else {
    // Workers can authenticate browser requests without forwarding an assertion.
    // The account-scoped UUID, not email or the global identity id, binds ownership.
    identity = { sub: observed?.user_uuid };
  }
  const subject = stableAccessSubject(identity, config.team);
  if (!subject || !config.owners.includes(subject.toLowerCase())) throw new AuthError();
  return subject;
}
