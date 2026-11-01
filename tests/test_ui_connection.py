"""Read-only dashboard health indicators must never imply remote authorization."""

from udb.ui_connection import (
    chatgpt_indicator,
    tunnel_indicator,
    unknown_indicator,
    worker_indicator,
)


def test_worker_indicators_need_explicit_boolean_evidence():
    assert worker_indicator(True).tone == "ready"
    assert worker_indicator(False).tone == "paused"
    for value in (None, 1, "true", {}, []):
        assert worker_indicator(value).tone == "neutral"


def test_tunnel_health_cannot_pretend_client_connection():
    assert tunnel_indicator(
        {"ready": True, "tunnel_running": True}
    ).tone == "ready"
    inconsistent = tunnel_indicator(
        {"ready": True, "tunnel_running": False}
    )
    assert inconsistent.tone == "neutral"
    assert "không nhất quán" in inconsistent.detail
    assert tunnel_indicator({"connecting": True}).tone == "paused"
    assert tunnel_indicator({"tunnel_wanted": True}).tone == "paused"
    assert tunnel_indicator({}).tone == "neutral"


def test_chatgpt_requires_actual_invocation_not_local_status():
    state = chatgpt_indicator()
    assert state.text == "Chưa xác minh"
    assert state.tone == "neutral"
    assert "lời gọi công cụ" in state.detail
    assert unknown_indicator().tone == "neutral"
