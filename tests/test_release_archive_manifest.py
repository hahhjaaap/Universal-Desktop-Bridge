"""Standalone ZIP validation must reject stale checksums and unsafe members."""

from __future__ import annotations

import hashlib
import warnings
import zipfile

import pytest

from tools.verify_signed_release import verify_archive_manifest


FILES = {
    "UDB/udb.exe": b"MZ\x00\x01synthetic-not-signed",
    "UDB/install.ps1": b"Write-Output 'safe synthetic fixture'",
    "UDB/LICENSE": b"fixture license",
}


def archive(tmp_path, data=None, *, omit=None, overrides=None):
    data = dict(FILES if data is None else data)
    sums = "".join(
        hashlib.sha256(body).hexdigest() + "  " + name.removeprefix("UDB/") + "\n"
        for name, body in sorted(data.items())
        if name != "UDB/STANDALONE-SHA256SUMS" and name != omit
    ).encode("ascii")
    data["UDB/STANDALONE-SHA256SUMS"] = sums
    output = tmp_path / "candidate.zip"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as pkg:
        for name, value in data.items():
            pkg.writestr(name, overrides.get(name, value) if overrides else value)
    return output


def verify(path):
    with zipfile.ZipFile(path) as pkg:
        return verify_archive_manifest(pkg)


def test_valid_built_archive_has_matching_manifest(tmp_path):
    assert verify(archive(tmp_path)) == {
        "members_verified": 3,
        "manifest_consistent": True,
    }


def test_a_modified_signed_exe_or_installer_breaks_checksum(tmp_path):
    for name in ("UDB/udb.exe", "UDB/install.ps1"):
        destination = tmp_path / name.removeprefix("UDB/")
        destination.mkdir()
        z = archive(destination, overrides={name: b"malicious changed payload"})
        with pytest.raises(ValueError, match="checksum mismatch"):
            verify(z)


def test_extra_file_not_in_manifest_is_refused(tmp_path):
    with pytest.raises(ValueError, match="does not cover exact archive"):
        verify(archive(tmp_path, data={
            **FILES,
            "UDB/extra.txt": b"extra",
        }, omit="UDB/extra.txt"))


@pytest.mark.parametrize("bad_name", [
    "UDB/../outside.txt",
    "UDB/./install.ps1",
    "UDB//double.txt",
    "outside.txt",
    "UDB\\suspicious.txt",
])
def test_unsafe_archive_member_is_rejected(tmp_path, bad_name):
    pkg = archive(tmp_path, data={**FILES, bad_name: b"synthetic"})
    with pytest.raises(ValueError, match="Unsafe standalone archive entry"):
        verify(pkg)


def test_case_collision_is_rejected_on_windows(tmp_path):
    pkg = archive(tmp_path, data={**FILES, "UDB/INSTALL.PS1": b"colliding"})
    with pytest.raises(ValueError, match="Unsafe standalone archive entry"):
        verify(pkg)


def test_duplicate_manifest_entry_is_rejected(tmp_path):
    pkg = archive(tmp_path)
    with zipfile.ZipFile(pkg) as z:
        manifest = z.read("UDB/STANDALONE-SHA256SUMS")
    duplicate = manifest + manifest.splitlines(keepends=True)[0]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(pkg, "a") as z:
            z.writestr("UDB/STANDALONE-SHA256SUMS", duplicate)
    with pytest.raises(ValueError, match="Unsafe standalone archive entry"):
        verify(pkg)


def test_symlink_archive_member_is_rejected(tmp_path):
    pkg = archive(tmp_path)
    with zipfile.ZipFile(pkg, "a") as z:
        item = zipfile.ZipInfo("UDB/link")
        item.create_system = 3
        item.external_attr = (0o120777 << 16)
        z.writestr(item, b"../outside")
    with pytest.raises(ValueError, match="Unsafe standalone archive entry"):
        verify(pkg)


def test_invalid_manifest_encoding_or_missing_final_newline_is_rejected(tmp_path):
    for suffix, replacement in (("bad", b"\xff"), ("missing-newline", b"0" * 64)):
        directory = tmp_path / suffix
        directory.mkdir()
        pkg = archive(
            directory, overrides={"UDB/STANDALONE-SHA256SUMS": replacement}
        )
        with pytest.raises(ValueError, match="manifest"):
            verify(pkg)
