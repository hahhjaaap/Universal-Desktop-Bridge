import json
from pathlib import Path

from udb.registry import catalog
from udb.tool_policy import DEFAULT_READ_TOOLS, SCOPES, TOOL_POLICY

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "cloudflare" / "tool-catalog.json"
GENERATED = ROOT / "cloudflare" / "src" / "generated" / "tool-catalog.js"


def test_public_tool_policy_covers_exactly_59_tools():
    result = catalog()
    tools = result["tools"]
    names = [tool["name"] for tool in tools]
    assert result["tool_count"] == 59
    assert len(names) == len(set(names)) == 59
    assert set(names) == set(TOOL_POLICY)
    assert DEFAULT_READ_TOOLS == {
        "bridge_status",
        "list_projects",
        "list_files",
        "read_file",
        "search_files",
        "check_python_syntax",
    }


def test_only_six_safe_read_tools_are_enabled_by_default():
    enabled = {name for name, policy in TOOL_POLICY.items() if policy["defaultEnabled"]}
    assert enabled == DEFAULT_READ_TOOLS
    assert all(TOOL_POLICY[name]["readOnly"] for name in enabled)
    assert all(TOOL_POLICY[name]["parallelSafe"] for name in enabled)
    assert all(
        not policy["parallelSafe"]
        for name, policy in TOOL_POLICY.items()
        if name not in DEFAULT_READ_TOOLS
    )


def test_every_tool_has_one_known_scope_and_risk_classification():
    assert set(SCOPES) == {
        "udb:read",
        "udb:observe",
        "udb:write",
        "udb:execute",
        "udb:sandbox",
        "udb:host",
        "udb:computer",
        "udb:download",
        "udb:jobs",
    }
    for name, policy in TOOL_POLICY.items():
        assert len(policy["scopes"]) == 1, name
        assert policy["scopes"][0] in SCOPES, name
        assert policy["risk"] in {"low", "medium", "high", "critical"}, name
        assert not policy["defaultEnabled"] or policy["readOnly"], name


def test_generated_cloud_catalog_matches_live_registry_and_policy():
    result = catalog()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schemaVersion"] == 1
    assert manifest["toolCount"] == 59
    assert manifest["defaultTools"] == sorted(DEFAULT_READ_TOOLS)
    assert [tool["name"] for tool in manifest["tools"]] == [
        tool["name"] for tool in result["tools"]
    ]
    assert GENERATED.is_file()
    js = GENERATED.read_text(encoding="utf-8")
    assert "export const TOOL_CATALOG" in js
    assert "computer_process" in js
    assert "file_transfer" in js

    for tool in manifest["tools"]:
        policy = TOOL_POLICY[tool["name"]]
        assert tool["policy"]["scopes"] == list(policy["scopes"])
        assert tool["policy"]["defaultEnabled"] is policy["defaultEnabled"]
        assert tool["securitySchemes"][0]["scopes"] == list(policy["scopes"])
        assert tool["annotations"]["readOnlyHint"] is policy["readOnly"]
        assert tool["annotations"]["destructiveHint"] is policy["destructive"]
        assert tool["annotations"]["openWorldHint"] is policy["openWorld"]


def test_mutating_and_host_tools_never_receive_the_default_scope_implicitly():
    for name in (
        "file_write",
        "file_replace",
        "terminal_start",
        "terminal_interact",
        "computer_files",
        "computer_process",
        "computer_desktop",
        "host_browser",
        "desktop_action",
        "spreadsheet",
    ):
        assert name not in DEFAULT_READ_TOOLS
        assert TOOL_POLICY[name]["defaultEnabled"] is False
