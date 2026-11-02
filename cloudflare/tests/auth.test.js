import test from "node:test";
import assert from "node:assert/strict";
import { adminAuthorized, bearer, fixedEqual, validRpc, readJson, DEVICE_ID } from "../src/auth.js";

test("admin endpoints reject absent and short keys", () => {
  const req = new Request("https://example.com", { headers: { Authorization: "Bearer " + "x".repeat(40) } });
  assert.equal(adminAuthorized(req, {}), false);
  assert.equal(adminAuthorized(req, { UDB_ADMIN_KEY: "short" }), false);
  assert.equal(adminAuthorized(req, { UDB_ADMIN_KEY: "y".repeat(40) }), false);
  assert.equal(adminAuthorized(req, { UDB_ADMIN_KEY: "x".repeat(40) }), true);
});

test("bearer token rejects whitespace and malformed authorization", () => {
  assert.equal(bearer(new Request("https://example.com")), null);
  assert.equal(bearer(new Request("https://example.com", { headers: { Authorization: "Basic abc" } })), null);
  assert.equal(bearer(new Request("https://example.com", { headers: { Authorization: "Bearer bad key" } })), null);
  assert.equal(fixedEqual("abc", "abc"), true);
  assert.equal(fixedEqual("abc", "abd"), false);
});

test("strict device ids", () => {
  assert.equal(DEVICE_ID.test("0".repeat(32)), true);
  assert.equal(DEVICE_ID.test("../other"), false);
});

test("RPC allowlist requires real request id and tools/call arguments", () => {
  const p = { jsonrpc: "2.0", method: "tools/list", id: 1 };
  assert.equal(validRpc(p), true);
  assert.equal(validRpc({ ...p, method: "arbitrary/execute" }), false);
  assert.equal(validRpc({ ...p, id: null }), false);
  assert.equal(validRpc({ ...p, method: "tools/call", params: {} }), false);
  assert.equal(validRpc({ ...p, method: "tools/call", params: { name: "bridge_status", arguments: {} } }), true);
});

test("oversized request body refused even without content-length", async () => {
  const req = new Request("https://example.com", { method: "POST", body: "x".repeat(256 * 1024 + 1) });
  await assert.rejects(readJson(req), /body_too_large/);
});
