"""Reproducible, read-only optimization benchmarks on disposable fixtures.

No owner homes, Cloudflare, Windows grants, external programs or network calls.
Speed ratios are informational; regression tests guard correctness.
"""

import hashlib
import json
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path

from udb import activity, build
from udb.sandbox_refresh_cache import SandboxRestartCache


def measure(operation, *, runs=3):
    elapsed = []
    allocations = []
    result = None
    for _ in range(runs):
        tracemalloc.start()
        start = time.perf_counter()
        try:
            result = operation()
            elapsed.append(time.perf_counter() - start)
            allocations.append(tracemalloc.get_traced_memory()[1])
        finally:
            tracemalloc.stop()
    return {
        "median_ms": round(statistics.median(elapsed) * 1000, 3),
        "peak_tracemalloc_bytes": max(allocations),
    }, result


def main():
    with tempfile.TemporaryDirectory(prefix="udb-opt-synthetic-") as folder:
        root = Path(folder)
        artifact = root / "fixture.bin"
        block = b"UDB-benchmark" * 81920
        with artifact.open("wb") as stream:
            for _ in range(32):
                stream.write(block)
        size = artifact.stat().st_size
        legacy_hash, expected = measure(
            lambda: hashlib.sha256(artifact.read_bytes()).hexdigest()
        )
        streamed_hash, actual = measure(lambda: build.stream_sha256(artifact))
        assert actual == expected

        state = root / "sandbox-setup-result.json"
        state.write_text('{"RestartNeeded": true}', encoding="utf-8")
        cache = SandboxRestartCache()

        def old_poll():
            for _ in range(400):
                json.loads(state.read_text("utf-8-sig")).get("RestartNeeded")

        def new_poll():
            for _ in range(400):
                assert cache.read(state)

        old_refresh, _ = measure(old_poll)
        new_refresh, _ = measure(new_poll)

        secret = "sk-" + "x" * (8 * 1024 * 1024)
        metadata_cost, safe = measure(lambda: activity.clean(secret), runs=3)
        assert safe == "[oversized metadata]"
        print(
            json.dumps(
                {
                    "scope": "synthetic build, log and non-security GUI hint only",
                    "source_bytes": size,
                    "hash_old": legacy_hash,
                    "hash_streamed": streamed_hash,
                    "restart_hint_uncached_400_polls": old_refresh,
                    "restart_hint_cached_400_polls": new_refresh,
                    "oversized_log_metadata": metadata_cost,
                    "notes": (
                        "Synthetic timings do not predict Windows startup, "
                        "ChatGPT latency, security checks or actual agent CPU use."
                    ),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
