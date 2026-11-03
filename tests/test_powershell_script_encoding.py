"""Windows PowerShell 5.1 requires a BOM for UTF-8 scripts with Unicode text."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_non_ascii_powershell_scripts_have_utf8_bom():
    scripts = [
        ROOT / "install.ps1",
        *(ROOT / "src").rglob("*.ps1"),
        *(ROOT / "tests").rglob("*.ps1"),
        *(ROOT / "tools").rglob("*.ps1"),
    ]
    assert scripts, "Expected PowerShell scripts in UDB"
    for script in scripts:
        data = script.read_bytes()
        # Reject invalid source encoding even if no Unicode character is used.
        data.decode("utf-8-sig")
        if any(byte >= 128 for byte in data):
            assert data.startswith(bytes((0xEF, 0xBB, 0xBF))), (
                f"{script.relative_to(ROOT)} contains non-ASCII UTF-8 but lacks "
                "a BOM required by Windows PowerShell 5.1"
            )
