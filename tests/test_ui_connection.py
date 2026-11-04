"""Cloudflare Agent state is not equivalent to an authenticated ChatGPT call."""

from udb.ui_connection import (
    chatgpt_indicator,
    cloud_indicator,
    unknown_indicator,
    worker_indicator,
)


def test_local_worker_requires_explicit_boolean():
    assert worker_indicator(True).tone == "ready"
    assert worker_indicator(False).tone == "paused"
    for value in (None, 1, "true", {}, []):
        assert worker_indicator(value).tone == "neutral"


def test_cloud_agent_process_status_never_claims_verified_oauth():
    running = cloud_indicator({"cloud_running": True})
    assert running.tone == "ready"
    assert "bridge_status" in running.detail
    assert cloud_indicator({"cloud_running": False, "cloud_wanted": True}).tone == "paused"
    assert cloud_indicator({}).tone == "neutral"
    assert cloud_indicator({"cloud_running": 1}).tone == "neutral"


def test_chatgpt_requires_an_actual_authenticated_tool_invocation():
    result = chatgpt_indicator()
    assert result.text == "Chưa xác minh"
    assert result.tone == "neutral"
    assert "lời gọi công cụ" in result.detail
    assert unknown_indicator().tone == "neutral"
