"""Windows-only UDB PowerShell UIA process/IPC benchmark using a rejected HWND.

An impossible HWND/PID pair is deliberately refused before a UIA tree is read.
Results do not measure actual applications, desktop inputs, network, or AI time.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def percentile_ms(samples: list[float], q: float) -> float:
    ordered = sorted(samples)
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 3)


def summary(values: list[float]) -> dict[str, float]:
    return {
        "p50_ms": percentile_ms(values, 0.5),
        "p95_ms": percentile_ms(values, 0.95),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=30)
    options = parser.parse_args(argv)
    if not 5 <= options.samples <= 100:
        parser.error("--samples must be between 5 and 100")
    if sys.platform != "win32":
        parser.error("Windows PowerShell and UIAutomation are required")

    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo / "src"))
    from udb.uia_worker import PersistentUIA

    exe = (
        Path(os.environ["SystemRoot"])
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    helper = repo / "src/udb/computer_uia.ps1"
    request = {"hwnd": 0, "pid": -1, "mode": "snapshot"}
    wire = json.dumps(request, separators=(",", ":"))
    oneshot: list[float] = []
    for _ in range(options.samples):
        started = time.perf_counter()
        result = subprocess.run(
            [
                str(exe),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Sta",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(helper),
            ],
            input=wire,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            shell=False,
        )
        oneshot.append((time.perf_counter() - started) * 1000)
        reply = json.loads(result.stdout.lstrip("\ufeff"))
        if result.returncode != 1 or reply["ok"] is not False:
            raise RuntimeError("One-shot UIA did not reject impossible HWND")

    worker = PersistentUIA(exe, helper)
    try:
        started = time.perf_counter()
        if worker.call(request, timeout=15)["ok"] is not False:
            raise RuntimeError("Persistent UIA did not reject impossible HWND")
        cold_ms = round((time.perf_counter() - started) * 1000, 3)
        warm: list[float] = []
        for _ in range(options.samples):
            started = time.perf_counter()
            if worker.call(request, timeout=15)["ok"] is not False:
                raise RuntimeError("Persistent UIA did not reject impossible HWND")
            warm.append((time.perf_counter() - started) * 1000)
    finally:
        worker.close()

    print(
        json.dumps(
            {
                "scope": "rejected HWND/PID process+IPC only; no real UIA or network",
                "samples": options.samples,
                "one_shot": summary(oneshot),
                "persistent_first_call_ms": cold_ms,
                "persistent_warm": summary(warm),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
