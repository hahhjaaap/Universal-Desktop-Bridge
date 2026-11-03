import assert from "node:assert/strict";
import test from "node:test";
import worker from "../src/index.js";
import { accessConfig, verifyAccessAssertion } from "../src/access.js";
import { AuthError } from "../src/oauth.js";

const DEVICE = "a".repeat(32);
const OTHER = "b".repeat(32);
const ROOT = "https://relay.workers.dev";
const RESOURCE = ROOT + "/v1/devices/" + DEVICE + "/mcp";
const TEAM = "https://owner-check.cloudflareaccess.com";
const AUD = "9a9a9a9a-1111-2222-3333-444444444444";
const EMAIL = "owner@example.test";
const b64 = (value) => Buffer.from(value).toString("base64url");
// Production JWKS is cached briefly by team domain. Tests must use one stable
// team signing key rather than minting a new key at the same certs URL.
const pairPromise = crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5",
  modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]),
  hash: "SHA-256" }, true, ["sign", "verify"]);

async function fixture() {
  const pair = await pairPromise;
  const publicKey = await crypto.subtle.exportKey("jwk", pair.publicKey);
  const jwks = { keys: [{ ...publicKey, kid: "access-signing-key" }] };
  const now = Math.floor(Date.now() / 1000);
  async function token(overrides = {}, header = {}) {
    const h = b64(JSON.stringify({ alg: "RS256", kid: "access-signing-key", ...header }));
    const p = b64(JSON.stringify({ iss: TEAM, aud: [AUD], exp: now + 300,
      iat: now, email: EMAIL, ...overrides }));
    const msg = h + "." + p;
    const signature = await crypto.subtle.sign("RSASSA-PKCS1-v1_5",
      pair.privateKey, new TextEncoder().encode(msg));
    return msg + "." + b64(signature);
  }
  let fetches = 0;
  const fetchImpl = async (url, options) => {
    assert.equal(url, TEAM + "/cdn-cgi/access/certs");
    assert.equal(options.redirect, "error");
    fetches++;
    return Response.json(jwks);
  };
  const forwards = [];
  const env = {
    UDB_AUTH_MODE: "cloudflare-access", UDB_ACCESS_AUD: AUD,
    UDB_ACCESS_TEAM_DOMAIN: TEAM,
    UDB_DEVICE_GRANTS: JSON.stringify({ [DEVICE]: { [EMAIL]: ["bridge_status"] } }),
    DEVICES: { idFromName: (id) => id, get: () => ({ async fetch(request) {
      const rpc = await request.json();
      forwards.push(rpc);
      return Response.json({ jsonrpc: "2.0", id: rpc.id, result:
        rpc.method === "tools/list" ? { tools: [
          { name: "bridge_status" }, { name: "computer_execute" }] } : { alive: true } });
    } }) },
  };
  function request(jwt, method = "tools/list", params = {}) {
    const headers = { "content-type": "application/json",
      "MCP-Protocol-Version": "2025-11-25" };
    if (jwt) headers["Cf-Access-Jwt-Assertion"] = jwt;
    return new Request(RESOURCE, { method: "POST", headers,
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }) });
  }
  return { env, token, request, forwards, fetchImpl, get fetches() { return fetches; } };
}

test("signed Cloudflare assertion validates without ctx.access", async () => {
  const f = await fixture();
  const jwt = await f.token();
  const signed = await verifyAccessAssertion(f.request(jwt), f.env, f.fetchImpl);
  assert.equal(signed, EMAIL);
  assert.equal(f.forwards.length, 0);
});

test("Worker routes signed Access assertions end to end without ctx.access", async () => {
  const f = await fixture();
  const previous = globalThis.fetch;
  globalThis.fetch = f.fetchImpl;
  try {
    const response = await worker.fetch(f.request(await f.token()), f.env);
    assert.equal(response.status, 200);
    assert.deepEqual((await response.json()).result.tools.map((t) => t.name),
      ["bridge_status"]);
    const other = new Request(ROOT + "/v1/devices/" + OTHER + "/mcp", {
      method: "POST", headers: { "Cf-Access-Jwt-Assertion": await f.token() },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
    });
    assert.equal((await worker.fetch(other, f.env)).status, 403);
    assert.equal(f.forwards.length, 1);
  } finally { globalThis.fetch = previous; }
});

