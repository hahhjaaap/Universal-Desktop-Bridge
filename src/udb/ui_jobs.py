"""Pure bounded job table filtering for the local Qt manager.

Search only task metadata, not logs, scripts or document bodies.
"""

from __future__ import annotations

import json

STATUS_GROUPS = ("Tất cả", "Đang chạy", "Cần chú ý", "Đã xong")


def job_group(status: str) -> str:
    if status in ("running", "stopping", "queued", "pending"):
        return "Đang chạy"
    if status in ("failed", "timeout", "output_limit", "reviewing"):
        return "Cần chú ý"
    if status in ("completed", "stopped"):
        return "Đã xong"
    return "Cần chú ý"  # Unknown state is never silently marked successful.


def job_metadata(row: dict) -> dict:
    try:
        info = json.loads(row.get("info") or "{}")
    except (TypeError, ValueError):
        info = {}
    return info if isinstance(info, dict) else {}


def visible_jobs(rows: list[dict], query: str, group: str) -> list[dict]:
    query = query.strip().casefold()[:128]
    group = group if group in STATUS_GROUPS else "Tất cả"
    visible = []
    for row in rows:
        status = str(row.get("status") or "")
        if group != "Tất cả" and job_group(status) != group:
            continue
        meta = job_metadata(row)
        haystack = " ".join(
            str(value or "")[:160]
            for value in (
                meta.get("project"),
                meta.get("language"),
                meta.get("kind"),
                status,
                row.get("id"),
            )
        ).casefold()
        if query and query not in haystack:
            continue
        visible.append(row)
    return visible
