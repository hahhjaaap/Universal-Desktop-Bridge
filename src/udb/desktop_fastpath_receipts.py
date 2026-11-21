"""Owner-grant-scoped, payload-free, one-shot receipts for native Desktop FastPath.

The request is recorded *before* its first Windows mutation. Repeated requests
only return a receipt and never re-enter the OS input lane, including when the
original caller timed out or the backend restarted. Browser receipts are
separate: this module neither shares browser ownership nor permits page JS.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from .core import PolicyError, reject_links
from .host_client import _read_json, atomic_json

_GRANT = re.compile(r"[a-f0-9]{32}\Z")
_REQUEST = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")
_MAX_PLAN_BYTES = 64 * 1024
_MAX_RECEIPTS = 1024


def _receipt(state, grant_id, request_id):
    if not isinstance(grant_id, str) or not _GRANT.fullmatch(grant_id):
        raise PolicyError("Invalid local computer access grant")
    if not isinstance(request_id, str) or not _REQUEST.fullmatch(request_id):
        raise PolicyError("Desktop FastPath requires stable request_id (1..80 characters)")
    folder = Path(state) / "desktop-fastpath-receipts" / grant_id
    path = folder / (hashlib.sha256(request_id.encode("ascii")).hexdigest() + ".json")
    reject_links(folder)
    reject_links(path)
    return folder, path


def _digest(steps):
    if not isinstance(steps, list) or not 1 <= len(steps) <= 12:
        raise PolicyError("Desktop FastPath requires 1..12 steps")
    try:
        raw = json.dumps(
            steps, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")
        ).encode("ascii")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise PolicyError("Desktop FastPath plan must be bounded JSON") from exc
    if len(raw) > _MAX_PLAN_BYTES:
        raise PolicyError("Desktop FastPath plan exceeds 64 KiB")
    return hashlib.sha256(raw).hexdigest()


def _summary(row, request_id):
    if (
        not isinstance(row, dict)
        or row.get("request_id") != request_id
        or row.get("state") not in ("running", "completed", "failed", "outcome_unknown")
        or type(row.get("completed_steps")) is not int
        or not 0 <= row["completed_steps"] <= 12
    ):
        raise PolicyError("Invalid Desktop FastPath receipt; inspect before retrying")
    state = row["state"]
    return {
        "request_id": request_id,
        "ok": state == "completed",
        "state": state,
        "completed_steps": row["completed_steps"],
        "failed_index": row.get("failed_index"),
        "outcome_unknown": state in ("running", "outcome_unknown"),
        "cached_result": True,
        "result_available": False,
        "replayed": False,
        "replay_safe": False,
    }


def run_once(state, grant_id, request_id, steps, execute):
    """Run validated owner-granted host FastPath once; no retry on uncertain input.

    The caller MUST hold the existing desktop grant/lock/resource admission,
    and execute MUST perform the existing Desktop.batch validation and controls.
    No raw UI content, screenshot, plan, or input text is persisted.
    """
    folder, path = _receipt(state, grant_id, request_id)
    digest = _digest(steps)
    folder.mkdir(parents=True, exist_ok=True)
    reject_links(folder)
    reject_links(path)

    if path.exists():
        row = _read_json(path, 4096)
        if not isinstance(row, dict) or row.get("digest") != digest:
            raise PolicyError("Desktop FastPath request_id reused for different actions")
        return _summary(row, request_id)

    if sum(p.suffix == ".json" for p in folder.iterdir()) >= _MAX_RECEIPTS:
        raise PolicyError("Desktop FastPath receipt capacity exceeded; renew owner grant")

    row = {
        "request_id": request_id,
        "digest": digest,
        "state": "running",
        "completed_steps": 0,
        "started_at": time.time(),
    }
    # O_EXCL also prevents a second process from racing the same request ID.
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    try:
        handle = os.open(path, flags, 0o600)
    except FileExistsError:
        old = _read_json(path, 4096)
        if not isinstance(old, dict) or old.get("digest") != digest:
            raise PolicyError("Desktop FastPath request_id reused for different actions")
        return _summary(old, request_id)
    try:
        with os.fdopen(handle, "w", encoding="ascii") as stream:
            json.dump(row, stream, ensure_ascii=True)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception as exc:
        # A partially written receipt must still block replay.
        raise PolicyError("Desktop FastPath receipt creation failed; do not retry") from exc

    try:
        result = execute()
    except Exception:
        row.update(state="outcome_unknown", finished_at=time.time())
        try:
            atomic_json(path, row)
        except OSError:
            pass
        return {
            "request_id": request_id,
            "ok": False,
            "state": "outcome_unknown",
            "completed_steps": 0,
            "outcome_unknown": True,
            "replay_safe": False,
            "replayed": False,
            "error": "Desktop FastPath interrupted; inspect before any further mutation",
        }

    if not isinstance(result, dict):
        state_name = "outcome_unknown"
        result = {
            "ok": False,
            "outcome_unknown": True,
            "error": "Unexpected desktop response; inspect before retrying",
        }
    elif result.get("ok") is True:
        state_name = "completed"
    else:
        state_name = "outcome_unknown" if result.get("outcome_unknown") else "failed"
    row.update(
        state=state_name,
        completed_steps=max(0, min(12, result.get("completed_steps", 0)))
        if type(result.get("completed_steps")) is int else 0,
        failed_index=result.get("failed_index")
        if type(result.get("failed_index")) is int else None,
        finished_at=time.time(),
    )
    try:
        atomic_json(path, row)
    except (OSError, ValueError) as exc:
        raise PolicyError(
            "Desktop FastPath receipt finalization failed; outcome unknown, do not retry"
        ) from exc
    return {
        **result,
        "request_id": request_id,
        "state": state_name,
        "outcome_unknown": state_name == "outcome_unknown",
        "replay_safe": False,
        "replayed": False,
    }
