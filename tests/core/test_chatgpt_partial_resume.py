"""ChatGPT fast-first-text and safe read-only reply resumption."""

from types import SimpleNamespace

import pytest

from udb.computer_desktop import Desktop
from udb.core import PolicyError


def make_desktop(*, completed=False, partial=True):
    desktop = Desktop.__new__(Desktop)
    calls = []
    desktop.gui = SimpleNamespace(GetForegroundWindow=lambda: 42)

    def uia(hwnd, action, **kwargs):
        calls.append((action, kwargs))
        if action == "chatgpt_prepare":
            return {"ok": True, "prepared": True}
        if action == "chatgpt_commit":
            return {"invoked": True, "verified_text": True}
        if action == "poll_chatgpt_reply":
            return {
                "completed": completed,
                "partial": partial,
                "reply": "Hello! 👋" if partial or completed else "",
                "truncated": False,
                "elapsed_ms": 2500,
                "first_reply_ms": 1800,
            }
        raise AssertionError(action)

    desktop.uia = uia
    desktop._dispatch = lambda action, **kwargs: {"injected_characters": 5}
    return desktop, calls


def test_fast_first_text_returns_bounded_partial_not_complete():
    desktop, calls = make_desktop()
    result = desktop.chatgpt_roundtrip(42, "w", "Hello", 6000, True)
    assert result["reply"] == "Hello! 👋"
    assert result["status"] == "partial_reply"
    assert result["reply_partial"] is True
    assert result["reply_verified"] is False
    assert result["submit_requested"] is True
    assert result["replay_safe"] is False
    assert calls[-1][1]["condition"] == "first_text"
    assert calls[-1][1]["wait_ms"] == 6000


def test_default_timeout_retains_visible_partial():
    desktop, calls = make_desktop()
    result = desktop.chatgpt_roundtrip(42, "w", "Hello", 6000)
    assert result["status"] == "reply_timeout"
    assert result["reply"] == "Hello! 👋"
    assert result["reply_partial"] is True
    assert result["reply_verified"] is False
    assert calls[-1][1]["condition"] == "exists"


def test_completed_response_is_never_marked_partial():
    desktop, calls = make_desktop(completed=True, partial=False)
    result = desktop.chatgpt_roundtrip(42, "w", "Hello", 6000, True)
    assert result["status"] == "complete"
    assert result["reply_verified"] is True
    assert result["reply_partial"] is False
    assert calls[-1][0] == "poll_chatgpt_reply"


def test_resume_is_read_only_and_never_sends():
    desktop, calls = make_desktop(completed=True, partial=False)
    result = desktop.chatgpt_read_reply(42, "Hello", 6000)
    assert result["read_only"] is True
    assert result["replay_safe"] is True
    assert result["status"] == "complete"
    assert result["reply"] == "Hello! 👋"
    assert [action for action, _ in calls] == ["poll_chatgpt_reply"]


def test_fast_resume_reads_partial_only():
    desktop, calls = make_desktop()
    result = desktop.chatgpt_read_reply(42, "Hello", 6000, True)
    assert result["status"] == "partial_reply"
    assert result["reply_partial"] is True
    assert result["reply_verified"] is False
    assert calls[0][1]["condition"] == "first_text"


@pytest.mark.parametrize("text,wait,fast", [
    ("", 6000, False),
    ("Hello", 0, False),
    ("Hello", 6000, 1),
    ("Hello", 10001, False),
])
def test_read_reply_invalid_request_rejected(text, wait, fast):
    desktop, calls = make_desktop()
    with pytest.raises(PolicyError):
        desktop.chatgpt_read_reply(42, text, wait, fast)
    assert calls == []


def test_read_reply_dispatch_never_focuses_target():
    desktop = Desktop.__new__(Desktop)
    seen = []

    def resolve(wid, focus=True):
        seen.append((wid, focus))
        return 42

    desktop.resolve = resolve
    desktop.chatgpt_read_reply = lambda *args: args
    result = desktop._dispatch(
        "chatgpt_read_reply",
        window_id="observed",
        text="Hello",
        wait_ms=6000,
    )
    assert result == (42, "Hello", 6000, False)
    assert seen == [("observed", False)]


def test_read_reply_foreground_auto_discovery():
    desktop = Desktop.__new__(Desktop)
    desktop.listing = lambda: {
        "windows": [
            {
                "title": "ChatGPT - Google Chrome",
                "pid": 2840,
                "window_id": "fresh",
                "foreground": True,
                "minimized": False,
            }
        ]
    }
    desktop._chrome_image_path = lambda pid: "C:\\Chrome\\chrome.exe"
    desktop.resolve = lambda wid, focus=True: 42
    desktop.chatgpt_read_reply = lambda *args: args
    assert desktop._dispatch(
        "chatgpt_read_reply", text="Hello", wait_ms=6000
    ) == (42, "Hello", 6000, False)


def test_chatgpt_poll_preserves_partial_text_on_timeout():
    from pathlib import Path

    script = (
        Path(__file__).resolve().parents[2] / "src" / "udb" / "computer_uia.ps1"
    ).read_text(encoding="utf-8-sig")
    assert "$bestResponse=$response" in script
    assert "reply=$bestResponse" in script
    assert "partial=(!$complete" in script
    assert "Ambiguous ChatGPT conversation" in script
