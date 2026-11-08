import assert from "node:assert/strict";
import test from "node:test";
import { handleMcp } from "../src/mcp.js";
import worker from "../src/index.js";
import { verifiedAccessPrincipal } from "../src/access.js";

const DEVICE = "a".repeat(32);
const OTHER = "b".repeat(32);
const TEAM = "https://p0d-security.cloudflareaccess.com";
const AUD = "a0a0a0a0-1111-2222-3333-444444444444";
const EMAIL = "owner@example.test";
const SUBJECT = "7335d417-61da-459d-899c-0a01c76a2f94";
const OTHER_SUBJECT = "7335d417-61da-459d-899c-0a01c76a2f95";
const RESOURCE = "https://example.workers.dev/v1/devices/" + DEVICE + "/mcp";
const b64 = (v) => Buffer.from(v).toString("base64url");
const keyPromise = crypto.subtle.generateKey({
  name: "RSASSA-PKCS1-v1_5", modulusLength: 2048,
  publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256",
}, true, ["sign", "verify"]);

async function fixture() {
  const keys = await keyPromise;
  const jwk = await crypto.subtle.exportKey("jwk", keys.publicKey);
  const fetchImpl = async (url) => {
    assert.equal(url, TEAM + "/cdn-cgi/access/certs");
    return Response.json({ keys: [{ ...jwk, kid: "staging-test-key" }] });
  };
  const timestamp = Math.floor(Date.now() / 1000);
  const token = async (overrides = {}) => {
    const head = b64(JSON.stringify({ alg: "RS256", kid: "staging-test-key" }));
    const payload = b64(JSON.stringify({
      iss: TEAM, aud: [AUD], exp: timestamp + 300, iat: timestamp,
      sub: SUBJECT, email: EMAIL, ...overrides,
    }));
    const signed = head + "." + payload;
    const signature = await crypto.subtle.sign(
      "RSASSA-PKCS1-v1_5", keys.privateKey, new TextEncoder().encode(signed));
    return signed + "." + b64(signature);
  };

  const state = { rows: [{ tool_name: "bridge_status" }, { tool_name: "read_file" }],
    calls: [], forward: [], unavailable: false };
  const db = {
    prepare(sql) {
      state.calls.push({ sql });
      if (state.unavailable) throw new Error("D1 outage");
      return {
        bind(...args) {
          state.calls[state.calls.length - 1].args = args;
          return { async all() {
            if (args[0] !== DEVICE || args[1] !== TEAM || args[2] !== SUBJECT)
              return { success: true, results: [] };
            return { success: true, results: [...state.rows] };
          } };
        },
      };
    },
  };
  const env = {
    UDB_AUTH_MODE: "cloudflare-access",
    UDB_ACCESS_AUD: AUD, UDB_ACCESS_TEAM_DOMAIN: TEAM,
    UDB_ACCESS_PRINCIPAL_MODE: "issuer-sub",
    UDB_TENANT_D1_AUTH: "true", UDB_TENANT_DB: db,
    UDB_EDGE_READ_CATALOG: "true",
    // Legacy grants must NEVER be consulted in D1 mode.
    UDB_DEVICE_GRANTS: JSON.stringify({
      [DEVICE]: { [EMAIL]: ["bridge_status", "computer_desktop"] },
    }),
    UDB_ENABLE_OWNER_TOOLS: "true",
    UDB_OWNER_TOOL_GRANTS: JSON.stringify({
      [DEVICE]: { [TEAM + "#" + SUBJECT]: ["computer_desktop"] },
    }),
  };
  const stub = { async fetch(req) {
    const rpc = await req.json();
    state.forward.push(rpc);
    return Response.json({
      jsonrpc: "2.0", id: rpc.id, result: { connected: true, source: "test-stub" },
    });
  } };
  const request = (jwt, method = "tools/list", params = {}) => new Request(RESOURCE, {
    method: "POST", headers: {
      "content-type": "application/json",
      ...(jwt ? { "Cf-Access-Jwt-Assertion": jwt } : {}),
    }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
  });
  const call = (jwt, method = "tools/list", params = {}, opts = {}) =>
    handleMcp(request(jwt, method, params), opts.env || env,
      opts.deviceId || DEVICE, stub, fetchImpl, opts.access || null);
  return { token, env, state, fetchImpl, request, call, stub };
}

test("verified Access issuer-sub never trusts a supplied email alone", async () => {
  const f = await fixture();
  const req = f.request(await f.token());
  assert.deepEqual(await verifiedAccessPrincipal(null, f.env, req, f.fetchImpl),
    { issuer: TEAM, subject: SUBJECT });
  await assert.rejects(verifiedAccessPrincipal(null,
    { ...f.env, UDB_ACCESS_PRINCIPAL_MODE: "email" }, req, f.fetchImpl));
});

test("signed principal and device-specific D1 grants expose only approved read tools", async () => {
  const f = await fixture();
  f.state.rows.push({ tool_name: "computer_desktop" }, { tool_name: "totally_fake" });
  const response = await f.call(await f.token());
  assert.equal(response.status, 200);
  const tools = (await response.json()).result.tools;
  assert.deepEqual(tools.map(t => t.name), ["bridge_status", "read_file"]);
  assert.equal(f.state.forward.length, 0);
  assert.deepEqual(f.state.calls[0].args.slice(0, 3), [DEVICE, TEAM, SUBJECT]);
  const sql = f.state.calls[0].sql;
  for (const expected of [
    "d.state = 'active'", "t.state = 'active'", "owner_m.state = 'active'",
    "m.state = 'active'", "g.revoked_at IS NULL", "g.expires_at > ?4",
    "g.device_id = d.device_id", "u.issuer = ?2",
  ]) assert.ok(sql.includes(expected), expected);
});

