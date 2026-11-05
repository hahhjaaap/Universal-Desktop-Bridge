"""Owner-requested public diagnostics never authenticate or modify owner state."""

import io
import json
from urllib.error import HTTPError, URLError

import pytest

from udb import cli, cloud_preflight, owner_command

ORIGIN = "https://example.workers.dev"
DEVICE = "a" * 32


class Response(io.BytesIO):
    status = 200

    def __init__(self, value, headers=None):
        super().__init__(json.dumps(value).encode())
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class PublicEndpoints:
    def __init__(self, *, project_read=True):
        self.requests = []
        self.project_read = project_read

    def open(self, request, timeout):
        assert timeout == 8
        assert request.get_header("Authorization") is None
        assert request.get_header("Cookie") is None
        self.requests.append(request)
        if request.full_url == ORIGIN + "/health":
            return Response(
                {"status": "ok", "kind": "private-relay-prototype"},
                {
                    "X-UDB-Access-OAuth-Capable": "1",
                    **(
                        {"X-UDB-Project-Read-Capable": "1"} if self.project_read else {}
                    ),
                },
            )
        if request.full_url.endswith("/mcp"):
            assert json.loads(request.data)["method"] == "tools/list"
            raise HTTPError(
                request.full_url,
                401,
                "denied",
                {
                    "WWW-Authenticate": 'Bearer resource_metadata="'
                    + ORIGIN
                    + '/.well-known/cloudflare-access-protected-resource/"'
                },
                None,
            )
        assert (
            request.full_url
            == ORIGIN + "/.well-known/cloudflare-access-protected-resource/"
        )
        return Response(
            {
                "protected": True,
                "resource": ORIGIN,
                "team_domain": "owner-check.cloudflareaccess.com",
                "authorization_servers": ["https://owner-check.cloudflareaccess.com"],
            }
        )


def pair(home):
    home.mkdir(exist_ok=True)
    (home / "cloud-pairing.json").write_text(
        json.dumps(
            {
                "relay": ORIGIN,
                "device_id": DEVICE,
            }
        ),
        encoding="utf-8",
    )


def files(home):
    return {
        str(p.relative_to(home)): p.read_bytes() for p in home.rglob("*") if p.is_file()
    }


def report():
    return dict(
        chatgpt_connection_verified=False,
        manager_running=False,
        local_tunnel_ready=False,
        background="disabled",
        manager_mode="stopped",
        next_action="Run udb.",
    )


def test_paired_preflight_never_reads_secrets_or_grants_and_keeps_live_proof_unverified(
    tmp_path,
    monkeypatch,
):
    pair(tmp_path)
    for name in (
        "cloud-device-token",
        "cloud-device-token.dpapi",
        "computer-access.dpapi",
    ):
        (tmp_path / name).write_bytes(b"owner-sentinel")
    from udb import cloud_secrets

    monkeypatch.setattr(
        cloud_secrets, "load_device_token", lambda *_: pytest.fail("secret loaded")
    )
    original_open = type(tmp_path).open

    def open_public(path, *args, **kwargs):
        if path.name in {
            "cloud-device-token",
            "cloud-device-token.dpapi",
            "computer-access.dpapi",
        }:
            pytest.fail("secret or grant read")
        return original_open(path, *args, **kwargs)

    before = files(tmp_path)
    opener = PublicEndpoints()
    with monkeypatch.context() as patch:
        patch.setattr(type(tmp_path), "open", open_public)
        result = cloud_preflight.paired_report(tmp_path, opener=opener)
    assert files(tmp_path) == before
    assert result["result"] == "passed_public_preflight"
    assert result["windows_device"] == result["chatgpt_oauth"] == "not_tested"
    assert result["authenticated_project_read"] == "not_tested"
    assert len(opener.requests) == 3
    assert ORIGIN not in json.dumps(result) and DEVICE not in json.dumps(result)


@pytest.mark.parametrize(
    "contents",
    [
        "{",
        "[]",
        "{}",
        " " * 2049,
        '{"relay":"https://evil.example","device_id":"' + DEVICE + '"}',
        '{"relay":[],"device_id":{}}',
    ],
)
def test_invalid_pairing_refuses_network_without_echoing_contents(tmp_path, contents):
    (tmp_path / "cloud-pairing.json").write_text(contents, encoding="utf-8")
    opener = PublicEndpoints()
    result = cloud_preflight.paired_report(tmp_path, opener=opener)
    assert result["reason"] == "pairing_invalid" and not opener.requests
    assert "evil.example" not in json.dumps(result)


