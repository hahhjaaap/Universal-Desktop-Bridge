"""Managed OAuth preflight must verify the exact edge-protected resource."""

import io
import json
from urllib.error import HTTPError

import pytest

from tools.check_cloudflare_deployment import check
from udb.cloud_agent import CLOUD_USER_AGENT
from udb.cloud_preflight import failure_reason

ORIGIN = "https://example.workers.dev"
DEVICE = "a" * 32
RESOURCE = ORIGIN + "/v1/devices/" + DEVICE + "/mcp"
GENERIC_META = ORIGIN + "/.well-known/cloudflare-access-protected-resource/"
SCOPED_META = GENERIC_META + "v1/devices/" + DEVICE + "/mcp"
STANDARD_META = (
    ORIGIN + "/.well-known/oauth-protected-resource/v1/devices/" + DEVICE + "/mcp"
)


class Response(io.BytesIO):
    status = 200

    def __init__(self, body, headers=None):
        super().__init__(body)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class Opener:
    def __init__(
        self,
        *,
        worker_capable=True,
        edge="managed",
        metadata_valid=True,
        scoped_resource=None,
        standard_available=True,
        standard_resource=None,
        standard_issuer=None,
        standard_scopes=None,
    ):
        self.urls = []
        self.worker_capable = worker_capable
        self.edge = edge
        self.metadata_valid = metadata_valid
        self.scoped_resource = scoped_resource
        self.standard_available = standard_available
        self.standard_resource = standard_resource
        self.standard_issuer = standard_issuer
        self.standard_scopes = standard_scopes

    def open(self, request, timeout):
        assert timeout == 8
        assert request.get_header("User-agent") == CLOUD_USER_AGENT
        assert request.get_header("Authorization") is None
        assert request.get_header("Cookie") is None
        self.urls.append(request.full_url)
        if request.full_url == ORIGIN + "/health":
            headers = {"X-UDB-Access-OAuth-Capable": "1"} if self.worker_capable else {}
            return Response(
                b'{"status":"ok","kind":"private-relay-prototype"}', headers
            )
        if request.full_url == STANDARD_META:
            if not self.standard_available:
                raise HTTPError(request.full_url, 404, "missing", {}, None)
            standard_value = {
                "resource": (
                    self.standard_resource
                    if self.standard_resource is not None
                    else RESOURCE
                ),
                "authorization_servers": [
                    self.standard_issuer
                    if self.standard_issuer is not None
                    else "https://owner-check.cloudflareaccess.com"
                ],
                "scopes_supported": (
                    self.standard_scopes
                    if self.standard_scopes is not None
                    else ["udb:read"]
                ),
            }
            return Response(json.dumps(standard_value).encode())
        if request.full_url in {GENERIC_META, SCOPED_META}:
            scoped = request.full_url == SCOPED_META
            value = {
                "protected": self.metadata_valid,
                "resource": (
                    self.scoped_resource
                    if self.scoped_resource is not None
                    else RESOURCE
                    if scoped
                    else ORIGIN
                ),
                "team_domain": "owner-check.cloudflareaccess.com",
                "authorization_servers": ["https://owner-check.cloudflareaccess.com"],
            }
            return Response(json.dumps(value).encode())
        if request.full_url == RESOURCE:
            challenges = {
                "managed": GENERIC_META,
                "managed-scoped": SCOPED_META,
                "wrong-device": (GENERIC_META + "v1/devices/" + "b" * 32 + "/mcp"),
                "query": SCOPED_META + "?redirect=https://example.invalid",
                "external": "https://evil.example/metadata",
                "jwt": (
                    ORIGIN
                    + "/.well-known/oauth-protected-resource/v1/devices/"
                    + DEVICE
                    + "/mcp"
                ),
            }
            metadata = challenges.get(self.edge)
            headers = (
                {"WWW-Authenticate": 'Bearer resource_metadata="' + metadata + '"'}
                if metadata
                else {}
            )
            raise HTTPError(
                request.full_url,
                401 if metadata else 403,
                "unauthorized",
                headers,
                None,
            )
        raise AssertionError("Unexpected probe URL")


@pytest.mark.parametrize("edge", ["managed", "managed-scoped"])
def test_access_preflight_accepts_only_its_own_edge_metadata(edge):
    opener = Opener(edge=edge)
    report = check(ORIGIN, DEVICE, opener, auth_mode="cloudflare-access")
    assert report["health"] == "ok"
    assert report["oauth_metadata"] == "cloudflare_access_metadata"
    assert report["unauthorized_access"] == "blocked"
    assert report["windows_device"] == "not_tested"
    assert report["chatgpt_oauth"] == "not_tested"
    assert len(opener.urls) == 3
    assert opener.urls[-1] == (GENERIC_META if edge == "managed" else SCOPED_META)


