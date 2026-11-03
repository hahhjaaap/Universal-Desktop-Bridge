"""Managed OAuth preflight must verify Cloudflare edge, not Worker denial."""

import io
import json
from urllib.error import HTTPError

import pytest

from tools.check_cloudflare_deployment import check
from udb.cloud_agent import CLOUD_USER_AGENT

ORIGIN = "https://example.workers.dev"
DEVICE = "a" * 32


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
    def __init__(self, *, worker_capable=True, edge="managed", metadata_valid=True):
        self.urls = []
        self.worker_capable = worker_capable
        self.edge = edge
        self.metadata_valid = metadata_valid

    def open(self, request, timeout):
        assert timeout == 8
        assert request.get_header("User-agent") == CLOUD_USER_AGENT
        assert request.get_header("Authorization") is None
        self.urls.append(request.full_url)
        if request.full_url == ORIGIN + "/health":
            headers = {"X-UDB-Access-OAuth-Capable": "1"} if self.worker_capable else {}
            return Response(
                b'{"status":"ok","kind":"private-relay-prototype"}',
                headers,
            )
        if (
            request.full_url
            == ORIGIN + "/.well-known/cloudflare-access-protected-resource/"
        ):
            value = {
                "protected": self.metadata_valid,
                "resource": ORIGIN,
                "team_domain": "owner-check.cloudflareaccess.com",
                "authorization_servers": ["https://owner-check.cloudflareaccess.com"],
            }
            return Response(json.dumps(value).encode())
        if request.full_url.endswith("/mcp"):
            if self.edge == "managed":
                challenge = (
                    'Bearer resource_metadata="'
                    + ORIGIN
                    + '/.well-known/cloudflare-access-protected-resource/"'
                )
                status = 401
            elif self.edge == "external":
                challenge = 'Bearer resource_metadata="https://evil.example/metadata"'
                status = 401
            elif self.edge == "jwt":
                challenge = (
                    'Bearer resource_metadata="'
                    + ORIGIN
                    + "/.well-known/oauth-protected-resource/v1/devices/"
                    + DEVICE
                    + '/mcp"'
                )
                status = 401
            else:
                challenge = ""
                status = 403
            raise HTTPError(
                request.full_url,
                status,
                "unauthorized",
                {"WWW-Authenticate": challenge} if challenge else {},
                None,
            )
        raise AssertionError("Unexpected probe URL")


def test_access_preflight_requires_real_edge_managed_oauth_challenge():
    opener = Opener()
    report = check(ORIGIN, DEVICE, opener, auth_mode="cloudflare-access")
    assert report["health"] == "ok"
    assert report["oauth_metadata"] == "cloudflare_access_metadata"
    assert report["unauthorized_access"] == "blocked"
    assert report["windows_device"] == "not_tested"
    assert report["chatgpt_oauth"] == "not_tested"
    assert len(opener.urls) == 3


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

def test_access_preflight_refuses_off_origin_metadata_without_fetch():
    opener = Opener(edge="external")
    with pytest.raises(ValueError, match="Untrusted Cloudflare"):
        check(ORIGIN, DEVICE, opener, auth_mode="cloudflare-access")
    assert len(opener.urls) == 2


def test_access_preflight_does_not_accept_unprotected_metadata():
    opener = Opener(metadata_valid=False)
    with pytest.raises(ValueError, match="Invalid Cloudflare Access resource"):
        check(ORIGIN, DEVICE, opener, auth_mode="cloudflare-access")
    assert len(opener.urls) == 3
