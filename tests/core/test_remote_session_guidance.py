"""Remote-device troubleshooting stays honest about what local probes prove."""

from udb.owner_command import remote_session_action


def test_running_cloud_agent_does_not_claim_connected_chatgpt():
    action = remote_session_action({"cloud_agent_running": True}, paired=True)
    assert "unverified" in action
    assert "bridge_status" in action
    assert "Session terminated" in action
    assert "Do not replay" in action
    assert "Connected" in action


def test_unpaired_device_points_to_cloudflare_setup():
    action = remote_session_action({"local_tunnel_ready": True}, paired=False)
    assert "Cloudflare" in action
    assert "udb setup" in action
    assert "bridge_status" not in action


def test_missing_cloud_agent_field_points_to_cloudflare_diagnostics():
    action = remote_session_action({}, paired=True)
    assert "udb doctor --cloud" in action
    assert "udb start" in action
    assert "bridge_status" not in action
