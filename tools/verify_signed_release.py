"""Verify a *published* or candidate Windows archive's Authenticode signer.

Validation only: this tool never signs an executable and never executes it.
A SHA256SUMS file produced alongside a release is not a trusted signature.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

MEMBER = "UDB/udb.exe"
MANIFEST = "UDB/STANDALONE-SHA256SUMS"
MAX_EXE_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 10000


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


def verify_archive_manifest(package: zipfile.ZipFile) -> dict:
    """Check every ZIP member against its self-consistency manifest.

    This guards packaging errors and unintentional tampering; an attacker who
    can replace both files and this unsigned manifest can still forge it.
    Publisher trust therefore requires separately authenticated provenance
    for every installer/script in a public release.
    """
    members = package.infolist()
    if not 2 <= len(members) <= MAX_ARCHIVE_FILES:
        raise ValueError("Invalid standalone archive member count")
    listed = {}
    seen_casefold = set()
    total_size = 0
    for item in members:
        name = item.filename
        if (
            item.is_dir()
            or not name.startswith("UDB/")
            or len(name) > 512
            or "\\" in name
            or "\x00" in name
            or any(part in ("", ".", "..") for part in name.split("/"))
            or name.casefold() in seen_casefold
            or ((item.external_attr >> 16) & 0o170000) == 0o120000
            or item.file_size < 0
            or item.file_size > MAX_EXE_BYTES
        ):
            raise ValueError("Unsafe standalone archive entry")
        seen_casefold.add(name.casefold())
        listed[name] = item
        total_size += item.file_size
        if total_size > MAX_TOTAL_BYTES:
            raise ValueError("Standalone archive exceeds size limit")
    if MEMBER not in listed or MANIFEST not in listed:
        raise ValueError("Standalone executable or manifest missing")
    if listed[MEMBER].file_size <= 0:
        raise ValueError("Invalid standalone executable size")
    manifest_info = listed[MANIFEST]
    if manifest_info.file_size <= 0 or manifest_info.file_size > MAX_MANIFEST_BYTES:
        raise ValueError("Standalone manifest size invalid")
    manifest_bytes = package.read(manifest_info)
    if len(manifest_bytes) != manifest_info.file_size:
        raise ValueError("Standalone manifest size changed")
    try:
        manifest = manifest_bytes.decode("ascii")
    except UnicodeDecodeError:
        raise ValueError("Standalone manifest must be ASCII") from None
    if not manifest.endswith("\n"):
        raise ValueError("Standalone manifest missing final newline")
    expected = {}
    for line in manifest.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\r\n]+)", line)
        if not match:
            raise ValueError("Invalid standalone checksum line")
        digest, relative = match.groups()
        member_name = "UDB/" + relative
        if member_name in expected:
            raise ValueError("Duplicate standalone manifest entry")
        expected[member_name] = digest
    if set(expected) != (set(listed) - {MANIFEST}):
        raise ValueError("Standalone manifest does not cover exact archive")
    for name, digest in expected.items():
        sha = hashlib.sha256()
        with package.open(listed[name]) as handle:
            while block := handle.read(1024 * 1024):
                sha.update(block)
        if sha.hexdigest() != digest:
            raise ValueError("Standalone manifest checksum mismatch")
    return {"members_verified": len(expected), "manifest_consistent": True}


def verify_archive(archive: Path, expected_thumbprint: str) -> dict:
    expected_thumbprint = normalized_thumbprint(expected_thumbprint)
    if os.name != "nt":
        raise RuntimeError("Run signer verification on Windows")
    with zipfile.ZipFile(archive) as zip_file:
        manifest_report = verify_archive_manifest(zip_file)
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
    return {
        "verified": True,
        "signer_thumbprint": signer["Thumbprint"].upper(),
        **manifest_report,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--signer-thumbprint", required=True)
    args = parser.parse_args()
    report = verify_archive(args.archive, args.signer_thumbprint)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
