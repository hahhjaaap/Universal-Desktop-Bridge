"""Common MCP status metadata without changing legacy payloads or names."""

import json

from ._version import VERSION
from .outcomes import report_outcome


def metadata(status):
    return dict(
        version=VERSION,
        status=status,
        replay_performed=False,
        unknown_outcome_must_not_replay=True,
    )


def annotate(result):
    """Derive outcomes from UDB metadata or structured backend reports, never text."""
    if not isinstance(result, dict):
        return result
    extra = dict(result.get("_meta") or {})
    supplied = extra.get("udb")
    marker = supplied.get("status") if isinstance(supplied, dict) else None
    report = result.get("structuredContent")
    structured = report_outcome(report).status if isinstance(report, dict) else "PASS"
    if result.get("isError") is True or "ERROR" in (marker, structured):
        status = "ERROR"
    elif "RUNNING" in (marker, structured):
        status = "RUNNING"
    else:
        status = "PASS"
    extra["udb"] = metadata(status)
    return dict(result, _meta=extra)


def result(data, state=None):
    if state is None:
        state = report_outcome(data).status
    return dict(
        content=[
            dict(type="text", text=state + " | UDB Companion"),
            dict(type="text", text=json.dumps(data, ensure_ascii=False)),
        ],
        structuredContent=data,
        isError=state == "ERROR",
        _meta={"udb": metadata(state)},
    )
