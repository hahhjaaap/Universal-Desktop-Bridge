"""Read-only presentation states for the UDB desktop connection summary.

These indicators intentionally NEVER infer ChatGPT tool discovery from local
worker or tunnel health. No permissions, credentials, or remote checks here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class HealthIndicator:
    text: str
    tone: str
    detail: str


def worker_indicator(worker_ready: object) -> HealthIndicator:
    """A local worker heartbeat, not confirmation of AI authorization."""
    if worker_ready is True:
        return HealthIndicator(
            "Sẵn sàng", "ready", "Tác nhân UDB cục bộ đã phản hồi."
        )
    if worker_ready is False:
        return HealthIndicator(
            "Chưa sẵn sàng", "paused", "Tác nhân cục bộ chưa phản hồi."
        )
    return HealthIndicator(
        "Chưa xác định", "neutral", "Chưa có trạng thái tác nhân đáng tin cậy."
    )


def tunnel_indicator(state: Mapping[str, object]) -> HealthIndicator:
    """Transport readiness only; never claims a working ChatGPT connection."""
    ready = state.get("ready") is True
    running = state.get("tunnel_running") is True
    connecting = state.get("connecting") is True
    wanted = state.get("tunnel_wanted") is True
    if ready and running:
        return HealthIndicator(
            "Sẵn sàng", "ready", "Tunnel trên máy này đã phản hồi."
        )
    if ready and not running:
        return HealthIndicator(
            "Chưa xác định",
            "neutral",
            "Tín hiệu tunnel không nhất quán; chưa xác nhận kết nối.",
        )
    if running or connecting:
        return HealthIndicator(
            "Đang kết nối", "paused", "Đang thiết lập hoặc kiểm tra tunnel."
        )
    if wanted:
        return HealthIndicator(
            "Chờ kết nối", "paused", "Tunnel chưa sẵn sàng; có thể đang thử lại."
        )
    return HealthIndicator(
        "Chưa kết nối", "neutral", "Tunnel chưa được yêu cầu kết nối."
    )


def chatgpt_indicator() -> HealthIndicator:
    """The GUI has no authoritative MCP invocation proof."""
    return HealthIndicator(
        "Chưa xác minh",
        "neutral",
        "Chỉ một lời gọi công cụ UDB thực tế từ ChatGPT mới xác minh được.",
    )


def unknown_indicator() -> HealthIndicator:
    return HealthIndicator(
        "Chưa xác định",
        "neutral",
        "Không đọc được trạng thái mới; không sử dụng kết quả cũ để báo sẵn sàng.",
    )
