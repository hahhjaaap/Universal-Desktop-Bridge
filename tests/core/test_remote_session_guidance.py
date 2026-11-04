"""Only a real Cloudflare MCP call verifies the remote ChatGPT session."""

import pytest

from udb.owner_command import remote_session_action


@pytest.mark.parametrize(
    "running,expected",
    [
        (False, "Cloud Agent is not running"),
        (True, "Cloud Agent process is running"),
    ],
)
def test_remote_status_guidance_never_promises_chatgpt_access(running, expected):
    message = remote_session_action({"cloud_agent_running": running}, offline=False)
    assert expected in message
    if running:
        assert "unverified" in message


def test_offline_diagnostics_does_not_claim_remote_connection():
    message = remote_session_action({"cloud_agent_running": False}, offline=True)
    assert "Offline diagnostics" in message


def test_missing_agent_field_fails_closed_with_diagnostics():
    assert "Cloud Agent is not running" in remote_session_action({}, offline=False)
