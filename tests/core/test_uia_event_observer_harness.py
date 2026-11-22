"""Static contract tests for the isolated UIA event observer canary."""

import ast
from pathlib import Path


def test_event_observer_canary_is_valid_python_and_uses_owned_fixture():
    root = Path(__file__).parents[2]
    script_path = root / "tools" / "compare_uia_event_observer.py"
    source = script_path.read_text(encoding="utf-8")
    ast.parse(source)

    assert "from tools.compare_uia_snapshot_cache import" in source
    assert "_fixture(" in source
    assert 'dynamic_mutation="replace"' in source
    assert "PersistentUIA" in source
    assert '"event_observer": event_observer' in source
    assert "observer_signals" in source
    assert "timeout_cleanup" in source


def test_event_observer_canary_does_not_enable_production_flags_or_touch_user_apps():
    root = Path(__file__).parents[2]
    source = (root / "tools" / "compare_uia_event_observer.py").read_text(
        encoding="utf-8"
    )
    assert "test-owned WinForms fixture only" in source
    assert "UDB_UIA_EVENT_OBSERVER" not in source
    assert "Chrome" not in source
    assert "MISA" not in source
