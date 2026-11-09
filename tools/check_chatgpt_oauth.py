"""Public, fail-closed diagnostic for ChatGPT -> Cloudflare Access -> UDB MCP.

The default checks are read-only. --register-client explicitly creates a
disposable OAuth DCR client, never performs user login and never requests tokens.
This is not a substitute for an authenticated ChatGPT -> Windows MCP acceptance.
"""

import argparse
import json
import re
import secrets
from urllib import error, parse, request

PUBLIC_CALLBACK = "https://chatgpt.com/connector_platform_oauth_redirect"
CALLBACK_PATTERN = re.compile(r"/connector/oauth/[A-Za-z0-9_-]{1,128}\Z")
DEVICE_PATTERN = re.compile(r"[0-9a-f]{32}\Z")
UA = "UDB-ChatGPT-OAuth-Preflight/1.0"
TIMEOUT = 12


def staging_resource(relay, device_id):
    parsed = parse.urlsplit(relay)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".workers.dev")
        or "staging" not in parsed.hostname.split(".")[0]
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or not DEVICE_PATTERN.fullmatch(device_id)
    ):
        raise ValueError("Expected an exact staging Worker origin and 32-hex device ID")
    origin = "https://" + parsed.hostname
    return origin + "/v1/devices/" + device_id + "/mcp"


def validate_callback(callback):
    parsed = parse.urlsplit(callback)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "chatgpt.com"
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or (callback != PUBLIC_CALLBACK and not CALLBACK_PATTERN.fullmatch(parsed.path))
    ):
        raise ValueError("Only exact official ChatGPT OAuth callbacks are allowed")
    return callback


def validate_access_endpoint(issuer, endpoint, expected_path):
    base = parse.urlsplit(issuer)
    actual = parse.urlsplit(endpoint or "")
    if (
        base.scheme != "https"
        or not base.hostname
        or not base.hostname.endswith(".cloudflareaccess.com")
        or base.port not in (None, 443)
        or base.username
        or base.password
        or base.path not in ("", "/")
        or base.query
        or base.fragment
        or actual.scheme != base.scheme
        or actual.netloc != base.netloc
        or actual.path != expected_path
        or actual.query
        or actual.fragment
    ):
        raise ValueError(
            "Cloudflare Access authorization endpoint not pinned to issuer"
        )
    return endpoint


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http(opener, url, *, method="GET", data=None, accept="application/json"):
    headers = {"User-Agent": UA, "Accept": accept}
    payload = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(data).encode("utf-8")
    req = request.Request(url, data=payload, method=method, headers=headers)
    try:
        response = opener.open(req, timeout=TIMEOUT)
    except error.HTTPError as exc:
        response = exc
    with response:
        body = response.read(65536)
        try:
            doc = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            doc = {}
        return response.status, response.headers, doc


def check(relay, device_id, *, callback=None, register_client=False, opener=None):
    resource = staging_resource(relay, device_id)
    if register_client:
        validate_callback(callback or "")
    opener = opener or request.build_opener(NoRedirect())
    origin = resource.split("/v1/devices/", 1)[0]
    path = resource.split(origin, 1)[1]
    metadata_url = origin + "/.well-known/oauth-protected-resource" + path
    status, _, meta = http(opener, metadata_url)
    if (
        status != 200
        or meta.get("resource") != resource
        or len(meta.get("authorization_servers", [])) != 1
        or not isinstance(meta["authorization_servers"][0], str)
    ):
        raise ValueError("RFC 9728 discovery rejected or unbound to exact resource")
    issuer = meta["authorization_servers"][0]
    validate_access_endpoint(
        issuer,
        issuer + "/cdn-cgi/access/oauth/authorization",
        "/cdn-cgi/access/oauth/authorization",
    )
    base = issuer.rstrip("/")
    as_url = base + "/.well-known/oauth-authorization-server"
    status, _, auth = http(opener, as_url)
    if status != 200 or auth.get("issuer") != issuer:
        raise ValueError("OAuth authorization server discovery mismatched")
    registration = validate_access_endpoint(
        issuer, auth.get("registration_endpoint"), "/cdn-cgi/access/oauth/registration"
    )
    authorize = validate_access_endpoint(
        issuer,
        auth.get("authorization_endpoint"),
        "/cdn-cgi/access/oauth/authorization",
    )
    if (
        "S256" not in auth.get("code_challenge_methods_supported", [])
        or "authorization_code" not in auth.get("grant_types_supported", [])
        or "refresh_token" not in auth.get("grant_types_supported", [])
    ):
        raise ValueError("OAuth PKCE or refresh grant not advertised")
    for method, data in [
        ("GET", None),
        (
            "POST",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "UDB-preflight", "version": "1.0"},
                },
            },
        ),
    ]:
        status, headers, _ = http(opener, resource, method=method, data=data)
        if status != 401 or not headers.get("WWW-Authenticate"):
            raise ValueError("Unauthenticated MCP request did not get OAuth 401")
    report = {
        "staging_only": True,
        "exact_resource_metadata": "passed",
        "oauth_discovery": "passed",
        "pkce_s256": "supported",
        "refresh_token": "supported",
        "unauthenticated_mcp": "denied",
        "dcr": "not_tested",
        "authenticated_chatgpt_mcp": "not_tested",
    }
    if not register_client:
        return report
    status, _, client = http(
        opener,
        registration,
        method="POST",
        data={
            "client_name": "UDB disposable staging preflight",
            "redirect_uris": [callback],
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )
    client_id = client.get("client_id")
    if status != 201 or not isinstance(client_id, str) or not client_id:
        raise ValueError(
            "OAuth DCR registration failed (verify ChatGPT callback allowlist)"
        )
    challenge = secrets.token_urlsafe(48)[:64]
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": callback,
        "state": secrets.token_urlsafe(16),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": resource,
    }
    status, headers, _ = http(
        opener,
        authorize + "?" + parse.urlencode(params),
        accept="text/html",
    )
    redir = parse.urlsplit(headers.get("Location", ""))
    if (
        status != 302
        or redir.scheme != "https"
        or redir.netloc != parse.urlsplit(issuer).netloc
        or not redir.path.startswith("/cdn-cgi/access/login/")
    ):
        raise ValueError("OAuth authorization did not enter Cloudflare Access login")
    params["resource"] = "https://invalid.example/mcp"
    status, _, _ = http(
        opener, authorize + "?" + parse.urlencode(params), accept="text/html"
    )
    if status != 400:
        raise ValueError("Wrong-resource OAuth authorization was not denied")
    report["dcr"] = "registered_callback_validated"
    report["oauth_authorization"] = "redirects_to_login"
    report["wrong_resource"] = "denied"
    report["warning"] = (
        "One disposable OAuth client was registered; no token issued. "
        "Authentication and permitted Windows file access still require a user."
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relay", required=True)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--register-client", action="store_true")
    parser.add_argument("--callback", default=PUBLIC_CALLBACK)
    args = parser.parse_args(argv)
    try:
        report = check(
            args.relay,
            args.device_id,
            callback=args.callback,
            register_client=args.register_client,
        )
    except (ValueError, error.URLError, OSError) as exc:
        print(json.dumps({"result": "failed", "reason": str(exc)[:180]}))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
