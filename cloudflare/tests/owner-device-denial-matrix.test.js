// P0-A synthetic authorization matrix. No live identities, secrets, or devices.
import assert from "node:assert/strict";
import test from "node:test";
import { handleMcp } from "../src/mcp.js";
import { tenantDeviceGrant, parseTenantPolicy } from "../src/tenant-policy.js";

const DEVICE_A = "a".repeat(32);
const DEVICE_B = "b".repeat(32);
const ALICE = "owner-a@example.test";
const BOB = "owner-b@example.test";
const AUDITOR = "auditor@example.test";
const UNKNOWN = "unknown@example.test";
const ACCESS_AUD = "synthetic-audience-not-production";
const URL = "https://example.workers.dev/v1/devices/";

function policy() {
  return {
    version: 1,
    tenants: [
      {
        id: "tenant-a",
        owners: [ALICE],
        members: [ALICE, AUDITOR],
        devices: [{
          id: DEVICE_A,
          grants: [{
            subject: ALICE,
            tools: ["bridge_status", "list_projects", "read_file"],
          }],
        }],
      },
      {
        id: "tenant-b",
        owners: [BOB],
        members: [BOB],
        devices: [{
          id: DEVICE_B,
          grants: [{
            subject: BOB,
            tools: ["bridge_status", "list_projects"],
          }],
        }],
      },
    ],
  };
}

function environment(p = policy()) {
  return {
    UDB_AUTH_MODE: "cloudflare-access",
    UDB_ACCESS_AUD: ACCESS_AUD,
    UDB_TENANT_POLICY: JSON.stringify(p),
    // Even an explicitly opted-in legacy owner grant must not override
    // a configured strict tenant policy.
    UDB_ENABLE_OWNER_TOOLS: "true",
    UDB_OWNER_TOOL_GRANTS: JSON.stringify({
      [DEVICE_A]: { [ALICE]: ["computer_execute", "computer_desktop"] },
    }),
    UDB_DEVICE_GRANTS: JSON.stringify({
      [DEVICE_A]: { [UNKNOWN]: ["read_file"] },
      [DEVICE_B]: { [ALICE]: ["read_file"] },
    }),
  };
}

const identity = (email) => ({
  aud: ACCESS_AUD,
  getIdentity: async () => ({ email }),
});

function request(device, name = null) {
  return new Request(URL + device + "/mcp", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 19,
      method: name ? "tools/call" : "tools/list",
      ...(name ? { params: {
        name, arguments: { project: "fixture", path: "README.md" },
      } } : {}),
    }),
  });
}

function deviceRelay(forwarded) {
  return {
    fetch: async (req) => {
      const rpc = await req.json();
      forwarded.push(rpc);
      return Response.json({
        jsonrpc: "2.0",
        id: rpc.id,
        result: rpc.method === "tools/list"
          ? { tools: [
            "bridge_status", "list_projects", "read_file", "computer_execute",
          ].map((name) => ({ name, inputSchema: { type: "object" } })) }
          : { content: [{ type: "text", text: "synthetic" }] },
      });
    },
  };
}

test("ten simultaneous cross-owner, ungranted and dangerous calls never reach a device", async () => {
  const env = environment();
  const forwarded = [];
  const relay = deviceRelay(forwarded);
  const denied = [
    [DEVICE_A, BOB, "read_file"],
    [DEVICE_B, ALICE, "read_file"],
    [DEVICE_A, AUDITOR, "read_file"],
    [DEVICE_A, UNKNOWN, "read_file"],
    [DEVICE_B, UNKNOWN, "bridge_status"],
    [DEVICE_A, ALICE, "computer_execute"],
    [DEVICE_A, ALICE, "computer_desktop"],
    [DEVICE_B, BOB, "read_file"],
    [DEVICE_A, ALICE, "propose_file_write"],
    [DEVICE_B, BOB, "desktop_action"],
  ];
  const responses = await Promise.all(denied.map(([id, user, name]) =>
    handleMcp(request(id, name), env, id, relay, fetch, identity(user))));
  assert.deepEqual(responses.map((response) => response.status),
    Array(10).fill(403));
  assert.deepEqual(forwarded, []);
});

test("only exact tenant/device grants appear during concurrent discovery", async () => {
  const env = environment();
  const forwarded = [];
  const relay = deviceRelay(forwarded);
  const calls = Array.from({ length: 10 }, (_, i) => {
    const owner = i % 2 === 0 ? ALICE : BOB;
    const device = i % 2 === 0 ? DEVICE_A : DEVICE_B;
    return handleMcp(request(device), env, device, relay, fetch,
      identity(owner));
  });
  const responses = await Promise.all(calls);
  for (let i = 0; i < responses.length; i++) {
    assert.equal(responses[i].status, 200);
    const names = (await responses[i].json()).result.tools.map((tool) => tool.name);
    assert.deepEqual(names, i % 2 === 0
      ? ["bridge_status", "list_projects", "read_file"]
      : ["bridge_status", "list_projects"]);
  }
  assert.equal(forwarded.length, 10);
  assert.ok(forwarded.every((rpc) => rpc.method === "tools/list"));
});

test("removing a tenant grant denies future requests with no legacy owner fallback", async () => {
  const env = environment();
  const forwarded = [];
  const relay = deviceRelay(forwarded);
  assert.equal((await handleMcp(request(DEVICE_A, "read_file"), env,
    DEVICE_A, relay, fetch, identity(ALICE))).status, 200);
  assert.equal(forwarded.length, 1);
  const revoked = policy();
  revoked.tenants[0].devices[0].grants = [];
  env.UDB_TENANT_POLICY = JSON.stringify(revoked);
  const calls = Array.from({ length: 10 }, () => handleMcp(
    request(DEVICE_A, "read_file"), env, DEVICE_A, relay, fetch,
    identity(ALICE)));
  assert.deepEqual((await Promise.all(calls)).map((x) => x.status),
    Array(10).fill(403));
  assert.equal(forwarded.length, 1);
  // This checks admission for *new* calls. It cannot cancel a request that
  // already passed authorization before the revocation update.
});

test("duplicate device assignment or unknown fields invalidate every tenant", () => {
  const duplicates = policy();
  duplicates.tenants[1].devices.push({
    id: DEVICE_A, grants: [{ subject: BOB, tools: ["bridge_status"] }],
  });
  assert.equal(parseTenantPolicy(JSON.stringify(duplicates)), null);
  assert.deepEqual(tenantDeviceGrant(JSON.stringify(duplicates), DEVICE_A, ALICE), []);
  const unknown = policy();
  unknown.tenants[0].devices[0].grants[0].owner = true;
  assert.equal(parseTenantPolicy(JSON.stringify(unknown)), null);
  assert.deepEqual(tenantDeviceGrant(JSON.stringify(unknown), DEVICE_B, BOB), []);
});
