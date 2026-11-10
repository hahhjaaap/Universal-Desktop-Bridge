import assert from "node:assert/strict";
import test from "node:test";
import { readJson } from "../src/auth.js";

const body = '{"ok":true}';
function makeRequest(contentLength) {
  return new Request("https://audit.example.workers.dev/echo", {
    method: "POST",
    headers: contentLength === undefined ? {} : { "Content-Length": contentLength },
    body,
  });
}

test("HTTP Content-Length accepts only unsigned decimal integers", async () => {
  for (const invalid of [
    "1.5", "+11", "11.0", "11e0", "11,11",
    "-1", "Infinity", "NaN", "9007199254740993",
  ]) {
    await assert.rejects(readJson(makeRequest(invalid)),
      /invalid_content_length/, invalid);
  }
});

test("HTTP JSON accepts a valid decimal content length or chunked input", async () => {
  assert.deepEqual(await readJson(makeRequest("11")), { ok: true });
  assert.deepEqual(await readJson(makeRequest()), { ok: true });
});
