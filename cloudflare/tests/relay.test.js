import assert from "node:assert/strict";
import { setImmediate } from "node:timers/promises";
import test from "node:test";
import { DeviceRelay } from "../src/index.js";

function harness() {
  const frames = [];
  const closed = [];
  const ws = {
    readyState: WebSocket.OPEN,
    send: (data) => frames.push(JSON.parse(data)),
    close: (code, reason) => closed.push({ code, reason }),
  };
  const relay = new DeviceRelay({
    getWebSockets: () => [ws],
    storage: { get: async () => undefined },
  }, {});
  const send = (id = 1, method = "tools/list", params = {}) =>
    relay.fetch(new Request("https://internal/rpc", {
      method: "POST",
      body: JSON.stringify({ jsonrpc: "2.0", id, method, params }),
    }));
  return { relay, ws, frames, closed, send };
}

async function sent(h) {
  for (let i = 0; i < 10 && h.frames.length === 0; i++) {
    await setImmediate();
  }
  assert.equal(h.frames.length, 1, "RPC was forwarded to the device");
  return h.frames[0];
}

test("one pending desktop request at a time, with exact response ID", async () => {
  const h = harness();
  const first = h.send();
  const forwarded = await sent(h);
  const second = await h.send(2, "tools/call",
    { name: "terminal_start", arguments: {} });
  assert.equal(second.status, 429);
  assert.equal(h.frames.length, 1);
  h.relay.webSocketMessage(h.ws, JSON.stringify({
    kind: "rpc_result",
    id: forwarded.id,
    rpc: { jsonrpc: "2.0", id: 1, result: { tools: [] } },
  }));
  const response = await first;
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    jsonrpc: "2.0", id: 1, result: { tools: [] },
  });
  assert.equal(h.relay.pending.size, 0);
});

test("one additional read-only request waits for the current RPC", async () => {
  const h = harness();
  const first = h.send();
  const forwarded = await sent(h);
  const second = h.send(2, "initialize", { protocolVersion: "2025-11-25" });
  for (let i = 0; i < 30 && h.relay.queuedReads === 0; i++)
    await setImmediate();
  assert.equal(h.relay.queuedReads, 1);
  assert.equal(h.frames.length, 1);
  const third = await h.send(3, "tools/list");
  assert.equal(third.status, 429, "A second waiting read is refused");
  const mutation = await h.send(4, "tools/call",
    { name: "terminal_start", arguments: {} });
  assert.equal(mutation.status, 429, "Mutations never enter the read queue");
  h.relay.webSocketMessage(h.ws, JSON.stringify({
    kind: "rpc_result", id: forwarded.id,
    rpc: { jsonrpc: "2.0", id: 1, result: { tools: [] } },
  }));
  assert.equal((await first).status, 200);
  for (let i = 0; i < 30 && h.frames.length < 2; i++)
    await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(h.frames.length, 2);
  assert.equal(h.frames[1].rpc.method, "initialize");
  h.relay.webSocketMessage(h.ws, JSON.stringify({
    kind: "rpc_result", id: h.frames[1].id,
    rpc: { jsonrpc: "2.0", id: 2,
      result: { protocolVersion: "2025-11-25" } },
  }));
  const response = await second;
  assert.equal(response.status, 200);
  assert.equal(h.relay.pending.size, 0);
  assert.equal(h.relay.queuedReads, 0);
});

test("queued reads fail closed if the device disconnects", async () => {
  const h = harness();
  const first = h.send();
  await sent(h);
  const second = h.send(2, "tools/list");
  for (let i = 0; i < 30 && h.relay.queuedReads === 0; i++)
    await setImmediate();
  assert.equal(h.relay.queuedReads, 1);
  h.ws.readyState = WebSocket.CLOSED;
  h.relay.webSocketClose(h.ws, 1006, "lost");
  assert.equal((await first).status, 503);
  assert.equal((await second).status, 503);
  assert.equal(h.frames.length, 1, "A queued read is not replayed after disconnect");
  assert.equal(h.relay.queuedReads, 0);
});

test("mismatched RPC IDs are rejected and connection is closed", async () => {
  const h = harness();
  const first = h.send();
  const forwarded = await sent(h);
  h.relay.webSocketMessage(h.ws, JSON.stringify({
    kind: "rpc_result",
    id: forwarded.id,
    rpc: { jsonrpc: "2.0", id: "wrong", result: "not trustworthy" },
  }));
  const response = await first;
  assert.equal(response.status, 502);
  assert.deepEqual(await response.json(), { error: "invalid_device_rpc_response" });
  assert.equal(h.closed[0].code, 1008);
});

test("responses with both result and error are invalid", async () => {
  const h = harness();
  const first = h.send();
  const forwarded = await sent(h);
  h.relay.webSocketMessage(h.ws, JSON.stringify({
    kind: "rpc_result",
    id: forwarded.id,
    rpc: { jsonrpc: "2.0", id: 1, result: {}, error: {} },
  }));
  assert.equal((await first).status, 502);
});

test("oversized UTF-8 socket replies close the connection and unblock callers", async () => {
  const h = harness();
  const first = h.send();
  await sent(h);
  h.relay.webSocketMessage(h.ws, "é".repeat(600_000));
  const response = await first;
  assert.equal(response.status, 503);
  assert.equal(h.closed[0].code, 1009);
  assert.equal(h.relay.pending.size, 0);
});

test("connection loss unblocks pending call without retrying mutations", async () => {
  const h = harness();
  const first = h.send();
  await sent(h);
  h.relay.webSocketClose(h.ws, 1000, "closed");
  const response = await first;
  assert.equal(response.status, 503);
  assert.equal((await response.json()).error, "device_disconnected_outcome_unknown");
  assert.equal(h.relay.pending.size, 0);
});
