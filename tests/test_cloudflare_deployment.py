"""Offline tests for read-only public Worker acceptance checks."""

import io
import json
from urllib.error import HTTPError

import pytest

from tools.check_cloudflare_deployment import check
from udb.cloud_agent import CLOUD_USER_AGENT


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class FakeOpener:
    def __init__(self):
        self.urls = []

    def open(self, request, timeout):
        assert timeout == 8
        assert request.get_header("User-agent") == CLOUD_USER_AGENT
        self.urls.append(request.full_url)
        url = request.full_url
        if url.endswith("/health"):
            return FakeResponse(b'{"status":"ok","kind":"private-relay-prototype"}')
        if "/.well-known/" in url:
            return FakeResponse(
                json.dumps(
                    {
                        "resource": "https://example.workers.dev/v1/devices/"
                        + "a" * 32
                        + "/mcp",
                        "authorization_servers": ["https://identity.example.org"],
                    }
                ).encode()
            )
        raise HTTPError(
            url,
            401,
            "unauthorized",
            {
                "WWW-Authenticate": 'Bearer resource_metadata="https://example.workers.dev"'
            },
            None,
        )


def test_cloudflare_probe_checks_only_public_metadata_and_unauthenticated_denial():
    opener = FakeOpener()
    report = check("https://example.workers.dev", "a" * 32, opener)
    assert report["health"] == "ok"
    assert report["project_read_capability"] == "not_advertised"
    assert report["oauth_metadata"] == "ok"
    assert report["unauthorized_access"] == "blocked"
    assert report["windows_device"] == "not_tested"
    assert report["chatgpt_oauth"] == "not_tested"
    assert len(opener.urls) == 3


def test_project_read_capability_does_not_claim_authenticated_device_access():
    class CurrentWorker(FakeOpener):
        def open(self, request, timeout):
            response = super().open(request, timeout)
            response.headers = {"X-UDB-Project-Read-Capable": "1"}
            return response

    report = check("https://example.workers.dev", "a" * 32, CurrentWorker())
    assert report["project_read_capability"] == "deployed"
    assert report["windows_device"] == report["chatgpt_oauth"] == "not_tested"


def test_cloudflare_probe_rejects_external_origin_before_network():
    opener = FakeOpener()
    with pytest.raises(ValueError):
        check("https://evil.example", "a" * 32, opener)
    assert not opener.urls
