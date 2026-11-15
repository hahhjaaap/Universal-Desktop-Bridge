"""Keep Sandbox runtime trust identical across guest launchers."""

from __future__ import annotations

import json

import pytest

from udb.core import Agent, PolicyError
from udb.sandbox_runtime import trusted_python_runtime


def test_explicit_trusted_runtime_is_resolved(tmp_path):
    agent = Agent(tmp_path / "udb")
    runtime = tmp_path / "python-runtime"
    runtime.mkdir()
    (runtime / "python.exe").write_bytes(b"dummy; never executed")
    (agent.state / "runtime.json").write_text(
        json.dumps({"python_runtime": str(runtime)}), encoding="utf-8"
    )
    assert trusted_python_runtime(agent, error_message="untrusted") == runtime


@pytest.mark.parametrize("inside", ["home", "state", "missing"])
def test_untrusted_runtime_is_rejected_without_executing(tmp_path, inside):
    agent = Agent(tmp_path / "udb")
    runtime = {
        "home": agent.home,
        "state": agent.state,
        "missing": tmp_path / "missing-runtime",
    }[inside]
    if inside != "missing":
        (runtime / "python.exe").write_bytes(b"dummy")
    (agent.state / "runtime.json").write_text(
        json.dumps({"python_runtime": str(runtime)}), encoding="utf-8"
    )
    with pytest.raises(PolicyError, match="untrusted"):
        trusted_python_runtime(agent, error_message="untrusted")


def test_runtime_configuration_reparse_point_is_refused(tmp_path):
    agent = Agent(tmp_path / "udb")
    target = tmp_path / "outside.json"
    target.write_text('{"python_runtime":"X"}', encoding="utf-8")
    link = agent.state / "runtime.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink permission unavailable")
    with pytest.raises(PolicyError):
        trusted_python_runtime(agent, error_message="untrusted")
