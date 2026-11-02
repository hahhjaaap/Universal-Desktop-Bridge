import assert from "node:assert/strict";
import test from "node:test";
import relay, { DeviceRelay } from "../src/index.js";
import { PAIRING_TTL_MS, newPairing } from "../src/pairing.js";

const ADMIN = "owner-secret-" + "a".repeat(40);
const ORIGIN = "https://udb.example.workers.dev";

function makeEnv() {
  const objects = new Map();
  return {
    UDB_ADMIN_KEY: ADMIN,
    DEVICES: {
      idFromName: (name) => name,
      get: (name) => {
        if (!objects.has(name)) {
          const values = new Map();
          const storage = {
            get: async (key) => values.get(key),
            put: async (key, val) => {
              if (typeof key === "object") {
                for (const [k, v] of Object.entries(key)) values.set(k, v);
              } else values.set(key, val);
            },
            delete: async (keys) => {
              for (const key of Array.isArray(keys) ? keys : [keys]) values.delete(key);
            },
            transaction: async (callback) => callback(storage),
          };
          const ctx = { storage, getWebSockets: () => [] };
          objects.set(name, { relay: new DeviceRelay(ctx, {}), values });
        }
        const entry = objects.get(name);
        return { fetch: (request) => entry.relay.fetch(request) };
      },
    },
    objects,
  };
}

async function call(env, path, method, bearer, body) {
  const headers = bearer ? { Authorization: "Bearer " + bearer } : {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  return relay.fetch(new Request(ORIGIN + path, {
    method, headers, body: body === undefined ? undefined : JSON.stringify(body),
  }), env);
}

async function issue(env) {
  const response = await call(env, "/v1/admin/pairings", "POST", ADMIN);
  assert.equal(response.status, 201);
  return response.json();
}

test("pairing invitations are random and expire after ten minutes", async () => {
  const a = await newPairing();
  const b = await newPairing();
  assert.match(a.device_id, /^[a-f0-9]{32}$/);
  assert.match(a.pairing_code, /^[a-f0-9]{64}$/);
  assert.match(a.pairing_token_sha256, /^[a-f0-9]{64}$/);
  assert.notEqual(a.device_id, b.device_id);
  assert.notEqual(a.pairing_code, b.pairing_code);
  assert.equal(PAIRING_TTL_MS, 600000);
});

test("admin secret is required to issue invitations; health reveals no devices", async () => {
  const env = makeEnv();
  assert.equal((await call(env, "/v1/admin/pairings", "POST")).status, 401);
  assert.equal((await call(env, "/v1/admin/pairings", "POST", "incorrect")).status, 401);
  const p = await issue(env);
  assert.equal(p.expires_in_seconds, 600);
  const health = await (await call(env, "/health", "GET")).json();
  assert.deepEqual(health, { status: "ok", kind: "private-relay-prototype" });
  assert.equal(JSON.stringify(health).includes(p.device_id), false);
});

test("Windows can claim once without owner admin key, then admin can revoke", async () => {
  const env = makeEnv();
  const p = await issue(env);
  const route = "/v1/devices/" + p.device_id + "/claim";
  const payload = { device_token_sha256: "b".repeat(64) };
  const rejected = await call(env, route, "POST", "1".repeat(64), payload);
  assert.equal(rejected.status, 403);
  const claimed = await call(env, route, "POST", p.pairing_code, payload);
  assert.equal(claimed.status, 201);
  assert.deepEqual(await claimed.json(), { registered: true });
  const replay = await call(env, route, "POST", p.pairing_code, payload);
  assert.equal(replay.status, 409);
  const statusRoute = "/v1/admin/devices/" + p.device_id + "/status";
  const status = await (await call(env, statusRoute, "GET", ADMIN)).json();
  assert.deepEqual(status, { registered: true, online: false });
  assert.equal(env.objects.get(p.device_id).values.has("pairing_token_sha256"), false);
  assert.equal((await call(env, "/v1/admin/devices/" + p.device_id, "DELETE")).status, 401);
  assert.equal((await call(env, "/v1/admin/devices/" + p.device_id, "DELETE", ADMIN)).status, 200);
  const after = await (await call(env, statusRoute, "GET", ADMIN)).json();
  assert.equal(after.registered, false);
});

test("five wrong pairing codes lock an invitation", async () => {
  const env = makeEnv();
  const p = await issue(env);
  const route = "/v1/devices/" + p.device_id + "/claim";
  const payload = { device_token_sha256: "f".repeat(64) };
  const wrong = "0".repeat(64) === p.pairing_code ? "1".repeat(64) : "0".repeat(64);
  for (let i = 0; i < 5; i++) {
    const response = await call(env, route, "POST", wrong, payload);
    assert.equal(response.status, 403);
  }
  assert.equal((await call(env, route, "POST", p.pairing_code, payload)).status, 403);
  assert.equal(env.objects.get(p.device_id).values.has("device_token_sha256"), false);
});

test("expired invitation cannot be used and claims validate device hashes", async () => {
  const env = makeEnv();
  const p = await issue(env);
  const route = "/v1/devices/" + p.device_id + "/claim";
  assert.equal((await call(env, route, "POST", p.pairing_code, { device_token_sha256: "x" })).status, 400);
  env.objects.get(p.device_id).values.set("pairing_expires_at", Date.now() - 1);
  const response = await call(env, route, "POST", p.pairing_code,
    { device_token_sha256: "a".repeat(64) });
  assert.equal(response.status, 403);
  assert.equal(env.objects.get(p.device_id).values.has("device_token_sha256"), false);
});
