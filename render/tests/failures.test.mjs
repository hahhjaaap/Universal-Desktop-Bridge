import assert from "node:assert/strict";
import test from "node:test";
import { probeRelay } from "../dashboard.mjs";

const ORIGIN = "https://my-relay.workers.dev";
const ok = () => new Response(JSON.stringify({
  status: "ok", kind: "private-relay-prototype",
}), { status: 200, headers: { "content-type": "application/json" } });

test("Cloudflare 429/502/503/504 are not mistaken for healthy availability", async () => {
  for (const [code, expected] of [
    [429, "rate_limited"], [502, "upstream_unavailable"],
    [503, "upstream_unavailable"], [504, "upstream_unavailable"],
  ]) {
    assert.deepEqual(await probeRelay(ORIGIN, async () => new Response(null, {
      status: code,
    })), { state: expected });
  }
});

test("invalid JSON is reported as a protocol problem rather than a network outage", async () => {
  const response = await probeRelay(ORIGIN, async () => new Response("{garbled", {
    status: 200, headers: { "content-type": "application/json" },
  }));
  assert.deepEqual(response, { state: "unexpected_response" });
});

test("network failure stays offline and successful next check recovers", async () => {
  assert.deepEqual(await probeRelay(ORIGIN, async () => {
    throw new Error("DNS resolution failed");
  }), { state: "unavailable" });
  assert.deepEqual(await probeRelay(ORIGIN, async () => ok()), { state: "online" });
});

test("aborted health response terminates with a bounded timeout state", async () => {
  const response = await probeRelay(ORIGIN, async (_url, options) => {
    return new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => {
        const error = new Error("aborted");
        error.name = "AbortError";
        reject(error);
      }, { once: true });
    });
  });
  assert.deepEqual(response, { state: "timeout" });
});
