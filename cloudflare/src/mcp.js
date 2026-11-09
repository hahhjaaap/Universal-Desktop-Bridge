// Opt-in stateless Streamable HTTP MCP resource. No admin or device secrets
// are accepted as user authentication; only explicit read-only grants are exposed.
import { readJson, validRpc } from "./auth.js";
import { AuthError, authorize, oauthConfig } from "./oauth.js";
import { accessConfig, authorizeAccess } from "./access.js";
import { isReadTool } from "./read-tools.js";
import { edgeCatalog, edgeCatalogSupported } from "./edge-discovery.js";
export { authorizeAccess } from "./access.js";

const supported = new Set(["2025-03-26", "2025-06-18", "2025-11-25"]);
const MODERN_VERSION = "2026-07-28";
// UDB is a dual-era server: it supports both modern per-request metadata
// and the legacy initialize handshake, so discovery lists both honestly.
const SUPPORTED_VERSIONS = Object.freeze([MODERN_VERSION, ...supported]);
const META = "io.modelcontextprotocol/";
const json = (value, status = 200, headers = {}) => new Response(JSON.stringify(value), {
  status, headers: { "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store", "x-content-type-options": "nosniff", ...headers } });
const error = (status, code) => json({ error: code }, status);
const rpcError = (rpc, code, message, status = 400) => {
  // Only bounded, static protocol categories; never IDs, arguments or identity.
  console.warn(JSON.stringify({ event: "mcp_protocol_rejected", code, reason: message }));
  return json({ jsonrpc: "2.0", id: rpc.id, error: { code, message } }, status);
};
const serverInfo = (user) => ({
  name: user.ownerTools?.length ? "udb-cloud-owner-gated" : "udb-cloud-readonly",
  version: "0.1.0",
});
const modernResult = (result, user) => ({
  ...result, resultType: "complete",
  _meta: { ...result._meta, [META + "serverInfo"]: serverInfo(user) },
});
function mirroredName(value) {
  if (value?.startsWith("=?base64?") && value.endsWith("?=")) {
    try {
      const bytes = Uint8Array.from(atob(value.slice(9, -2)), c => c.charCodeAt(0));
      return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    } catch { return null; }
  }
  return value;
}
export const metadataPath = (id) => "/.well-known/oauth-protected-resource/v1/devices/" + id + "/mcp";

export function protectedResource(request, env, id) {
  // RFC 9728 standard discovery improves compatibility with MCP clients that
  // do not understand Cloudflare's vendor-prefixed resource metadata URL.
  // This endpoint only advertises an issuer. It never grants access or
  // replaces Cloudflare Access authentication for the protected MCP route.
  const resource = new URL(request.url).origin + "/v1/devices/" + id + "/mcp";
  const mode = env?.UDB_AUTH_MODE || "jwt";
  if (mode === "cloudflare-access") {
    const cfg = accessConfig(env);
    if (!cfg?.team) return error(503, "access_not_configured");
    return json({ resource, authorization_servers: [cfg.team],
      scopes_supported: ["udb:read"] });
  }
  if (mode !== "jwt") return error(503, "invalid_auth_mode");
  const cfg = oauthConfig(env);
  if (!cfg) return error(503, "oauth_not_configured");
  return json({ resource, authorization_servers: [cfg.issuer],
    scopes_supported: ["udb:read"] });
}

function challenge(request, id) {
  return json({ error: "invalid_token_or_device_grant" }, 401, {
    "www-authenticate": 'Bearer resource_metadata="' +
      new URL(request.url).origin + metadataPath(id) + '", scope="udb:read"',
  });
}

async function relay(stub, rpc) {
  try {
    return await stub.fetch(new Request("https://internal/rpc", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify(rpc),
    }));
  } catch { return error(503, "relay_unavailable_outcome_unknown"); }
}

async function isExplicitDeviceOffline(response) {
  if (response.status !== 503) return false;
  try {
    const body = await readJson(response.clone());
    return body?.error === "device_offline";
  } catch { return false; }
}

