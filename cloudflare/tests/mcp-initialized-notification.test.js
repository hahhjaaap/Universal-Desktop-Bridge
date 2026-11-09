import assert from "node:assert/strict";
import test from "node:test";
import { handleMcp } from "../src/mcp.js";

const DEVICE = "a".repeat(32);
const URL = "https://audit.example.workers.dev/v1/devices/" + DEVICE + "/mcp";
const AUD = "notification-audience";
const env = {
  UDB_AUTH_MODE: "cloudflare-access", UDB_ACCESS_AUD: AUD,
  UDB_DEVICE_GRANTS: JSON.stringify({ [DEVICE]: {
    "owner@example.test": ["bridge_status"],
  } }),
};
const owner = { aud: AUD,
  getIdentity: async () => ({ email: "owner@example.test" }) };
function harness() {
  let forwarded = 0;
  const stub = { fetch: async () => { forwarded++; throw new Error("Must not forward"); } };
  const call = (rpc, version = "2025-11-25", access = owner) => handleMcp(
    new Request(URL, {
      method: "POST",
      headers: { "content-type": "application/json",
        "MCP-Protocol-Version": version },
      body: JSON.stringify(rpc),
    }), env, DEVICE, stub, fetch, access,
  );
  return { call, forwarded: () => forwarded };
}

test("legacy MCP initialized notification without JSON-RPC ID returns 202", async () => {
  const h = harness();
  const response = await h.call({ jsonrpc: "2.0",
    method: "notifications/initialized", params: {} });
  assert.equal(response.status, 202);
  assert.equal(await response.text(), "");
  assert.equal(h.forwarded(), 0);
});

test("legacy initialized notification enforces identity and version", async () => {
  const h = harness();
  const notification = { jsonrpc: "2.0", method: "notifications/initialized" };
  assert.equal((await h.call(notification, "2025-11-25", { ...owner,
    getIdentity: async () => ({ email: "other@example.test" }),
  })).status, 403);
  const invalidVersion = await h.call({
    ...notification,
    params: { _meta: { "io.modelcontextprotocol/protocolVersion": "2099-01-01" } },
  });
  assert.equal(invalidVersion.status, 400);
  assert.equal(h.forwarded(), 0);
});

test("JSON-RPC requests and malformed notifications still need valid IDs", async () => {
  const h = harness();
  for (const rpc of [
    { jsonrpc: "2.0", id: null, method: "notifications/initialized" },
    { jsonrpc: "2.0", id: 1, method: "notifications/initialized" },
    { jsonrpc: "2.0", method: "tools/list" },
    { jsonrpc: "2.0", method: "notifications/initialized", params: [] },
    { jsonrpc: "2.0", method: "notifications/initialized", params: null },
  ]) {
    const res = await h.call(rpc);
    assert.equal(res.status, 400);
  }
  assert.equal(h.forwarded(), 0);
});
