"""Staging deployment config must stay isolated and fail closed."""

import json
import sys
from copy import deepcopy

import pytest

from tools import check_staging_worker_config as staging


def test_repo_default_and_explicit_config_target_one_staging_gateway():
    result = staging.check_config(staging.DEFAULT_STAGING, staging.DEFAULT_PRIMARY)
    assert result["worker"] == "udb-private-relay-staging"
    assert json.loads(staging.DEFAULT_PRIMARY.read_text(encoding="utf-8")) == json.loads(
        staging.DEFAULT_STAGING.read_text(encoding="utf-8")
    )
    assert result["deployed"] is False
    assert result["oauth_verified"] is False
    assert result["authenticated_project_read_verified"] is False


@pytest.mark.parametrize(
    "edit",
    [
        {"name": "udb-private-relay"},
        {"workers_dev": False},
        {"routes": ["example.com/*"]},
        {"vars": {"UDB_AUTH_MODE": "cloudflare-access"}},
        {"account_id": "fake-account"},
        {"durable_objects": {"bindings": []}},
        {"migrations": []},
        {"main": "src/other-worker.js"},
        {"compatibility_date": "2025-01-01"},
    ],
)
def test_unsafe_staging_changes_are_rejected(tmp_path, edit):
    source = json.loads(staging.DEFAULT_STAGING.read_text(encoding="utf-8"))
    modified = deepcopy(source)
    modified.update(edit)
    candidate = tmp_path / "staging.jsonc"
    candidate.write_text(json.dumps(modified), encoding="utf-8")
    with pytest.raises(ValueError):
        staging.check_config(candidate, staging.DEFAULT_PRIMARY)


def test_broken_default_wrangler_binding_cannot_pass_check(tmp_path):
    primary = json.loads(staging.DEFAULT_PRIMARY.read_text(encoding="utf-8"))
    primary["durable_objects"]["bindings"][0]["class_name"] = "OtherRelay"
    candidate = tmp_path / "default.jsonc"
    candidate.write_text(json.dumps(primary), encoding="utf-8")
    with pytest.raises(ValueError):
        staging.check_config(staging.DEFAULT_STAGING, candidate)



@pytest.mark.parametrize(
    "bad_edit",
    [
        {"name": "udb-private-relay"},
        {"workers_dev": False},
        {"routes": ["example.com/*"]},
        {"vars": {"UDB_AUTH_MODE": "cloudflare-access"}},
        {"account_id": "fake-account"},
        {"main": "src/other-worker.js"},
    ],
)
def test_default_wrangler_cannot_create_legacy_or_alternate_gateway(tmp_path, bad_edit):
    primary = json.loads(staging.DEFAULT_PRIMARY.read_text(encoding="utf-8"))
    primary.update(bad_edit)
    candidate = tmp_path / "default.jsonc"
    candidate.write_text(json.dumps(primary), encoding="utf-8")
    with pytest.raises(ValueError):
        staging.check_config(staging.DEFAULT_STAGING, candidate)


def test_cli_reports_safe_codes_without_echoing_paths(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "private-path-with-owner-name.jsonc"
    bad.write_text('{"name":"udb-private-relay"}', encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv", ["check_staging_worker_config.py", "--staging-config", str(bad)]
    )
    assert staging.main() == 1
    output = capsys.readouterr().out
    assert json.loads(output) == {
        "result": "failed",
        "reason": "unsafe_staging_config",
    }
    assert str(bad) not in output


def test_cli_accepts_repository_staging_config(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["check_staging_worker_config.py"])
    assert staging.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["result"] == "staging_configuration_safe"
    assert result["deployed"] is False
