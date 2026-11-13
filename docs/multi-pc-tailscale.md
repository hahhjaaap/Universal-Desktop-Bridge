# UDB Multi-PC over two different Wi-Fi networks (experimental)

> **UDB 0.12.0 docs review (2026-11-13):** **Historical design/evidence, not a current runbook.** Earlier experiments, metrics and version-specific status do not establish current v0.12.0 behavior; never execute obsolete deployment/transport instructions. See [version/status](current-version.md).

> **Historical experimental transport, not the UDB v0.12.0 remote setup path.**
> UDB v0.12.0 removed the OpenAI Tunnel compatibility transport. The
> hub/Tunnel design below is kept for architectural research and must not be
> presented as a supported v0.12.0 installation or deployed to a real device.
> Current supported pairing instructions: [standalone quickstart](standalone-quickstart-vi.md)
> and [remote troubleshooting](remote-device-troubleshooting.md).

This is a **historical opt-in source experiment** first developed on the `feature/multi-pc-tailscale-router` branch, not a supported v0.12.0 Windows install path. Related source/test fixtures may remain for compatibility; Do not replace a working
UDB installation with untested branch code. Test it on a separate source checkout.

## Architecture

- PC A (hub): the existing ChatGPT MCP tunnel and UDB proxy. With a local
  `state/fleet.json` it advertises two extra MCP tools:
  `fleet_list_computers` and `fleet_call`.
- PC B (agent): one attended, loopback-only `udb fleet-agent` HTTP listener,
  reverse proxied to the private tailnet through **Tailscale Serve**.
- Both machines keep separate owner-granted UDB access and protected paths.
  Each device has a stable ID. No fallback to PC A if PC B is offline.
- A single ChatGPT plugin connects to PC A. No OpenAI API calls are made by
  the fleet router.
- The remote agent will *not* serve requests directly on a public interface.
  **Never use Tailscale Funnel or Internet port-forwarding for this feature.**

## 1. Prepare the two devices locally

Install Tailscale on both Windows machines and sign into the same authorized
tailnet. Set tailnet ACLs to allow only PC A to access PC B's Serve endpoint.
Do not grant remote-access privileges to unrelated tailnet users.

The **owner of PC B** must activate the ordinary UDB computer permission if
they want remote desktop/process/file access. The fleet agent does not grant it.

## 2. Generate a separate device secret on PC B

Run in a **local Windows PowerShell terminal**, not through UDB/ChatGPT:

```powershell
$dir = Join-Path $env:LOCALAPPDATA "UniversalDesktopBridge\state\fleet-secrets"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$bytes = New-Object byte[] 48
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
$rng.Dispose()
$secret = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
Set-Content -LiteralPath (Join-Path $dir "pc-office.token") -Encoding ASCII -NoNewline -Value $secret
```

Transfer **only this secret** to PC A over an owner-approved secure channel,
and save it as the same path/name in PC A's UDB state directory. Never put the
secret in ChatGPT, a GitHub issue, a command-line argument or `fleet.json`.
Protect the token file with Windows account ACLs. Each remote device needs a
different token. Never reuse the OpenAI tunnel API key.

## 3. Run the agent on PC B

After building/running UDB from the experimental source checkout, start locally:

```powershell
udb fleet-agent --device-id pc-office
```

The default allows only a fixed set of read-only UDB tools. To allow broader
tools, start from an **attended local terminal** with:

```powershell
udb fleet-agent --device-id pc-office --allow-control
```

The owner must type `ALLOW FLEET`. Every routed tool still goes through PC B's
existing UDB authorization and resource/safety checks. This is *not* UAC bypass
or credential sharing.

The local agent listens only at `127.0.0.1:18743`.

In a separate **local administrative PowerShell** on PC B, enable private
Tailscale Serve (never Funnel):

```powershell
tailscale serve --bg 18743
tailscale serve status
```

Read the `https://...ts.net` URL from the output. Serve may ask you to enable
tailnet HTTPS certificates in the Tailscale UI; this requires your consent.
Keep the local agent terminal alive; `Ctrl+C` stops the agent.
To disable tailnet sharing locally, run `tailscale serve off`.

Official reference: https://tailscale.com/docs/reference/tailscale-cli/serve

## 4. Configure the Hub on PC A

Create `%LOCALAPPDATA%\UniversalDesktopBridge\state\fleet.json` **locally**:

```json
{
  "schema": 1,
  "local_id": "pc-home",
  "remotes": [
    {"id": "pc-office", "url": "https://pc-office.YOUR-TAILNET.ts.net"}
  ]
}
```

Use the actual Tailscale Serve URL, not the placeholder. Fleet URLs must be
HTTPS `*.ts.net` origins (no custom ports or paths). The Hub uses TLS
certificate validation, no HTTP proxy and no redirects. Token paths are fixed
in UDB's local `state/fleet-secrets` directory.

Restart **only the hub's own UDB process, from a local owner terminal**, once
the source build with this feature has been installed/tested. Do not invoke
UDB's update/restart from a UDB computer_execute job.

## 5. Verify before enabling remote writes

From ChatGPT using the existing single UDB plugin on PC A:

1. Call `fleet_list_computers` to see configured `pc-home` and `pc-office`.
   **Being listed is not proof of being online.**
2. Call `fleet_call` with
   `{"computer_id":"pc-office","tool":"bridge_status","arguments":{}}`.
3. Verify that the response comes from the intended PC B.
4. Only then request another supported tool. PC A remains available through
   the existing ordinary tools; `fleet_call` also accepts `pc-home` to invoke
   them explicitly.

If remote calls time out, treat their outcomes as **unknown** and inspect the
destination before retrying a mutation. The router never forwards a failed
request to the other PC. If the B computer disconnects, B operations fail.

## Scope / limitations

- This is a prototype: Windows integration and two physical tailnet PCs are
  **not yet verified**; the existing installed UDB does not contain this code.
- Neither Tailscale installation nor its local login is automated by UDB.
- The agent runs in a visible owner-started terminal; restart it manually after
  reboot. There is no unattended service installer yet.
- TCP/HTTPS is only transport. Authorization still requires UDB's original
  per-machine owner grant plus a per-device bearer token and tailnet ACLs.
- Response size and request size are bounded; no retry of remote mutations.
- Initial plugin tool discovery may be cached by ChatGPT. Restart the hub
  connection and refresh its MCP tool catalog in the ChatGPT interface.
