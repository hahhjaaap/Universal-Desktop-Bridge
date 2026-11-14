// One authenticated Cloudflare Access MCP resource for the owner's enrolled fleet.
// No current-device globals, client-supplied owner IDs, or delegated Windows permissions.
import { digest, readJson, validRpc, DEVICE_ID } from "./auth.js";
import { accessConfig, verifiedAccessIdentity } from "./access.js";
import { stableAccessSubject } from "./enrollment-owner.js";
import { handleMcp } from "./mcp.js";
import { ENROLLED_CATALOG } from "./local-permissions.js";
import { publicToolNames } from "./tool-families.js";

const MODERN = "2026-07-28";
const LEGACY = new Set(["2025-03-26", "2025-06-18", "2025-11-25"]);
const VERSIONS = [MODERN, ...LEGACY];
const META = "io.modelcontextprotocol/";
const NAME = /^[A-Za-z0-9 _.-]{1,48}$/;
const ALLOWED = new Set(publicToolNames(ENROLLED_CATALOG));
const json = (value, status = 200, headers = {}) => Response.json(value, {
  status, headers: { "cache-control": "no-store", "x-content-type-options": "nosniff", ...headers },
});
const fail = (status, code) => json({ error: code }, status);
const result = (id, value, modern = false) => json({ jsonrpc: "2.0", id,
  result: modern ? { ...value, resultType: "complete",
    _meta: { ...value._meta, [META + "serverInfo"]:
      { name: "udb-account-fleet", version: "0.1.0" } } } : value });
const denied = (request) => json({ error: "cloudflare_access_authentication_required" }, 401, {
  "www-authenticate": 'Bearer error="invalid_token", resource_metadata="' +
    new URL(request.url).origin +
    '/.well-known/oauth-protected-resource/v1/account/mcp", scope="udb:read"',
});

export const fleetEnabled = env =>
  env?.UDB_ENABLE_ACCOUNT_FLEET === "true" &&
  env?.UDB_ENABLE_BROWSER_ENROLLMENT === "true" &&
  env?.UDB_ENABLE_LOCAL_TOOL_SYNC === "true" &&
  env?.UDB_TENANT_POLICY === undefined &&
  env?.UDB_AUTH_MODE === "cloudflare-access" &&
  !!accessConfig(env)?.team && !!env.DEVICES?.get;

export function fleetProtectedResource(request, env) {
  if (!fleetEnabled(env)) return fail(404, "account_fleet_disabled");
  return json({ resource: new URL(request.url).origin + "/v1/account/mcp",
    authorization_servers: [accessConfig(env).team], scopes_supported: ["udb:read"] });
}

// Access runtime identity is authoritative when supplied by the platform;
// otherwise accept only the independently validated, pinned Access assertion.
export async function fleetIdentity(request, env, access = null, fetchImpl = fetch) {
  const config = accessConfig(env);
  if (!config?.team || !config.aud || (access && access.aud !== config.aud))
    return null;
  let identity;
  if (typeof access?.getIdentity === "function") {
    try {
      const observed = await access.getIdentity();
      identity = { sub: observed?.user_uuid };
    } catch { return null; }
  } else {
    try { identity = await verifiedAccessIdentity(request, env, fetchImpl); }
    catch { return null; }
  }
  return stableAccessSubject(identity, config.team);
}

async function registry(env, owner) {
  const key = await digest("udb-account-fleet:v1:" + owner);
  return env.DEVICES.get(env.DEVICES.idFromName("__udb_account_fleet_v1__" + key));
}

// A device-token-authenticated status check; never substitutes device auth for
// user OAuth and never reveals the linked owner's identity to anonymous callers.
export async function routeFleetLinkStatus(request, env) {
  const match = new RegExp("^/v1/devices/([a-f0-9]{32})/fleet/status$").exec(new URL(request.url).pathname);
  if (!match) return null;
  if (!fleetEnabled(env)) return fail(404, "account_fleet_disabled");
  if (request.method !== "GET") return fail(405, "method_not_allowed");
  if (request.headers.has("Origin")) return fail(403, "browser_origin_not_supported");
  try {
    const self = await env.DEVICES.get(env.DEVICES.idFromName(match[1])).fetch(
      new Request("https://internal/fleet/self", { headers: {
        Authorization: request.headers.get("Authorization") || "",
      } }));
    if (!self.ok) return fail(self.status, "device_auth_failed");
    const body = await self.json();
    if (!body.owner || !body.request_id) return json({ linked: false });
    const snapshot = await fleetSnapshot(env, body.owner);
    const entry = snapshot.devices.find(x => x.id === match[1] &&
      x.request_id === body.request_id);
    return json({ linked: Boolean(entry) });
  } catch { return fail(503, "fleet_registry_unavailable"); }
}

