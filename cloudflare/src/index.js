// UDB Cloudflare private relay prototype. NOT a public MCP server.
// The desktop retains all UDB owner-grant and tool policy enforcement.
import { DEVICE_ID, HASH, bearer, adminAuthorized, digest, readJson, validRpc, fixedEqual } from "./auth.js";
import { newPairing, PAIRING_TTL_MS } from "./pairing.js";
import { handleMcp, protectedResource } from "./mcp.js";

const json = (obj, status = 200) => new Response(JSON.stringify(obj), {
  status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store",
    "x-content-type-options": "nosniff" }
});
const failure = (status, code) => json({ error: code }, status);
// A single Windows stdio proxy processes RPCs sequentially. Refuse additional
// calls rather than queue commands that might outlive HTTP timeouts.
const MAX_PENDING_PER_DEVICE = 1;
const MAX_REPLY_BYTES = 1024 * 1024;
const encoder = new TextEncoder();

// A failed Durable Object invocation is an upstream outage, not a malformed
// client request. Mutations may already have executed: no automatic replay.
async function forward(stub, request) {
  try { return await stub.fetch(request); }
  catch { return failure(503, "relay_unavailable_outcome_unknown"); }
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname === "/health" && request.method === "GET")
      return json({ status: "ok", kind: "private-relay-prototype" });
    if (url.pathname === "/v1/admin/pairings" && request.method === "POST") {
      if (!adminAuthorized(request, env)) return failure(401, "admin_auth_required");
      const { device_id, pairing_code, pairing_token_sha256 } = await newPairing();
      const expires_at = Date.now() + PAIRING_TTL_MS;
      const stub = env.DEVICES.get(env.DEVICES.idFromName(device_id));
      const issued = await forward(stub, new Request("https://internal/pair/issue", {
        method: "POST", body: JSON.stringify({ pairing_token_sha256, expires_at }),
      }));
      if (!issued.ok) return failure(503, "pairing_unavailable");
      return json({ device_id, pairing_code, expires_in_seconds: PAIRING_TTL_MS / 1000 }, 201);
    }
    const claimMatch = /^\/v1\/devices\/([a-f0-9]{32})\/claim$/.exec(url.pathname);
    if (claimMatch && request.method === "POST") {
      const pairingCode = bearer(request);
      if (!pairingCode || !HASH.test(pairingCode)) return failure(401, "pairing_auth_required");
      try {
        const body = await readJson(request);
        if (!HASH.test(body.device_token_sha256)) return failure(400, "invalid_token_hash");
        const stub = env.DEVICES.get(env.DEVICES.idFromName(claimMatch[1]));
        return forward(stub, new Request("https://internal/pair/claim", {
          method: "POST",
          headers: { Authorization: "Bearer " + pairingCode },
          body: JSON.stringify({ device_token_sha256: body.device_token_sha256 }),
        }));
      } catch {
        return failure(400, "invalid_request");
      }
    }
    const agentMatch = /^\/v1\/devices\/([a-f0-9]{32})\/connect$/.exec(url.pathname);
    if (agentMatch && request.method === "GET") {
      if (request.headers.get("Upgrade")?.toLowerCase() !== "websocket")
        return failure(426, "websocket_required");
      if (!bearer(request)) return failure(401, "device_auth_required");
      const id = env.DEVICES.idFromName(agentMatch[1]);
      return env.DEVICES.get(id).fetch(new Request("https://internal/connect", request));
    }
    const resourceMatch = /^\/\.well-known\/oauth-protected-resource\/v1\/devices\/([a-f0-9]{32})\/mcp$/.exec(url.pathname);
    if (resourceMatch && request.method === "GET")
      return protectedResource(request, env, resourceMatch[1]);
    const mcpMatch = /^\/v1\/devices\/([a-f0-9]{32})\/mcp$/.exec(url.pathname);
    if (mcpMatch) {
      if (!env.DEVICES?.get || !env.DEVICES?.idFromName)
        return failure(503, "relay_not_configured");
      const stub = env.DEVICES.get(env.DEVICES.idFromName(mcpMatch[1]));
      return handleMcp(request, env, mcpMatch[1], stub, fetch, ctx?.access);
    }
    const adminMatch = /^\/v1\/admin\/devices\/([a-f0-9]{32})(\/rpc|\/status)?$/.exec(url.pathname);
    if (!adminMatch) return failure(404, "not_found");
    if (!adminAuthorized(request, env)) return failure(401, "admin_auth_required");
    const id = env.DEVICES.idFromName(adminMatch[1]);
    const stub = env.DEVICES.get(id);
    try {
      if (!adminMatch[2] && request.method === "DELETE") {
        return forward(stub, new Request("https://internal/revoke", { method: "DELETE" }));
      }
      if (!adminMatch[2] && request.method === "PUT") {
        const body = await readJson(request);
        if (!HASH.test(body.device_token_sha256)) return failure(400, "invalid_token_hash");
        return forward(stub, new Request("https://internal/register", {
          method: "PUT", body: JSON.stringify(body),
        }));
      }
      if (adminMatch[2] === "/status" && request.method === "GET")
        return forward(stub, new Request("https://internal/status"));
      if (adminMatch[2] === "/rpc" && request.method === "POST") {
        // The original private prototype admin API can bypass user identity.
        // Keep it disabled when exposing a public, per-user MCP resource.
        if (env.UDB_ENABLE_DEV_ADMIN_RPC !== "true")
          return failure(403, "admin_rpc_disabled");
        const rpc = await readJson(request);
        if (!validRpc(rpc)) return failure(400, "invalid_rpc");
        return forward(stub, new Request("https://internal/rpc", {
          method: "POST", body: JSON.stringify(rpc),
        }));
      }
    } catch (error) {
      return failure(400, error instanceof SyntaxError ? "invalid_json" : "invalid_request");
    }
    return failure(405, "method_not_allowed");
  }
};

