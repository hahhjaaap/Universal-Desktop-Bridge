import assert from "node:assert/strict";
import test from "node:test";
import worker, { DeviceRelay } from "../src/index.js";
import { handleAccountMcp, registerEnrolledDevice } from "../src/account-fleet.js";
import { handleMcp } from "../src/mcp.js";
import { ENROLLED_CATALOG } from "../src/local-permissions.js";
import canonicalTools from "../src/fleet-tool-catalog.json" with { type: "json" };
import { fleetCanonicalCatalog } from "../src/fleet-catalog.js";

const BASE = "https://fleet-test.workers.dev";
const TEAM = "https://fleet-test.cloudflareaccess.com";
const APP = "fleet-mcp-audience";
const OWNER = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";
const deviceA = "a".repeat(32), deviceB = "b".repeat(32), deviceC = "c".repeat(32);
const principal = uuid => TEAM + "#" + uuid;
const report = (broad, project = true) => ({
  name: "Universal Desktop Bridge", platform: "nt",
  computer_access: { enabled: broad, scope: "current_windows_user",
    capabilities: broad ? ["files", "execute", "desktop"] : [] },
  host_background: { enabled: false },
  readiness: { readable_projects: project ? 1 : 0 },
});
const tool = (name, properties = {}) => ({ name, description: name,
  inputSchema: { type: "object", properties, additionalProperties: false } });
function fixture() {
  const objects = new Map(), invocations = [], state = new Map(), seen = new Map();
  const f = { objects, invocations, state, seen, failWriteOnce: false, loseResultOn: null };
  const env = f.env = { UDB_AUTH_MODE: "cloudflare-access",
    UDB_ACCESS_TEAM_DOMAIN: TEAM, UDB_ACCESS_AUD: APP,
    UDB_ENABLE_BROWSER_ENROLLMENT: "true", UDB_ENABLE_LOCAL_TOOL_SYNC: "true",
    UDB_ENABLE_ACCOUNT_FLEET: "true", UDB_ENABLE_OWNER_TOOLS: "true",
    UDB_ENABLE_COMPANION_TOOLS: "true" };
  env.DEVICES = {
    idFromName: id => id,
    get(id) {
      if (!objects.has(id)) {
        const values = new Map();
        let queue = Promise.resolve();
        const storage = {
          async get(k) { return structuredClone(values.get(k)); },
          async put(k, value) {
            for (const [key, item] of typeof k === "object" ?
              Object.entries(k) : [[k, value]]) values.set(key, structuredClone(item));
          },
          async delete(keys) { for (const k of Array.isArray(keys) ? keys : [keys])
            values.delete(k); },
          transaction(fn) { const pending = queue.then(() => fn(storage));
            queue = pending.catch(() => {}); return pending; },
        };
        const ctx = { storage, getWebSockets: () =>
          state.get(id)?.online ? [{ readyState: 1, close() {} }] : [] };
        objects.set(id, { values, relay: new DeviceRelay(ctx, env) });
      }
      return { async fetch(request) {
        const path = new URL(request.url).pathname;
        if (path === "/rpc") {
          const device = state.get(id);
          if (!device?.online) return Response.json({ error: "device_offline" }, { status: 503 });
          const rpc = await request.json();
          invocations.push({ id, rpc: structuredClone(rpc) });
          if (f.loseResultOn === id && rpc.method === "tools/call" &&
              rpc.params.name !== "bridge_status")
            return Response.json({ error: "device_disconnected_outcome_unknown" }, { status: 503 });
          const isStatus = rpc.method === "tools/call" && rpc.params.name === "bridge_status";
          const value = rpc.method === "tools/list" ? { tools: [
            tool("bridge_status"), tool("list_projects"), tool("computer_process",
              { action: { type: "string" } }), tool("computer_status"),
          ] } : isStatus ? { content: [{ type: "text", text: JSON.stringify(report(device.granted)) }] } :
            { content: [{ type: "text", text: JSON.stringify({
              target: id, args: rpc.params?.arguments || {} }) }] };
          return Response.json({ jsonrpc: "2.0", id: rpc.id, result: value });
        }
        const response = await objects.get(id).relay.fetch(request);
        if (path === "/fleet/register" && f.failWriteOnce) {
          f.failWriteOnce = false;
          throw Error("synthetic lost registry acknowledgement");
        }
        return response;
      } };
    },
  };
  f.add = async (id, uuid, name = "Windows UDB", granted = true) => {
    state.set(id, { online: true, granted });
    const r = await env.DEVICES.get(id).fetch(new Request("https://internal/setup-register", {
      method: "POST", body: JSON.stringify({
        request_id: id, owner: principal(uuid), device_token_sha256: "f".repeat(64) }),
    }));
    assert.equal(r.status, 201);
    assert.equal(await registerEnrolledDevice(env, {
      id, name, owner: principal(uuid),
    }), true);
    return id;
  };
  f.access = uuid => ({ access: { aud: APP,
    getIdentity: async () => ({ email: "same-name@example.test", user_uuid: uuid }) } });
  f.call = (uuid, method = "tools/list", params = {}, id = 1, headers = {}) =>
    worker.fetch(new Request(BASE + "/v1/account/mcp", {
      method: "POST", headers: { "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-11-25", ...headers },
      body: JSON.stringify({ jsonrpc: "2.0", method, params, id }),
    }), env, f.access(uuid));
  f.devices = async uuid => (await (await f.call(uuid, "tools/call",
    { name: "list_devices", arguments: {} })).json()).result.structuredContent.devices;
  return f;
}

