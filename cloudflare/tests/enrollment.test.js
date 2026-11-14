import assert from "node:assert/strict";
import { createHash, randomBytes } from "node:crypto";
import test from "node:test";
import relay, { DeviceRelay } from "../src/index.js";

const ORIGIN = "https://udb.example.workers.dev";
const ADMIN = "local-owner-" + "a".repeat(40);
const hash = (v) => createHash("sha256").update(v).digest("hex");

function envFixture({ enabled = true } = {}) {
  const objects = new Map();
  const env = {
    UDB_ADMIN_KEY: ADMIN,
    UDB_ENABLE_PRIVATE_ENROLLMENT: enabled ? "true" : "false",
    DEVICES: {
      idFromName: (s) => s,
      get: (id) => {
        if (!objects.has(id)) {
          const values = new Map();
          const storage = {
            get: async (key) => values.get(key),
            put: async (key, v) => {
              if (typeof key === "object") {
                for (const [k, val] of Object.entries(key)) values.set(k, val);
              } else values.set(key, v);
            },
            delete: async (keys) => {
              for (const key of Array.isArray(keys) ? keys : [keys]) values.delete(key);
            },
            transaction: async (fn) => fn(storage),
          };
          objects.set(id, { values, relay: new DeviceRelay({
            storage, getWebSockets: () => [],
          }, env) });
        }
        return {
          fetch: (request) => objects.get(id).relay.fetch(request),
        };
      },
    },
  };
  return { env, objects };
}

async function call(env, path, method = "GET", token = null, data = null, extraHeaders = {}) {
  const headers = { ...extraHeaders };
  if (token) headers.Authorization = "Bearer " + token;
  if (data) headers["Content-Type"] = "application/json";
  const request = new Request(ORIGIN + path, {
    method, headers, body: data ? JSON.stringify(data) : undefined,
  });
  return relay.fetch(request, env);
}

async function begin(env, name = "Office PC", source = "192.0.2.1") {
  const secret = randomBytes(32).toString("hex");
  const token = "private-local-secret-" + randomBytes(32).toString("hex");
  const requestHash = hash(secret);
  const tokenHash = hash(token);
  const response = await call(env, "/v1/enrollments", "POST", null, {
    request_secret_sha256: requestHash,
    device_token_sha256: tokenHash,
    device_name: name,
  }, { "CF-Connecting-IP": source });
  return {
    secret, token, requestHash, tokenHash, status: response.status,
    response: await response.json(),
  };
}

test("private enrollment disabled by default without leaking registrations", async () => {
  const fixture = envFixture({ enabled: false });
  const fresh = await begin(fixture.env);
  assert.equal(fresh.status, 404);
  assert.equal(fixture.objects.size, 0);
  const admin = await call(fixture.env, "/v1/admin/enrollments", "GET", ADMIN);
  assert.equal(admin.status, 404);
});

test("pending client cannot register before human owner approves", async () => {
  const { env, objects } = envFixture();
  const p = await begin(env);
  assert.equal(p.status, 201);
  assert.equal(p.response.state, "pending");
  const id = p.response.device_id;
  assert.match(id, /^[a-f0-9]{32}$/);
  const pending = await (await call(env, "/v1/enrollments/" + id + "/status", "GET", p.secret)).json();
  assert.deepEqual(pending, { device_id: id, state: "pending" });
  const noSecret = await call(env, "/v1/enrollments/" + id + "/status");
  assert.equal(noSecret.status, 401);
  const wrong = await call(env, "/v1/enrollments/" + id + "/status",
    "GET", randomBytes(32).toString("hex"));
  assert.equal(wrong.status, 403);
  assert.equal(objects.has(id), false, "No device registration before approval");
  assert.equal((await call(env, "/v1/admin/enrollments", "GET")).status, 401);
  assert.equal((await call(env, "/v1/admin/enrollments", "GET", ADMIN)).status, 200);
  const list = await (await call(env, "/v1/admin/enrollments", "GET", ADMIN)).json();
  assert.deepEqual(list.requests.map((r) => r.device_id), [id]);
  assert.equal(JSON.stringify(list).includes(p.requestHash), false);
  assert.equal(JSON.stringify(list).includes(p.tokenHash), false);
});

