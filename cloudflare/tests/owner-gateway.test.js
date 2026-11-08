import assert from "node:assert/strict";
import test from "node:test";
import { handleMcp } from "../src/mcp.js";
import { READ_TOOLS } from "../src/read-tools.js";
import { OWNER_TOOLS } from "../src/owner-tools.js";

const DEVICE = "a".repeat(32);
const OTHER_DEVICE = "b".repeat(32);
const OWNER = "owner@example.test";
const AUD = "access-owner-tool-gateway-audience";
const resource = "https://staging.workers.dev/v1/devices/" + DEVICE + "/mcp";
const base = () => ({
  UDB_AUTH_MODE: "cloudflare-access",
  UDB_ACCESS_AUD: AUD,
  UDB_DEVICE_GRANTS: JSON.stringify({ [DEVICE]: { [OWNER]: ["bridge_status", "read_file"] } }),
});
const opts = () => ({
  UDB_ENABLE_OWNER_TOOLS: "true",
  UDB_OWNER_TOOL_GRANTS: JSON.stringify({ [DEVICE]: {
    [OWNER]: ["computer_process", "propose_file_write", "host_browser"],
  } }),
});
const access = (email = OWNER, aud = AUD) => ({
  aud, getIdentity: async () => ({ email }),
});
const makeRequest = (id, method, name) => new Request(resource, {
  method: "POST", body: JSON.stringify({
    jsonrpc: "2.0", id, method,
    ...(name ? { params: { name, arguments: {} } } : {}),
  }),
});
const makeStub = () => {
  const forwarded = [];
  const stub = { async fetch(request) {
    const rpc = await request.json();
    forwarded.push(rpc);
    let result;
    if (rpc.method === "initialize") result = { protocolVersion: "2025-11-25" };
    else if (rpc.method === "tools/list") result = { tools: [
      "bridge_status", "read_file", "computer_process", "propose_file_write",
      "host_browser", "computer_desktop",
    ].map((name) => ({
      name,
      inputSchema: { type: "object", properties: { name: { type: "string" } } },
      annotations: { readOnlyHint: ["bridge_status", "read_file"].includes(name) },
    })) };
    else result = { status: "requires_local_owner_approval" };
    return new Response(JSON.stringify({ jsonrpc: "2.0", id: rpc.id, result }), {
      headers: { "content-type": "application/json" },
    });
  } };
  return { stub, forwarded };
};

test("Access mode defaults to read-only even if an owner grants exist", async () => {
  const env = { ...base(), ...opts(), UDB_ENABLE_OWNER_TOOLS: "false" };
  const { stub, forwarded } = makeStub();
  const catalog = await handleMcp(makeRequest(1, "tools/list"), env, DEVICE, stub, fetch, access());
  assert.equal(catalog.status, 200);
  assert.deepEqual((await catalog.json()).result.tools.map((t) => t.name),
    ["bridge_status", "read_file"]);
  const denied = await handleMcp(makeRequest(2, "tools/call", "computer_process"),
    env, DEVICE, stub, fetch, access());
  assert.equal(denied.status, 403);
  assert.deepEqual(forwarded.map((x) => x.id), [1]);
});

test("explicit Access owner and device grant show operations with local approval retained", async () => {
  const env = { ...base(), ...opts() };
  const { stub, forwarded } = makeStub();
  const init = await handleMcp(makeRequest(1, "initialize"), env, DEVICE, stub, fetch, access());
  assert.equal(init.status, 200);
  assert.equal((await init.json()).result.serverInfo.name, "udb-cloud-owner-gated");
  const catalog = await handleMcp(makeRequest(2, "tools/list"), env, DEVICE, stub, fetch, access());
  assert.equal(catalog.status, 200);
  const tools = (await catalog.json()).result.tools;
  assert.deepEqual(tools.map((t) => t.name), [
    "bridge_status", "read_file", "computer_process", "propose_file_write", "host_browser",
  ]);
  assert.deepEqual(tools[0].securitySchemes[0].scopes, ["udb:read"]);
  assert.deepEqual(tools[2].securitySchemes[0].scopes, ["udb:computer"]);
  assert.equal(tools[2].annotations.readOnlyHint, false);
  const operation = await handleMcp(makeRequest(3, "tools/call", "computer_process"),
    env, DEVICE, stub, fetch, access());
  assert.equal(operation.status, 200);
  assert.deepEqual((await operation.json()).result,
    { status: "requires_local_owner_approval" });
  const neverGranted = await handleMcp(makeRequest(4, "tools/call", "computer_desktop"),
    env, DEVICE, stub, fetch, access());
  assert.equal(neverGranted.status, 403);
  assert.deepEqual(forwarded.map((x) => x.id), [1, 2, 3]);
});

