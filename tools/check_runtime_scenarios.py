"""Windows scenario acceptance using owned fixtures and existing local access."""

from __future__ import annotations

import argparse
import base64
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from udb.core import Agent
from udb.host_client import command as host_command
from udb.host_client import status as host_status
from udb.launcher import child_environment, worker_command


def _wait_for_fixture_host(agent, process, session_id, *, timeout=12):
    """Wait for the *read-only* host heartbeat after QA browser publication.

    fixture-ready.json confirms CDP setup, not necessarily that the monitor's
    status heartbeat has become visible. Do not retry any browser mutation:
    only poll the host status for this disposable session.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Disposable browser worker exited before host readiness")
        state = host_status(agent)
        if (
            state.get("worker_ready") is True
            and state.get("enabled") is True
            and any(
                row.get("session_id") == session_id and row.get("kind") == "browser"
                for row in state.get("sessions", [])
            )
        ):
            return
        time.sleep(0.1)
    raise RuntimeError("Disposable browser worker heartbeat did not become ready")


def _browser_postcondition_ab(agent, args, *, trials=5):
    """Time both FastPath variants on one warm Windows browser and mailbox."""
    if not 1 <= trials <= 50:
        raise ValueError("Browser A/B trials must be between 1 and 50")
    windows_ms = {"legacy": [], "postcondition": []}
    page = 1
    for trial in range(trials):
        for guarded in (False, True) if trial % 2 == 0 else (True, False):
            mode = "postcondition" if guarded else "legacy"
            steps = []
            for _ in range(5):
                page += 1
                step = {"action": "click", "selector": "#next"}
                if guarded:
                    step["click_postcondition"] = {
                        "selector": "#page",
                        "text": f"Page {page}",
                    }
                steps.append(step)
            steps.append(
                {
                    "action": "wait_for",
                    "selector": "#page",
                    "state": "text",
                    "value": f"Page {page}",
                }
            )
            started = time.perf_counter()
            result = host_command(
                agent,
                "browser",
                action="fastpath",
                request_id=f"ab-{mode}-{trial}",
                steps=steps,
                **args,
            )
            windows_ms[mode].append(round((time.perf_counter() - started) * 1000, 2))
            assert result["ok"] and result["completed_steps"] == len(steps), result
    # Nearest-rank p95 is meaningful for the opt-in 50-trial acceptance run.
    p95_ms = {
        mode: sorted(values)[(95 * len(values) + 99) // 100 - 1]
        for mode, values in windows_ms.items()
    }
    return {
        "scope": "Windows host mailbox and owned Chrome, warm session",
        "clicks_per_batch": 5,
        "samples_per_variant": trials,
        "median_ms": {
            mode: statistics.median(values) for mode, values in windows_ms.items()
        },
        "p95_ms": p95_ms,
        "p95_reduction_percent": round(
            100 * (1 - p95_ms["postcondition"] / p95_ms["legacy"]), 2
        ) if p95_ms["legacy"] > 0 else None,
        "samples_ms": windows_ms,
    }


def browser_fixture(*, ab_trials=5):
    with tempfile.TemporaryDirectory(prefix="udb-hostqa-") as directory:
        home = Path(directory).resolve()
        (home / "QA-ISOLATED").write_text("Disposable browser fixture")
        with (home / "worker.log").open("wb") as log:
            process = subprocess.Popen(
                worker_command("core", ["--home", str(home), "--host-engine-qa"]),
                env=child_environment(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                ready = home / "fixture-ready.json"
                deadline = time.monotonic() + 75
                while not ready.exists():
                    if process.poll() is not None or time.monotonic() > deadline:
                        details = (home / "worker.log").read_text(
                            encoding="utf-8", errors="replace"
                        )[-6000:]
                        raise RuntimeError(
                            "Disposable browser fixture did not start "
                            f"(exit={process.poll()}):\n{details}"
                        )
                    time.sleep(0.1)
                issued = json.loads(ready.read_text())
                agent = Agent(home)
                args = dict(session_id=issued["session_id"], tab_id=issued["tab_id"])
                _wait_for_fixture_host(agent, process, args["session_id"])
                row = host_command(agent, "browser", action="read", **args)
                assert row["title"] == "UDB owned fixture"
                value = "UDB Unicode kiểm thử"
                assert host_command(
                    agent,
                    "browser",
                    action="fill",
                    selector="#name",
                    value=value,
                    **args,
                )["ok"]
                assert host_command(
                    agent, "browser", action="click", selector="#confirm", **args
                )["ok"]
                assert (
                    value
                    in host_command(agent, "browser", action="read", **args)["text"]
                )
                selected = host_command(
                    agent,
                    "browser",
                    action="select_option",
                    selector="#choice",
                    value="VN",
                    **args,
                )
                assert selected["ok"] and selected["value"] == "VN"
                assert host_command(
                    agent,
                    "browser",
                    action="fill",
                    selector="#choice",
                    value="",
                    **args,
                )["ok"]
                for selector, error in (
                    ("#disabled", "disabled"),
                    ("#readonly", "readonly"),
                ):
                    result = host_command(
                        agent,
                        "browser",
                        action="fill",
                        selector=selector,
                        value="changed",
                        **args,
                    )
                    assert result["error"] == error and not result.get("timed_out")
                image = host_command(agent, "browser", action="screenshot", **args)
                assert base64.b64decode(image["png_base64"]).startswith(
                    b"\x89PNG\r\n\x1a\n"
                )
                batch_args = dict(
                    args,
                    request_id="native-batch-acceptance",
                    steps=[
                        {
                            "action": "fill",
                            "selector": "#name",
                            "value": "Batch acceptance",
                        },
                        {"action": "click", "selector": "#confirm"},
                        {"action": "read"},
                    ],
                )
                batch = host_command(agent, "browser", action="batch", **batch_args)
                assert batch["ok"] and batch["completed_steps"] == 3
                assert "Batch acceptance" in batch["results"][2]["result"]["text"]
                repeated = host_command(agent, "browser", action="batch", **batch_args)
                assert repeated["cached_result"] and repeated["replayed"] is False
                receipt = host_command(
                    agent, "browser", action="batch_status", **batch_args
                )
                assert (
                    receipt["state"] == "completed" and receipt["completed_steps"] == 3
                )
                postcondition_ab = _browser_postcondition_ab(agent, args, trials=ab_trials)
                capture = host_command(agent, "browser", action="capture_start", **args)
                assert capture["active"] and capture["target_fps"] == 1
                cached = host_command(
                    agent, "browser", action="cached_screenshot", **args
                )
                assert cached["cached"] and cached["age_ms"] <= 3000
                assert base64.b64decode(cached["png_base64"]).startswith(
                    b"\x89PNG\r\n\x1a\n"
                )
                assert host_command(agent, "browser", action="capture_stop", **args)[
                    "stopped"
                ]
                assert host_command(agent, "close", session_id=args["session_id"])[
                    "closed"
                ]
                assert not (agent.state / "computer-access.dpapi").exists()
            finally:
                (home / "stop.flag").write_text("stop owned test fixture")
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=10)
            assert process.returncode == 0
    return dict(
        browser="PASS",
        read_fill_click_screenshot=True,
        native_select_and_disabled=True,
        native_batch_replay_barrier=True,
        browser_postcondition_ab=postcondition_ab,
        native_cached_capture=True,
        permissions_issued=False,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--wheel",
        action="store_true",
        help="Also install a wheel in a fresh temporary venv",
    )
    parser.add_argument(
        "--browser-ab-trials", type=int, default=5,
        help="A/B samples per variant (1..50; default 5 for CI)",
    )
    args = parser.parse_args()
    if not 1 <= args.browser_ab_trials <= 50:
        parser.error("--browser-ab-trials must be between 1 and 50")
    root = Path(__file__).resolve().parents[1]
    logs = root / "reports" / "runtime-scenarios"
    logs.mkdir(parents=True, exist_ok=True)
    results = []

    def run(name, argv, timeout=180):
        print(json.dumps(dict(scenario=name, state="RUNNING")), flush=True)
        with (logs / (name + ".log")).open("wb") as output:
            result = subprocess.run(
                argv,
                cwd=root,
                env=child_environment(),
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
        if result.returncode:
            details = (logs / (name + ".log")).read_text(
                encoding="utf-8", errors="replace"
            )
            raise RuntimeError(name + " failed:\n" + details[-6000:])
        results.append(dict(scenario=name, state="PASS"))
        print(json.dumps(results[-1]), flush=True)

    for name in (
        "test_backend_recovery_mcp",
        "test_documents_mcp",
        "test_uia_provider",
    ):
        run(name, [sys.executable, str(root / "tests/components" / (name + ".py"))])
    print(json.dumps(dict(scenario="owned_browser", state="RUNNING")), flush=True)
    results.append(browser_fixture(ab_trials=args.browser_ab_trials))
    print(json.dumps(results[-1]), flush=True)
    if args.wheel:
        destination = root / "build" / "runtime-wheel"
        run(
            "build_wheel",
            [
                sys.executable,
                "-I",
                "-m",
                "build",
                "--wheel",
                "--no-isolation",
                "--outdir",
                str(destination),
            ],
        )
        wheels = list(destination.glob("*.whl"))
        assert len(wheels) == 1
        run(
            "isolated_wheel",
            [sys.executable, "-I", str(root / "tools/check_wheel.py"), str(wheels[0])],
            timeout=360,
        )
    report = dict(
        result="PASS",
        scenarios=results,
        physical_mouse_keyboard_tested=False,
        sandbox_guest_boot_tested=False,
    )
    (logs / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
