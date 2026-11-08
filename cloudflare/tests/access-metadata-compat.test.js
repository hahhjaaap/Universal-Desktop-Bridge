import assert from "node:assert/strict";
import test from "node:test";
import worker from "../src/index.js";

const BASE = "https://udb-private-relay-staging.example.workers.dev";
const ID = "a".repeat(32);
const RESOURCE = BASE + "/v1/devices/" + ID + "/mcp";
const DISCOVERY = BASE + "/.well-known/oauth-protected-resource/v1/devices/" + ID + "/mcp";
const TEAM = "https://round-bonus-5b5c.cloudflareaccess.com";

function settings(overrides = {}) {
  let forwarded = 0;
  return {
    UDB_AUTH_MODE: "cloudflare-access",
    UDB_ACCESS_AUD: "staging-only-access-audience",
    UDB_ACCESS_TEAM_DOMAIN: TEAM,
    UDB_DEVICE_GRANTS: "{}",
    DEVICES: {
      idFromName: (id) => id,
      get: () => ({ async fetch() { forwarded++; return new Response("bad"); } }),
    },
    forwarded: () => forwarded,
    ...overrides,
  };
}

test("RFC 9728 discovery advertises exact staging resource and Access issuer", async () => {
  const env = settings();
  const response = await worker.fetch(new Request(DISCOVERY), env);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    resource: RESOURCE,
    authorization_servers: [TEAM],
    scopes_supported: ["udb:read"],
  });
  assert.match(response.headers.get("content-type"), /application\/json/);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(env.forwarded(), 0);
});

test("OAuth discovery is informational; it never permits unauthenticated MCP tool calls", async () => {
  const env = settings();
  const response = await worker.fetch(new Request(RESOURCE, {
    method: "POST",
    body: JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list" }),
  }), env);
  assert.equal(response.status, 403);
  assert.equal(env.forwarded(), 0);
});

test("missing pinned Access team or invalid auth mode cannot advertise an issuer", async () => {
  for (const overrides of [
    { UDB_ACCESS_TEAM_DOMAIN: undefined },
    { UDB_ACCESS_TEAM_DOMAIN: "http://insecure.example.com" },
    { UDB_AUTH_MODE: "not-a-valid-mode" },
  ]) {
    const response = await worker.fetch(new Request(DISCOVERY), settings(overrides));
    assert.equal(response.status, 503);
  }
});

test("other device paths or mutation methods do not produce valid OAuth metadata", async () => {
  const env = settings();
  assert.equal((await worker.fetch(new Request(BASE +
    "/.well-known/oauth-protected-resource/v1/devices/not-a-device/mcp"), env))
    .status, 404);
  assert.equal((await worker.fetch(new Request(DISCOVERY, { method: "POST" }), env))
    .status, 404);
});
