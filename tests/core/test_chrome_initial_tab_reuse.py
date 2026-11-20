"""First UDB-owned Chrome page reuses the browser's blank target.

These isolated tests never attach to a personal Chrome profile, open
a browser, grant access, or perform any real page navigation.
"""

from __future__ import annotations

import time

import pytest

from udb.core import Agent, PolicyError
from udb.host_browser import Browser
from udb.host_client import atomic_json
from udb.host_service import HostService
from udb.resources import Governor


def _browser(pages):
    browser = Browser.__new__(Browser)
    browser.tabs = {row["tab_id"]: "owned-session" for row in pages}
    browser.listing = lambda: pages
    return browser


def test_first_owned_blank_target_is_reused_without_creating_another():
    browser = _browser([{"tab_id": "seed", "url": "about:blank"}])
    calls = []
    browser.navigate = lambda tab, url: (
        calls.append(("navigate", tab, url))
        or {"navigation_started": True, "tab_id": tab}
    )
    browser.new = lambda url: pytest.fail("Must not create a second Chrome tab")
    result = browser.open_initial("https://example.org/")
    assert result == {
        "tab_id": "seed",
        "navigation_started": True,
        "owner": "UDB",
        "background": True,
    }
    assert calls == [("navigate", "seed", "https://example.org/")]


def test_open_initial_blank_does_not_issue_cdp_mutation():
    browser = _browser([{"tab_id": "seed", "url": "about:blank"}])
    browser.navigate = lambda *a: pytest.fail("No navigation needed for blank")
    browser.new = lambda *a: pytest.fail("No new tab needed")
    assert browser.open_initial() == {
        "tab_id": "seed",
        "owner": "UDB",
        "background": True,
    }


@pytest.mark.parametrize(
    "pages",
    [
        [],
        [{"tab_id": "existing", "url": "https://example.org/"}],
        [
            {"tab_id": "seed", "url": "about:blank"},
            {"tab_id": "other", "url": "https://example.org/"},
        ],
    ],
)
def test_nonpristine_browser_keeps_existing_new_tab_contract(pages):
    browser = _browser(pages)
    calls = []
    browser.navigate = lambda *a: pytest.fail("Never repurpose a nonblank page")
    browser.new = lambda url: calls.append(url) or {"tab_id": "new"}
    assert browser.open_initial("https://example.org/") == {"tab_id": "new"}
    assert calls == ["https://example.org/"]


def test_failed_initial_navigation_must_not_fall_back_to_creating_tab():
    browser = _browser([{"tab_id": "seed", "url": "about:blank"}])
    browser.navigate = lambda tab, url: (_ for _ in ()).throw(
        PolicyError("Navigation timed out; outcome unknown")
    )
    browser.new = lambda *a: pytest.fail("Never replay uncertain navigation")
    with pytest.raises(PolicyError, match="outcome unknown"):
        browser.open_initial("https://example.org/")


def test_blocked_initial_url_fails_before_tab_inspection_or_navigation():
    browser = _browser([{"tab_id": "seed", "url": "about:blank"}])
    browser.listing = lambda: pytest.fail("Policy guard must run first")
    browser.new = lambda *a: pytest.fail("No tab creation on invalid URL")
    with pytest.raises(PolicyError, match="Local browser endpoints"):
        browser.open_initial("http://localhost/private")


@pytest.fixture
def engine(tmp_path):
    agent = Agent(tmp_path / "home")
    atomic_json(agent.state / "host-settings.json", {"enabled": True})
    service = HostService.__new__(HostService)
    service.agent = agent
    service.sessions = {}
    service.resource = Governor().update(
        {
            "at": time.time(),
            "cpu_percent": 12,
            "ram_percent": 40,
            "commit_percent": 50,
            "available_mib": 8000,
        }
    )
    service.folder = agent.state / "host"
    service.folder.mkdir()
    service.current = None
    return service


def test_host_first_open_uses_seed_but_repeated_or_explicit_opens_create_tabs(
    engine, monkeypatch
):
    spawned = []

    class FakeOwnedBrowser:
        def __init__(self, folder):
            self.deadline = None
            self.visible = False
            self.urls = ["about:blank"]
            self.actions = []
            spawned.append(self)

        def listing(self):
            return [
                {"tab_id": str(i), "url": url, "owner": "UDB"}
                for i, url in enumerate(self.urls)
            ]

        def open_initial(self, url):
            self.actions.append("open_initial")
            self.urls[0] = url
            return {"tab_id": "0", "owner": "UDB", "background": True}

        def new(self, url):
            self.actions.append("new")
            self.urls.append(url)
            return {
                "tab_id": str(len(self.urls) - 1),
                "owner": "UDB",
                "background": True,
            }

    monkeypatch.setattr("udb.host_browser.Browser", FakeOwnedBrowser)
    first = engine.dispatch(
        "browser", {"action": "open", "url": "https://example.org/first"}
    )
    assert len(spawned) == 1
    sid = first["session_id"]
    assert first["tab_id"] == "0"
    second = engine.dispatch(
        "browser", {"action": "open", "url": "https://example.org/second"}
    )
    third = engine.dispatch(
        "browser",
        {"action": "open", "session_id": sid, "url": "https://example.org/third"},
    )
    assert second["session_id"] == sid and second["tab_id"] == "1"
    assert third["session_id"] == sid and third["tab_id"] == "2"
    assert spawned[0].actions == ["open_initial", "new", "new"]
    assert spawned[0].urls == [
        "https://example.org/first",
        "https://example.org/second",
        "https://example.org/third",
    ]
