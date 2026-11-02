import assert from "node:assert/strict";
import { setImmediate } from "node:timers/promises";
import test from "node:test";
import worker, { DeviceRelay } from "../src/index.js";

function harness(sendFailure = false) {
  const frames = [];
  const closures = [];
  const ws = {
    readyState: WebSocket.OPEN,
    send(data) {
      if (sendFailure) throw new Error("socket died while sending");
      frames.push(JSON.parse(data));
    },
    close(code, reason) { closures.push({ code, reason }); },
  };
  const relay = new DeviceRelay({
    getWebSockets: () => [ws],
    storage: { get: async () => undefined },
  }, {});
  const request = () => relay.fetch(new Request("https://internal/rpc", {
    method: "POST",
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
  }));
  return { relay, frames, closures, ws, request };
}

async function oneForward(h) {
  for (let i = 0; i < 15 && !h.frames.length; i++) await setImmediate();
  assert.equal(h.frames.length, 1);
}

test("corrupt socket JSON fails a pending request immediately and closes device", async () => {
  const h = harness();
  const pending = h.request();
  await oneForward(h);
  h.relay.webSocketMessage(h.ws, "{not-json");
  const response = await pending;
  assert.equal(response.status, 503);
  assert.equal((await response.json()).error, "device_disconnected_outcome_unknown");
  assert.equal(h.closures[0].code, 1007);
  assert.equal(h.relay.pending.size, 0);
});

test("unexpected socket frame fails closed rather than hanging for 25 seconds", async () => {
  const h = harness();
  const pending = h.request();
  await oneForward(h);
  h.relay.webSocketMessage(h.ws, JSON.stringify({ kind: "unknown" }));
  assert.equal((await pending).status, 503);
  assert.equal(h.closures[0].code, 1008);
  assert.equal(h.relay.pending.size, 0);
});

test("send failure returns unknown outcome and clears pending state", async () => {
  const h = harness(true);
  const response = await h.request();
  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), { error: "device_disconnected_outcome_unknown" });
  assert.equal(h.relay.pending.size, 0);
});

test("Durable Object connection outage is a 503, never a bad client request", async () => {
  const key = "test-secret-" + "x".repeat(35);
  const env = {
    UDB_ADMIN_KEY: key,
    UDB_ENABLE_DEV_ADMIN_RPC: "true", // Explicitly exercise legacy prototype mode.
    DEVICES: {
      idFromName: name => name,
      get: () => ({ fetch: async () => { throw Error("upstream inaccessible"); } }),
    },
  };
  const id = "a".repeat(32);
  const origin = "https://udb.example.workers.dev";
  const admin = { Authorization: "Bearer " + key };
  const status = await worker.fetch(new Request(origin + "/v1/admin/devices/" + id + "/status", { headers: admin }), env);
  assert.equal(status.status, 503);
  assert.deepEqual(await status.json(), { error: "relay_unavailable_outcome_unknown" });
  const rpc = await worker.fetch(new Request(origin + "/v1/admin/devices/" + id + "/rpc", {
    method: "POST",
    headers: admin,
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
  }), env);
  assert.equal(rpc.status, 503);
  assert.deepEqual(await rpc.json(), { error: "relay_unavailable_outcome_unknown" });
  const pairing = await worker.fetch(new Request(origin + "/v1/admin/pairings", {
    method: "POST", headers: admin,
  }), env);
  assert.equal(pairing.status, 503);
  assert.deepEqual(await pairing.json(), { error: "pairing_unavailable" });
});
