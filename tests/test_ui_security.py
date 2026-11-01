"""Security posture labels are not policy grants or proof of client identity."""

from udb.ui_security import (
    approval_indicator,
    input_pause_indicator,
    source_autonomy_indicator,
)


def test_pending_approvals_are_counts_not_authorization():
    assert approval_indicator(0).text == "0 yêu cầu"
    assert approval_indicator(0).tone == "neutral"
    assert approval_indicator(3).text == "3 yêu cầu"
    assert approval_indicator(3).tone == "paused"
    for untrusted in (True, False, None, "4", -1, 1.5):
        assert approval_indicator(untrusted).tone == "neutral"
        assert approval_indicator(untrusted).text == "Chưa xác minh"


def test_pause_is_host_input_only():
    assert input_pause_indicator(True).text == "Đang tạm dừng"
    assert input_pause_indicator(True).tone == "owner"
    assert "nền" in input_pause_indicator(True).detail
    assert input_pause_indicator(False).text == "Chưa tạm dừng"
    for untrusted in (None, 0, 1, "false"):
        assert input_pause_indicator(untrusted).text == "Chưa xác minh"


def test_source_autonomy_is_scoped_and_unknown_is_not_green():
    assert source_autonomy_indicator(0).text == "Không bật"
    assert source_autonomy_indicator(2).text == "2 dự án"
    assert source_autonomy_indicator(2).tone == "paused"
    assert "không phải quyền máy" in source_autonomy_indicator(2).detail
    for invalid in (True, False, None, "3", -2):
        assert source_autonomy_indicator(invalid).text == "Chưa xác minh"
        assert source_autonomy_indicator(invalid).tone == "neutral"
