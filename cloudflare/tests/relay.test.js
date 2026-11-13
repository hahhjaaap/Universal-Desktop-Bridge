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
  const answer = (frame, result = {}) => relay.webSocketMessage(ws, JSON.stringify({
    kind: "rpc_result", id: frame.id,
    rpc: { jsonrpc: "2.0", id: frame.rpc.id, result },
  }));
  return { relay, ws, frames, closed, send, answer };
}

async function untilFrames(h, count) {
  for (let i = 0; i < 1000 && h.frames.length < count; i++) await setImmediate();
  assert.equal(h.frames.length, count, "Expected concurrent requests to reach Windows");
}

for (const name of ["list_files", "read_file", "search_files", "check_python_syntax",
  "host_status", "computer_status"]) {
  test(name + " executes concurrently instead of waiting behind a read", async () => {
    const h = harness();
    const first = h.send(1, "tools/list");
    const second = h.send(2, "tools/call",
      { name, arguments: { project: "udb-room" } });
    await untilFrames(h, 2);
    assert.equal(h.relay.pending.size, 2);
    // Reverse completion proves each response is associated with its own ID.
    h.answer(h.frames[1], { second: true });
    h.answer(h.frames[0], { first: true });
    const response1 = await first;
    const response2 = await second;
    assert.equal(response1.status, 200);
    assert.deepEqual(await response2.json(), {
      jsonrpc: "2.0", id: 2, result: { second: true },
    });
    assert.equal(h.relay.pending.size, 0);
  });
}

test("owner status scheduling does not grant udb:read access or parallel desktop actions", async () => {
  const { isReadTool, isParallelReadTool } = await import("../src/read-tools.js");
  for (const name of ["host_status", "computer_status"]) {
    assert.equal(isReadTool(name), false);
    assert.equal(isParallelReadTool(name), true);
  }
  for (const name of ["computer_desktop", "computer_process", "host_browser",
    "host_start_session", "host_close_session", "file_write", "unknown_status"]) {
    assert.equal(isParallelReadTool(name), false);
  }
});

test("ten concurrent reads dispatch before any response; eleventh is refused", async () => {
  const h = harness();
  const calls = [];
  for (let id = 1; id <= 10; id++)
    calls.push(h.send(id, "tools/call", {
      name: "read_file", arguments: { project: "fixture", path: "README.md" },
    }));
  await untilFrames(h, 10);
  assert.equal(h.relay.pending.size, 10);
  assert.equal((await h.send(11)).status, 429);
  assert.equal((await h.send(12, "tools/call",
    { name: "computer_execute", arguments: {} })).status, 429);
  // The relay does not assume in-order replies.
  for (let index = 9; index >= 0; index--)
    h.answer(h.frames[index], { slot: index });
  const replies = await Promise.all(calls);
  for (let index = 0; index < 10; index++) {
    assert.equal(replies[index].status, 200);
    assert.deepEqual((await replies[index].json()).result, { slot: index });
  }
  assert.equal(h.relay.pending.size, 0);
  const mutation = h.send(13, "tools/call",
    { name: "computer_execute", arguments: {} });
  await untilFrames(h, 11);
  h.answer(h.frames[10]);
  assert.equal((await mutation).status, 200);
});

test("mutation holds an exclusive device slot", async () => {
  const h = harness();
  const mutation = h.send(1, "tools/call", {
    name: "computer_execute", arguments: {},
  });
  await untilFrames(h, 1);
  assert.equal((await h.send(2, "tools/list")).status, 429);
  assert.equal((await h.send(3, "tools/call", {
    name: "computer_execute", arguments: {},
  })).status, 429);
  h.answer(h.frames[0]);
  assert.equal((await mutation).status, 200);
  const read = h.send(4, "tools/list");
  await untilFrames(h, 2);
  h.answer(h.frames[1]);
  assert.equal((await read).status, 200);
});