export async function registerEnrolledDevice(env, record) {
  // An enrollment approval already bound this record to an authenticated owner.
  // Reverify the actual device object before adding the idempotent index entry.
  if (!fleetEnabled(env)) return true; // feature-off leaves old enrollment intact
  const requestId = record?.request_id || record?.id;
  if (!DEVICE_ID.test(record?.id || "") || !DEVICE_ID.test(requestId || "") ||
      typeof record.owner !== "string" || record.owner.length > 500 ||
      !NAME.test(record.name))
    return false;
  const stub = env.DEVICES.get(env.DEVICES.idFromName(record.id));
  try {
    const status = await stub.fetch(new Request("https://internal/fleet/verify", {
      method: "POST", body: JSON.stringify({ owner: record.owner, request_id: requestId }),
    }));
    if (!status.ok || !(await status.json()).verified) return false;
    const account = await registry(env, record.owner);
    const response = await account.fetch(new Request("https://internal/fleet/register", {
      method: "POST", headers: { "X-UDB-Owner": record.owner },
      body: JSON.stringify({ id: record.id, name: record.name, request_id: requestId }),
    }));
    return response.status === 201;
  } catch { return false; } // The status poll safely retries this SAME registration.
}

export async function handleFleetRegistry(request, ctx) {
  const path = new URL(request.url).pathname;
  const owner = request.headers.get("X-UDB-Owner");
  if (typeof owner !== "string" || !/^https:\/\/[^\s#]+#[0-9a-f-]{36}$/.test(owner) ||
      owner.length > 500) return fail(403, "owner_invalid");
  const store = ctx.storage;
  if (path === "/fleet/register" && request.method === "POST") {
    const body = await readJson(request);
    if (!DEVICE_ID.test(body?.id || "") || !DEVICE_ID.test(body?.request_id || "") || !NAME.test(body.name))
      return fail(400, "invalid_device_registration");
    return store.transaction(async txn => {
      const bound = await txn.get("fleet_owner");
      if (bound && bound !== owner) return fail(409, "registry_owner_conflict");
      const entries = await txn.get("fleet_devices") || [];
      if (!Array.isArray(entries) || entries.length > 100) return fail(503, "registry_invalid");
      const prior = entries.find(x => x.id === body.id);
      if (prior) return prior.request_id === body.request_id && prior.name === body.name
        ? json({ registered: true }, 201) : fail(409, "registry_device_conflict");
      if (entries.length >= 100) return fail(429, "registry_full");
      await txn.put({ fleet_owner: owner, fleet_devices: [...entries, {
        id: body.id, name: body.name, request_id: body.request_id,
      }] });
      return json({ registered: true }, 201);
    });
  }
  if (path === "/fleet/list" && request.method === "GET") {
    const bound = await store.get("fleet_owner");
    if (bound && bound !== owner) return fail(403, "registry_owner_conflict");
    return json({ devices: bound ? await store.get("fleet_devices") || [] : [],
      catalog: bound ? await store.get("fleet_catalog") || null : null });
  }
  if (path === "/fleet/catalog" && request.method === "POST") {
    const body = await readJson(request);
    if (!Array.isArray(body?.tools) || body.tools.length === 0 || body.tools.length > 60 ||
        JSON.stringify(body).length > 512 * 1024 ||
        new Set(body.tools.map(x => x?.name)).size !== body.tools.length ||
        !body.tools.every(x => x && ALLOWED.has(x.name) && x.inputSchema?.type === "object" &&
          !Object.hasOwn(x.inputSchema.properties || {}, "device_id")))
      return fail(400, "invalid_catalog");
    return store.transaction(async txn => {
      if (await txn.get("fleet_owner") !== owner) return fail(403, "registry_owner_conflict");
      if (!await txn.get("fleet_catalog"))
        await txn.put("fleet_catalog", body.tools);
      return json({ stored: true });
    });
  }
  return fail(404, "not_found");
}

async function fleetSnapshot(env, owner) {
  const account = await registry(env, owner);
  const response = await account.fetch(new Request("https://internal/fleet/list", {
    headers: { "X-UDB-Owner": owner },
  }));
  if (!response.ok) throw Error("registry_unavailable");
  const body = await response.json();
  if (!Array.isArray(body.devices) || body.devices.length > 100) throw Error("registry_invalid");
  return { account, ...body };
}

async function verifiedDevice(env, owner, device) {
  const stub = env.DEVICES.get(env.DEVICES.idFromName(device.id));
  try {
    const response = await stub.fetch(new Request("https://internal/fleet/verify", {
      method: "POST", body: JSON.stringify({ owner, request_id: device.request_id }),
    }));
    if (!response.ok) return { stub, verified: false };
    const value = await response.json();
    return { stub, verified: value.verified === true, online: value.online === true,
      last_seen_at: Number.isSafeInteger(value.last_seen_at) ? value.last_seen_at : null };
  } catch { return { stub, verified: false }; }
}

async function deviceList(env, owner, entries) {
  // Concurrent status reads are isolated by their immutable IDs; errors cannot
  // silently route the next tool call to a different device.
  return Promise.all(entries.map(async entry => {
    const current = await verifiedDevice(env, owner, entry);
    return { device_id: entry.id, display_name: entry.name,
      connection: !current.verified ? "unverified" : current.online ? "online" : "offline",
      verified: current.verified,
      last_seen_at: current.verified && current.last_seen_at ?
        new Date(current.last_seen_at).toISOString() : null };
  }));
}

const listTool = {
  name: "list_devices",
  description: "List Windows devices enrolled to this authenticated owner, their stable IDs, current connection status and last contact. Choose device_id explicitly for every machine operation.",
  inputSchema: { type: "object", properties: {}, additionalProperties: false },
  annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true,
    openWorldHint: false },
  securitySchemes: [{ type: "oauth2", scopes: ["udb:read"] }],
};

