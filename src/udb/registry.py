"""Discover public tool schemas from their implementations, not hard-coded counts."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from .catalog import public_catalog
from .tool_policy import validate_tool_policy


def catalog() -> dict[str, Any]:
    """Build the public schema and report the actual backend tool counts."""
    from .companion.dispatch import validate_catalog
    from .companion.runtime import TOOLS
    from .core import Agent
    from .server import make_server

    validate_catalog()

    with tempfile.TemporaryDirectory(prefix="udb-catalog-") as temporary_root:
        server = make_server(Agent(Path(temporary_root)))
        native_tools = [
            tool.model_dump(mode="json", exclude_none=True)
            for tool in asyncio.run(server.list_tools())
        ]

    core_route = object()
    companion_route = object()
    routes = {tool["name"]: core_route for tool in native_tools}
    routes.update({tool["name"]: companion_route for tool in TOOLS})

    public_tools = public_catalog([*native_tools, *TOOLS], routes)
    # Fail the build if any public tool is missing a reviewed access policy.
    validate_tool_policy(public_tools)
    return {
        "tools": public_tools,
        "tool_count": len(public_tools),
        "backend_count": len(native_tools) + len(TOOLS),
        "core_count": len(native_tools),
        "companion_count": len(TOOLS),
    }
