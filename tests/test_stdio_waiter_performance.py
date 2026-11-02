"""Regression tests for lightweight per-request RPC waiters and public name lookup."""

import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from udb.proxy import UnifiedProxy
from udb.transport import StdioChild


def test_rpc_waiter_delivers_only_matching_response_under_concurrency(tmp_path):
    child = StdioChild("fixture", [], str(tmp_path), lambda _: None)
    ids = []
    lock = threading.Lock()

    def reply(message):
        request_id = message["id"]
        value = message["params"]["value"]
        with lock:
            ids.append(request_id)
        waiter = child.waiters[request_id]
        assert isinstance(waiter, queue.SimpleQueue)
        waiter.put({"jsonrpc": "2.0", "id": request_id, "result": {"value": value}})

    child._send = reply
    with ThreadPoolExecutor(max_workers=10) as pool:
        answers = list(
            pool.map(
                lambda i: child.request("echo", {"value": i}, timeout=1),
                range(100),
            )
        )
    assert [a["result"]["value"] for a in answers] == list(range(100))
    assert len(set(ids)) == 100
    assert child.waiters == {}


def test_rpc_timeout_releases_simple_queue_waiter(tmp_path):
    child = StdioChild("fixture", [], str(tmp_path), lambda _: None)
    child._send = lambda _message: None
    with pytest.raises(TimeoutError, match="outcome unknown"):
        child.request("no-reply", {}, timeout=0.001)
    assert child.waiters == {}


def test_rpc_send_failure_releases_simple_queue_waiter(tmp_path):
    child = StdioChild("fixture", [], str(tmp_path), lambda _: None)
    child._send = Mock(side_effect=RuntimeError("synthetic failure"))
    with pytest.raises(RuntimeError, match="synthetic failure"):
        child.request("write-error", {}, timeout=1)
    assert child.waiters == {}


def test_consolidated_public_names_cached_once_and_not_mutable():
    primary, companion = Mock(), Mock()
    primary.name = "primary"
    companion.name = "companion"
    primary.request.return_value = {"result": {"tools": []}}
    companion.request.return_value = {"result": {"tools": []}}
    proxy = UnifiedProxy(primary, companion)

    assert proxy.tools_list() == {"tools": []}
    assert proxy.public_tool_names == frozenset()
    first_count = primary.request.call_count
    assert proxy.tools_list() == {"tools": []}
    assert primary.request.call_count == first_count
    assert companion.request.call_count == first_count
    with pytest.raises(ValueError, match="Unknown MCP tool"):
        proxy.call_tool({"name": "unknown", "arguments": {}})
