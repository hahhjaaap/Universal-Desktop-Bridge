"""Public, no-credential Worker preflight must not claim scoped reads too early."""

import io
import json
import sys
from urllib.error import HTTPError

import pytest

from tools import check_cloudflare_deployment as probe

RELAY = "https://example.workers.dev"
DEVICE = "a" * 32


class Response(io.BytesIO):
    status = 200

    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class Opener:
    def __init__(self, *, read_capable=False, access_challenge=False):
        self.read_capable = read_capable
        self.access_challenge = access_challenge
        self.urls = []

    def open(self, request, timeout):
        assert timeout == 8
        assert request.get_header("Authorization") is None
        self.urls.append(request.full_url)
        if request.full_url.endswith("/health"):
            headers = {"X-UDB-Access-OAuth-Capable": "1"}
            if self.read_capable:
                headers["X-UDB-Project-Read-Capable"] = "1"
            return Response(
                b'{"status":"ok","kind":"private-relay-prototype"}',
                headers,
            )
        if request.full_url.endswith("/mcp"):
            metadata = RELAY + (
                "/.well-known/cloudflare-access-protected-resource/"
                if self.access_challenge
                else "/.well-known/oauth-protected-resource/v1/devices/"
                + DEVICE
                + "/mcp"
            )
            raise HTTPError(
                request.full_url,
                401,
                "unauthorized",
                {"WWW-Authenticate": 'Bearer resource_metadata="' + metadata + '"'},
                None,
            )
        if request.full_url.endswith(
            "/.well-known/cloudflare-access-protected-resource/"
        ):
            return Response(
                json.dumps(
                    {
                        "protected": True,
                        "resource": RELAY,
                        "team_domain": "fixture.cloudflareaccess.com",
                        "authorization_servers": [
                            "https://fixture.cloudflareaccess.com"
                        ],
                    }
                ).encode(),
            )
        raise AssertionError("Unexpected probe request")


def test_read_capability_required_fails_before_any_access_rpc():
    transport = Opener(read_capable=False)
    with pytest.raises(ValueError, match="project_read_not_advertised"):
        probe.check(
            RELAY,
            DEVICE,
            transport,
            auth_mode="cloudflare-access",
            require_project_read=True,
        )
    assert transport.urls == [RELAY + "/health"]


def test_capability_only_without_oauth_knowledge_does_not_authenticate_user():
    transport = Opener(read_capable=True, access_challenge=True)
    report = probe.check(
        RELAY,
        DEVICE,
        transport,
        auth_mode="cloudflare-access",
        require_project_read=True,
    )
    assert report["project_read_capability"] == "deployed"
    assert report["unauthorized_access"] == "blocked"
    assert report["chatgpt_oauth"] == "not_tested"
    assert report["windows_device"] == "not_tested"
    assert len(transport.urls) == 3


def test_worker_challenge_must_come_from_managed_access_edge():
    transport = Opener(read_capable=True, access_challenge=False)
    with pytest.raises(ValueError, match="Untrusted Cloudflare resource metadata"):
        probe.check(
            RELAY,
            DEVICE,
            transport,
            auth_mode="cloudflare-access",
            require_project_read=True,
        )


def test_cli_failure_is_sanitized(monkeypatch, capsys):
    secret = "do-not-echo"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_cloudflare_deployment.py",
            "--relay",
            RELAY,
            "--device-id",
            DEVICE,
            "--auth-mode",
            "cloudflare-access",
            "--require-project-read",
        ],
    )
    monkeypatch.setattr(
        probe,
        "check",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("project_read_not_advertised")
        ),
    )
    assert probe.main() == 1
    output = capsys.readouterr().out
    assert json.loads(output) == {
        "result": "failed",
        "reason": "project_read_not_advertised",
    }
    assert DEVICE not in output and RELAY not in output and secret not in output
