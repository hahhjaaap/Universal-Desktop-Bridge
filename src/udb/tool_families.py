"""Declarative public families; native handlers and permission checks stay intact."""

from __future__ import annotations

import copy
import json
from pathlib import Path

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
    """Drop redundant annotations, preserving fields and validation constraints."""
    schema = copy.deepcopy(schema)
    schema.pop("title", None)
    if schema.get("default") == "":
        schema.pop("default")
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
        members = list(actions.values())
        if any(t not in routes or routes[t] is not routes[members[0]] for t in members):
            raise RuntimeError("Cannot consolidate tools across permission backends")
        if name in catalog or name in routes:
            raise RuntimeError("Public family collides with a backend tool")
        branches = []
        for action, target in actions.items():
            original = catalog[target]
            schema = compact_schema(original["inputSchema"])
            schema.pop("type", None)  # The common params schema enforces object type.
            schema["additionalProperties"] = False
            branches.append(
                dict(
                    properties={"action": {"const": action}, "params": schema},
                    description=original.get("description", target),
                )
            )
        catalog[name] = dict(
            name=name,
            description=group["description"],
            inputSchema=dict(
                type="object",
                properties={
                    "action": {"type": "string", "enum": list(actions)},
                    "params": {"type": "object"},
                },
                oneOf=branches,
                required=["action", "params"],
                additionalProperties=False,
            ),
            annotations=family_annotations(group),
        )
        for target in actions.values():
            catalog.pop(target)
    return list(catalog.values())


def resolve_family(name, arguments):
    """Unwrap one family; legacy names never acquire new actions or permissions."""
    for group in FAMILIES:
        if name != group["name"]:
            continue
        if set(arguments) != {"action", "params"} or not isinstance(
            arguments["params"], dict
        ):
            raise ValueError("Family calls require exactly action and object params")
        action = arguments["action"]
        if not isinstance(action, str) or action not in group["actions"]:
            raise ValueError("Unknown tool family action")
        return group["actions"][action], arguments["params"]
    return name, arguments
