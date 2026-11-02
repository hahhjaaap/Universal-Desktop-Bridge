# Render: optional independent read-only UDB observer

Render does not run device commands, identify individual PCs, authenticate
end users, or proxy MCP traffic. Cloudflare remains the main connection path.

## Deployment

- After reviewing the draft source, create a Render account and attach the
  repository using a Blueprint based on the root render.yaml.
- The blueprint requests a Free web service and disables automatic deployment.
  It does not request credentials, databases, or cloud command privileges.
- Set UDB_RELAY_HEALTH_ORIGIN in Render environment settings to the actual
  HTTPS Cloudflare Worker origin, such as https://example.account.workers.dev.
  Only workers.dev hostnames without credentials, ports, paths or parameters
  are accepted; any other value fails closed.
- Open the Render dashboard and click the manual connection-check button.
  It queries only the public Cloudflare /health route. No device information
  or credentials are requested or displayed.
- The dashboard itself runs on Render and can sleep on its Free plan when idle.

## Operational boundaries

- Built entirely with Node 22 standard library, with no runtime dependencies.
- No OAuth/admin device tokens, no permissions to control a Windows computer.
- Does not accept arbitrary external URLs from HTTP requests.
- Cloudflare response capped at 2 KiB, rejects redirects, 3s end-to-end timeout.
- Status distinguishes 429 rate limits, upstream 502/503/504, invalid health JSON,
  timeouts and successful public health checks. A healthy relay does **not**
  confirm any Windows device is online, authorized or reachable.
- No background health polling, only user-triggered on-demand checks.
- The Cloudflare private relay remains an experimental developer-only
  prototype; full OAuth, per-user permissions and GUI pairing are still pending.

## Tests

Run: node --test render/tests/*.test.mjs

For the cloud relay details see docs/cloudflare-relay-prototype.md.
