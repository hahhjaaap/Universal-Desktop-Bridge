import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { handleMcp } from "../src/mcp.js";
import { edgeCatalog, edgeCatalogSupported } from "../src/edge-discovery.js";
import { OWNER_TOOLS } from "../src/owner-tools.js";
import { READ_TOOLS } from "../src/read-tools.js";

const manifest = JSON.parse(readFileSync(
  new URL("../tool-catalog.json", import.meta.url), "utf8",
));
const id = "b".repeat(32);
const url = "https://udb-staging.workers.dev/v1/devices/" + id + "/mcp";
const aud = "test-cloudflare-access-audience";
const access = { aud, getIdentity: async () => ({ email: "owner@example.test" }) };

function env(tools = ["bridge_status", "read_file"]) {
  return {
    UDB_AUTH_MODE: "cloudflare-access",
    UDB_ACCESS_AUD: aud,
    UDB_EDGE_READ_CATALOG: "true",
    UDB_DEVICE_GRANTS: JSON.stringify({ [id]: { "owner@example.test": tools } }),
  };
}
function request(method, params = {}, rpcId = 1, headers = {}) {
  return new Request(url, { method: "POST", headers: {
    "content-type": "application/json", ...headers,
  }, body: JSON.stringify({ jsonrpc: "2.0", id: rpcId, method, params }) });
}
function offlineStub() {
  let calls = 0;
  return {
    get calls() { return calls; },
    fetch: async () => {
      calls++;
      return Response.json({ error: "device_offline" }, { status: 503 });
    },
  };
}

test("owner-authorized edge can initialize and discover scoped READ catalog offline", async () => {
  const stub = offlineStub();
  const e = env(["bridge_status", "read_file", "computer_process"]);
  const init = await handleMcp(request("initialize", {
    protocolVersion: "2025-11-25", capabilities: {},
  }), e, id, stub, fetch, access);
  assert.equal(init.status, 200);
  const handshake = (await init.json()).result;
  assert.equal(handshake.serverInfo.name, "udb-cloud-edge-discovery");
  assert.equal(handshake.protocolVersion, "2025-11-25");
  assert.ok(!JSON.stringify(handshake).includes("windows_device_verified"));

  const listing = await handleMcp(request("tools/list"), e, id, stub, fetch, access);
  assert.equal(listing.status, 200);
  const catalog = (await listing.json()).result.tools;
  assert.deepEqual(catalog.map(tool => tool.name), ["bridge_status", "read_file"]);
  assert.equal(catalog[0].inputSchema.type, "object");
  assert.deepEqual(catalog[0].inputSchema.properties, {});
  assert.deepEqual(catalog[1].inputSchema.required, ["project"]);
  assert.ok(catalog[1].inputSchema.oneOf.some((branch) =>
    branch.required?.includes("path")));
  assert.ok(catalog[1].inputSchema.oneOf.some((branch) =>
    branch.required?.includes("paths")));
  assert.ok(catalog.every(tool => tool.annotations.readOnlyHint &&
    tool.securitySchemes[0].scopes[0] === "udb:read"));
  assert.equal(stub.calls, 0, "discovery must not depend on an offline socket");
});

test("a fully granted owner can discover all 59 generated tools while Windows is offline", async () => {
  const stub = offlineStub();
  const e = {
    ...env(READ_TOOLS),
    UDB_ENABLE_OWNER_TOOLS: "true",
    UDB_EDGE_TOOL_CATALOG: "true",
    UDB_OWNER_TOOL_GRANTS: JSON.stringify({
      [id]: { "owner@example.test": OWNER_TOOLS },
    }),
  };
  const listing = await handleMcp(request("tools/list"), e, id, stub, fetch, access);
  assert.equal(listing.status, 200);
  const tools = (await listing.json()).result.tools;
  assert.equal(tools.length, 59);
  assert.deepEqual(tools.map((tool) => tool.name).sort(),
    manifest.tools.map((tool) => tool.name).sort());
  assert.ok(tools.some((tool) => tool.name === "computer_desktop"));
  assert.ok(tools.some((tool) => tool.name === "file_transfer"));
  assert.ok(tools.some((tool) => tool.name === "spreadsheet"));
  assert.equal(stub.calls, 0);
});

test("offline bridge_status uses an honest MCP tool error, not a fake device", async () => {
  const stub = offlineStub();
  const result = await handleMcp(request("tools/call", {
    name: "bridge_status", arguments: {},
  }), env(), id, stub, fetch, access);
  assert.equal(result.status, 200);
  const rpc = await result.json();
  assert.equal(rpc.result.isError, true);
  assert.deepEqual(rpc.result.structuredContent, {
    windows_device_verified: false, connection: "offline", reason: "device_offline",
  });
  assert.equal(stub.calls, 1);
});

