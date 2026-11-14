// Device diagnostics are NOT user OAuth. Proof comes only from authenticated MCP.
import { bearer, digest, fixedEqual, HASH, readJson } from "./auth.js";
import { stableAccessSubject } from "./enrollment-owner.js";

const json = (value, status = 200) => Response.json(value, { status,
  headers: { "cache-control": "no-store", "x-content-type-options": "nosniff" } });
const CHALLENGE_MS = 30 * 60 * 1000, PROOF_MS = 5 * 60 * 1000;
export async function routeDeviceSetup(request, env, forward) {
  const m = /^\/v1\/devices\/([a-f0-9]{32})\/setup\/(status|challenge)$/.exec(new URL(request.url).pathname);
  if (!m) return null;
  if (request.headers.has("Origin")) return json({ error: "browser_origin_not_supported" }, 403);
  if (!((m[2] === "status" && request.method === "GET") ||
        (m[2] === "challenge" && request.method === "POST")))
    return json({ error: "method_not_allowed" }, 405);
  const stub = env.DEVICES.get(env.DEVICES.idFromName(m[1]));
  return forward(stub, new Request("https://internal/setup/" + m[2], request));
}
export async function handleDeviceSetup(request, ctx) {
  const path = new URL(request.url).pathname, store = ctx.storage;
  if (path === "/setup/owner-grant" && request.method === "GET") {
    const subject = request.headers.get("X-UDB-Subject");
    return store.transaction(async txn => json({ allowTools:
      subject && subject === await txn.get("enrollment_owner") &&
      await txn.get("device_token_sha256") && !(await txn.get("enrollment_revoked"))
        ? ["bridge_status"] : [] }));
  }
  if (path === "/setup/record-proof" && request.method === "POST") {
    const b = await readJson(request);
    return store.transaction(async txn => {
      const tokenHash = await txn.get("device_token_sha256"), challenge = await txn.get("setup_challenge");
      if (!tokenHash || !challenge || challenge.expires <= Date.now() ||
          typeof b.subject !== "string" || b.subject.length > 500 ||
          !["bridge_status", "tools/list+bridge_status"].includes(b.method))
        return json({ recorded: false });
      await txn.put("setup_proof", { at: Date.now(), challenge: challenge.hash,
        tokenHash, method: b.method });
      return json({ recorded: true });
    });
  }
  const token = bearer(request);
  if (!token) return json({ error: "device_auth_failed" }, 403);
  const tokenHash = await digest(token);
  const body = path === "/setup/challenge" && request.method === "POST" ? await readJson(request) : null;
  return store.transaction(async txn => {
    const expected = await txn.get("device_token_sha256");
    if (!expected || !fixedEqual(tokenHash, expected)) return json({ error: "device_auth_failed" }, 403);
    if (body) {
      if (!HASH.test(body.challenge_sha256)) return json({ error: "invalid_challenge" }, 400);
      const old = await txn.get("setup_challenge");
      if (old?.hash !== body.challenge_sha256 || old.expires <= Date.now()) {
        await txn.put("setup_challenge", { hash: body.challenge_sha256, expires: Date.now() + CHALLENGE_MS });
        await txn.delete("setup_proof");
      }
      return json({ challenge_ready: true });
    }
    if (path !== "/setup/status" || request.method !== "GET") return json({ error: "not_found" }, 404);
    const proof = await txn.get("setup_proof"), challenge = await txn.get("setup_challenge");
    const fresh = proof && challenge && proof.challenge === challenge.hash &&
      proof.tokenHash === expected && challenge.expires > Date.now() &&
      proof.at <= Date.now() && Date.now() - proof.at <= PROOF_MS;
    return json({ token_valid: true,
      cloud_agent_online: ctx.getWebSockets("device").some(ws => ws.readyState === 1),
      authenticated_mcp_verified: !!fresh, verified_at: fresh ? proof.at : null,
      verification_method: fresh ? proof.method : null,
      client_attribution: "unavailable", chatgpt_connected: false });
  });
}
export async function enrolledReadGrant(env, stub, identity) {
  if (env.UDB_ENABLE_BROWSER_ENROLLMENT !== "true" || env.UDB_TENANT_POLICY !== undefined) return [];
  const subject = stableAccessSubject(identity, env.UDB_ACCESS_TEAM_DOMAIN);
  if (!subject) return [];
  const r = await stub.fetch(new Request("https://internal/setup/owner-grant", {
    headers: { "X-UDB-Subject": subject },
  }));
  if (!r.ok) return [];
  const b = await r.json();
  return Array.isArray(b.allowTools) && b.allowTools.length === 1 &&
    b.allowTools[0] === "bridge_status" ? b.allowTools : [];
}
export async function recordMcpProof(stub, subject, result, method = "bridge_status") {
  if (result?.isError || !Array.isArray(result?.content) ||
      !result.content.some(b => b?.type === "text")) return;
  try {
    await stub.fetch(new Request("https://internal/setup/record-proof", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subject, method }),
    }));
  } catch { /* Never change or replay a tool call after a diagnostics failure. */ }
}
