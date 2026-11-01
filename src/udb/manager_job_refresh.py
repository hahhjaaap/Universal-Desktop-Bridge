"""Pure idle-refresh policy for native manager job details.

Kept Qt-independent so Linux/headless tests exercise the same decision rule.
"""

FINISHED_JOB_STATUSES = frozenset(
    {"completed", "failed", "timeout", "stopped", "output_limit"}
)


def should_reload_job_details(changed: bool, selected_status: str | None) -> bool:
    """Live/unknown states refresh; known terminal state on unchanged poll does not."""
    return changed or selected_status not in FINISHED_JOB_STATUSES
