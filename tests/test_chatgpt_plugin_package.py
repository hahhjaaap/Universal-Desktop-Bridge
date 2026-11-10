"""The private ChatGPT package must stay pinned to authenticated UDB staging."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "integrations" / "chatgpt-plugin"
EXPECTED_URL = (
    "https://udb-private-relay-staging.hkhoinguyen72.workers.dev/"
    "v1/devices/54841a965bb6405c9408137a1e2eb650/mcp"
)


def test_plugin_manifest_is_valid_and_concise():
    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    interface = manifest["extensions"]["com.openai"]["interface"]
    assert manifest["name"] == "udb-desktop-bridge"
    assert len(interface["displayName"]) <= 30
    assert len(interface["shortDescription"]) <= 30
    assert interface["category"] == "Developer Tools"
    assert interface["capabilities"] == []


def test_mcp_package_uses_exact_staging_resource():
    config = json.loads((ROOT / "mcp.json").read_text(encoding="utf-8"))
    assert set(config["mcpServers"]) == {"udb-staging"}
    server = config["mcpServers"]["udb-staging"]
    assert server["type"] == "streamable-http"
    assert server["url"] == EXPECTED_URL
    assert "production" not in server["url"]


def test_mcp_package_uses_managed_oauth_dcr_and_read_scope():
    config = json.loads((ROOT / "mcp.json").read_text(encoding="utf-8"))
    openai = config["mcpServers"]["udb-staging"]["extensions"]["com.openai"]
    assert openai["auth"] == {"type": "oauth", "client": {"mode": "dcr"}}
    assert openai["baseScopes"] == ["udb:read"]
    assert openai["defaultScopes"] == ["udb:read"]
    assert "clientId" not in openai["auth"].get("client", {})


def test_package_contains_no_embedded_credentials_or_tokens():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        raw = path.read_text(encoding="utf-8")
        lowered = raw.lower()
        assert "client_secret" not in lowered
        assert "access_token" not in lowered
        assert "refresh_token" not in lowered
        assert "bearer " not in lowered


def test_skill_requires_live_tool_discovery_and_oauth():
    skill = (ROOT / "skills" / "udb-desktop" / "SKILL.md").read_text(encoding="utf-8")
    assert "Inspect the tools actually exposed" in skill
    assert "OAuth sign-in and consent" in skill
    assert "Never retrieve or expose OAuth tokens" in skill
