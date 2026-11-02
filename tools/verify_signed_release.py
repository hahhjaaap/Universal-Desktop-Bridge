"""Verify a *published* or candidate Windows archive's Authenticode signer.

Validation only: this tool never signs an executable and never executes it.
A SHA256SUMS file produced alongside a release is not a trusted signature.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

MEMBER = "UDB/udb.exe"
MAX_EXE_BYTES = 512 * 1024 * 1024


def normalized_thumbprint(value: str) -> str:
    value = re.sub(r"\s+", "", value).upper()
    if not re.fullmatch(r"[A-F0-9]{40}", value):
        raise ValueError("Expected a 40-character SHA1 certificate thumbprint")
    return value


def signature_is_trusted(result: dict, expected_thumbprint: str) -> bool:
    """Certificate thumbprint identifies the pinned signer, not the file hash."""
    if not isinstance(result, dict):
        return False
    signer = result.get("SignerCertificate")
    return (
        result.get("Status") == 0
        and isinstance(signer, dict)
        and isinstance(signer.get("Thumbprint"), str)
        and signer["Thumbprint"].upper() == normalized_thumbprint(expected_thumbprint)
    )


def read_signature(executable: Path) -> dict:
    if os.name != "nt":
        raise RuntimeError("Authenticode verification must run on Windows")
    windows = Path(os.environ["SystemRoot"])
    powershell = windows / "System32/WindowsPowerShell/v1.0/powershell.exe"
    script = """
param([Parameter(Mandatory=$true)][string]$Target)
$ErrorActionPreference = 'Stop'
$signature = Get-AuthenticodeSignature -LiteralPath $Target
[pscustomobject]@{
    Status = [int]$signature.Status
    SignerCertificate = if ($signature.SignerCertificate) {
        [pscustomobject]@{
            Thumbprint = $signature.SignerCertificate.Thumbprint
            Subject = $signature.SignerCertificate.Subject
        }
    } else { $null }
} | ConvertTo-Json -Depth 5 -Compress
"""
    with tempfile.TemporaryDirectory(prefix="udb-signer-") as temp:
        script_file = Path(temp) / "verify.ps1"
        script_file.write_text(script, encoding="utf-8-sig")
        completed = subprocess.run(
            [
                str(powershell),
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_file),
                "-Target",
                str(executable),
            ],
            capture_output=True,
            text=True,
            timeout=40,
            check=False,
        )
    if completed.returncode != 0 or len(completed.stdout) > 8192:
        raise RuntimeError("Windows Authenticode verification failed")
    try:
        return json.loads(completed.stdout)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("Invalid Windows signature verification response") from exc


def verify_archive(archive: Path, expected_thumbprint: str) -> dict:
    expected_thumbprint = normalized_thumbprint(expected_thumbprint)
    if os.name != "nt":
        raise RuntimeError("Run signer verification on Windows")
    with zipfile.ZipFile(archive) as zip_file:
        members = [item for item in zip_file.infolist() if item.filename == MEMBER]
        if len(members) != 1:
            raise ValueError("Expected exactly one UDB/udb.exe in standalone archive")
        member = members[0]
        if member.file_size <= 0 or member.file_size > MAX_EXE_BYTES:
            raise ValueError("Unexpected standalone executable size")
        with tempfile.TemporaryDirectory(prefix="udb-release-verify-") as folder:
            exe = Path(folder) / "udb.exe"
            with zip_file.open(member) as source, exe.open("xb") as target:
                written = 0
                while chunk := source.read(1024 * 1024):
                    written += len(chunk)
                    if written > MAX_EXE_BYTES:
                        raise ValueError("Executable exceeded verification limit")
                    target.write(chunk)
            signature = read_signature(exe)
    if not signature_is_trusted(signature, expected_thumbprint):
        raise ValueError("Authenticode signature invalid or signer does not match")
    signer = signature["SignerCertificate"]
    return {"verified": True, "signer_thumbprint": signer["Thumbprint"].upper()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--signer-thumbprint", required=True)
    args = parser.parse_args()
    report = verify_archive(args.archive, args.signer_thumbprint)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
