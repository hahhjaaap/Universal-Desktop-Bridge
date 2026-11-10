"""Actual local stdio/project acceptance. This is NOT deployed Cloudflare E2E."""

import hashlib
import json
import subprocess
import sys

from udb.cloud_agent import LocalProxy
from udb.config import Settings, activate
from udb.core import Agent


def body(reply):
    result = reply["result"]
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    return next(
        json.loads(block["text"])
        for block in result["content"]
        if block.get("type") == "text" and block["text"].startswith("{")
    )


def test_actual_proxy_resume_scoped_reads_owner_approval_and_cleanup(tmp_path):
    home, project = tmp_path / "home", tmp_path / "udb-room"
    project.mkdir()
    original = "# UDB fixture — kiểm thử\n"
    (project / "README.md").write_bytes(original.encode())
    (project / ".env").write_text("SYNTHETIC_PRIVATE_VALUE", encoding="utf-8")
    (tmp_path / "private.txt").write_text("SYNTHETIC_OUTSIDE_VALUE", encoding="utf-8")
    (project / "module.py").write_text("print('before')\n", encoding="utf-8")
    agent = Agent(home)
    agent.register_local("udb-room", str(project), writable=True)
    previous = activate(Settings(home=home, project_root=project))
    try:
        proxy = LocalProxy(Settings(home=home, project_root=project))
    finally:
        activate(previous)
    counter = [0]

    def call(name, **arguments):
        counter[0] += 1
        return proxy.call(
            {
                "jsonrpc": "2.0",
                "id": counter[0],
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )

    try:
        # No explicit remote initialize: this is the reconnect/resume trigger.
        catalog = proxy.call(
            {"jsonrpc": "2.0", "id": "catalog", "method": "tools/list"}
        )["result"]["tools"]
        schemas = {tool["name"]: tool["inputSchema"] for tool in catalog}
        for name in ("list_files", "read_file", "search_files", "check_python_syntax"):
            assert (
                schemas[name]["type"] == "object"
                and "project" in schemas[name]["properties"]
            )
        read = body(call("read_file", project="udb-room", path="README.md"))
        assert read == {
            "path": "README.md",
            "sha256": hashlib.sha256(original.encode()).hexdigest(),
            "text": original,
        }
        assert not call("list_files", project="udb-room")["result"].get("isError")
        assert not call("search_files", project="udb-room", text="fixture")[
            "result"
        ].get("isError")
        assert not call("check_python_syntax", project="udb-room", path="module.py")[
            "result"
        ].get("isError")
        assert call("read_file", project="udb-room", path="../private.txt")["result"][
            "isError"
        ]
        assert call("read_file", project="udb-room", path=".env")["result"]["isError"]
        before = body(call("read_file", project="udb-room", path="module.py"))
        proposed = body(
            call(
                "propose_file_write",
                project="udb-room",
                path="module.py",
                content="print('after')\n",
                expected_sha256=before["sha256"],
            )
        )
        assert proposed["status"] == "pending_local_approval"
        assert (project / "module.py").read_text() == "print('before')\n"
        # Explicit owner approval exists only in this disposable local fixture;
        # the Cloudflare udb:read route must never expose this method or writes.
        agent.decide_local(proposed["request_id"], True)
        executed = subprocess.run(
            [sys.executable, "-I", str(project / "module.py")],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert executed.returncode == 0 and executed.stdout.strip() == "after"
        backup = (
            agent.state / "backups" / (proposed["request_id"] + ".bak")
        ).read_text()
        changed = body(call("read_file", project="udb-room", path="module.py"))
        stale = call(
            "propose_file_write",
            project="udb-room",
            path="module.py",
            content="stale\n",
            expected_sha256=before["sha256"],
        )
        assert stale["result"]["isError"]
        rollback = agent.propose_write(
            "udb-room", "module.py", backup, changed["sha256"]
        )
        agent.decide_local(rollback["request_id"], True)
        assert (project / "module.py").read_text() == "print('before')\n"
        assert agent.source_autonomy_projects() == []
    finally:
        proxy.close()
    assert proxy.process.poll() is not None
    assert proxy.process.stdin.closed and proxy.process.stdout.closed
    assert not proxy.reader.is_alive()
