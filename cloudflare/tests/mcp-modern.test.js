import assert from "node:assert/strict";
import test from "node:test";
import { handleMcp } from "../src/mcp.js";

const device = "a".repeat(32);
const url = "https://staging.workers.dev/v1/devices/" + device + "/mcp";
const version = "2026-07-28", prefix = "io.modelcontextprotocol/";
const env = { UDB_AUTH_MODE: "cloudflare-access", UDB_ACCESS_AUD: "staging-audience",
  UDB_DEVICE_GRANTS: JSON.stringify({ [device]: {
    "owner@example.test": ["read_file", "list_files"],
  } }) };
const access = { aud: "staging-audience",
  getIdentity: async () => ({ email: "owner@example.test" }) };

function harness() {
  const forwarded = [];
  const stub = { async fetch(request) {
    const rpc = await request.json();
    forwarded.push(rpc);
    return Response.json({ jsonrpc: "2.0", id: rpc.id, result:
      rpc.method === "tools/list" ? { tools: [
        { name: "read_file" }, { name: "list_files" }, { name: "computer_execute" },
      ] } : { content: [{ type: "text", text: "synthetic fixture" }] } });
  } };
  const body = (method = "tools/call", id = 1) => ({ jsonrpc: "2.0", id, method,
    params: { ...(method === "tools/call" ? {
      name: "read_file", arguments: { project: "fixture", path: "README.md" },
    } : {}), _meta: { [prefix + "protocolVersion"]: version,
      [prefix + "clientCapabilities"]: {} } } });
  const call = (rpc, headers = {}, identity = access) => handleMcp(new Request(url, {
    method: "POST", headers: { "content-type": "application/json",
      "MCP-Protocol-Version": version, "Mcp-Method": rpc.method,
      ...(rpc.method === "tools/call" ? { "Mcp-Name": rpc.params.name } : {}),
      ...headers }, body: JSON.stringify(rpc),
  }), env, device, stub, fetch, identity);
  return { forwarded, body, call };
}

test("modern tools/call needs no remote initialize and adapts to legacy stdio", async () => {
  const h = harness();
  const response = await h.call(h.body());
  assert.equal(response.status, 200);
  const result = (await response.json()).result;
  assert.equal(result.resultType, "complete");
  assert.equal(result._meta[prefix + "serverInfo"].name, "udb-cloud-readonly");
  assert.equal(h.forwarded.length, 1);
  assert.equal(h.forwarded[0].method, "tools/call");
  assert.equal(h.forwarded[0].params._meta, undefined);
});

test("modern discovery is authenticated and does not initialize the device", async () => {
  const h = harness();
  const response = await h.call(h.body("server/discover"));
  assert.equal(response.status, 200);
  const result = (await response.json()).result;
  assert.equal(result.supportedVersions[0], version);
  assert.deepEqual(result.capabilities, { tools: {} });
  assert.equal(result.ttlMs, 0);
  assert.equal(result.cacheScope, "private");
  assert.equal(h.forwarded.length, 0);
  const denied = await h.call(h.body("server/discover"), {}, {
    ...access, getIdentity: async () => ({ email: "other@example.test" }),
  });
  assert.equal(denied.status, 403);
});

test("modern catalog retains exact grants and is not publicly cacheable", async () => {
  const h = harness();
  const response = await h.call(h.body("tools/list"));
  const result = (await response.json()).result;
  assert.deepEqual(result.tools.map(t => t.name), ["read_file", "list_files"]);
  assert.equal(result.cacheScope, "private");
  assert.equal(response.headers.get("cache-control"), "no-store");
  const rpc = h.body(); rpc.params.name = "computer_execute";
  assert.equal((await h.call(rpc)).status, 403);
  assert.equal(h.forwarded.length, 1);
});

for (const mutation of [
  rpc => delete rpc.params._meta,
  rpc => delete rpc.params._meta[prefix + "clientCapabilities"],
  rpc => { rpc.params._meta[prefix + "clientCapabilities"] = []; },
]) {
  test("malformed modern metadata never reaches the device", async () => {
    const h = harness(), rpc = h.body(); mutation(rpc);
    const response = await h.call(rpc);
    assert.equal(response.status, 400);
    assert.equal((await response.json()).error.code, -32602);
    assert.equal(h.forwarded.length, 0);
  });
}

for (const headers of [
  { "Mcp-Method": "tools/list" }, { "Mcp-Method": "" },
  { "Mcp-Name": "computer_execute" }, { "Mcp-Name": "" },
  { "Mcp-Name": "=?base64?invalid!=" },
  { "MCP-Protocol-Version": "2025-11-25" },
]) {
  test("modern header/body mismatch fails closed", async () => {
    const h = harness();
    const response = await h.call(h.body(), headers);
    assert.equal(response.status, 400);
    assert.equal((await response.json()).error.code, -32020);
    assert.equal(h.forwarded.length, 0);
  });
}

test("encoded tool-name header is decoded before grant enforcement", async () => {
  const h = harness();
  assert.equal((await h.call(h.body(), {
    "Mcp-Name": "=?base64?" + btoa("read_file") + "?=",
  })).status, 200);
});

test("modern unsupported lifecycle method cannot reach the legacy proxy", async () => {
  const h = harness();
  const response = await h.call(h.body("initialize"));
  assert.equal(response.status, 404);
  assert.equal((await response.json()).error.code, -32601);
  assert.equal(h.forwarded.length, 0);
});

test("ten modern stateless calls preserve IDs and per-call grants", async () => {
  const h = harness();
  const responses = await Promise.all(Array.from({ length: 10 }, (_, i) =>
    h.call(h.body("tools/call", i + 1))));
  for (let i = 0; i < responses.length; i++) {
    assert.equal(responses[i].status, 200);
    const reply = await responses[i].json();
    assert.equal(reply.id, i + 1);
    assert.equal(reply.result.resultType, "complete");
  }
  assert.equal(h.forwarded.length, 10);
});
