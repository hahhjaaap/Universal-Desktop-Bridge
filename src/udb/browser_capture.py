"""Bounded, worker-owned screenshot cache. No personal windows or profiles."""

from __future__ import annotations

import time

from .core import PolicyError
from .host_client import enabled
from .resources import require_capacity


class CaptureCache:
    def __init__(self):
        self.streams = {}

    def start(self, service, sid, tab):
        browser = service._session(sid, kind="browser")["object"]
        browser.sid(tab)
        if (sid, tab) not in self.streams and len(self.streams) >= 4:
            raise PolicyError("At most four owned capture streams")
        self.streams[(sid, tab)] = {"next": 0, "frame": None, "last_error": None}
        self.tick(service)
        return self.status(sid, tab)

    def stop(self, sid, tab=None):
        keys = [k for k in self.streams if k[0] == sid and (tab is None or k[1] == tab)]
        for key in keys:
            self.streams.pop(key)
        return {"stopped": bool(keys)}

    def tick(self, service):
        for (sid, tab), row in list(self.streams.items()):
            if time.monotonic() < row["next"]:
                continue
            row["next"] = time.monotonic() + 1
            try:
                if not enabled(service.agent):
                    self.stop(sid)
                    continue
                browser = service._session(sid, kind="browser")["object"]
                if getattr(browser, "visible", False) or getattr(
                    browser, "frozen", False
                ):
                    row.update(frame=None, last_error="owner_control_or_frozen")
                    continue
                require_capacity(service.resource, 128)
                before = getattr(browser, "deadline", None)
                try:
                    browser.deadline = time.monotonic() + 1
                    data = browser.screenshot(tab)
                finally:
                    if before is not None:
                        browser.deadline = before
                if not isinstance(data, str) or len(data) > 4 * 1048576:
                    raise PolicyError("Capture exceeds the 4 MiB cache limit")
                row.update(
                    frame={"png_base64": data, "captured_at": time.time()},
                    last_error=None,
                )
            except Exception as exc:
                row["last_error"] = type(exc).__name__

    def status(self, sid, tab):
        row = self.streams.get((sid, tab))
        if row is None:
            return {"active": False, "target_fps": 1}
        frame = row["frame"]
        return {
            "active": True,
            "target_fps": 1,
            "captured_at": frame["captured_at"] if frame else None,
            "age_ms": max(0, round((time.time() - frame["captured_at"]) * 1000))
            if frame
            else None,
            "last_error": row["last_error"],
        }

    def get(self, sid, tab, max_age_ms=3000):
        if type(max_age_ms) is not int or not 100 <= max_age_ms <= 10000:
            raise PolicyError("max_age_ms must be 100..10000")
        row = self.streams.get((sid, tab))
        if not row or not row["frame"] or row["last_error"]:
            raise PolicyError(
                "No valid cached image; start capture and inspect capture_status"
            )
        frame = row["frame"]
        age = (time.time() - frame["captured_at"]) * 1000
        if not -2000 <= age <= max_age_ms:
            raise PolicyError("Cached image is stale; inspect capture_status")
        return dict(frame, age_ms=max(0, round(age)), cached=True, target_fps=1)
