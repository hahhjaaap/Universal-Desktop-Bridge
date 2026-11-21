"""Bounded, declarative FastPath planning for an already owned UDB browser.

FastPath never runs caller JavaScript, OS commands, or alternate browser
profiles. It reuses BatchRunner's durable one-shot receipts, owner permission
checks and 20-second deadline. A dependency graph is evaluated in topological
order; page mutations still execute serially.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .core import PolicyError

MAX_FASTPATH_STEPS = 12
PLAN_FIELDS = frozenset(
    {"step_id", "depends_on", "when", "verify", "return_result", "click_postcondition"}
)
RESULT_FIELDS = frozenset(
    {
        "ok",
        "state",
        "matches",
        "visible",
        "enabled",
        "navigation_completed",
        "navigation_timed_out",
        "timed_out",
        "clicked",
        "postcondition_met",
        "changed",
        "selected",
        "checked",
    }
)
READ_ONLY = frozenset({"read", "snapshot", "wait_for"})
_STEP_ID = re.compile(r"[a-zA-Z][a-zA-Z0-9_]{0,31}\Z")
_ID_SELECTOR = re.compile(r"#[a-zA-Z_][a-zA-Z0-9_-]{0,127}\Z")


@dataclass(frozen=True)
class PlannedStep:
    step_id: str
    action: str
    arguments: dict
    depends_on: tuple[str, ...]
    when: dict | None
    verify: dict | None
    return_result: bool
    click_postcondition: dict | None


def _click_postcondition(raw, arguments):
    if not isinstance(raw, dict) or not {"selector", "text"} <= set(raw) <= {
        "selector",
        "text",
        "timeout_ms",
    }:
        raise PolicyError("FastPath click_postcondition requires selector and text")
    if arguments["action"] != "click" or set(arguments) != {"action", "selector"}:
        raise PolicyError("FastPath click_postcondition requires an ID-only click")
    for selector in (arguments["selector"], raw["selector"]):
        if not isinstance(selector, str) or not _ID_SELECTOR.fullmatch(selector):
            raise PolicyError(
                "FastPath click_postcondition requires simple ID selectors"
            )
    timeout = raw.get("timeout_ms", 1000)
    if type(timeout) is not int or not 100 <= timeout <= 2000:
        raise PolicyError("FastPath click_postcondition timeout_ms must be 100..2000")
    expected = raw["text"]
    if (
        not isinstance(expected, str)
        or not 1 <= len(expected) <= 160
        or expected != expected.strip()
    ):
        raise PolicyError(
            "FastPath click_postcondition requires trimmed text of 1..160 characters"
        )
    return {"selector": raw["selector"], "text": expected, "timeout_ms": timeout}


def _scalar(value):
    if type(value) is bool:
        return value
    if type(value) is int and -1000000000 <= value <= 1000000000:
        return value
    if type(value) is str and len(value) <= 160:
        return value
    raise PolicyError("FastPath expected value must be bounded bool/int/text")


def _predicate(raw, *, previous, dependency):
    if not isinstance(raw, dict):
        raise PolicyError("FastPath guard must be an object")
    fields = {"field", "equals"} | ({"step_id"} if previous else set())
    if (
        set(raw) != fields
        or not isinstance(raw.get("field"), str)
        or raw["field"] not in RESULT_FIELDS
    ):
        raise PolicyError("FastPath guard uses unsupported result field")
    if previous and raw.get("step_id") not in dependency:
        raise PolicyError("FastPath guard must reference a previous step")
    return {
        **({"step_id": raw["step_id"]} if previous else {}),
        "field": raw["field"],
        "equals": _scalar(raw["equals"]),
    }


def compile_plan(steps, allowed):
    """Validate the complete plan before a receipt, page mutation or I/O."""
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_FASTPATH_STEPS:
        raise PolicyError("FastPath requires 1..12 steps")
    result = []
    known = {}
    postcondition_started = False
    for index, raw in enumerate(steps):
        if not isinstance(raw, dict):
            raise PolicyError("FastPath step must be an object")
        action = raw.get("action")
        if (
            not isinstance(action, str)
            or action not in allowed
            or set(raw) - (allowed[action] | PLAN_FIELDS | {"action"})
        ):
            raise PolicyError("FastPath contains unknown or nested browser action")
        step_id = raw.get("step_id", f"s{index}")
        if (
            not isinstance(step_id, str)
            or not _STEP_ID.fullmatch(step_id)
            or step_id in known
        ):
            raise PolicyError("FastPath step IDs must be unique and bounded")
        parents = raw.get("depends_on", [])
        if (
            not isinstance(parents, list)
            or len(parents) > index
            or len(set(str(parent) for parent in parents)) != len(parents)
            or any(
                not isinstance(parent, str) or parent not in known for parent in parents
            )
        ):
            raise PolicyError("FastPath dependency must reference an earlier step")
        when = (
            _predicate(raw["when"], previous=True, dependency=known)
            if "when" in raw
            else None
        )
        verify = (
            _predicate(raw["verify"], previous=False, dependency=known)
            if "verify" in raw
            else None
        )
        retain = raw.get("return_result", False)
        if type(retain) is not bool:
            raise PolicyError("FastPath return_result must be boolean")
        arguments = {key: value for key, value in raw.items() if key not in PLAN_FIELDS}
        postcondition = None
        if "click_postcondition" in raw:
            postcondition = _click_postcondition(raw["click_postcondition"], arguments)
            postcondition_started = True
        elif postcondition_started and is_mutation(action):
            raise PolicyError(
                "FastPath postcondition clicks can only be followed by reads or other postcondition clicks"
            )
        result.append(
            PlannedStep(
                step_id=step_id,
                action=action,
                arguments=arguments,
                depends_on=tuple(parents),
                when=when,
                verify=verify,
                return_result=retain,
                click_postcondition=postcondition,
            )
        )
        known[step_id] = index
    return tuple(result)


def _same(actual, expected):
    # Prevent Python's True == 1 from treating unrelated UI evidence as equal.
    return type(actual) is type(expected) and actual == expected


def matches(payload, predicate):
    if not isinstance(payload, dict) or predicate["field"] not in payload:
        raise PolicyError(
            "FastPath required observation unavailable; inspect before continuing"
        )
    return _same(payload[predicate["field"]], predicate["equals"])


def gate(step, observations):
    """Return True to execute or False to skip; missing evidence fails closed."""
    for parent in step.depends_on:
        previous = observations[parent]
        if previous["skipped"]:
            return False
        if not previous["ok"]:
            raise PolicyError("FastPath dependent step did not succeed")
    if step.when is None:
        return True
    previous = observations[step.when["step_id"]]
    if previous["skipped"]:
        return False
    if not previous["ok"]:
        raise PolicyError("FastPath condition depends on unsuccessful step")
    return matches(previous["value"], step.when)


def is_mutation(action):
    return action not in READ_ONLY
