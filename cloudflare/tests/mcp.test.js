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
      rpc.method === "initialize" ? { protocolVersion: "2025-11-25" } : rpc.method === "tools/list" ? { tools: [
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
  assert.equal(forwarded.length, 1);
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
  assert.equal(forwarded.length, 3);
});

test("initialize fails closed if the local device is offline or rejects initialization", async () => {
  // Use the trusted runtime identity to avoid coupling this test to the JWT JWKS cache.
  const accessEnv = { UDB_AUTH_MODE: "cloudflare-access",
    UDB_ACCESS_AUD: "application-audience-test",
    UDB_DEVICE_GRANTS: JSON.stringify({ [id]: { "owner@example.test": ["bridge_status"] } }) };
  const access = { aud: "application-audience-test",
    getIdentity: async () => ({ email: "owner@example.test" }) };
  const rpc = { jsonrpc: "2.0", id: 5, method: "initialize",
    params: { protocolVersion: "2025-11-25", capabilities: {},
      clientInfo: { name: "udb-test", version: "1" } } };
  const request = () => new Request(resource, { method: "POST",
    headers: { "content-type": "application/json" }, body: JSON.stringify(rpc) });
  const offline = await handleMcp(request(), accessEnv, id, {
    fetch: async () => new Response(JSON.stringify({ error: "device_offline" }), {
      status: 503, headers: { "content-type": "application/json" },
    }),
  }, fetch, access);
  assert.equal(offline.status, 503);
  const rejected = await handleMcp(request(), accessEnv, id, {
    fetch: async () => new Response(JSON.stringify({
      jsonrpc: "2.0", id: 5, error: { code: -32000, message: "not ready" },
    }), { headers: { "content-type": "application/json" } }),
  }, fetch, access);
  assert.equal(rejected.status, 502);
});

test("origin mismatch and unsupported protocol cannot reach a device", async () => {
  const { request, fetchImpl } = await setup();
  const stub = { fetch: () => { throw new Error("must not forward"); } };
  const badOrigin = await handleMcp(request({ jsonrpc: "2.0", id: 1,
    method: "ping" }, { headers: { Origin: "https://evil.example" } }),
  env, id, stub, fetchImpl);
  assert.equal(badOrigin.status, 403);
  // Protocol negotiation runs only *after* a verified Access subject/device
  // grant. A syntactically valid version header must not become an auth bypass.
  const accessEnv = { UDB_AUTH_MODE: "cloudflare-access",
    UDB_ACCESS_AUD: "version-test-audience",
    UDB_DEVICE_GRANTS: JSON.stringify({ [id]: {
      "owner@example.test": ["bridge_status"],
    } }) };
  const access = { aud: "version-test-audience",
    getIdentity: async () => ({ email: "owner@example.test" }) };
  const wrongVersion = await handleMcp(request({ jsonrpc: "2.0", id: 1,
    method: "ping" }, { headers: { "MCP-Protocol-Version": "other" } }),
  accessEnv, id, stub, fetch, access);
  assert.equal(wrongVersion.status, 400);
  const details = await wrongVersion.json();
  assert.equal(details.error.code, -32022);
  assert.equal(details.error.data.requested, "other");
  assert.ok(details.error.data.supported.includes("2026-07-28"));
  const denied = await handleMcp(request({ jsonrpc: "2.0", id: 2,
    method: "ping" }, { headers: { "MCP-Protocol-Version": "other" } }),
  accessEnv, id, stub, fetch, {
    ...access, getIdentity: async () => ({ email: "outsider@example.test" }),
  });
  assert.equal(denied.status, 403);
});

test("gateway discovers and calls explicitly granted project read tools only", async () => {
  const scopedEnv = { UDB_AUTH_MODE: "cloudflare-access",
    UDB_ACCESS_AUD: "application-audience-test",
    UDB_DEVICE_GRANTS: JSON.stringify({ [id]: {
      "owner@example.test": ["list_files", "read_file"],
    } }) };
  const access = { aud: "application-audience-test",
    getIdentity: async () => ({ email: "owner@example.test" }) };
  const forwarded = [];
  const stub = { async fetch(req) {
    const rpc = await req.json();
    forwarded.push(rpc);
    const result = rpc.method === "initialize" ? { protocolVersion: "2025-11-25" } :
      rpc.method === "tools/list" ? { tools: [
        { name: "bridge_status" }, { name: "list_files" },
        { name: "read_file" }, { name: "propose_file_write" },
        { name: "computer_execute" },
      ] } : { ok: true };
    return new Response(JSON.stringify({ jsonrpc: "2.0", id: rpc.id, result }));
  } };
  const request = (rpc) => new Request(resource, { method: "POST",
    headers: { "content-type": "application/json" }, body: JSON.stringify(rpc) });
  const execute = (rpc) => handleMcp(request(rpc), scopedEnv, id, stub, fetch, access);

  const init = await execute({ jsonrpc: "2.0", id: 100, method: "initialize",
    params: {} });
  assert.equal(init.status, 200);
  const list = await execute({ jsonrpc: "2.0", id: 101, method: "tools/list" });
  assert.equal(list.status, 200);
  assert.deepEqual((await list.json()).result.tools.map(t => t.name),
    ["list_files", "read_file"]);

  const allowed = await execute({ jsonrpc: "2.0", id: 102, method: "tools/call",
    params: { name: "read_file", arguments: { project: "udb-room", path: "README.md" } } });
  assert.equal(allowed.status, 200);
  const denied = await execute({ jsonrpc: "2.0", id: 103, method: "tools/call",
    params: { name: "propose_file_write", arguments: {} } });
  assert.equal(denied.status, 403);
  const ungranted = await execute({ jsonrpc: "2.0", id: 104, method: "tools/call",
    params: { name: "bridge_status", arguments: {} } });
  assert.equal(ungranted.status, 403);
  assert.deepEqual(forwarded.map(rpc => rpc.id), [100, 101, 102]);
});

