import assert from "node:assert/strict";
import { once } from "node:events";
import test from "node:test";
import { makeServer, probeRelay, relayOrigin } from "../dashboard.mjs";

test("only HTTPS workers.dev origins are accepted", () => {
  assert.equal(relayOrigin("https://udb-test.example.workers.dev"),
    "https://udb-test.example.workers.dev");
  for (const item of [
    "", "http://udb-test.example.workers.dev", "https://127.0.0.1",
    "https://example.com", "https://example.workers.dev.evil.com",
    "https://user:pass@udb-test.example.workers.dev",
    "https://udb-test.example.workers.dev/admin",
    "https://udb-test.example.workers.dev/?q=1",
  ]) assert.equal(relayOrigin(item), null);
});

test("no config never contacts the network", async () => {
  assert.deepEqual(await probeRelay("", () => { throw new Error("must not fetch"); }),
    { state: "not_configured" });
});

test("only expected public health response counts as online", async () => {
  const fake = async () => new Response(JSON.stringify({
    status: "ok", kind: "private-relay-prototype", device_id: "must-not-leak",
  }), { status: 200, headers: { "content-type": "application/json" } });
  assert.deepEqual(await probeRelay("https://a.workers.dev", fake), { state: "online" });
  const bad = async () => new Response(JSON.stringify({ status: "ok", kind: "wrong" }),
    { status: 200, headers: { "content-type": "application/json" } });
  assert.deepEqual(await probeRelay("https://a.workers.dev", bad),
    { state: "unexpected_response" });
});

test("oversized and redirected upstreams are not trusted", async () => {
  const big = async () => new Response("z".repeat(3000),
    { headers: { "content-type": "application/json" } });
  assert.deepEqual(await probeRelay("https://a.workers.dev", big),
    { state: "unavailable" });
  const redirect = async () => new Response(null, { status: 302,
    headers: { location: "https://example.com" } });
  assert.deepEqual(await probeRelay("https://a.workers.dev", redirect),
    { state: "unavailable" });
});

test("public status dashboard has no command or device route", async (t) => {
  const server = makeServer({ relay: "" });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  t.after(() => server.close());
  const origin = "http://127.0.0.1:" + server.address().port;
  const health = await fetch(origin + "/health");
  assert.equal(health.status, 200);
  assert.equal((await health.json()).service, "udb-render-observer");
  const status = await fetch(origin + "/api/relay-status");
  assert.deepEqual(await status.json(), { state: "not_configured" });
  const post = await fetch(origin + "/api/relay-status", { method: "POST" });
  assert.equal(post.status, 405);
  const control = await fetch(origin + "/v1/admin/devices/abc/rpc");
  assert.equal(control.status, 404);
  const home = await fetch(origin);
  assert.equal(home.headers.get("x-frame-options"), "DENY");
  assert.equal(home.headers.get("content-security-policy")?.includes("script-src 'self'"), true);
  assert.equal((await home.text()).includes("Universal Desktop Bridge"), true);
});
