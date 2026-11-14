"""Only cached diagnostics may be stale; live status and grants stay live."""

import json
from pathlib import Path

from udb import sandbox_refresh_cache
from udb.sandbox_refresh_cache import SandboxRestartCache


def test_unchanged_restart_hint_does_not_reopen_json(tmp_path, monkeypatch):
    path = tmp_path / "sandbox-setup-result.json"
    path.write_text('{"RestartNeeded": true}', encoding="utf-8")
    calls = []
    original = Path.open

    def counted(file, *args, **kwargs):
        if file == path:
            calls.append(True)
        return original(file, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counted)
    monkeypatch.setattr(sandbox_refresh_cache.time, "monotonic", lambda: 0.0)
    cache = SandboxRestartCache()
    for _ in range(100):
        assert cache.read(path) is True
    assert len(calls) == 1


def test_cache_invalidates_on_atomic_replacement_and_deletion(tmp_path, monkeypatch):
    path = tmp_path / "sandbox-setup-result.json"
    path.write_text('{"RestartNeeded": true}')
    monkeypatch.setattr(sandbox_refresh_cache.time, "monotonic", lambda: 0.0)
    cache = SandboxRestartCache()
    assert cache.read(path) is True
    replacement = tmp_path / "new.json"
    replacement.write_text('{"RestartNeeded": false}')
    replacement.replace(path)
    assert cache.read(path) is False
    path.unlink()
    assert cache.read(path) is False


def test_cache_refreshes_even_if_filesystem_metadata_looks_unchanged(
    tmp_path, monkeypatch
):
    path = tmp_path / "sandbox-setup-result.json"
    path.write_text('{"RestartNeeded": true}')
    clock = [0.0]
    monkeypatch.setattr(sandbox_refresh_cache.time, "monotonic", lambda: clock[0])
    cache = SandboxRestartCache()
    assert cache.read(path) is True

    # Model network/virtual filesystem metadata that remains unchanged.
    initial = path.lstat()
    original = Path.lstat

    def stale_stat(file, *args, **kwargs):
        if file == path:
            return initial
        return original(file, *args, **kwargs)

    path.write_text('{"RestartNeeded": false}')
    monkeypatch.setattr(Path, "lstat", stale_stat)
    assert cache.read(path) is True
    clock[0] = cache.RESCAN_SECONDS
    assert cache.read(path) is False


def test_invalid_and_missing_json_fail_to_no_restart_hint(tmp_path):
    path = tmp_path / "sandbox-setup-result.json"
    cache = SandboxRestartCache()
    assert cache.read(path) is False
    path.write_text("not json")
    assert cache.read(path) is False
    path.write_text(json.dumps({"RestartNeeded": True}))
    assert cache.read(path) is True
    path.write_text("[]")
    assert cache.read(path) is False


def test_restart_hint_never_consults_configuration_or_permissions(tmp_path):
    path = tmp_path / "sandbox-setup-result.json"
    path.write_text('{"RestartNeeded": true, "grant": "do not use"}')
    cache = SandboxRestartCache()
    assert cache.read(path) is True
    assert set(vars(cache)) == {"signature", "value", "next_read"}


def test_restart_cache_fails_closed_for_untrusted_input_types(tmp_path):
    path = tmp_path / "sandbox-setup-result.json"
    cache = SandboxRestartCache()
    for invalid in (
        '{"RestartNeeded": "false"}',
        '{"RestartNeeded": 1}',
        '{"RestartNeeded": ["true"]}',
        '{"RestartNeeded": null}',
    ):
        path.write_text(invalid + " " * (len(invalid) + 1))
        assert cache.read(path) is False


def test_restart_cache_never_reads_oversized_fixture(tmp_path, monkeypatch):
    path = tmp_path / "sandbox-setup-result.json"
    path.write_bytes(b"x" * (SandboxRestartCache.MAX_HINT_BYTES + 1))
    original = Path.open

    def forbidden(file, *args, **kwargs):
        if file == path:
            raise AssertionError("Oversized restart hint was opened")
        return original(file, *args, **kwargs)

    monkeypatch.setattr(Path, "open", forbidden)
    assert SandboxRestartCache().read(path) is False


def test_restart_cache_refuses_linked_file(tmp_path):
    outside = tmp_path / "external.json"
    outside.write_text('{"RestartNeeded": true}')
    linked = tmp_path / "sandbox-setup-result.json"
    try:
        linked.symlink_to(outside)
    except OSError:
        import pytest

        pytest.skip("Symlink privilege unavailable")
    assert SandboxRestartCache().read(linked) is False
