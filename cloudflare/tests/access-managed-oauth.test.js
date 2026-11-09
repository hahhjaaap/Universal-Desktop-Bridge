import assert from "node:assert/strict";
import test from "node:test";
import worker from "../src/index.js";
import { authorizeAccess } from "../src/mcp.js";

const ID = "a".repeat(32);
const ORIGIN = "https://example.workers.dev";
const RESOURCE = ORIGIN + "/v1/devices/" + ID + "/mcp";
const VERIFIED_AUD = "11111111-2222-3333-4444-555555555555";
function settings() {
  const forwarded = [];
  return {
    UDB_AUTH_MODE: "cloudflare-access",
    UDB_ACCESS_AUD: VERIFIED_AUD,
    UDB_DEVICE_GRANTS: JSON.stringify({ [ID]: {
      "owner@example.test": ["bridge_status"],
    } }),
    DEVICES: {
      idFromName: (id) => id,
      get: () => ({ async fetch(request) {
        const rpc = await request.json();
        forwarded.push(rpc);
        return Response.json({ jsonrpc: "2.0", id: rpc.id,
          result: rpc.method === "tools/list" ? { tools: [
            { name: "bridge_status", description: "Status" },
            { name: "computer_terminal", description: "Not allowed" },
          ] } : { ok: true } });
      } }),
    },
    forwarded,
  };
}
function req(method, id = 1, params = {}) {
  return new Request(RESOURCE, { method: "POST",
    headers: { "content-type": "application/json", "MCP-Protocol-Version": "2025-11-25" },
    body: JSON.stringify({ jsonrpc: "2.0", id, method, params }),
  });
}
function ctx(email = "owner@example.test", aud = VERIFIED_AUD) {
  return { access: { aud, getIdentity: async () => ({ email }) } };
}

test("Access mode fails closed without configured audience or runtime identity", async () => {
  const env = settings();
  const spoof = new Request(RESOURCE, { method: "POST",
    headers: { "Cf-Access-Jwt-Assertion": "forged-header" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
  });
  assert.equal((await worker.fetch(spoof, env)).status, 401);
  assert.equal(env.forwarded.length, 0);
  delete env.UDB_ACCESS_AUD;
  assert.equal((await worker.fetch(req("tools/list"), env, ctx())).status, 503);
  env.UDB_AUTH_MODE = "typo";
  assert.equal((await worker.fetch(req("tools/list"), env, ctx())).status, 503);
  assert.equal(env.forwarded.length, 0);
});

test("Access verifies application audience and exact owner/device grant", async () => {
  const env = settings();
  for (const [bad, expected] of [
    [ctx("owner@example.test", "not-our-access-app"), 403],
    [ctx("another@example.test"), 403],
    [{ access: { aud: VERIFIED_AUD, getIdentity: async () => null } }, 401],
  ]) {
    assert.equal((await worker.fetch(req("tools/list"), env, bad)).status, expected);
  }
  assert.equal(env.forwarded.length, 0);
  assert.deepEqual(await authorizeAccess(ctx().access, env, ID),
    { subject: "owner@example.test", allowTools: ["bridge_status"] });
  const response = await worker.fetch(req("tools/list"), env, ctx());
  assert.equal(response.status, 200);
  const catalog = (await response.json()).result.tools;
  assert.deepEqual(catalog.map((x) => x.name), ["bridge_status"]);
  assert.equal(env.forwarded.length, 1);
  assert.equal((await worker.fetch(req("tools/call", 2, {
    name: "computer_terminal", arguments: {} }), env, ctx())).status, 403);
  assert.equal(env.forwarded.length, 1);
  const allowed = await worker.fetch(req("tools/call", 3, {
    name: "bridge_status", arguments: {} }), env, ctx());
  assert.equal(allowed.status, 200);
  assert.equal(env.forwarded.length, 2);
});

test("Access authentication never accepts identity from arbitrary request headers", async () => {
  const env = settings();
  const attempt = req("tools/list");
  attempt.headers.set("Cf-Access-Jwt-Assertion", "fake");
  attempt.headers.set("X-User-Email", "owner@example.test");
  const denied = await worker.fetch(attempt, env);
  assert.equal(denied.status, 401);
  assert.match(denied.headers.get("www-authenticate"), /resource_metadata=/);
  assert.equal(env.forwarded.length, 0);
});

test("Worker health advertises Access code capability without claiming auth enabled", async () => {
  const response = await worker.fetch(new Request(ORIGIN + "/health"), settings());
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("X-UDB-Access-OAuth-Capable"), "1");
  assert.equal(response.headers.get("X-UDB-Project-Read-Capable"), "1");
  assert.deepEqual(await response.json(),
    { status: "ok", kind: "private-relay-prototype" });
});
