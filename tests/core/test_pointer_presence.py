"""Virtual pointer presence and its independent owner-grant lifecycle."""

from pathlib import Path
from types import SimpleNamespace

from udb.companion.virtual_pointer import VirtualPointer
from udb.proxy import UnifiedProxy


def test_virtual_pointer_presence_uses_virtual_screen_not_system_cursor(monkeypatch):
    import sys

    monkeypatch.setitem(
        sys.modules,
        "win32api",
        SimpleNamespace(
            MonitorFromPoint=lambda point, flags: "primary",
            GetMonitorInfo=lambda monitor: {"Work": (-1920, -200, 1920, 1000)},
        ),
    )
    pointer = VirtualPointer.__new__(VirtualPointer)
    pointer.interactive = lambda: None
    metrics = {76: -1920, 77: -200, 78: 3840, 79: 1200}
    pointer.u = SimpleNamespace(GetSystemMetrics=lambda i: metrics[i])
    points = []
    pointer.show = lambda x, y: (
        points.append((x, y)),
        setattr(pointer, "position", [x, y]),
    )
    assert pointer.show_idle() == {
        "visibility": "selected_udb_chrome_tab_only",
        "position": [1776, 934],
        "independent": True,
    }
    assert points == [(1776, 934)]


class OneOrTwoCycles:
    def __init__(self, cycles):
        self.cycles = cycles
        self.count = 0

    def wait(self, seconds):
        self.count += 1
        return self.count > self.cycles


class FakePrimary:
    def __init__(self, states):
        self.states = iter(states)

    def request(self, method, params, timeout=5):
        assert method == "tools/call"
        assert params["name"] == "computer_status"
        return {"result": {"structuredContent": next(self.states)}}


class FakeCompanion:
    def __init__(self):
        self.calls = []

    def request(self, method, timeout=10):
        self.calls.append(method)
        return {"result": {"visible": True}}


def test_proxy_auto_shows_pointer_once_after_existing_desktop_grant():
    grant = {"enabled": True, "capabilities": ["desktop"]}
    primary = FakePrimary([grant, grant])
    companion = FakeCompanion()
    proxy = UnifiedProxy(primary, companion)
    proxy.closed = OneOrTwoCycles(2)
    proxy._watch_access()
    assert companion.calls == ["udb/show-pointer"]
    assert proxy._pointer_presence_started


def test_proxy_hides_pointer_when_grant_is_revoked():
    primary = FakePrimary(
        [
            {"enabled": True, "capabilities": ["desktop"]},
            {"enabled": False, "capabilities": []},
        ]
    )
    companion = FakeCompanion()
    proxy = UnifiedProxy(primary, companion)
    proxy.closed = OneOrTwoCycles(2)
    proxy._watch_access()
    assert companion.calls == ["udb/show-pointer", "udb/close-sessions"]
    assert not proxy._pointer_presence_started


def test_proxy_never_starts_pointer_without_desktop_capability():
    primary = FakePrimary([{"enabled": True, "capabilities": ["files"]}])
    companion = FakeCompanion()
    proxy = UnifiedProxy(primary, companion)
    proxy.closed = OneOrTwoCycles(1)
    proxy._watch_access()
    assert companion.calls == ["udb/close-desktop"]


def test_optional_pointer_failure_does_not_close_existing_work():
    class FailedCompanion(FakeCompanion):
        def request(self, method, timeout=10):
            self.calls.append(method)
            if method == "udb/show-pointer":
                raise RuntimeError("Overlay unavailable")
            return {"result": {}}

    primary = FakePrimary([{"enabled": True, "capabilities": ["desktop"]}])
    companion = FailedCompanion()
    proxy = UnifiedProxy(primary, companion)
    proxy.closed = OneOrTwoCycles(1)
    proxy._watch_access()
    assert companion.calls == ["udb/show-pointer"]
    assert not proxy._pointer_presence_started


def test_standalone_package_does_not_ship_retired_chrome_aura(tmp_path, monkeypatch):
    import zipfile

    from udb import build

    root = Path(__file__).resolve().parents[2]
    (tmp_path / "udb.exe").write_bytes(b"synthetic executable")
    monkeypatch.setattr(build, "copy_notices", lambda _: [])
    archive = build.standalone_package(root, tmp_path, tmp_path, [])
    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())
    assert not any("/chrome-extension/" in name for name in names)
    assert "UDB/tools/enable_chrome_aura.ps1" not in names
    assert "UDB/STANDALONE-SHA256SUMS" in names


def test_pointer_presence_hides_during_local_pause_and_returns_on_resume():
    grant = {"enabled": True, "capabilities": ["desktop"]}
    primary = FakePrimary([grant, {**grant, "desktop_paused": True}, grant])
    companion = FakeCompanion()
    proxy = UnifiedProxy(primary, companion)
    proxy.closed = OneOrTwoCycles(3)
    proxy._watch_access()
    assert companion.calls == [
        "udb/show-pointer",
        "udb/close-desktop",
        "udb/show-pointer",
    ]