test("account discovery mirrors the authoritative Windows catalog and preserves exact schemas offline", async () => {
  const f = fixture();
  const canonical = fleetCanonicalCatalog();
  const expected = new Map(canonicalTools.map(tool => [tool.name, tool]));
  assert.equal(canonical.length, 41);
  assert.deepEqual(canonical.map(tool => tool.name).sort(), [...expected.keys()].sort());
  for (const tool of canonical) {
    assert.deepEqual(tool.inputSchema, expected.get(tool.name).inputSchema, tool.name);
    assert.ok(Array.isArray(tool.securitySchemes));
    assert.ok(tool.annotations, "all public tools expose truthful annotations: " + tool.name);
  }
  const response = await f.call(OWNER);
  const listed = (await response.json()).result.tools;
  assert.equal(listed.length, canonicalTools.length + 1);
  const byName = new Map(listed.map(tool => [tool.name, tool]));
  for (const tool of canonicalTools) {
    const discovered = byName.get(tool.name);
    assert.ok(discovered, "missing canonical tool " + tool.name);
    assert.ok(discovered.inputSchema.required.includes("device_id"), tool.name);
    assert.equal(discovered.inputSchema.properties.device_id.pattern, "^[a-f0-9]{32}$");
    const schema = structuredClone(discovered.inputSchema);
    delete schema.properties.device_id;
    schema.required = schema.required.filter(name => name !== "device_id");
    if (!Object.hasOwn(tool.inputSchema, "required")) delete schema.required;
    assert.deepEqual(schema, tool.inputSchema, "device routing must not alter native schema: " + tool.name);
  }
});

test("opt-in fleet discovery is a distinct protected resource and unauthenticated calls fail", async () => {
  const f = fixture();
  const metadata = await worker.fetch(new Request(BASE +
    "/.well-known/oauth-protected-resource/v1/account/mcp"), f.env);
  assert.equal((await metadata.json()).resource, BASE + "/v1/account/mcp");
  const unauthenticated = await worker.fetch(new Request(BASE + "/v1/account/mcp", {
    method: "POST", body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
  }), f.env);
  assert.equal(unauthenticated.status, 401);
  assert.match(unauthenticated.headers.get("www-authenticate"), /resource_metadata=/);
  assert.equal(f.objects.size, 0);
  delete f.env.UDB_ENABLE_ACCOUNT_FLEET;
  assert.equal((await f.call(OWNER)).status, 404);
  assert.equal((await worker.fetch(new Request(BASE +
    "/.well-known/oauth-protected-resource/v1/account/mcp"), f.env)).status, 404);
});

test("offline account discovery is complete, stable, and ignores poisoned legacy catalog", async () => {
  const f = fixture();
  const before = (await (await f.call(OWNER)).json()).result.tools;
  assert.ok(before.length >= 35, "offline fleet must expose every canonical public family");
  assert.ok(before.some(t => t.name === "computer_process"));
  assert.ok(before.every(t => t.name === "list_devices" ||
    t.inputSchema.required?.includes("device_id")),
    "every Windows operation has required device_id");
  const fleetKey = [...f.objects.keys()].find(k => k.startsWith("__udb_account_fleet_v1__"));
  assert.ok(fleetKey);
  f.objects.get(fleetKey).values.set("fleet_catalog", [tool("bridge_status")]);
  await f.add(deviceA, OWNER, "Legacy", false);
  f.state.get(deviceA).online = false;
  assert.deepEqual((await (await f.call(OWNER)).json()).result.tools, before,
    "an offline machine and a truncated cached catalog cannot change discovery");
  f.state.get(deviceA).online = true;
  f.state.get(deviceA).granted = true;
  await f.add(deviceB, OWNER, "New", true);
  assert.deepEqual((await (await f.call(OWNER)).json()).result.tools, before);
  assert.equal(f.invocations.filter(x => x.rpc.method === "tools/list").length, 0,
    "fleet discovery must never query an online device");
});

