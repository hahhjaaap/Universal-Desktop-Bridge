// Version 2 enrollment: resumable device proof, authenticated owner and one-use CSRF.
import { HASH, bearer, digest, fixedEqual, readJson } from "./auth.js";
import { accessConfig } from "./access.js";
import { enrollmentEnabled } from "./enrollment.js";
import { authorizeEnrollmentOwner, ownerEnrollmentConfig } from "./enrollment-owner.js";

const TTL = 600000, RETAIN = 86400000, HUB = "__udb_browser_enrollment_v2__";
const json = (b, status = 200) => Response.json(b, { status, headers: {
  "cache-control": "no-store", "x-content-type-options": "nosniff" } });
const fail = (status, error) => json({ error }, status);
const stub = env => env.DEVICES.get(env.DEVICES.idFromName(HUB));
const enabled = env => enrollmentEnabled(env) && !!ownerEnrollmentConfig(env) &&
  env.UDB_AUTH_MODE === "cloudflare-access" && !!accessConfig(env) &&
  env.UDB_ACCESS_AUD !== env.UDB_ENROLLMENT_ACCESS_AUD && env.UDB_TENANT_POLICY === undefined;
const ID = /^[a-f0-9]{32}$/;
const label = s => typeof s === "string" && /^[A-Za-z0-9 _.-]{1,48}$/.test(s);
const escape = s => String(s).replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
function page(body, status = 200) {
  return new Response("<!doctype html><html lang=en><meta charset=utf-8>" +
    "<meta name=viewport content='width=device-width,initial-scale=1'><title>UDB device approval</title>" +
    "<style>body{font:18px system-ui;max-width:42rem;margin:4rem auto;padding:1rem}button{padding:.7rem}code{overflow-wrap:anywhere}</style>" +
    "<h1>UDB device approval</h1>" + body + "</html>", { status, headers: {
    "content-type": "text/html; charset=utf-8", "cache-control": "no-store",
    "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
    // no-referrer makes native form POSTs send Origin: null. Keep same-origin
    // submissions verifiable without leaking enrollment URLs across origins.
    "referrer-policy": "same-origin", "x-content-type-options": "nosniff",
    "x-frame-options": "DENY" } });
}
async function form(request) {
  if (!request.headers.get("content-type")?.startsWith("application/x-www-form-urlencoded"))
    throw new Error("invalid_form");
  const reader = request.body?.getReader(); if (!reader) throw new Error("empty_form");
  let text = "", size = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read(); if (done) break;
      size += value.length; if (size > 2048) throw new Error("large_form");
      text += new TextDecoder().decode(value);
    }
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
  const values = new URLSearchParams(text);
  for (const key of values.keys()) if (values.getAll(key).length !== 1) throw new Error("duplicate_field");
  return Object.fromEntries(values);
}
export async function routeBrowserEnrollment(request, env, forward, fetchImpl = fetch, access = null) {
  const url = new URL(request.url), path = url.pathname;
  if (path === "/v1/setup" && request.method === "GET")
    return json({ protocol: 2, browser_enrollment: enabled(env), device_diagnostics: true,
      chatgpt_client_attribution: false });
  const connect = /^\/v1\/devices\/([a-f0-9]{32})\/connect-chatgpt$/.exec(path);
  if (connect && request.method === "GET") {
    const endpoint = url.origin + "/v1/devices/" + connect[1] + "/mcp";
    const nonce = crypto.randomUUID();
    const response = page("<p>Copy this device MCP URL, then add a custom MCP server in ChatGPT Plugins and approve OAuth.</p>" +
      "<p><code id=endpoint>" + escape(endpoint) + "</code></p><button id=copy>Copy MCP URL</button> " +
      "<a href='https://chatgpt.com/plugins' target=_blank rel='noopener noreferrer'>Open ChatGPT Plugins</a>" +
      "<p id=message></p><p>If custom MCP servers are unavailable for your account, ask your ChatGPT workspace administrator. Windows permissions remain separate.</p>" +
      "<script nonce='" + nonce + "'>document.getElementById('copy').onclick=async()=>{try{await navigator.clipboard.writeText(document.getElementById('endpoint').textContent);document.getElementById('message').textContent='Copied. Paste it into Add custom MCP server.'}catch{document.getElementById('message').textContent='Select and copy the URL above.'}};</script>");
    response.headers.set("content-security-policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-" + nonce + "'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'");
    return response;
  }
  const begin = path === "/v1/setup/enrollments" && request.method === "POST";
  const status = /^\/v1\/setup\/enrollments\/([a-f0-9]{32})\/status$/.exec(path);
  const approval = /^\/v1\/setup\/enrollments\/([a-f0-9]{32})\/approval$/.exec(path);
  if (!begin && !status && !approval) return null;
  if (!enabled(env)) return fail(404, "browser_enrollment_disabled");
  try {
    if (approval) {
      if (!["GET", "POST"].includes(request.method)) return fail(405, "method_not_allowed");
      let owner;
      try { owner = await authorizeEnrollmentOwner(request, env, fetchImpl, access); }
      catch (error) {
        const reason = ["owner_config_invalid", "owner_runtime_audience", "owner_runtime_unavailable",
          "owner_assertion_invalid", "owner_identity_conflict", "owner_identity_missing",
          "owner_not_allowed", "owner_keys_unavailable", ...["malformed", "algorithm", "issuer",
            "audience", "time", "identity", "key", "signature"].map(value => "owner_assertion_" + value)]
          .includes(error?.message) ? error.message : "owner_auth_failed";
        // Static diagnostics only: never log assertions, cookies, identity or URL.
        console.warn(JSON.stringify({ event: "udb_owner_auth_denied", reason,
          runtime_present: Boolean(access), assertion_present: request.headers.has("Cf-Access-Jwt-Assertion") }));
        return page("<p>Owner authentication could not be verified. Sign in through the configured Cloudflare Access application.</p>" +
          "<p>Diagnostic: <code>" + reason + "</code>. If already signed in, ask the relay operator to check this code.</p>", 403);
      }
      if (request.method === "GET") {
        const code = url.searchParams.get("code");
        if (!/^[A-F0-9]{10}$/.test(code || "")) return fail(400, "invalid_code");
        const r = await forward(stub(env), new Request("https://internal/enroll-v2/review/" + approval[1], {
          method: "POST", body: JSON.stringify({ owner, code }) }));
        if (!r.ok) return page("<p>This request expired, was handled, or does not match the device.</p>", r.status);
        const b = await r.json();
        return page("<p>Approve only the Windows device in front of you.</p><p>Device: <b>" +
          escape(b.name) + "</b><br>ID: <code>" + escape(approval[1]) +
          "</code><br>Fingerprint: <code>" + escape(code) + "</code></p>" +
          "<form method=post><input type=hidden name=csrf value='" + escape(b.csrf) +
          "'><label><input type=checkbox name=status_only value=yes required> Allow this signed-in owner to read bridge status through MCP. " +
          "This grants no Windows file, terminal or desktop access.</label><p>" +
          "<button name=action value=approve>Approve device</button> " +
          "<button name=action value=reject formnovalidate>Reject</button></p></form>");
      }
      if (request.headers.get("Origin") !== url.origin ||
          !["same-origin", "none", null].includes(request.headers.get("Sec-Fetch-Site")))
        return fail(403, "csrf_rejected");
      const b = await form(request);
      if (!["approve", "reject"].includes(b.action) || !HASH.test(b.csrf || "") ||
          (b.action === "approve" && b.status_only !== "yes")) return fail(400, "invalid_consent");
      const r = await forward(stub(env), new Request("https://internal/enroll-v2/decision/" + approval[1], {
        method: "POST", body: JSON.stringify({ ...b, owner }) }));
      return page(r.ok ? "<p>Decision saved. Return to Windows and keep UDB setup open. ChatGPT OAuth remains a separate approval.</p>" :
        "<p>The decision could not be confirmed. Return to Windows and run udb setup to resume safely.</p>", r.status);
    }
    if (request.headers.has("Origin")) return fail(403, "browser_origin_not_supported");
    if (begin) {
      const b = await readJson(request);
      if (!ID.test(b.request_id) || !HASH.test(b.request_secret_sha256) ||
          !HASH.test(b.device_token_sha256) || !label(b.device_name)) return fail(400, "invalid_request");
      const source = await digest(env.UDB_ADMIN_KEY + ":" + (request.headers.get("CF-Connecting-IP") || "unknown"));
      return forward(stub(env), new Request("https://internal/enroll-v2/request", {
        method: "POST", body: JSON.stringify({ ...b, source }) }));
    }
    if (request.method !== "GET") return fail(405, "method_not_allowed");
    const proof = bearer(request);
    if (!HASH.test(proof || "")) return fail(401, "proof_required");
    return forward(stub(env), new Request("https://internal/enroll-v2/status/" + status[1], {
      headers: { Authorization: "Bearer " + proof } }));
  } catch { return fail(400, "invalid_request"); }
}
async function finish(store, env, record) {
  // Only this exact idempotent registration may be retried after uncertainty.
  // A revocation tombstone in the device object permanently blocks recovery.
  let response;
  try {
    response = await env.DEVICES.get(env.DEVICES.idFromName(record.id)).fetch(
      new Request("https://internal/setup-register", { method: "POST",
        body: JSON.stringify({ request_id: record.id, owner: record.owner,
          device_token_sha256: record.tokenHash }) }));
  } catch { return false; }
  if (response.status !== 201) return false;
  await store.transaction(async txn => {
    const records = await txn.get("setup_enrollments") || [];
    const r = records.find(x => x.id === record.id);
    if (r?.state === "registering") {
      r.state = "approved"; await txn.put("setup_enrollments", records);
    }
  });
  return true;
}
export async function handleBrowserEnrollment(request, ctx, env) {
  const path = new URL(request.url).pathname, store = ctx.storage, now = Date.now();
  if (path === "/enroll-v2/request" && request.method === "POST") {
    const b = await readJson(request);
    if (!ID.test(b.request_id) || !HASH.test(b.request_secret_sha256) ||
        !HASH.test(b.device_token_sha256) || !HASH.test(b.source) || !label(b.device_name))
      return fail(400, "invalid_request");
    return store.transaction(async txn => {
      const records = (await txn.get("setup_enrollments") || []).filter(r => r.created > now - RETAIN);
      const recent = (await txn.get("setup_rates") || []).filter(r => r.at > now - 3600000);
      const limited = records.length >= 200 ||
        records.filter(r => r.state === "pending" && r.expires > now).length >= 20 ||
        recent.length >= 50 || recent.filter(r => r.source === b.source).length >= 4;
      const old = records.find(r => r.id === b.request_id);
      if (old) {
        if (!fixedEqual(old.secretHash, b.request_secret_sha256) ||
            !fixedEqual(old.tokenHash, b.device_token_sha256) || old.name !== b.device_name)
          return fail(409, "request_conflict");
        // Only an expired, NEVER approved request can receive another approval
        // window. Identity/secrets stay unchanged; normal recovery is free.
        if (old.state === "pending" && old.expires <= now) {
          if (limited) return fail(429, "rate_limited");
          old.expires = now + TTL;
          delete old.csrf;
          await txn.put("setup_enrollments", records);
          await txn.put("setup_rates", [...recent, { source: b.source, at: now }]);
        }
        return json({ device_id: old.id, state: old.state }, 201);
      }
      if (limited) return fail(429, "rate_limited");
      records.push({ id: b.request_id, name: b.device_name, secretHash: b.request_secret_sha256,
        tokenHash: b.device_token_sha256, created: now, expires: now + TTL, state: "pending" });
      await txn.put("setup_enrollments", records);
      await txn.put("setup_rates", [...recent, { source: b.source, at: now }]);
      return json({ device_id: b.request_id, state: "pending" }, 201);
    });
  }
  const m = /^\/enroll-v2\/(status|review|decision)\/([a-f0-9]{32})$/.exec(path);
  if (!m) return fail(404, "not_found");
  if (m[1] === "status" && request.method === "GET") {
    const secret = bearer(request), hash = await digest(secret || "");
    let r = (await store.get("setup_enrollments") || []).find(r => r.id === m[2]);
    if (!r || !fixedEqual(r.secretHash, hash)) return fail(403, "proof_rejected");
    if (r.created <= now - RETAIN || (r.state === "pending" && r.expires <= now))
      return fail(410, "request_expired");
    if (r.state === "registering") {
      await finish(store, env, r);
      r = (await store.get("setup_enrollments")).find(r => r.id === m[2]);
    }
    return json({ device_id: r.id, state: r.state });
  }
  if (request.method !== "POST") return fail(405, "method_not_allowed");
  const b = await readJson(request);
  if (typeof b.owner !== "string" || b.owner.length > 500) return fail(400, "invalid_owner");
  const result = await store.transaction(async txn => {
    const records = await txn.get("setup_enrollments") || [];
    const r = records.find(r => r.id === m[2]);
    if (!r || r.expires <= now || r.state !== "pending") return { status: 410 };
    if (m[1] === "review") {
      if (!fixedEqual(r.secretHash.slice(0, 10).toUpperCase(), b.code || ""))
        return { status: 403 };
      const csrf = crypto.randomUUID().replaceAll("-", "") + crypto.randomUUID().replaceAll("-", "");
      r.csrf = { hash: await digest(csrf), owner: b.owner, expires: now + 120000 };
      await txn.put("setup_enrollments", records);
      return { status: 200, csrf, name: r.name };
    }
    if (!["approve", "reject"].includes(b.action) || !r.csrf || r.csrf.expires <= now ||
        r.csrf.owner !== b.owner || !fixedEqual(r.csrf.hash, await digest(b.csrf || "")) ||
        (b.action === "approve" && b.status_only !== "yes")) return { status: 403 };
    delete r.csrf;
    r.owner = b.owner;
    r.state = b.action === "reject" ? "rejected" : "registering";
    await txn.put("setup_enrollments", records);
    return { status: 200, record: { ...r } };
  });
  if (result.status !== 200) return fail(result.status, "decision_rejected");
  if (result.csrf) return json({ name: result.name, csrf: result.csrf });
  if (result.record.state === "rejected") return json({ rejected: true });
  return await finish(store, env, result.record) ? json({ approved: true }) :
    fail(503, "registration_pending_resume_setup");
}
