import assert from "node:assert/strict";
import test from "node:test";
import worker from "../src/index.js";

const DEVICE = "a".repeat(32);
const OWNER = "owner@example.test";
const AUD = "udb-live-test-audience";
const URL = "https://example.workers.dev/v1/devices/" + DEVICE + "/mcp";
const SESSION = "b".repeat(32);
const TAB = "c".repeat(32);
const IDENTITY = () => ({ access: {
  aud: AUD, getIdentity: async () => ({ email: OWNER }),
} });

function setup(ownerTools = []) {
  const forwarded = [];
  const env = {
    UDB_AUTH_MODE: "cloudflare-access",
    UDB_ACCESS_AUD: AUD,
    UDB_DEVICE_GRANTS: JSON.stringify({ [DEVICE]: { [OWNER]: ["bridge_status"] } }),
    UDB_ENABLE_OWNER_TOOLS: "true",
    UDB_OWNER_TOOL_GRANTS: JSON.stringify({ [DEVICE]: { [OWNER]: ownerTools } }),
    DEVICES: {
      idFromName: value => value,
      get: () => ({ async fetch(request) {
        const rpc = await request.json();
        forwarded.push(rpc);
        const name = rpc.params?.name;
        const data = name === "host_status" ? {
          enabled: true, worker_ready: true, sessions: [
            { kind: "browser", presentation: "background", session_id: SESSION },
            { kind: "browser", presentation: "foreground", session_id: "d".repeat(32) },
          ],
        } : name === "host_browser" ? {
          tabs: [
            { tab_id: TAB, background: true, title: "Allowed tab" },
            { tab_id: "d".repeat(32), background: false, title: "Other tab" },
          ],
        } : { enabled: false };
        return Response.json({ jsonrpc: "2.0", id: rpc.id, result: {
          content: [{ type: "text", text: JSON.stringify(data) }],
        } });
      } }),
    },
  };
  return { env, forwarded };
}
const request = (params = "", site) => new Request(URL + "?view=live" + params, {
  method: "GET", headers: site ? { "Sec-Fetch-Site": site } : {},
});

test("Live mode stays closed without Access, signed identity or owner grants", async () => {
  const { env, forwarded } = setup();
  const unavailable = await worker.fetch(request(), { ...env, UDB_AUTH_MODE: "jwt" });
  assert.equal(unavailable.status, 404);
  const anonymous = await worker.fetch(request(), env);
  assert.equal(anonymous.status, 401);
  const unauthorized = await worker.fetch(request(), env, IDENTITY());
  assert.equal(unauthorized.status, 403);
  assert.equal(forwarded.length, 0);
});

test("Live screen requires three explicit owner tools and renders strict CSP", async () => {
  const { env, forwarded } = setup(["host_status", "host_browser", "host_screenshot"]);
  const wrongOwner = { access: { aud: AUD,
    getIdentity: async () => ({ email: "other@example.test" }) } };
  assert.equal((await worker.fetch(request(), env, wrongOwner)).status, 401);
  const response = await worker.fetch(request(), env, IDENTITY());
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-security-policy"), /script-src 'nonce-[a-z0-9]+'/);
  assert.equal(response.headers.get("x-frame-options"), "DENY");
  assert.match(response.headers.get("cache-control"), /no-store/);
  assert.match(await response.text(), /UDB Live/);
  assert.equal(forwarded.length, 0);
});

test("Live data rejects cross-site, missing fetch metadata, malformed IDs", async () => {
  const { env, forwarded } = setup(["host_status", "host_browser", "host_screenshot"]);
  for (const site of [undefined, "cross-site", "same-site", "none"]) {
    const denied = await worker.fetch(request("&data=status", site), env, IDENTITY());
    assert.equal(denied.status, 403);
  }
  const malformed = await worker.fetch(request("&data=tabs&session=../../../secret", "same-origin"),
    env, IDENTITY());
  assert.equal(malformed.status, 400);
  assert.equal(forwarded.length, 0);
});

test("Live data forwards only fixed read calls and filters background sessions and tabs", async () => {
  const { env, forwarded } = setup(["host_status", "host_browser", "host_screenshot"]);
  const status = await worker.fetch(request("&data=status", "same-origin"), env, IDENTITY());
  assert.equal(status.status, 200);
  assert.deepEqual(await status.json(), { enabled: true, ready: true,
    sessions: [{ id: SESSION }] });
  const tabs = await worker.fetch(request("&data=tabs&session=" + SESSION, "same-origin"),
    env, IDENTITY());
  assert.equal(tabs.status, 200);
  assert.deepEqual(await tabs.json(), { tabs: [{ id: TAB, title: "Allowed tab" }] });
  assert.deepEqual(forwarded.map(rpc => rpc.params?.name),
    ["host_status", "host_browser"]);
  assert.deepEqual(forwarded[0].params.arguments, {});
  assert.deepEqual(forwarded[1].params.arguments, { action: "list", session_id: SESSION });
});