def test_missing_pairing_is_read_only_and_does_not_try_network(tmp_path):
    home = tmp_path / "absent"
    opener = PublicEndpoints()
    result = cloud_preflight.paired_report(home, opener=opener)
    assert result["reason"] == "pairing_missing" and not opener.requests
    assert not home.exists()


def test_linked_pairing_refuses_network(tmp_path):
    pair(tmp_path)
    (tmp_path / "cloud-pairing.json").rename(tmp_path / "other.json")
    try:
        (tmp_path / "cloud-pairing.json").symlink_to(tmp_path / "other.json")
    except OSError:
        pytest.skip("Symlink creation unavailable")
    opener = PublicEndpoints()
    assert (
        cloud_preflight.paired_report(tmp_path, opener=opener)["reason"]
        == "pairing_invalid"
    )
    assert not opener.requests


def test_obsolete_worker_is_not_a_pass(tmp_path):
    pair(tmp_path)
    opener = PublicEndpoints(project_read=False)
    result = cloud_preflight.paired_report(tmp_path, opener=opener)
    assert result["reason"] == "project_read_not_advertised"
    assert len(opener.requests) == 1


def test_network_failure_is_redacted_and_not_retried(tmp_path):
    pair(tmp_path)

    class Failure:
        calls = 0

        def open(self, *_args, **_kwargs):
            self.calls += 1
            raise URLError("SECRET-UPSTREAM-TOKEN " + ORIGIN + "/" + DEVICE)

    opener = Failure()
    result = cloud_preflight.paired_report(tmp_path, opener=opener)
    assert result["reason"] == "preflight_failed" and opener.calls == 1
    assert "SECRET" not in json.dumps(result) and DEVICE not in json.dumps(result)


def test_default_doctor_does_not_run_public_preflight(tmp_path, monkeypatch):
    pair(tmp_path)
    monkeypatch.setattr(
        cloud_preflight,
        "paired_report",
        lambda *_a, **_k: pytest.fail("network opt-in absent"),
    )
    monkeypatch.setattr(owner_command, "inspect", lambda *_: report())
    before = files(tmp_path)
    assert owner_command.main(["doctor", "--home", str(tmp_path), "--json"]) == 2
    assert files(tmp_path) == before


def test_doctor_cli_routes_opt_in_and_exposes_unverified_live_proof(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(owner_command, "inspect", lambda *_: report())
    pair(tmp_path)
    opener = PublicEndpoints()
    original = cloud_preflight.paired_report
    monkeypatch.setattr(
        cloud_preflight,
        "paired_report",
        lambda home, **options: original(home, opener=opener, **options),
    )
    before = files(tmp_path)
    assert cli.main(["doctor", "--home", str(tmp_path), "--cloud", "--json"]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["cloud_preflight"]["result"] == "passed_public_preflight"
    assert result["chatgpt_connection_verified"] is False
    checks = {c["check"]: c for c in result["checks"]}
    assert checks["cloud_public_preflight"]["ok"] is True
    assert checks["cloud_authenticated_read"]["ok"] is None
    assert files(tmp_path) == before


@pytest.mark.parametrize(
    "args", [["status", "--cloud"], ["doctor", "--cloud-auth-mode", "jwt"]]
)
def test_owner_flags_cannot_accidentally_probe_other_actions(
    tmp_path, monkeypatch, args
):
    monkeypatch.setattr(
        owner_command,
        "executable",
        lambda *_: pytest.fail("invalid options reached lifecycle"),
    )
    assert owner_command.main([*args, "--home", str(tmp_path), "--json"]) == 1


def test_cli_forwards_explicit_jwt_mode_without_starting_setup(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(owner_command, "main", lambda argv: calls.append(argv) or 0)
    assert (
        cli.main(
            ["doctor", "--home", str(tmp_path), "--cloud", "--cloud-auth-mode", "jwt"]
        )
        == 0
    )
    assert calls[0][-3:] == ["--cloud", "--cloud-auth-mode", "jwt"]
