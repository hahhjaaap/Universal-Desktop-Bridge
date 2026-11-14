// Opt-in, owner-approved PRIVATE enrollment. No admin secret/device token on
// a new Windows machine. No permission grant or ChatGPT OAuth bypass.
import { DEVICE_ID, HASH, adminAuthorized, bearer, digest, fixedEqual, readJson } from "./auth.js";

export const ENROLLMENT_TTL_MS = 10 * 60 * 1000;
const HOUR_MS = 60 * 60 * 1000;
const MAX_LIVE = 20;
const MAX_HOURLY = 50;
const MAX_PER_SOURCE = 4;
const HUB_NAME = "__udb_owner_enrollment_v1__";

const json = (object, status = 200) => new Response(JSON.stringify(object), {
  status,
  headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
});
const fail = (status, code) => json({ error: code }, status);
const hub = (env) => env.DEVICES.get(env.DEVICES.idFromName(HUB_NAME));
const allowedLabel = (value) => typeof value === "string" &&
  /^[A-Za-z0-9 _.-]{1,48}$/.test(value);

// Anonymous enrollment is disabled unless the operator explicitly enables
// it AND configures the administrator key. Rate limiting here is a backstop,
// not a replacement for Cloudflare WAF/access rules.
export function enrollmentEnabled(env) {
  return env.UDB_ENABLE_PRIVATE_ENROLLMENT === "true" &&
    typeof env.UDB_ADMIN_KEY === "string" && env.UDB_ADMIN_KEY.length >= 32 &&
    !!env.DEVICES?.get && !!env.DEVICES?.idFromName;
}

export async function routeEnrollment(request, env, forward) {
  const path = new URL(request.url).pathname;
  const isBegin = path === "/v1/enrollments" && request.method === "POST";
  const statusMatch = /^\/v1\/enrollments\/([a-f0-9]{32})\/status$/.exec(path);
  const adminList = path === "/v1/admin/enrollments" && request.method === "GET";
  const adminApprove = /^\/v1\/admin\/enrollments\/([a-f0-9]{32})\/approve$/.exec(path);
  const adminRevoke = /^\/v1\/admin\/enrollments\/([a-f0-9]{32})$/.exec(path);
  if (!isBegin && !(statusMatch && request.method === "GET") &&
      !adminList && !(adminApprove && request.method === "POST") &&
      !(adminRevoke && request.method === "DELETE")) return null;
  if (!enrollmentEnabled(env)) return fail(404, "enrollment_disabled");
  const isAdmin = adminList || adminApprove || adminRevoke;
  if (isAdmin && !adminAuthorized(request, env)) return fail(401, "admin_auth_required");
  if (request.headers.get("Origin")) return fail(403, "browser_origin_not_supported");
  try {
    if (isBegin) {
      const body = await readJson(request);
      if (!HASH.test(body.request_secret_sha256) ||
          !HASH.test(body.device_token_sha256) || !allowedLabel(body.device_name))
        return fail(400, "invalid_enrollment_request");
      const deviceId = crypto.randomUUID().replaceAll("-", "");
      // Cloudflare normally sets CF-Connecting-IP; its hash stays inside the
      // DO and is never returned, logged or persisted outside the hour window.
      const source = await digest(request.headers.get("CF-Connecting-IP") || "unknown");
      return forward(hub(env), new Request("https://internal/enroll/request", {
        method: "POST",
        body: JSON.stringify({ device_id: deviceId, ...body, source }),
      }));
    }
    if (statusMatch) {
      const secret = bearer(request);
      if (!secret || !HASH.test(secret)) return fail(401, "enrollment_auth_required");
      return forward(hub(env), new Request("https://internal/enroll/status/" + statusMatch[1], {
        headers: { Authorization: "Bearer " + secret },
      }));
    }
    if (adminList) return forward(hub(env), new Request("https://internal/enroll/list"));
    if (adminApprove) {
      const body = await readJson(request);
      if (typeof body.code !== "string" || !/^[A-F0-9]{10}$/.test(body.code))
        return fail(400, "invalid_approval_code");
      return forward(hub(env), new Request(
        "https://internal/enroll/approve/" + adminApprove[1], {
          method: "POST", body: JSON.stringify({ code: body.code }),
        }
      ));
    }
    return forward(hub(env), new Request(
      "https://internal/enroll/reject/" + adminRevoke[1], { method: "DELETE" }
    ));
  } catch {
    return fail(400, "invalid_request");
  }
}

