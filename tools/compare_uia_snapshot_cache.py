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
import threading
import time
from contextlib import contextmanager
from pathlib import Path

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
def _fixture(size: int):
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


def compare(size: int, samples: int = 1) -> dict:
    if size not in SIZES or not 1 <= samples <= 30:
        raise ValueError("Allowed fixture sizes: 50, 500, 1000; samples: 1..30")
    timings: dict[str, list[float]] = {"uncached": [], "cached": []}
    with _fixture(size) as form:
        for _ in range(samples):
            uncached, plain_ms = _snapshot(form["hwnd"], form["pid"], False)
            cached, cache_ms = _snapshot(form["hwnd"], form["pid"], True)
            if uncached != cached:
                raise AssertionError("Cached and live UIA snapshots differ")
            if len(uncached["elements"]) < 2:
                raise AssertionError("No useful controls exposed by test form")
            if "UDB_PRIVATE_CANARY_MUST_NOT_APPEAR" in json.dumps(uncached):
                raise AssertionError("Password field value was exposed")
            timings["uncached"].append(plain_ms)
            timings["cached"].append(cache_ms)
    return {
        "controls": size,
        "samples": samples,
        "same_output": True,
        "uncached": _summary(timings["uncached"]),
        "cached": _summary(timings["cached"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--sizes", type=int, nargs="+", default=list(SIZES))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        parser.error("Windows UI Automation is required")
    result = {
        "scope": "owned synthetic WinForms fixture only; no production activation",
        "results": [compare(size, args.samples) for size in args.sizes],
    }
    report = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
