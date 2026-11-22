"""Compare opt-in UIA event waits with the bounded polling fallback.

This canary uses only a test-owned WinForms window. It does not attach to a
user desktop or enable the observer for normal UDB sessions.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

from tools.compare_uia_snapshot_cache import (
    HELPER,
    _fixture,
    _powershell,
    percentile,
)
from udb.uia_worker import PersistentUIA


def _run_wait(event_observer: bool, wait_ms: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="udb-uia-event-") as directory:
        root = Path(directory)
        signal = root / "mutation.json"
        trigger = root / "trigger"
        with _fixture(
            50,
            dynamic_signal_path=signal,
            dynamic_trigger_path=trigger,
            dynamic_mutation="replace",
        ) as form:
            worker = PersistentUIA(_powershell(), HELPER)
            timer = threading.Timer(
                0.25, lambda: trigger.write_text("go", encoding="utf-8")
            )
            timer.start()
            started = time.perf_counter()
            try:
                reply = worker.call(
                    {
                        "hwnd": form["hwnd"],
                        "pid": form["pid"],
                        "mode": "wait_for",
                        "automation_id": "FixtureDynamicReplacement",
                        "condition": "exists",
                        "wait_ms": wait_ms,
                        "event_observer": event_observer,
                    },
                    timeout=7 + wait_ms / 1000,
                    cancel_check=lambda: None,
                )
                elapsed_ms = (time.perf_counter() - started) * 1000
                if reply.get("ok") is not True or reply.get("matched") is not True:
                    raise AssertionError("wait_for did not observe the replacement")
                if reply.get("observer_cleanup") is not True:
                    raise AssertionError("UIA event handler was not detached")
                if event_observer:
                    if reply.get("observer_mode") != "event":
                        raise AssertionError("UIA event registration fell back to polling")
                    if reply.get("observer_signals", 0) < 1:
                        raise AssertionError("UIA structure event did not wake the wait")
                elif (
                    reply.get("observer_mode") != "polling"
                    or reply.get("observer_signals") != 0
                ):
                    raise AssertionError("Polling fallback unexpectedly subscribed")
                if not signal.exists():
                    raise AssertionError("WinForms fixture did not complete its mutation")

                timeout_reply = worker.call(
                    {
                        "hwnd": form["hwnd"],
                        "pid": form["pid"],
                        "mode": "wait_for",
                        "automation_id": "UDB_EVENT_TIMEOUT_SENTINEL",
                        "condition": "exists",
                        "wait_ms": 250,
                        "event_observer": True,
                    },
                    timeout=7.25,
                    cancel_check=lambda: None,
                )
                if (
                    timeout_reply.get("timed_out") is not True
                    or timeout_reply.get("observer_mode") != "event"
                    or timeout_reply.get("observer_cleanup") is not True
                ):
                    raise AssertionError("Timed-out UIA observer did not clean up")
            finally:
                timer.join(timeout=3)
                worker.close()
            return {
                "mode": "event" if event_observer else "polling",
                "elapsed_ms": round(elapsed_ms, 2),
                "helper_elapsed_ms": reply.get("elapsed_ms"),
                "observer_signals": reply.get("observer_signals", 0),
                "timeout_cleanup": timeout_reply.get("observer_cleanup") is True,
            }


def _summary(rows: list[dict]) -> dict:
    values = [row["elapsed_ms"] for row in rows]
    return {
        "samples": len(values),
        "p50_ms": percentile(values, 0.50),
        "p95_ms": percentile(values, 0.95),
        "p99_ms": percentile(values, 0.99),
        "observer_signals": sum(row["observer_signals"] for row in rows),
        "timeout_cleanups": sum(row["timeout_cleanup"] for row in rows),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--wait-ms", type=int, default=3000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        parser.error("Windows UI Automation is required")
    if type(args.samples) is not int or not 1 <= args.samples <= 10:
        parser.error("--samples must be between 1 and 10")
    if type(args.wait_ms) is not int or not 500 <= args.wait_ms <= 10000:
        parser.error("--wait-ms must be between 500 and 10000")

    rows = {
        "event": [_run_wait(True, args.wait_ms) for _ in range(args.samples)],
        "polling": [_run_wait(False, args.wait_ms) for _ in range(args.samples)],
    }
    report = {
        "scope": "test-owned WinForms fixture only; no production activation",
        "event_observer_default": "off",
        "samples_per_mode": args.samples,
        "results": {mode: _summary(samples) for mode, samples in rows.items()},
        "timeout_cleanup_verified": all(
            row["timeout_cleanup"] for samples in rows.values() for row in samples
        ),
        "interpretation": (
            "Event mode is opt-in and uses a bounded structure subscription. "
            "Polling remains the fallback and rechecks the same condition/deadline. "
            "No latency result here represents a user application or end-to-end RPC."
        ),
    }
    wire = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(wire + "\n", encoding="utf-8")
    print(wire)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
