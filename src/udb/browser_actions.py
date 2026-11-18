"""Explicit browser action routing; no arbitrary method or JavaScript dispatch."""

from .core import PolicyError

BROWSER_ACTIONS = (
    "open",
    "batch",
    "fastpath",
    "batch_status",
    "batch_cancel",
    "capture_start",
    "capture_stop",
    "capture_status",
    "upload",
    "download",
    "scroll",
    "list",
    "new",
    "navigate",
    "read",
    "snapshot",
    "wait_for",
    "click",
    "fill",
    "press",
    "select_option",
    "check",
    "uncheck",
    "back",
    "forward",
    "reload",
    "close_tab",
)


POST_OBSERVABLE_ACTIONS = frozenset(
    {
        "open",
        "new",
        "navigate",
        "click",
        "fill",
        "press",
        "select_option",
        "check",
        "uncheck",
        "scroll",
        "back",
        "forward",
        "reload",
    }
)


def validate_post_observation(args):
    """Validate the post-action read before any possibly mutating operation."""
    mode = args.get("observe_after", "none")
    if type(mode) is not str or mode not in {"none", "snapshot", "read"}:
        raise PolicyError("observe_after must be none, snapshot or read")
    if mode != "none" and args.get("action") not in POST_OBSERVABLE_ACTIONS:
        raise PolicyError("observe_after is unsupported for this browser action")
    return mode


def attach_post_observation(obj, args, result):
    """Attach a bounded, redacting observation without re-dispatching input.

    An observation failing after input must NOT turn the entire mutation into
    a retriable exception. Only the original action is executed, exactly once.
    """
    mode = validate_post_observation(args)
    if mode == "none":
        return result
    if not isinstance(result, dict):
        raise PolicyError("Browser action result unavailable; inspect before retrying")
    if (
        result.get("ok") is False
        or result.get("timed_out") is True
        or result.get("navigation_timed_out") is True
    ):
        return dict(result, observation_skipped="action_failed_or_uncertain")
    tab = result.get("tab_id") or args.get("tab_id", "")
    if not isinstance(tab, str) or not tab:
        return dict(result, observation_unavailable=True)
    try:
        observation = obj.snapshot(tab) if mode == "snapshot" else obj.read(tab)
    except Exception:
        # A click/submit may have succeeded. Fail closed on observation while
        # still returning the original action evidence; never replay that step.
        return dict(result, observation_unavailable=True)
    if not isinstance(observation, dict) or observation.get("error"):
        return dict(result, observation_unavailable=True)
    return dict(result, observe_after=mode, observation=observation)


def dispatch_browser(obj, args):
    action = args.get("action")
    if action == "scroll":
        return obj.scroll(
            args.get("tab_id", ""), args.get("delta_x", 0), args.get("delta_y", 500)
        )
    if action == "list":
        return dict(tabs=obj.listing())
    if action == "new":
        return obj.new(args.get("url", "about:blank"))
    tab = args.get("tab_id", "")
    if action == "navigate":
        return obj.navigate(tab, args.get("url", ""))
    if action == "read":
        return obj.read(tab)
    if action == "snapshot":
        return obj.snapshot(tab)
    if action == "wait_for":
        return obj.wait_for(
            tab,
            args.get("selector", ""),
            args.get("role", ""),
            args.get("name", ""),
            args.get("exact", True),
            args.get("state", "visible"),
            args.get("value", ""),
            args.get("timeout_ms", 5000),
        )
    if action in ("fill", "click", "select_option", "check", "uncheck"):
        return obj.element(
            tab,
            action,
            args.get("selector", ""),
            args.get("value", ""),
            args.get("role", ""),
            args.get("name", ""),
            args.get("exact", True),
        )
    if action == "press":
        return obj.press(
            tab,
            args.get("key", ""),
            args.get("selector", ""),
            args.get("role", ""),
            args.get("name", ""),
            args.get("exact", True),
        )
    if action in ("back", "forward", "reload"):
        return obj.history(tab, action)
    if action == "screenshot":
        return dict(png_base64=obj.screenshot(tab))
    if action == "close_tab":
        return obj.close_tab(tab)
    raise PolicyError("Unsupported browser action")
