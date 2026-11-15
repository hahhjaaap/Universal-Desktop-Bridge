"""Single UDB call ChatGPT roundtrip: strict empty-chat and no replay."""

from types import SimpleNamespace

import pytest

from udb.computer_desktop import Desktop
from udb.core import PolicyError


def fake_desktop(previous=False, incomplete=False):
    desktop = Desktop.__new__(Desktop)
    ops = []
    desktop.gui = SimpleNamespace(GetForegroundWindow=lambda: 42)

    def uia(hwnd, action, **kwargs):
        ops.append(("uia", action, kwargs))
        if action == "snapshot":
            rows = [
                {"control_type": "ControlType.Document", "name": "ChatGPT"},
                {
                    "control_type": "ControlType.Edit",
                    "name": "Hỏi ChatGPT",
                    "offscreen": False,
                },
            ]
            if previous:
                rows.append(
                    {
                        "control_type": "ControlType.Text",
                        "name": "ChatGPT đã nói:",
                    }
                )
            return {"elements": rows, "truncated": False}
        if action == "poll_chatgpt_reply":
            return {
                "completed": not incomplete,
                "reply": "" if incomplete else "Hello! 👋",
                "truncated": False,
                "elapsed_ms": 850,
            }
        raise AssertionError(action)

    def send(hwnd, window_id, text, name, automation_id, submit_name):
        ops.append(("verified_submit", text, submit_name))
        return {"submit_requested": True, "verified_text": True}

    desktop.uia = uia
    desktop.verified_submit = send
    return desktop, ops


def test_roundtrip_uses_one_local_poll_after_one_exact_submit():
    desktop, ops = fake_desktop()
    result = desktop.chatgpt_roundtrip(42, "w", "Hello", 6000)
    assert result["reply_verified"] is True
    assert result["reply"] == "Hello! 👋"
    assert result["replay_safe"] is False
    assert result["response_observed_in_ui"] is True
    assert result["timings_ms"]["reply_wait"] == 850
    assert [op[:2] for op in ops] == [
        ("uia", "snapshot"),
        ("verified_submit", "Hello"),
        ("uia", "poll_chatgpt_reply"),
    ]
    assert ops[-1][2]["wait_ms"] == 6000


def test_existing_chat_is_not_modified():
    desktop, ops = fake_desktop(previous=True)
    with pytest.raises(PolicyError, match="existing messages"):
        desktop.chatgpt_roundtrip(42, "w", "Hello", 6000)
    assert len(ops) == 1


def test_timeout_preserves_uncertain_submission_without_retry():
    desktop, ops = fake_desktop(incomplete=True)
    result = desktop.chatgpt_roundtrip(42, "w", "Hello", 6000)
    assert result["status"] == "reply_timeout"
    assert result["submit_requested"] is True
    assert result["reply_verified"] is False
    assert result["reply"] == ""
    assert [op[0] for op in ops].count("verified_submit") == 1


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
    desktop, ops = fake_desktop()
    with pytest.raises(PolicyError):
        desktop.chatgpt_roundtrip(42, "w", message, wait_ms)
    assert ops == []


def test_ambiguous_editor_refused_without_sending():
    desktop, ops = fake_desktop()
    original = desktop.uia

    def duplicate(hwnd, action, **kwargs):
        result = original(hwnd, action, **kwargs)
        if action == "snapshot":
            result["elements"].append(
                {
                    "control_type": "ControlType.Edit",
                    "name": "Hỏi ChatGPT",
                    "offscreen": False,
                }
            )
        return result

    desktop.uia = duplicate
    with pytest.raises(PolicyError, match="Expected an empty"):
        desktop.chatgpt_roundtrip(42, "w", "Hello", 6000)
    assert not any(op[0] == "verified_submit" for op in ops)


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
