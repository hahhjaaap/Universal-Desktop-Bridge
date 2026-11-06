"""No-credential paired Worker versus staging health comparison regression."""

from __future__ import annotations

import io
import json

import pytest

from tools.compare_cloudflare_worker_readiness import compare, main

STAGING = "https://udb-private-relay-staging.example.workers.dev"
PAIRED = "https://udb-private-relay.example.workers.dev"
DEVICE = "a" * 32


class HealthResponse(io.BytesIO):
    status = 200

    def __init__(self, *, read: bool, access: bool = True):
        super().__init__(b'{"status":"ok","kind":"private-relay-prototype"}')
        self.headers = {
            "X-UDB-Access-OAuth-Capable": "1" if access else "0",
            "X-UDB-Project-Read-Capable": "1" if read else "0",
        }

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class PublicOnly:
    def __init__(self):
        self.urls = []

    def open(self, request, timeout):
        assert timeout == 8
        assert request.get_method() == "GET"
        assert request.get_header("Authorization") is None
        assert request.get_header("Cookie") is None
        assert request.get_header("User-agent") is not None
        assert request.full_url.endswith("/health")
        self.urls.append(request.full_url)
        if request.full_url == STAGING + "/health":
            return HealthResponse(read=True)
        if request.full_url == PAIRED + "/health":
            return HealthResponse(read=False)
        pytest.fail("Unexpected destination")


def pairing(home, relay=PAIRED):
    home.mkdir(parents=True, exist_ok=True)
    (home / "cloud-pairing.json").write_text(
        json.dumps({"relay": relay, "device_id": DEVICE}), encoding="utf-8"
    )


def test_different_worker_is_reported_without_any_secret_or_identity(tmp_path):
    pairing(tmp_path)
    (tmp_path / "cloud-device-token").write_text("DO-NOT-READ", encoding="utf-8")
    opener = PublicOnly()
    result = compare(tmp_path, STAGING, opener)
    assert result["result"] == "public_health_compared"
    assert result["pairing_matches_staging"] is False
    assert result["staging_worker"]["project_read"] == "advertised"
    assert result["paired_worker"]["project_read"] == "not_advertised"
    assert result["next_stage"] == "create_separate_staging_pairing"
    assert result["authenticated_read"] == "not_tested"
    assert opener.urls == [STAGING + "/health", PAIRED + "/health"]
    serialized = json.dumps(result)
    for forbidden in (DEVICE, "DO-NOT-READ", STAGING, PAIRED, "example.workers.dev"):
        assert forbidden not in serialized


def test_same_staging_worker_only_makes_one_public_request(tmp_path):
    pairing(tmp_path, STAGING)
    opener = PublicOnly()
    result = compare(tmp_path, STAGING + "/", opener)
    assert result["pairing_matches_staging"] is True
    assert result["next_stage"] == "verify_authenticated_staging_read"
    assert result["staging_worker"] == result["paired_worker"]
    assert opener.urls == [STAGING + "/health"]


@pytest.mark.parametrize(
    "invalid",
    [
        "https://udb-private-relay.example.workers.dev",
        "http://udb-staging.example.workers.dev",
        "https://evil.example",
        "https://user:pass@udb-staging.example.workers.dev",
        "https://udb-staging.example.workers.dev/health",
        "https://udb-staging.example.workers.dev?q=1",
        "https://udb-staging.example.workers.dev#fragment",
        "https://udb-staging.example.workers.dev:8443",
        "https://udb-staging.example.workers.dev@evil.example",
    ],
)
def test_non_staging_or_unsafe_origin_is_rejected_before_network(tmp_path, invalid):
    pairing(tmp_path)
    opener = PublicOnly()
    with pytest.raises(ValueError, match="invalid_staging_relay"):
        compare(tmp_path, invalid, opener)
    assert opener.urls == []


def test_bad_or_missing_pairing_causes_no_network_requests(tmp_path):
    opener = PublicOnly()
    assert compare(tmp_path, STAGING, opener)["reason"] == "pairing_missing_or_invalid"
    pairing(tmp_path, "https://evil.example")
    assert compare(tmp_path, STAGING, opener)["reason"] == "pairing_missing_or_invalid"
    assert opener.urls == []


def test_linked_pairing_refused_without_probe(tmp_path):
    pairing(tmp_path)
    (tmp_path / "cloud-pairing.json").rename(tmp_path / "other.json")
    try:
        (tmp_path / "cloud-pairing.json").symlink_to(tmp_path / "other.json")
    except OSError:
        pytest.skip("Symlink creation unavailable")
    opener = PublicOnly()
    assert compare(tmp_path, STAGING, opener)["reason"] == "pairing_missing_or_invalid"
    assert opener.urls == []


def test_cli_redacts_invalid_origin_and_reports_no_credentials(tmp_path, capsys):
    pairing(tmp_path)
    assert (
        main(["--staging-relay", "https://invalid.example", "--home", str(tmp_path)])
        == 1
    )
    output = capsys.readouterr().out
    assert json.loads(output) == {
        "result": "failed",
        "reason": "invalid_staging_relay",
    }
    assert DEVICE not in output and "invalid.example" not in output
