import assert from "node:assert/strict";
import test from "node:test";
import { authorizeAccess } from "../src/access.js";
import { ENROLLED_CATALOG } from "../src/local-permissions.js";

const device = "b".repeat(32);
const team = "https://matrix-test.cloudflareaccess.com";
const aud = "test-authorize-matrix";
const email = "owner@example.test";
const uuid = "11111111-1111-4111-8111-111111111111";
const owner = `${team}#${uuid}`;
const otherOwner = `${team}#22222222-2222-4222-8222-222222222222`;
const fixtureProject = "udb-staging-fixture";
const fixtureTools = ["bridge_status", "list_projects", "list_files", "read_file",
  "search_files", "check_python_syntax"];
const scopedTools = ["computer_files", "file_operation"];
const actionGrants = new Map([["computer_files", new Set(["stat"])],
  ["file_operation", new Set(["list"])]]);
const axes = {
  mode: ["email", "issuer-sub"],
  runtime: ["absent", "ok", "throws", "no-getter"],
  jwt: ["absent", "valid", "invalid"],
  fleet: ["absent", "matches", "mismatches"],
  enrolled: [false, true],
  tenant: ["unset", "denied", "granted"],
  fixture: [false, true],
  staticGrant: [false, true],
};

function config(row, subject) {
  const grant = entries => JSON.stringify({ [device]: { [subject]: entries } });
  return { UDB_ACCESS_AUD: aud, UDB_ACCESS_TEAM_DOMAIN: team,
    // The email cases exercise the default configuration.
    ...(row.mode === "issuer-sub" ? { UDB_ACCESS_PRINCIPAL_MODE: row.mode } : {}),
    ...(row.tenant === "unset" ? {} : { UDB_TENANT_POLICY: JSON.stringify({
      version: 1, tenants: [{ id: "test-tenant", owners: [subject], members: [subject],
        devices: [{ id: device, grants: row.tenant === "granted" ?
          [{ subject, tools: ["list_files"] }] : [] }] }],
    }) }),
    ...(row.staticGrant ? { UDB_DEVICE_GRANTS: grant(["search_files"]) } : {}),
    ...(row.fixture ? { UDB_DEPLOYMENT_ENV: "staging", UDB_STAGING_FIXTURE_READ_GRANT:
      JSON.stringify({ device_id: device, subject, project: fixtureProject }) } : {}),
    UDB_ENABLE_OWNER_TOOLS: "true", UDB_ENABLE_COMPANION_TOOLS: "true",
    UDB_ENABLE_LOCAL_TOOL_SYNC: "true", UDB_OWNER_TOOL_GRANTS: grant(["computer_files:stat"]),
    UDB_COMPANION_TOOL_GRANTS: grant(["file_operation:list"]),
  };
}

function expectedIdentityDenial(row) {
  const assertionDenial = { absent: "access_assertion_malformed", invalid: "access_assertion_signature" };
  if (row.mode === "email") {
    if (row.runtime === "ok") return null;
    return row.jwt === "absent" ? "verified_identity_missing" : assertionDenial[row.jwt];
  }
  if (row.fleet === "absent") return assertionDenial[row.jwt];
  if (row.runtime === "throws") return "runtime unavailable";
  if (row.runtime !== "ok" || row.jwt !== "absent") {
    if (assertionDenial[row.jwt]) return assertionDenial[row.jwt];
  }
  return row.fleet === "mismatches" ? "access_denied" : null;
}

function expectedGrants(row, subject) {
  if (row.tenant === "granted") return { subject, allowTools: ["list_files"] };
  if (row.tenant === "denied") return null;
  const grants = { subject, ownerTools: scopedTools, actionGrants };
  if (row.staticGrant) return { ...grants, allowTools: ["search_files", ...scopedTools] };
  if (row.fixture && row.mode === "email") return { ...grants,
    allowTools: [...fixtureTools, ...scopedTools], stagingFixtureProject: fixtureProject };
  if (!row.enrolled) return null;
  const allowTools = ["bridge_status"];
  return row.mode === "email" || row.fleet === "matches" ?
    { subject, allowTools, enrolledOwner: true, catalogTools: ENROLLED_CATALOG } :
    { subject, allowTools };
}

function* combinations(entries, row = {}) {
  if (!entries.length) {
    yield row;
    return;
  }
  const [[axis, values], ...rest] = entries;
  for (const value of values) yield* combinations(rest, { ...row, [axis]: value });
}

test("Access identity and grants have explicit outcomes across all 1728 combinations", async () => {
  const algorithm = { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048,
    publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" };
  const pair = await crypto.subtle.generateKey(algorithm, true, ["sign", "verify"]);
  const jwk = await crypto.subtle.exportKey("jwk", pair.publicKey);
  const base64 = value => Buffer.from(value).toString("base64url");
  const header = base64(JSON.stringify({ alg: "RS256", kid: "matrix" }));
  const payload = base64(JSON.stringify({ email, sub: uuid, iss: team, aud,
    exp: Math.floor(Date.now() / 1000) + 120 }));
  const signed = `${header}.${payload}`;
  const signature = new Uint8Array(await crypto.subtle.sign(algorithm.name,
    pair.privateKey, new TextEncoder().encode(signed)));
  const valid = `${signed}.${base64(signature)}`;
  signature[0] ^= 1;
  const assertions = { valid, invalid: `${signed}.${base64(signature)}` };
  const fetchJwks = async () => Response.json({ keys: [{ ...jwk, kid: "matrix" }] });
  const runtimes = { ok: { aud, getIdentity: async () => ({ email, user_uuid: uuid }) },
    throws: { aud, getIdentity: async () => { throw new Error("runtime unavailable"); } },
    "no-getter": { aud } };
  const forwarded = { absent: null, matches: owner, mismatches: otherOwner };
  let count = 0;
  for (const row of combinations(Object.entries(axes))) {
    count += 1;
    const subject = row.mode === "email" ? email : owner;
    const request = new Request("https://mcp-fixture.example.test", {
      headers: row.jwt === "absent" ? {} : { "Cf-Access-Jwt-Assertion": assertions[row.jwt] },
    });
    const enroll = row.enrolled ? async () => ["bridge_status"] : null;
    const attempt = authorizeAccess(runtimes[row.runtime], config(row, subject), device,
      request, fetchJwks, enroll, forwarded[row.fleet]);
    const deny = expectedIdentityDenial(row);
    const expected = deny ? null : expectedGrants(row, subject);
    const label = JSON.stringify(row);
    if (expected) assert.deepEqual(await attempt, expected, label);
    else await assert.rejects(attempt, { message: deny ?? "device_grant_missing" }, label);
  }
  assert.equal(count, 1728);
});

// WS12b will use the same exact email validator for identities and tool grants.
// A mock runtime returning malformed identity data must fail closed.
test("malformed runtime email cannot match a legacy read grant", {
  todo: "WS12b: replace the presence-only email validation with the tool-grant validator",
}, async () => {
  const malformed = "owner@@example.test";
  await assert.rejects(authorizeAccess({ aud, getIdentity: async () => ({ email: malformed }) },
    { UDB_ACCESS_AUD: aud, UDB_DEVICE_GRANTS: JSON.stringify({
      [device]: { [malformed]: ["bridge_status"] },
    }) }, device), { message: "verified_identity_missing" });
});