test("two identically named devices share one plugin schema; a third needs no new schema", async () => {
  const f = fixture();
  await f.add(deviceA, OWNER, "Dell", true);
  await f.add(deviceB, OWNER, "Dell", false);
  const tools = (await (await f.call(OWNER)).json()).result.tools;
  assert.equal(tools.filter(x => x.name === "list_devices").length, 1);
  assert.deepEqual(tools.filter(x => x.name === "list_projects")[0].inputSchema.required,
    ["device_id"]);
  assert.equal(tools.some(x => x.inputSchema?.properties?.device_id?.enum), false);
  const names = (await f.devices(OWNER)).map(x => [x.device_id, x.display_name]);
  assert.deepEqual(names, [[deviceA, "Dell"], [deviceB, "Dell"]]);
  await f.add(deviceC, OWNER, "Home", true);
  const after = (await (await f.call(OWNER)).json()).result.tools;
  assert.deepEqual(after, tools, "adding a third PC must not alter the MCP schema");
  assert.equal((await f.devices(OWNER)).length, 3);
});

test("per-call device_id prevents cross-chat result or parameter mixups and missing IDs fail closed", async () => {
  const f = fixture();
  await f.add(deviceA, OWNER); await f.add(deviceB, OWNER);
  const params = id => ({ name: "list_projects", arguments: { device_id: id } });
  const [a, b] = await Promise.all([
    f.call(OWNER, "tools/call", params(deviceA), "same-call"),
    f.call(OWNER, "tools/call", params(deviceB), "same-call"),
  ]);
  const read = async response => JSON.parse((await response.json()).result.content[0].text);
  assert.equal((await read(a)).target, deviceA);
  assert.equal((await read(b)).target, deviceB);
  assert.equal((await f.call(OWNER, "tools/call",
    { name: "list_projects", arguments: {} })).status, 400);
  assert.equal(f.invocations.filter(x => x.rpc.method === "tools/call" &&
    x.rpc.params.name === "list_projects").length, 2);
  assert.ok(f.invocations.every(x => !Object.hasOwn(x.rpc.params.arguments || {}, "device_id")),
    "device_id is routing metadata, never sent as a Windows tool argument");
});

test("immutable Access identity isolates fleet accounts despite identical emails and forged owner headers", async () => {
  const f = fixture();
  await f.add(deviceA, OWNER, "Shared"); await f.add(deviceB, OTHER, "Shared");
  assert.deepEqual((await f.devices(OWNER)).map(x => x.device_id), [deviceA]);
  assert.deepEqual((await f.devices(OTHER)).map(x => x.device_id), [deviceB]);
  assert.equal((await f.call(OTHER, "tools/call",
    { name: "list_projects", arguments: { device_id: deviceA } })).status, 403);
  assert.equal((await f.call(OWNER, "tools/call",
    { name: "list_projects", arguments: { device_id: deviceB } }, 3,
    { "X-UDB-Owner": principal(OTHER), "X-User-Email": "same-name@example.test" })).status, 403);
  const bad = await worker.fetch(new Request(BASE + "/v1/account/mcp", {
    method: "POST", body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
  }), f.env, { access: { aud: "other-audience",
    getIdentity: async () => ({ user_uuid: OWNER }) } });
  assert.equal(bad.status, 401);
});

