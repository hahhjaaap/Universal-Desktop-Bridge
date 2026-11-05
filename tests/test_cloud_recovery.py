"""Cloud doctor should guide users without revealing private pairing data."""

import json

import pytest

from udb import cloud_preflight

RELAY = "https://fixture.workers.dev"
DEVICE = "a" * 32


@pytest.mark.parametrize(
    ("reason", "stage", "phrase"),
    [
        ("pairing_missing", "pairing", "Pair the device"),
        ("pairing_invalid", "pairing", "pairing"),
        ("project_read_not_advertised", "worker", "project-read-capable"),
        ("Access-aware Worker code has not been deployed", "worker", "Access"),
        ("oauth_challenge_missing_or_wrong_status", "access", "Managed OAuth"),
        ("access_metadata_untrusted", "access", "unexpected metadata URL"),
        ("access_metadata_invalid", "access", "metadata is incomplete"),
        ("preflight_failed", "network", "health"),
        ("passed_public_preflight", "live_check", "ChatGPT"),
    ],
)
def test_known_failure_has_specific_sanitized_next_action(reason, stage, phrase):
    message = cloud_preflight.recovery(reason)
    assert message["stage"] == stage
    assert phrase in message["next_action"]
    assert RELAY not in json.dumps(message) and DEVICE not in json.dumps(message)


def test_unknown_upstream_error_cannot_reflect_secrets():
    result = cloud_preflight.recovery("Bearer private-token " + RELAY)
    assert result == cloud_preflight.recovery("preflight_failed")
    assert "private-token" not in json.dumps(result)


def test_failed_access_preflight_names_the_access_layer(tmp_path, monkeypatch):
    tmp_path.joinpath("cloud-pairing.json").write_text(
        json.dumps({"relay": RELAY, "device_id": DEVICE}), encoding="utf-8"
    )

    def missing_access(*_a, **_kw):
        raise ValueError("oauth_challenge_missing_or_wrong_status")

    monkeypatch.setattr(cloud_preflight, "check", missing_access)
    report = cloud_preflight.paired_report(tmp_path)
    assert report["reason"] == "oauth_challenge_missing_or_wrong_status"
    assert report["stage"] == "access"
    assert "Managed OAuth" in report["next_action"]
    assert report["authenticated_project_read"] == "not_tested"
    assert RELAY not in json.dumps(report)
    assert DEVICE not in json.dumps(report)


def test_public_success_still_requires_actual_authenticated_read(tmp_path, monkeypatch):
    tmp_path.joinpath("cloud-pairing.json").write_text(
        json.dumps({"relay": RELAY, "device_id": DEVICE}), encoding="utf-8"
    )
    monkeypatch.setattr(
        cloud_preflight,
        "check",
        lambda *_a, **_kw: {
            "health": "ok",
            "unauthorized_access": "blocked",
            "oauth_metadata": "cloudflare_access_metadata",
            "windows_device": "not_tested",
            "chatgpt_oauth": "not_tested",
        },
    )
    report = cloud_preflight.paired_report(tmp_path)
    assert report["result"] == "passed_public_preflight"
    assert report["stage"] == "live_check"
    assert "ChatGPT" in report["next_action"]
    assert report["authenticated_project_read"] == "not_tested"


def test_missing_pairing_guides_locally_without_creating_state(tmp_path):
    report = cloud_preflight.paired_report(tmp_path / "missing")
    assert report["reason"] == "pairing_missing"
    assert report["stage"] == "pairing"
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize(
    ("upstream", "expected"),
    [
        ("Untrusted Cloudflare resource metadata URL", "access_metadata_untrusted"),
        ("Invalid Cloudflare Access metadata type", "access_metadata_invalid"),
        ("Missing Cloudflare Access team domain", "access_metadata_invalid"),
    ],
)
def test_access_metadata_errors_are_classified_without_echoing_upstream(
    upstream, expected, tmp_path, monkeypatch
):
    tmp_path.joinpath("cloud-pairing.json").write_text(
        json.dumps({"relay": RELAY, "device_id": DEVICE}), encoding="utf-8"
    )

    def rejected(*_a, **_kw):
        raise ValueError(upstream)

    monkeypatch.setattr(cloud_preflight, "check", rejected)
    report = cloud_preflight.paired_report(tmp_path)
    assert report["reason"] == expected
    assert report["stage"] == "access"
    assert report["authenticated_project_read"] == "not_tested"
    assert RELAY not in json.dumps(report) and DEVICE not in json.dumps(report)


def test_access_failure_cannot_reflect_arbitrary_error_text(tmp_path, monkeypatch):
    tmp_path.joinpath("cloud-pairing.json").write_text(
        json.dumps({"relay": RELAY, "device_id": DEVICE}), encoding="utf-8"
    )

    def rejected(*_a, **_kw):
        raise ValueError("private-query-token at " + RELAY)

    monkeypatch.setattr(cloud_preflight, "check", rejected)
    report = cloud_preflight.paired_report(tmp_path)
    assert report["reason"] == "preflight_failed"
    assert report["stage"] == "network"
    assert "private-query-token" not in json.dumps(report)
