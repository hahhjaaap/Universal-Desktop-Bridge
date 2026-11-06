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
  // This gateway is dual-era: modern discovery accurately includes the
  // three legacy initialize revisions that remain available.
  assert.deepEqual(result.supportedVersions, [
    version, "2025-03-26", "2025-06-18", "2025-11-25",
  ]);
  assert.deepEqual(result.capabilities, { tools: {} });
  assert.equal(result.ttlMs, 0);
  assert.equal(result.cacheScope, "private");
  assert.equal(h.forwarded.length, 0);
  const denied = await h.call(h.body("server/discover"), {}, {
    ...access, getIdentity: async () => ({ email: "other@example.test" }),
  });
  assert.equal(denied.status, 403);
});

test("unknown protocol version returns spec-compliant -32022 and supported versions", async () => {
  const h = harness();
  const requested = "2099-01-01";
  const rpc = h.body();
  rpc.params._meta[prefix + "protocolVersion"] = requested;
  const response = await h.call(rpc, { "MCP-Protocol-Version": requested });
  assert.equal(response.status, 400);
  const body = await response.json();
  assert.deepEqual(body, {
    jsonrpc: "2.0", id: rpc.id, error: {
      code: -32022,
      message: "Unsupported protocol version",
      data: {
        supported: [version, "2025-03-26", "2025-06-18", "2025-11-25"],
        requested,
      },
    },
  });
  assert.equal(h.forwarded.length, 0, "no request with unknown protocol reaches Windows");
});

test("unknown version is not disclosed before owner authorization", async () => {
  const h = harness();
  const requested = "2099-01-01";
  const rpc = h.body("tools/call");
  rpc.params._meta[prefix + "protocolVersion"] = requested;
  const unauthorized = await h.call(rpc, {
    "MCP-Protocol-Version": requested,
  }, { ...access, getIdentity: async () => ({ email: "other@example.test" }) });
  assert.equal(unauthorized.status, 403);
  assert.equal(h.forwarded.length, 0);
});

test("header/body version mismatch takes precedence over version negotiation", async () => {
  const h = harness();
  const response = await h.call(h.body(), {
    "MCP-Protocol-Version": "2099-01-01",
  });
  assert.equal(response.status, 400);
  const error = (await response.json()).error;
  assert.equal(error.code, -32020);
  assert.equal(h.forwarded.length, 0);
});

test("invalid RPC IDs and oversized version strings fail without reflection", async () => {
  const h = harness();
  const wrong = h.body();
  wrong.id = null;
  wrong.params._meta[prefix + "protocolVersion"] = "2099-01-01";
  const badId = await h.call(wrong, { "MCP-Protocol-Version": "2099-01-01" });
  assert.equal(badId.status, 400);
  assert.equal((await badId.json()).error, "invalid_rpc_id");

  const oversized = "9".repeat(256);
  const second = h.body();
  second.params._meta[prefix + "protocolVersion"] = oversized;
  const badVersion = await h.call(second, { "MCP-Protocol-Version": oversized });
  assert.equal(badVersion.status, 400);
  const response = await badVersion.json();
  assert.equal(response.error, "invalid_protocol_version");
  assert.ok(!JSON.stringify(response).includes(oversized));
  assert.equal(h.forwarded.length, 0);
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
