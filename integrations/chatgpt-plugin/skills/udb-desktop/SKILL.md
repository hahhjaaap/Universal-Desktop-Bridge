---
name: udb-desktop
description: Use when the user wants to inspect, troubleshoot, or operate the connected UDB Windows desktop bridge.
---

# UDB Desktop Bridge

> **UDB 0.12.0 documentation review (2026-11-13):** Staging/opt-in instructions do not change live Worker, OAuth, owner permissions or secrets. See [version/status](../../../../docs/current-version.md).

Use this skill only with the authenticated UDB MCP server configured by this plugin.

## Connection verification

1. Inspect the tools actually exposed by the connected MCP server. Do not assume a tool exists merely because it is mentioned in documentation.
2. If `bridge_status` is exposed, call it first and report its returned status without inferring that the desktop is online from public health checks alone.
3. If the server is not connected, explain that the user must complete the Cloudflare Access OAuth sign-in and consent flow. Never bypass Access or use a second, unauthenticated endpoint.
4. Distinguish public preflight success, OAuth login initiation, successful user authentication, and successful end-to-end desktop operations. They are separate states.

## Operating rules

- Use only tools and parameters advertised by the live MCP server.
- Follow the Windows owner's configured device permissions and any server-side path allowlist.
- Prefer status and read-only operations. Do not enumerate unrelated personal files, browser profiles, cookies, credentials, or secrets.
- Before a write, delete, process launch, software installation, or other state-changing action, explain the exact target and impact and obtain explicit confirmation.
- Never retrieve or expose OAuth tokens, pairing secrets, Cloudflare credentials, or authentication cookies.
- If a tool call fails, preserve the original error and diagnose the actual layer. Do not weaken authentication, broaden resource access, or disable device authorization as a workaround.