test("issuer-sub Fleet works with a signed JWT when Cloudflare omits ctx.access", async () => {
  const f = fixture();
  f.env.UDB_ACCESS_PRINCIPAL_MODE = "issuer-sub";
  await f.add(deviceA, OWNER, "Signed owner device", true);
  const pair = await crypto.subtle.generateKey({
    name: "RSASSA-PKCS1-v1_5", modulusLength: 2048,
    publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256",
  }, true, ["sign", "verify"]);
  const jwk = await crypto.subtle.exportKey("jwk", pair.publicKey);
  let fetched = 0;
  const fetchKeys = async (url, opts) => {
    assert.equal(url, TEAM + "/cdn-cgi/access/certs");
    assert.equal(opts.redirect, "manual");
    fetched++;
    return Response.json({ keys: [{ ...jwk, kid: "fleet-signed-test" }] });
  };
  const encoded = value => Buffer.from(JSON.stringify(value)).toString("base64url");
  const sign = async (sub = OWNER) => {
    const header = encoded({ alg: "RS256", kid: "fleet-signed-test" });
    const claims = encoded({
      iss: TEAM, aud: [APP], email: "same-name@example.test", sub,
      exp: Math.floor(Date.now() / 1000) + 300,
    });
    const payload = header + "." + claims;
    const signature = await crypto.subtle.sign("RSASSA-PKCS1-v1_5",
      pair.privateKey, new TextEncoder().encode(payload));
    return payload + "." + Buffer.from(signature).toString("base64url");
  };
  const send = (jwt, name = "bridge_status") => new Request(
    BASE + "/v1/account/mcp", {
      method: "POST", headers: { "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-11-25",
        ...(jwt ? { "Cf-Access-Jwt-Assertion": jwt } : {}) },
      body: JSON.stringify({ jsonrpc: "2.0", id: 11, method: "tools/call",
        params: { name, arguments: { device_id: deviceA } } }),
    });
  const valid = await sign();
  const success = await handleAccountMcp(send(valid), f.env, null, fetchKeys);
  assert.equal(success.status, 200,
    "signed Access identity must work without native ctx.access");
  assert.ok((await success.json()).result.content?.length);
  assert.equal(f.invocations.filter(x => x.rpc.params?.name === "bridge_status").length, 1);
  assert.equal(fetched, 1, "Access JWKS is cached across the two verification layers");
  const dispatched = f.invocations.length;

  // The internal owner delegation must not rely only on the forwarded string.
  const wrongOwner = await handleMcp(send(valid), f.env, deviceA,
    f.env.DEVICES.get(deviceA), fetchKeys, null, principal(OTHER));
  assert.equal(wrongOwner.status, 401);
  assert.equal(f.invocations.length, dispatched);

  const mismatched = await handleAccountMcp(send(await sign(OTHER)), f.env,
    null, fetchKeys);
  assert.equal(mismatched.status, 403, "different Access owner cannot access device");
  assert.equal(f.invocations.length, dispatched);
  const unsigned = await handleAccountMcp(send(), f.env, null, fetchKeys);
  assert.equal(unsigned.status, 401);
  const parts = valid.split(".");
  const forged = parts[0] + "." + parts[1] + "." +
    (parts[2][0] === "A" ? "B" : "A") + parts[2].slice(1);
  assert.equal((await handleAccountMcp(send(forged), f.env, null, fetchKeys)).status, 401);
  assert.equal(f.invocations.length, dispatched);
});

test("issuer-sub native Access Fleet delegation reaches Windows without weakening per-device JWT", async () => {
  const f = fixture();
  f.env.UDB_ACCESS_PRINCIPAL_MODE = "issuer-sub";
  await f.add(deviceA, OWNER, "Owned", true);
  await f.add(deviceB, OTHER, "Other", true);
  assert.deepEqual((await f.devices(OWNER)).map(x => x.device_id), [deviceA]);

  const status = await f.call(OWNER, "tools/call",
    { name: "bridge_status", arguments: { device_id: deviceA } });
  assert.equal(status.status, 200, "native Access identity must survive internal delegation");
  const body = (await status.json()).result;
  assert.ok(body.content?.some(x => x.type === "text"));
  assert.equal(f.invocations.filter(x => x.id === deviceA &&
    x.rpc.params?.name === "bridge_status").length, 1);

  const otherOwner = await f.call(OTHER, "tools/call",
    { name: "bridge_status", arguments: { device_id: deviceA } });
  assert.equal(otherOwner.status, 403);
  const absentId = await f.call(OWNER, "tools/call",
    { name: "bridge_status", arguments: {} });
  assert.equal(absentId.status, 400);
  // Bypassing the account Fleet route never unlocks issuer-sub without
  // a valid signed per-device Access assertion, even for a known owner.
  const direct = await worker.fetch(new Request(BASE + "/v1/devices/" + deviceA + "/mcp", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 3, method: "tools/call",
      params: { name: "bridge_status", arguments: {} } }),
  }), f.env, f.access(OWNER));
  assert.equal(direct.status, 401);
});

