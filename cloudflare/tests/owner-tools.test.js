import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { OWNER_TOOLS, ownerToolGrant } from "../src/owner-tools.js";
import { READ_TOOLS } from "../src/read-tools.js";

const DEVICE = "a".repeat(32);
const OTHER = "b".repeat(32);
const SUBJECT = "owner@example.test";
const envFor = (tools = OWNER_TOOLS) => ({
  UDB_ENABLE_OWNER_TOOLS: "true",
  UDB_OWNER_TOOL_GRANTS: JSON.stringify({
    [DEVICE]: { [SUBJECT]: tools },
  }),
});

test("the opt-in names precisely match the defined local FastMCP catalog", () => {
  const python = readFileSync(new URL("../../src/udb/server.py", import.meta.url), "utf8");
  const local = [...python.matchAll(
    /@mcp\.tool\([\s\S]*?\)\s*\n\s*(?:async\s+)?def\s+([a-z][a-z0-9_]*)\s*\(/g,
  )].map((match) => match[1]);
  assert.ok(local.length > 30, "unexpectedly small local MCP catalog");
  assert.equal(new Set(local).size, local.length);
  const named = [...READ_TOOLS, ...OWNER_TOOLS];
  assert.equal(new Set(named).size, named.length);
  assert.deepEqual([...named].sort(), local.sort());
});

test("no owner tool is granted without all opt-in boundaries", () => {
  const allowed = envFor(["computer_files", "propose_file_write"]);
  assert.deepEqual(ownerToolGrant(allowed, DEVICE, SUBJECT),
    ["computer_files", "propose_file_write"]);
  assert.deepEqual(ownerToolGrant({ ...allowed, UDB_ENABLE_OWNER_TOOLS: "false" },
    DEVICE, SUBJECT), []);
  assert.deepEqual(ownerToolGrant({ ...allowed, UDB_ENABLE_OWNER_TOOLS: true },
    DEVICE, SUBJECT), []);
  assert.deepEqual(ownerToolGrant({ UDB_ENABLE_OWNER_TOOLS: "true" },
    DEVICE, SUBJECT), []);
  assert.deepEqual(ownerToolGrant({ ...allowed, UDB_TENANT_POLICY: "{}" },
    DEVICE, SUBJECT), []);
});

test("subject and device grants never bleed across owners", () => {
  const env = envFor(["computer_execute"]);
  for (const [id, subject] of [
    [OTHER, SUBJECT], [DEVICE, "other@example.test"],
    [DEVICE, "not-an-email"], ["garbage", SUBJECT],
  ]) assert.deepEqual(ownerToolGrant(env, id, subject), []);
});

test("malformed and unknown tool grants fail entirely closed", () => {
  for (const tools of [
    [], ["computer_execute", "computer_execute"], ["computer_execute", "unsafe_owner_admin"],
    ["bridge_status"], [3], OWNER_TOOLS.concat(["unauthorized_tool"]),
  ]) assert.deepEqual(ownerToolGrant(envFor(tools), DEVICE, SUBJECT), []);
  for (const raw of [
    "not JSON", "[]", "null", "{" + "a".repeat(16384) + "}",
    JSON.stringify({ [DEVICE]: { [SUBJECT]: "computer_execute" } }),
  ]) assert.deepEqual(ownerToolGrant({
    UDB_ENABLE_OWNER_TOOLS: "true", UDB_OWNER_TOOL_GRANTS: raw,
  }, DEVICE, SUBJECT), []);
});
