"""Compare real Windows builds using disposable state, without owner grants.

Every sample starts a new process. OS/AV caches are uncontrolled; this is not
a clean-boot or user-machine benchmark. No stdout, paths or secrets are logged.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import queue
import statistics
import subprocess
import tempfile
import threading
import time
from pathlib import Path

PROBES = {
    "version": ["--version"],
    "identity": ["version", "--json"],
    "status": ["status", "--json", "--wait", "0"],
    "doctor": ["doctor", "--json", "--wait", "0"],
}


def summary(samples):
    ordered = sorted(samples)
    return {
        "samples_ms": [round(value, 3) for value in samples],
        "first_launch_ms": round(samples[0], 3),
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)], 3),
    }


def environment(root):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("_PYI_")
        and key
        not in {
            "PYTHONPATH",
            "PYTHONHOME",
            "PYTHONUSERBASE",
            "VIRTUAL_ENV",
            "CONDA_PREFIX",
            "UDB_HOME",
            "_MEIPASS2",
            "CONTROL_PLANE_API_KEY",
            "TUNNEL_CLIENT_PROFILE_DIR",
        }
    }
    env.update(
        PYINSTALLER_RESET_ENVIRONMENT="1",
        PYTHONIOENCODING="utf-8",
        TEMP=str(root),
        TMP=str(root),
    )
    return env


def cli_probe(exe, arguments, env, root):
    started = time.perf_counter()
    result = subprocess.run(
        [str(exe), "--home", str(root / "home"), *arguments],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        stdin=subprocess.DEVNULL,
    )
    elapsed = (time.perf_counter() - started) * 1000
    # An unconfigured disposable home is correctly unhealthy; never start it.
    expected = 2 if arguments[0] in ("status", "doctor") else 0
    if result.returncode != expected:
        raise RuntimeError("Packaged CLI probe failed; inspect the build separately")
    if arguments[0] in ("status", "doctor"):
        value = json.loads(result.stdout)
        if value.get("manager_running") is not False:
            raise RuntimeError("Benchmark unexpectedly found a running manager")
    return elapsed, result.stdout


def mcp_probe(exe, env, root):
    home, project = root / "mcp-home", root / "project"
    home.mkdir()
    project.mkdir()
    started = time.perf_counter()
    process = subprocess.Popen(
        [str(exe), "--home", str(home), "--root", str(project), "serve"],
        cwd=root,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )
    replies = queue.Queue(maxsize=8)

    def read():
        try:
            while line := process.stdout.readline(2097153):
                if len(line) > 2097152 or not line.endswith(b"\n"):
                    break
                replies.put_nowait(json.loads(line))
        except (OSError, ValueError, queue.Full):
            pass
        finally:
            try:
                replies.put_nowait(None)
            except queue.Full:
                pass

    reader = threading.Thread(target=read, daemon=True)
    reader.start()

    def rpc(ident, method, params):
        process.stdin.write(
            (
                json.dumps(dict(jsonrpc="2.0", id=ident, method=method, params=params))
                + "\n"
            ).encode()
        )
        process.stdin.flush()
        try:
            answer = replies.get(timeout=120)
        except queue.Empty:
            raise RuntimeError(
                "Packaged MCP startup timed out; no call was retried"
            ) from None
        if (
            not isinstance(answer, dict)
            or answer.get("jsonrpc") != "2.0"
            or answer.get("id") != ident
            or "error" in answer
            or "result" not in answer
        ):
            raise RuntimeError("Packaged MCP probe failed; no call was retried")
        return answer["result"]

    try:
        rpc(
            1,
            "initialize",
            dict(
                protocolVersion="2025-11-25",
                capabilities={},
                clientInfo=dict(name="udb-startup-benchmark", version="1"),
            ),
        )
        initialized = (time.perf_counter() - started) * 1000
        process.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        process.stdin.flush()
        tools = rpc(2, "tools/list", {})["tools"]
        if len(tools) != 36:
            raise RuntimeError("Packaged tool catalog changed")
        discovered = (time.perf_counter() - started) * 1000
        status = rpc(3, "tools/call", {"name": "bridge_status", "arguments": {}})
        value = status.get("structuredContent")
        if not isinstance(value, dict):
            value = next(
                json.loads(block["text"])
                for block in status.get("content", [])
                if block.get("type") == "text" and block.get("text", "").startswith("{")
            )
        if value["computer_access"]["enabled"] or value["host_background"]["enabled"]:
            raise RuntimeError("Disposable benchmark unexpectedly has host grants")
        return dict(
            initialize_ms=round(initialized, 3),
            discovery_ms=round(discovered, 3),
            tool_count=len(tools),
            permission_probe_passed=True,
        )
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        process.stdout.close()
        reader.join(timeout=1)


def compare(onefile, onedir, *, samples=5):
    if not 3 <= samples <= 20:
        raise ValueError("samples must be 3..20")
    executables = {"onefile": Path(onefile).resolve(), "onedir": Path(onedir).resolve()}
    if not all(path.is_file() for path in executables.values()):
        raise ValueError("Both built executables are required")
    result = dict(
        scope="Fresh processes on one Windows runner; OS/AV caches uncontrolled",
        platform=platform.platform(),
        grants_changed=False,
        layouts={},
    )
    with tempfile.TemporaryDirectory(prefix="udb-startup-") as temporary:
        root = Path(temporary)
        histories = {layout: {name: [] for name in PROBES} for layout in executables}
        for layout in executables:
            (root / layout).mkdir()
        for index in range(samples):
            # Alternate order to reduce systematic cache/runner-load bias.
            layouts = (
                list(executables) if index % 2 == 0 else list(reversed(executables))
            )
            for name, arguments in PROBES.items():
                for layout in layouts:
                    elapsed, output = cli_probe(
                        executables[layout],
                        arguments,
                        environment(root / layout),
                        root / layout,
                    )
                    histories[layout][name].append(elapsed)
                    if name == "identity":
                        identity = json.loads(output)
                        if (
                            identity.get("build_layout") != layout
                            or identity.get("source_dirty") is not False
                            or not identity.get("source_revision")
                        ):
                            raise RuntimeError(
                                "Benchmark requires clean revision-identified builds"
                            )
                        result["layouts"].setdefault(layout, {})["build"] = identity
        revisions = {
            row["build"]["source_revision"] for row in result["layouts"].values()
        }
        if len(revisions) != 1:
            raise RuntimeError("Compare builds from the same source revision")
        for layout, executable in executables.items():
            result["layouts"][layout]["cli"] = {
                name: summary(values) for name, values in histories[layout].items()
            }
            result["layouts"][layout]["mcp"] = mcp_probe(
                executable, environment(root / layout), root / layout
            )
            if (root / layout / "home").exists():
                raise RuntimeError("Read-only CLI probes created owner state")
        result["p50_speedup"] = {
            name: round(
                statistics.median(histories["onefile"][name])
                / max(0.001, statistics.median(histories["onedir"][name])),
                3,
            )
            for name in PROBES
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onefile", type=Path, required=True)
    parser.add_argument("--onedir", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Run packaged startup comparisons on Windows")
    value = compare(args.onefile, args.onedir, samples=args.samples)
    text = json.dumps(value, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
