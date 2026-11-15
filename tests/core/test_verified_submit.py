"""Owner-gated one-round-trip verified UI submission, without a real desktop."""

from types import SimpleNamespace

import pytest

from udb.computer_desktop import Desktop
from udb.core import PolicyError


def desktop(initial="Hỏi ChatGPT\n", after="Hello", foreground=42, paused=False):
    d = Desktop.__new__(Desktop)
    calls = []

    def uia(hwnd, action, **kwargs):
        calls.append(("uia", action, kwargs))
        if action == "read_text":
            n = sum(row[0:2] == ("uia", "read_text") for row in calls)
            return {
                "ok": True,
                "text": initial if n == 1 else after,
                "truncated": False,
            }
        if action == "invoke":
            return {"ok": True, "invoked": True}
        return {"ok": True}

    def dispatch(action, **kwargs):
        calls.append(("desktop", action, kwargs))
        assert action == "type"
        return {"injected_characters": len(kwargs["text"])}

    def check():
        calls.append(("control", "check", {}))
        if paused:
            raise PolicyError("desktop paused")

    d.uia = uia
    d._dispatch = dispatch
    d.gui = SimpleNamespace(GetForegroundWindow=lambda: foreground)
    d.control = SimpleNamespace(check=check)
    return d, calls


def submit(d, text="Hello"):
    return d.verified_submit(42, "observed-window", text, "Hỏi ChatGPT", "", "Gửi")


def test_exact_text_then_single_submit():
    d, calls = desktop()
    result = submit(d)
    assert result["verified_text"] is True
    assert result["submit_requested"] is True
    assert result["application_submission_verified"] is False
    assert result["replay_safe"] is False
    assert [row[0:2] for row in calls] == [
        ("uia", "read_text"),
        ("uia", "uia_focus"),
        ("desktop", "type"),
        ("uia", "read_text"),
        ("control", "check"),
        ("uia", "invoke"),
    ]
    assert calls[-1][2]["name"] == "Gửi"
    assert calls[-1][2]["control_type"] == "Button"


@pytest.mark.parametrize(
    "initial",
    ["An existing draft", "Hello", "Something else\n"],
)
def test_existing_draft_is_preserved(initial):
    d, calls = desktop(initial=initial)
    with pytest.raises(PolicyError, match="existing draft preserved"):
        submit(d)
    assert [x[0:2] for x in calls] == [("uia", "read_text")]


@pytest.mark.parametrize(
    "after",
    ["HelloHello", "Hell", "Hello\n", "Something else"],
)
def test_mismatched_text_refuses_submit(after):
    d, calls = desktop(after=after)
    with pytest.raises(PolicyError, match="nothing submitted"):
        submit(d)
    assert not any(x[0:2] == ("uia", "invoke") for x in calls)


def test_paused_before_submit_never_invokes():
    d, calls = desktop(paused=True)
    with pytest.raises(PolicyError, match="desktop paused"):
        submit(d)
    assert not any(x[0:2] == ("uia", "invoke") for x in calls)


def test_foreground_changed_before_submit_never_invokes():
    d, calls = desktop(foreground=77)
    with pytest.raises(PolicyError, match="Foreground changed"):
        submit(d)
    assert not any(x[0:2] == ("uia", "invoke") for x in calls)


@pytest.mark.parametrize(
    "text,name,button",
    [
        ("", "Hỏi ChatGPT", "Gửi"),
        ("Hello", "", "Gửi"),
        ("Hello", "Hỏi ChatGPT", ""),
        ("Hello", "Hỏi ChatGPT", "Gửi\nDelete all"),
    ],
)
def test_invalid_arguments_refused_before_ui_action(text, name, button):
    d, calls = desktop()
    with pytest.raises(PolicyError):
        d.verified_submit(42, "w", text, name, "", button)
    assert calls == []


def test_exact_action_routes_without_running_batch(monkeypatch):
    d = Desktop.__new__(Desktop)
    d.resolve = lambda window_id, focus=True: 42
    d.verified_submit = lambda *args: {"args": args}
    result = d._dispatch(
        "verified_submit",
        window_id="observed",
        text="Hello",
        name="Hỏi ChatGPT",
        submit_name="Gửi",
    )
    assert result["args"] == (42, "observed", "Hello", "Hỏi ChatGPT", "", "Gửi")


def test_verified_submit_is_not_allowed_in_batch():
    d = Desktop.__new__(Desktop)
    with pytest.raises(PolicyError, match="Invalid/nested batch step"):
        d.batch("observed", [{"action": "verified_submit", "text": "Hello"}])


def test_public_catalog_exposes_verified_submit_as_mutating():
    from udb.registry import catalog

    tools = {tool["name"]: tool for tool in catalog()["tools"]}
    desktop_tool = tools["computer_desktop"]
    props = desktop_tool["inputSchema"]["properties"]
    assert "verified_submit" in props["action"]["enum"]
    assert props["submit_name"]["type"] == "string"
    assert desktop_tool["annotations"]["readOnlyHint"] is False