test("socket replacement fails every in-flight read without transferring it", async () => {
  const h = harness();
  const calls = Array.from({ length: 10 }, (_, i) => h.send(i + 1));
  await untilFrames(h, 10);
  const replacement = {
    readyState: WebSocket.OPEN,
    send: () => assert.fail("Old request dispatched on replacement socket"),
  };
  h.relay.ctx.getWebSockets = () => [replacement];
  h.relay.webSocketClose(h.ws, 1006, "superseded");
  for (const response of await Promise.all(calls)) {
    assert.equal(response.status, 503);
    assert.equal((await response.json()).error, "device_disconnected_outcome_unknown");
  }
  assert.equal(h.relay.pending.size, 0);
  assert.equal(h.frames.length, 10);
});

test("thirty five-read bursts complete with distinct IDs and out-of-order replies", async () => {
  for (let batch = 0; batch < 30; batch++) {
    const h = harness();
    const calls = Array.from({ length: 5 }, (_, i) =>
      h.send(i + 1, "tools/call", {
        name: "read_file", arguments: { project: "fixture", path: "README.md" },
      }));
    await untilFrames(h, 5);
    for (let i = 4; i >= 0; i--) h.answer(h.frames[i], { batch, id: i + 1 });
    const replies = await Promise.all(calls);
    for (let i = 0; i < 5; i++) {
      assert.equal(replies[i].status, 200);
      assert.deepEqual((await replies[i].json()).result, { batch, id: i + 1 });
    }
    assert.equal(h.relay.pending.size, 0);
  }
});

test("invalid response closes socket and fails the other outstanding requests", async () => {
  const h = harness();
  const calls = [h.send(1), h.send(2), h.send(3)];
  await untilFrames(h, 3);
  h.relay.webSocketMessage(h.ws, JSON.stringify({
    kind: "rpc_result", id: h.frames[0].id,
    rpc: { jsonrpc: "2.0", id: "wrong", result: {} },
  }));
  const replies = await Promise.all(calls);
  assert.equal(replies[0].status, 502);
  assert.deepEqual(await replies[0].json(), { error: "invalid_device_rpc_response" });
  for (const response of replies.slice(1)) assert.equal(response.status, 503);
  assert.equal(h.closed[0].code, 1008);
  assert.equal(h.relay.pending.size, 0);
});

test("all pending calls fail closed when device disconnects", async () => {
  const h = harness();
  const calls = [h.send(1), h.send(2)];
  await untilFrames(h, 2);
  h.ws.readyState = WebSocket.CLOSED;
  h.relay.webSocketClose(h.ws, 1006, "lost");
  for (const response of await Promise.all(calls)) assert.equal(response.status, 503);
  assert.equal(h.relay.pending.size, 0);
});

test("responses with both result and error are rejected", async () => {
  const h = harness();
  const first = h.send(1);
  await untilFrames(h, 1);
  h.relay.webSocketMessage(h.ws, JSON.stringify({
    kind: "rpc_result", id: h.frames[0].id,
    rpc: { jsonrpc: "2.0", id: 1, result: {}, error: {} },
  }));
  assert.equal((await first).status, 502);
  assert.equal(h.closed[0].code, 1008);
});

test("oversized UTF-8 socket reply closes the device and unblocks callers", async () => {
  const h = harness();
  const calls = [h.send(1), h.send(2)];
  await untilFrames(h, 2);
  h.relay.webSocketMessage(h.ws, "é".repeat(600_000));
  for (const response of await Promise.all(calls)) assert.equal(response.status, 503);
  assert.equal(h.closed[0].code, 1009);
  assert.equal(h.relay.pending.size, 0);
});

test("no unknown mutation is automatically retried following disconnect", async () => {
  const h = harness();
  const pending = h.send(1, "tools/call", {
    name: "computer_execute", arguments: {},
  });
  await untilFrames(h, 1);
  h.relay.webSocketClose(h.ws, 1000, "closed");
  const response = await pending;
  assert.equal(response.status, 503);
  assert.equal((await response.json()).error, "device_disconnected_outcome_unknown");
  assert.equal(h.frames.length, 1);
});