function deviceCatalog(tools) {
  return tools.filter(t => ALLOWED.has(t.name)).map(tool => {
    const schema = structuredClone(tool.inputSchema);
    return { ...tool, description: (tool.description || "") +
      " Required device_id selects one Windows device; permissions are verified on that device.",
    inputSchema: { ...schema, properties: {
      ...schema.properties, device_id: { type: "string", pattern: "^[a-f0-9]{32}$",
        description: "Stable ID from list_devices (not a display name)." },
    }, required: [...new Set([...(schema.required || []), "device_id"])] } };
  });
}

function decodeName(raw) {
  if (raw?.startsWith("=?base64?") && raw.endsWith("?=")) {
    try { return new TextDecoder("utf-8", { fatal: true }).decode(
      Uint8Array.from(atob(raw.slice(9, -2)), x => x.charCodeAt(0))); }
    catch { return null; }
  }
  return raw;
}

function validateFleetRpc(request, rpc, version) {
  if (!rpc || rpc.jsonrpc !== "2.0" ||
      !((typeof rpc.id === "string" && rpc.id.length > 0 && rpc.id.length <= 256) ||
        Number.isSafeInteger(rpc.id)) || typeof rpc.method !== "string")
    return "invalid_rpc";
  if (!VERSIONS.includes(version)) return "unsupported_version";
  if (rpc.params !== undefined && (!rpc.params || typeof rpc.params !== "object" ||
      Array.isArray(rpc.params))) return "invalid_params";
  const meta = rpc.params?._meta;
  if (meta?.[META + "protocolVersion"] !== undefined &&
      meta[META + "protocolVersion"] !== version) return "metadata_mismatch";
  if (version === MODERN && (meta?.[META + "protocolVersion"] !== MODERN ||
      !meta?.[META + "clientCapabilities"] ||
      typeof meta[META + "clientCapabilities"] !== "object" ||
      Array.isArray(meta[META + "clientCapabilities"]) ||
      request.headers.get("Mcp-Method") !== rpc.method ||
      (rpc.method === "tools/call" && decodeName(request.headers.get("Mcp-Name")) !== rpc.params?.name)))
    return "metadata_mismatch";
  if (version === MODERN && !["server/discover", "tools/list", "tools/call"].includes(rpc.method))
    return "unsupported_method";
  if (rpc.method === "tools/call" && !validRpc(rpc)) return "invalid_params";
  return null;
}

function forwardedRequest(request, rpc, id) {
  return new Request(new URL(request.url).origin + "/v1/devices/" + id + "/mcp", {
    method: "POST", headers: request.headers, body: JSON.stringify(rpc),
  });
}

