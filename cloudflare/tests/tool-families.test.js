import assert from "node:assert/strict";
import test from "node:test";
import { handleMcp } from "../src/mcp.js";
import { COMPANION_TOOLS } from "../src/companion-tools.js";
import { FAMILIES, authorizedFamilyCatalog, consolidateFamilies, resolveFamily } from "../src/tool-families.js";

const DEVICE = "a".repeat(32), SUBJECT = "owner@example.test", AUD = "family-test-audience";
const identity = { aud: AUD, getIdentity: async () => ({ email: SUBJECT }) };
const legacy = FAMILIES.flatMap(group => [
  ...(group.extend ? [group.name] : []), ...Object.values(group.actions),
]).map(name => ({ name, description: name,
  inputSchema: { type: "object", properties: { marker: { type: "string" } } } }));

function fixture(granted, modern = false) {
  const env = { UDB_AUTH_MODE: "cloudflare-access", UDB_ACCESS_AUD: AUD,
    UDB_DEVICE_GRANTS: JSON.stringify({ [DEVICE]: { [SUBJECT]: ["bridge_status"] } }),
    UDB_ENABLE_COMPANION_TOOLS: "true", UDB_ENABLE_OWNER_TOOLS: "true" };
  const setGrants = names => {
    env.UDB_COMPANION_TOOL_GRANTS = JSON.stringify({ [DEVICE]: { [SUBJECT]: names.filter(n => COMPANION_TOOLS.includes(n)) } });
    env.UDB_OWNER_TOOL_GRANTS = JSON.stringify({ [DEVICE]: { [SUBJECT]: names.filter(n => !COMPANION_TOOLS.includes(n)) } });
  };
  setGrants(granted);
  const calls = [];
  const stub = { async fetch(req) {
    const rpc = await req.json(); calls.push(rpc);
    return Response.json({ jsonrpc: "2.0", id: rpc.id,
      result: rpc.method === "tools/list" ? { tools: modern ? consolidateFamilies(legacy) : legacy }
        : { content: [{ type: "text", text: "fixture" }] } });
  } };
  async function call(name, args = {}) {
    const rpc = { jsonrpc: "2.0", id: 1, method: name ? "tools/call" : "tools/list",
      params: name ? { name, arguments: args } : {} };
    return handleMcp(new Request(`https://unit.workers.dev/v1/devices/${DEVICE}/mcp`, {
      method: "POST", body: JSON.stringify(rpc),
    }), env, DEVICE, stub, fetch, identity);
  }
  return { calls, call, setGrants };
}

for (const modern of [false, true]) {
  test(`partial grants advertise and dispatch only the original allowed action (${modern ? "new" : "old"} Windows)`, async () => {
    const f = fixture(["terminal_read"], modern);
    const tools = (await (await f.call(null)).json()).result.tools;
    assert.deepEqual(tools.map(t => t.name), ["terminal"]);
    assert.deepEqual(tools[0].inputSchema.properties.action.enum, ["read"]);
    assert.equal(tools[0].inputSchema.oneOf.length, 1);
    f.calls.length = 0;
    assert.equal((await f.call("terminal", { action: "start", params: { program: "blocked" } })).status, 403);
    assert.equal((await f.call("terminal_start", { program: "blocked" })).status, 403);
    assert.equal(f.calls.length, 0);
    const args = { action: "read", params: { session_id: "owned", offset: 12 } };
    assert.equal((await f.call("terminal", args)).status, 200);
    assert.equal(f.calls.length, 1);
    assert.deepEqual(f.calls[0].params, { name: "terminal_read", arguments: args.params });
    f.setGrants([]); f.calls.length = 0;
    assert.equal((await f.call("terminal", args)).status, 403);
    assert.equal(f.calls.length, 0);
  });
}

test("every family action requires its specific existing grant, never a sibling grant", async () => {
  for (const group of FAMILIES) for (const [action, target] of Object.entries(group.actions)) {
    const f = fixture([target]);
    const args = group.extend ? { action, session_id: "s", tab_id: "t" }
      : { action, params: { marker: "original" } };
    const before = structuredClone(args);
    assert.equal((await f.call(group.name, args)).status, 200, `${group.name}:${action}`);
    assert.deepEqual(args, before);
    assert.equal(f.calls.length, 1);
    assert.equal(f.calls[0].params.name, target);
    for (const [otherAction] of Object.entries(group.actions).filter(([a]) => a !== action)) {
      const denied = { action: otherAction, params: {} };
      assert.equal((await f.call(group.name, denied)).status, 403);
    }
    assert.equal(f.calls.length, 1);
  }
});

test("browser screenshot and browser interaction retain independent grants", async () => {
  for (const modern of [false, true]) {
    const capture = { action: "screenshot", session_id: "owned", tab_id: "tab" };
    const f = fixture(["host_browser"], modern);
    const schema = (await (await f.call(null)).json()).result.tools[0].inputSchema;
    assert.equal(schema.oneOf.length, 1);
    assert.equal(schema.oneOf[0].properties.action.not.const, "screenshot");
    f.calls.length = 0;
    assert.equal((await f.call("host_browser", capture)).status, 403);
    assert.equal(f.calls.length, 0);
    f.setGrants(["host_screenshot"]);
    assert.equal((await f.call("host_browser", { action: "open", url: "https://example.test" })).status, 403);
    const onlyCapture = (await (await f.call(null)).json()).result.tools[0].inputSchema;
    assert.deepEqual(onlyCapture.properties.action, { const: "screenshot" });
    f.calls.length = 0;
    assert.equal((await f.call("host_browser", capture)).status, 200);
    assert.deepEqual(f.calls[0].params, { name: "host_screenshot", arguments: { session_id: "owned", tab_id: "tab" } });
  }
});

test("ambiguous/prototype action names and extra wrapper fields never dispatch", async () => {
  const f = fixture(["terminal_start"]);
  for (const args of [{}, { action: "start", params: [] }, { action: "toString", params: {} },
    { action: "__proto__", params: {} }, { action: "start", params: {}, extra: true }]) {
    assert.equal((await f.call("terminal", args)).status, 400);
  }
  assert.equal(f.calls.length, 0);
});

test("discovery and argument translation do not mutate shared schemas or request objects", () => {
  const original = structuredClone(legacy);
  const args = { action: "read", params: { session_id: "s" } };
  const result = resolveFamily("terminal", args);
  result.arguments.session_id = "changed";
  assert.equal(args.params.session_id, "s");
  const tools = consolidateFamilies(legacy);
  const before = structuredClone(tools);
  authorizedFamilyCatalog(tools, ["terminal_read"]);
  assert.deepEqual(tools, before);
  assert.deepEqual(legacy, original);
});
