import assert from "node:assert/strict";
import test from "node:test";
import { deviceGrant } from "../src/oauth.js";
import { handleMcp } from "../src/mcp.js";

const DEVICE = "a".repeat(32);
const OTHER_DEVICE = "b".repeat(32);
const SUBJECT = "owner@example.test";
const OTHER_SUBJECT = "other@example.test";
const AUD = "strict-grant-test-app-audience";

const environment = (tools, flag = "true") => ({
  UDB_AUTH_MODE: "cloudflare-access",
  UDB_ACCESS_AUD: AUD,
  ...(flag === "absent" ? {} : { UDB_STRICT_LEGACY_GRANTS: flag }),
  UDB_DEVICE_GRANTS: JSON.stringify({
    [DEVICE]: { [SUBJECT]: tools },
  }),
});

const identity = (email = SUBJECT) => ({
  aud: AUD,
  getIdentity: async () => ({ email }),
});
const request = (device = DEVICE, tool = "read_file") => new Request(
  "https://test.workers.dev/v1/devices/" + device + "/mcp", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 17,
      method: "tools/call",
      params: { name: tool, arguments: { project: "fixture", path: "README.md" } },
    }),
  },
);

test("strict mode permits only explicit unique read tool names", () => {
  const valid = ["bridge_status", "list_projects", "read_file"];
  assert.deepEqual(deviceGrant(environment(valid), DEVICE, SUBJECT), valid);
  assert.deepEqual(deviceGrant(environment(valid), DEVICE, OTHER_SUBJECT), []);
  assert.deepEqual(deviceGrant(environment(valid), OTHER_DEVICE, SUBJECT), []);
  for (const malformed of [
    [], ["read_file", "computer_execute"], ["read_file", "unknown_tool"],
    ["read_file", "read_file"], ["read_file", 17], ["read_file", null],
    ["read_file", ""], ["read_file", " read_file"],
    ["bridge_status", "list_projects", "list_files", "read_file",
      "search_files", "check_python_syntax", "another"],
  ]) assert.deepEqual(deviceGrant(environment(malformed), DEVICE, SUBJECT), [],
    JSON.stringify(malformed));
});

test("migration flag is opt-in; mistyped values fail closed", () => {
  const malformed = ["read_file", "computer_execute"];
  assert.deepEqual(deviceGrant(environment(malformed, "absent"),
    DEVICE, SUBJECT), ["read_file"]);
  assert.deepEqual(deviceGrant(environment(malformed, "false"),
    DEVICE, SUBJECT), ["read_file"]);
  for (const invalid of ["TRUE", "", false, true, 1, null]) {
    assert.deepEqual(deviceGrant(environment(["read_file"], invalid),
      DEVICE, SUBJECT), []);
  }
  assert.deepEqual(deviceGrant(environment(["read_file"]),
    DEVICE, SUBJECT), ["read_file"]);
});

test("ten concurrent requests with an invalid strict grant deny before relay", async () => {
  const env = environment(["read_file", "computer_execute"]);
  const forwarded = [];
  const stub = { fetch: async (incoming) => {
    forwarded.push(await incoming.json());
    return Response.json({ jsonrpc: "2.0", id: 17, result: {} });
  } };
  const responses = await Promise.all(Array.from({ length: 10 }, () =>
    handleMcp(request(), env, DEVICE, stub, fetch, identity())));
  assert.deepEqual(responses.map((response) => response.status),
    Array(10).fill(403));
  assert.deepEqual(forwarded, []);
  // Repairing the exact per-subject grant allows only the explicitly named
  // scoped read operation; no write or desktop operation is ever allowed.
  env.UDB_DEVICE_GRANTS = JSON.stringify({
    [DEVICE]: { [SUBJECT]: ["read_file"] },
  });
  const response = await handleMcp(request(), env, DEVICE, stub, fetch, identity());
  assert.equal(response.status, 200);
  assert.equal(forwarded.length, 1);
  const forbidden = await handleMcp(request(DEVICE, "computer_execute"),
    env, DEVICE, stub, fetch, identity());
  assert.equal(forbidden.status, 403);
  assert.equal(forwarded.length, 1);
});

test("strict legacy flag cannot override authoritative tenant policy", () => {
  const env = environment(["read_file"]);
  env.UDB_TENANT_POLICY = "{}";
  assert.deepEqual(deviceGrant(env, DEVICE, SUBJECT), []);
});
