import assert from "node:assert/strict";
import test from "node:test";
import { handleMcp } from "../src/mcp.js";

const DEVICE = "a".repeat(32);
const SUBJECT = "owner@example.test";
const PROJECT = "udb-staging-fixture";
const AUD = "scoped-fixture-aud";
const URL = "https://staging.workers.dev/v1/devices/" + DEVICE + "/mcp";
const identity = (email = SUBJECT) => ({
  aud: AUD, getIdentity: async () => ({ email }),
});
const env = () => ({
  UDB_AUTH_MODE: "cloudflare-access",
  UDB_ACCESS_AUD: AUD,
  UDB_DEVICE_GRANTS: "{}",
  UDB_STAGING_FIXTURE_READ_GRANT: JSON.stringify({
    device_id: DEVICE, subject: SUBJECT, project: PROJECT,
  }),
});

function harness() {
  const forwarded = [];
  const stub = { async fetch(request) {
    const rpc = await request.json();
    forwarded.push(rpc);
    let result = { content: [{ type: "text", text: "fixture-content" }] };
    if (rpc.params?.name === "list_projects") {
      const items = [{ id: PROJECT, writable: false },
        { id: "private-project", writable: true }];
      result = { content: [{ type: "text", text: JSON.stringify(items) }],
        structuredContent: { result: items } };
    }
    return Response.json({ jsonrpc: "2.0", id: rpc.id, result });
  } };
  const call = (name, args = {}, changedEnv = env(), owner = identity()) =>
    handleMcp(new Request(URL, { method: "POST", body: JSON.stringify({
      jsonrpc: "2.0", id: 1, method: "tools/call",
      params: { name, arguments: args },
    }) }), changedEnv, DEVICE, stub, fetch, owner);
  return { forwarded, call };
}

test("fixture grant is exact-owner exact-device and never bypasses tenant policy", async () => {
  const { forwarded, call } = harness();
  const good = { project: PROJECT, path: "README.md" };
  for (const [policy, owner] of [
    [{ ...env(), UDB_STAGING_FIXTURE_READ_GRANT: "{}" }, identity()],
    [{ ...env(), UDB_STAGING_FIXTURE_READ_GRANT: JSON.stringify({
      device_id: "b".repeat(32), subject: SUBJECT, project: PROJECT,
    }) }, identity()],
    [env(), identity("other@example.test")],
    [{ ...env(), UDB_TENANT_POLICY: "{}" }, identity()],
  ]) {
    const denied = await call("read_file", good, policy, owner);
    assert.notEqual(denied.status, 200);
  }
  assert.equal(forwarded.length, 0);
});

test("fixture grant restricts read_file to the approved README and registered project", async () => {
  const { forwarded, call } = harness();
  for (const [name, args] of [
    ["read_file", { project: PROJECT, path: ".env" }],
    ["read_file", { project: PROJECT, path: "../outside.txt" }],
    ["read_file", { project: PROJECT, paths: ["README.md", ".env"] }],
    ["read_file", { project: PROJECT, path: "README.md", paths: ["README.md"] }],
    ["read_file", { project: "private-project", path: "README.md" }],
    ["list_files", { project: "private-project" }],
  ]) {
    const denied = await call(name, args);
    assert.equal(denied.status, 403, name + " should be rejected");
  }
  assert.equal(forwarded.length, 0);
  const accepted = await call("read_file", { project: PROJECT, path: "README.md" });
  assert.equal(accepted.status, 200);
  assert.equal(forwarded.length, 1);
});

test("fixture grant suppresses other project names and write permissions", async () => {
  const { forwarded, call } = harness();
  const response = await call("list_projects");
  assert.equal(response.status, 200);
  const result = (await response.json()).result;
  assert.deepEqual(result.structuredContent.result, [{ id: PROJECT, writable: false }]);
  assert.deepEqual(forwarded.map(x => x.params.name), ["list_projects"]);
});
