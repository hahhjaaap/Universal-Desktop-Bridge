"""Fast click obtains the previous page URL from its actionable element probe."""

from __future__ import annotations

from udb.host_browser import Browser


def test_click_uses_one_actionability_evaluation_and_preserves_origin():
    browser = Browser.__new__(Browser)
    browser.tabs = {"owned-tab": "owned-session"}
    evaluation = []
    mouse = []
    observed = []

    def evaluate(tab, expression, timeout=10):
        evaluation.append(expression)
        assert expression != "location.href", (
            "A standalone URL read costs one extra CDP RPC"
        )
        assert "previous_url:location.href" in expression
        return {
            "ok": True,
            "x": 31,
            "y": 29,
            "previous_url": "https://old.example/private?token=secret",
        }

    def call(method, params=None, session=None, timeout=10):
        assert method == "Page.getFrameTree"
        return {"frameTree": {"frame": {"id": "main", "loaderId": "old-loader"}}}

    def navigation(tab, previous_url, **kwargs):
        observed.append((previous_url, kwargs))
        return {"navigation_completed": True, "url": "https://new.example/landing"}

    browser.evaluate = evaluate
    browser.call = call
    browser._mouse_click = lambda tab, x, y: mouse.append((tab, x, y))
    browser._wait_for_click_navigation = navigation
    result = browser.element("owned-tab", "click", selector="#continue")
    assert evaluation and len(evaluation) == 1
    assert mouse == [("owned-tab", 31, 29)]
    assert observed[0][0] == "https://old.example/private?token=secret"
    assert observed[0][1]["previous_loader_id"] == "old-loader"
    assert result == {
        "ok": True,
        "clicked": True,
        "replay_safe": False,
        "navigation_completed": True,
        "url": "https://new.example/landing",
    }
    assert "secret" not in str(result)


def test_click_without_origin_keeps_uncertain_non_navigation_receipt():
    browser = Browser.__new__(Browser)
    browser.tabs = {"owned-tab": "owned-session"}
    browser.evaluate = lambda *_args, **_kwargs: {"ok": True, "x": 2, "y": 3}
    browser.call = lambda *_args, **_kwargs: {"frameTree": {"frame": {}}}
    seen = []
    browser._mouse_click = lambda *args: seen.append(args)
    def navigation(tab, previous_url, **kwargs):
        assert previous_url is None, "missing actionable origin must stay unknown"
        return {"navigation_completed": False, "navigation_observation_limited": True}

    browser._wait_for_click_navigation = navigation
    result = browser.element(
        "owned-tab", "click", selector="#open", observe_navigation_ms=100
    )
    assert seen == [("owned-tab", 2, 3)]
    assert result["clicked"] and result["replay_safe"] is False
    assert result["navigation_observation_limited"] is True
