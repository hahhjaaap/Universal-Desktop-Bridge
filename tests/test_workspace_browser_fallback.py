"""Regression for the workspace browser's safe Edge-to-Chrome fallback."""

import asyncio
import importlib.util
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "chatgpt-workspace"


def browser_module(monkeypatch):
    monkeypatch.syspath_prepend(str(EXAMPLE))
    spec = importlib.util.spec_from_file_location(
        "udb_example_browser_under_test", EXAMPLE / "browser_flow.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeChromium:
    def __init__(self, edge_error=None, chrome_error=None):
        self.edge_error = edge_error
        self.chrome_error = chrome_error
        self.calls = []

    async def launch(self, *, channel, headless):
        self.calls.append((channel, headless))
        error = self.edge_error if channel == "msedge" else self.chrome_error
        if error:
            raise RuntimeError(error)
        return channel


def test_prefers_edge_when_present(monkeypatch):
    module = browser_module(monkeypatch)
    stub = FakeChromium()
    assert asyncio.run(module.launch_supported_browser(stub)) == "msedge"
    assert stub.calls == [("msedge", True)]


def test_absent_edge_falls_back_to_chrome(monkeypatch):
    module = browser_module(monkeypatch)
    stub = FakeChromium(edge_error="Chromium distribution 'msedge' is not found")
    assert asyncio.run(module.launch_supported_browser(stub)) == "chrome"
    assert stub.calls == [("msedge", True), ("chrome", True)]


def test_edge_launch_failure_is_not_silently_masked(monkeypatch):
    module = browser_module(monkeypatch)
    stub = FakeChromium(edge_error="Executable permission denied")
    with pytest.raises(RuntimeError, match="permission denied"):
        asyncio.run(module.launch_supported_browser(stub))
    assert stub.calls == [("msedge", True)]


def test_missing_both_browsers_reports_required_install(monkeypatch):
    module = browser_module(monkeypatch)
    stub = FakeChromium(
        edge_error="Chromium distribution 'msedge' is not found",
        chrome_error="Chromium distribution 'chrome' is not found",
    )
    with pytest.raises(RuntimeError, match="requires Microsoft Edge or Google Chrome"):
        asyncio.run(module.launch_supported_browser(stub))
    assert stub.calls == [("msedge", True), ("chrome", True)]
