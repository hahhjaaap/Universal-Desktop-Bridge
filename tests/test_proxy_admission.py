"""Resource routing must preserve grants, cleanup and escape actions under load."""

import time
from types import SimpleNamespace

import pytest

from udb.proxy import UnifiedProxy


class Backend:
    def __init__(self, trace, replies=None):
        self.trace, self.replies = trace, replies or {}

    def request(self, method, params=None, **kwargs):
        name = params["name"] if method == "tools/call" else method
        self.trace.append(name)
        return {"result": self.replies.get(name, {"structuredContent": {"ok": True}})}


def fixture_proxy(
    name,
    *,
    enabled=True,
    capabilities=("desktop", "execute"),
    paused=False,
    light=False,
    heavy=False,
    stale=False,
):
    trace = []
    primary = Backend(
        trace,
        {
            "computer_status": {
                "structuredContent": {
                    "enabled": enabled,
                    "capabilities": list(capabilities),
                    "desktop_paused": paused,
                }
            },
            "host_status": {
                "structuredContent": {
                    "resources": {
                        "at": time.time() - (60 if stale else 0),
                        "light_operations_ready": light,
                        "admission_ready": heavy,
                    }
                }
            },
        },
    )
    companion = Backend(trace)
    proxy = UnifiedProxy(primary, companion)
    proxy.tool_routes = {name: companion}
    return SimpleNamespace(proxy=proxy, trace=trace)


@pytest.mark.parametrize(
    "name,args",
    [
        ("terminal_stop", {}),
        ("terminal_read", {}),
        ("terminal_list", {}),
        ("terminal_wait", {}),
        ("search_read", {}),
        ("search_stop", {}),
        ("system_process_terminate", {}),
        ("file_operation", {"action": "read"}),
        ("file_operation", {"action": "list"}),
        ("file_operation", {"action": "cancel"}),
        ("file_upload", {"action": "status"}),
        ("file_upload", {"action": "abort"}),
        ("virtual_pointer", {"action": "hide"}),
        ("virtual_pointer", {"action": "stop"}),
        ("virtual_pointer", {"action": "status"}),
        ("work_recovery", {}),
        ("work_recovery", {"action": "inspect"}),
        ("terminal_interact", {}),
        ("terminal_interact", {"text": ""}),
    ],
)
def test_inspection_and_cleanup_do_not_need_a_healthy_resource_monitor(name, args):
    f = fixture_proxy(name, stale=True)
    f.proxy.call_tool({"name": name, "arguments": args})
    assert f.trace == ["computer_status", name]


@pytest.mark.parametrize(
    "name,args",
    [
        ("file_list", {}),
        ("file_read", {}),
        ("file_write", {}),
        ("file_replace", {}),
        ("file_stat", {}),
        ("file_mkdir", {}),
        ("file_copy", {}),
        ("file_move", {}),
        ("file_read_lines", {}),
        ("file_read_chunk", {}),
        ("system_process_list", {}),
        ("file_upload", {"action": "begin"}),
        ("file_upload", {"action": "write"}),
    ],
)
def test_light_admission_does_not_require_capacity_for_heavy_work(name, args):
    f = fixture_proxy(name, light=True)
    f.proxy.call_tool({"name": name, "arguments": args})
    assert f.trace == ["computer_status", "host_status", name]


@pytest.mark.parametrize(
    "name,args",
    [
        ("terminal_start", {}),
        ("terminal_interact", {"text": "run"}),
        ("search_start", {}),
        ("file_search", {}),
        ("spreadsheet", {}),
        ("word_document", {}),
        ("pdf_document", {}),
        ("future_unknown_tool", {}),
        ("file_operation", {"action": "copy"}),
        ("file_upload", {"action": "commit"}),
        ("work_recovery", {"action": "resume"}),
    ],
)
def test_new_work_and_upload_commit_still_require_heavy_admission(name, args):
    f = fixture_proxy(name, light=True)
    with pytest.raises(RuntimeError, match="Machine busy"):
        f.proxy.call_tool({"name": name, "arguments": args})
    assert f.trace == ["computer_status", "host_status"]


@pytest.mark.parametrize("name", ["terminal_stop", "file_read", "spreadsheet"])
def test_owner_revocation_precedes_every_resource_shortcut(name):
    f = fixture_proxy(name, enabled=False, light=True, heavy=True)
    with pytest.raises(RuntimeError, match="owner computer access"):
        f.proxy.call_tool({"name": name, "arguments": {}})
    assert f.trace == ["computer_status", "udb/close-sessions"]


@pytest.mark.parametrize(
    "name,args",
    [
        ("virtual_pointer", {"action": "status"}),
        ("terminal_start", {"mode": "conpty"}),
    ],
)
def test_capability_denial_precedes_resource_checks(name, args):
    f = fixture_proxy(name, capabilities=(), light=True, heavy=True)
    with pytest.raises(RuntimeError, match="capability is required"):
        f.proxy.call_tool({"name": name, "arguments": args})
    assert f.trace == ["computer_status"]


def test_local_pause_blocks_input_but_preserves_pointer_cleanup():
    f = fixture_proxy("virtual_pointer", paused=True, heavy=True)
    with pytest.raises(RuntimeError, match="paused locally"):
        f.proxy.call_tool({"name": "virtual_pointer", "arguments": {"action": "move"}})
    assert f.trace == ["computer_status"]
    f.proxy.call_tool({"name": "virtual_pointer", "arguments": {"action": "hide"}})
    assert f.trace == ["computer_status", "computer_status", "virtual_pointer"]


@pytest.mark.parametrize("name", ["file_read", "spreadsheet"])
def test_stale_admission_does_not_authorize_work(name):
    f = fixture_proxy(name, light=True, heavy=True, stale=True)
    with pytest.raises(RuntimeError, match="resource monitor unavailable"):
        f.proxy.call_tool({"name": name, "arguments": {}})
    assert f.trace == ["computer_status", "host_status"]


def test_family_resolution_happens_before_native_admission_classification():
    f = fixture_proxy("file_read", light=True)
    f.proxy.public_tool_names = frozenset({"project_files"})
    f.proxy.call_tool(
        {
            "name": "project_files",
            "arguments": {
                "action": "read",
                "params": {"path": "fixture.txt"},
            },
        }
    )
    assert f.trace == ["computer_status", "host_status", "file_read"]
