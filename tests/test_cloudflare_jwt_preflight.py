"""JWT-mode public preflight must not accept another device's OAuth metadata."""

import io
import json
from urllib.error import HTTPError

import pytest

from udb.cloud_preflight import check, failure_reason

ORIGIN = "https://example.workers.dev"
DEVICE = "a" * 32
OTHER = "b" * 32
RESOURCE = ORIGIN + "/v1/devices/" + DEVICE + "/mcp"
METADATA = (
    ORIGIN + "/.well-known/oauth-protected-resource/v1/devices/" + DEVICE + "/mcp"
)


class Response(io.BytesIO):
    status = 200

    def __init__(self, value):
        super().__init__(json.dumps(value).encode())
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class PublicJwt:
    def __init__(self, challenge=METADATA, servers=None, header_prefix="Bearer "):
        self.urls = []
        self.challenge = challenge
        self.servers = (
            ["https://identity.example.org/tenant/"] if servers is None else servers
        )
        self.header_prefix = header_prefix

    def open(self, request, timeout):
        assert timeout == 8
        assert request.get_header("Authorization") is None
        assert request.get_header("Cookie") is None
        self.urls.append(request.full_url)
        if request.full_url == ORIGIN + "/health":
            return Response({"status": "ok", "kind": "private-relay-prototype"})
        if request.full_url == METADATA:
            return Response(
                {
                    "resource": RESOURCE,
                    "authorization_servers": self.servers,
                }
            )
        if request.full_url == RESOURCE:
            raise HTTPError(
                RESOURCE,
                401,
                "denied",
                {
                    "WWW-Authenticate": self.header_prefix
                    + 'resource_metadata="'
                    + self.challenge
                    + '"'
                },
                None,
            )
        raise AssertionError("Unexpected request")


def test_jwt_preflight_requires_exact_device_challenge_and_never_loads_credentials():
    opener = PublicJwt()
    report = check(ORIGIN, DEVICE, opener, auth_mode="jwt")
    assert report["health"] == "ok"
    assert report["oauth_metadata"] == "ok"
    assert report["unauthorized_access"] == "blocked"
    assert report["windows_device"] == "not_tested"
    assert report["chatgpt_oauth"] == "not_tested"
    assert opener.urls == [ORIGIN + "/health", METADATA, RESOURCE]


@pytest.mark.parametrize(
    "challenge",
    [
        ORIGIN,
        ORIGIN + "/.well-known/oauth-protected-resource/v1/devices/" + OTHER + "/mcp",
        METADATA + "?redirect=other",
        METADATA + "#fragment",
        "https://other.workers.dev/.well-known/oauth-protected-resource",
        "http://example.workers.dev/.well-known/oauth-protected-resource",
        "",
    ],
)
def test_other_device_or_incorrect_metadata_challenge_is_denied(challenge):
    opener = PublicJwt(challenge=challenge)
    with pytest.raises(ValueError, match="Untrusted Cloudflare") as caught:
        check(ORIGIN, DEVICE, opener, auth_mode="jwt")
    assert failure_reason(caught.value) == "access_metadata_untrusted"
    assert opener.urls == [ORIGIN + "/health", METADATA, RESOURCE]


@pytest.mark.parametrize("prefix", ["NotBearer ", "", "Basic "])
def test_non_bearer_challenge_does_not_count_as_jwt_authorization(prefix):
    opener = PublicJwt(header_prefix=prefix)
    with pytest.raises(ValueError, match="oauth_challenge_missing_or_wrong_status"):
        check(ORIGIN, DEVICE, opener, auth_mode="jwt")


@pytest.mark.parametrize(
    "issuers",
    [
        [],
        ["http://identity.example.org"],
        ["https://identity.example.org", "https://identity.example.org"],
        ["https://identity.example.org?q=1"],
        ["https://identity.example.org#fragment"],
        ["https://identity.example.org/@path", "not-a-url"],
        ["https://user:secret@identity.example.org"],
        ["https://identity.example.org\nInjected: yes"],
        ["https://identity.example.org"] * 5,
        "https://identity.example.org",
        {"issuer": "https://identity.example.org"},
    ],
)
def test_invalid_authorization_server_metadata_is_rejected_before_mcp(issuers):
    opener = PublicJwt(servers=issuers)
    with pytest.raises(ValueError, match="Invalid OAuth protected resource metadata"):
        check(ORIGIN, DEVICE, opener, auth_mode="jwt")
    assert opener.urls == [ORIGIN + "/health", METADATA]


def test_issuer_https_non_default_port_is_valid_metadata():
    opener = PublicJwt(servers=["https://identity.example.org:8443/tenant"])
    report = check(ORIGIN, DEVICE, opener, auth_mode="jwt")
    assert report["unauthorized_access"] == "blocked"
