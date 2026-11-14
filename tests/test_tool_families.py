"""Family routing, strict schema branches and desktop/gateway parity."""

import copy
import json
import shutil
import subprocess
from pathlib import Path

import jsonschema
import pytest

from udb import catalog as surface
from udb.registry import catalog
from udb.tool_families import FAMILIES, compact_schema, consolidate_families

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def inventory():
    return {tool["name"]: tool for tool in catalog()["tools"]}


@pytest.mark.parametrize("group", FAMILIES, ids=lambda g: g["name"])
def test_each_action_resolves_to_its_existing_handler_once(group, inventory):
    for action, target in group["actions"].items():
        args = (
            {"action": action, "session_id": "owned", "tab_id": "tab"}
            if group.get("extend")
            else {"action": action, "params": {}}
        )
        before = copy.deepcopy(args)
        assert surface.resolve_call(group["name"], args) == (
            target,
            {k: v for k, v in args.items() if k != "action"}
            if group.get("extend")
            else {},
        )
        assert args == before
    jsonschema.Draft202012Validator.check_schema(
        inventory[group["name"]]["inputSchema"]
    )


def test_nested_terminal_flags_keep_legacy_send_and_wait_behavior():
    assert surface.resolve_call(
        "terminal",
        {
            "action": "read",
            "params": {
                "session_id": "owned",
                "wait_for_exit": True,
                "wait_ms": 700,
            },
        },
    ) == ("terminal_wait", {"session_id": "owned", "timeout_ms": 700})
    assert surface.resolve_call(
        "terminal",
        {
            "action": "interact",
            "params": {
                "session_id": "owned",
                "send_only": True,
                "text": "hello",
            },
        },
    ) == ("terminal_send", {"session_id": "owned", "text": "hello"})


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"action": "start"},
        {"action": "start", "params": []},
        {"action": [], "params": {}},
        {"action": "__proto__", "params": {}},
        {"action": "read", "params": {}, "program": "unexpected"},
    ],
)
def test_invalid_or_ambiguous_wrappers_are_rejected(args):
    with pytest.raises(ValueError):
        surface.resolve_call("terminal", args)


def test_schema_requires_action_specific_fields_and_separate_guest_input(inventory):
    schema = inventory["terminal"]["inputSchema"]
    jsonschema.validate({"action": "start", "params": {"program": "fixture"}}, schema)
    for args in (
        {"action": "start", "params": {}},
        {"action": "list", "params": {"program": "wrong-action"}},
        {"action": "read", "params": {"program": "wrong-action"}},
    ):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(args, schema)
    args = {"action": "input", "params": {"session_id": "guest", "action": "click"}}
    jsonschema.validate(args, inventory["sandbox_desktop"]["inputSchema"])
    assert surface.resolve_call("sandbox_desktop", args) == (
        "desktop_action",
        args["params"],
    )


def test_browser_capture_is_strict_and_regular_calls_keep_their_shape(inventory):
    schema = inventory["host_browser"]["inputSchema"]
    for args in (
        {"action": "open", "url": "https://example.test"},
        {"action": "screenshot", "session_id": "s", "tab_id": "t"},
        {},
    ):
        jsonschema.validate(args, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"action": "screenshot", "url": "https://example.test"}, schema
        )
    with pytest.raises(ValueError):
        surface.resolve_call(
            "host_browser", {"action": "screenshot", "selector": "wrong"}
        )
    assert surface.resolve_call("host_browser", {"action": "list"}) == (
        "host_browser",
        {"action": "list"},
    )


def test_families_cannot_cross_backends_even_for_read_only_actions():
    tools = [
        {"name": name, "inputSchema": {"type": "object"}}
        for name in ("file_list", "file_read")
    ]
    with pytest.raises(RuntimeError, match="permission backends"):
        consolidate_families(
            tools, {name: object() for name in ("file_list", "file_read")}
        )


def test_gateway_and_desktop_produce_identical_schemas(monkeypatch):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for gateway parity")
    with monkeypatch.context() as patch:
        patch.setattr(surface, "consolidate_families", lambda tools, routes: tools)
        legacy = catalog()["tools"]
    script = """
import {consolidateFamilies} from './cloudflare/src/tool-families.js';
let raw=''; for await (const chunk of process.stdin) raw+=chunk;
process.stdout.write(JSON.stringify(consolidateFamilies(JSON.parse(raw))));
"""
    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        cwd=ROOT,
        input=json.dumps(legacy),
        text=True,
        capture_output=True,
        check=True,
        timeout=20,
    )
    assert json.loads(result.stdout) == catalog()["tools"]


def test_smaller_inventory_does_not_increase_discovery_payload(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(surface, "consolidate_families", lambda tools, routes: tools)
        legacy = catalog()["tools"]
    current = catalog()["tools"]

    def size(tools):
        return len(json.dumps(tools, separators=(",", ":")).encode("utf-8"))

    assert len(current) < len(legacy)
    assert size(current) <= size(legacy)


def test_compaction_preserves_real_fields_named_title():
    schema = {
        "title": "Generated",
        "properties": {"title": {"title": "Title", "type": "string"}},
    }
    assert compact_schema(schema) == {"properties": {"title": {"type": "string"}}}