@pytest.mark.parametrize("edge", ["jwt", "denied"])
def test_access_preflight_rejects_worker_only_denials(edge):
    with pytest.raises(ValueError):
        check(ORIGIN, DEVICE, Opener(edge=edge), auth_mode="cloudflare-access")


def test_access_preflight_rejects_older_worker_before_access_probe():
    opener = Opener(worker_capable=False)
    with pytest.raises(ValueError, match="has not been deployed"):
        check(ORIGIN, DEVICE, opener, auth_mode="cloudflare-access")
    assert opener.urls == [ORIGIN + "/health"]


def test_access_preflight_rejects_unknown_mode_before_network():
    opener = Opener()
    with pytest.raises(ValueError, match="Unknown authentication mode"):
        check(ORIGIN, DEVICE, opener, auth_mode="disabled")
    assert not opener.urls


@pytest.mark.parametrize("edge", ["external", "wrong-device", "query"])
def test_access_preflight_refuses_untrusted_metadata_without_fetch(edge):
    opener = Opener(edge=edge)
    with pytest.raises(ValueError, match="Untrusted Cloudflare"):
        check(ORIGIN, DEVICE, opener, auth_mode="cloudflare-access")
    assert len(opener.urls) == 2


@pytest.mark.parametrize("edge", ["managed", "managed-scoped"])
def test_access_preflight_does_not_accept_unprotected_metadata(edge):
    opener = Opener(edge=edge, metadata_valid=False)
    with pytest.raises(ValueError, match="Invalid Cloudflare Access resource"):
        check(ORIGIN, DEVICE, opener, auth_mode="cloudflare-access")
    assert len(opener.urls) == 3


def test_scoped_metadata_must_identify_exact_device_not_broad_origin():
    opener = Opener(edge="managed-scoped", scoped_resource=ORIGIN)
    with pytest.raises(ValueError, match="Invalid Cloudflare Access resource"):
        check(ORIGIN, DEVICE, opener, auth_mode="cloudflare-access")
    assert opener.urls[-1] == SCOPED_META


def test_scoped_metadata_cannot_authorize_other_device():
    opener = Opener(
        edge="managed-scoped",
        scoped_resource=ORIGIN + "/v1/devices/" + "b" * 32 + "/mcp",
    )
    with pytest.raises(ValueError, match="Invalid Cloudflare Access resource"):
        check(ORIGIN, DEVICE, opener, auth_mode="cloudflare-access")
    assert opener.urls[-1] == SCOPED_META


@pytest.mark.parametrize("edge", ["managed", "managed-scoped"])
@pytest.mark.parametrize("invalid_resource", [{}, []])
def test_access_preflight_normalizes_non_string_resource(edge, invalid_resource):
    opener = Opener(edge=edge, scoped_resource=invalid_resource)
    with pytest.raises(ValueError, match="Invalid Cloudflare Access resource") as error:
        check(ORIGIN, DEVICE, opener, auth_mode="cloudflare-access")
    assert failure_reason(error.value) == "access_metadata_invalid"


def test_access_preflight_verifies_live_standard_rfc9728_metadata():
    opener = Opener(edge="managed-scoped")
    report = check(
        ORIGIN,
        DEVICE,
        opener,
        auth_mode="cloudflare-access",
        require_standard_metadata=True,
    )
    assert report["standard_oauth_metadata"] == "ok"
    assert report["unauthorized_access"] == "blocked"
    assert opener.urls[-1] == STANDARD_META
    assert len(opener.urls) == 4


@pytest.mark.parametrize(
    "kwargs",
    [
        {"standard_available": False},
        {"standard_resource": ORIGIN},
        {"standard_resource": ORIGIN + "/v1/devices/" + "b" * 32 + "/mcp"},
        {"standard_issuer": "https://evil.example"},
        {"standard_scopes": []},
        {"standard_scopes": ["udb:read", "admin:write"]},
    ],
)
def test_standard_discovery_fails_closed_if_missing_or_mismatched(kwargs):
    opener = Opener(edge="managed-scoped", **kwargs)
    with pytest.raises(ValueError, match="standard_oauth_metadata_invalid") as error:
        check(
            ORIGIN,
            DEVICE,
            opener,
            auth_mode="cloudflare-access",
            require_standard_metadata=True,
        )
    assert failure_reason(error.value) == "standard_oauth_metadata_invalid"
    assert opener.urls[-1] == STANDARD_META


def test_rfc9728_deep_check_requires_access_auth_mode_before_network():
    opener = Opener()
    with pytest.raises(ValueError, match="requires Cloudflare Access"):
        check(
            ORIGIN,
            DEVICE,
            opener,
            auth_mode="jwt",
            require_standard_metadata=True,
        )
    assert not opener.urls
