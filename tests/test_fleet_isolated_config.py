"""Isolation regression: a Fleet lab must never inherit the live staging DO."""

import json
from copy import deepcopy

import pytest

from tools.check_fleet_isolated_config import (
    DEFAULT_ISOLATED,
    DEFAULT_PRIMARY,
    DEFAULT_STAGING,
    check_isolated_config,
)


def test_isolated_fleet_staging_has_its_own_script_namespace():
    result = check_isolated_config()
    assert result["worker"] == "udb-fleet-isolated-staging"
    assert result["runtime_flags_enabled"] is False
    assert result["deployed"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        {"name": "udb-private-relay-staging"},
        {"workers_dev": False},
        {"vars": {"UDB_ENABLE_ACCOUNT_FLEET": "true"}},
        {"routes": ["*/*"]},
        {
            "durable_objects": {
                "bindings": [
                    {
                        "name": "DEVICES",
                        "class_name": "DeviceRelay",
                        "script_name": "udb-private-relay-staging",
                    },
                ]
            }
        },
        {"migrations": [{"tag": "v1", "new_classes": ["DeviceRelay"]}]},
        {"migrations": [{"tag": "v1", "new_sqlite_classes": ["OtherClass"]}]},
    ],
)
def test_isolated_worker_rejects_live_aliases_routes_and_implicit_flags(
    mutation, tmp_path
):
    source = json.loads(DEFAULT_ISOLATED.read_text(encoding="utf-8"))
    candidate = deepcopy(source)
    candidate.update(mutation)
    file = tmp_path / "candidate.jsonc"
    file.write_text(json.dumps(candidate), encoding="utf-8")
    with pytest.raises(ValueError, match="Unsafe isolated Fleet"):
        check_isolated_config(file)


def test_live_worker_must_remain_unchanged_even_if_isolated_worker_is_valid(tmp_path):
    primary = json.loads(DEFAULT_PRIMARY.read_text(encoding="utf-8"))
    modified = deepcopy(primary)
    modified["name"] = "udb-fleet-isolated-staging"
    file = tmp_path / "changed-live-config.jsonc"
    file.write_text(json.dumps(modified), encoding="utf-8")
    with pytest.raises(ValueError, match="Unsafe staging deployment"):
        check_isolated_config(DEFAULT_ISOLATED, DEFAULT_STAGING, file)