test("revocation, wrong owner, wrong device and tenant mode reject operations", async () => {
  const env = { ...base(), ...opts() };
  const { stub, forwarded } = makeStub();
  for (const changed of [
    { env: { ...env, UDB_OWNER_TOOL_GRANTS: "{}" }, device: DEVICE, identity: access() },
    { env: env, device: DEVICE, identity: access("other@example.test") },
    { env: env, device: OTHER_DEVICE, identity: access() },
    { env: env, device: DEVICE, identity: access(OWNER, "wrong-audience") },
    { env: { ...env, UDB_TENANT_POLICY: "{}" }, device: DEVICE, identity: access() },
    { env: { ...env, UDB_DEVICE_GRANTS: "{}" }, device: DEVICE, identity: access() },
  ]) {
    const reply = await handleMcp(makeRequest(5, "tools/call", "computer_process"),
      changed.env, changed.device, stub, fetch, changed.identity);
    assert.equal(reply.status, 403);
  }
  assert.equal(forwarded.length, 0);
});

test("legacy JWT resource cannot inherit Access-only owner tool scope", async () => {
  const env = { ...base(), ...opts(), UDB_AUTH_MODE: "jwt" };
  const { stub, forwarded } = makeStub();
  const reply = await handleMcp(makeRequest(6, "tools/call", "computer_process"),
    env, DEVICE, stub, fetch, access());
  assert.equal(reply.status, 503);
  assert.equal(forwarded.length, 0);
});

test("explicit full owner grant discovers all 59 public tools without auto-running them", async () => {
  const all = [...READ_TOOLS, ...OWNER_TOOLS];
  assert.equal(all.length, 59);
  const env = {
    ...base(),
    UDB_DEVICE_GRANTS: JSON.stringify({ [DEVICE]: { [OWNER]: READ_TOOLS } }),
    UDB_ENABLE_OWNER_TOOLS: "true",
    UDB_OWNER_TOOL_GRANTS: JSON.stringify({ [DEVICE]: { [OWNER]: OWNER_TOOLS } }),
  };
  const forwarded = [];
  const stub = { async fetch(request) {
    const rpc = await request.json();
    forwarded.push(rpc);
    return new Response(JSON.stringify({
      jsonrpc: "2.0", id: rpc.id,
      result: { tools: all.map((name) => ({
        name, inputSchema: { type: "object", properties: { fixture: { type: "string" } } },
      })) },
    }));
  } };
  const list = await handleMcp(makeRequest(71, "tools/list"),
    env, DEVICE, stub, fetch, access());
  assert.equal(list.status, 200);
  const tools = (await list.json()).result.tools;
  assert.equal(tools.length, 59);
  assert.deepEqual(tools.map((tool) => tool.name), all);
  assert.ok(tools.every((tool) => tool.inputSchema.properties.fixture.type === "string"));
  assert.equal(forwarded.length, 1);
  assert.equal(forwarded[0].method, "tools/list");

  // Removing either opt-in never changes the normal six-tool baseline.
  delete env.UDB_ENABLE_OWNER_TOOLS;
  const reduced = await handleMcp(makeRequest(72, "tools/list"),
    env, DEVICE, stub, fetch, access());
  assert.deepEqual((await reduced.json()).result.tools.map((tool) => tool.name),
    READ_TOOLS);
  assert.equal(forwarded.length, 2);
});
