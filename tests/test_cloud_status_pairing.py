"""The local Tunnel is independent from the paired Cloudflare agent.

Status must not tell a paired Cloudflare user to re-run setup solely because
the separate headless Manager intentionally runs with --no-connect.
"""

import json
from pathlib import Path

import pytest

from udb import owner_command


@pytest.mark.parametrize("valid_pairing", [True, False])
def test_offline_headless_status_distinguishes_cloud_pairing(
    tmp_path, monkeypatch, valid_pairing
):
    monkeypatch.setattr(
        owner_command,
        "headless_state",
        lambda _: {"connection_mode": "offline"},
    )
    pairing = tmp_path / "cloud-pairing.json"
    pairing.write_text(
        json.dumps(
            {
                "relay": "https://udb-relay-staging.example.workers.dev",
                "device_id": "a" * 32,
            }
        )
        if valid_pairing
        else '{"relay":"http://invalid","device_id":"x"}',
        encoding="utf-8",
    )
    report = owner_command.inspect(
        tmp_path,
        Path("unused"),
        running=lambda *_: True,
        ready=lambda *_: False,
    )
    assert report["local_tunnel_ready"] is False
    assert report["chatgpt_connection_verified"] is False
    assert report["cloudflare_pairing_configured"] is valid_pairing
    if valid_pairing:
        assert "doctor --cloud" in report["next_action"]
        assert "separate" in report["next_action"].lower()
        assert "udb setup" not in report["next_action"]
    else:
        assert "udb setup" in report["next_action"]
