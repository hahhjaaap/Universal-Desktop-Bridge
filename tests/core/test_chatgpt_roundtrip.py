"""Fast ChatGPT UIA roundtrip: exact matching, guarded input, no replay."""

from types import SimpleNamespace

import pytest

from udb.computer_desktop import Desktop
from udb.core import PolicyError


def fake_desktop(
    previous=False,
    incomplete=False,
    ambiguous=False,
    mismatch=False,
    paused=False,
    foreground=42,
):
    desktop = Desktop.__new__(Desktop)
    calls = []
    desktop.gui = SimpleNamespace(GetForegroundWindow=lambda: foreground)

    def check():
        calls.append(("control", "check"))
        if paused:
            raise PolicyError("desktop paused")

    def uia(hwnd, action, **kwargs):
        calls.append(("uia", action, kwargs))
        if action == "chatgpt_prepare":
            if previous or ambiguous:
                raise PolicyError("Existing conversation or ambiguous editor")
            return {"ok": True, "prepared": True}
        if action == "chatgpt_commit":
            if mismatch:
                raise PolicyError("Text mismatch; not submitted")
            return {"ok": True, "verified_text": True, "invoked": True}
        if action == "poll_chatgpt_reply":
            return {
                "completed": not incomplete,
                "reply": "" if incomplete else "Hello! 👋",
                "truncated": False,
                "elapsed_ms": 850,
                "first_reply_ms": 360,
            }
        raise AssertionError(action)

    def dispatch(action, **kwargs):
        calls.append(("desktop", action, kwargs))
        assert action == "type"
        assert kwargs["text"] == "Hello"
        return {"injected_characters": len(kwargs["text"])}

    desktop.uia = uia
    desktop._dispatch = dispatch
    desktop.control = SimpleNamespace(check=check)
    return desktop, calls


def test_two_uia_phases_with_one_guarded_input_and_one_reply_poll():
    desktop, calls = fake_desktop()
    result = desktop.chatgpt_roundtrip(42, "w", "Hello", 6000)
    assert result["reply_verified"] is True
    assert result["reply"] == "Hello! 👋"
    assert result["submit_requested"] is True
    assert result["verified_text"] is True
    assert result["replay_safe"] is False
    assert result["response_observed_in_ui"] is True
    assert result["timings_ms"]["reply_wait"] == 850
    assert result["timings_ms"]["reply_first_text"] == 360
    assert [op[:2] for op in calls] == [
        ("uia", "chatgpt_prepare"),
        ("desktop", "type"),
        ("control", "check"),
        ("uia", "chatgpt_commit"),
        ("uia", "poll_chatgpt_reply"),
    ]
    assert calls[-1][2]["wait_ms"] == 6000


def test_existing_chat_is_not_modified():
    desktop, calls = fake_desktop(previous=True)
    with pytest.raises(PolicyError, match="Existing conversation"):
        desktop.chatgpt_roundtrip(42, "w", "Hello", 6000)
    assert len(calls) == 1


def test_timeout_preserves_uncertain_submission_without_retry():
    desktop, calls = fake_desktop(incomplete=True)
    result = desktop.chatgpt_roundtrip(42, "w", "Hello", 6000)
    assert result["status"] == "reply_timeout"
    assert result["submit_requested"] is True
    assert result["reply_verified"] is False
    assert result["reply"] == ""
    assert [op[1] for op in calls if op[0] == "uia"].count("chatgpt_commit") == 1


@pytest.mark.parametrize(
    "message,wait_ms",
    [
        ("", 6000),
        ("Hello", 10001),
        ("Hello", 0),
        ("Hello", True),
    ],
)
def test_bad_request_rejected_before_ui(message, wait_ms):
    desktop, calls = fake_desktop()
    with pytest.raises(PolicyError):
        desktop.chatgpt_roundtrip(42, "w", message, wait_ms)
    assert calls == []


def test_ambiguous_editor_refused_without_typing():
    desktop, calls = fake_desktop(ambiguous=True)
    with pytest.raises(PolicyError, match="ambiguous editor"):
        desktop.chatgpt_roundtrip(42, "w", "Hello", 6000)
    assert all(op[0] != "desktop" for op in calls)


def test_mismatch_prevents_submit_and_reply_poll():
    desktop, calls = fake_desktop(mismatch=True)
    with pytest.raises(PolicyError, match="Text mismatch"):
        desktop.chatgpt_roundtrip(42, "w", "Hello", 6000)
    assert "poll_chatgpt_reply" not in [op[1] for op in calls if op[0] == "uia"]


def test_paused_after_typing_prevents_submission():
    desktop, calls = fake_desktop(paused=True)
    with pytest.raises(PolicyError, match="desktop paused"):
        desktop.chatgpt_roundtrip(42, "w", "Hello", 6000)
    assert "chatgpt_commit" not in [op[1] for op in calls if op[0] == "uia"]


def test_foreground_changed_after_typing_prevents_submission():
    desktop, calls = fake_desktop(foreground=77)
    with pytest.raises(PolicyError, match="Foreground changed"):
        desktop.chatgpt_roundtrip(42, "w", "Hello", 6000)
    assert "chatgpt_commit" not in [op[1] for op in calls if op[0] == "uia"]


def test_dispatch_routes_new_action():
    desktop = Desktop.__new__(Desktop)
    desktop.resolve = lambda window_id, focus=True: 42
    desktop.chatgpt_roundtrip = lambda *args: args
    assert desktop._dispatch(
        "chatgpt_roundtrip", window_id="observed", text="Hello", wait_ms=6000
    ) == (42, "observed", "Hello", 6000)


def test_roundtrip_refused_in_batch():
    desktop = Desktop.__new__(Desktop)
    with pytest.raises(PolicyError, match="Invalid/nested batch"):
        desktop.batch(
            "observed",
            [{"action": "chatgpt_roundtrip", "text": "Hello"}],
        )
