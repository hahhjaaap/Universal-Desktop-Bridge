// Render is a public, read-only UDB observer; never relay commands or secrets.
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const MAX_BODY = 2048;
const securityHeaders = {
  "cache-control": "no-store",
  "content-security-policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
  "referrer-policy": "no-referrer",
  "x-content-type-options": "nosniff",
  "x-frame-options": "DENY",
};

export function relayOrigin(value) {
  if (typeof value !== "string" || value.length > 250) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password ||
        url.search || url.hash || (url.pathname !== "/" && url.pathname !== "") ||
        url.port || !url.hostname.endsWith(".workers.dev")) return null;
    return url.origin;
  } catch {
    return null;
  }
}

async function boundedText(response) {
  if (!response.body) return "";
  const reader = response.body.getReader();
  let size = 0;
  const chunks = [];
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_BODY) throw new Error("upstream_body_too_large");
      chunks.push(value);
    }
  } finally {
    await reader.cancel().catch(() => {});
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(bytes);
}

export async function probeRelay(originValue, fetchImpl = fetch) {
  const origin = relayOrigin(originValue);
  if (!origin) return { state: "not_configured" };
  const controller = new AbortController();
  // Bound the entire HTTP exchange, including body streaming, not just headers.
  const timer = setTimeout(() => controller.abort(), 3000);
  try {
    const response = await fetchImpl(origin + "/health", {
      method: "GET", redirect: "error",
      signal: controller.signal,
      headers: { accept: "application/json" },
    });
    if (response.status === 429) return { state: "rate_limited" };
    if ([502, 503, 504].includes(response.status)) return { state: "upstream_unavailable" };
    if (response.status !== 200 ||
        !response.headers.get("content-type")?.includes("application/json")) {
      return { state: "unavailable" };
    }
    let data;
    try { data = JSON.parse(await boundedText(response)); }
    catch (error) {
      if (controller.signal.aborted) return { state: "timeout" };
      return { state: error?.message === "upstream_body_too_large"
        ? "unavailable" : "unexpected_response" };
    }
    if (data?.status !== "ok" || data?.kind !== "private-relay-prototype") {
      return { state: "unexpected_response" };
    }
    return { state: "online" };
  } catch (error) {
    if (controller.signal.aborted || error?.name === "AbortError" ||
        error?.name === "TimeoutError") return { state: "timeout" };
    return { state: "unavailable" };
  } finally {
    clearTimeout(timer);
  }
}

function send(response, status, type, body) {
  response.writeHead(status, { ...securityHeaders, "content-type": type });
  response.end(body);
}

export function makeServer(options = {}) {
  const origin = options.relay ?? process.env.UDB_RELAY_HEALTH_ORIGIN ?? "";
  const fetchImpl = options.fetchImpl ?? fetch;
  return createServer(async (request, response) => {
    const pathname = new URL(request.url ?? "/", "http://localhost").pathname;
    if (request.method !== "GET") {
      return send(response, 405, "application/json",
        JSON.stringify({ error: "method_not_allowed" }));
    }
    if (pathname === "/health") {
      return send(response, 200, "application/json",
        JSON.stringify({ status: "ok", service: "udb-render-observer" }));
    }
    if (pathname === "/api/relay-status") {
      return send(response, 200, "application/json",
        JSON.stringify(await probeRelay(origin, fetchImpl)));
    }
    if (pathname === "/" || pathname === "/app.js" || pathname === "/style.css") {
      const filename = pathname === "/" ? "index.html" : pathname.slice(1);
      const type = filename.endsWith(".js") ? "text/javascript; charset=utf-8" :
        filename.endsWith(".css") ? "text/css; charset=utf-8" : "text/html; charset=utf-8";
      try {
        return send(response, 200, type, await readFile(join(root, "public", filename)));
      } catch {
        return send(response, 500, "text/plain", "Dashboard unavailable");
      }
    }
    return send(response, 404, "application/json",
      JSON.stringify({ error: "not_found" }));
  });
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const port = Number(process.env.PORT || "10000");
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("Invalid PORT");
  makeServer().listen(port, "0.0.0.0", () => {
    console.log("UDB read-only Render observer listening.");
  });
}
