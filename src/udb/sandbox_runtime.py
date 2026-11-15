"""Shared trusted Python runtime selection for the two isolated Sandbox launchers.

The guest approval and execution boundaries remain in their respective modules.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .core import PolicyError, reject_links


def trusted_python_runtime(agent, *, error_message: str) -> Path:
    """Choose an explicit or packaged interpreter, refusing private/linked paths."""
    config = agent.state / "runtime.json"
    reject_links(config)
    runtime = (
        Path(json.loads(config.read_text("utf-8-sig"))["python_runtime"])
        if config.exists()
        else (
            Path(sys.executable).parent / "vendor" / "python-runtime"
            if getattr(sys, "frozen", False)
            else Path(sys.base_prefix)
        )
    )
    reject_links(runtime)
    if (
        not (runtime / "python.exe").is_file()
        or runtime == agent.home
        or agent.state.is_relative_to(runtime)
    ):
        raise PolicyError(error_message)
    return runtime