export async function handleAccountMcp(request, env, access = null, fetchImpl = fetch) {
  if (!fleetEnabled(env)) return fail(404, "account_fleet_disabled");
  const origin = request.headers.get("Origin");
  if (origin && origin !== new URL(request.url).origin) return fail(403, "invalid_origin");
  if (request.method !== "POST") return fail(405, "method_not_allowed");
  const owner = await fleetIdentity(request, env, access, fetchImpl);
  if (!owner) return denied(request);
  let snapshot, rpc;
  try { snapshot = await fleetSnapshot(env, owner); }
  catch { return fail(503, "fleet_registry_unavailable"); }
  try { rpc = await readJson(request); }
  catch { return fail(400, "invalid_json_rpc"); }
  const version = request.headers.get("MCP-Protocol-Version") || "2025-03-26";
  if (rpc?.jsonrpc === "2.0" && rpc.method === "notifications/initialized" &&
      !Object.hasOwn(rpc, "id") && LEGACY.has(version) &&
      (rpc.params === undefined || (rpc.params && typeof rpc.params === "object" &&
      !Array.isArray(rpc.params)))) return new Response(null, { status: 202 });
  const invalid = validateFleetRpc(request, rpc, version);
  if (invalid) return fail(400, invalid);
  const modern = version === MODERN;
  if (rpc.method === "server/discover")
    return result(rpc.id, { supportedVersions: VERSIONS, capabilities: { tools: {} },
      ttlMs: 0, cacheScope: "private" }, modern);
  if (rpc.method === "initialize")
    return result(rpc.id, { protocolVersion: LEGACY.has(rpc.params?.protocolVersion) ?
      rpc.params.protocolVersion : "2025-11-25", capabilities: { tools: { listChanged: false } },
      serverInfo: { name: "udb-account-fleet", version: "0.1.0" } });
  if (rpc.method === "ping") return result(rpc.id, {});
  if (rpc.method === "tools/list") {
    let catalog = snapshot.catalog;
    if (!catalog) {
      for (const device of snapshot.devices) {
        const current = await verifiedDevice(env, owner, device);
        if (!current.verified || !current.online) continue;
        const found = await handleMcp(forwardedRequest(request, rpc, device.id), env,
          device.id, current.stub, fetchImpl, access);
        if (!found.ok) continue;
        let payload;
        try { payload = await found.json(); } catch { continue; }
        const tools = payload?.result?.tools;
        if (!Array.isArray(tools) || !tools.length) continue;
        const safe = tools.filter(x => x && ALLOWED.has(x.name) && x.inputSchema?.type === "object" &&
          !Object.hasOwn(x.inputSchema.properties || {}, "device_id"));
        if (!safe.length) continue;
        const response = await snapshot.account.fetch(new Request("https://internal/fleet/catalog", {
          method: "POST", headers: { "X-UDB-Owner": owner },
          body: JSON.stringify({ tools: safe }),
        }));
        if (response.ok) { catalog = safe; break; }
      }
    }
    return result(rpc.id, { tools: [listTool, ...deviceCatalog(catalog || [])],
      ...(modern ? { ttlMs: 0, cacheScope: "private" } : {}) }, modern);
  }
  if (rpc.method !== "tools/call") return fail(400, "unsupported_rpc");
  if (rpc.params.name === "list_devices") {
    if (Object.keys(rpc.params.arguments || {}).length) return fail(400, "invalid_tool_arguments");
    const devices = await deviceList(env, owner, snapshot.devices);
    const value = { content: [{ type: "text", text: JSON.stringify(devices) }],
      structuredContent: { devices } };
    return result(rpc.id, value, modern);
  }
  const args = rpc.params.arguments;
  const id = args?.device_id;
  if (!DEVICE_ID.test(id || "") || Object.hasOwn(rpc.params, "device_id"))
    return fail(400, "device_id_required");
  const entry = snapshot.devices.find(x => x.id === id);
  if (!entry) return fail(403, "device_not_owned");
  const current = await verifiedDevice(env, owner, entry);
  if (!current.verified) return fail(403, "device_ownership_unverified");
  if (!current.online) return fail(503, "device_offline");
  const { device_id, ...rest } = args;
  // No replay: delegate once to the existing per-device Access/local-permission
  // gateway and retain its response status, protocol adaptation and errors.
  return handleMcp(forwardedRequest(request, { ...rpc, params: {
    ...rpc.params, arguments: rest } }, id), env, id, current.stub, fetchImpl, access);
}
