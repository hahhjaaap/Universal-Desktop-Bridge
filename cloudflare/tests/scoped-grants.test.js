import assert from "node:assert/strict";
import test from "node:test";
import { companionToolGrant } from "../src/companion-tools.js";
import { handleMcp } from "../src/mcp.js";
import { ownerToolGrant } from "../src/owner-tools.js";

const device = "a".repeat(32);
const email = "owner@example.test";
const principal = "https://udb-test.cloudflareaccess.com#12345678-1234-1234-1234-123456789abc";
const aud = "scoped-grants-example-audience";

for (const [kind, grant, tool] of [
  ["COMPANION", companionToolGrant, "file_operation"],
  ["OWNER", ownerToolGrant, "computer_files"],
]) {
  test(kind + " grants require an exact valid email or issuer-sub principal", () => {
    const env = { ["UDB_ENABLE_" + kind + "_TOOLS"]: "true" };
    const key = "UDB_" + kind + "_TOOL_GRANTS";
    const set = subject => { env[key] = JSON.stringify({ [device]: { [subject]: [tool] } }); };
    for (const subject of [email, principal]) {
      set(subject);
      assert.deepEqual(grant(env, device, subject), [tool]);
      for (const different of ["prefix" + subject, subject + ".test", subject.toUpperCase()]) {
        assert.deepEqual(grant(env, device, different), []);
      }
    }
    for (const invalid of ["has@two@signs", "owner@example.test\n", "s p@example.test",
      principal + "x", principal.replace("https:", "http:"),
      principal.replace(".cloudflareaccess.com", ".example.com"), "a".repeat(201) + "@example.test"]) {
      set(invalid);
      assert.deepEqual(grant(env, device, invalid), []);
    }
    for (const raw of ["{", "[]", "null", JSON.stringify({ [device]: { [email]: tool } })]) {
      env[key] = raw;
      assert.deepEqual(grant(env, device, email), []);
    }
  });
}

function gateway(companion, owner = []) {
  const forwarded = [];
  const env = {
    UDB_AUTH_MODE: "cloudflare-access", UDB_ACCESS_AUD: aud,
    UDB_DEVICE_GRANTS: JSON.stringify({ [device]: { [email]: ["bridge_status"] } }),
    UDB_ENABLE_COMPANION_TOOLS: "true", UDB_ENABLE_OWNER_TOOLS: "true",
    UDB_COMPANION_TOOL_GRANTS: JSON.stringify({ [device]: { [email]: companion } }),
    UDB_OWNER_TOOL_GRANTS: JSON.stringify({ [device]: { [email]: owner } }),
  };
  const run = (method, params) => handleMcp(new Request("https://fixture.test/v1/devices/" + device + "/mcp", {
    method: "POST", body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
  }), env, device, { async fetch(request) {
    const rpc = await request.json();
    forwarded.push(rpc);
    const result = rpc.method === "tools/list" ? { tools: [
      { name: "work_recovery", inputSchema: { type: "object" },
        annotations: { readOnlyHint: false, destructiveHint: false } },
      { name: "file_operation", inputSchema: { type: "object" },
        annotations: { readOnlyHint: true, destructiveHint: false } },
    ] } : { content: [] };
    return Response.json({ jsonrpc: "2.0", id: rpc.id, result });
  } }, fetch, { aud, getIdentity: async () => ({ email }) });
  return { forwarded, call: (name, args) => run("tools/call", { name, arguments: args }),
    list: () => run("tools/list", {}) };
}

test("a scoped grant authorizes only its exact action across canonical calls", async () => {
  const cases = [
    ["file_operation", "read", "copy"], ["virtual_pointer", "status", "click"],
    ["work_recovery", "inspect", "resume"], ["file_upload", "status", "commit"],
  ];
  const h = gateway(cases.map(([name, action]) => name + ":" + action),
    ["computer_files:read"]);
  for (const [name, allowed, denied] of [...cases, ["computer_files", "read", "write"]]) {
    for (const args of [{}, { action: 1 }, { action: denied }, { action: allowed + "x" }]) {
      assert.equal((await h.call(name, args)).status, 403);
    }
    assert.equal((await h.call(name, { action: allowed })).status, 200);
  }
  assert.deepEqual(h.forwarded.map(x => [x.params.name, x.params.arguments.action]),
    [...cases, ["computer_files", "read"]].map(([name, action]) => [name, action]));
});

test("a terminal interaction grant binds to the actual validated family action", async () => {
  const h = gateway(["terminal_interact:interact"]);
  assert.equal((await h.call("terminal_interact", { session_id: "fixture" })).status, 403);
  assert.equal((await h.call("terminal", { action: "start", params: {} })).status, 403);
  assert.equal((await h.call("terminal", { action: "interact", params: { session_id: "fixture" } })).status, 200);
  assert.deepEqual(h.forwarded[0].params, { name: "terminal_interact", arguments: { session_id: "fixture" } });
});

test("invalid scopes reject the matching subject grant, while bare grants keep existing behavior", async () => {
  const v = gateway(["file_operation", "file_upload:unknown"]);
  assert.equal((await v.call("file_operation", { action: "read" })).status, 403);
  assert.equal(v.forwarded.length, 0);
  const h = gateway(["file_operation", "file_operation:read"]);
  assert.equal((await h.call("file_operation", { action: "copy" })).status, 200);
});

test("multiplexed tool annotations stay conservative, including create-only recovery", async () => {
  const h = gateway(["file_operation:read", "work_recovery"]);
  const tools = (await (await h.list()).json()).result.tools;
  assert.deepEqual(tools.map(t => [t.name, t.annotations.readOnlyHint, t.annotations.destructiveHint]),
    [["work_recovery", false, true], ["file_operation", false, true]]);
});
