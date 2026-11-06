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

for (const name of ["list_files", "read_file", "search_files", "check_python_syntax"]) {
  test(name + " shares the bounded read queue without replay", async () => {
    const h = harness();
    const first = h.send();
    const forwarded = await sent(h);
    const second = h.send(2, "tools/call", { name, arguments: { project: "udb-room" } });
    for (let i = 0; i < 30 && h.relay.queuedReads === 0; i++) await setImmediate();
    assert.equal(h.relay.queuedReads, 1);
    assert.equal(h.frames.length, 1);
    h.relay.webSocketMessage(h.ws, JSON.stringify({ kind: "rpc_result", id: forwarded.id,
      rpc: { jsonrpc: "2.0", id: 1, result: {} } }));
    assert.equal((await first).status, 200);
    for (let i = 0; i < 30 && h.frames.length < 2; i++)
      await new Promise(resolve => setTimeout(resolve, 20));
    assert.equal(h.frames.length, 2);
    h.relay.webSocketMessage(h.ws, JSON.stringify({ kind: "rpc_result", id: h.frames[1].id,
      rpc: { jsonrpc: "2.0", id: 2, result: {} } }));
    assert.equal((await second).status, 200);
    assert.equal(h.frames.length, 2);
  });
}

test("queued reads cannot move to a replacement device connection", async () => {
  const h = harness();
  const first = h.send();
  await sent(h);
  const second = h.send(2, "tools/list");
  for (let i = 0; i < 30 && h.relay.queuedReads === 0; i++) await setImmediate();
  const replacement = { readyState: WebSocket.OPEN, send: () => assert.fail("Must not dispatch on a new connection") };
  h.relay.ctx.getWebSockets = () => [replacement];
  h.relay.webSocketClose(h.ws, 1006, "replaced");
  assert.equal((await first).status, 503);
  const response = await second;
  assert.equal(response.status, 503);
  assert.equal((await response.json()).error, "device_connection_changed");
  assert.equal(h.relay.queuedReads, 0);
});

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

test("ten simultaneous read-only calls dispatch in FIFO order", async () => {
  const h = harness();
  const calls = [h.send(1, "tools/list")];
  await sent(h);
  for (let id = 2; id <= 10; id++) {
    calls.push(h.send(id, "tools/call",
      { name: "read_file", arguments: { project: "fixture", path: "README.md" } }));
  }
  for (let i = 0; i < 50 && h.relay.queuedReads !== 9; i++)
    await setImmediate();
  assert.equal(h.relay.queuedReads, 9);
  assert.equal(h.frames.length, 1, "Windows stdio still receives one RPC at a time");

  const overflow = await h.send(11, "tools/list");
  assert.equal(overflow.status, 429, "The eleventh call must be rejected");
  const mutation = await h.send(12, "tools/call",
    { name: "computer_execute", arguments: {} });
  assert.equal(mutation.status, 429, "Mutations never queue, even when reads are pending");

  for (let id = 1; id <= 10; id++) {
    assert.equal(h.frames.length, id);
    assert.equal(h.frames[id - 1].rpc.id, id, "FIFO, not a race for the next slot");
    h.relay.webSocketMessage(h.ws, JSON.stringify({
      kind: "rpc_result", id: h.frames[id - 1].id,
      rpc: { jsonrpc: "2.0", id, result: {} },
    }));
    assert.equal((await calls[id - 1]).status, 200);
    if (id < 10) {
      for (let i = 0; i < 20 && h.frames.length < id + 1; i++)
        await setImmediate();
    }
  }
  assert.equal(h.relay.pending.size, 0);
  assert.equal(h.relay.queuedReads, 0);
  assert.equal(h.frames.length, 10);
});

test("queued reads are cancelled and never replayed after socket replacement", async () => {
  const h = harness();
  const calls = [h.send(1, "tools/list")];
  await sent(h);
  for (let id = 2; id <= 10; id++)
    calls.push(h.send(id, "tools/list"));
  for (let i = 0; i < 50 && h.relay.queuedReads !== 9; i++)
    await setImmediate();
  assert.equal(h.relay.queuedReads, 9);
  const replacement = {
    readyState: WebSocket.OPEN,
    send: () => assert.fail("No prior read may run on another connection"),
  };
  h.relay.ctx.getWebSockets = () => [replacement];
  h.relay.webSocketClose(h.ws, 1006, "superseded");
  const responses = await Promise.all(calls);
  assert.equal(responses[0].status, 503);
  for (const response of responses.slice(1)) {
    assert.equal(response.status, 503);
    assert.equal((await response.json()).error, "device_connection_changed");
  }
  assert.equal(h.frames.length, 1);
  assert.equal(h.relay.pending.size, 0);
  assert.equal(h.relay.queuedReads, 0);
});

test("thirty five-request read bursts complete without lost or duplicated replies", async () => {
  for (let batch = 0; batch < 30; batch++) {
    const h = harness();
    const calls = [h.send(1, "tools/list")];
    await sent(h);
    for (let id = 2; id <= 5; id++)
      calls.push(h.send(id, "tools/call",
        { name: "read_file", arguments: { project: "fixture", path: "README.md" } }));
    for (let i = 0; i < 40 && h.relay.queuedReads < 4; i++)
      await setImmediate();
    assert.equal(h.relay.queuedReads, 4, "four pending reads in burst " + batch);
    for (let id = 1; id <= 5; id++) {
      assert.equal(h.frames[id - 1]?.rpc.id, id, "FIFO in burst " + batch);
      h.relay.webSocketMessage(h.ws, JSON.stringify({
        kind: "rpc_result", id: h.frames[id - 1].id,
        rpc: { jsonrpc: "2.0", id, result: { batch, id } },
      }));
      const response = await calls[id - 1];
      assert.equal(response.status, 200);
      assert.deepEqual((await response.json()).result, { batch, id });
      if (id < 5) for (let tries = 0; tries < 20 && h.frames.length <= id; tries++)
        await setImmediate();
    }
    assert.equal(h.frames.length, 5);
    assert.equal(h.relay.queuedReads, 0);
    assert.equal(h.relay.pending.size, 0);
  }
});

test("invalid active RPC response cancels waiting reads without dispatch", async () => {
  const h = harness();
  const first = h.send(1, "tools/list");
  const forwarded = await sent(h);
  const queued = [h.send(2, "tools/list"), h.send(3, "tools/list")];
  for (let i = 0; i < 40 && h.relay.queuedReads < 2; i++)
    await setImmediate();
  assert.equal(h.relay.queuedReads, 2);
  h.relay.webSocketMessage(h.ws, JSON.stringify({
    kind: "rpc_result", id: forwarded.id,
    rpc: { jsonrpc: "2.0", id: "unexpected", result: {} },
  }));
  assert.equal((await first).status, 502);
  for (const response of await Promise.all(queued)) assert.equal(response.status, 503);
  assert.equal(h.frames.length, 1, "No queued request can follow a corrupt reply");
  assert.equal(h.relay.queuedReads, 0);
  assert.equal(h.closed[0].code, 1008);
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
