"""Disposable browser fixture failure simulation; no browser or network needed."""

from types import SimpleNamespace

import pytest

from udb.core import PolicyError
from udb.host_qa import (
    FIXTURE,
    QA_COMMAND_TIMEOUT_SECONDS,
    QA_SETUP_BUDGET_SECONDS,
    prepare_fixture,
)


class Browser:
    def __init__(self, fail_at=None):
        self.deadline = None
        self.calls = []
        self.fail_at = fail_at

    def sid(self, tab):
        assert tab == "fixture-tab"
        return "owned-session"

    def call(self, method, params=None, session=None, timeout=10):
        self.calls.append((method, params, session, timeout, self.deadline))
        if method == self.fail_at:
            raise PolicyError("Browser operation timed out; outcome unknown")
        if method == "Page.getFrameTree":
            return {"frameTree": {"frame": {"id": "fixture-frame"}}}
        return {}


def test_qa_setup_is_bounded_and_stages_are_never_replayed():
    browser = Browser()
    prepare_fixture(browser, "fixture-tab")
    assert [call[0] for call in browser.calls] == [
        "Page.getFrameTree",
        "Page.setDocumentContent",
    ]
    assert browser.calls[0][2] == browser.calls[1][2] == "owned-session"
    assert browser.calls[1][1] == {"frameId": "fixture-frame", "html": FIXTURE}
    assert all(call[3] == QA_COMMAND_TIMEOUT_SECONDS for call in browser.calls)
    assert all(call[4] is not None for call in browser.calls)
    assert QA_SETUP_BUDGET_SECONDS >= QA_COMMAND_TIMEOUT_SECONDS
    assert browser.deadline is None


@pytest.mark.parametrize("method", ["Page.getFrameTree", "Page.setDocumentContent"])
def test_failed_qa_setup_never_replays_an_uncertain_cdp_action(method):
    browser = Browser(fail_at=method)
    with pytest.raises(PolicyError, match="outcome unknown"):
        prepare_fixture(browser, "fixture-tab")
    assert [call[0] for call in browser.calls].count(method) == 1
    assert browser.deadline is None


def test_qa_restores_existing_browser_action_deadline():
    browser = Browser()
    browser.deadline = 123456.0
    prepare_fixture(browser, "fixture-tab")
    assert browser.deadline == 123456.0


def test_qa_does_not_mutate_browser_identity_or_owned_session():
    browser = Browser()
    before = SimpleNamespace(session="owned-session", tab="fixture-tab")
    prepare_fixture(browser, before.tab, html="<title>only-fixture</title>")
    assert browser.calls[-1][1]["html"] == "<title>only-fixture</title>"
    assert browser.calls[-1][2] == before.session
