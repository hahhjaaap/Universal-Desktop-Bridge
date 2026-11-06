"""Synthetic tests for strict, non-secret P0-B acceptance checklist."""

from __future__ import annotations

import copy
import json

import pytest

from tools.check_p0b_staging_acceptance import (
    DENIALS,
    FLAGS,
    NETWORKS,
    evaluate,
    main,
    run,
)


def complete():
    return {
        "schema_version": 1,
        "environment": "isolated-staging",
        "source_commit": "a" * 40,
        "worker_revision": "b" * 8,
        "checks": {key: True for key in FLAGS},
        "denials": {key: True for key in DENIALS},
        "networks": {key: {"attempted": 30, "matched": 30} for key in NETWORKS},
    }


def test_full_synthetic_checklist_is_not_cryptographic_proof():
    result = evaluate(complete())
    assert result["result"] == "checklist_complete"
    assert result["missing_checks"] == []
    assert "Self-reported" in result["note"]


def test_missing_checks_and_bad_networks_are_fails_closed():
    data = complete()
    data["checks"]["verified_oauth_chatgpt_read"] = False
    data["denials"]["wrong_device"] = False
    data["networks"]["network_a"] = {"attempted": 30, "matched": 29}
    data["networks"]["network_c"] = {"attempted": 29, "matched": 29}
    out = evaluate(data)
    assert out["result"] == "blocked"
    assert out["missing_checks"] == [
        "verified_oauth_chatgpt_read",
        "wrong_device",
        "network_a",
        "network_c",
    ]


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update({"oauth_token": "SECRET"}),
        lambda d: d.update({"environment": "production"}),
        lambda d: d.update({"source_commit": "0" * 40}),
        lambda d: d.update({"worker_revision": "bad/ID"}),
        lambda d: d.update({"schema_version": True}),
        lambda d: d["checks"].update({"unexpected": True}),
        lambda d: d["checks"].update({"owner_attended": 1}),
        lambda d: d["denials"].update({"wrong_identity": "true"}),
        lambda d: d["networks"].update(
            {"network_a": {"attempted": True, "matched": 1}}
        ),
        lambda d: d["networks"].update({"network_a": {"attempted": 29, "matched": 30}}),
        lambda d: d["networks"].update(
            {"network_a": {"attempted": 30, "matched": 30, "secret": "x"}}
        ),
    ],
)
def test_invalid_report_fields_cannot_pass_or_leak(change):
    data = complete()
    change(data)
    out = evaluate(data)
    assert out["result"] == "invalid"
    assert "SECRET" not in json.dumps(out)
    assert "secret" not in json.dumps(out)


def test_invalid_type_and_truncated_json_fail_closed(tmp_path):
    assert evaluate(None)["result"] == "invalid"
    path = tmp_path / "report.json"
    path.write_text('{"checks":', encoding="utf-8")
    assert run(path)["result"] == "invalid"
    path.write_text("X" * 16385, encoding="utf-8")
    assert run(path) == {"result": "invalid", "reason": "invalid_file"}


def test_symlink_report_is_refused(tmp_path):
    target = tmp_path / "target.json"
    target.write_text(json.dumps(complete()), encoding="utf-8")
    symlink = tmp_path / "shortcut.json"
    try:
        symlink.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation not available")
    assert run(symlink) == {"result": "invalid", "reason": "invalid_file"}


def test_cli_returns_nonzero_for_unverified_data_without_echo(tmp_path, capsys):
    data = copy.deepcopy(complete())
    data["checks"]["two_owners_verified"] = False
    path = tmp_path / "report.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert main([str(path)]) == 1
    stdout = capsys.readouterr().out
    assert json.loads(stdout)["missing_checks"] == ["two_owners_verified"]
    assert data["source_commit"] not in stdout
    assert data["worker_revision"] not in stdout
