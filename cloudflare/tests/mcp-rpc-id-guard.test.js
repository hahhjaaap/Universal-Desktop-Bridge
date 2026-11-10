import assert from "node:assert/strict";
import test from "node:test";
import { handleMcp } from "../src/mcp.js";
import { validRpc } from "../src/auth.js";

const DEVICE = "a".repeat(32);
const URL = "https://audit.example.workers.dev/v1/devices/" + DEVICE + "/mcp";
const ENV = {
  UDB_AUTH_MODE: "cloudflare-access",
  UDB_ACCESS_AUD: "audit-test-only-audience",
  UDB_DEVICE_GRANTS: JSON.stringify({ [DEVICE]: {
    "audit@example.test": ["bridge_status", "read_file"],
  } }),
};
const ACCESS = {
  aud: "audit-test-only-audience",
  getIdentity: async () => ({ email: "audit@example.test" }),
};

function harness() {
  let forwarded = 0;
  const stub = {
    async fetch() {
      forwarded++;
      return Response.json({ jsonrpc: "2.0", id: 1, result: { tools: [] } });
    },
  };
  function call(rpc, version = "2026-07-28") {
    return handleMcp(new Request(URL, {
      method: "POST",
      headers: { "content-type": "application/json",
        "MCP-Protocol-Version": version,
        "Mcp-Method": rpc.method },
      body: JSON.stringify(rpc),
    }), ENV, DEVICE, stub, fetch, ACCESS);
  }
  return { call, getForwarded: () => forwarded };
}

test("invalid RPC IDs cannot be reflected before protocol version checks", async () => {
  for (const id of [null, { secretFixture: "DO_NOT_ECHO" }, [], "x".repeat(257)]) {
    const h = harness();
    const response = await h.call({
      jsonrpc: "2.0", id, method: "tools/list",
      params: { _meta: { "io.modelcontextprotocol/protocolVersion": "2025-11-25" } },
    }, "2099-01-01");
    assert.equal(response.status, 400);
    const result = await response.json();
    assert.equal(result.error, "invalid_rpc_id");
    assert.ok(!JSON.stringify(result).includes("DO_NOT_ECHO"));
    assert.equal(h.getForwarded(), 0);
  }
});

test("invalid RPC IDs cannot be echoed by modern metadata errors", async () => {
  for (const id of [null, { secretFixture: "DO_NOT_ECHO" }, "x".repeat(257)]) {
    const h = harness();
    const response = await h.call({
      jsonrpc: "2.0", id, method: "tools/list",
      params: { _meta: { "io.modelcontextprotocol/protocolVersion": "2026-07-28" } },
    });
    assert.equal(response.status, 400);
    const result = await response.json();
    assert.equal(result.error, "invalid_rpc_id");
    assert.ok(!JSON.stringify(result).includes("DO_NOT_ECHO"));
    assert.equal(h.getForwarded(), 0);
  }
});

test("low-level validation bounds RPC IDs before proxy forwarding", () => {
  for (const badId of [null, {}, [], "", "x".repeat(257)]) {
    assert.equal(validRpc({
      jsonrpc: "2.0", id: badId, method: "tools/list", params: {},
    }), false);
  }
  assert.equal(validRpc({
    jsonrpc: "2.0", id: "x".repeat(256), method: "tools/list", params: {},
  }), true);
});
