import assert from "node:assert/strict";
import test from "node:test";
import { authorize, deviceGrant, oauthConfig, AuthError } from "../src/oauth.js";

const DEVICE = "a".repeat(32);
const RESOURCE = "https://relay.workers.dev/v1/devices/" + DEVICE + "/mcp";
const ISSUER = "https://identity.example.com";
const env = { UDB_OAUTH_ISSUER: ISSUER,
  UDB_OAUTH_JWKS_URL: ISSUER + "/jwks.json",
  UDB_DEVICE_GRANTS: JSON.stringify({ [DEVICE]: { "alice": ["bridge_status"], "bob": ["list_projects"] } }) };

function b64(bytes) { return Buffer.from(bytes).toString("base64url"); }

async function signedToken(subject, claims = {}) {
  const pair = await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5",
    modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
  true, ["sign", "verify"]);
  const pub = await crypto.subtle.exportKey("jwk", pair.publicKey);
  const head = b64(JSON.stringify({ alg: "RS256", typ: "JWT", kid: "trusted" }));
  const now = Math.floor(Date.now() / 1000);
  const body = b64(JSON.stringify({ iss: ISSUER, aud: RESOURCE, sub: subject, scope: "udb:read",
    iat: now, exp: now + 120, ...claims }));
  const message = head + "." + body;
  const signature = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", pair.privateKey,
    new TextEncoder().encode(message));
  return { token: message + "." + b64(signature), jwks: { keys: [{ ...pub, kid: "trusted" }] } };
}

test("issuer identifiers are exact, including optional trailing slash", () => {
  assert.equal(oauthConfig(env).issuer, ISSUER);
  assert.equal(oauthConfig({ ...env, UDB_OAUTH_ISSUER: ISSUER + "/" }).issuer,
    ISSUER + "/");
  assert.equal(oauthConfig({ ...env, UDB_OAUTH_ISSUER: ISSUER + "/tenant" }).issuer,
    ISSUER + "/tenant");
  assert.equal(oauthConfig({ ...env, UDB_OAUTH_ISSUER: ISSUER + " /" }), null);
});

test("short-lived signed tokens from a trailing-slash issuer validate", async () => {
  const { token, jwks } = await signedToken("alice", { iss: ISSUER + "/" });
  const cfg = { ...env, UDB_OAUTH_ISSUER: ISSUER + "/" };
  const request = new Request(RESOURCE, {
    headers: { Authorization: "Bearer " + token },
  });
  const fetchImpl = async () => new Response(JSON.stringify(jwks), {
    status: 200, headers: { "content-type": "application/json" },
  });
  assert.deepEqual(await authorize(request, cfg, DEVICE, fetchImpl),
    { subject: "alice", allowTools: ["bridge_status"] });
  await assert.rejects(authorize(request, env, DEVICE, fetchImpl), AuthError);
});

test("missing OAuth configuration and owner grant fail closed", () => {
  assert.equal(oauthConfig({}), null);
  assert.deepEqual(deviceGrant({}, DEVICE, "alice"), []);
  assert.deepEqual(deviceGrant(env, DEVICE, "alice"), ["bridge_status"]);
  assert.deepEqual(deviceGrant(env, DEVICE, "bob"), ["list_projects"]);
  assert.deepEqual(deviceGrant(env, DEVICE, "mallory"), []);
  assert.deepEqual(deviceGrant(env, "b".repeat(32), "alice"), []);
});

test("per-user signed access token is bound to the exact device resource", async () => {
  const { token, jwks } = await signedToken("alice");
  const req = new Request(RESOURCE, { headers: { Authorization: "Bearer " + token } });
  const fetchImpl = async (_url, options) => {
    assert.equal(options.redirect, "error");
    return new Response(JSON.stringify(jwks), {
      status: 200, headers: { "content-type": "application/json" } });
  };
  assert.deepEqual(await authorize(req, env, DEVICE, fetchImpl),
    { subject: "alice", allowTools: ["bridge_status"] });
  const evil = new Request(RESOURCE.replace(DEVICE, "b".repeat(32)),
    { headers: { Authorization: "Bearer " + token } });
  await assert.rejects(authorize(evil, env, "b".repeat(32), fetchImpl), AuthError);
});

test("expired, wrong-audience and unsigned tokens cannot authorize", async () => {
  for (const claims of [
    { exp: Math.floor(Date.now()/1000) - 1 },
    { aud: "https://other.workers.dev/mcp" }, { scope: "other:scope" },
  ]) {
    const { token } = await signedToken("alice", claims);
    await assert.rejects(authorize(new Request(RESOURCE, {
      headers: { Authorization: "Bearer " + token } }), env, DEVICE), AuthError);
  }
  await assert.rejects(authorize(new Request(RESOURCE), env, DEVICE), AuthError);
  await assert.rejects(authorize(new Request(RESOURCE, {
    headers: { Authorization: "Bearer eyJhbGciOiJub25lIn0.e30.invalid" },
  }), env, DEVICE), AuthError);
});
