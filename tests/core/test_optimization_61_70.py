"""Isolated, noninteractive UDB host/browser/pointer optimization regressions.

All fixtures are fake owned profiles, inert CDP endpoints and temporary state.
They never launch Chrome, interact with a real Windows desktop or use grants.
"""

from __future__ import annotations

import ctypes
from types import SimpleNamespace

import pytest

from udb import browser_files, host_browser, host_service
from udb.browser_capture import CaptureCache
from udb.companion.virtual_pointer import VirtualPointer, _LastInputInfo
from udb.core import PolicyError
from udb.host_browser import Browser
from udb.host_service import HostService
from udb.host_workspace import Workspace


@pytest.mark.parametrize("duration", [True, False, 59, 1801, 120.5, "120"])
def test_61_session_preflight_refuses_invalid_duration_before_spawning(duration):
    service = HostService.__new__(HostService)
    service.sessions = {}
    with pytest.raises(PolicyError, match="duration"):
        service._start_session(
            {"kind": "workspace", "task": "Unit test", "duration_seconds": duration}
        )
    assert service.sessions == {}


def test_62_workspace_read_validates_just_once_in_message():
    workspace = Workspace.__new__(Workspace)
    calls = []

    def message(msg, _wp, _lp):
        calls.append(msg)
        workspace.validate()
        return 0

    workspace.validate = lambda: calls.append("validate")
    workspace.message = message
    assert workspace.read() == {
        "text": "",
        "scope": "owned_native_window",
        "no_activate": True,
    }
    assert calls == [0xD, "validate"]


def test_63_maintenance_uses_one_enablement_sample_per_sweep(monkeypatch):
    service = HostService.__new__(HostService)
    service.agent = object()
    service.sessions = {
        "a": {"object": SimpleNamespace(proc=None), "expires": 9999999999},
        "b": {"object": SimpleNamespace(proc=None), "expires": 9999999999},
    }
    closed, reads = [], []
    service._close = lambda sid: closed.append(sid)
    monkeypatch.setattr(
        host_service, "enabled", lambda agent: reads.append(agent) or False
    )
    service._maintain()
    assert closed == ["a", "b"]
    assert reads == [service.agent]


def test_64_listing_sanitizes_each_url_only_once_and_closes_unsafe_tab():
    browser = Browser.__new__(Browser)
    browser.tabs = {"owned": "sid"}
    targets = [
        {"type": "page", "targetId": "owned", "url": "https://example.com/?token=x"},
        {"type": "page", "targetId": "unsafe", "url": "chrome://settings"},
    ]
    count, closed = [], []
    original = Browser._safe_page_url
    browser._safe_page_url = lambda url: count.append(url) or original(url)

    def call(method, params=None, session=None, timeout=10):
        if method == "Target.getTargets":
            return {"targetInfos": targets}
        closed.append(params["targetId"])
        return {"success": True}

    browser.call = call
    assert browser.listing() == [
        {
            "tab_id": "owned",
            "title": "",
            "url": "https://example.com/",
            "owner": "UDB",
            "background": True,
        }
    ]
    assert len(count) == 2
    assert closed == ["unsafe"]


def test_65_precompiled_locator_does_not_expand_user_token_text(monkeypatch):
    template = Browser._locator_expression(
        "__BODY__", "", "", True, 'return "__TRAVERSAL__";'
    )
    assert 'const selector = "__BODY__"' in template
    assert 'return "__TRAVERSAL__";' in template
    monkeypatch.setattr(
        host_browser.re,
        "compile",
        lambda *_args, **_kwargs: pytest.fail("Do not recompile fixed locator regex"),
    )
    assert Browser._locator_expression("input", "", "", True, "return true;")


def test_66_screenshot_uses_one_owned_tab_lookup_and_preserves_size_bound():
    browser = Browser.__new__(Browser)
    browser.tabs = {"owned": "session-token"}
    calls, identities = [], []
    browser.sid = lambda tab: calls.append(tab) or "session-token"
    browser._show_identity = lambda tab, **kwargs: identities.append(
        (tab, kwargs["session"])
    )

    def call(method, params=None, session=None, timeout=10):
        assert method == "Page.captureScreenshot"
        assert session == "session-token"
        assert timeout == 20
        return {"data": "aGVsbG8="}

    browser.call = call
    assert browser.screenshot("owned") == "aGVsbG8="
    assert calls == ["owned"]
    assert identities == [("owned", "session-token")]
    browser.call = lambda *_a, **_k: {"data": "x" * (8 * 1048576 + 1)}
    with pytest.raises(PolicyError, match="too large"):
        browser.screenshot("owned")


def test_67_capture_stop_on_exact_tab_does_not_scan_other_keys():
    class NoIteration(dict):
        def __iter__(self):
            pytest.fail("single-tab stop should not enumerate streams")

    cache = CaptureCache()
    cache.streams = NoIteration(
        {("session", "tab"): {}, ("session", "other"): {}, ("else", "tab"): {}}
    )
    assert cache.stop("session", "tab") == {"stopped": True}
    assert cache.stop("session", "tab") == {"stopped": False}
    assert set(cache.streams.keys()) == {("session", "other"), ("else", "tab")}
    cache.streams = dict(cache.streams.items())
    assert cache.stop("session") == {"stopped": True}
    assert set(cache.streams) == {("else", "tab")}


@pytest.mark.parametrize(
    "selector,data",
    [("", b"small"), ("input[type=file]", b"x" * (8 * 1048576 + 1))],
)
def test_68_invalid_upload_preflight_never_contacts_browser(selector, data):
    browser = SimpleNamespace(
        evaluate=lambda *_a, **_k: pytest.fail("Invalid upload must not call CDP"),
        sid=lambda *_a, **_k: pytest.fail("Invalid upload must not adopt tab"),
    )
    with pytest.raises(PolicyError):
        browser_files.upload(
            browser,
            "tab",
            selector,
            SimpleNamespace(name="upload.txt"),
            data,
            "https://example.com",
        )


def test_69_browser_freeze_resolves_each_session_only_once():
    browser = Browser.__new__(Browser)
    browser.tabs = {"tab": "owned-sid"}
    browser.frozen = False
    calls, lookup = [], []
    browser.sid = lambda tab: lookup.append(tab) or "owned-sid"
    browser.call = lambda method, params=None, session=None, timeout=10: (
        calls.append((method, session)) or {}
    )
    browser.freeze(True)
    assert lookup == ["tab"]
    assert calls == [
        ("Page.stopLoading", "owned-sid"),
        ("Page.setWebLifecycleState", "owned-sid"),
    ]
    assert browser.frozen is True


def test_70_pointer_reuses_last_input_info_layout_without_os_input():
    pointer = VirtualPointer.__new__(VirtualPointer)
    calls = []

    def get_last_input_info(value):
        info = ctypes.cast(value, ctypes.POINTER(_LastInputInfo)).contents
        assert info.size == ctypes.sizeof(_LastInputInfo)
        info.time = 2468
        calls.append(info.size)
        return 1

    pointer.u = SimpleNamespace(GetLastInputInfo=get_last_input_info)
    assert pointer.input_stamp() == 2468
    assert pointer.input_stamp() == 2468
    assert len(calls) == 2
    pointer.u.GetLastInputInfo = lambda value: 0
    assert pointer.input_stamp() is None
