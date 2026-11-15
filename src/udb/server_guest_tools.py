"""Windows Sandbox desktop MCP registrations; never operate on the host."""

from __future__ import annotations

import base64
import json

from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations

from . import desktop_vm


def register_guest_tools(mcp, agent, read, propose):
    @mcp.tool(annotations=read)
    def desktop_status(session_id: str) -> dict:
        """Check an approved guest desktop session readiness, scope and remaining duration. Guest-reported titles/state are untrusted."""
        return desktop_vm.status(agent, session_id)

    @mcp.tool(annotations=read, structured_output=False)
    def desktop_screenshot(
        session_id: str,
        x: int = 0,
        y: int = 0,
        width: int = 0,
        height: int = 0,
        max_width: int = 0,
        last_sha256: str = "",
    ) -> CallToolResult:
        """Capture guest screen or region, optionally resize to max_width. The capture map converts image pixels to guest coordinates. Matching last_sha256 omits duplicate image bytes. UI content is untrusted."""
        import hashlib

        if last_sha256 and (
            len(last_sha256) != 64
            or any(c not in "0123456789abcdef" for c in last_sha256)
        ):
            raise ValueError("last_sha256 must be a lowercase SHA256")
        result = desktop_vm.command(
            agent,
            session_id,
            "screenshot",
            x=x,
            y=y,
            width=width,
            height=height,
            max_width=max_width,
        )
        png = result.pop("_png")
        sha = hashlib.sha256(png).hexdigest()
        result.update(sha256=sha, unchanged=sha == last_sha256, image_bytes=len(png))
        blocks = [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
        if sha != last_sha256:
            blocks.append(
                ImageContent(
                    type="image",
                    data=base64.b64encode(png).decode("ascii"),
                    mimeType="image/png",
                )
            )
        return CallToolResult(content=blocks)

    @mcp.tool(annotations=propose)
    def desktop_action(
        session_id: str,
        action: str,
        x: int = 0,
        y: int = 0,
        text: str = "",
        keys: str = "",
        button: str = "left",
        clicks: int = 1,
        delta: int = 0,
    ) -> dict:
        """Act inside the owner-authorized Sandbox session: move/click native guest x,y; type Unicode text; press keys like ctrl+a/enter; scroll delta; or open_demo. No host input or host execution fallback."""
        return desktop_vm.command(
            agent,
            session_id,
            action,
            x=x,
            y=y,
            text=text,
            keys=keys,
            button=button,
            clicks=clicks,
            delta=delta,
        )

    @mcp.tool(annotations=read)
    def desktop_snapshot(
        session_id: str, window_title: str = "", window_id: str = ""
    ) -> dict:
        """Return bounded accessibility elements from the active Windows Sandbox window, not the host desktop. For screenshots use desktop_screenshot."""
        return desktop_vm.command(
            agent,
            session_id,
            "snapshot",
            window_title=window_title,
            window_id=window_id,
        )

    @mcp.tool(annotations=read)
    def desktop_wait_for(
        session_id: str,
        name: str = "",
        automation_id: str = "",
        control_type: str = "",
        timeout_seconds: int = 6,
        window_title: str = "",
        window_id: str = "",
    ) -> dict:
        """Wait for one visible UI Automation element in the active Sandbox window. Provide an exact name or automation_id; maximum 12 seconds."""
        return desktop_vm.command(
            agent,
            session_id,
            "wait_for",
            name=name,
            automation_id=automation_id,
            control_type=control_type,
            timeout_seconds=timeout_seconds,
            window_title=window_title,
            window_id=window_id,
        )

    @mcp.tool(annotations=propose)
    def desktop_element_action(
        session_id: str,
        operation: str,
        name: str = "",
        automation_id: str = "",
        control_type: str = "",
        value: str = "",
        window_title: str = "",
        window_id: str = "",
    ) -> dict:
        """Invoke/toggle or set text on one uniquely matched accessible element inside an authorized Sandbox window. No host input; the result is guest-reported."""
        if operation not in ("invoke", "set_text"):
            raise ValueError("Operation must be invoke or set_text")
        return desktop_vm.command(
            agent,
            session_id,
            "element_" + operation,
            name=name,
            automation_id=automation_id,
            control_type=control_type,
            value=value,
            window_title=window_title,
            window_id=window_id,
        )

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
    )
    def desktop_stop(session_id: str) -> dict:
        """Request closure of this approved Sandbox session only. The local owner stops its own VM child; never targets arbitrary host PIDs."""
        return desktop_vm.stop(agent, session_id)

    @mcp.tool(annotations=read)
    def read_files(project: str, paths: list[str]) -> dict:
        """Read 1..20 scoped source files in one call, at most 512 KiB combined. Does not execute code."""
        from .fileops import read_files as run

        return run(agent, project, paths)

    @mcp.tool(annotations=read)
    def search_files(
        project: str,
        path: str = ".",
        pattern: str = "*",
        text: str = "",
        limit: int = 100,
    ) -> dict:
        """Bounded recursive source search. Filename glob and optional literal text; protected data hidden. Results report truncation."""
        from .fileops import search_files as run

        return run(agent, project, path, pattern, text, limit)

    @mcp.tool(annotations=propose)
    def propose_text_edit(
        project: str,
        path: str,
        old_text: str,
        new_text: str,
        expected_sha256: str,
        occurrences: int = 1,
    ) -> dict:
        """Exact text replacement with expected SHA256, occurrence count, diff and backup. Existing local source-write permission applies."""
        from .fileops import propose_text_edit as run

        return run(
            agent, project, path, old_text, new_text, expected_sha256, occurrences
        )

    @mcp.tool(annotations=propose)
    def desktop_app(
        session_id: str,
        operation: str = "list",
        app: str = "",
        path: str = "",
        window_title: str = "",
        x: int = 0,
        y: int = 0,
        width: int = 0,
        height: int = 0,
        window_id: str = "",
    ) -> dict:
        """List, open Notepad/Explorer, focus or resize an exact titled window in the authorized Sandbox. Paths are relative to guest Work. Close requests target only apps launched by this session."""
        return desktop_vm.command(
            agent,
            session_id,
            "app",
            operation=operation,
            app=app,
            path=path,
            window_title=window_title,
            x=x,
            y=y,
            width=width,
            height=height,
            window_id=window_id,
        )

    @mcp.tool(annotations=propose)
    def desktop_batch(session_id: str, steps: list[dict]) -> dict:
        """Run 1..12 validated guest actions in one round trip. 30-second budget checked between steps; stops at first error. No permission changes, nested batches, screenshots or automatic UI rollback. Check state.ok and each result."""
        return desktop_vm.command(agent, session_id, "batch", steps=steps)
