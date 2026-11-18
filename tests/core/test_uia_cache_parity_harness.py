"""Cross-platform contract checks for the Windows-only UIA cache parity harness."""

import pytest

from tools.compare_uia_snapshot_cache import compare, percentile


def test_percentiles_are_deterministic_and_interpolated():
    assert percentile([100.0, 10.0, 40.0, 20.0], 0.5) == 30.0
    assert percentile([100.0, 10.0, 40.0, 20.0], 0.95) == 91.0
    assert percentile([12.0], 0.99) == 12.0


@pytest.mark.parametrize(
    ("size", "samples"),
    [(0, 1), (49, 1), (501, 1), (1001, 1), (50, 0), (50, 31)],
)
def test_invalid_canary_sizes_or_sample_count_fail_before_windows_access(size, samples):
    with pytest.raises(ValueError, match="Allowed fixture sizes"):
        compare(size, samples)
