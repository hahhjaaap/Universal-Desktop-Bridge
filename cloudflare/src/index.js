// UDB Cloudflare private relay prototype. NOT a public MCP server.
// The desktop retains all UDB owner-grant and tool policy enforcement.
import { DEVICE_ID, HASH, bearer, adminAuthorized, digest, readJson, validRpc } from "./auth.js";

const json = (obj, status = 200) => new Response(JSON.stringify(obj), {
  status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store",
    "x-content-type-options": "nosniff" }
});
const failure = (status, code) => json({ error: code }, status);

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/health" && request.method === "GET")
      return json({ status: "ok", kind: "private-relay-prototype" });
    const agentMatch = /^\/v1\/devices\/([a-f0-9]{32})\/connect$/.exec(url.pathname);
    if (agentMatch && request.method === "GET") {
      if (request.headers.get("Upgrade")?.toLowerCase() !== "websocket")
        return failure(426, "websocket_required");
      if (!bearer(request)) return failure(401, "device_auth_required");
      const id = env.DEVICES.idFromName(agentMatch[1]);
      return env.DEVICES.get(id).fetch(new Request("https://internal/connect", request));
    }
    const adminMatch = /^\/v1\/admin\/devices\/([a-f0-9]{32})(\/rpc|\/status)?$/.exec(url.pathname);
    if (!adminMatch) return failure(404, "not_found");
    if (!adminAuthorized(request, env)) return failure(401, "admin_auth_required");
    const id = env.DEVICES.idFromName(adminMatch[1]);
    const stub = env.DEVICES.get(id);
    try {
      if (!adminMatch[2] && request.method === "PUT") {
        const body = await readJson(request);
        if (!HASH.test(body.device_token_sha256)) return failure(400, "invalid_token_hash");
        return stub.fetch(new Request("https://internal/register", {
          method: "PUT", body: JSON.stringify(body),
        }));
      }
      if (adminMatch[2] === "/status" && request.method === "GET")
        return stub.fetch(new Request("https://internal/status"));
      if (adminMatch[2] === "/rpc" && request.method === "POST") {
        const rpc = await readJson(request);
        if (!validRpc(rpc)) return failure(400, "invalid_rpc");
        return stub.fetch(new Request("https://internal/rpc", {
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
      if (this.pending.size >= 4) return failure(429, "device_busy");
      const rpc = await readJson(request);
      if (!validRpc(rpc)) return failure(400, "invalid_rpc");
      const requestId = crypto.randomUUID();
      return await new Promise((resolve) => {
        const timeout = setTimeout(() => {
          this.pending.delete(requestId);
          resolve(failure(504, "outcome_unknown_do_not_retry_mutations"));
        }, 25000);
        this.pending.set(requestId, { ws, resolve, timeout });
        try {
          ws.send(JSON.stringify({ kind: "rpc", id: requestId, rpc }));
        } catch {
          clearTimeout(timeout);
          this.pending.delete(requestId);
          resolve(failure(503, "device_disconnected"));
        }
      });
    }
    return failure(404, "not_found");
  }

  webSocketMessage(ws, message) {
    if (typeof message !== "string" || message.length > 128 * 1024) {
      ws.close(1009, "message_too_large");
      return;
    }
    let item;
    try { item = JSON.parse(message); } catch { return; }
    if (!item || item.kind !== "rpc_result" || typeof item.id !== "string" ||
        !item.rpc || typeof item.rpc !== "object") return;
    const waiting = this.pending.get(item.id);
    if (!waiting || waiting.ws !== ws) return;
    clearTimeout(waiting.timeout);
    this.pending.delete(item.id);
    waiting.resolve(json(item.rpc));
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
