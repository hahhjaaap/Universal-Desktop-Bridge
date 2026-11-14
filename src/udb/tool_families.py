"""Declarative public families; native handlers and permission checks stay intact."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

# The gateway imports this same packaged JSON; no generated second inventory.
_SPEC = json.loads(Path(__file__).with_suffix(".json").read_text("utf-8"))
FAMILIES = tuple(_SPEC["families"])
LEGACY_ALIASES = frozenset(_SPEC["legacyAliases"])
FAMILY_NAMES = frozenset(group["name"] for group in FAMILIES)
FAMILY_MEMBERS = frozenset(
    name for group in FAMILIES for name in group["actions"].values()
)


def family_annotations(group):
    read = group["readOnly"]
    return dict(
        readOnlyHint=read,
        destructiveHint=not read,
        idempotentHint=read,
        openWorldHint=group["openWorld"],
    )


def compact_schema(schema):
    """Drop generated display titles, preserving actual properties named title."""
    schema = copy.deepcopy(schema)
    schema.pop("title", None)
    for keyword in ("properties", "$defs"):
        if keyword in schema:
            schema[keyword] = {k: compact_schema(v) for k, v in schema[keyword].items()}
    for keyword in ("items", "additionalProperties"):
        if isinstance(schema.get(keyword), dict):
            schema[keyword] = compact_schema(schema[keyword])
    for keyword in ("oneOf", "anyOf", "allOf"):
        if keyword in schema:
            schema[keyword] = [compact_schema(v) for v in schema[keyword]]
    return schema


def consolidate_families(tools, routes):
    catalog = {tool["name"]: copy.deepcopy(tool) for tool in tools}
    for group in FAMILIES:
        name = group["name"]
        actions = {a: t for a, t in group["actions"].items() if t in catalog}
        if not actions:
            continue
        members = list(actions.values()) + ([name] if group.get("extend") else [])
        if any(t not in routes or routes[t] is not routes[members[0]] for t in members):
            raise RuntimeError("Cannot consolidate tools across permission backends")
        if not group.get("extend") and name in catalog:
            raise RuntimeError("Public family collides with a backend tool")
        branches = []
        properties: dict[str, Any] = {}
        if group.get("extend"):
            original = catalog[name]
            branch = compact_schema(original["inputSchema"])
            branch.pop("type", None)  # The common root is already an object.
            # Legacy browser actions are open-ended; reserve exactly screenshot.
            branch.setdefault("properties", {}).setdefault("action", {})["not"] = {
                "const": "screenshot"
            }
            branches.append(branch)
            properties.update(copy.deepcopy(branch["properties"]))
        for action, target in actions.items():
            original = catalog[target]
            schema = compact_schema(original["inputSchema"])
            schema.pop("type", None)  # Root/params already enforces object type.
            schema["additionalProperties"] = False
            if group.get("extend"):
                schema.setdefault("properties", {})["action"] = {"const": action}
                schema["required"] = [*schema.get("required", []), "action"]
                properties.update(copy.deepcopy(schema["properties"]))
                branches.append(schema)
            else:
                branches.append(
                    dict(
                        properties={"action": {"const": action}, "params": schema},
                        description=original.get("description", target),
                    )
                )
        if not group.get("extend"):
            properties = {
                "action": {"type": "string", "enum": list(actions)},
                "params": {"type": "object"},
            }
        else:
            properties = {"action": {"type": "string", "default": "list"}}
        catalog[name] = dict(
            name=name,
            description=(
                catalog[name].get("description", "") if group.get("extend") else ""
            )
            + group["description"],
            inputSchema=dict(type="object", properties=properties, oneOf=branches),
            annotations=family_annotations(group),
        )
        if not group.get("extend"):
            catalog[name]["inputSchema"].update(
                required=["action", "params"], additionalProperties=False
            )
        for target in actions.values():
            catalog.pop(target)
    return list(catalog.values())


def resolve_family(name, arguments):
    """Unwrap one family without executing anything or mutating the request."""
    for group in FAMILIES:
        if name != group["name"]:
            continue
        if group.get("extend"):
            if arguments.get("action") != "screenshot":
                return name, arguments
            if set(arguments) - {
                "action",
                "session_id",
                "tab_id",
                "cached",
                "max_age_ms",
            }:
                raise ValueError("Browser screenshot accepts only capture options")
            return "host_screenshot", {
                k: v for k, v in arguments.items() if k != "action"
            }
        if set(arguments) != {"action", "params"} or not isinstance(
            arguments["params"], dict
        ):
            raise ValueError("Family calls require exactly action and object params")
        action = arguments["action"]
        if not isinstance(action, str) or action not in group["actions"]:
            raise ValueError("Unknown tool family action")
        return group["actions"][action], arguments["params"]
    return name, arguments
