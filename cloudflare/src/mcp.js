// Opt-in stateless Streamable HTTP MCP resource. No admin or device secrets
// are accepted as user authentication; only explicit read-only grants are exposed.
import { readJson, validRpc } from "./auth.js";
import { AuthError, authorize, oauthConfig } from "./oauth.js";
import { accessConfig, authorizeAccess } from "./access.js";
export { authorizeAccess } from "./access.js";

const supported = new Set(["2025-03-26", "2025-06-18", "2025-11-25"]);
const json = (value, status = 200, headers = {}) => new Response(JSON.stringify(value), {
  status, headers: { "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store", "x-content-type-options": "nosniff", ...headers } });
const error = (status, code) => json({ error: code }, status);
export const metadataPath = (id) => "/.well-known/oauth-protected-resource/v1/devices/" + id + "/mcp";

export function protectedResource(request, env, id) {
  // Cloudflare publishes its own metadata in Managed OAuth mode.
  if ((env?.UDB_AUTH_MODE || "jwt") !== "jwt")
    return error(404, "oauth_metadata_owned_by_access");
  const cfg = oauthConfig(env);
  if (!cfg) return error(503, "oauth_not_configured");
  return json({ resource: new URL(request.url).origin + "/v1/devices/" + id + "/mcp",
    authorization_servers: [cfg.issuer], scopes_supported: ["udb:read"] });
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
  if (origin && origin !== new URL(request.url).origin) return error(403, "invalid_origin");
  if (request.method !== "POST") return error(405, "method_not_allowed");
  const version = request.headers.get("MCP-Protocol-Version") || "2025-03-26";
  if (!supported.has(version)) return error(400, "unsupported_protocol_version");
  // Choose exactly one auth scheme; an unknown mode must fail closed.
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
    catch { return error(403, "cloudflare_access_identity_or_grant_required"); }
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
  if (rpc.method === "notifications/initialized" && rpc.id === undefined)
    return new Response(null, { status: 202, headers: { "cache-control": "no-store" } });
  if (!((typeof rpc.id === "string" && rpc.id !== "") || Number.isSafeInteger(rpc.id)))
    return error(400, "invalid_rpc_id");
  if (!validRpc(rpc)) return error(400, "invalid_json_rpc");
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
      serverInfo: { name: "udb-cloud-readonly", version: "0.1.0" },
    } });
  }
  if (rpc.method === "ping") return json({ jsonrpc: "2.0", id: rpc.id, result: {} });
  if (!["tools/list", "tools/call"].includes(rpc.method) || !validRpc(rpc))
    return error(400, "unsupported_rpc");
  if (rpc.method === "tools/call" && !user.allowTools.includes(rpc.params.name))
    return error(403, "device_tool_not_authorized");
  const response = await relay(stub, rpc);
  if (!response.ok)
    return unavailable(response, "device_unavailable_outcome_unknown");
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
        ...tool, securitySchemes: [{ type: "oauth2", scopes: ["udb:read"] }],
      })) };
  }
  return json(reply);
}
