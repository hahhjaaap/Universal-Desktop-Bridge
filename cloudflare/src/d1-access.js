// Staging-only D1 grant bridge. The Cloudflare Access JWT (including
// signature, issuer, audience, expiry and UUID subject) is verified first.
// No legacy email/JSON grants, fallback, or implicit owner permission.
import { verifiedAccessPrincipal } from "./access.js";
import { authorizedDeviceReadToolsByPrincipal } from "./tenant-store.js";
import { READ_TOOLS } from "./read-tools.js";
import { AuthError } from "./oauth.js";

const READ_CATALOG = new Set(READ_TOOLS);

export async function authorizeD1Read(access, env, deviceId, request, fetchImpl = fetch) {
  if (env?.UDB_TENANT_D1_AUTH !== "true" ||
      env?.UDB_AUTH_MODE !== "cloudflare-access" ||
      env?.UDB_ACCESS_PRINCIPAL_MODE !== "issuer-sub" ||
      !env?.UDB_TENANT_DB?.prepare)
    throw new AuthError();
  const identity = await verifiedAccessPrincipal(access, env, request, fetchImpl);
  const allowTools = await authorizedDeviceReadToolsByPrincipal(env.UDB_TENANT_DB, {
    deviceId, identity, catalogNames: READ_CATALOG,
  });
  if (!allowTools.length) throw new AuthError();
  return { subject: identity.issuer + "#" + identity.subject, allowTools };
}
