"""Onedir candidate packaging preserves resources and excludes owner state."""

import hashlib
import sys
import types
import zipfile
from pathlib import Path

import pytest

from tools.benchmark_startup import summary
from udb import build


@pytest.fixture
def package_tree(tmp_path, monkeypatch):
    base, output = tmp_path / "source", tmp_path / "candidate"
    (base / "tools").mkdir(parents=True)
    output.mkdir()
    (base / "LICENSE").write_text("public license")
    (base / "install.ps1").write_text("# fixed public installer")
    (base / "tools/create_start_shortcut.ps1").write_text("# fixed helper")
    (output / "udb.exe").write_bytes(b"synthetic test image")
    internal = output / "_internal"
    internal.mkdir()
    (internal / "python311.dll").write_bytes(b"synthetic runtime")
    (internal / "udb").mkdir()
    (internal / "udb/desktop_guest.py").write_text("# fixed guest payload")
    (output / "state").mkdir()
    (output / "state/private.json").write_text("PRIVATE-SENTINEL")
    (output / "owner.log").write_text("PRIVATE-SENTINEL")
    monkeypatch.setattr(build, "copy_notices", lambda _: [])
    return base, output, internal


def test_onedir_archive_hashes_complete_runtime_and_omits_adjacent_owner_state(
    package_tree,
):
    base, output, _ = package_tree
    archive = build.standalone_package(base, output, base, [], layout="onedir")
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        assert "UDB/_internal/python311.dll" in names
        assert "UDB/_internal/udb/desktop_guest.py" in names
        assert not any("state/" in name or name.endswith("owner.log") for name in names)
        for line in package.read("UDB/STANDALONE-SHA256SUMS").decode().splitlines():
            expected, name = line.split("  ", 1)
            assert hashlib.sha256(package.read("UDB/" + name)).hexdigest() == expected
        assert b"_internal" in package.read("UDB/STANDALONE.md")


@pytest.mark.parametrize(
    "private_name", ["receipt.dpapi", "workspace.sqlite3", ".env", "connection.json"]
)
def test_onedir_refuses_private_data_inside_runtime(package_tree, private_name):
    base, output, internal = package_tree
    (internal / private_name).write_text("PRIVATE-SENTINEL")
    with pytest.raises(ValueError, match="Owner state"):
        build.standalone_package(base, output, base, [], layout="onedir")
    assert not list(output.glob("*.zip"))


def test_onedir_requires_binary_build_and_valid_runtime(tmp_path):
    with pytest.raises(ValueError, match="requires --exe"):
        build.run(layout="onedir")
    (tmp_path / "udb.exe").write_bytes(b"synthetic")
    with pytest.raises(ValueError, match="runtime is missing"):
        build.standalone_package(tmp_path, tmp_path, tmp_path, [], layout="onedir")


def test_onedir_spec_collects_dependencies_and_readable_guest_source(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    for name in ("PyInstaller", "PyInstaller.utils", "PyInstaller.utils.hooks"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    hooks = sys.modules["PyInstaller.utils.hooks"]
    hooks.collect_data_files = lambda *a, **kw: []
    hooks.collect_submodules = lambda *a, **kw: []
    hooks.copy_metadata = lambda *a, **kw: []
    monkeypatch.setattr("udb.components.verified_assets", lambda _: [])
    monkeypatch.setenv("UDB_BUILD_LAYOUT", "onedir")
    monkeypatch.setenv("UDB_COLLECTION_NAME", "candidate")
    executable, collected = {}, {}

    def exe(*args, **kwargs):
        executable.update(kwargs)
        return "synthetic-exe"

    def collect(*args, **kwargs):
        collected.update(args=args, **kwargs)

    def analyze(*args, **kwargs):
        return types.SimpleNamespace(
            pure=[],
            scripts=[],
            binaries=[("runtime.dll", "source", "BINARY")],
            datas=kwargs["datas"],
        )

    namespace = dict(
        SPECPATH=str(root / "tools"),
        Analysis=analyze,
        PYZ=lambda *a: None,
        EXE=exe,
        COLLECT=collect,
    )
    spec = root / "tools/udb.spec"
    exec(compile(spec.read_text(), str(spec), "exec"), namespace)
    assert executable["exclude_binaries"] is True
    assert collected["name"] == "candidate" and collected["args"][0] == "synthetic-exe"
    assert (str(root / "src/udb/desktop_guest.py"), "udb") in collected["args"][2]


def test_benchmark_keeps_first_launch_separate_from_sorted_percentiles():
    value = summary([5, 1, 3, 2, 4])
    assert (
        value["first_launch_ms"] == 5 and value["p50_ms"] == 3 and value["p95_ms"] == 5
    )
