"""Staging deployment config must stay isolated and fail closed."""

import json
import sys
from copy import deepcopy

import pytest

from tools import check_staging_worker_config as staging


def test_repo_staging_config_is_isolated_and_offline():
    result = staging.check_config(staging.DEFAULT_STAGING, staging.DEFAULT_PRODUCTION)
    assert result["worker"] != "udb-private-relay"
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
        {"d1_databases": []},
        {
            "d1_databases": [
                {
                    "binding": "UDB_TENANT_DB",
                    "database_name": "udb-auth-staging",
                    "database_id": "wrong",
                    "migrations_dir": "migrations",
                }
            ]
        },
        {
            "d1_databases": [
                {
                    "binding": "PRODUCTION_DB",
                    "database_name": "udb-auth-staging",
                    "database_id": "fd474b23-56be-44c7-8387-615a071de824",
                    "migrations_dir": "migrations",
                }
            ]
        },
    ],
)
def test_unsafe_staging_changes_are_rejected(tmp_path, edit):
    source = json.loads(staging.DEFAULT_STAGING.read_text(encoding="utf-8"))
    modified = deepcopy(source)
    modified.update(edit)
    candidate = tmp_path / "staging.jsonc"
    candidate.write_text(json.dumps(modified), encoding="utf-8")
    with pytest.raises(ValueError):
        staging.check_config(candidate, staging.DEFAULT_PRODUCTION)


def test_broken_production_binding_cannot_pass_check(tmp_path):
    production = json.loads(staging.DEFAULT_PRODUCTION.read_text(encoding="utf-8"))
    production["durable_objects"]["bindings"][0]["class_name"] = "OtherRelay"
    candidate = tmp_path / "production.jsonc"
    candidate.write_text(json.dumps(production), encoding="utf-8")
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
