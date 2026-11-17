"""The published Windows acceptance test must track the real MCP transport contract.

No release download, owner access or Windows installation occurs in these tests.
"""

import pytest

from tools.check_public_installer import is_cloudflare_only_release


@pytest.mark.parametrize(
    ("version", "cloud_only"),
    [
        ("0.9.3", False),
        ("0.10.0", False),
        ("0.11.9", False),
        ("0.12.0", True),
        ("0.13.0", True),
        ("0.14.0", True),
        ("1.0.0", True),
    ],
)
def test_public_installer_transport_contract(version, cloud_only):
    assert is_cloudflare_only_release(version) is cloud_only


@pytest.mark.parametrize("version", ["", "v0.13.0", "0.13", "0.13.0rc1", None, 0.13])
def test_public_installer_rejects_malformed_versions(version):
    with pytest.raises(ValueError, match="Invalid published UDB version"):
        is_cloudflare_only_release(version)


def test_acceptance_no_longer_infers_cloud_only_from_help_format():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "check_public_installer.py"
    ).read_text(encoding="utf-8")
    assert "cloud_only = is_cloudflare_only_release(version)" in source
    assert 'assert mcp["mcpServers"] == {}' in source
    assert '"universal-desktop-bridge"' in source  # Legacy version fallback only.
    assert 'run([exe, "--help"]).stdout' not in source
