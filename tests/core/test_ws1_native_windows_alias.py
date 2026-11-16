"""Regression: Win32 8.3 aliases must be subject to the full protected-name policy."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path

import pytest

from udb.companion.files import ScopedFiles
from udb.core import Agent, PolicyError
from udb.path_policy import canonical_relative_parts


@pytest.fixture
def source_apis(tmp_path):
    agent = Agent(tmp_path / "owner")
    source = tmp_path / "source"
    source.mkdir()
    agent.register_local("synthetic", str(source), True)
    return agent, source, ScopedFiles(str(source))


def test_injected_alias_resolves_to_protected_long_name(source_apis):
    agent, source, files = source_apis
    alias = source / "CREDEN~1.PY"
    alias.write_text("synthetic only", encoding="utf-8")

    def resolver(path):
        if path == alias:
            return source / "credentials_private.py"
        return path

    assert canonical_relative_parts(source, alias, long_path=resolver) == (
        "credentials_private.py",
    )


def test_resolver_failure_fails_closed(source_apis):
    agent, source, files = source_apis
    alias = source / "CREDEN~1.PY"
    alias.write_text("synthetic only", encoding="utf-8")

    def fail(path):
        if path == alias:
            raise OSError("synthetic resolver failure")
        return path

    with pytest.raises(PermissionError):
        canonical_relative_parts(source, alias, long_path=fail)


@pytest.mark.parametrize("name", [".git.", "credentials.dat ", "normal.py."])
def test_windows_trailing_name_rejected(source_apis, name):
    agent, source, files = source_apis
    with pytest.raises(PolicyError):
        agent.path("synthetic", name)
    with pytest.raises(PermissionError):
        files.path(name, allow_missing=True)


def test_real_tilde_filename_is_allowed(source_apis):
    agent, source, files = source_apis
    path = source / "hello~work.py"
    path.write_text("x=1", encoding="utf-8")
    assert agent.path("synthetic", path.name) == path
    assert files.path(path.name) == path


@pytest.mark.skipif(os.name != "nt", reason="Requires genuine native Windows 8.3 alias")
def test_actual_short_name_denied_by_both_apis(source_apis):
    agent, source, files = source_apis
    target = source / "credentials_long_filename.py"
    target.write_text("synthetic only", encoding="utf-8")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    api = kernel.GetShortPathNameW
    api.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint)
    api.restype = ctypes.c_uint
    buf = ctypes.create_unicode_buffer(32768)
    count = api(str(target), buf, len(buf))
    if count <= 0 or count >= len(buf):
        pytest.skip("8.3 aliases not enabled on this volume")
    alias = Path(buf.value).name
    if alias.casefold() == target.name.casefold():
        pytest.skip("8.3 aliases not enabled on this volume")
    assert (source / alias).resolve() == target.resolve()
    with pytest.raises(PolicyError):
        agent.path("synthetic", alias)
    with pytest.raises(PermissionError):
        files.path(alias)
