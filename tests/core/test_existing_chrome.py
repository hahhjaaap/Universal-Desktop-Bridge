"""Owner-granted visible Chrome tab integration (not CDP or profile takeover)."""

from types import SimpleNamespace

import pytest

from udb.computer_desktop import Desktop
from udb.core import PolicyError

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


@pytest.fixture(autouse=True)
def no_live_uia_in_unit_tests(monkeypatch):
    monkeypatch.setattr("udb.chrome_tab_identity.observe_tabs", lambda hwnd: [])
    monkeypatch.setattr(
        "udb.chrome_tab_identity.register_new_tab",
        lambda hwnd, pid, previous: False,
    )


def desktop(windows=None, foreground=101):
    d = Desktop.__new__(Desktop)
    d.interactive = lambda: None
    d.gui = SimpleNamespace(GetForegroundWindow=lambda: foreground)
    d._chrome_windows = lambda: [(101, 9876, CHROME)] if windows is None else windows
    return d


def test_open_tab_reuses_existing_chrome_without_shell_or_user_input(monkeypatch):
    d = desktop()
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("udb.computer_desktop.subprocess.run", run)
    result = d._dispatch("open_chrome_tab", text="https://example.org/test")
    assert result["requested"] is True
    assert result["existing_window_reused_observed"] is True
    assert result["chrome_pid"] == 9876
    assert result["dom_attached"] is False
    assert result["user_input_injected"] is False
    assert calls[0][0] == [CHROME, "--new-tab", "https://example.org/test"]
    assert calls[0][1]["shell"] is False
    assert "--new-window" not in calls[0][0]
    assert "--user-data-dir" not in calls[0][0]


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/secret.txt",
        "http://localhost:9222/json",
        "http://127.0.0.1:9222",
        "https://user:password@example.org/",
        "javascript:alert(1)",
        "https://example.org/\n--new-window",
    ],
)
def test_open_tab_rejects_unsafe_urls_before_process_launch(monkeypatch, url):
    d = desktop()
    monkeypatch.setattr(
        "udb.computer_desktop.subprocess.run",
        lambda *a, **kw: pytest.fail("Process launch must not happen"),
    )
    with pytest.raises(PolicyError):
        d.open_chrome_tab(url)


def test_open_tab_requires_an_existing_chrome_window(monkeypatch):
    d = desktop(windows=[])
    monkeypatch.setattr(
        "udb.computer_desktop.subprocess.run",
        lambda *a, **kw: pytest.fail("Must not create a Chrome window"),
    )
    with pytest.raises(PolicyError, match="No existing Google Chrome"):
        d.open_chrome_tab("https://example.org/")


def test_open_tab_reports_new_window_rather_than_claiming_reuse(monkeypatch):
    d = desktop()
    before = [(101, 9876, CHROME)]
    after = before + [(202, 9876, CHROME)]
    calls = iter([before, after])
    d._chrome_windows = lambda: next(calls)
    monkeypatch.setattr(
        "udb.computer_desktop.subprocess.run",
        lambda *a, **kw: SimpleNamespace(returncode=0),
    )
    result = d.open_chrome_tab("https://example.org/")
    assert result["existing_window_reused_observed"] is False
    assert result["chrome_windows_before"] == 1
    assert result["chrome_windows_after"] == 2


def test_open_tab_failed_launch_requires_inspection_before_retry(monkeypatch):
    d = desktop()
    monkeypatch.setattr(
        "udb.computer_desktop.subprocess.run",
        lambda *a, **kw: SimpleNamespace(returncode=1),
    )
    with pytest.raises(PolicyError, match="inspect before retrying"):
        d.open_chrome_tab("https://example.org/")


def test_open_tab_is_not_allowed_inside_desktop_batch():
    d = desktop()
    with pytest.raises(PolicyError, match="Invalid/nested batch step"):
        d.batch(
            "some-window",
            [{"action": "open_chrome_tab", "text": "https://example.org"}],
        )


def test_open_tab_is_a_recognized_desktop_action():
    Desktop.validate_options("open_chrome_tab")


def test_open_tab_ignores_retired_aura_marker(monkeypatch, tmp_path):
    marker = tmp_path / "UniversalDesktopBridge" / "chrome-aura-enabled"
    marker.parent.mkdir()
    marker.write_text("ancaoelohcjcbbmncfhimpookhdelhle", encoding="ascii")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    d = desktop()
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("udb.computer_desktop.subprocess.run", run)
    result = d.open_chrome_tab("https://example.org/ai?test=1")
    assert result["branding_requested"] is False
    assert result["branding_verified"] is False
    assert calls == [[CHROME, "--new-tab", "https://example.org/ai?test=1"]]


def test_open_chatgpt_reuses_existing_browser_without_touching_login(monkeypatch):
    d = desktop()
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("udb.computer_desktop.subprocess.run", run)
    result = d._dispatch("open_chatgpt", text="https://evil.example/ignored")
    assert calls[0][0] == [CHROME, "--new-tab", "https://chatgpt.com/"]
    assert calls[0][1]["shell"] is False
    assert result["requested"] is True
    assert result["launch_mode"] == "existing_chrome_tab"
    assert result["url"] == "https://chatgpt.com/"
    assert result["login_verified"] is False
    assert result["page_loaded_verified"] is False
    assert result["dom_attached"] is False
    assert result["replay_safe"] is False


def test_open_chatgpt_starts_default_browser_when_chrome_is_absent(monkeypatch):
    d = desktop(windows=[])
    urls = []
    monkeypatch.setattr(
        "udb.computer_desktop.os.startfile",
        urls.append,
        raising=False,
    )
    result = d._dispatch("open_chatgpt")
    assert urls == ["https://chatgpt.com/"]
    assert result["requested"] is True
    assert result["launch_mode"] == "default_browser"
    assert result["browser_launch_verified"] is False
    assert result["page_loaded_verified"] is False
    assert result["login_verified"] is False
    assert result["user_input_injected"] is False


def test_open_chatgpt_failed_default_browser_does_not_retry(monkeypatch):
    d = desktop(windows=[])
    requested = []

    def fail(url):
        requested.append(url)
        raise OSError("failed")

    monkeypatch.setattr("udb.computer_desktop.os.startfile", fail, raising=False)
    with pytest.raises(PolicyError, match="inspect the desktop before retrying"):
        d._dispatch("open_chatgpt")
    assert requested == ["https://chatgpt.com/"]


def test_open_chatgpt_does_not_fallback_after_uncertain_chrome_error(monkeypatch):
    d = desktop()
    called = []

    def fail(url):
        called.append(url)
        raise PolicyError("Chrome outcome unknown")

    d.open_chrome_tab = fail
    monkeypatch.setattr(
        "udb.computer_desktop.os.startfile",
        lambda url: pytest.fail("Must not retry through a different browser"),
        raising=False,
    )
    with pytest.raises(PolicyError, match="unknown"):
        d._dispatch("open_chatgpt")
    assert called == ["https://chatgpt.com/"]


def test_open_chatgpt_obeys_desktop_pause(monkeypatch):
    d = desktop()
    d.control = SimpleNamespace(
        check=lambda: (_ for _ in ()).throw(PolicyError("Desktop paused"))
    )
    d.open_chatgpt = lambda: pytest.fail("Paused launch must not occur")
    with pytest.raises(PolicyError, match="Desktop paused"):
        d._dispatch("open_chatgpt")


def test_open_chatgpt_not_allowed_in_batch():
    d = desktop()
    with pytest.raises(PolicyError, match="Invalid/nested batch step"):
        d.batch("some-window", [{"action": "open_chatgpt"}])
