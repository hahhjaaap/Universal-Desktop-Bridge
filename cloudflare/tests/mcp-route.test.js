import assert from "node:assert/strict";
import test from "node:test";
import worker from "../src/index.js";

const id = "a".repeat(32);
const base = "https://example.workers.dev";
const admin = "admin-private-key-" + "x".repeat(35);

function env() {
  let forwarded = 0;
  return {
    UDB_ADMIN_KEY: admin,
    UDB_OAUTH_ISSUER: "https://identity.example.org",
    UDB_OAUTH_JWKS_URL: "https://identity.example.org/jwks",
    UDB_DEVICE_GRANTS: JSON.stringify({ [id]: { alice: ["bridge_status"] } }),
    DEVICES: { idFromName: (id) => id,
      get: () => ({ fetch: async () => { forwarded++;
        return new Response(JSON.stringify({ result: {} })); } }) },
    forwards: () => forwarded,
  };
}

test("OAuth metadata is public, but unverified client cannot use MCP", async () => {
  const settings = env();
  const path = "/.well-known/oauth-protected-resource/v1/devices/" + id + "/mcp";
  const metadata = await worker.fetch(new Request(base + path), settings);
  assert.equal(metadata.status, 200);
  assert.equal((await metadata.json()).resource, base + "/v1/devices/" + id + "/mcp");
  const unauthorized = await worker.fetch(new Request(base + "/v1/devices/" + id + "/mcp", {
    method: "POST", body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
  }), settings);
  assert.equal(unauthorized.status, 401);
  assert.match(unauthorized.headers.get("www-authenticate"), /resource_metadata=/);
  assert.equal(settings.forwards(), 0);
});

test("developer-wide admin RPC is disabled unless explicitly opted in", async () => {
  const settings = env();
  const rpc = new Request(base + "/v1/admin/devices/" + id + "/rpc", {
    method: "POST", headers: { Authorization: "Bearer " + admin },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
  });
  const denied = await worker.fetch(rpc, settings);
  assert.equal(denied.status, 403);
  assert.deepEqual(await denied.json(), { error: "admin_rpc_disabled" });
  assert.equal(settings.forwards(), 0);
});

test("the retired browser viewer does not serve HTML or call the device", async () => {
  const settings = env();
  const health = await worker.fetch(new Request(base + "/health"), settings);
  assert.equal(health.headers.get("x-udb-live-capable"), null);
  const path = "/v1/devices/" + id + "/mcp?view=live&data=status";
  const response = await worker.fetch(new Request(base + path), settings);
  assert.ok(response.status >= 400);
  assert.doesNotMatch(response.headers.get("content-type") ?? "", /html/);
  assert.equal(settings.forwards(), 0);
});
