import assert from "node:assert/strict";
import { createHash, randomBytes } from "node:crypto";
import test from "node:test";
import worker, { DeviceRelay } from "../src/index.js";
import { routeBrowserEnrollment } from "../src/browser-enrollment.js";
import { handleMcp } from "../src/mcp.js";

const ROOT = "https://setup-test.workers.dev";
const TEAM = "https://setup-test.cloudflareaccess.com";
const OWNER = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";
const APP = "setup-approval-application-audience";
const MCP = "setup-mcp-application-audience";
const ADMIN = "synthetic-admin-" + "a".repeat(40);
const hash = s => createHash("sha256").update(s).digest("hex");
const b64 = s => Buffer.from(s).toString("base64url");
const pairPromise = crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5",
  modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
true, ["sign", "verify"]);
async function jwt(audience = APP, subject = OWNER, overrides = {}) {
  const pair = await pairPromise, now = Math.floor(Date.now() / 1000);
  const unsigned = b64(JSON.stringify({ alg: "RS256", kid: "setup-test-key" })) + "." +
    b64(JSON.stringify({ iss: TEAM, aud: [audience], exp: now + 300, iat: now,
      sub: subject, email: "synthetic-owner@example.test", ...overrides }));
  return unsigned + "." + b64(await crypto.subtle.sign("RSASSA-PKCS1-v1_5",
    pair.privateKey, new TextEncoder().encode(unsigned)));
}
async function keys() {
  const pair = await pairPromise;
  return Response.json({ keys: [{ ...await crypto.subtle.exportKey("jwk", pair.publicKey),
    kid: "setup-test-key" }] });
}
function fixture() {
  const objects = new Map();
  const f = { objects, online: true, failAfterRegister: false, probes: 0, toolError: false };
  const env = f.env = {
    UDB_AUTH_MODE: "cloudflare-access", UDB_ACCESS_AUD: MCP, UDB_ACCESS_TEAM_DOMAIN: TEAM,
    UDB_ENABLE_PRIVATE_ENROLLMENT: "true", UDB_ENABLE_BROWSER_ENROLLMENT: "true",
    UDB_ADMIN_KEY: ADMIN, UDB_ENROLLMENT_ACCESS_AUD: APP,
    UDB_ENROLLMENT_OWNER_SUBJECTS: JSON.stringify([TEAM + "#" + OWNER]),
    DEVICES: {
      idFromName: id => id,
      get(id) {
        if (!objects.has(id)) {
          const values = new Map();
          let queue = Promise.resolve();
          const store = {
            async get(k) { return structuredClone(values.get(k)); },
            async put(k, v) {
              for (const [key, val] of typeof k === "object" ? Object.entries(k) : [[k, v]])
                values.set(key, structuredClone(val));
            },
            async delete(keys) {
              for (const k of Array.isArray(keys) ? keys : [keys]) values.delete(k);
            },
            transaction(fn) {
              const pending = queue.then(() => fn(store));
              queue = pending.catch(() => {});
              return pending;
            },
          };
          const ctx = { storage: store, getWebSockets: () => f.online ? [{ readyState: 1, close() {} }] : [] };
          objects.set(id, { values, ctx, relay: new DeviceRelay(ctx, env) });
        }
        return { async fetch(request) {
          const path = new URL(request.url).pathname;
          if (path === "/rpc") {
            if (!f.online) return Response.json({ error: "device_offline" }, { status: 503 });
            const rpc = await request.json();
            const result = rpc.method === "tools/list" ? { tools: [{ name: "bridge_status", inputSchema: { type: "object" } }] } :
              { content: [{ type: "text", text: "synthetic Windows status" }], isError: f.toolError };
            if (rpc.method === "tools/call") f.probes++;
            return Response.json({ jsonrpc: "2.0", id: rpc.id, result });
          }
          const response = await objects.get(id).relay.fetch(request);
          if (path === "/setup-register" && f.failAfterRegister) {
            f.failAfterRegister = false;
            throw new Error("Synthetic lost registration reply");
          }
          return response;
        } };
      },
    },
  };
  f.route = async (path, method = "GET", body, headers = {}, access = null) => {
    const request = new Request(ROOT + path, { method, headers,
      body: body === undefined ? undefined : typeof body === "string" ? body : JSON.stringify(body) });
    return await routeBrowserEnrollment(request, env, (stub, req) => stub.fetch(req), keys, access) ??
      worker.fetch(request, env);
  };
  return f;
}
async function begin(f) {
  const id = randomBytes(16).toString("hex"), proof = randomBytes(32).toString("hex"),
    token = randomBytes(48).toString("base64url");
  const data = { request_id: id, request_secret_sha256: hash(proof),
    device_token_sha256: hash(token), device_name: "Synthetic Windows" };
  const response = await f.route("/v1/setup/enrollments", "POST", data);
  assert.equal(response.status, 201);
  return { id, proof, token, data, path: "/v1/setup/enrollments/" + id };
}
async function review(f, p, assertion = null) {
  const response = await f.route(p.path + "/approval?code=" + hash(p.proof).slice(0, 10).toUpperCase(),
    "GET", undefined, { "Cf-Access-Jwt-Assertion": assertion || await jwt() });
  const html = await response.text();
  return { response, html, csrf: /name=csrf value='([a-f0-9]{64})'/.exec(html)?.[1] };
}
async function decide(f, p, csrf, action = "approve", assertion = null, extras = {}) {
  return f.route(p.path + "/approval", "POST",
    new URLSearchParams({ csrf, action, status_only: "yes" }).toString(), {
      "Cf-Access-Jwt-Assertion": assertion || await jwt(),
      "Content-Type": "application/x-www-form-urlencoded", Origin: ROOT, ...extras });
}
async function status(f, p, proof = p.proof) {
  return f.route(p.path + "/status", "GET", undefined, { Authorization: "Bearer " + proof });
}
async function deviceStatus(f, p, token = p.token) {
  return worker.fetch(new Request(ROOT + "/v1/devices/" + p.id + "/setup/status", {
    headers: { Authorization: "Bearer " + token },
  }), f.env);
}
async function approve(f, p) {
  const r = await review(f, p);
  assert.equal(r.response.status, 200); assert.ok(r.csrf);
  return decide(f, p, r.csrf);
}
async function mcp(f, p, assertion, method = "tools/list", params = {}) {
  return handleMcp(new Request(ROOT + "/v1/devices/" + p.id + "/mcp", {
    method: "POST", headers: { "Cf-Access-Jwt-Assertion": assertion,
      "Content-Type": "application/json", "MCP-Protocol-Version": "2025-11-25" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
  }), f.env, p.id, f.env.DEVICES.get(p.id), keys);
}

test("browser enrollment is opt-in and requires separate pinned owner application", async () => {
  for (const mutate of [
    env => delete env.UDB_ENABLE_BROWSER_ENROLLMENT,
    env => env.UDB_ENROLLMENT_ACCESS_AUD = MCP,
    env => env.UDB_ACCESS_AUD = "",
    env => env.UDB_ENROLLMENT_OWNER_SUBJECTS = '["owner@example.test"]',
    env => env.UDB_TENANT_POLICY = "{}",
    env => delete env.UDB_ACCESS_TEAM_DOMAIN,
  ]) {
    const f = fixture(); mutate(f.env);
    assert.equal((await (await f.route("/v1/setup")).json()).browser_enrollment, false);
    assert.equal((await f.route("/v1/setup/enrollments", "POST", {})).status, 404);
    assert.equal(f.objects.size, 0);
  }
});

test("lost POST response and process restart reuse identical identity and do not consume rate twice", async () => {
  const f = fixture(), p = await begin(f);
  for (let i = 0; i < 8; i++) {
    const r = await f.route("/v1/setup/enrollments", "POST", p.data);
    assert.equal(r.status, 201);
    assert.equal((await r.json()).device_id, p.id);
  }
  const hub = f.objects.get("__udb_browser_enrollment_v2__");
  assert.equal(hub.values.get("setup_rates").length, 1);
  hub.relay = new DeviceRelay(hub.ctx, f.env);
  assert.equal((await (await status(f, p)).json()).state, "pending");
  assert.equal((await f.route("/v1/setup/enrollments", "POST", { ...p.data, device_token_sha256: hash("different") })).status, 409);
  assert.equal((await status(f, p, "0".repeat(64))).status, 403);
  assert.equal(f.objects.has(p.id), false);
});

test("owner approval rejects missing, forged, expired, other-account and MCP-audience tokens", async () => {
  const f = fixture(), p = await begin(f);
  for (const assertion of [
    "forged", await jwt(MCP), await jwt(APP, OTHER),
    await jwt(APP, OWNER, { exp: 1 }), await jwt(APP, OWNER, { iss: "https://other.cloudflareaccess.com" }),
  ]) {
    assert.equal((await review(f, p, assertion)).response.status, 403);
  }
  const missing = await f.route(p.path + "/approval?code=" + hash(p.proof).slice(0, 10).toUpperCase());
  assert.equal(missing.status, 403);
  assert.equal(f.objects.has(p.id), false);
});

test("approval diagnostics identify the failing verification step without echoing credentials", async () => {
  const f = fixture(), p = await begin(f);
  for (const [assertion, reason] of [
    ["private-invalid-token", "owner_assertion_malformed"],
    [await jwt(MCP), "owner_assertion_audience"],
    [await jwt(APP, OWNER, { iss: "https://other.cloudflareaccess.com" }), "owner_assertion_issuer"],
    [await jwt(APP, OWNER, { exp: 1 }), "owner_assertion_time"],
  ]) {
    const r = await review(f, p, assertion);
    assert.equal(r.response.status, 403);
    assert.ok(r.html.includes(reason));
    assert.ok(!r.html.includes(assertion));
    assert.ok(!r.html.includes("synthetic-owner@example.test"));
  }
  assert.equal(f.objects.has(p.id), false);
});

const runtimeOwner = (user_uuid = OWNER, aud = APP) => ({ aud,
  async getIdentity() { return { user_uuid, email: "synthetic-owner@example.test" }; } });

test("Worker passes trusted Access identity to approval without registering on GET", async () => {
  const f = fixture(), p = await begin(f);
  const request = new Request(ROOT + p.path + "/approval?code=" + hash(p.proof).slice(0, 10).toUpperCase());
  const response = await worker.fetch(request, f.env, { access: runtimeOwner() });
  assert.equal(response.status, 200);
  const csrf = /name=csrf value='([a-f0-9]{64})'/.exec(await response.text())?.[1];
  assert.ok(csrf);
  assert.equal(f.objects.has(p.id), false);
  assert.equal((await (await status(f, p)).json()).state, "pending");
  const consent = new Request(ROOT + p.path + "/approval", { method: "POST",
    headers: { Origin: ROOT, "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ csrf, action: "approve", status_only: "yes" }) });
  assert.equal((await worker.fetch(consent, f.env, { access: runtimeOwner() })).status, 200);
  assert.equal(f.objects.get(p.id).values.get("enrollment_owner"), TEAM + "#" + OWNER);
});

test("runtime approval requires exact application and account UUID, never email or global id", async () => {
  const f = fixture(), p = await begin(f);
  for (const access of [runtimeOwner(OTHER), runtimeOwner(OWNER, MCP), { aud: APP },
    { aud: APP, getIdentity: async () => ({ email: "synthetic-owner@example.test", id: OWNER }) },
    { aud: APP, getIdentity: async () => { throw new Error("unavailable"); } },
  ]) {
    assert.equal((await f.route(p.path + "/approval?code=" + hash(p.proof).slice(0, 10).toUpperCase(),
      "GET", undefined, {}, access)).status, 403);
  }
  assert.equal(f.objects.has(p.id), false);
});

test("invalid assertion or conflicting runtime identity cannot use the other authentication path", async () => {
  const f = fixture(), p = await begin(f);
  for (const [assertion, access] of [
    ["", runtimeOwner()], ["forged", runtimeOwner()],
    [await jwt(APP, OWNER, { exp: 1 }), runtimeOwner()],
    [await jwt(MCP), runtimeOwner()], [await jwt(APP, OTHER), runtimeOwner()],
    [await jwt(), runtimeOwner(OWNER, MCP)], [await jwt(), runtimeOwner(OTHER)],
    [await jwt(), { aud: APP, getIdentity: async () => ({ user_uuid: OWNER, email: "other@example.test" }) }],
  ]) {
    assert.equal((await f.route(p.path + "/approval?code=" + hash(p.proof).slice(0, 10).toUpperCase(),
      "GET", undefined, { "Cf-Access-Jwt-Assertion": assertion }, access)).status, 403);
  }
  assert.equal(f.objects.has(p.id), false);
});

test("client headers cannot inject runtime approval identity", async () => {
  const f = fixture(), p = await begin(f);
  const response = await f.route(p.path + "/approval?code=" + hash(p.proof).slice(0, 10).toUpperCase(),
    "GET", undefined, { "Cf-Access-Authenticated-User-Email": "synthetic-owner@example.test",
      "X-Access-Aud": APP, "X-User-UUID": OWNER, Cookie: "CF_Authorization=forged" });
  assert.equal(response.status, 403);
  assert.equal(f.objects.has(p.id), false);
});

test("approval is CSRF protected, bound to device and owner, single-use and status-only", async () => {
  const f = fixture(), p = await begin(f), other = await begin(f);
  const r = await review(f, p);
  assert.equal(r.response.headers.get("referrer-policy"), "no-referrer");
  assert.match(r.response.headers.get("content-security-policy"), /frame-ancestors 'none'/);
  assert.equal((await decide(f, p, r.csrf, "approve", null, { Origin: "https://evil.invalid" })).status, 403);
  assert.equal((await decide(f, other, r.csrf)).status, 403);
  assert.equal((await decide(f, p, "0".repeat(64))).status, 403);
  assert.equal((await decide(f, p, r.csrf)).status, 200);
  assert.equal((await decide(f, p, r.csrf)).status, 410);
  assert.equal((await (await status(f, p)).json()).state, "approved");
  const device = f.objects.get(p.id).values;
  assert.equal(device.get("device_token_sha256"), hash(p.token));
  assert.equal(device.get("enrollment_owner"), TEAM + "#" + OWNER);
  assert.ok(!JSON.stringify([...device]).includes(p.token));
  const response = await mcp(f, p, await jwt(MCP));
  assert.equal(response.status, 200);
  assert.deepEqual((await response.json()).result.tools.map(t => t.name), ["bridge_status"]);
  assert.equal((await mcp(f, p, await jwt(MCP), "tools/call",
    { name: "computer_execute", arguments: {} })).status, 403);
});

test("approval requires explicit status-only consent and form rejects duplicate fields", async () => {
  const f = fixture(), p = await begin(f), r = await review(f, p);
  for (const body of [
    new URLSearchParams({ csrf: r.csrf, action: "approve" }).toString(),
    "csrf=" + r.csrf + "&action=approve&status_only=yes&action=reject",
  ]) {
    assert.equal((await f.route(p.path + "/approval", "POST", body, {
      "Cf-Access-Jwt-Assertion": await jwt(), Origin: ROOT,
      "Content-Type": "application/x-www-form-urlencoded" })).status, 400);
  }
  assert.equal((await (await status(f, p)).json()).state, "pending");
});

test("owner rejection and approval expiry never register a device", async () => {
  const f = fixture(), p = await begin(f), r = await review(f, p);
  assert.equal((await decide(f, p, r.csrf, "reject")).status, 200);
  assert.equal((await (await status(f, p)).json()).state, "rejected");
  const second = await begin(f);
  const records = f.objects.get("__udb_browser_enrollment_v2__").values.get("setup_enrollments");
  records.find(r => r.id === second.id).expires = Date.now() - 1;
  assert.equal((await status(f, second)).status, 410);
  assert.equal((await review(f, second)).response.status, 410);
  assert.equal(f.objects.has(p.id), false); assert.equal(f.objects.has(second.id), false);
});

test("registration uncertain response is recovered only through exact idempotent operation", async () => {
  const f = fixture(), p = await begin(f);
  f.failAfterRegister = true;
  assert.equal((await approve(f, p)).status, 503);
  const hashBefore = f.objects.get(p.id).values.get("device_token_sha256");
  assert.equal((await (await status(f, p)).json()).state, "approved");
  assert.equal(f.objects.get(p.id).values.get("device_token_sha256"), hashBefore);
  assert.equal((await (await deviceStatus(f, p)).json()).token_valid, true);
});

test("revocation tombstone prevents uncertain enrollment recovery from resurrecting credentials", async () => {
  const f = fixture(), p = await begin(f);
  f.failAfterRegister = true;
  assert.equal((await approve(f, p)).status, 503);
  const result = await worker.fetch(new Request(ROOT + "/v1/admin/devices/" + p.id, {
    method: "DELETE", headers: { Authorization: "Bearer " + ADMIN },
  }), f.env);
  assert.equal(result.status, 200);
  assert.equal((await (await status(f, p)).json()).state, "registering");
  assert.equal((await deviceStatus(f, p)).status, 403);
  assert.equal(f.objects.get(p.id).values.has("device_token_sha256"), false);
  const lateLegacy = await f.env.DEVICES.get(p.id).fetch(new Request("https://internal/enroll/register", {
    method: "POST", body: JSON.stringify({ device_token_sha256: hash(p.token) }),
  }));
  assert.equal(lateLegacy.status, 409, "A late v1 enrollment cannot revive a revoked device");

});

test("two devices and accounts cannot share owner grants, device tokens or setup proofs", async () => {
  const f = fixture(), first = await begin(f), second = await begin(f);
  await approve(f, first);
  f.env.UDB_ENROLLMENT_OWNER_SUBJECTS = JSON.stringify([TEAM + "#" + OWNER, TEAM + "#" + OTHER]);
  const r = await review(f, second, await jwt(APP, OTHER));
  assert.equal((await decide(f, second, r.csrf, "approve", await jwt(APP, OTHER))).status, 200);
  assert.equal((await deviceStatus(f, first, second.token)).status, 403);
  assert.equal((await status(f, first, second.proof)).status, 403);
  assert.equal((await mcp(f, first, await jwt(MCP, OTHER))).status, 403);
  assert.equal((await mcp(f, second, await jwt(MCP, OWNER))).status, 403);
  assert.equal((await mcp(f, second, await jwt(MCP, OTHER))).status, 200);
});

test("live authenticated MCP probe is required; static discovery and Agent online are insufficient", async () => {
  const f = fixture(), p = await begin(f); await approve(f, p);
  const challenge = hash("synthetic-challenge");
  assert.equal((await worker.fetch(new Request(ROOT + "/v1/devices/" + p.id + "/setup/challenge", {
    method: "POST", headers: { Authorization: "Bearer " + p.token },
    body: JSON.stringify({ challenge_sha256: challenge }),
  }), f.env)).status, 200);
  assert.equal((await (await deviceStatus(f, p)).json()).authenticated_mcp_verified, false);
  f.env.UDB_EDGE_READ_CATALOG = "true";
  f.online = false;
  await mcp(f, p, await jwt(MCP));
  assert.equal((await (await deviceStatus(f, p)).json()).authenticated_mcp_verified, false);
  f.online = true; f.toolError = true;
  await mcp(f, p, await jwt(MCP));
  assert.equal((await (await deviceStatus(f, p)).json()).authenticated_mcp_verified, false);
  f.toolError = false;
  await mcp(f, p, await jwt(MCP));
  const proof = await (await deviceStatus(f, p)).json();
  assert.equal(proof.authenticated_mcp_verified, true);
  assert.equal(proof.chatgpt_connected, false);
  assert.equal(proof.client_attribution, "unavailable");
  f.objects.get(p.id).values.get("setup_proof").at -= 300001;
  assert.equal((await (await deviceStatus(f, p)).json()).authenticated_mcp_verified, false);
});

test("rate limits, public routing and handoff do not expose internal operations or secrets", async () => {
  const f = fixture();
  for (let i = 0; i < 4; i++) await begin(f);
  assert.equal((await f.route("/v1/setup/enrollments", "POST", {
    request_id: "f".repeat(32), request_secret_sha256: hash("proof"),
    device_token_sha256: hash("token"), device_name: "Fifth device" })).status, 429);
  for (const path of ["/setup/record-proof", "/setup/owner-grant", "/setup-register", "/enroll-v2/request"]) {
    assert.equal((await worker.fetch(new Request(ROOT + path), f.env)).status, 404);
  }
  const handoff = await f.route("/v1/devices/" + "a".repeat(32) + "/connect-chatgpt");
  const html = await handoff.text();
  assert.ok(html.includes("https://chatgpt.com/plugins"));
  assert.ok(html.includes("Copy MCP URL"));
  assert.ok(!html.includes(ADMIN));
  assert.match(handoff.headers.get("content-security-policy"), /script-src 'nonce-/);
});


test("rerun renews an expired unapproved window without changing identity, proof or token", async () => {
  const f = fixture(), p = await begin(f);
  const oldReview = await review(f, p);
  const hub = f.objects.get("__udb_browser_enrollment_v2__").values;
  hub.get("setup_enrollments")[0].expires = Date.now() - 1;
  assert.equal((await status(f, p)).status, 410);
  const retry = await f.route("/v1/setup/enrollments", "POST", p.data);
  assert.equal(retry.status, 201);
  assert.equal((await retry.json()).device_id, p.id);
  assert.equal((await (await status(f, p)).json()).state, "pending");
  assert.equal(hub.get("setup_rates").length, 2, "Renewal consumes a rate slot");
  assert.equal((await decide(f, p, oldReview.csrf)).status, 403);
  assert.equal(f.objects.has(p.id), false, "Renewal is never approval");
  assert.equal((await approve(f, p)).status, 200);
  const stored = f.objects.get(p.id).values.get("device_token_sha256");
  assert.equal(stored, hash(p.token));
  await f.route("/v1/setup/enrollments", "POST", p.data);
  assert.equal(hub.get("setup_rates").length, 2, "Approved recovery does not renew approval");
  assert.equal((await (await status(f, p)).json()).state, "approved");
});
