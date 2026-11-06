"""P0-B local smoke: ten independent agents share read-only project safely.

This is intentionally offline and uses disposable pytest fixtures. It does not
claim to validate Cloudflare, OAuth, paired Windows subprocesses or ChatGPT.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Barrier

import pytest

from udb.core import Agent, PolicyError


def test_ten_independent_agent_instances_read_and_deny_concurrently(tmp_path):
    home = tmp_path / "isolated-agent-home"
    project = tmp_path / "synthetic-project"
    project.mkdir()
    files = {
        "README.md": b"# Synthetic UDB read fixture\n",
        "module.py": b"def answer():\n    return 42\n",
    }
    for name, content in files.items():
        (project / name).write_bytes(content)
    (project / ".env").write_text("SYNTHETIC_ONLY=yes\n", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("SYNTHETIC_OUTSIDE\n", encoding="utf-8")

    bootstrap = Agent(home)
    bootstrap.register_local("staging", str(project), writable=False)
    expected_hashes = {name: sha256(data).hexdigest() for name, data in files.items()}
    barrier = Barrier(10, timeout=30)

    def run_worker(index: int) -> tuple[int, int]:
        # Separate Agent objects imply separate connections and fresh schema
        # initialization, matching how multiple stdio children access state.
        barrier.wait()
        agent = Agent(home)
        approved = denied = 0
        for iteration in range(8):
            name = "README.md" if (index + iteration) % 2 else "module.py"
            result = agent.read("staging", name)
            assert result["path"] == name
            assert result["sha256"] == expected_hashes[name]
            assert result["text"].encode("utf-8") == files[name]
            approved += 1
            protected = ".env" if iteration % 2 else "../outside.txt"
            with pytest.raises(PolicyError):
                agent.read("staging", protected)
            denied += 1
        with pytest.raises(PolicyError):
            agent.path("staging", "README.md", write=True)
        return approved, denied

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(run_worker, range(10)))
    assert sum(approved for approved, _ in results) == 80
    assert sum(denied for _, denied in results) == 80
    assert all((approved, denied) == (8, 8) for approved, denied in results)
    assert all((project / name).read_bytes() == data for name, data in files.items())
    with bootstrap.connect() as connection:
        count = connection.execute(
            "SELECT count(*) FROM events WHERE event = 'read'"
        ).fetchone()[0]
    assert count == 80, "Every allowed read must leave its normal local audit record"
