"""Memory-bounded hashing of Windows releases and source manifests."""

import hashlib
import tracemalloc
import zipfile
from pathlib import Path

from udb import build


def test_stream_sha256_matches_digest_without_loading_file_into_memory(tmp_path):
    payload = tmp_path / "runtime.dll"
    with payload.open("wb") as stream:
        for _ in range(24):
            stream.write(b"UDB" * (1024 * 1024 // 3))

    with payload.open("rb") as stream:
        expected = hashlib.file_digest(stream, "sha256").hexdigest()

    tracemalloc.start()
    try:
        actual = build.stream_sha256(payload)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert actual == expected
    assert peak < 2 * 1024 * 1024  # no 24 MiB read_bytes() allocation


def test_standalone_manifest_streams_large_runtime_files(tmp_path, monkeypatch):
    source, destination = tmp_path / "source", tmp_path / "out"
    (source / "tools").mkdir(parents=True)
    destination.mkdir()
    for path in (
        source / "LICENSE",
        source / "install.ps1",
        source / "tools/create_start_shortcut.ps1",
    ):
        path.write_text("fixture", encoding="utf-8")
    image = destination / "udb.exe"
    image.write_bytes(b"UDB" * (1024 * 1024))
    internal = destination / "_internal"
    internal.mkdir()
    runtime = internal / "runtime.dll"
    runtime.write_bytes(b"X" * (12 * 1024 * 1024))
    monkeypatch.setattr(build, "copy_notices", lambda target: [])

    # The old implementation read the entire 12 MiB binary into Python memory.
    original = Path.read_bytes

    def no_large_read_bytes(path):
        if path in (runtime, image):
            raise AssertionError("Build hashed a large file by reading it all")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", no_large_read_bytes)
    archive = build.standalone_package(source, destination, source, [], layout="onedir")
    with zipfile.ZipFile(archive) as package:
        rows = package.read("UDB/STANDALONE-SHA256SUMS").decode().splitlines()
        signatures = dict(row.split("  ", 1)[::-1] for row in rows)
        assert signatures["_internal/runtime.dll"] == build.stream_sha256(runtime)
        assert signatures["udb.exe"] == build.stream_sha256(image)


def test_source_manifest_does_not_eagerly_read_large_components(tmp_path, monkeypatch):
    pkg = tmp_path / "udb"
    pkg.mkdir()
    source = pkg / "fixture.py"
    source.write_bytes(b"# synthetic\n" * (1024 * 256))
    original = Path.read_bytes

    def forbid_source_read_bytes(path):
        if path == source:
            raise AssertionError("Read all source bytes instead of streaming")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", forbid_source_read_bytes)
    manifest = build.runtime_manifest(pkg)
    assert manifest["udb/fixture.py"] == build.stream_sha256(source)


def test_source_build_checksum_streams_large_artifacts(tmp_path, monkeypatch):
    from udb import metadata

    base = tmp_path / "source"
    out = tmp_path / "dist"
    config = base / "examples/config"
    config.mkdir(parents=True)
    (config / "udb.example.toml").write_text("# sample\n")
    (config / "MCP_CONFIGURATION.example.json").write_text("{}")
    wheel = out / "large.whl"
    wheel_size = 12 * 1024 * 1024

    def build_fixture(*args, **kwargs):
        out.mkdir(parents=True, exist_ok=True)
        with wheel.open("wb") as stream:
            stream.truncate(wheel_size)

    monkeypatch.setattr(build, "source_root", lambda: base)
    monkeypatch.setattr(build.subprocess, "run", build_fixture)
    monkeypatch.setattr(metadata, "manifest", lambda: {"name": "udb"})
    original = Path.read_bytes

    def forbid_artifact_read_bytes(path):
        if path == wheel:
            raise AssertionError("Large artifact must be checksummed by streaming")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", forbid_artifact_read_bytes)
    assert build.run(exe=False, output=out) == 0
    entries = dict(
        row.split("  ", 1)[::-1]
        for row in (out / "SHA256SUMS").read_text().splitlines()
    )
    assert entries["large.whl"] == build.stream_sha256(wheel)
