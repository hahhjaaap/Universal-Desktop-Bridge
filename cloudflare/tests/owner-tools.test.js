import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { OWNER_TOOLS, ownerToolGrant } from "../src/owner-tools.js";
import { READ_TOOLS } from "../src/read-tools.js";

const DEVICE = "a".repeat(32);
const OTHER = "b".repeat(32);
const SUBJECT = "owner@example.test";
const manifest = JSON.parse(readFileSync(
  new URL("../tool-catalog.json", import.meta.url), "utf8",
));
const envFor = (tools = OWNER_TOOLS) => ({
  UDB_ENABLE_OWNER_TOOLS: "true",
  UDB_OWNER_TOOL_GRANTS: JSON.stringify({
    [DEVICE]: { [SUBJECT]: tools },
  }),
});

test("the read and owner grants exactly cover the 59 generated public tools", () => {
  const named = [...READ_TOOLS, ...OWNER_TOOLS];
  assert.equal(manifest.toolCount, 59);
  assert.equal(new Set(named).size, 59);
  assert.deepEqual([...named].sort(), manifest.tools.map((tool) => tool.name).sort());
  assert.equal(READ_TOOLS.length, 6);
  assert.equal(OWNER_TOOLS.length, 53);
  assert.deepEqual([...OWNER_TOOLS].sort(),
    manifest.tools.filter((tool) => !tool.policy.defaultEnabled)
      .map((tool) => tool.name).sort());
});

test("no owner tool is granted without all opt-in boundaries", () => {
  const allowed = envFor(["computer_process", "propose_file_write"]);
  assert.deepEqual(ownerToolGrant(allowed, DEVICE, SUBJECT),
    ["computer_process", "propose_file_write"]);
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
  const env = envFor(["computer_process"]);
  for (const [id, subject] of [
    [OTHER, SUBJECT], [DEVICE, "other@example.test"],
    [DEVICE, "not-an-email"], ["garbage", SUBJECT],
  ]) assert.deepEqual(ownerToolGrant(env, id, subject), []);
});

test("malformed and unknown tool grants fail entirely closed", () => {
  for (const tools of [
    [], ["computer_process", "computer_process"],
    ["computer_process", "unsafe_owner_admin"],
    ["bridge_status"], [3], OWNER_TOOLS.concat(["unauthorized_tool"]),
  ]) assert.deepEqual(ownerToolGrant(envFor(tools), DEVICE, SUBJECT), []);
  for (const raw of [
    "not JSON", "[]", "null", "{" + "a".repeat(32768) + "}",
    JSON.stringify({ [DEVICE]: { [SUBJECT]: "computer_process" } }),
  ]) assert.deepEqual(ownerToolGrant({
    UDB_ENABLE_OWNER_TOOLS: "true", UDB_OWNER_TOOL_GRANTS: raw,
  }, DEVICE, SUBJECT), []);
});