async function unavailable(response, code) {
  const safeReasons = new Set(["device_offline", "device_busy",
    "device_connection_changed", "device_disconnected_outcome_unknown",
    "outcome_unknown_do_not_retry_mutations", "invalid_device_rpc_response",
    "relay_unavailable_outcome_unknown"]);
  let reason = "upstream_unavailable";
  try {
    const body = await readJson(response);
    if (safeReasons.has(body.error)) reason = body.error;
  } catch { /* Never echo raw device errors, paths, or response bodies. */ }
  return json({ error: code, diagnostics: { reason,
    upstream_status: response.status, dispatched_outcome: "unverified",
    next_action: reason === "device_offline" ? "Reconnect the local UDB cloud agent, then initialize again." :
      reason === "device_busy" ? "Wait for the current request to finish, then request discovery again." :
      "Inspect device status and reconnect; do not replay uncertain tool calls.",
  } }, [429, 502, 503, 504].includes(response.status) ? response.status : 503);
}

export async function handleMcp(request, env, id, stub, fetchImpl = fetch, access = null) {
  const origin = request.headers.get("Origin");
  if (origin && origin !== new URL(request.url).origin) {
    console.warn(JSON.stringify({ event: "udb_mcp_scan_denied", category: "origin_mismatch" }));
    return error(403, "invalid_origin");
  }
  if (request.method !== "POST") return error(405, "method_not_allowed");
  const version = request.headers.get("MCP-Protocol-Version") || "2025-03-26";
  // Choose exactly one auth scheme; an unknown mode must fail closed.
  // Even version negotiation must not bypass owner identity/device grants.
  const mode = env?.UDB_AUTH_MODE || "jwt";
  if (mode !== "jwt" && mode !== "cloudflare-access")
    return error(503, "invalid_auth_mode");
  if (mode === "jwt" && !oauthConfig(env))
    return error(503, "oauth_not_configured");
  if (mode === "cloudflare-access" &&
      !accessConfig(env))
    return error(503, "access_not_configured");

  let user;
  if (mode === "cloudflare-access") {
    // Cloudflare runtime identity or a verified Access-signed JWT only.
    try { user = await authorizeAccess(access, env, id, request, fetchImpl); }
    catch (failure) {
      // Do not log caller identity, bearer material, JWTs, device IDs, or
      // request bodies. Only static reason classes are permitted in logs.
      const safe = new Set(["access_audience_mismatch",
        "verified_identity_missing", "device_grant_missing"]);
      const category = failure instanceof AuthError && safe.has(failure.message)
        ? failure.message : "identity_unverified";
      console.warn(JSON.stringify({ event: "udb_mcp_scan_denied", category }));
      return error(403, "cloudflare_access_identity_or_grant_required");
    }
  } else {
    try { user = await authorize(request, env, id, fetchImpl); }
    catch (e) {
      return e instanceof AuthError ? challenge(request, id) :
        error(503, "auth_unavailable");
    }
  }
  let rpc;
  try { rpc = await readJson(request); }
  catch { return error(400, "invalid_json_rpc"); }
  if (rpc.jsonrpc !== "2.0" || typeof rpc.method !== "string") return error(400, "invalid_json_rpc");
  // MCP initialized is a JSON-RPC notification: it intentionally has no ID.
  // Admit it only after owner/device authorization, for a supported legacy
  // protocol version, with a well-formed optional params object. Do not
  // reflect notification fields in any error or forward it to Windows.
  if (rpc.method === "notifications/initialized" &&
      !Object.hasOwn(rpc, "id") && supported.has(version)) {
    if (rpc.params !== undefined &&
        (!rpc.params || typeof rpc.params !== "object" ||
         Array.isArray(rpc.params))) return error(400, "invalid_json_rpc");
    const announced = rpc.params?._meta?.[META + "protocolVersion"];
    if (announced !== undefined && announced !== version)
      return error(400, "protocol_version_mismatch");
    return new Response(null, { status: 202,
      headers: { "cache-control": "no-store" } });
  }
  // Validate the JSON-RPC ID before constructing any detailed protocol
  // error. Otherwise malformed IDs can be reflected in mismatch responses
  // even though neither the legacy proxy nor the modern protocol accepts
  // them. The same upper bound is enforced by validRpc before forwarding.
  if (!((typeof rpc.id === "string" && rpc.id.length > 0 &&
          rpc.id.length <= 256) || Number.isSafeInteger(rpc.id)))
    return error(400, "invalid_rpc_id");
  const modern = version === MODERN_VERSION;
  const claimedVersion = rpc.params?._meta?.[META + "protocolVersion"];
  if (claimedVersion !== undefined && claimedVersion !== version)
    return rpcError(rpc, -32020, "Protocol header/body mismatch");
  if (!supported.has(version) && !modern) {
    // The modern spec requires this structured error so clients can
    // negotiate; never send arbitrary request arguments or identities.
    // Validate the id before reflecting it in a JSON-RPC response.
    if (!((typeof rpc.id === "string" && rpc.id !== "" && rpc.id.length <= 256) ||
          Number.isSafeInteger(rpc.id)))
      return error(400, "invalid_rpc_id");
    if (version.length > 64) return error(400, "invalid_protocol_version");
    return json({ jsonrpc: "2.0", id: rpc.id, error: {
      code: -32022, message: "Unsupported protocol version",
      data: { supported: SUPPORTED_VERSIONS, requested: version },
    } }, 400);
  }
  if (modern) {
    const meta = rpc.params?._meta;
    const caps = meta?.[META + "clientCapabilities"];
    if (claimedVersion !== MODERN_VERSION || !caps || typeof caps !== "object" || Array.isArray(caps))
      return rpcError(rpc, -32602, "Missing or invalid per-request protocol metadata");
    if (request.headers.get("Mcp-Method") !== rpc.method ||
        (rpc.method === "tools/call" &&
         (typeof rpc.params?.name !== "string" ||
          mirroredName(request.headers.get("Mcp-Name")) !== rpc.params.name)))
      return rpcError(rpc, -32020, "Required MCP headers must match the request body");
    if (!((typeof rpc.id === "string" && rpc.id !== "") || Number.isSafeInteger(rpc.id)))
      return rpcError(rpc, -32600, "Invalid RPC ID");
    if (rpc.method === "server/discover")
      return json({ jsonrpc: "2.0", id: rpc.id, result: modernResult({
         supportedVersions: SUPPORTED_VERSIONS, capabilities: { tools: {} },
        ttlMs: 0, cacheScope: "private",
      }, user) });
    if (!["tools/list", "tools/call"].includes(rpc.method))
      return rpcError(rpc, -32601, "Method not found", 404);
    // The gateway adapts modern stateless HTTP to the 2025 stdio proxies.
    // Each Windows proxy remains serial, but independent reads may use
    // separate proxy instances; initialization happens per instance.
    // Untrusted client metadata never controls local initialization/identity.
    rpc = { ...rpc, params: { ...rpc.params } };
    delete rpc.params._meta;
  }
  if (!((typeof rpc.id === "string" && rpc.id !== "") || Number.isSafeInteger(rpc.id)))
    return error(400, "invalid_rpc_id");
  if (!validRpc(rpc)) return error(400, "invalid_json_rpc");
  // Opt-in only: the verified owner/device READ grant is sufficient for
  // discovery, not for declaring that Windows is online or executing tools.
  // LocalProxy initializes each worker before the first forwarded tools/call.
  const useEdgeCatalog = mode === "cloudflare-access" &&
    edgeCatalogSupported(env, user);
  if (useEdgeCatalog && rpc.method === "initialize") {
    const requested = rpc.params?.protocolVersion;
    return json({ jsonrpc: "2.0", id: rpc.id, result: {
      protocolVersion: supported.has(requested) ? requested : "2025-11-25",
      capabilities: { tools: { listChanged: false } },
      serverInfo: { name: "udb-cloud-edge-discovery", version: "0.1.0" },
    } });
  }
  if (useEdgeCatalog && rpc.method === "tools/list") {
    const result = { tools: edgeCatalog(user.allowTools) };
    console.info(JSON.stringify({ event: "udb_mcp_tools_discovered",
      source: "edge", count: result.tools.length }));
    return json({ jsonrpc: "2.0", id: rpc.id, result:
      modern ? modernResult({ ...result, ttlMs: 0, cacheScope: "private" }, user)
        : result,
    });
  }
  if (rpc.method === "initialize") {
    // The Windows stdio proxy must receive initialize before tools/list.
    // Otherwise this edge handshake succeeds while the first discovery call
    // fails with "MCP not initialized" and ChatGPT displays zero tools.
    const upstream = await relay(stub, rpc);
    if (!upstream.ok)
      return unavailable(upstream, "device_initialize_unavailable");
    let answer;
    try { answer = await upstream.json(); }
    catch { return error(502, "invalid_device_initialize_response"); }
    if (answer?.jsonrpc !== "2.0" || answer.id !== rpc.id ||
        !answer.result || !supported.has(answer.result.protocolVersion) ||
        Object.hasOwn(answer, "error"))
      return error(502, "device_initialize_rejected");
    return json({ jsonrpc: "2.0", id: rpc.id, result: {
      protocolVersion: answer.result.protocolVersion, capabilities: { tools: { listChanged: false } },
      serverInfo: {
        name: user.ownerTools?.length ? "udb-cloud-owner-gated" : "udb-cloud-readonly",
        version: "0.1.0",
      },
    } });
  }
  if (rpc.method === "ping") return json({ jsonrpc: "2.0", id: rpc.id, result: {} });
  if (!["tools/list", "tools/call"].includes(rpc.method) || !validRpc(rpc))
    return error(400, "unsupported_rpc");
  if (rpc.method === "tools/call" && !user.allowTools.includes(rpc.params.name))
    return error(403, "device_tool_not_authorized");
  const response = await relay(stub, rpc);
  if (!response.ok) {
    // Only an explicit DO "no device socket" response may yield an offline
    // diagnostic. Never relabel 429/timeout/uncertain dispatched outcomes.
    // A real bridge_status is still forwarded when the device is available.
    if (useEdgeCatalog && rpc.method === "tools/call" &&
        rpc.params.name === "bridge_status" &&
        await isExplicitDeviceOffline(response)) {
      const offline = { content: [{ type: "text",
        text: "Windows UDB is offline; start the Cloud Agent and reconnect." }],
        structuredContent: { windows_device_verified: false,
          connection: "offline", reason: "device_offline" },
        isError: true,
      };
      return json({ jsonrpc: "2.0", id: rpc.id,
        result: modern ? modernResult(offline, user) : offline });
    }
    return unavailable(response, "device_unavailable_outcome_unknown");
  }
  let reply;
  try { reply = await response.json(); }
  catch { return error(502, "invalid_device_response"); }
  if (!reply || reply.jsonrpc !== "2.0" || typeof reply.id !== typeof rpc.id ||
      reply.id !== rpc.id || ("result" in reply) === ("error" in reply))
    return error(502, "invalid_device_response");
  if (rpc.method === "tools/list" && !reply.error) {
    if (!Array.isArray(reply.result?.tools)) return error(502, "invalid_device_catalog");
    reply.result = { tools: reply.result.tools.filter((tool) =>
      tool && user.allowTools.includes(tool.name)).map((tool) => ({
        ...tool,
        // Access Managed OAuth binds the client to the exact protected
        // application; non-read privileges are checked by separate owner
        // grants and local approvals, not falsely labeled udb:read.
        securitySchemes: [{
          type: "oauth2", scopes: isReadTool(tool.name) ? ["udb:read"] : [],
        }],
      })) };
  }
  if (modern && reply.result) {
    if (typeof reply.result !== "object" || Array.isArray(reply.result))
      return error(502, "invalid_device_response");
    reply.result = modernResult(reply.result, user);
    if (rpc.method === "tools/list")
      Object.assign(reply.result, { ttlMs: 0, cacheScope: "private" });
  }
  return json(reply);
}
