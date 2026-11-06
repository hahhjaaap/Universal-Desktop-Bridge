"""Safely classify frozen onefile start failures without owner state in CI."""

import json

from tools.check_frozen import offline_start_failure_evidence


def test_offline_manager_failure_evidence_contains_only_fixed_fields(tmp_path):
    home = tmp_path / "private-test-home"
    state = home / "state"
    runtime = tmp_path / "runtime"
    state.mkdir(parents=True)
    runtime.mkdir()
    (state / "manager.lock").write_text("75381\nSENSITIVE\n", encoding="utf-8")
    (state / "headless-status.json").write_text(
        '{"token": "DO-NOT-PRINT"}', encoding="utf-8"
    )
    for num in range(3):
        (runtime / f"_MEI{num}").mkdir()

    output = json.dumps(
        {
            "manager_running": False,
            "connection_mode": "unknown",
            "device_token": "DO-NOT-PRINT",
            "home": str(home),
        }
    )
    result = offline_start_failure_evidence(
        home, runtime, returncode=2, stdout=output
    )
    assert result == {
        "stage": "frozen_offline_manager_start",
        "child_exit": "nonzero",
        "reported_status": "json",
        "reported_running": False,
        "reported_mode": "unknown",
        "lock_present": True,
        "headless_status_present": True,
        "onefile_extract_count": 3,
    }
    serialized = json.dumps(result)
    for secret in ("DO-NOT-PRINT", "SENSITIVE", "75381", str(home)):
        assert secret not in serialized


def test_frozen_start_timeout_or_invalid_json_never_echoes_subprocess_data(
    tmp_path,
):
    home = tmp_path / "home"
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    expired = offline_start_failure_evidence(
        home, runtime, returncode=None, stdout="token=DO-NOT-PRINT"
    )
    assert expired["child_exit"] == "timeout"
    assert expired["reported_status"] == "missing_or_invalid"
    assert expired["lock_present"] is False
    assert expired["onefile_extract_count"] == 0
    oversized = offline_start_failure_evidence(
        home,
        runtime,
        returncode=-1,
        stdout=json.dumps({"secret": "DO-NOT-PRINT" * 1000}),
    )
    assert oversized["child_exit"] == "nonzero"
    assert oversized["reported_status"] == "missing_or_invalid"
    assert "DO-NOT-PRINT" not in json.dumps(oversized)


def test_frozen_start_diagnostic_accepts_only_known_modes(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    report = offline_start_failure_evidence(
        tmp_path,
        runtime,
        returncode=1,
        stdout=json.dumps({"manager_running": True, "connection_mode": "token"}),
    )
    assert report["reported_running"] is True
    assert report["reported_mode"] == "unknown"
    assert report["child_exit"] == "nonzero"
