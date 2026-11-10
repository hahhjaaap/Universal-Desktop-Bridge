import assert from "node:assert/strict";
import test from "node:test";
import { handleMcp } from "../src/mcp.js";
import { companionToolGrant, COMPANION_TOOLS } from "../src/companion-tools.js";
import { OWNER_TOOLS } from "../src/owner-tools.js";
import { READ_TOOLS } from "../src/read-tools.js";

const DEVICE = "a".repeat(32);
const OTHER_DEVICE = "b".repeat(32);
const SUBJECT = "owner@example.test";
const OTHER_SUBJECT = "other@example.test";
const AUD = "unified-mcp-59-synthetic-audience";
const LEGACY_ALIASES = [
  "read_files", "propose_text_edit", "computer_utilities", "computer_execute",
];
const publicCore = OWNER_TOOLS.filter(name => !LEGACY_ALIASES.includes(name));
const allPublicNames = [...READ_TOOLS, ...publicCore, ...COMPANION_TOOLS];

const readGrants = { [DEVICE]: { [SUBJECT]: READ_TOOLS } };
const coreGrants = { [DEVICE]: { [SUBJECT]: OWNER_TOOLS } };
const companionGrants = { [DEVICE]: { [SUBJECT]: COMPANION_TOOLS } };

function env() {
  return {
    UDB_AUTH_MODE: "cloudflare-access",
    UDB_ACCESS_AUD: AUD,
    UDB_EDGE_READ_CATALOG: "true",
    UDB_DEVICE_GRANTS: JSON.stringify(readGrants),
    UDB_ENABLE_OWNER_TOOLS: "true",
    UDB_OWNER_TOOL_GRANTS: JSON.stringify(coreGrants),
    UDB_ENABLE_COMPANION_TOOLS: "true",
    UDB_COMPANION_TOOL_GRANTS: JSON.stringify(companionGrants),
  };
}
const identity = (email = SUBJECT) => ({
  aud: AUD, getIdentity: async () => ({ email }),
});
function request(method, name = null, device = DEVICE, id = 1) {
  return new Request("https://stage.example.workers.dev/v1/devices/" + device + "/mcp", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({
      jsonrpc: "2.0", id, method,
      params: name ? { name, arguments: { fixture: true } } : {},
    }),
  });
}
function relay() {
  const calls = [];
  const stub = { async fetch(req) {
    const rpc = await req.json();
    calls.push(rpc);
    const result = rpc.method === "initialize"
      ? { protocolVersion: "2025-11-25" }
      : rpc.method === "tools/list"
        ? { tools: allPublicNames.map(name => ({
          name,
          inputSchema: { type: "object",
            properties: { fixture: { type: "boolean" } } },
        })) }
        : { content: [{ type: "text", text: "local owner approval required" }],
          isError: true };
    return Response.json({ jsonrpc: "2.0", id: rpc.id, result });
  } };
  return { stub, calls };
}

test("public inventory has 59 distinct tools and no duplicate Companion names", () => {
  assert.equal(READ_TOOLS.length, 6);
  assert.equal(OWNER_TOOLS.length, 30);
  assert.equal(COMPANION_TOOLS.length, 27);
  assert.equal(allPublicNames.length, 59);
  assert.equal(new Set(allPublicNames).size, 59);
  for (const name of COMPANION_TOOLS)
    assert.ok(!READ_TOOLS.includes(name) && !OWNER_TOOLS.includes(name));
});

test("59 tools discovered through one MCP endpoint without auto-executing them", async () => {
  const e = env();
  const { stub, calls } = relay();
  const initialize = await handleMcp(request("initialize"), e, DEVICE, stub,
    fetch, identity());
  assert.equal(initialize.status, 200);
  assert.equal((await initialize.json()).result.serverInfo.name,
    "udb-cloud-owner-gated");
  const result = await handleMcp(request("tools/list", null, DEVICE, 2), e,
    DEVICE, stub, fetch, identity());
  assert.equal(result.status, 200);
  const tools = (await result.json()).result.tools;
  assert.equal(tools.length, 59);
  assert.deepEqual(tools.map(tool => tool.name), allPublicNames);
  assert.ok(tools.every(tool => tool.inputSchema.properties.fixture.type === "boolean"));
  for (const tool of tools) {
    assert.deepEqual(tool.securitySchemes[0].scopes,
      READ_TOOLS.includes(tool.name) ? ["udb:read"] : []);
  }
  assert.deepEqual(calls.map(rpc => rpc.method), ["initialize", "tools/list"]);
  for (const name of ["terminal_start", "spreadsheet", "file_transfer"]) {
    const reply = await handleMcp(request("tools/call", name, DEVICE, 3),
      e, DEVICE, stub, fetch, identity());
    assert.equal(reply.status, 200);
    const output = (await reply.json()).result;
    assert.equal(output.isError, true);
    assert.match(output.content[0].text, /local owner approval/);
  }
  assert.deepEqual(calls.slice(2).map(rpc => rpc.params.name),
    ["terminal_start", "spreadsheet", "file_transfer"]);
});

test("default, revoked, wrong-device and cross-owner Companion calls never reach Windows", async () => {
  const e = env();
  const { stub, calls } = relay();
  for (const changed of [
    { UDB_ENABLE_COMPANION_TOOLS: undefined },
    { UDB_ENABLE_COMPANION_TOOLS: "false" },
    { UDB_COMPANION_TOOL_GRANTS: undefined },
    { UDB_COMPANION_TOOL_GRANTS: "{}" },
    { UDB_COMPANION_TOOL_GRANTS: JSON.stringify({
      [OTHER_DEVICE]: { [SUBJECT]: COMPANION_TOOLS },
    }) },
    { UDB_COMPANION_TOOL_GRANTS: JSON.stringify({
      [DEVICE]: { [OTHER_SUBJECT]: COMPANION_TOOLS },
    }) },
    { UDB_DEVICE_GRANTS: "{}" },
    { UDB_TENANT_POLICY: "{}" },
  ]) {
    const reply = await handleMcp(request("tools/call", "terminal_start"),
      { ...e, ...changed }, DEVICE, stub, fetch, identity());
    assert.equal(reply.status, 403);
  }
  for (const [device, email] of [
    [OTHER_DEVICE, SUBJECT], [DEVICE, OTHER_SUBJECT],
  ]) {
    const reply = await handleMcp(request("tools/call", "file_write", device),
      e, device, stub, fetch, identity(email));
    assert.equal(reply.status, 403);
  }
  assert.equal(calls.length, 0);
});

test("Companion tool grants reject unknown names, duplicates, wrong shape, and non-string flags", () => {
  const e = env();
  assert.deepEqual(companionToolGrant(e, DEVICE, SUBJECT), COMPANION_TOOLS);
  for (const invalid of [
    ["terminal_start", "terminal_start"],
    ["terminal_start", "unknown_tool"],
    ["read_file"],
    [],
    "terminal_start",
    [3],
  ]) assert.deepEqual(companionToolGrant({
    ...e, UDB_COMPANION_TOOL_GRANTS: JSON.stringify({
      [DEVICE]: { [SUBJECT]: invalid },
    }),
  }, DEVICE, SUBJECT), []);
  for (const raw of ["null", "[]", "not-json", "{" + "x".repeat(16384) + "}"])
    assert.deepEqual(companionToolGrant({
      ...e, UDB_COMPANION_TOOL_GRANTS: raw,
    }, DEVICE, SUBJECT), []);
  assert.deepEqual(companionToolGrant({
    ...e, UDB_ENABLE_COMPANION_TOOLS: true,
  }, DEVICE, SUBJECT), []);
});