test("issuer-sub Fleet still requires local Windows permission for all non-status tools", async () => {
  const f = fixture();
  f.env.UDB_ACCESS_PRINCIPAL_MODE = "issuer-sub";
  await f.add(deviceA, OWNER, "No desktop permission", false);
  const denied = await f.call(OWNER, "tools/call", {
    name: "computer_process",
    arguments: { device_id: deviceA, action: "list" },
  });
  assert.equal(denied.status, 200);
  assert.equal((await denied.json()).result.structuredContent.code,
    "local_owner_permission_required");
  assert.equal(f.invocations.filter(x => x.id === deviceA &&
    x.rpc.params?.name === "computer_process").length, 0,
  "no computer operation dispatched without Windows local approval");
});

test("local Windows permissions and revocation are evaluated on the target device every time", async () => {
  const f = fixture(); await f.add(deviceA, OWNER, "Dell", true);
  await f.add(deviceB, OWNER, "Home", false);
  const call = id => f.call(OWNER, "tools/call",
    { name: "computer_process", arguments: { device_id: id, action: "list" } });
  assert.equal((await call(deviceA)).status, 200);
  const b = await call(deviceB);
  assert.equal((await b.json()).result.structuredContent.code, "local_owner_permission_required");
  assert.equal(f.invocations.filter(x => x.id === deviceB &&
    x.rpc.params?.name === "computer_process").length, 0);
  f.state.get(deviceA).granted = false;
  assert.equal((await (await call(deviceA)).json()).result.structuredContent.code,
    "local_owner_permission_required");
  f.state.get(deviceB).granted = true;
  assert.equal((await call(deviceB)).status, 200);
  assert.equal(f.invocations.filter(x => x.id === deviceA &&
    x.rpc.params?.name === "computer_process").length, 1);
});

test("offline never silently fails over; reconnect keeps stable ID and last contact distinct", async () => {
  const f = fixture(); await f.add(deviceA, OWNER); await f.add(deviceB, OWNER);
  f.objects.get(deviceA).values.set("fleet_last_seen", Date.now() - 10000);
  f.state.get(deviceA).online = false;
  const devices = await f.devices(OWNER);
  assert.equal(devices.find(x => x.device_id === deviceA).connection, "offline");
  assert.equal(devices.find(x => x.device_id === deviceB).connection, "online");
  assert.ok(devices.find(x => x.device_id === deviceA).last_seen_at);
  assert.equal((await f.call(OWNER, "tools/call",
    { name: "list_projects", arguments: { device_id: deviceA } })).status, 503);
  assert.equal(f.invocations.filter(x => x.rpc.params?.name === "list_projects").length, 0);
  f.state.get(deviceA).online = true;
  assert.equal((await f.call(OWNER, "tools/call",
    { name: "list_projects", arguments: { device_id: deviceA } })).status, 200);
  // Token revocation leaves a tombstone and stale index; it never reassigns the device.
  await f.env.DEVICES.get(deviceA).fetch(new Request("https://internal/revoke", { method: "DELETE" }));
  assert.equal((await f.devices(OWNER)).find(x => x.device_id === deviceA).connection, "unverified");
  assert.equal((await f.call(OWNER, "tools/call",
    { name: "list_projects", arguments: { device_id: deviceA } })).status, 403);
});

test("lost registry acknowledgement can be reconciled idempotently without token replacement", async () => {
  const f = fixture(), id = deviceA, owner = principal(OWNER);
  f.state.set(id, { online: true, granted: false });
  await f.env.DEVICES.get(id).fetch(new Request("https://internal/setup-register", {
    method: "POST", body: JSON.stringify({
      request_id: id, owner, device_token_sha256: "f".repeat(64) }),
  }));
  f.failWriteOnce = true;
  assert.equal(await registerEnrolledDevice(f.env, { id, owner, name: "Dell" }), false);
  assert.equal(await registerEnrolledDevice(f.env, { id, owner, name: "Dell" }), true);
  assert.equal((await f.devices(OWNER)).length, 1);
  assert.equal(f.objects.get(id).values.get("device_token_sha256"), "f".repeat(64));
  assert.equal(await registerEnrolledDevice(f.env, { id, owner, name: "Different" }), false);
});

