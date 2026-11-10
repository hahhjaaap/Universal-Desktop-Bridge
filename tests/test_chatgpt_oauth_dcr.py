"""No-network regression tests for manual ChatGPT OAuth / DCR preflight."""

import io
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from tools.check_chatgpt_oauth import (
    PUBLIC_CALLBACK,
    check,
    staging_resource,
    validate_access_endpoint,
    validate_callback,
)

ORIGIN = "https://udb-example-staging.example.workers.dev"
DEVICE = "a" * 32
RESOURCE = ORIGIN + "/v1/devices/" + DEVICE + "/mcp"
ISSUER = "https://example.cloudflareaccess.com"


@pytest.mark.parametrize(
    "callback",
    [
        PUBLIC_CALLBACK,
        "https://chatgpt.com/connector/oauth/test-id",
        "https://chatgpt.com/connector/oauth/1d508afe-56f9",
    ],
)
def test_accept_official_callback_formats(callback):
    assert validate_callback(callback) == callback


@pytest.mark.parametrize(
    "callback",
    [
        "http://chatgpt.com/connector/oauth/callback",
        "https://chatgpt.com.evil.example/connector/oauth/callback",
        "https://chatgpt.com/connector/oauth/",
        "https://chatgpt.com/connector/oauth/callback?code=bad",
        "https://chatgpt.com/connector_platform_oauth_redirect#unexpected",
        "https://chatgpt.com/connector/oauth/callback/extra",
        "https://other.example/callback",
    ],
)
def test_reject_nonofficial_callbacks(callback):
    with pytest.raises(ValueError):
        validate_callback(callback)


@pytest.mark.parametrize(
    "relay,device",
    [
        ("http://udb-example-staging.example.workers.dev", DEVICE),
        ("https://udb-example-production.example.workers.dev", DEVICE),
        ("https://udb-example-staging.example.workers.dev/extra", DEVICE),
        ("https://udb-example-staging.example.workers.dev?forward=1", DEVICE),
        ("https://udb-example-staging.example.workers.dev", "foo"),
    ],
)
def test_reject_unsafe_staging_resource(relay, device):
    with pytest.raises(ValueError):
        staging_resource(relay, device)


def test_staging_resource_exact():
    assert staging_resource(ORIGIN, DEVICE) == RESOURCE


def test_issuer_not_external():
    with pytest.raises(ValueError):
        validate_access_endpoint(
            ISSUER,
            "https://malicious.invalid/cdn-cgi/access/oauth/registration",
            "/cdn-cgi/access/oauth/registration",
        )


class Response(io.BytesIO):
    def __init__(self, status, obj=None, headers=None):
        super().__init__(json.dumps(obj or {}).encode("utf-8"))
        self.status = status
        self.headers = headers or {}


class StubOpener:
    def __init__(self, *, missing_challenge=False, reject_callback=False):
        self.requests = []
        self.missing_challenge = missing_challenge
        self.reject_callback = reject_callback

    def open(self, req, timeout):
        assert timeout == 12
        self.requests.append((req.get_method(), req.full_url))
        u = urlsplit(req.full_url)
        if u.path.startswith("/.well-known/oauth-protected-resource/"):
            return Response(
                200,
                {
                    "resource": RESOURCE,
                    "authorization_servers": [ISSUER],
                    "scopes_supported": ["udb:read"],
                },
            )
        if u.path == "/.well-known/oauth-authorization-server":
            return Response(
                200,
                {
                    "issuer": ISSUER,
                    "registration_endpoint": ISSUER
                    + "/cdn-cgi/access/oauth/registration",
                    "authorization_endpoint": ISSUER
                    + "/cdn-cgi/access/oauth/authorization",
                    "grant_types_supported": ["authorization_code", "refresh_token"],
                    "code_challenge_methods_supported": ["S256"],
                },
            )
        if u.path.endswith("/mcp"):
            return Response(
                401,
                {},
                {}
                if self.missing_challenge
                else {"WWW-Authenticate": "Bearer realm=UDB"},
            )
        if u.path.endswith("/registration"):
            if self.reject_callback:
                return Response(400, {"error": "invalid_client_metadata"})
            body = json.loads(req.data)
            assert body["redirect_uris"] == [PUBLIC_CALLBACK]
            assert body["token_endpoint_auth_method"] == "none"
            return Response(201, {"client_id": "disposable-test-client"})
        if u.path.endswith("/authorization"):
            query = parse_qs(u.query)
            assert query["code_challenge_method"] == ["S256"]
            if query["resource"] == [RESOURCE]:
                return Response(
                    302,
                    {},
                    {"Location": ISSUER + "/cdn-cgi/access/login/udb-staging"},
                )
            return Response(400, {"error": "invalid_target"})
        raise AssertionError(f"Unexpected URL {u.path}")


def test_no_registration_by_default():
    opener = StubOpener()
    report = check(ORIGIN, DEVICE, opener=opener)
    assert report["dcr"] == "not_tested"
    assert report["unauthenticated_mcp"] == "denied"
    assert not any(path.endswith("/registration") for _, path in opener.requests)


def test_registered_callback_flows_to_login_not_token():
    opener = StubOpener()
    report = check(
        ORIGIN,
        DEVICE,
        callback=PUBLIC_CALLBACK,
        register_client=True,
        opener=opener,
    )
    assert report["dcr"] == "registered_callback_validated"
    assert report["wrong_resource"] == "denied"
    assert report["authenticated_chatgpt_mcp"] == "not_tested"
    assert not any("token" in path for _, path in opener.requests)


def test_missing_mcp_oauth_challenge_rejected():
    with pytest.raises(ValueError, match="OAuth 401"):
        check(ORIGIN, DEVICE, opener=StubOpener(missing_challenge=True))


def test_blocked_callback_reported_as_dcr_failure():
    with pytest.raises(ValueError, match="registration failed"):
        check(
            ORIGIN,
            DEVICE,
            callback=PUBLIC_CALLBACK,
            register_client=True,
            opener=StubOpener(reject_callback=True),
        )
