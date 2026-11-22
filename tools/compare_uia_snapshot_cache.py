"""Read-only UIA cache parity canary on an isolated Windows Forms fixture.

Results do not measure Chrome, user windows, or end-to-end computer-use speed.
Never enable UDB_UIA_SNAPSHOT_CACHE for users based only on this fixture.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "uia_snapshot_form.ps1"
HELPER = ROOT / "src" / "udb" / "computer_uia.ps1"
SIZES = (50, 500, 1000)


def _powershell() -> Path:
    return (
        Path(os.environ["SystemRoot"])
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )


def _flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _read_ready(proc: subprocess.Popen[bytes], timeout: float) -> dict:
    lines: queue.Queue[bytes] = queue.Queue(maxsize=1)
    threading.Thread(
        target=lambda: lines.put(proc.stdout.readline()), daemon=True
    ).start()
    try:
        line = lines.get(timeout=timeout)
        reply = json.loads(line.decode("utf-8-sig"))
    except (queue.Empty, ValueError, UnicodeError) as exc:
        raise RuntimeError("Test form did not report readiness") from exc
    if (
        not isinstance(reply, dict)
        or reply.get("event") != "ready"
        or reply.get("pid") != proc.pid
        or type(reply.get("hwnd")) is not int
        or reply["hwnd"] <= 0
    ):
        raise RuntimeError("Unexpected test form identity")
    return reply


@contextmanager
def _fixture(size: int, *, dynamic_signal_path: Path | None = None):
    proc = subprocess.Popen(
        [
            str(_powershell()),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Sta",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(FIXTURE),
            "-Controls",
            str(size),
            *(
                ["-DynamicSignalPath", str(dynamic_signal_path)]
                if dynamic_signal_path is not None
                else []
            ),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=_flags(),
        shell=False,
    )
    try:
        yield _read_ready(proc, timeout=60)
    finally:
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=8)
        proc.stdout.close()


def _snapshot(hwnd: int, pid: int, cached: bool) -> tuple[dict, float]:
    env = dict(os.environ, UDB_UIA_SNAPSHOT_CACHE="1" if cached else "0")
    started = time.perf_counter()
    run = subprocess.run(
        [
            str(_powershell()),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Sta",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(HELPER),
        ],
        input=json.dumps({"mode": "snapshot", "hwnd": hwnd, "pid": pid}),
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=45,
        creationflags=_flags(),
        shell=False,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    try:
        reply = json.loads(run.stdout.lstrip("\ufeff"))
    except (ValueError, UnicodeError) as exc:
        raise RuntimeError("Snapshot returned malformed JSON") from exc
    if run.returncode != 0 or reply.get("ok") is not True:
        raise RuntimeError("Snapshot UIA request failed")
    return reply, elapsed_ms


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 2)


def _summary(values: list[float]) -> dict:
    return {
        f"p{p}_ms": percentile(values, q)
        for p, q in ((50, 0.5), (95, 0.95), (99, 0.99))
    }


def _validate(size: int, samples: int) -> None:
    if size not in SIZES or not 1 <= samples <= 30:
        raise ValueError("Allowed fixture sizes: 50, 500, 1000; samples: 1..30")


def _check_pair(uncached: dict, cached: dict) -> None:
    if uncached != cached:
        raise AssertionError("Cached and live UIA snapshots differ")
    if uncached.get("ok") is not True or len(uncached.get("elements", [])) < 2:
        raise AssertionError("No useful controls exposed by test form")
    if "UDB_PRIVATE_CANARY_MUST_NOT_APPEAR" in json.dumps(uncached):
        raise AssertionError("Password field value was exposed")


def compare(size: int, samples: int = 1) -> dict:
    _validate(size, samples)
    timings: dict[str, list[float]] = {"uncached": [], "cached": []}
    with _fixture(size) as form:
        for _ in range(samples):
            uncached, plain_ms = _snapshot(form["hwnd"], form["pid"], False)
            cached, cache_ms = _snapshot(form["hwnd"], form["pid"], True)
            _check_pair(uncached, cached)
            timings["uncached"].append(plain_ms)
            timings["cached"].append(cache_ms)
    return {
        "controls": size,
        "samples": samples,
        "same_output": True,
        "uncached": _summary(timings["uncached"]),
        "cached": _summary(timings["cached"]),
    }


def compare_warm(size: int, samples: int, *, worker_factory=None) -> dict:
    """Compare cache modes after one cold request per private test worker."""
    _validate(size, samples)
    if worker_factory is None:
        from udb.uia_worker import PersistentUIA

        worker_factory = PersistentUIA

    modes = ("uncached", "cached")
    timings: dict[str, list[float]] = {mode: [] for mode in modes}
    cold = {}
    processes = {}
    truncated_samples = 0
    with _fixture(size) as form, ExitStack() as cleanup:
        request = {"mode": "snapshot", "hwnd": form["hwnd"], "pid": form["pid"]}
        workers = {}
        executable = _powershell()
        for mode in modes:
            worker = worker_factory(executable, HELPER)
            cleanup.callback(worker.close)
            workers[mode] = worker
        for index in range(samples + 1):
            replies = {}
            for mode in modes if index % 2 == 0 else reversed(modes):
                worker = workers[mode]
                with patch.dict(
                    os.environ, UDB_UIA_SNAPSHOT_CACHE="1" if mode == "cached" else "0"
                ):
                    started = time.perf_counter()
                    replies[mode] = worker.call(request, timeout=18)
                    elapsed = (time.perf_counter() - started) * 1000
                if index == 0:
                    processes[mode] = worker._process
                    cold[mode] = round(elapsed, 2)
                else:
                    if worker._process is not processes[mode]:
                        raise AssertionError("UIA worker restarted during warm samples")
                    timings[mode].append(elapsed)
            _check_pair(replies["uncached"], replies["cached"])
            if index:
                truncated_samples += replies["uncached"].get("truncated") is True
    return {
        "controls": size,
        "samples": samples,
        "same_output": True,
        "cold_ms": cold,
        "truncated_samples": truncated_samples,
        **{mode: _summary(timings[mode]) for mode in modes},
    }



def _check_dynamic_transition(before: dict, after: dict) -> None:
    """Require a persistent worker to observe a changed UIA Name on its next request."""
    before_text = json.dumps(before, ensure_ascii=True)
    after_text = json.dumps(after, ensure_ascii=True)
    if "UDB_DYNAMIC_BEFORE" not in before_text:
        raise AssertionError("Initial dynamic UIA control was not observed")
    if "UDB_DYNAMIC_AFTER" not in after_text:
        raise AssertionError("Updated dynamic UIA control was not observed")
    if "UDB_DYNAMIC_BEFORE" in after_text:
        raise AssertionError("Persistent UIA worker returned a stale control value")
    if before == after:
        raise AssertionError("Dynamic UIA snapshot did not change")


def compare_dynamic_warm(size: int, samples: int = 10, *, worker_factory=None) -> dict:
    """Verify cached/live parity after a control changes in a test-owned WinForms window."""
    _validate(size, samples)
    if worker_factory is None:
        from udb.uia_worker import PersistentUIA

        worker_factory = PersistentUIA

    modes = ("uncached", "cached")
    timings: dict[str, list[float]] = {mode: [] for mode in modes}
    cold = {}
    processes = {}
    truncated_samples = 0

    with tempfile.TemporaryDirectory(prefix="udb-uia-dynamic-") as folder:
        signal = Path(folder) / "changed.json"
        with _fixture(size, dynamic_signal_path=signal) as form, ExitStack() as cleanup:
            request = {"mode": "snapshot", "hwnd": form["hwnd"], "pid": form["pid"]}
            workers = {}
            executable = _powershell()
            for mode in modes:
                worker = worker_factory(executable, HELPER)
                cleanup.callback(worker.close)
                workers[mode] = worker

            before = {}
            for mode in modes:
                worker = workers[mode]
                with patch.dict(
                    os.environ,
                    UDB_UIA_SNAPSHOT_CACHE="1" if mode == "cached" else "0",
                ):
                    started = time.perf_counter()
                    before[mode] = worker.call(request, timeout=18)
                    cold[mode] = round((time.perf_counter() - started) * 1000, 2)
                processes[mode] = worker._process
            _check_pair(before["uncached"], before["cached"])
            if "UDB_DYNAMIC_BEFORE" not in json.dumps(before["uncached"], ensure_ascii=True):
                raise AssertionError("Initial dynamic UIA control was not observed")

            deadline = time.monotonic() + 12
            while not signal.is_file() and time.monotonic() < deadline:
                time.sleep(0.05)
            if not signal.is_file():
                raise RuntimeError("Dynamic WinForms fixture did not signal its change")

            for index in range(samples):
                current = {}
                order = modes if index % 2 == 0 else tuple(reversed(modes))
                for mode in order:
                    worker = workers[mode]
                    with patch.dict(
                        os.environ,
                        UDB_UIA_SNAPSHOT_CACHE="1" if mode == "cached" else "0",
                    ):
                        started = time.perf_counter()
                        current[mode] = worker.call(request, timeout=18)
                        timings[mode].append((time.perf_counter() - started) * 1000)
                    if worker._process is not processes[mode]:
                        raise AssertionError("UIA worker restarted during dynamic warm samples")
                _check_pair(current["uncached"], current["cached"])
                _check_dynamic_transition(before["uncached"], current["uncached"])
                if current["uncached"].get("truncated") is True:
                    truncated_samples += 1

    return {
        "controls": size,
        "samples": samples,
        "same_output": True,
        "dynamic_change_observed": True,
        "workers_reused": True,
        "cold_ms": cold,
        "truncated_samples": truncated_samples,
        **{mode: _summary(timings[mode]) for mode in modes},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--sizes", type=int, nargs="+", default=list(SIZES))
    parser.add_argument("--warm", action="store_true")
    parser.add_argument("--dynamic-warm", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        parser.error("Windows UI Automation is required")
    run = compare_dynamic_warm if args.dynamic_warm else compare_warm if args.warm else compare
    result = {
        "scope": "owned synthetic WinForms fixture only; no production activation",
        "measurement": "dynamic warm worker" if args.dynamic_warm else "warm worker" if args.warm else "one-shot",
        "results": [run(size, args.samples) for size in args.sizes],
    }
    report = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
