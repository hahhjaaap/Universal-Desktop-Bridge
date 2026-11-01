"""A failing Chrome/CDP smoke run must not leak browsing metadata."""

import json

from tools.browser_smoke_diagnostics import browser_smoke_failure


class FakeProcess:
    def alive(self):
        return True


class FakeCDP:
    def event_markers(self):
        return ("Network.requestWillBeSent", "PRIVATE_URL_SECRET")


class FakeBrowser:
    proc = FakeProcess()
    tabs = {"SECRET_TARGET_ID": "SECRET_SESSION_ID"}
    _cdp = FakeCDP()


def test_failure_diagnostics_are_bounded_and_redacted():
    report = browser_smoke_failure(
        FakeBrowser(), stage="initial_screenshot", elapsed_ms=10_000_000
    )
    assert report == {
        "check": "owned_browser_smoke",
        "stage": "initial_screenshot",
        "elapsed_ms": 120_000,
        "owned_process_alive": True,
        "owned_tab_count": 1,
        "cdp_event_marker_count": 2,
        "outcome": "unknown",
        "retry_performed": False,
    }
    raw = json.dumps(report)
    assert "SECRET" not in raw
    assert "Network" not in raw
    assert "http" not in raw


def test_diagnostics_resist_missing_or_invalid_observations():
    class Broken:
        class proc:
            @staticmethod
            def alive():
                raise OSError("PRIVATE_PATH")

        class _cdp:
            @staticmethod
            def event_markers():
                raise OSError("PRIVATE_URL")

        tabs = None

    report = browser_smoke_failure(Broken(), stage="malicious-url", elapsed_ms=float("nan"))
    assert report["stage"] == "unknown"
    assert report["elapsed_ms"] == 0
    assert report["owned_process_alive"] is None
    assert report["owned_tab_count"] is None
    assert report["cdp_event_marker_count"] is None
    assert report["outcome"] == "unknown"
    assert report["retry_performed"] is False
    assert "PRIVATE" not in str(report)


def test_diagnostics_missing_process_is_unknown_not_success():
    class Empty:
        pass

    report = browser_smoke_failure(Empty(), stage="initial_screenshot", elapsed_ms=-20)
    assert report["owned_process_alive"] is None
    assert report["elapsed_ms"] == 0
    assert report["owned_tab_count"] is None