test("initialize reports the actual negotiated device protocol without requiring an HTTP header", async () => {
  const e = { UDB_AUTH_MODE: "cloudflare-access", UDB_ACCESS_AUD: "application-audience-test",
    UDB_DEVICE_GRANTS: JSON.stringify({ [id]: { "owner@example.test": ["read_file"] } }) };
  const access = { aud: "application-audience-test", getIdentity: async () => ({ email: "owner@example.test" }) };
  const request = () => new Request(resource, { method: "POST", body: JSON.stringify({
    jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-11-25" } }) });
  const stub = { fetch: async () => new Response(JSON.stringify({ jsonrpc: "2.0", id: 1,
    result: { protocolVersion: "2025-11-25" } })) };
  const result = await handleMcp(request(), e, id, stub, fetch, access);
  assert.equal((await result.json()).result.protocolVersion, "2025-11-25");
  stub.fetch = async () => new Response(JSON.stringify({ jsonrpc: "2.0", id: 1,
    result: { protocolVersion: "not-supported" } }));
  assert.equal((await handleMcp(request(), e, id, stub, fetch, access)).status, 502);
  stub.fetch = async () => new Response(JSON.stringify({ jsonrpc: "2.0", id: 1,
    result: { protocolVersion: "2025-11-25" }, error: null }));
  assert.equal((await handleMcp(request(), e, id, stub, fetch, access)).status, 502);
});

test("gateway preserves scoped tool schemas and denies revoked identity/device grants", async () => {
  const names = ["list_files", "read_file", "search_files", "check_python_syntax"];
  const e = { UDB_AUTH_MODE: "cloudflare-access", UDB_ACCESS_AUD: "application-audience-test",
    UDB_DEVICE_GRANTS: JSON.stringify({ [id]: { "owner@example.test": names } }) };
  const access = { aud: "application-audience-test", getIdentity: async () => ({ email: "owner@example.test" }) };
  const schema = { type: "object", properties: { project: { type: "string" }, path: { type: "string" } }, required: ["project", "path"] };
  const forwarded = [];
  const stub = { async fetch(req) {
    const rpc = await req.json(); forwarded.push(rpc);
    return new Response(JSON.stringify({ jsonrpc: "2.0", id: rpc.id,
      result: rpc.method === "tools/list" ? { tools: [...names, "propose_file_write"].map(name => ({ name, inputSchema: schema })) } : { ok: true } }));
  } };
  const request = (method, name) => new Request(resource, { method: "POST", body: JSON.stringify({
    jsonrpc: "2.0", id: 1, method, ...(name ? { params: { name, arguments: { project: "udb-room", path: "README.md" } } } : {}) }) });
  const list = await handleMcp(request("tools/list"), e, id, stub, fetch, access);
  const tools = (await list.json()).result.tools;
  assert.deepEqual(tools.map(tool => tool.name), names);
  for (const tool of tools) assert.deepEqual(tool.inputSchema, schema);
  for (const name of names) assert.equal((await handleMcp(request("tools/call", name), e, id, stub, fetch, access)).status, 200);
  assert.equal((await handleMcp(request("tools/call", "propose_file_write"), e, id, stub, fetch, access)).status, 403);
  const count = forwarded.length;
  assert.equal((await handleMcp(request("tools/list"), e, "b".repeat(32), stub, fetch, access)).status, 403);
  e.UDB_DEVICE_GRANTS = "{}";
  assert.equal((await handleMcp(request("tools/call", "read_file"), e, id, stub, fetch, access)).status, 403);
  assert.equal(forwarded.length, count);
});

test("initialize failure diagnostics distinguish safe reasons and redact upstream payloads", async () => {
  const e = { UDB_AUTH_MODE: "cloudflare-access", UDB_ACCESS_AUD: "application-audience-test",
    UDB_DEVICE_GRANTS: JSON.stringify({ [id]: { "owner@example.test": ["read_file"] } }) };
  const access = { aud: "application-audience-test", getIdentity: async () => ({ email: "owner@example.test" }) };
  const request = params => new Request(resource, { method: "POST", body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params }) });
  for (const reason of ["device_offline", "device_busy", "secret-path-and-token"]) {
    let calls = 0;
    const result = await handleMcp(request({}), e, id, { fetch: async () => {
      calls++; return new Response(JSON.stringify({ error: reason, token: "private" }), { status: reason === "device_busy" ? 429 : 503 });
    } }, fetch, access);
    const reply = await result.json();
    assert.equal(reply.error, "device_initialize_unavailable");
    assert.equal(reply.diagnostics.reason, reason === "secret-path-and-token" ? "upstream_unavailable" : reason);
    assert.equal(calls, 1);
    assert.ok(!JSON.stringify(reply).includes("private") && !JSON.stringify(reply).includes("secret-path-and-token"));
  }
  assert.equal((await handleMcp(request([]), e, id, { fetch: () => assert.fail("Bad initialize must not reach device") }, fetch, access)).status, 400);
});
