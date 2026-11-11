import { authorizeAccess, handleMcp, metadataPath } from "./mcp.js";
import { livePage } from "./live-page.js";

const ID = /^[a-f0-9]{32}$/i;
const HEADERS = {
  "Cache-Control": "no-store, private",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "X-Frame-Options": "DENY",
  "Cross-Origin-Resource-Policy": "same-origin",
};
const GRANTS = ["host_status", "host_browser", "host_screenshot"];

function reply(status, error, extra = {}) {
  return Response.json({ error }, { status, headers: { ...HEADERS, ...extra } });
}

function objectResult(result) {
  if (result?.isError) return null;
  const value = result?.structuredContent?.result ?? result?.structuredContent;
  if (value && typeof value === "object" && !Array.isArray(value)) return value;
  const first = result?.content?.find(block => block?.type === "text");
  try { return JSON.parse(first?.text ?? "null"); }
  catch { return null; }
}

export async function handleLive(request, env, device, stub, access) {
  if (env.UDB_AUTH_MODE !== "cloudflare-access") return reply(404, "live_unavailable");
  const url = new URL(request.url);
  const data = url.searchParams.get("data");
  if (data !== null && request.headers.get("Sec-Fetch-Site") !== "same-origin")
    return reply(403, "live_same_origin_required");
  let user;
  try {
    user = await authorizeAccess(access, env, device, request);
  } catch {
    return reply(401, "live_sign_in_required", {
      "WWW-Authenticate": 'Bearer resource_metadata="' + url.origin + metadataPath(device) + '"',
    });
  }
  if (!GRANTS.every(name => user.allowTools.includes(name)))
    return reply(403, "live_owner_grants_required");

  if (data === null) {
    const nonce = crypto.randomUUID().replaceAll("-", "");
    return new Response(livePage(nonce), { headers: {
      ...HEADERS,
      "Content-Type": "text/html; charset=utf-8",
      "Content-Security-Policy": "default-src 'none'; script-src 'nonce-" + nonce +
        "'; style-src 'nonce-" + nonce + "'; connect-src 'self'; img-src blob:; " +
        "base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
    } });
  }

  const session = url.searchParams.get("session");
  const tab = url.searchParams.get("tab");
  let tool;
  let args;
  if (data === "status") {
    tool = "host_status";
    args = {};
  } else if (data === "tabs" && ID.test(session ?? "")) {
    tool = "host_browser";
    args = { action: "list", session_id: session };
  } else if (data === "frame" && ID.test(session ?? "") && ID.test(tab ?? "")) {
    tool = "host_screenshot";
    args = { session_id: session, tab_id: tab };
  } else {
    return reply(400, "live_invalid_request");
  }
  // Reuse the normal MCP authorization, device relay and local tool checks.
  // Request parameters select only a fixed, read-only operation.
  const headers = new Headers(request.headers);
  headers.delete("Content-Length");
  headers.set("Content-Type", "application/json");
  headers.set("MCP-Protocol-Version", "2025-11-25");
  const rpc = { jsonrpc: "2.0", id: crypto.randomUUID(), method: "tools/call",
    params: { name: tool, arguments: args } };
  const mcp = await handleMcp(new Request(url.origin + url.pathname, {
    method: "POST", headers, body: JSON.stringify(rpc),
  }), env, device, stub, fetch, access);
  if (!mcp.ok) return reply(mcp.status, "live_device_unavailable");
  let result;
  try { ({ result } = await mcp.json()); }
  catch { return reply(502, "live_invalid_device_response"); }
  if (!result || result.isError) return reply(503, "live_device_unavailable");

  if (data === "frame") {
    const png = result.content?.find(block => block?.type === "image" && block.mimeType === "image/png");
    if (!png || typeof png.data !== "string" || png.data.length > 1024 * 1024)
      return reply(503, "live_frame_unavailable");
    try {
      const bytes = Uint8Array.from(atob(png.data), byte => byte.charCodeAt(0));
      if (![137, 80, 78, 71, 13, 10, 26, 10].every((byte, index) => bytes[index] === byte))
        return reply(502, "live_invalid_frame");
      return new Response(bytes, { headers: { ...HEADERS, "Content-Type": "image/png" } });
    } catch { return reply(502, "live_invalid_frame"); }
  }

  const info = objectResult(result);
  if (!info || typeof info !== "object") return reply(502, "live_invalid_device_response");
  const safe = data === "status" ? {
    enabled: info.enabled === true,
    ready: info.worker_ready === true,
    sessions: (Array.isArray(info.sessions) ? info.sessions : [])
      .filter(row => row?.kind === "browser" && row.presentation === "background" &&
        row.closing !== true && ID.test(row.session_id ?? ""))
      .slice(0, 2).map(row => ({ id: row.session_id })),
  } : {
    tabs: (Array.isArray(info.tabs) ? info.tabs : [])
      .filter(row => row?.background === true && ID.test(row.tab_id ?? ""))
      .slice(0, 4).map(row => ({ id: row.tab_id,
        title: typeof row.title === "string" ? row.title.slice(0, 160) : "" })),
  };
  return Response.json(safe, { headers: HEADERS });
}