test("owner approval binds device hash, cannot replay or share its token", async () => {
  const { env, objects } = envFixture();
  const p = await begin(env);
  const id = p.response.device_id;
  const route = "/v1/admin/enrollments/" + id + "/approve";
  const code = p.requestHash.slice(0, 10).toUpperCase();
  assert.equal((await call(env, route, "POST", "wrong", { code })).status, 401);
  assert.equal((await call(env, route, "POST", ADMIN, { code: "0".repeat(10) === code ? "F".repeat(10) : "0".repeat(10) })).status, 403);
  assert.equal((await call(env, route, "POST", ADMIN, { code })).status, 200);
  assert.equal(objects.get(id).values.get("device_token_sha256"), p.tokenHash);
  assert.notEqual(p.token, p.tokenHash);
  assert.equal((await call(env, route, "POST", ADMIN, { code })).status, 409);
  const status = await (await call(env, "/v1/enrollments/" + id + "/status", "GET", p.secret)).json();
  assert.equal(status.state, "approved");
  const enrollmentState = objects.get("__udb_owner_enrollment_v1__").values;
  assert.equal(JSON.stringify([...enrollmentState]).includes(p.secret), false);
  assert.equal(JSON.stringify([...enrollmentState]).includes(p.token), false);
  const deviceState = objects.get(id).values;
  assert.equal(JSON.stringify([...deviceState]).includes(p.token), false);
});

test("rejection requires administrator key, prevents registration and approval", async () => {
  const { env, objects } = envFixture();
  const p = await begin(env);
  const id = p.response.device_id;
  const path = "/v1/admin/enrollments/" + id;
  assert.equal((await call(env, path, "DELETE")).status, 401);
  assert.equal((await call(env, path, "DELETE", ADMIN)).status, 200);
  assert.equal((await call(env, path, "DELETE", ADMIN)).status, 409);
  assert.equal((await call(env, path + "/approve", "POST", ADMIN, {
    code: p.requestHash.slice(0, 10).toUpperCase(),
  })).status, 409);
  assert.equal(objects.has(id), false);
});

test("anonymous requests are rate-limited per source and globally", async () => {
  const { env } = envFixture();
  for (let i = 0; i < 4; i++) {
    assert.equal((await begin(env, "Office PC", "192.0.2.2")).status, 201);
  }
  assert.equal((await begin(env, "Office PC", "192.0.2.2")).status, 429);
  assert.equal((await begin(env, "Office PC", "192.0.2.3")).status, 201);
  for (let i = 0; i < 15; i++) {
    assert.equal((await begin(env, "Office PC", "192.0.2." + (10 + i))).status, 201);
  }
  assert.equal((await begin(env, "Office PC", "192.0.2.101")).status, 429);
});

test("expiry and malformed input fail closed", async () => {
  const { env, objects } = envFixture();
  const p = await begin(env);
  const id = p.response.device_id;
  const hub = objects.get("__udb_owner_enrollment_v1__").values;
  const records = hub.get("private_enrollments");
  records[0].expires = Date.now() - 1;
  const status = await call(env, "/v1/enrollments/" + id + "/status", "GET", p.secret);
  assert.equal(status.status, 410);
  const approve = await call(env, "/v1/admin/enrollments/" + id + "/approve", "POST", ADMIN, {
    code: p.requestHash.slice(0, 10).toUpperCase(),
  });
  assert.equal(approve.status, 409);
  assert.equal(objects.has(id), false);
  const badLabel = await call(env, "/v1/enrollments", "POST", null, {
    request_secret_sha256: "a".repeat(64),
    device_token_sha256: "b".repeat(64),
    device_name: "<script>alert('x')</script>",
  });
  assert.equal(badLabel.status, 400);
  assert.equal((await call(env, "/v1/enrollments", "POST", null, {
    request_secret_sha256: "a".repeat(64),
    device_token_sha256: "b".repeat(64),
    device_name: "Test PC",
  }, { Origin: "https://malicious.example" })).status, 403);
});

test("pre-existing registered device cannot be replaced by self enrollment", async () => {
  const { env, objects } = envFixture();
  const p = await begin(env);
  const id = p.response.device_id;
  const entry = env.DEVICES.get(id);
  const registration = await entry.fetch(new Request("https://internal/register", {
    method: "PUT", body: JSON.stringify({ device_token_sha256: "f".repeat(64) }),
  }));
  assert.equal(registration.status, 200);
  const approve = await call(env, "/v1/admin/enrollments/" + id + "/approve", "POST", ADMIN, {
    code: p.requestHash.slice(0, 10).toUpperCase(),
  });
  assert.equal(approve.status, 503);
  assert.equal(objects.get(id).values.get("device_token_sha256"), "f".repeat(64));
  const hub = objects.get("__udb_owner_enrollment_v1__").values;
  assert.equal(hub.get("private_enrollments")[0].state, "registering");
  const replay = await call(env, "/v1/admin/enrollments/" + id + "/approve", "POST", ADMIN, {
    code: p.requestHash.slice(0, 10).toUpperCase(),
  });
  assert.equal(replay.status, 409);
});
