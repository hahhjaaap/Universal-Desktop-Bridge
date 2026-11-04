import assert from "node:assert/strict";
import test from "node:test";
import { deviceGrant } from "../src/oauth.js";
import { parseTenantPolicy, tenantDeviceGrant } from "../src/tenant-policy.js";
import { handleMcp } from "../src/mcp.js";

const a = "a".repeat(32), b = "b".repeat(32);
const alice = "alice@example.test", bob = "bob@example.test";
const policy = () => ({
  version: 1,
  tenants: [
    { id: "tenant-a", owners: [alice], members: [alice], devices: [
      { id: a, grants: [{ subject: alice, tools: ["bridge_status", "read_file"] }] },
    ] },
    { id: "tenant-b", owners: [bob], members: [bob], devices: [
      { id: b, grants: [{ subject: bob, tools: ["bridge_status", "list_projects"] }] },
    ] },
  ],
});
const env = (p = policy()) => ({
  UDB_AUTH_MODE: "cloudflare-access",
  UDB_ACCESS_AUD: "private-app-audience",
  UDB_TENANT_POLICY: JSON.stringify(p),
  // Never allow an invalid tenant policy to fall back to an older secret.
  UDB_DEVICE_GRANTS: JSON.stringify({
    [a]: { [bob]: ["bridge_status", "read_file"] },
    [b]: { [alice]: ["read_file"] },
  }),
});
const access = (email) => ({
  aud: "private-app-audience",
  getIdentity: async () => ({ email }),
});
function rpc(method, name) {
  return { jsonrpc: "2.0", id: 7, method,
    ...(name ? { params: { name, arguments: { project: "fixture", path: "README.md" } } } : {}) };
}
function request(device, method, name) {
  return new Request("https://relay.workers.dev/v1/devices/" + device + "/mcp", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(rpc(method, name)),
  });
}
const stub = (counter) => ({ async fetch(req) {
  counter.push(await req.json());
  return new Response(JSON.stringify({
    jsonrpc: "2.0", id: 7, result: {
      tools: ["bridge_status", "read_file", "list_projects",
        "computer_execute"].map(name => ({
        name, inputSchema: { type: "object" },
      })),
    },
  }), { headers: { "content-type": "application/json" } });
} });

test("tenant owners can only see their device and tools", () => {
  const config = env();
  assert.deepEqual(deviceGrant(config, a, alice), ["bridge_status", "read_file"]);
  assert.deepEqual(deviceGrant(config, b, bob), ["bridge_status", "list_projects"]);
  assert.deepEqual(deviceGrant(config, a, bob), []);
  assert.deepEqual(deviceGrant(config, b, alice), []);
  assert.deepEqual(deviceGrant(config, a, "mallory@example.test"), []);
  assert.deepEqual(tenantDeviceGrant(config.UDB_TENANT_POLICY, a, alice),
    ["bridge_status", "read_file"]);
});

test("full MCP authorization blocks cross-tenant and cross-device requests before forwarding", async () => {
  const e = env();
  const seen = [];
  const remote = stub(seen);
  const aliceCatalog = await handleMcp(request(a, "tools/list"), e, a, remote,
    fetch, access(alice));
  assert.equal(aliceCatalog.status, 200);
  assert.deepEqual((await aliceCatalog.json()).result.tools.map(x => x.name),
    ["bridge_status", "read_file"]);
  const denied = [
    [b, alice, "read_file"],
    [a, bob, "read_file"],
    [b, bob, "read_file"],
    [a, alice, "computer_execute"],
  ];
  for (const [device, subject, tool] of denied) {
    const result = await handleMcp(request(device, "tools/call", tool), e,
      device, remote, fetch, access(subject));
    assert.equal(result.status, 403);
  }
  assert.equal(seen.length, 1);
  assert.equal((await handleMcp(request(a, "tools/call", "read_file"), e,
    a, remote, fetch, access(alice))).status, 200);
  assert.equal(seen.length, 2);
});

test("revocation denies access even when legacy secrets still authorize", async () => {
  const e = env();
  const seen = [];
  const remote = stub(seen);
  assert.equal((await handleMcp(request(a, "tools/call", "read_file"), e,
    a, remote, fetch, access(alice))).status, 200);
  const changed = policy();
  changed.tenants[0].devices[0].grants = [];
  e.UDB_TENANT_POLICY = JSON.stringify(changed);
  assert.equal((await handleMcp(request(a, "tools/call", "read_file"), e,
    a, remote, fetch, access(alice))).status, 403);
  assert.equal(seen.length, 1);
});

test("broken and empty tenant policies fail closed with no legacy fallback", () => {
  const candidates = [
    "", "{", "{}", "null", "[]", JSON.stringify({ version: 2, tenants: [] }),
    JSON.stringify({ version: 1, tenants: [policy().tenants[0],
      { ...policy().tenants[1], devices: [{ id: a, grants: [] }] }] }),
    JSON.stringify({ version: 1, tenants: [policy().tenants[0],
      { ...policy().tenants[0], devices: [] }] }),
    JSON.stringify({ version: 1, tenants: [{
      ...policy().tenants[0], members: ["mallory@example.test"],
    }] }),
    JSON.stringify({ version: 1, tenants: [{
      ...policy().tenants[0], devices: [{ id: a, grants: [
        { subject: alice, tools: ["read_file", "computer_execute"] },
      ] }],
    }] }),
    JSON.stringify({ version: 1, tenants: [{
      ...policy().tenants[0], devices: [{ id: a, grants: [
        { subject: alice, tools: ["read_file"] },
        { subject: alice, tools: ["bridge_status"] },
      ] }],
    }] }),
    JSON.stringify({ version: 1, tenants: [{
      ...policy().tenants[0], superuser: true,
    }] }),
  ];
  for (const raw of candidates) {
    const e = { ...env(), UDB_TENANT_POLICY: raw };
    assert.deepEqual(deviceGrant(e, a, alice), [], raw.slice(0, 60));
    assert.equal(parseTenantPolicy(raw), null);
  }
});

test("legacy single-owner grants remain supported only when tenant policy is absent", () => {
  const e = env();
  delete e.UDB_TENANT_POLICY;
  assert.deepEqual(deviceGrant(e, a, bob), ["bridge_status", "read_file"]);
  assert.deepEqual(deviceGrant({ ...e, UDB_TENANT_POLICY: "" }, a, bob), []);
});

test("a scoped collaborator must be an explicit tenant member and device grantee", () => {
  const p = policy();
  const collaborator = "auditor@example.test";
  p.tenants[0].members.push(collaborator);
  p.tenants[0].devices[0].grants.push({
    subject: collaborator, tools: ["list_projects"],
  });
  assert.deepEqual(tenantDeviceGrant(JSON.stringify(p), a, collaborator),
    ["list_projects"]);
  assert.deepEqual(tenantDeviceGrant(JSON.stringify(p), b, collaborator), []);
});
