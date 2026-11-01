"""Bounded, privacy-preserving diagnostics for disposable Windows browser smoke tests.

This module is a diagnostic observer only. It never captures browser
content, targets, URLs, credentials, file paths, process IDs or CDP payloads.
"""

from __future__ import annotations

import math

_MAX_EVENTS = 128


def browser_smoke_failure(browser: object, *, stage: str, elapsed_ms: object) -> dict:
    """Summarize a failed owned-browser smoke step without leaking content."""
    if stage not in {"initial_screenshot", "visible_handoff", "background_handoff"}:
        stage = "unknown"
    if type(elapsed_ms) not in (int, float) or not math.isfinite(elapsed_ms):
        elapsed_ms = 0
    elapsed_ms = min(120_000, max(0, round(elapsed_ms)))
    try:
        process = getattr(browser, "proc", None)
        process_alive = process.alive() is True if process is not None else None
    except (OSError, RuntimeError, AttributeError):
        process_alive = None
    try:
        tabs = getattr(browser, "tabs", None)
        owned_tab_count = min(100, max(0, len(tabs))) if isinstance(tabs, dict) else None
    except (OSError, RuntimeError, TypeError):
        owned_tab_count = None
    try:
        channel = getattr(browser, "_cdp", None)
        markers = channel.event_markers() if channel is not None else None
        recent_event_count = min(_MAX_EVENTS, len(markers)) if markers is not None else None
    except (OSError, RuntimeError, TypeError, AttributeError):
        recent_event_count = None
    return {
        "check": "owned_browser_smoke",
        "stage": stage,
        "elapsed_ms": elapsed_ms,
        "owned_process_alive": process_alive,
        "owned_tab_count": owned_tab_count,
        "cdp_event_marker_count": recent_event_count,
        "outcome": "unknown",
        "retry_performed": False,
    }
