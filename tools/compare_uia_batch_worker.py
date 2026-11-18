"""Read-only Windows UIA batch worker parity and startup-cost canary.

Uses a test-owned WinForms HWND/PID only. Never sends input, touches personal
windows, reads credentials, enables a user setting or claims end-to-end speed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from tools.compare_uia_snapshot_cache import (
    HELPER,
    _fixture,
    _powershell,
    _snapshot,
    percentile,
)
from udb.uia_worker import PersistentUIA


def compare(samples: int = 3, controls: int = 50) -> dict:
    if type(samples) is not int or not 1 <= samples <= 10:
        raise ValueError("Samples must be 1..10")
    if controls not in (50, 500, 1000):
        raise ValueError("Use one of the isolated 50/500/1000-control fixtures")

    original = os.environ.get("UDB_UIA_SNAPSHOT_CACHE")
    os.environ["UDB_UIA_SNAPSHOT_CACHE"] = "0"
    direct_ms = []
    reusable_ms = []
    try:
        with _fixture(controls) as form:
            with_worker = PersistentUIA(_powershell(), HELPER)
            try:
                for _ in range(samples):
                    request = {
                        "mode": "snapshot",
                        "hwnd": form["hwnd"],
                        "pid": form["pid"],
                    }
                    one_shot, elapsed = _snapshot(
                        form["hwnd"], form["pid"], cached=False
                    )
                    direct_ms.append(round(elapsed, 2))
                    started = time.perf_counter()
                    reuse = with_worker.call(request, timeout=18)
                    reusable_ms.append(round((time.perf_counter() - started) * 1000, 2))
                    if reuse != one_shot:
                        raise AssertionError("Batch-local UIA worker snapshot mismatch")
                    if len(reuse.get("elements", [])) < 2:
                        raise AssertionError("Synthetic fixture controls were not observed")
                    if "UDB_PRIVATE_CANARY_MUST_NOT_APPEAR" in json.dumps(reuse):
                        raise AssertionError("UIA snapshot leaked password sentinel")
            finally:
                with_worker.close()
    finally:
        if original is None:
            os.environ.pop("UDB_UIA_SNAPSHOT_CACHE", None)
        else:
            os.environ["UDB_UIA_SNAPSHOT_CACHE"] = original

    return {
        "scope": "test-owned static WinForms fixture only",
        "controls": controls,
        "samples": samples,
        "same_output": True,
        "cold_start_included_ms": reusable_ms[0],
        "one_shot_p50_ms": percentile(direct_ms, 0.5),
        "persistent_p50_including_cold_ms": percentile(reusable_ms, 0.5),
        "persistent_warm_p50_ms": (
            percentile(reusable_ms[1:], 0.5) if samples > 1 else None
        ),
        "one_shot_times_ms": direct_ms,
        "persistent_times_ms": reusable_ms,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--controls", type=int, default=50)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        parser.error("Windows UI Automation is required")
    report = compare(args.samples, args.controls)
    output = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