// Shared EnrollmentHub Durable Object state is stored inside the existing
// DEVICES namespace. No new DO binding, migration or table is required.
export async function handleEnrollmentHub(request, ctx, env) {
  const path = new URL(request.url).pathname;
  const store = ctx.storage;
  const now = Date.now();
  const live = (records) => records.filter((r) => r.expires > now);
  if (path === "/enroll/request" && request.method === "POST") {
    const b = await readJson(request);
    if (!DEVICE_ID.test(b.device_id) || !HASH.test(b.request_secret_sha256) ||
        !HASH.test(b.device_token_sha256) || !HASH.test(b.source) ||
        !allowedLabel(b.device_name)) return fail(400, "invalid_enrollment_request");
    const result = await store.transaction(async (txn) => {
      const records = live((await txn.get("private_enrollments")) || []);
      const recent = ((await txn.get("private_enrollment_rates")) || [])
        .filter((x) => x.at > now - HOUR_MS);
      if (records.length >= MAX_LIVE || recent.length >= MAX_HOURLY ||
          recent.filter((x) => x.source === b.source).length >= MAX_PER_SOURCE)
        return { status: 429 };
      if (records.some((r) => r.id === b.device_id))
        return { status: 409 };
      const record = {
        id: b.device_id, name: b.device_name,
        secretHash: b.request_secret_sha256, tokenHash: b.device_token_sha256,
        expires: now + ENROLLMENT_TTL_MS, created: now, state: "pending",
      };
      await txn.put("private_enrollments", [...records, record]);
      await txn.put("private_enrollment_rates", [
        ...recent, { at: now, source: b.source },
      ]);
      return { status: 201, record };
    });
    if (result.status !== 201) return fail(result.status, "enrollment_limit_or_collision");
    return json({
      device_id: result.record.id,
      expires_in_seconds: ENROLLMENT_TTL_MS / 1000, state: "pending",
    }, 201);
  }
  if (path === "/enroll/list" && request.method === "GET") {
    const records = live((await store.get("private_enrollments")) || []);
    return json({
      requests: records.map((r) => ({
        device_id: r.id, device_name: r.name, state: r.state,
        expires_in_seconds: Math.max(0, Math.ceil((r.expires - now) / 1000)),
      })),
    });
  }
  const statusMatch = /^\/enroll\/status\/([a-f0-9]{32})$/.exec(path);
  if (statusMatch && request.method === "GET") {
    const secret = bearer(request);
    if (!secret || !HASH.test(secret)) return fail(401, "enrollment_auth_required");
    const records = await store.get("private_enrollments") || [];
    const record = records.find((r) => r.id === statusMatch[1]);
    if (!record || record.expires <= now) return fail(410, "enrollment_expired");
    if (!fixedEqual(record.secretHash, await digest(secret)))
      return fail(403, "enrollment_auth_failed");
    // Status is never used as proof of ChatGPT OAuth or local Windows grants.
    return json({ device_id: record.id, state: record.state });
  }
  const rejectMatch = /^\/enroll\/reject\/([a-f0-9]{32})$/.exec(path);
  if (rejectMatch && request.method === "DELETE") {
    const result = await store.transaction(async (txn) => {
      const records = await txn.get("private_enrollments") || [];
      const r = records.find((x) => x.id === rejectMatch[1]);
      if (!r || r.state !== "pending") return false;
      await txn.put("private_enrollments", records.filter((x) => x.id !== r.id));
      return true;
    });
    return result ? json({ rejected: true }) : fail(409, "not_pending");
  }
  const approveMatch = /^\/enroll\/approve\/([a-f0-9]{32})$/.exec(path);
  if (approveMatch && request.method === "POST") {
    const b = await readJson(request);
    if (!/^[A-F0-9]{10}$/.test(b.code || "")) return fail(400, "invalid_code");
    const approval = await store.transaction(async (txn) => {
      const records = await txn.get("private_enrollments") || [];
      const r = records.find((x) => x.id === approveMatch[1]);
      if (!r || r.expires <= now || r.state !== "pending")
        return { status: 409 };
      if (!fixedEqual(r.secretHash.slice(0, 10).toUpperCase(), b.code))
        return { status: 403 };
      // Persist "registering" BEFORE the first side-effect to avoid replay
      // when a Durable Object/backend times out after registration.
      r.state = "registering";
      await txn.put("private_enrollments", records);
      return { status: 200, tokenHash: r.tokenHash, deviceId: r.id };
    });
    if (approval.status !== 200)
      return fail(approval.status, "approval_rejected");
    let response;
    try {
      const stub = env.DEVICES.get(env.DEVICES.idFromName(approval.deviceId));
      response = await stub.fetch(new Request("https://internal/enroll/register", {
        method: "POST",
        body: JSON.stringify({ device_token_sha256: approval.tokenHash }),
      }));
    } catch {
      return fail(503, "registration_outcome_unknown_do_not_retry");
    }
    if (response.status !== 201)
      return fail(503, "registration_outcome_unknown_do_not_retry");
    await store.transaction(async (txn) => {
      const records = await txn.get("private_enrollments") || [];
      const r = records.find((x) => x.id === approval.deviceId);
      if (r && r.state === "registering") {
        r.state = "approved";
        await txn.put("private_enrollments", records);
      }
    });
    return json({ approved: true, device_id: approval.deviceId });
  }
  return fail(404, "not_found");
}
