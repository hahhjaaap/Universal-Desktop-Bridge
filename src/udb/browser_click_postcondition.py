"""Confirm a bounded same-document Chrome UI update after one native click."""

from __future__ import annotations

import json
import secrets

from .core import PolicyError

class GuardedClickPhaseError(PolicyError):
    """Stable, non-sensitive diagnostic for a failed guarded-click stage.

    The enclosing batch still reports outcome_unknown and never replays a
    possibly dispatched mouse event. Underlying CDP/page text is not exposed.
    """

    def __init__(self, phase):
        super().__init__("Guarded click failed; inspect page state before retrying")
        self.phase = phase


_WORLD = "UDBClickPostcondition"
# Bound cleanup when native input never produces a trusted click. CDP calls
# and the enclosing browser action retain their own deadlines.
_ARM_TIMEOUT_MS = 8_000
_WATCH = """(({selector, expected, buttonSelector, url, x, y, timeout, armTimeout, token}) => {
  const button = one(buttonSelector);
  let resolve, observer, timer, pressed = false, finished = false;
  const promise = new Promise(done => { resolve = done; });
  function one(css) {
    const nodes = document.querySelectorAll(css);
    return nodes.length === 1 ? nodes[0] : null;
  }
  function matches() {
    const node = one(selector);
    return node instanceof HTMLElement
      && node.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})
      && node.innerText.trim() === expected;
  }
  function stillActionable() {
    return location.href === url && button instanceof HTMLButtonElement
      && button.type === 'button' && button === one(buttonSelector)
      && !button.matches(':disabled, [aria-disabled="true"]')
      && !button.closest('[inert]') && button.contains(document.elementFromPoint(x, y));
  }
  function finish(ok) {
    if (finished) return;
    finished = true;
    clearTimeout(timer);
    observer.disconnect();
    document.removeEventListener('click', onClick, true);
    resolve(ok);
  }
  function check() {
    if (pressed && matches()) finish(location.href === url);
  }
  function onClick(event) {
    if (!pressed && event.isTrusted && event.button === 0 && button.contains(event.target)) {
      pressed = true;
      clearTimeout(timer);
      timer = setTimeout(() => finish(false), timeout);
      check();
    }
  }
  globalThis.udbClickWatch?.cancel();
  if (!stillActionable() || matches()) return false;
  observer = new MutationObserver(check);
  observer.observe(document.documentElement, {
    attributes: true, characterData: true, childList: true, subtree: true
  });
  document.addEventListener('click', onClick, true);
  timer = setTimeout(() => finish(false), armTimeout);
  globalThis.udbClickWatch = {
    token, promise, cancel: () => finish(false),
    canPress: () => !finished && stillActionable() && !matches(),
    confirmed: () => location.href === url && matches()
  };
  return true;
})"""


def _document(browser, session):
    frame = (
        browser.call("Page.getFrameTree", session=session, timeout=1)
        .get("frameTree", {})
        .get("frame", {})
    )
    frame_id, loader_id = frame.get("id"), frame.get("loaderId")
    if not frame_id or not loader_id:
        raise PolicyError("Browser document identity unavailable")
    return frame_id, loader_id


def click_with_postcondition(browser, tab, selector, condition, expected_document):
    session = browser.sid(tab)
    try:
        frame_id, loader_id = _document(browser, session)
    except PolicyError as exc:
        raise GuardedClickPhaseError("document_identity") from exc
    if expected_document is not None and expected_document[:2] != (frame_id, loader_id):
        return {
            "ok": False,
            "error": "postcondition_document_changed",
        }, expected_document
    channel = browser._cdp
    if expected_document is None:
        channel.discard_committed_navigation(session, frame_id, loader_id)
    try:
        point = browser._click_point(tab, selector)
    except PolicyError as exc:
        raise GuardedClickPhaseError("target_resolution") from exc
    if not point.get("ok"):
        return point, expected_document
    url = point.get("previous_url")
    document = frame_id, loader_id, url
    if not url or (expected_document is not None and document != expected_document):
        return {"ok": False, "error": "postcondition_document_changed"}, document
    if channel.has_pending_navigation(session, frame_id):
        return {"ok": False, "error": "postcondition_navigation_pending"}, document

    try:
        context = browser.call(
            "Page.createIsolatedWorld",
            {"frameId": frame_id, "worldName": _WORLD},
            session,
            timeout=1,
        )["executionContextId"]
    except (PolicyError, KeyError) as exc:
        raise GuardedClickPhaseError("observer_context") from exc
    token = secrets.token_hex(16)
    timeout = condition["timeout_ms"]

    def evaluate(expression, *, wait=False):
        result = browser.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "contextId": context,
                "returnByValue": True,
                "awaitPromise": wait,
            },
            session,
            timeout=timeout / 1000 + 0.25 if wait else 1,
        )
        if result.get("exceptionDetails"):
            raise PolicyError("Browser click observation failed")
        return result.get("result", {}).get("value")

    x, y = point["x"], point["y"]
    options = json.dumps(
        dict(
            selector=condition["selector"],
            expected=condition["text"],
            buttonSelector=selector,
            url=url,
            x=x,
            y=y,
            timeout=timeout,
            armTimeout=_ARM_TIMEOUT_MS,
            token=token,
        )
    )
    try:
        armed = evaluate(f"{_WATCH}({options})")
    except PolicyError as exc:
        raise GuardedClickPhaseError("watch_arm") from exc
    if armed is not True:
        return {
            "ok": False,
            "error": "postcondition_unavailable_or_already_met",
        }, document
    watch = "globalThis.udbClickWatch"
    watch_matches = f"({watch}?.token === {json.dumps(token)})"

    def before_press():
        return evaluate(
            f"{watch_matches} && {watch}.canPress()"
        ) is True and not channel.has_pending_navigation(session, frame_id)

    confirmed = False
    try:
        try:
            pressed = browser._mouse_click(tab, x, y, before_press=before_press)
        except PolicyError as exc:
            raise GuardedClickPhaseError("input_dispatch") from exc
        if not pressed:
            return {"ok": False, "error": "postcondition_target_changed"}, document
        try:
            confirmed = (
                evaluate(f"{watch_matches} && {watch}.promise", wait=True) is True
                and evaluate(f"{watch_matches} && {watch}.confirmed()") is True
                and _document(browser, session) == (frame_id, loader_id)
                and not channel.has_pending_navigation(session, frame_id)
            )
        except PolicyError:
            confirmed = False
    finally:
        if not confirmed:
            try:
                evaluate(f"{watch_matches} && {watch}.cancel()")
            except PolicyError:
                # Navigation or the action deadline can invalidate the context.
                pass
    if confirmed:
        return dict(
            ok=True,
            clicked=True,
            replay_safe=False,
            postcondition_met=True,
            navigation_completed=False,
            navigation_observation_limited=True,
        ), document

    # A changing document can destroy the isolated world. Use the standard
    # navigation observer to report what happened, and stop the guarded batch.
    navigation = browser._wait_for_click_navigation(
        tab, url, previous_loader_id=loader_id, previous_frame_id=frame_id
    )
    return dict(
        ok=False,
        clicked=True,
        replay_safe=False,
        postcondition_met=False,
        observation_unavailable=True,
        **navigation,
    ), document