export class DeviceRelay {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
    this.pending = new Map();
  }

  deviceSocket() {
    return this.ctx.getWebSockets("device").find((ws) => ws.readyState === WebSocket.OPEN);
  }

  async fetch(request) {
    const path = new URL(request.url).pathname;
    if (path === "/pair/issue" && request.method === "POST") {
      const body = await readJson(request);
      if (!HASH.test(body.pairing_token_sha256) ||
          !Number.isSafeInteger(body.expires_at) ||
          body.expires_at <= Date.now() ||
          body.expires_at > Date.now() + PAIRING_TTL_MS + 1000) {
        return failure(400, "invalid_pairing");
      }
      if (await this.ctx.storage.get("device_token_sha256")) {
        return failure(409, "already_registered");
      }
      await this.ctx.storage.put({
        pairing_token_sha256: body.pairing_token_sha256,
        pairing_expires_at: body.expires_at,
        pairing_attempts: 0,
      });
      return json({ issued: true });
    }
    if (path === "/pair/claim" && request.method === "POST") {
      const code = bearer(request);
      if (!code || !HASH.test(code)) return failure(401, "pairing_auth_required");
      const body = await readJson(request);
      if (!HASH.test(body.device_token_sha256)) return failure(400, "invalid_token_hash");
      const codeHash = await digest(code);
      const result = await this.ctx.storage.transaction(async (txn) => {
        if (await txn.get("device_token_sha256")) return "already_registered";
        const expiry = await txn.get("pairing_expires_at");
        const expected = await txn.get("pairing_token_sha256");
        const attempts = await txn.get("pairing_attempts") || 0;
        if (!expected || !expiry || Date.now() >= expiry) return "pairing_expired";
        if (attempts >= 5) return "pairing_locked";
        if (!fixedEqual(expected, codeHash)) {
          await txn.put("pairing_attempts", attempts + 1);
          return "pairing_rejected";
        }
        await txn.put("device_token_sha256", body.device_token_sha256);
        await txn.delete(["pairing_token_sha256", "pairing_expires_at", "pairing_attempts"]);
        return "registered";
      });
      if (result === "registered") return json({ registered: true }, 201);
      if (result === "already_registered") return failure(409, result);
      return failure(403, "pairing_failed");
    }
    if (path === "/revoke" && request.method === "DELETE") {
      await this.ctx.storage.delete([
        "device_token_sha256", "pairing_token_sha256",
        "pairing_expires_at", "pairing_attempts",
      ]);
      for (const ws of this.ctx.getWebSockets("device")) ws.close(4001, "device revoked");
      return json({ revoked: true });
    }
    if (path === "/register" && request.method === "PUT") {
      const body = await readJson(request);
      if (!HASH.test(body.device_token_sha256)) return failure(400, "invalid_token_hash");
      await this.ctx.storage.put("device_token_sha256", body.device_token_sha256);
      for (const ws of this.ctx.getWebSockets("device")) ws.close(4001, "device token rotated");
      return json({ registered: true });
    }
    if (path === "/status") {
      return json({ registered: !!(await this.ctx.storage.get("device_token_sha256")),
        online: !!this.deviceSocket() });
    }
    if (path === "/connect") {
      const token = bearer(request);
      const expected = await this.ctx.storage.get("device_token_sha256");
      // Compare hashes; plaintext device secrets are never stored in the DO.
      if (!expected || !token || (await digest(token)) !== expected)
        return failure(403, "device_auth_failed");
      if (request.headers.get("Upgrade")?.toLowerCase() !== "websocket")
        return failure(426, "websocket_required");
      const pair = new WebSocketPair();
      const [client, server] = Object.values(pair);
      this.ctx.acceptWebSocket(server, ["device"]);
      server.serializeAttachment({ role: "device" });
      for (const ws of this.ctx.getWebSockets("device")) {
        if (ws !== server) ws.close(4002, "superseded by new device connection");
      }
      return new Response(null, { status: 101, webSocket: client });
    }
    if (path === "/rpc" && request.method === "POST") {
      const ws = this.deviceSocket();
      if (!ws) return failure(503, "device_offline");
      if (this.pending.size >= MAX_PENDING_PER_DEVICE) return failure(429, "device_busy");
      const rpc = await readJson(request);
      if (!validRpc(rpc)) return failure(400, "invalid_rpc");
      const requestId = crypto.randomUUID();
      return await new Promise((resolve) => {
        const timeout = setTimeout(() => {
          this.pending.delete(requestId);
          resolve(failure(504, "outcome_unknown_do_not_retry_mutations"));
        }, 25000);
        this.pending.set(requestId, { ws, resolve, timeout, rpcId: rpc.id });
        try {
          ws.send(JSON.stringify({ kind: "rpc", id: requestId, rpc }));
        } catch {
          clearTimeout(timeout);
          this.pending.delete(requestId);
          resolve(failure(503, "device_disconnected_outcome_unknown"));
        }
      });
    }
    return failure(404, "not_found");
  }

  webSocketMessage(ws, message) {
    if (typeof message !== "string" || encoder.encode(message).byteLength > MAX_REPLY_BYTES) {
      this.webSocketClose(ws, 1009, "message_too_large");
      return;
    }
    let item;
    try { item = JSON.parse(message); }
    catch {
      this.webSocketClose(ws, 1007, "invalid_json");
      return;
    }
    if (!item || item.kind !== "rpc_result" || typeof item.id !== "string" ||
        !item.rpc || typeof item.rpc !== "object" || Array.isArray(item.rpc)) {
      this.webSocketClose(ws, 1008, "invalid_rpc_response");
      return;
    }
    const waiting = this.pending.get(item.id);
    if (!waiting || waiting.ws !== ws) return;
    clearTimeout(waiting.timeout);
    this.pending.delete(item.id);
    const rpc = item.rpc;
    const hasResult = Object.prototype.hasOwnProperty.call(rpc, "result");
    const hasError = Object.prototype.hasOwnProperty.call(rpc, "error");
    if (rpc.jsonrpc !== "2.0" || rpc.id !== waiting.rpcId || hasResult === hasError) {
      waiting.resolve(failure(502, "invalid_device_rpc_response"));
      this.webSocketClose(ws, 1008, "invalid_rpc_response");
      return;
    }
    waiting.resolve(json(rpc));
  }

  webSocketClose(ws, code, reason) {
    for (const [id, pending] of this.pending) {
      if (pending.ws === ws) {
        clearTimeout(pending.timeout);
        this.pending.delete(id);
        pending.resolve(failure(503, "device_disconnected_outcome_unknown"));
      }
    }
    try { ws.close(code || 1000, reason || "closed"); } catch { /* already closed */ }
  }
  webSocketError(ws) {
    this.webSocketClose(ws, 1011, "connection_error");
  }
}
