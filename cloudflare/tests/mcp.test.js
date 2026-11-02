import assert from "node:assert/strict";
import test from "node:test";
import { handleMcp, protectedResource } from "../src/mcp.js";

const id = "a".repeat(32), resource = "https://relay.workers.dev/v1/devices/" + id + "/mcp";
const issuer = "https://idp.example.org";
const env = { UDB_OAUTH_ISSUER: issuer, UDB_OAUTH_JWKS_URL: issuer + "/jwks",
  UDB_DEVICE_GRANTS: JSON.stringify({ [id]: { user1: ["bridge_status"] } }) };

async function setup() {
  const key = await crypto.subtle.generateKey({
    name: "RSASSA-PKCS1-v1_5", modulusLength: 2048,
    publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256",
  }, true, ["sign", "verify"]);
  const now = Math.floor(Date.now()/1000);
  const b64 = (v) => Buffer.from(v).toString("base64url");
  const h = b64(JSON.stringify({ alg: "RS256", kid: "mcp-test" }));
  const p = b64(JSON.stringify({ iss: issuer, aud: resource, sub: "user1",
    scope: "udb:read", exp: now + 300, iat: now }));
  const signed = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key.privateKey,
    new TextEncoder().encode(h + "." + p));
  const token = h + "." + p + "." + b64(signed);
  const jwk = await crypto.subtle.exportKey("jwk", key.publicKey);
  const fetchImpl = async () => new Response(JSON.stringify({ keys: [{ ...jwk, kid: "mcp-test" }] }),
    { headers: { "content-type": "application/json" } });
  const request = (rpc, opts = {}) => new Request(resource, { method: "POST",
    headers: { "Authorization": "Bearer " + token, "MCP-Protocol-Version": "2025-11-25",
      ...(opts.headers || {}) }, body: JSON.stringify(rpc) });
  return { fetchImpl, request };
}

test("OAuth metadata is public but actual MCP fails closed without configuration", async () => {
  const metadata = protectedResource(new Request(resource), env, id);
  assert.equal(metadata.status, 200);
  assert.equal((await metadata.json()).authorization_servers[0], issuer);
  const absent = await handleMcp(new Request(resource, { method: "POST" }),
    {}, id, { fetch() { throw new Error("must not touch remote device"); } });
  assert.equal(absent.status, 503);
});

test("only owner-approved read tools appear or execute", async () => {
  const { fetchImpl, request } = await setup();
  const forwarded = [];
  const stub = { async fetch(req) {
    const rpc = await req.json();
    forwarded.push(rpc);
    return new Response(JSON.stringify({ jsonrpc: "2.0", id: rpc.id, result:
      rpc.method === "tools/list" ? { tools: [
        { name: "bridge_status", description: "Safe status" },
        { name: "computer_terminal", description: "Not authorized" },
      ] } : { ok: true } }));
  } };
  const init = await handleMcp(request({ jsonrpc: "2.0", id: 1,
    method: "initialize", params: {} }), env, id, stub, fetchImpl);
  assert.equal(init.status, 200);
  assert.equal((await init.json()).result.protocolVersion, "2025-11-25");
  const forbidden = await handleMcp(request({ jsonrpc: "2.0", id: 2,
    method: "tools/call", params: { name: "computer_terminal", arguments: {} } }),
  env, id, stub, fetchImpl);
  assert.equal(forbidden.status, 403);
  assert.equal(forwarded.length, 0);
  const catalog = await handleMcp(request({ jsonrpc: "2.0", id: 3,
    method: "tools/list" }), env, id, stub, fetchImpl);
  assert.equal(catalog.status, 200);
  const tools = (await catalog.json()).result.tools;
  assert.deepEqual(tools.map((t) => t.name), ["bridge_status"]);
  assert.deepEqual(tools[0].securitySchemes[0].scopes, ["udb:read"]);
  const call = await handleMcp(request({ jsonrpc: "2.0", id: 4,
    method: "tools/call", params: { name: "bridge_status", arguments: {} } }),
  env, id, stub, fetchImpl);
  assert.equal(call.status, 200);
  assert.deepEqual((await call.json()).result, { ok: true });
  assert.equal(forwarded.length, 2);
});

test("origin mismatch and unsupported protocol cannot reach a device", async () => {
  const { request, fetchImpl } = await setup();
  const stub = { fetch: () => { throw new Error("must not forward"); } };
  const badOrigin = await handleMcp(request({ jsonrpc: "2.0", id: 1,
    method: "ping" }, { headers: { Origin: "https://evil.example" } }),
  env, id, stub, fetchImpl);
  assert.equal(badOrigin.status, 403);
  const wrongVersion = await handleMcp(request({ jsonrpc: "2.0", id: 1,
    method: "ping" }, { headers: { "MCP-Protocol-Version": "other" } }),
  env, id, stub, fetchImpl);
  assert.equal(wrongVersion.status, 400);
});
