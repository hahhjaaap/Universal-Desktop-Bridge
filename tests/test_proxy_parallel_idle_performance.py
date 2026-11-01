"""Parallel read-only MCP discovery and mailbox optimization regressions."""

import os
import threading
from pathlib import Path

from udb.host_service import pending_inbox_commands
from udb.proxy import UnifiedProxy


class SlowBackend:
    def __init__(self, name, gate):
        self.name = name
        self.gate = gate
        self.requests = []

    def request(self, method, params=None):
        self.requests.append(method)
        # The barrier times out if the proxy invokes these backends sequentially.
        self.gate.wait(timeout=4)
        if method == "initialize":
            return {
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "serverInfo": {"name": self.name, "version": "1"},
                }
            }
        if method == "tools/list":
            return {
                "result": {
                    "tools": [
                        {
                            "name": "fixture_" + self.name,
                            "description": self.name,
                            "inputSchema": {"type": "object", "properties": {}},
                        }
                    ]
                }
            }
        raise AssertionError(method)


def test_parallel_initialize_preserves_primary_metadata():
    gate = threading.Barrier(2)
    core = SlowBackend("core", gate)
    companion = SlowBackend("companion", gate)
    proxy = UnifiedProxy(core, companion)
    proxy.startup_ok = True  # Do not start an unrelated owner-grant watcher.
    result = proxy.initialize({"protocolVersion": "2025-03-26"})
    assert result["protocolVersion"] == "2025-03-26"
    assert result["serverInfo"]["name"] == "UDB Unified"
    assert result["capabilities"]["tools"]["listChanged"] is False
    assert core.requests == companion.requests == ["initialize"]


def test_parallel_catalog_keeps_order_routes_and_cached_schema_isolation():
    gate = threading.Barrier(2)
    core = SlowBackend("core", gate)
    companion = SlowBackend("companion", gate)
    proxy = UnifiedProxy(core, companion)
    first = proxy.tools_list()["tools"]
    assert [x["name"] for x in first] == ["fixture_core", "fixture_companion"]
    assert proxy.tool_routes["fixture_core"] is core
    assert proxy.tool_routes["fixture_companion"] is companion
    first[0]["description"] = "mutation outside proxy"
    second = proxy.tools_list()["tools"]
    assert second[0]["description"] == "core"
    assert core.requests == companion.requests == ["tools/list"]


def test_inbox_listing_preserves_sorted_json_command_files(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for name in ("b.json", "a.json", "ignored.txt", "nested.json"):
        (inbox / name).write_text("{}", encoding="utf-8")
    # A directory with a JSON suffix is returned for existing per-file
    # validation to reject; listing itself does not follow any path.
    (inbox / "dir.json").mkdir()
    result = [p.name for p in pending_inbox_commands(inbox)]
    assert result == ["a.json", "b.json", "dir.json", "nested.json"]


def test_inbox_listing_empty_and_case_semantics(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    assert pending_inbox_commands(inbox) == []
    (inbox / "upper.JSON").write_text("{}")
    wanted = ["upper.JSON"] if os.name == "nt" else []
    assert [p.name for p in pending_inbox_commands(inbox)] == wanted