test("online read RPC still goes through the real device unchanged", async () => {
  const calls = [];
  const stub = { fetch: async req => {
    const rpc = await req.json();
    calls.push(rpc);
    return Response.json({ jsonrpc: "2.0", id: rpc.id,
      result: { connected: true, live_device_proof: "synthetic" } });
  } };
  const response = await handleMcp(request("tools/call", {
    name: "bridge_status", arguments: {},
  }), env(), id, stub, fetch, access);
  assert.equal(response.status, 200);
  assert.deepEqual((await response.json()).result,
    { connected: true, live_device_proof: "synthetic" });
  assert.deepEqual(calls.map(x => x.method), ["tools/call"]);
});

test("other reads fail closed offline; uncertain outcomes never get synthesized", async () => {
  const offline = offlineStub();
  const read = await handleMcp(request("tools/call", {
    name: "read_file", arguments: { project: "fixture", path: "README.md" },
  }), env(), id, offline, fetch, access);
  assert.equal(read.status, 503);
  assert.equal((await read.json()).diagnostics.reason, "device_offline");

  const uncertain = await handleMcp(request("tools/call", {
    name: "bridge_status", arguments: {},
  }), env(), id, { fetch: async () => Response.json({
    error: "device_disconnected_outcome_unknown",
  }, { status: 503 }) }, fetch, access);
  assert.equal(uncertain.status, 503);
  assert.equal((await uncertain.json()).diagnostics.reason,
    "device_disconnected_outcome_unknown");
});

test("no authentication, no grants, or no explicit flag means no offline discovery", async () => {
  const stub = offlineStub();
  assert.equal((await handleMcp(request("tools/list"), env(), id,
    stub, fetch, { aud, getIdentity: async () => ({
      email: "someoneelse@example.test",
    }) })).status, 403);
  assert.equal(stub.calls, 0);
  const otherDevice = "c".repeat(32);
  assert.equal((await handleMcp(request("tools/list"), env(), otherDevice,
    stub, fetch, access)).status, 403);
  assert.equal(stub.calls, 0);

  const disabled = env();
  delete disabled.UDB_EDGE_READ_CATALOG;
  const init = await handleMcp(request("initialize", {
    protocolVersion: "2025-11-25",
  }), disabled, id, stub, fetch, access);
  assert.equal(init.status, 503);
  assert.equal(stub.calls, 1);
});

test("catalog never reflects unknown names and returns privileged tools only for exact grants", () => {
  const selected = edgeCatalog([
    "computer_process", "admin_rpc", "bridge_status", "read_file", "search_files",
  ]);
  assert.deepEqual(selected.map(t => t.name),
    ["bridge_status", "read_file", "search_files", "computer_process"]);
  assert.deepEqual(edgeCatalog(null), []);
  assert.deepEqual(edgeCatalog(["admin_rpc"]), []);
  assert.deepEqual(edgeCatalog(["propose_file_write"]).map(t => t.name),
    ["propose_file_write"]);
});

test("full edge catalog requires explicit opt-in and a nonempty exact grant", () => {
  assert.equal(edgeCatalogSupported({ UDB_EDGE_TOOL_CATALOG: "true" },
    { allowTools: ["bridge_status"], ownerTools: ["computer_process"] }), true);
  assert.equal(edgeCatalogSupported({ UDB_EDGE_TOOL_CATALOG: "true" },
    { allowTools: [] }), false);
  assert.equal(edgeCatalogSupported({}, { allowTools: OWNER_TOOLS }), false);
});

test("modern read discovery carries exact per-request metadata, not device claims", async () => {
  const rpc = {
    jsonrpc: "2.0", id: "test-id", method: "tools/list",
    params: { _meta: {
      "io.modelcontextprotocol/protocolVersion": "2026-07-28",
      "io.modelcontextprotocol/clientCapabilities": {},
    } },
  };
  const req = new Request(url, { method: "POST",
    headers: { "MCP-Protocol-Version": "2026-07-28",
      "Mcp-Method": "tools/list" },
    body: JSON.stringify(rpc),
  });
  const stub = offlineStub();
  const response = await handleMcp(req, env(["list_projects"]), id, stub, fetch, access);
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.deepEqual(body.result.tools.map(t => t.name), ["list_projects"]);
  assert.equal(body.result.resultType, "complete");
  assert.equal(body.result.cacheScope, "private");
  assert.equal(stub.calls, 0);
});