test("MCP invocation cannot use legacy elevated tool grants while D1 read mode is active", async () => {
  const f = await fixture();
  const jwt = await f.token();
  const forbidden = await f.call(jwt, "tools/call",
    { name: "computer_desktop", arguments: {} });
  assert.equal(forbidden.status, 403);
  assert.equal(f.state.forward.length, 0);
  const allowed = await f.call(jwt, "tools/call",
    { name: "bridge_status", arguments: {} });
  assert.equal(allowed.status, 200);
  assert.deepEqual((await allowed.json()).result,
    { connected: true, source: "test-stub" });
  assert.equal(f.state.forward.length, 1);
});

test("same email with different signed Access UUID cannot inherit another user's D1 grants", async () => {
  const f = await fixture();
  const denied = await f.call(await f.token({ sub: OTHER_SUBJECT }));
  assert.equal(denied.status, 403);
  assert.equal(f.state.forward.length, 0);
  assert.deepEqual(f.state.calls[0].args.slice(0, 3),
    [DEVICE, TEAM, OTHER_SUBJECT]);
});

test("another device ID never inherits the same owner's D1 grant", async () => {
  const f = await fixture();
  const denied = await f.call(await f.token(), "tools/list", {}, { deviceId: OTHER });
  assert.equal(denied.status, 403);
  assert.equal(f.state.forward.length, 0);
  assert.equal(f.state.calls[0].args[0], OTHER);
});

test("revoked/expired grant and database outages immediately deny MCP despite legacy grants", async () => {
  const f = await fixture();
  const jwt = await f.token();
  assert.equal((await f.call(jwt)).status, 200);
  f.state.rows = [];
  assert.equal((await f.call(jwt)).status, 403);
  f.state.unavailable = true;
  assert.equal((await f.call(jwt)).status, 403);
  assert.equal(f.state.forward.length, 0);
});

test("unsigned/expired/wrong-issuer/invalid-sub tokens are rejected before database access", async () => {
  const f = await fixture();
  for (const jwt of [
    null,
    await f.token({ exp: Math.floor(Date.now() / 1000) - 60 }),
    await f.token({ iss: "https://another.cloudflareaccess.com" }),
    await f.token({ sub: "not-a-uuid" }),
  ]) assert.equal((await f.call(jwt)).status, 403);
  assert.equal(f.state.calls.length, 0);
});

test("conflicting runtime Access identity rejects signed request", async () => {
  const f = await fixture();
  const jwt = await f.token();
  const denied = await f.call(jwt, "tools/list", {}, {
    access: { aud: AUD, getIdentity: async () => ({
      email: "another@example.test", user_uuid: SUBJECT,
    }) },
  });
  assert.equal(denied.status, 403);
  assert.equal(f.state.calls.length, 0);
});

test("wrong audience, no D1 binding, wrong principal mode and unrecognized flag fail closed", async () => {
  const f = await fixture();
  const jwt = await f.token();
  for (const changes of [
    { UDB_ACCESS_AUD: "wrong-audience" },
    { UDB_ACCESS_PRINCIPAL_MODE: "email" },
    { UDB_TENANT_DB: undefined },
    { UDB_TENANT_D1_AUTH: "perhaps" },
    { UDB_AUTH_MODE: "jwt" },
  ]) {
    const response = await f.call(jwt, "tools/list", {}, {
      env: { ...f.env, ...changes },
    });
    assert.ok([403, 503].includes(response.status), String(response.status));
  }
  assert.equal(f.state.forward.length, 0);
});

test("D1 mode rejects forged claims inside JSON-RPC params", async () => {
  const f = await fixture();
  const jwt = await f.token();
  const response = await f.call(jwt, "tools/list", {
    tenantId: "attacker", issuer: "https://other.cloudflareaccess.com",
    subject: OTHER_SUBJECT,
  });
  assert.equal(response.status, 200);
  assert.deepEqual(f.state.calls[0].args.slice(0, 3), [DEVICE, TEAM, SUBJECT]);
});

test("an explicit false D1 flag preserves the preexisting single-owner Access path", async () => {
  const f = await fixture();
  const subject = TEAM + "#" + SUBJECT;
  const env = { ...f.env, UDB_TENANT_D1_AUTH: "false",
    UDB_DEVICE_GRANTS: JSON.stringify({
      [DEVICE]: { [subject]: ["bridge_status"] },
    }),
    UDB_ENABLE_OWNER_TOOLS: "false" };
  const response = await f.call(await f.token(), "tools/list", {}, { env });
  assert.equal(response.status, 200);
  assert.equal(f.state.calls.length, 0);
});

test("real Worker route enforces signed D1 identity before forwarding to its Durable Object", async () => {
  const f = await fixture();
  const ids = [];
  f.env.DEVICES = {
    idFromName: (id) => { ids.push(id); return id; },
    get: () => f.stub,
  };
  const previousFetch = globalThis.fetch;
  globalThis.fetch = f.fetchImpl;
  try {
    const jwt = await f.token();
    const ok = await worker.fetch(f.request(jwt), f.env, {
      access: { aud: AUD, getIdentity: async () => ({
        email: EMAIL, user_uuid: SUBJECT,
      }) },
    });
    assert.equal(ok.status, 200);
    assert.deepEqual((await ok.json()).result.tools.map(t => t.name),
      ["bridge_status", "read_file"]);
    assert.deepEqual(ids, [DEVICE]);
    assert.equal(f.state.forward.length, 0, "edge catalog requires no live execution");

    const denied = await worker.fetch(f.request(await f.token({
      sub: OTHER_SUBJECT,
    })), f.env);
    assert.equal(denied.status, 403);
    assert.equal(f.state.forward.length, 0);
  } finally {
    globalThis.fetch = previousFetch;
  }
});
