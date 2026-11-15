"""UDB roadmap steps 91–100: bounded, synthetic performance regressions.

No actual host process termination, HLS download, Fleet network connection,
Cloudflare deployment, browser authorization or installer is invoked.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from udb import cli, fleet, maintenance, media, registry, setup
from udb.companion.system_processes import ProcessCatalog
from udb.fleet import FleetRouter
from udb.proxy import UnifiedProxy
from udb.tool_families import FAMILIES, resolve_family


def test_91_invalid_hls_path_rejected_before_owner_allowlist(monkeypatch):
    monkeypatch.setattr(
        media,
        "_hosts",
        lambda _agent: pytest.fail("Non-HLS URL must not touch host allowlist"),
    )
    with pytest.raises(ValueError, match="HLS"):
        media.validate(
            SimpleNamespace(state=None),
            "https://approved.example.com/assets/not-a-playlist.mp4",
            "safe.mp4",
        )


def test_92_process_list_validates_bounds_before_enumerating_system(tmp_path):
    processes = ProcessCatalog(tmp_path)
    processes._linux = lambda: pytest.fail("Invalid query must not scan processes")
    processes._windows = processes._linux
    for offset, limit in ((-1, 1), (0, 0), (0, 201), (True, 1), (1.5, 10)):
        with pytest.raises(ValueError, match="offset/limit"):
            processes.list(offset=offset, limit=limit)


def test_92_process_listing_keeps_filtered_order_and_page(tmp_path, monkeypatch):
    processes = ProcessCatalog(tmp_path)
    rows = [
        {
            "pid": number,
            "parent_pid": 0,
            "name": "Editor.exe" if number % 2 else "Other.exe",
            "same_user": True,
            "critical": False,
            "creation": number * 100,
            "image": "/tmp/fixture",
            "cpu_seconds": 0.0,
            "working_set_mib": 1.0,
            "private_commit_mib": 1.0,
        }
        for number in (101, 102, 103, 104, 105)
    ]
    monkeypatch.setattr(
        processes,
        "_windows" if fleet.os.name == "nt" else "_linux",
        lambda: [dict(row) for row in rows],
    )
    result = processes.list(match="eDiToR", offset=1, limit=1)
    assert result["total"] == 3
    assert [item["pid"] for item in result["processes"]] == [103]
    assert result["next_offset"] == 2
    assert result["processes"][0]["can_terminate"] is True
    assert result["processes"][0]["observation_id"] in processes.observations


def test_93_process_termination_invalid_token_never_reaches_os(tmp_path):
    processes = ProcessCatalog(tmp_path)
    processes.observations["a" * 32] = {
        "pid": 321,
        "creation": 1,
        "until": 9999999999,
    }
    for token in ("", "not-a-token", None, "A" * 32, []):
        with pytest.raises(ValueError, match="Observation expired"):
            processes.terminate(token)
    assert "a" * 32 in processes.observations


@pytest.mark.parametrize(
    "arguments", [{"bad": object()}, {"nonfinite": float("nan")}]
)
def test_94_invalid_fleet_json_never_loads_secret_or_dials(
    tmp_path, monkeypatch, arguments
):
    router = FleetRouter(
        tmp_path, "pc-home", {"pc-office": "https://pc-office.example.ts.net"}
    )
    monkeypatch.setattr(
        fleet,
        "load_secret",
        lambda *_a: pytest.fail("Invalid arguments must not read fleet token"),
    )
    with pytest.raises(ValueError, match="valid JSON"):
        router.invoke("pc-office", "bridge_status", arguments)
    with pytest.raises(ValueError, match="no fallback"):
        router.invoke([], "bridge_status", {})


def test_95_sorted_fleet_listing_is_stable_and_detached(tmp_path):
    router = FleetRouter(
        tmp_path,
        "pc-home",
        {
            "pc-zeta": "https://zeta.example.ts.net",
            "pc-alpha": "https://alpha.example.ts.net",
        },
    )
    original = router.list_computers()
    assert [row["id"] for row in original["computers"]] == [
        "pc-home", "pc-alpha", "pc-zeta"
    ]
    original["computers"][1]["id"] = "changed"
    assert router.list_computers()["computers"][1]["id"] == "pc-alpha"
    assert router.list_computers()["note"].startswith("Remote entries")


class _Backend:
    def __init__(self, name):
        self.name = name
        self.calls = []

    def request(self, method, params=None):
        self.calls.append(method)
        if method == "tools/list":
            return {
                "result": {
                    "tools": [{
                        "name": "fixture_" + self.name,
                        "description": self.name,
                        "inputSchema": {"type": "object", "properties": {}},
                    }]
                }
            }
        if method == "initialize":
            return {
                "result": {
                    "capabilities": {},
                    "protocolVersion": "2025-03-26",
                }
            }
        raise AssertionError(method)


def test_96_cached_mcp_catalog_isolation_and_no_redundant_backend_rpc():
    primary = _Backend("core")
    companion = _Backend("companion")
    gateway = UnifiedProxy(primary, companion)
    first = gateway.tools_list()
    assert gateway._tool_catalog_json is not None
    first["tools"][0]["inputSchema"]["properties"]["evil"] = {"type": "boolean"}
    again = gateway.tools_list()
    assert "evil" not in again["tools"][0]["inputSchema"]["properties"]
    assert primary.calls == ["tools/list"]
    assert companion.calls == ["tools/list"]


def test_97_family_dispatch_is_stable_without_unknown_action_escalation():
    group = FAMILIES[0]
    action, target = next(iter(group["actions"].items()))
    arguments = {"action": action, "params": {"fixture": "value"}}
    assert resolve_family(group["name"], arguments) == (
        target, {"fixture": "value"}
    )
    assert arguments == {"action": action, "params": {"fixture": "value"}}
    assert resolve_family("unrelated_native", arguments) == (
        "unrelated_native", arguments
    )
    with pytest.raises(ValueError, match="Unknown"):
        resolve_family(
            group["name"], {"action": "never-a-tool", "params": {}}
        )


def test_98_setup_origin_is_selected_once_for_locked_canary(
    tmp_path, monkeypatch
):
    calls = []
    monkeypatch.setattr(setup, "attended_console", lambda: True)
    monkeypatch.setattr(setup.owner_command, "launch_gate", lambda *_a, **_k: nullcontext())
    monkeypatch.setattr(setup, "installation_status", lambda: {})
    monkeypatch.setattr(setup, "read_journal", lambda *_a: {"schema": 1})
    monkeypatch.setattr(setup, "paired_cloud", lambda *_a: None)
    monkeypatch.setattr(setup, "prepare_pending", lambda *_a: {"id": "fixture"})
    monkeypatch.setattr(
        setup,
        "setup_relay",
        lambda: calls.append("origin") or setup.FLEET_TEST_RELAY,
    )
    monkeypatch.setattr(
        setup,
        "_request_json",
        lambda *_a, **_k: (200, {"protocol": 2, "browser_enrollment": False}),
    )
    settings = SimpleNamespace(home=tmp_path)
    assert setup.run(settings, opener=object(), browser=lambda *_a: None) == 2
    assert calls == ["origin"]


def test_99_compact_tools_cli_only_serializes_public_names(monkeypatch, capsys):
    inventory = {
        "tools": [
            {"name": "zeta", "inputSchema": {"properties": {"secret": 1}}},
            {"name": "alpha", "inputSchema": {}},
        ],
        "tool_count": 2,
        "backend_count": 4,
        "core_count": 2,
        "companion_count": 2,
    }
    monkeypatch.setattr(registry, "catalog", lambda: inventory)
    assert cli.main(["tools", "--names"]) == 0
    short = json.loads(capsys.readouterr().out)
    assert short == {
        "version": cli.VERSION,
        "tool_count": 2,
        "backend_count": 4,
        "names": ["alpha", "zeta"],
    }
    assert cli.main(["tools"]) == 0
    full = json.loads(capsys.readouterr().out)
    assert full["tools"][0]["inputSchema"]["properties"] == {"secret": 1}


def test_100_no_update_skips_installer_path_and_powershell(
    tmp_path, monkeypatch, capsys
):
    from udb import windows_paths

    installed = {
        "version": "7.8.9",
        "home": str(tmp_path),
    }
    monkeypatch.setattr(
        maintenance, "installation", lambda: (tmp_path, installed)
    )
    monkeypatch.setattr(
        maintenance, "require_external_updater", lambda *_a: None
    )
    monkeypatch.setattr(maintenance, "latest_release", lambda: "7.8.9")
    monkeypatch.setattr(
        maintenance,
        "installer_script",
        lambda: pytest.fail("No installer lookup for current version"),
    )
    monkeypatch.setattr(
        windows_paths,
        "system_executable",
        lambda *_a: pytest.fail("No PowerShell lookup for current version"),
    )
    assert maintenance.run(
        "update", SimpleNamespace(home=tmp_path), as_json=True
    ) == 0
    assert json.loads(capsys.readouterr().out) == {
        "updated": False, "version": "7.8.9"
    }
