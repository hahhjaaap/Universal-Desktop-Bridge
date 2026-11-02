import assert from "node:assert/strict";
import test from "node:test";
import { readJson } from "../src/auth.js";

test("streaming JSON parser accepts split UTF-8 multibyte sequences", async () => {
  const text = JSON.stringify({ hello: "Việt Nam 🇻🇳" });
  const bytes = new TextEncoder().encode(text);
  let next = 0;
  const stream = new ReadableStream({
    pull(controller) {
      if (next >= bytes.length) return controller.close();
      controller.enqueue(bytes.slice(next, next + 1));
      next += 1;
    },
  });
  const request = new Request("https://example.com", {
    method: "POST", body: stream, duplex: "half",
  });
  assert.deepEqual(await readJson(request), { hello: "Việt Nam 🇻🇳" });
});

test("streaming parser rejects oversized chunked bodies without reading the rest", async () => {
  let pulls = 0;
  let canceled = false;
  const stream = new ReadableStream({
    pull(controller) {
      pulls += 1;
      if (pulls > 100) return controller.close();
      controller.enqueue(new Uint8Array(100_000));
    },
    cancel() { canceled = true; },
  });
  const request = new Request("https://example.com", {
    method: "POST", body: stream, duplex: "half",
  });
  await assert.rejects(readJson(request), /body_too_large/);
  assert.ok(pulls < 10, "must stop consuming quickly");
  assert.equal(canceled, true);
});

test("JSON root must be an object, not an array or null", async () => {
  for (const body of ["[]", "null", "1", "\"test\""]) {
    await assert.rejects(
      readJson(new Request("https://example.com", { method: "POST", body })),
      /invalid_json/,
    );
  }
});