test("signed assertion can call only read tools via the real MCP handler", async () => {
  const { handleMcp } = await import("../src/mcp.js");
  const f = await fixture();
  const jwt = await f.token();
  const stub = f.env.DEVICES.get();
  const response = await handleMcp(f.request(jwt), f.env, DEVICE, stub, f.fetchImpl);
  assert.equal(response.status, 200);
  assert.deepEqual((await response.json()).result.tools.map((t) => t.name),
    ["bridge_status"]);
  const forbidden = await handleMcp(f.request(jwt, "tools/call", {
    name: "computer_execute", arguments: {} }), f.env, DEVICE, stub, f.fetchImpl);
  assert.equal(forbidden.status, 403);
  assert.equal(f.forwards.length, 1);
  const call = await handleMcp(f.request(jwt, "tools/call", {
    name: "bridge_status", arguments: {} }), f.env, DEVICE, stub, f.fetchImpl);
  assert.equal(call.status, 200);
  assert.equal(f.forwards.length, 2);
});

test("invalid, expired, wrong-application and wrong-team assertions fail closed", async () => {
  const f = await fixture();
  const now = Math.floor(Date.now() / 1000);
  for (const changes of [
    { iss: "https://other.cloudflareaccess.com" },
    { aud: ["different-audience"] },
    { email: "stranger@example.test" },
    { exp: now - 10 }, { nbf: now + 600 },
  ]) {
    const jwt = await f.token(changes);
    const response = await (await import("../src/mcp.js")).handleMcp(
      f.request(jwt), f.env, DEVICE, f.env.DEVICES.get(), f.fetchImpl);
    assert.equal(response.status, 403);
  }
  const swapped = await f.token({}, { alg: "none" });
  await assert.rejects(
    verifyAccessAssertion(f.request(swapped), f.env, f.fetchImpl), AuthError);
  const signed = await f.token();
  const [a, b, c] = signed.split(".");
  const tampered = a + "." + b + "." + (c[0] === "A" ? "B" : "A") + c.slice(1);
  await assert.rejects(
    verifyAccessAssertion(f.request(tampered), f.env, f.fetchImpl), AuthError);
  assert.equal(f.forwards.length, 0);
});

test("a fake Access header, cookie, or opaque token without signed JWT cannot login", async () => {
  const f = await fixture();
  const raw = f.request(null);
  raw.headers.set("Cf-Access-Jwt-Assertion", "forged.token.signature");
  raw.headers.set("X-User-Email", EMAIL);
  raw.headers.set("Authorization", "Bearer oauth:opaque-cannot-be-verified-here");
  raw.headers.set("Cookie", "CF_Authorization=untrusted");
  const response = await (await import("../src/mcp.js")).handleMcp(
    raw, f.env, DEVICE, f.env.DEVICES.get(), f.fetchImpl);
  assert.equal(response.status, 403);
  assert.equal(f.forwards.length, 0);
});

test("Access audience conflict cannot fall back to a valid assertion", async () => {
  const { authorizeAccess } = await import("../src/access.js");
  const f = await fixture();
  const jwt = await f.token();
  await assert.rejects(authorizeAccess({ aud: "wrong", getIdentity:
    async () => ({ email: EMAIL }) }, f.env, DEVICE, f.request(jwt), f.fetchImpl), AuthError);
  assert.equal(f.fetches, 0);
});

test("runtime Access without an email verifies signed JWT fallback", async () => {
  const { authorizeAccess } = await import("../src/access.js");
  const f = await fixture();
  const jwt = await f.token();
  const result = await authorizeAccess({ aud: AUD, getIdentity: async () => null },
    f.env, DEVICE, f.request(jwt), f.fetchImpl);
  assert.deepEqual(result, { subject: EMAIL, allowTools: ["bridge_status"] });
});

test("Access config refuses unpinned or unsafe team domains", () => {
  for (const team of ["http://owner.cloudflareaccess.com",
    "https://owner.cloudflareaccess.com.evil.example",
    "https://owner.cloudflareaccess.com:8443",
    "https://owner.cloudflareaccess.com/path",
    "https://owner.cloudflareaccess.com/"]) {
    assert.equal(accessConfig({ UDB_ACCESS_AUD: AUD,
      UDB_ACCESS_TEAM_DOMAIN: team }), null);
  }
  assert.equal(accessConfig({ UDB_ACCESS_AUD: AUD }).team, null);
});
