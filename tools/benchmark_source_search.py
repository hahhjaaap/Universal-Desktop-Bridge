"""Synthetic performance check for source discovery; no user projects or grants."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

from udb.core import Agent
from udb.fileops import search_files


def run(samples: int = 3) -> dict:
    if not 1 <= samples <= 20:
        raise ValueError("Samples must be 1..20")
    with tempfile.TemporaryDirectory(prefix="udb-source-search-benchmark-") as tmp:
        base = Path(tmp)
        root = base / "synthetic-source-only"
        root.mkdir()
        for n in range(250):
            (root / f"artifact-{n:04}.bin").write_bytes(b"not source")
        for n in range(20):
            (root / f"source-{n:03}.py").write_text(
                "print('synthetic')\n", encoding="utf-8"
            )
        for n in range(20):
            (root / f"note-{n:03}.md").write_text("synthetic\n", encoding="utf-8")
        agent = Agent(base / "config")
        agent.register_local("synthetic", str(root), False)
        original_path = agent.path
        timings = []
        path_checks = []
        for _ in range(samples):
            calls = [0]

            def counted_path(project, path=".", write=False, counter=calls):
                counter[0] += 1
                return original_path(project, path, write=write)

            agent.path = counted_path
            start = time.perf_counter()
            result = search_files(agent, "synthetic", pattern="*.py", limit=200)
            elapsed_ms = (time.perf_counter() - start) * 1000
            if len(result["items"]) != 20 or result["scanned"] != 290:
                raise RuntimeError("Synthetic search returned unexpected results")
            if result["truncated"]:
                raise RuntimeError("Synthetic search hit a resource cap")
            timings.append(round(elapsed_ms, 3))
            path_checks.append(calls[0])
        return {
            "scope": "synthetic, local files only; excludes ChatGPT/network latency",
            "samples": samples,
            "files_scanned": 290,
            "matching_source_files": 20,
            "path_checks": path_checks,
            "times_ms": timings,
            "median_ms": round(statistics.median(timings), 3),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(run(args.samples), indent=2))


if __name__ == "__main__":
    main()
