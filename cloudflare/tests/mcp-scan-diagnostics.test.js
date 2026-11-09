import assert from "node:assert/strict";
import test from "node:test";
import worker from "../src/index.js";

const ID = "a".repeat(32);
const ORIGIN = "https://stage.example.workers.dev";
const AUD = "11111111-2222-3333-4444-555555555555";
const URL = ORIGIN + "/v1/devices/" + ID + "/mcp";

function env() {
  let forwarded = 0;
  return {
    UDB_AUTH_MODE: "cloudflare-access",
    UDB_ACCESS_AUD: AUD,
    UDB_EDGE_READ_CATALOG: "true",
    UDB_DEVICE_GRANTS: JSON.stringify({ [ID]: {
      "owner@example.test": ["bridge_status"],
    } }),
    DEVICES: {
      idFromName: value => value,
      get: () => ({
        fetch: async () => {
          forwarded++;
          return Response.json({ error: "unexpected_proxy_call" }, { status: 503 });
        },
      }),
    },
    forwards: () => forwarded,
  };
}
function request() {
  return new Request(URL, {
    method: "POST",
    headers: { "content-type": "application/json",
      "MCP-Protocol-Version": "2025-11-25",
      Authorization: "Bearer test-value-not-a-signed-identity" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1,
      method: "tools/list", params: {} }),
  });
}
function context(email = "owner@example.test", aud = AUD) {
  return { access: { aud, getIdentity: async () => ({ email }) } };
}
async function recorded(run) {
  const prevWarn = console.warn;
  const prevInfo = console.info;
  const messages = [];
  try {
    console.warn = value => messages.push(JSON.parse(value));
    console.info = value => messages.push(JSON.parse(value));
    const response = await run();
    return { response, messages };
  } finally {
    console.warn = prevWarn;
    console.info = prevInfo;
  }
}

test("missing read grant produces only a non-PII denial category", async () => {
  const e = env();
  const { response, messages } = await recorded(() =>
    worker.fetch(request(), e, context("ungranted@example.test")));
  assert.equal(response.status, 403);
  assert.equal((await response.json()).error,
    "cloudflare_access_identity_or_grant_required");
  assert.deepEqual(messages, [
    { event: "udb_mcp_scan_denied", category: "device_grant_missing" },
  ]);
  assert.equal(e.forwards(), 0);
  assert.doesNotMatch(JSON.stringify(messages), /example\.test|Bearer|JWT|a{32}/);
});

test("Access audience mismatch cannot be bypassed by a bearer header", async () => {
  const e = env();
  const { response, messages } = await recorded(() =>
    worker.fetch(request(), e, context("owner@example.test", "wrong-audience")));
  assert.equal(response.status, 403);
  assert.equal(messages[0].category, "access_audience_mismatch");
  assert.equal(e.forwards(), 0);
});

test("missing signed Access identity stays denied despite bearer token", async () => {
  const e = env();
  const { response, messages } = await recorded(() =>
    worker.fetch(request(), e));
  assert.equal(response.status, 401);
  assert.equal((await response.json()).error,
    "cloudflare_access_authentication_required");
  assert.match(response.headers.get("www-authenticate"),
    /Bearer error="invalid_token", resource_metadata="https:\/\/stage\.example\.workers\.dev\/\.well-known\/oauth-protected-resource\/v1\/devices\/a{32}\/mcp"/);
  assert.equal(messages[0].category, "verified_identity_missing");
  assert.equal(e.forwards(), 0);
});

test("valid identity and grant announce the scoped edge catalog", async () => {
  const e = env();
  const { response, messages } = await recorded(() =>
    worker.fetch(request(), e, context()));
  assert.equal(response.status, 200);
  const result = (await response.json()).result;
  assert.deepEqual(result.tools.map(tool => tool.name), ["bridge_status"]);
  assert.deepEqual(messages, [
    { event: "udb_mcp_tools_discovered", source: "edge", count: 1 },
  ]);
  assert.equal(e.forwards(), 0);
});

test("foreign Origin fails without leaking origin or credential", async () => {
  const e = env();
  const req = request();
  req.headers.set("Origin", "https://untrusted.example.test");
  const { response, messages } = await recorded(() =>
    worker.fetch(req, e, context()));
  assert.equal(response.status, 403);
  assert.equal(messages[0].category, "origin_mismatch");
  assert.doesNotMatch(JSON.stringify(messages), /example\.test|Bearer/);
  assert.equal(e.forwards(), 0);
});