test("uncertain mutation outcome is never replayed; old endpoint and rollback stay intact", async () => {
  const f = fixture(); await f.add(deviceA, OWNER);
  f.loseResultOn = deviceA;
  const r = await f.call(OWNER, "tools/call",
    { name: "list_projects", arguments: { device_id: deviceA } });
  assert.equal(r.status, 503);
  assert.equal(f.invocations.filter(x => x.rpc.params?.name === "list_projects").length, 1);
  const old = await worker.fetch(new Request(BASE + "/v1/devices/" + deviceA + "/setup/status", {
    headers: { Authorization: "Bearer not-the-device-token" },
  }), f.env);
  assert.equal(old.status, 403);
  delete f.env.UDB_ENABLE_ACCOUNT_FLEET;
  assert.equal((await f.call(OWNER)).status, 404);
  assert.equal(f.objects.get(deviceA).values.get("device_token_sha256"), "f".repeat(64));
});

test("modern account catalog and tool call retain per-request metadata", async () => {
  const f = fixture(); await f.add(deviceA, OWNER);
  const meta = (method, params = {}, id = 1) => {
    const version = "2026-07-28", prefix = "io.modelcontextprotocol/";
    const rpc = { jsonrpc: "2.0", id, method, params: {
      ...params, _meta: { [prefix + "protocolVersion"]: version,
        [prefix + "clientCapabilities"]: {} } } };
    return worker.fetch(new Request(BASE + "/v1/account/mcp", {
      method: "POST", headers: { "MCP-Protocol-Version": version,
        "Mcp-Method": method, ...(method === "tools/call" ? { "Mcp-Name": params.name } : {}) },
      body: JSON.stringify(rpc),
    }), f.env, f.access(OWNER));
  };
  const list = (await (await meta("tools/list")).json()).result;
  assert.equal(list.resultType, "complete");
  assert.equal(list.cacheScope, "private");
  assert.equal(list.tools.find(x => x.name === "list_projects").inputSchema.required.includes("device_id"), true);
  const called = (await (await meta("tools/call", {
    name: "list_projects", arguments: { device_id: deviceA },
  })).json()).result;
  assert.equal(called.resultType, "complete");
  assert.equal(JSON.parse(called.content[0].text).target, deviceA);
  assert.equal((await meta("tools/call", { name: "list_projects",
    arguments: { device_id: deviceA } }, 8)).status, 200);
  assert.equal(ENROLLED_CATALOG.includes("list_projects"), true);
});

test("list_devices change-only revision retains fresh owner and connection checks", async () => {
  const f = fixture();
  await f.add(deviceA, OWNER, "Office");
  await f.add(deviceB, OWNER, "Laptop");
  const call = async args => (await (await f.call(OWNER, "tools/call",
    { name: "list_devices", arguments: args })).json()).result.structuredContent;
  const first = await call({});
  assert.equal(first.devices.length, 2);
  assert.match(first.revision, /^[a-f0-9]{64}$/);
  const same = await call({ if_revision: first.revision });
  assert.deepEqual(same, { revision: first.revision, unchanged: true });
  f.state.get(deviceB).online = false;
  const changed = await call({ if_revision: first.revision });
  assert.notEqual(changed.revision, first.revision);
  assert.equal(changed.devices[1].connection, "offline");
  const oldOwner = await f.call(OTHER, "tools/call",
    { name: "list_devices", arguments: { if_revision: changed.revision } });
  const deniedList = (await oldOwner.json()).result.structuredContent;
  assert.deepEqual(deniedList.devices, [], "one owner's revision never grants another's inventory");
  for (const argumentsValue of [{ if_revision: "bad" }, { unexpected: true }]) {
    assert.equal((await f.call(OWNER, "tools/call",
      { name: "list_devices", arguments: argumentsValue })).status, 400);
  }
});

test("list_devices limits fleet verification fanout without changing device order", async () => {
  const f = fixture();
  const ids = Array.from({ length: 26 }, (_, i) => i.toString(16).padStart(32, "0"));
  for (const [i, id] of ids.entries()) await f.add(id, OWNER, "Device " + i);
  const originalGet = f.env.DEVICES.get.bind(f.env.DEVICES);
  let inFlight = 0, maximum = 0, checked = 0;
  f.env.DEVICES.get = id => {
    const stub = originalGet(id);
    return { fetch: async request => {
      if (new URL(request.url).pathname !== "/fleet/verify")
        return stub.fetch(request);
      inFlight++;
      maximum = Math.max(maximum, inFlight);
      try {
        await new Promise(resolve => setTimeout(resolve, 2));
        checked++;
        return await stub.fetch(request);
      } finally {
        inFlight--;
      }
    } };
  };
  const inventory = await f.devices(OWNER);
  assert.deepEqual(inventory.map(x => x.device_id), ids);
  assert.equal(checked, ids.length, "all devices must be freshly verified");
  assert.equal(maximum, 12, "fanout must be bounded");
});
