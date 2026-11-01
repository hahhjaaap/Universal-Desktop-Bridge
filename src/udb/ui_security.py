"""Presentation-only status signals for the local UDB Security page.

No caller may use these indicators as an authorization decision. Every
indicator must be derived from current, already-read owner-local state.
"""

from __future__ import annotations

from .ui_connection import HealthIndicator


def approval_indicator(count: object) -> HealthIndicator:
    if type(count) is not int or count < 0:
        return HealthIndicator(
            "Chưa xác minh", "neutral", "Không đọc được yêu cầu phê duyệt cục bộ."
        )
    if count:
        return HealthIndicator(
            f"{count} yêu cầu",
            "paused",
            "Có yêu cầu chủ máy cần xem; không đồng nghĩa đã được cấp quyền.",
        )
    return HealthIndicator(
        "0 yêu cầu", "neutral", "Không có yêu cầu phê duyệt đang chờ tại lần kiểm tra."
    )


def input_pause_indicator(paused: object) -> HealthIndicator:
    if paused is True:
        return HealthIndicator(
            "Đang tạm dừng",
            "owner",
            "Đầu vào chuột/phím Windows đã tạm dừng; tác vụ nền có thể tiếp tục.",
        )
    if paused is False:
        return HealthIndicator(
            "Chưa tạm dừng",
            "neutral",
            "Đầu vào chuột/phím Windows chưa tạm dừng; không nói lên trạng thái các job.",
        )
    return HealthIndicator(
        "Chưa xác minh", "neutral", "Không đọc được khóa tạm dừng Windows."
    )


def source_autonomy_indicator(count: object) -> HealthIndicator:
    if type(count) is not int or count < 0:
        return HealthIndicator(
            "Chưa xác minh", "neutral", "Không đọc được quyền tự sửa mã nguồn."
        )
    if count:
        return HealthIndicator(
            f"{count} dự án",
            "paused",
            "Tự sửa mã nguồn đang bật trong phạm vi dự án đã cấp quyền, không phải quyền máy.",
        )
    return HealthIndicator(
        "Không bật",
        "neutral",
        "Không có dự án được xác nhận bật tự sửa mã nguồn trong lần kiểm tra.",
    )
