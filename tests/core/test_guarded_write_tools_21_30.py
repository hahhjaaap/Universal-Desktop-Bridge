"""Owner-scoped regression tests for UDB write/replace/transfer steps 21–30."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from udb.companion import extensions
from udb.companion.files import ScopedFiles
from udb.computer_files import Files
from udb.core import Agent, PolicyError, diff_preview
from udb.fileops import propose_text_edit


@pytest.fixture
def project(tmp_path):
    agent = Agent(tmp_path / "owner")
    source = tmp_path / "source"
    source.mkdir()
    agent.register_local("demo", str(source), True)
    return agent, source


def test_proposal_diff_matches_legacy_and_omits_huge_preview(project):
    agent, source = project
    (source / "script.py").write_text("before = 1\n", encoding="utf-8")
    original = (source / "script.py").read_bytes()
    after = "after = 'xin chào'\n"
    assert diff_preview(original, after, "script.py") == diff_preview(
        original, after, "script.py", new_size=len(after.encode("utf-8"))
    )
    assert "Diff preview omitted" in diff_preview(
        original, "x" * (130 * 1024), "script.py", new_size=130 * 1024
    )
    previous = agent.read("demo", "script.py")["sha256"]
    proposal = agent.propose_write("demo", "script.py", after, previous)
    assert proposal["status"] == "pending_local_approval"
    assert (source / "script.py").read_bytes() == original
    with pytest.raises(PolicyError, match="Stale file"):
        agent.propose_write("demo", "script.py", after, "0" * 64)


def test_exact_replacement_count_unicode_crlf_and_no_auto_write(project):
    agent, source = project
    path = source / "format.py"
    text = "# café\r\nvalue = '🍀'\r\nvalue = '🍀'\r\n"
    path.write_bytes(text.encode("utf-8"))
    original_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    response = propose_text_edit(
        agent, "demo", "format.py", "🍀", "🌿", original_sha, occurrences=2
    )
    assert response["status"] == "pending_local_approval"
    with agent.connect() as db:
        payload = json.loads(
            db.execute(
                "SELECT payload FROM requests WHERE id=?", (response["request_id"],)
            ).fetchone()[0]
        )
    assert payload["text"] == text.replace("🍀", "🌿", 2)
    assert "\r\n" in payload["text"]
    assert path.read_bytes() == text.encode("utf-8")
    with pytest.raises(PolicyError, match="count"):
        propose_text_edit(
            agent, "demo", "format.py", "🍀", "🌿", original_sha, occurrences=1
        )
    with pytest.raises(PolicyError, match="changed"):
        propose_text_edit(
            agent, "demo", "format.py", "🍀", "🌿", "0" * 64, occurrences=2
        )


def test_companion_guarded_write_and_replace_preserve_recovery(tmp_path):
    files = ScopedFiles(str(tmp_path))
    current = "emoji = '🍀'\r\nemoji = '🍀'\r\n"
    created = files.write("hello.py", current, "NEW")
    assert created["created"] is True
    updated = files.replace("hello.py", "🍀", "🌿", created["sha256"], occurrences=2)
    assert updated["replacements"] == 2
    assert (tmp_path / "hello.py").read_bytes().decode("utf-8") == current.replace(
        "🍀", "🌿"
    )
    assert list((tmp_path / ".udb-recovery").glob("*.bak"))
    assert any(
        p.read_bytes().decode("utf-8") == current
        for p in (tmp_path / ".udb-recovery").glob("*.bak")
    )
    for occurrences in (True, 0, 101, "2"):
        with pytest.raises(ValueError, match="Occurrences"):
            files.replace(
                "hello.py", "🌿", "🍀", updated["sha256"], occurrences=occurrences
            )
    with pytest.raises(ValueError, match="changed"):
        files.replace("hello.py", "🌿", "🍀", "0" * 64, occurrences=2)
    assert (tmp_path / "hello.py").read_bytes().decode("utf-8") == current.replace(
        "🍀", "🌿"
    )


def test_companion_mkdir_atomic_create_only_and_case_collision(tmp_path):
    files = ScopedFiles(str(tmp_path))
    rt = SimpleNamespace(files=files)
    assert "Created directory" in extensions._file_mkdir(rt, {"path": "folder"})
    with pytest.raises(FileExistsError, match="Directory already exists"):
        extensions._file_mkdir(rt, {"path": "folder"})
    assert (tmp_path / "folder").is_dir()
    if __import__("os").name == "nt":
        with pytest.raises(FileExistsError):
            extensions._file_mkdir(rt, {"path": "FOLDER"})


def test_copy_is_streamed_verified_and_never_replaces_other_owner(
    tmp_path, monkeypatch
):
    source = tmp_path / "original.txt"
    source.write_bytes(b"approved bytes" * 1000)
    files = ScopedFiles(str(tmp_path))
    rt = SimpleNamespace(files=files)
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    result = extensions._file_copy(
        rt,
        {
            "source": "original.txt",
            "destination": "copied.txt",
            "expected_sha256": expected,
        },
    )
    assert expected in result
    assert (tmp_path / "copied.txt").read_bytes() == source.read_bytes()
    with pytest.raises(FileExistsError):
        extensions._file_copy(
            rt, {"source": "original.txt", "destination": "copied.txt"}
        )

    original_hash = extensions._sha256
    mutated = False

    def change_after_first_hash(path):
        nonlocal mutated
        hash_value = original_hash(path)
        if path == source and not mutated:
            mutated = True
            source.write_bytes(b"changed bytes" * 1000)
        return hash_value

    monkeypatch.setattr(extensions, "_sha256", change_after_first_hash)
    with pytest.raises(IOError, match="Source changed"):
        extensions._file_copy(
            rt, {"source": "original.txt", "destination": "raced.txt"}
        )
    assert not (tmp_path / "raced.txt").exists()


def test_supplied_copy_hash_does_not_rehash_source(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_bytes(b"same-volume-transfer" * 256)
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    files = ScopedFiles(str(tmp_path))
    rt = SimpleNamespace(files=files)
    original_hash = extensions._sha256
    seen = []

    def counted(path):
        seen.append(path)
        return original_hash(path)

    monkeypatch.setattr(extensions, "_sha256", counted)
    extensions._file_copy(
        rt,
        {
            "source": "source.txt",
            "destination": "copy.txt",
            "expected_sha256": expected,
        },
    )
    assert seen.count(source) == 1
    assert seen.count(tmp_path / "copy.txt") == 1


def test_computer_files_shared_bounds_and_recovery_are_verified(project):
    agent, root = project
    files = Files(agent)
    created = files.dispatch(
        "write", str(root / "invoice.txt"), content="original", expected_sha256="NEW"
    )
    replacement = files.dispatch(
        "write",
        str(root / "invoice.txt"),
        content="changed",
        expected_sha256=created["sha256"],
    )
    recovery = agent.state / "computer-recovery" / replacement["recovery_id"]
    assert recovery.read_bytes() == b"original"
    assert (root / "invoice.txt").read_text() == "changed"
    details = files.dispatch("stat", str(root / "invoice.txt"))
    assert details["sha256"] == replacement["sha256"]
    listing = files.dispatch("list", str(root), limit=100)
    assert "invoice.txt" in {row["name"] for row in listing["entries"]}
    for value in (True, False, 1.0):
        with pytest.raises(PolicyError, match="offset"):
            files.dispatch("read", str(root / "invoice.txt"), offset=value)
        with pytest.raises(PolicyError, match="offset"):
            files.dispatch("list", str(root), offset=value)
    with pytest.raises(PolicyError):
        files.dispatch(
            "write", str(root / "invoice.txt"), content="no", expected_sha256="NEW"
        )


def test_computer_copy_move_still_guards_destination_and_source(project):
    agent, root = project
    files = Files(agent)
    source = root / "source.txt"
    source.write_bytes(b"trusted")
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    copied = files.dispatch(
        "copy",
        str(source),
        destination=str(root / "copied.txt"),
        expected_sha256=expected,
    )
    assert copied["sha256"] == expected
    assert source.exists()
    with pytest.raises(PolicyError):
        files.dispatch(
            "move",
            str(source),
            destination=str(root / "copied.txt"),
            expected_sha256=expected,
        )
    moved = files.dispatch(
        "move",
        str(source),
        destination=str(root / "moved.txt"),
        expected_sha256=expected,
    )
    assert moved["moved"] is True
    assert not source.exists()
    assert (root / "moved.txt").read_bytes() == b"trusted"
