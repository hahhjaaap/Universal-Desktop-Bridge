"""Session-bound browser batches with durable, payload-free replay receipts."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from .browser_actions import (
    attach_post_observation,
    dispatch_browser,
    validate_click_navigation_budget,
    validate_post_observation,
)
from .core import PolicyError, reject_links
from .fastpath import compile_plan, gate, is_mutation, matches
from .host_client import _read_json, atomic_json, enabled
from .resources import require_capacity

FIELDS = {
    "navigate": {"url"},
    "read": set(),
    "snapshot": set(),
    "click": {
        "selector",
        "role",
        "name",
        "exact",
        "observe_after",
        "click_navigation_observe_ms",
    },
    "fill": {"selector", "role", "name", "exact", "value"},
    "press": {"selector", "role", "name", "exact", "key"},
    "select_option": {"selector", "role", "name", "exact", "value"},
    "check": {"selector", "role", "name", "exact"},
    "uncheck": {"selector", "role", "name", "exact"},
    "wait_for": {"selector", "role", "name", "exact", "state", "value", "timeout_ms"},
    "scroll": {"delta_x", "delta_y"},
    "back": set(),
    "forward": set(),
    "reload": set(),
}


def receipt_path(folder: Path, session_id: str, request_id: str) -> Path:
    if not isinstance(session_id, str) or not re.fullmatch(r"[a-f0-9]{32}", session_id):
        raise PolicyError("Invalid owned session ID")
    if not isinstance(request_id, str) or not re.fullmatch(
        r"[A-Za-z0-9_.:-]{1,80}", request_id
    ):
        raise PolicyError(
            "Batch requires a stable request_id of 1..80 identifier characters"
        )
    path = (
        Path(folder)
        / "batches"
        / session_id
        / (hashlib.sha256(request_id.encode()).hexdigest() + ".json")
    )
    reject_links(path)
    return path


def prepare(args):
    steps = args.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 12:
        raise PolicyError("Browser batch requires 1..12 steps")
    fastpath = args.get("action") == "fastpath"
    if fastpath:
        compile_plan(steps, FIELDS)
        # FastPath verification semantics are intentionally unchanged.
        if any(
            step.get("action") == "click"
            and ("observe_after" in step or "click_navigation_observe_ms" in step)
            for step in steps
        ):
            raise PolicyError("FastPath does not support short click observation")
    else:
        for index, step in enumerate(steps):
            if not isinstance(step, dict) or not isinstance(step.get("action"), str):
                raise PolicyError("Every browser step requires an action")
            action = step["action"]
            if action not in FIELDS or set(step) - (FIELDS[action] | {"action"}):
                raise PolicyError("Unsupported/nested browser step or unknown fields")
            if action == "click":
                mode = validate_post_observation(step)
                budget = validate_click_navigation_budget(step)
                if (mode != "none" or budget < 1000) and index != len(steps) - 1:
                    raise PolicyError(
                        "Observed/short click must be the terminal batch step"
                    )
    # Preserve the exact old digest for legacy batch receipts.
    envelope = {"tab_id": args.get("tab_id", ""), "steps": steps}
    if fastpath:
        envelope["fastpath"] = 1
    raw = json.dumps(
        envelope,
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
    )
    if len(raw) > 65536:
        raise PolicyError("Browser batch exceeds 64 KiB")
    return steps, hashlib.sha256(raw.encode()).hexdigest()


def inspect_receipt(folder, session_id, request_id):
    path = receipt_path(folder, session_id, request_id)
    try:
        value = _read_json(path, 4096)
    except FileNotFoundError:
        return {"request_id": request_id, "state": "unknown", "replayed": False}
    if not isinstance(value, dict) or value.get("request_id") != request_id:
        raise PolicyError("Invalid batch receipt; do not replay actions")
    return {k: v for k, v in value.items() if k != "digest"} | {"replayed": False}


def cancel(folder, session_id, request_id):
    path = receipt_path(folder, session_id, request_id)
    value = inspect_receipt(folder, session_id, request_id)
    if value["state"] != "running":
        return {
            "cancellation_requested": False,
            "state": value["state"],
            "interrupts_in_flight": False,
        }
    flag = path.with_suffix(".cancel")
    reject_links(flag)
    atomic_json(flag, {"expires": time.time() + 30})
    return {"cancellation_requested": True, "interrupts_in_flight": False}


class BatchRunner:
    def __init__(self):
        self.results = {}

    def run(self, service, browser, args):
        sid, rid = args.get("session_id"), args.get("request_id")
        path = receipt_path(service.folder, sid, rid)
        steps, digest = prepare(args)
        fastpath = args.get("action") == "fastpath"
        plan = compile_plan(steps, FIELDS) if fastpath else None
        observed = {}
        if path.exists():
            old = _read_json(path, 4096)
            if old.get("digest") != digest:
                raise PolicyError("Batch request_id already used for different actions")
            if (sid, rid) in self.results:
                return dict(
                    self.results[(sid, rid)], cached_result=True, replayed=False
                )
            return dict(
                inspect_receipt(service.folder, sid, rid),
                result_available=False,
                outcome_unknown=old.get("state") == "running",
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        reject_links(path.parent)
        if sum(p.suffix == ".json" for p in path.parent.iterdir()) >= 256:
            raise PolicyError(
                "Session batch receipt limit reached; close this session before starting another"
            )
        row = {
            "request_id": rid,
            "digest": digest,
            "state": "running",
            "total_steps": len(steps),
            "completed_steps": 0,
            "started_at": time.time(),
            "replayed": False,
        }
        atomic_json(path, row)  # Persist before any page mutation.
        results = []
        started = time.monotonic()
        deadline = min(getattr(browser, "deadline", started + 20), started + 20)
        state = "completed"
        failed_index = None
        try:
            for index, step in enumerate(steps):
                service.operation_detail = {
                    "op": "browser",
                    "action": "batch",
                    "started_at": row["started_at"],
                    "completed_steps": index,
                    "total_steps": len(steps),
                }
                flag = path.with_suffix(".cancel")
                reject_links(flag)
                cancelled = False
                if flag.exists():
                    request = _read_json(flag, 1024)
                    expiry = (
                        request.get("expires") if isinstance(request, dict) else None
                    )
                    if type(expiry) not in (int, float):
                        raise PolicyError(
                            "Invalid cancellation request; inspect batch status"
                        )
                    cancelled = time.time() < expiry <= time.time() + 60
                if service.stop_event.is_set() or cancelled:
                    state = "cancelled"
                    break
                if time.monotonic() >= deadline:
                    state = "deadline_exceeded"
                    break
                if not enabled(service.agent):
                    raise PolicyError("Background permission revoked during batch")
                require_capacity(service.resource, 128)
                if service._session(sid, kind="browser")[
                    "object"
                ] is not browser or getattr(browser, "visible", False):
                    raise PolicyError("Browser control changed; inspect session")
                browser.deadline = deadline
                tick = time.monotonic()
                current = plan[index] if fastpath else None
                if current is not None:
                    try:
                        execute = gate(current, observed)
                    except PolicyError as exc:
                        results.append(
                            {
                                "index": index,
                                "action": step["action"],
                                "step_id": current.step_id,
                                "ok": False,
                                "error_type": type(exc).__name__,
                                "error": "FastPath verification evidence unavailable",
                            }
                        )
                        state, failed_index = "failed", index
                        break
                    if not execute:
                        observed[current.step_id] = {
                            "skipped": True,
                            "ok": True,
                            "value": None,
                        }
                        results.append(
                            {
                                "index": index,
                                "action": step["action"],
                                "step_id": current.step_id,
                                "ok": True,
                                "skipped": True,
                                "reason": "condition_or_dependency_not_met",
                            }
                        )
                        row["considered_steps"] = len(results)
                        atomic_json(path, row)
                        continue
                try:
                    call_args = current.arguments if current is not None else step
                    value = dispatch_browser(
                        browser, dict(call_args, tab_id=args.get("tab_id", ""))
                    )
                    if (
                        current is None
                        and step["action"] == "click"
                        and step.get("observe_after", "none") != "none"
                    ):
                        value = attach_post_observation(
                            browser,
                            dict(call_args, tab_id=args.get("tab_id", "")),
                            value,
                        )
                    uncertain = isinstance(value, dict) and any(
                        value.get(key) is True
                        for key in (
                            "navigation_timed_out",
                            "timed_out",
                            "observation_unavailable",
                        )
                    )
                    ok = not uncertain and not (
                        isinstance(value, dict) and value.get("ok") is False
                    )
                    if len(json.dumps(value, ensure_ascii=True)) > 65536:
                        value, ok = (
                            {
                                "truncated": True,
                                "next_action": "Inspect this page separately",
                            },
                            False,
                        )
                    verified = True
                    if ok and current is not None and current.verify is not None:
                        try:
                            verified = matches(value, current.verify)
                        except PolicyError:
                            verified = False
                        if not verified:
                            ok = False
                            # Input may have succeeded before verification
                            # failed: never claim the result is safe to retry.
                            uncertain = is_mutation(step["action"])
                    entry = {
                        "index": index,
                        "action": step["action"],
                        "ok": ok,
                        "elapsed_ms": round((time.monotonic() - tick) * 1000, 2),
                    }
                    if current is None or current.return_result:
                        entry["result"] = value
                    if current is not None:
                        entry.update(
                            step_id=current.step_id,
                            verified=verified,
                        )
                        observed[current.step_id] = {
                            "skipped": False,
                            "ok": ok,
                            "value": value,
                        }
                    results.append(entry)
                    if not ok:
                        state, failed_index = (
                            "outcome_unknown" if uncertain else "failed",
                            index,
                        )
                        break
                except Exception as exc:
                    results.append(
                        {
                            "index": index,
                            "action": step["action"],
                            **(
                                {"step_id": current.step_id}
                                if current is not None
                                else {}
                            ),
                            "ok": False,
                            "error_type": type(exc).__name__,
                            "error": "Browser step failed; inspect page before retrying a mutation",
                        }
                    )
                    state, failed_index = "outcome_unknown", index
                    break
                row["completed_steps"] = sum(
                    1 for item in results if item["ok"] and not item.get("skipped")
                )
                row["considered_steps"] = len(results)
                atomic_json(path, row)
                capture = getattr(service, "captures", None)
                if capture:
                    capture.tick(service)
        except (PolicyError, OSError, ValueError) as exc:
            state, failed_index = "failed", len(results)
            results.append(
                {"index": failed_index, "ok": False, "error_type": type(exc).__name__}
            )
        completed = sum(r["ok"] and not r.get("skipped") for r in results)
        row.update(
            state=state,
            completed_steps=completed,
            considered_steps=len(results),
            finished_at=time.time(),
            failed_index=failed_index,
        )
        atomic_json(path, row)
        path.with_suffix(".cancel").unlink(missing_ok=True)
        result = {
            "request_id": rid,
            "state": state,
            **({"mode": "fastpath"} if fastpath else {}),
            "ok": state == "completed",
            "results": results,
            "completed_steps": completed,
            "considered_steps": len(results),
            "failed_index": failed_index,
            "replayed": False,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
        }
        if getattr(service, "operation_detail", None):
            service.operation_detail["completed_steps"] = completed
        if len(self.results) >= 16:
            self.results.pop(
                next(iter(self.results))
            )  # Receipt still prevents replay after output eviction.
        self.results[(sid, rid)] = result
        return result
