"""Read-only presentation states for the UDB desktop connection summary.

These indicators intentionally NEVER infer ChatGPT tool discovery from local
worker or Cloud Agent process state. No permissions, credentials, or remote checks here.
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
        return HealthIndicator("Sẵn sàng", "ready", "Tác nhân UDB cục bộ đã phản hồi.")
    if worker_ready is False:
        return HealthIndicator(
            "Chưa sẵn sàng", "paused", "Tác nhân cục bộ chưa phản hồi."
        )
    return HealthIndicator(
        "Chưa xác định", "neutral", "Chưa có trạng thái tác nhân đáng tin cậy."
    )


def cloud_indicator(state: Mapping[str, object]) -> HealthIndicator:
    """Cloud Agent process status only, not ChatGPT OAuth verification."""
    running = state.get("cloud_running") is True
    wanted = state.get("cloud_wanted") is True
    if running:
        return HealthIndicator(
            "Đang chạy", "ready",
            "Tiến trình Cloud Agent đang chạy; cần gọi bridge_status tại ChatGPT để xác minh.",
        )
    if wanted:
        return HealthIndicator(
            "Đang thử lại", "paused",
            "Cloud Agent tạm dừng hoặc đang thử kết nối lại, không tự phát lại công cụ.",
        )
    return HealthIndicator(
        "Đang tắt", "neutral",
        "Cloud Agent chưa bật. Ghép nối thiết bị rồi bật để sử dụng ChatGPT.",
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
