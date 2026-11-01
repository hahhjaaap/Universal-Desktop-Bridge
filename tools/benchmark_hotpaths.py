"""Synthetic benchmark of independent MCP backend reads and idle mailbox scans.

No tunnel, credentials, user files, desktop input or real browser is used.
Numbers describe these local fixtures only, not end-to-end ChatGPT latency.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
import time
from pathlib import Path

from udb.host_service import pending_inbox_commands
from udb.proxy import UnifiedProxy


class DelayedBackend:
    def __init__(self, name, delay):
        self.name = name
        self.delay = delay

    def request(self, method, params=None):
        time.sleep(self.delay)
        if method == "initialize":
            return {"result": {"protocolVersion": "2025-03-26", "capabilities": {}}}
        if method == "tools/list":
            return {
                "result": {
                    "tools": [
                        {
                            "name": "synthetic_" + self.name,
                            "inputSchema": {"type": "object", "properties": {}},
                        }
                    ]
                }
            }
        raise AssertionError("Unexpected synthetic RPC")


def run(samples=15, backend_delay_ms=15):
    if not 1 <= samples <= 100 or not 0 <= backend_delay_ms <= 200:
        raise ValueError("samples 1..100 and backend_delay_ms 0..200")
    delay = backend_delay_ms / 1000
    first, second = DelayedBackend("first", delay), DelayedBackend("second", delay)
    sequential_ms, parallel_ms = [], []
    for _ in range(samples):
        started = time.perf_counter()
        first.request("tools/list")
        second.request("tools/list")
        sequential_ms.append((time.perf_counter() - started) * 1000)
        proxy = UnifiedProxy(first, second)
        started = time.perf_counter()
        tools = proxy.tools_list()["tools"]
        parallel_ms.append((time.perf_counter() - started) * 1000)
        assert [tool["name"] for tool in tools] == [
            "synthetic_first",
            "synthetic_second",
        ]
    with tempfile.TemporaryDirectory(prefix="udb-idle-mailbox-") as tmp:
        folder = Path(tmp)
        rounds = samples * 150

        def measure(read):
            started = time.perf_counter()
            for _ in range(rounds):
                assert read() == []
            return 1000 * (time.perf_counter() - started) / rounds

        glob_ms = measure(lambda: sorted(folder.glob("*.json")))
        listdir_ms = measure(lambda: pending_inbox_commands(folder))
    a, b = statistics.median(sequential_ms), statistics.median(parallel_ms)
    return {
        "scope": "synthetic, no network/ChatGPT latency",
        "samples": samples,
        "backend_delay_ms": backend_delay_ms,
        "tool_discovery_sequential_median_ms": round(a, 3),
        "tool_discovery_parallel_median_ms": round(b, 3),
        "tool_discovery_ratio": round(a / max(b, 0.000001), 3),
        "empty_inbox_glob_ms_per_scan": round(glob_ms, 5),
        "empty_inbox_listdir_ms_per_scan": round(listdir_ms, 5),
        "os": os.name,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=15)
    parser.add_argument("--backend-delay-ms", type=int, default=15)
    args = parser.parse_args()
    print(json.dumps(run(args.samples, args.backend_delay_ms), indent=2))


if __name__ == "__main__":
    main()
