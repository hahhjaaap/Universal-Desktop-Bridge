"""Current-user desktop primitives. Caller must enforce a separate owner grant.

Never bypass UIPI, elevate, switch to a secure desktop or attach input queues.
Window IDs are observations with a short lifetime, not arbitrary HWND inputs.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import subprocess
import time
import uuid
from ctypes import wintypes as w
from pathlib import Path

from . import hyperspeed_perf as perf
from .computer_capture import encode_bgrx_png
from .core import PolicyError
from .desktop_guest import BitmapHeader, InputEvent, KeyInput, MouseInput
from .windows_actions import DESKTOP_ACTIONS, UIA_ACTIONS

_UIA_HELPER = Path(__file__).with_name("computer_uia.ps1")


class Desktop:
    def __init__(self, guard=None, control=None):
        import win32gui
        import win32process

        self.gui = win32gui
        self.process = win32process
        self.windows = {}
        self.guard = guard
        self.control = control
        self._uia_worker = None
        self.u = ctypes.WinDLL("user32", use_last_error=True)
        self.u.SendInput.argtypes = [w.UINT, ctypes.POINTER(InputEvent), ctypes.c_int]
        self.u.SendInput.restype = w.UINT
        self.u.OpenInputDesktop.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.u.OpenInputDesktop.restype = w.HANDLE
        self.u.GetUserObjectInformationW.argtypes = [
            w.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            w.DWORD,
            ctypes.POINTER(w.DWORD),
        ]
        self.u.CloseDesktop.argtypes = [w.HANDLE]
        self.dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
        self.dwm.DwmGetWindowAttribute.argtypes = [
            w.HWND,
            w.DWORD,
            ctypes.c_void_p,
            w.DWORD,
        ]
        self.dwm.DwmGetWindowAttribute.restype = ctypes.c_long

    def close(self):
        worker = getattr(self, "_uia_worker", None)
        if worker is not None:
            self._uia_worker = None
            worker.close()

    def is_cloaked(self, hwnd):
        """WS_VISIBLE alone also includes hidden UWP/virtual-desktop shells."""
        value = w.DWORD()
        if (
            self.dwm.DwmGetWindowAttribute(
                hwnd, 14, ctypes.byref(value), ctypes.sizeof(value)
            )
            != 0
        ):
            raise PolicyError("Window visibility could not be verified; list again")
        return bool(value.value)

    def interactive(self):
        if self.guard is not None and not self.guard():
            raise PolicyError("Computer access was revoked")
        handle = self.u.OpenInputDesktop(0, False, 1)
        if not handle:
            raise PolicyError("Interactive desktop is unavailable or locked")
        try:
            name = ctypes.create_unicode_buffer(256)
            needed = w.DWORD()
            if (
                not self.u.GetUserObjectInformationW(
                    handle, 2, name, ctypes.sizeof(name), ctypes.byref(needed)
                )
                or name.value.lower() != "default"
            ):
                raise PolicyError("Secure/locked desktop is not controllable by UDB")
        finally:
            self.u.CloseDesktop(handle)

    def listing(self):
        self.interactive()
        rows = []
        observed = {}
        # A single short-lived foreground observation describes this listing;
        # identity and visibility are freshly verified again by resolve().
        foreground = self.gui.GetForegroundWindow()

        def visit(hwnd, _):
            if not self.gui.IsWindowVisible(hwnd):
                return
            title = self.gui.GetWindowText(hwnd)
            if not title:
                return
            try:
                if self.is_cloaked(hwnd):
                    return
            except PolicyError:
                return  # A window may disappear while EnumWindows is running.
            pid = self.process.GetWindowThreadProcessId(hwnd)[1]
            kind = self.gui.GetClassName(hwnd)
            wid = uuid.uuid4().hex
            observed[wid] = (hwnd, pid, kind, time.monotonic() + 60)
            rows.append(
                dict(
                    window_id=wid,
                    title=title[:300],
                    pid=pid,
                    bounds=list(self.gui.GetWindowRect(hwnd)),
                    foreground=hwnd == foreground,
                    minimized=bool(self.gui.IsIconic(hwnd)),
                    class_name=kind,
                )
            )

        self.gui.EnumWindows(visit, None)
        self.windows = observed
        return dict(
            windows=rows,
            expires_in_seconds=60,
            coordinates="physical screen pixels",
            cloaked_windows_hidden=True,
        )

    @staticmethod
    def _chrome_image_path(pid):
        """Resolve a Chrome process image without trusting PATH or a window title."""
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        kernel.OpenProcess.restype = w.HANDLE
        kernel.QueryFullProcessImageNameW.argtypes = [
            w.HANDLE,
            w.DWORD,
            w.LPWSTR,
            ctypes.POINTER(w.DWORD),
        ]
        kernel.QueryFullProcessImageNameW.restype = w.BOOL
        kernel.CloseHandle.argtypes = [w.HANDLE]
        kernel.CloseHandle.restype = w.BOOL
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            size = w.DWORD(32768)
            image = ctypes.create_unicode_buffer(size.value)
            if not kernel.QueryFullProcessImageNameW(
                handle, 0, image, ctypes.byref(size)
            ):
                return None
            path = image.value
            if (
                path.lower()
                .replace("/", "\\")
                .endswith("\\google\\chrome\\application\\chrome.exe")
            ):
                return path
            return None
        finally:
            kernel.CloseHandle(handle)

    def _chrome_windows(self):
        """Observe only top-level windows belonging to real Chrome processes."""
        images = {}
        rows = []

        def visit(hwnd, _):
            if (
                not self.gui.IsWindowVisible(hwnd)
                or self.gui.GetClassName(hwnd) != "Chrome_WidgetWin_1"
            ):
                return
            pid = self.process.GetWindowThreadProcessId(hwnd)[1]
            if pid not in images:
                images[pid] = self._chrome_image_path(pid)
            if images[pid]:
                rows.append((hwnd, pid, images[pid]))

        self.gui.EnumWindows(visit, None)
        return rows

    def open_chrome_tab(self, url):
        """Ask an already-running Chrome to open a visible tab.

        Owner-granted computer access; NOT an owned CDP session. Only tab
        UIA runtime IDs are compared before/after to identify the new tab.
        Existing tab names, URLs and content are not read.
        """
        from .chrome_tab_identity import observe_tabs, register_new_tab
        from .host_browser import validate_url

        self.interactive()
        target = validate_url(url)
        # Open the validated URL directly; retired Aura markers are ignored.
        chrome_target = target
        before = self._chrome_windows()
        if not before:
            raise PolicyError(
                "No existing Google Chrome window; no browser was launched"
            )
        foreground = self.gui.GetForegroundWindow()
        chosen = next((row for row in before if row[0] == foreground), before[0])
        previous_tabs = observe_tabs(chosen[0])
        try:
            result = subprocess.run(
                [chosen[2], "--new-tab", chrome_target],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                timeout=15,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PolicyError(
                "Chrome did not acknowledge the new-tab request; inspect "
                "the browser before retrying"
            ) from exc
        if result.returncode != 0:
            raise PolicyError(
                "Chrome rejected the new-tab request; inspect before retrying"
            )
        after = self._chrome_windows()
        native_marker = register_new_tab(chosen[0], chosen[1], previous_tabs)
        return dict(
            requested=True,
            chrome_pid=chosen[1],
            chrome_windows_before=len(before),
            chrome_windows_after=len(after),
            existing_window_reused_observed=bool(after)
            and {row[0] for row in before} == {row[0] for row in after},
            branding_requested=False,
            branding_verified=False,
            native_tab_marker_verified=native_marker,
            dom_attached=False,
            user_input_injected=False,
        )

    def open_chatgpt(self):
        """Open only the official ChatGPT home; never inspect login or tabs.

        Prefer the verified existing-Chrome path. If there is no running
        Chrome window, ask Windows to launch the default URL handler once.
        A successful request never proves the page loaded or the user logged in.
        """
        url = "https://chatgpt.com/"
        self.interactive()
        if self._chrome_windows():
            result = self.open_chrome_tab(url)
            return {
                **result,
                "url": url,
                "launch_mode": "existing_chrome_tab",
                "browser_launch_verified": result["native_tab_marker_verified"],
                "page_loaded_verified": False,
                "login_verified": False,
                "replay_safe": False,
            }
        try:
            os.startfile(url)
        except (OSError, AttributeError) as exc:
            raise PolicyError(
                "Windows could not request the default browser; inspect "
                "the desktop before retrying"
            ) from exc
        return {
            "requested": True,
            "url": url,
            "launch_mode": "default_browser",
            "browser_launch_verified": False,
            "page_loaded_verified": False,
            "login_verified": False,
            "dom_attached": False,
            "user_input_injected": False,
            "replay_safe": False,
        }

    def verified_submit(self, hwnd, window_id, text, name, automation_id, submit_name):
        """Verify exact editor contents before invoking one uniquely named button.

        This reduces remote MCP round trips, not Windows UI authorization.
        Never discards a pre-existing draft and never retries a submission.
        """
        if not isinstance(text, str) or not 1 <= len(text) <= 5000:
            raise PolicyError("Submission text must contain 1..5000 characters")
        if not isinstance(name, str) or len(name) > 120:
            raise PolicyError("Editor name must be at most 120 characters")
        if not isinstance(automation_id, str) or len(automation_id) > 120:
            raise PolicyError("Editor automation_id must be at most 120 characters")
        if not name and not automation_id:
            raise PolicyError("Provide an exact editor name or automation_id")
        if not isinstance(submit_name, str) or not 1 <= len(submit_name) <= 120:
            raise PolicyError("Provide the exact submit button name (1..120)")
        if "\n" in submit_name or "\r" in submit_name:
            raise PolicyError("Submit button name must be one line")

        selector = dict(name=name, automation_id=automation_id, control_type="Edit")
        first = self.uia(hwnd, "read_text", limit=5000, **selector)
        initial = first["text"].rstrip("\r\n")
        # Some contenteditable controls expose the placeholder as TextPattern.
        # Treat only the exact editor label as a potential placeholder.
        if first.get("truncated") or initial not in ("", name):
            raise PolicyError("Editor is not empty; existing draft preserved")
        self.uia(hwnd, "uia_focus", **selector)
        self._dispatch("type", window_id=window_id, text=text)
        observed = self.uia(hwnd, "read_text", limit=5000, **selector)
        if observed.get("truncated") or observed.get("text") != text:
            raise PolicyError(
                "Input does not exactly match requested text; nothing submitted. "
                "Inspect the editor before retrying."
            )
        control = getattr(self, "control", None)
        if control:
            control.check()
        if self.gui.GetForegroundWindow() != hwnd:
            raise PolicyError("Foreground changed; nothing submitted")
        result = self.uia(hwnd, "invoke", name=submit_name, control_type="Button")
        return dict(
            verified_text=True,
            submit_requested=result.get("invoked") is True,
            reply_verified=False,
            replay_safe=False,
            application_submission_verified=False,
            input_characters=len(text),
        )

    def chatgpt_roundtrip(self, hwnd, window_id, text, wait_ms, fast_reply=False):
        """One remote call: verify blank ChatGPT, submit, and wait for one reply.

        The request is NOT idempotent. A timeout after submit must never
        trigger a replay; inspect the same browser window instead.
        """
        if not isinstance(text, str) or not 1 <= len(text) <= 5000:
            raise PolicyError("ChatGPT message must contain 1..5000 characters")
        if type(wait_ms) is not int or not 500 <= wait_ms <= 10000:
            raise PolicyError("ChatGPT reply wait_ms must be 500..10000")
        if type(fast_reply) is not bool:
            raise PolicyError("fast_reply must be a boolean")

        started = time.monotonic()
        # One targeted UIA pass checks this exact ChatGPT document, blank
        # editor, and absent prior assistant messages, then focuses the editor.
        # A second pass verifies *exact* text and invokes Send once.
        # Physical typing still uses the original owner-guarded SendInput.
        self.uia(hwnd, "chatgpt_prepare", text=text)
        self._dispatch("type", window_id=window_id, text=text)
        control = getattr(self, "control", None)
        if control:
            control.check()
        if self.gui.GetForegroundWindow() != hwnd:
            raise PolicyError("Foreground changed; nothing submitted")
        confirmed = self.uia(hwnd, "chatgpt_commit", text=text)
        sent = {
            "submit_requested": confirmed.get("invoked") is True,
            "verified_text": confirmed.get("verified_text") is True,
        }
        if not sent["submit_requested"] or not sent["verified_text"]:
            raise PolicyError("ChatGPT submit not verified; do not retry")
        submitted_ms = round((time.monotonic() - started) * 1000)
        # One UIA process polls locally instead of one remote MCP RPC/poll.
        # If UIA fails after sending, outcome is unknown and not replay-safe.
        reply = self.uia(
            hwnd,
            "poll_chatgpt_reply",
            text=text,
            wait_ms=wait_ms,
            condition="first_text" if fast_reply else "exists",
            limit=3000,
        )
        total_ms = round((time.monotonic() - started) * 1000)
        complete = bool(reply.get("completed"))
        partial = bool(reply.get("partial")) and not complete
        status = (
            "complete"
            if complete
            else "partial_reply"
            if fast_reply and partial
            else "reply_timeout"
        )
        return {
            "submit_requested": sent["submit_requested"],
            "verified_text": sent["verified_text"],
            "reply_verified": complete,
            "reply_partial": partial,
            "reply": reply.get("reply", ""),
            "reply_truncated": reply.get("truncated", False),
            "status": status,
            "timings_ms": {
                "desktop_operation": total_ms,
                "verified_submit": submitted_ms,
                "reply_wait": round(reply.get("elapsed_ms", 0)),
                "reply_first_text": round(reply.get("first_reply_ms", -1)),
            },
            "replay_safe": False,
            "login_verified": False,
            "response_observed_in_ui": bool(reply.get("completed")),
        }

    def chatgpt_read_reply(self, hwnd, text, wait_ms, fast_reply=False):
        """Observe an exact already-sent prompt without sending or retrying."""
        if not isinstance(text, str) or not 1 <= len(text) <= 5000:
            raise PolicyError("Expected ChatGPT prompt must be 1..5000 characters")
        if type(wait_ms) is not int or not 500 <= wait_ms <= 10000:
            raise PolicyError("ChatGPT reply wait_ms must be 500..10000")
        if type(fast_reply) is not bool:
            raise PolicyError("fast_reply must be a boolean")
        started = time.monotonic()
        result = self.uia(
            hwnd,
            "poll_chatgpt_reply",
            text=text,
            wait_ms=wait_ms,
            condition="first_text" if fast_reply else "exists",
            limit=3000,
        )
        complete = bool(result.get("completed"))
        partial = bool(result.get("partial")) and not complete
        return {
            "read_only": True,
            "reply_verified": complete,
            "reply_partial": partial,
            "reply": result.get("reply", ""),
            "reply_truncated": result.get("truncated", False),
            "status": (
                "complete"
                if complete
                else "partial_reply"
                if fast_reply and partial
                else "reply_timeout"
            ),
            "timings_ms": {
                "reply_wait": round(result.get("elapsed_ms", 0)),
                "observer_wall": round((time.monotonic() - started) * 1000),
                "reply_first_text": round(result.get("first_reply_ms", -1)),
            },
            "replay_safe": True,
        }

    def resolve(self, window_id, focus=True):
        self.interactive()
        row = self.windows.get(window_id)
        if not row:
            raise PolicyError("Observe windows with computer_desktop list first")
        hwnd, pid, kind, until = row
        if (
            time.monotonic() > until
            or not self.gui.IsWindow(hwnd)
            or not self.gui.IsWindowVisible(hwnd)
            or self.process.GetWindowThreadProcessId(hwnd)[1] != pid
            or self.gui.GetClassName(hwnd) != kind
            or self.is_cloaked(hwnd)
        ):
            raise PolicyError("Window observation expired or changed; list again")
        if focus and self.gui.GetForegroundWindow() != hwnd:
            try:
                self.gui.ShowWindow(hwnd, 9)
                self.gui.SetForegroundWindow(hwnd)
            except Exception:
                pass  # Foreground APIs are best-effort; verify focus below.
            if self.gui.GetForegroundWindow() != hwnd:
                self.uia(hwnd, "uia_focus")
        if focus and self.gui.GetForegroundWindow() != hwnd:
            raise PolicyError("Target is not foreground; no input was sent")
        return hwnd

    def send(self, hwnd, events):
        control = getattr(self, "control", None)
        if control:
            control.check()
        if self.guard is not None and not self.guard():
            raise PolicyError("Computer access was revoked; input stopped")
        if self.gui.GetForegroundWindow() != hwnd:
            raise PolicyError(
                "Foreground changed; input stopped. Inspect before retrying"
            )
        values = (InputEvent * len(events))(*events)
        if self.u.SendInput(len(events), values, ctypes.sizeof(InputEvent)) != len(
            events
        ):
            raise PolicyError(
                "Windows blocked or partially accepted input; inspect before retrying. No elevation/UAC bypass"
            )

        if control:
            control.note_injected()

    def key(self, vk=0, scan=0, flags=0):
        event = InputEvent()
        event.type = 1
        event.data.ki = KeyInput(vk, scan, flags, 0, 0)
        return event

    def uia(
        self,
        hwnd,
        mode,
        text="",
        automation_id="",
        name="",
        control_type="",
        wait_ms=0,
        condition="exists",
        checked=None,
        limit=5000,
    ):
        self.interactive()
        pid = self.process.GetWindowThreadProcessId(hwnd)[1]
        request = dict(
            hwnd=hwnd,
            pid=pid,
            mode=mode,
            text=text,
            automation_id=automation_id,
            name=name,
            control_type=control_type,
            wait_ms=wait_ms,
            condition=condition,
            checked=checked,
            limit=limit,
        )
        exe = (
            Path(os.environ["SystemRoot"])
            / "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        helper = _UIA_HELPER
        deadline = 7 + (
            wait_ms / 1000 if mode in ("wait_for", "poll_chatgpt_reply") else 0
        )
        from .uia_worker import PersistentUIA, enabled

        if enabled() or getattr(self, "_batch_uia", False):
            if getattr(self, "_uia_worker", None) is None:
                self._uia_worker = PersistentUIA(exe, helper)
            # A rejected, missing or late response never falls back to legacy
            # subprocess.run; that could replay a successful mutation.
            data = perf.timed_call(
                "desktop.uia",
                "execution",
                self._uia_worker.call,
                request,
                deadline,
            )
            if not data.get("ok"):
                raise PolicyError(
                    "UI Automation was refused; inspect the target before retrying."
                )
            return data
        try:
            result = perf.timed_call(
                "desktop.uia",
                "execution",
                subprocess.run,
                [
                    str(exe),
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(helper),
                ],
                input=json.dumps(request, separators=(",", ":")),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=deadline,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                shell=False,
            )
            if len(result.stdout) > 262144:
                raise ValueError("UIA response exceeds limit")
            if result.returncode:
                raise ValueError("UIA command returned nonzero")
            data = json.loads(result.stdout)
            if not isinstance(data, dict) or not data.get("ok"):
                raise ValueError("UIA declined")
            return data
        except (OSError, ValueError, subprocess.TimeoutExpired):
            raise PolicyError(
                "UI Automation was refused or timed out; outcome may be unknown, inspect the target before retrying. No input/elevation fallback was used."
            ) from None

    def dispatch(
        self,
        action,
        window_id="",
        text="",
        x=0,
        y=0,
        key="",
        delta=0,
        automation_id="",
        name="",
        control_type="",
        **extra,
    ):
        self.u.SetThreadDpiAwarenessContext.argtypes = [w.HANDLE]
        self.u.SetThreadDpiAwarenessContext.restype = w.HANDLE
        previous = self.u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        if not previous:
            raise PolicyError("Per-monitor DPI context unavailable")
        try:
            return self._dispatch(
                action,
                window_id,
                text,
                x,
                y,
                key,
                delta,
                automation_id,
                name,
                control_type,
                **extra,
            )
        finally:
            self.u.SetThreadDpiAwarenessContext(previous)

    def _dispatch(
        self,
        action,
        window_id="",
        text="",
        x=0,
        y=0,
        key="",
        delta=0,
        automation_id="",
        name="",
        control_type="",
        button="left",
        clicks=1,
        from_x=None,
        from_y=None,
        duration_ms=250,
        horizontal=False,
        width=0,
        height=0,
        window_state="",
        wait_ms=1000,
        condition="exists",
        steps=None,
        display_index=-1,
        region=None,
        checked=None,
        limit=5000,
        submit_name="",
        fast_reply=False,
    ):
        self.validate_options(
            action, button, clicks, duration_ms, horizontal, wait_ms, condition
        )
        if action == "set_checked" and type(checked) is not bool:
            raise PolicyError("set_checked requires checked=true or false")
        if action == "read_text" and (type(limit) is not int or not 1 <= limit <= 5000):
            raise PolicyError("read_text limit must be 1..5000")
        if action == "select" and (not isinstance(text, str) or len(text) > 500):
            raise PolicyError("Selection label must be a string up to 500 characters")
        control = getattr(self, "control", None)
        if action == "control_status":
            return (
                control.status()
                if control
                else {"state": "unavailable", "exclusive": False}
            )
        if control and action not in {
            "list",
            "displays",
            "snapshot",
            "screenshot",
            "wait_for",
            "batch",
            "read_text",
            "chatgpt_read_reply",
        }:
            control.check()
        if action == "list":
            return self.listing()
        if action == "displays":
            self.interactive()
            return self.display_inventory()
        if action == "screenshot" and (display_index != -1 or region is not None):
            self.interactive()
            return self.display_capture(display_index, region)
        if action == "batch":
            return self.batch(window_id, steps)
        if action == "open_chrome_tab":
            return self.open_chrome_tab(text)
        if action == "open_chatgpt":
            return self.open_chatgpt()
        if action in ("chatgpt_roundtrip", "chatgpt_read_reply") and not window_id:
            # Resolve only an already-foreground, visible, real Chrome window.
            # A unique local observation avoids another remote list RPC.
            rows = self.listing()["windows"]
            candidates = [
                row
                for row in rows
                if row["title"] == "ChatGPT - Google Chrome"
                and row["foreground"]
                and not row["minimized"]
                and self._chrome_image_path(row["pid"]) is not None
            ]
            if len(candidates) != 1:
                raise PolicyError(
                    "No unique foreground ChatGPT Chrome window; nothing sent"
                )
            window_id = candidates[0]["window_id"]
        hwnd = self.resolve(
            window_id,
            focus=action
            not in (
                "screenshot",
                "snapshot",
                "set_value",
                "invoke",
                "uia_focus",
                "wait_for",
                "move_window",
                "resize_window",
                "window_state",
                "close_window",
                "read_text",
                "set_checked",
                "select",
                "expand",
                "collapse",
                "scroll_into_view",
                "chatgpt_read_reply",
            ),
        )
        if action == "verified_submit":
            return self.verified_submit(
                hwnd, window_id, text, name, automation_id, submit_name
            )
        if action == "chatgpt_roundtrip":
            return self.chatgpt_roundtrip(hwnd, window_id, text, wait_ms, fast_reply)
        if action == "chatgpt_read_reply":
            return self.chatgpt_read_reply(hwnd, text, wait_ms, fast_reply)
        if action in UIA_ACTIONS:
            return self.uia(
                hwnd,
                action,
                text,
                automation_id,
                name,
                control_type,
                wait_ms,
                condition,
                checked,
                limit,
            )
        if action == "close_window":
            self.gui.PostMessage(hwnd, 0x0010, 0, 0)
            deadline = time.monotonic() + min(wait_ms, 1000) / 1000
            while self.gui.IsWindow(hwnd) and time.monotonic() < deadline:
                time.sleep(0.04)
            return dict(
                requested=True,
                closed_observed=not self.gui.IsWindow(hwnd),
                replay_safe=False,
                forced=False,
            )
        if action in ("move_window", "resize_window", "window_state"):
            return self.window_action(hwnd, action, x, y, width, height, window_state)
        if action == "focus":
            return dict(foreground=True)
        if action == "screenshot":
            return self.screenshot(hwnd)
        self.u.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.u.GetAsyncKeyState.restype = ctypes.c_short
        if any(
            self.u.GetAsyncKeyState(vk) & 0x8000 for vk in (1, 2, 16, 17, 18, 91, 92)
        ):
            raise PolicyError(
                "User input is active; wait until mouse buttons/modifiers are released"
            )
        if action in ("mouse_move", "drag"):
            return self.mouse_action(
                hwnd, action, x, y, from_x, from_y, duration_ms, button
            )
        if action == "type":
            if not isinstance(text, str) or len(text) > 5000:
                raise PolicyError("Type at most 5000 characters per call")
            data = text.encode("utf-16-le")
            for at in range(0, len(data), 64):
                events = []
                for i in range(at, min(at + 64, len(data)), 2):
                    unit = int.from_bytes(data[i : i + 2], "little")
                    events.extend(
                        [self.key(scan=unit, flags=4), self.key(scan=unit, flags=6)]
                    )
                self.send(hwnd, events)
            return dict(injected_characters=len(text), verified_application_text=False)
        if action == "key":
            names = {
                "CTRL": 17,
                "ALT": 18,
                "SHIFT": 16,
                "ENTER": 13,
                "TAB": 9,
                "ESC": 27,
                "BACKSPACE": 8,
                "DELETE": 46,
                "HOME": 36,
                "END": 35,
                "LEFT": 37,
                "UP": 38,
                "RIGHT": 39,
                "DOWN": 40,
                "SPACE": 32,
                "WIN": 91,
                "PAGEUP": 33,
                "PAGEDOWN": 34,
            }
            names.update({chr(n): n for n in range(65, 91)})
            names.update({str(n): 48 + n for n in range(10)})
            names.update({"F" + str(n): 111 + n for n in range(1, 13)})
            parts = key.upper().split("+")
            if not 1 <= len(parts) <= 4 or any(k not in names for k in parts):
                raise PolicyError("Unsupported key chord")
            if set(parts) in (
                {"WIN", "L"},
                {"CTRL", "ALT", "DELETE"},
                {"CTRL", "ALT", "SHIFT", "BACKSPACE"},
            ):
                raise PolicyError("Secure/lock key combinations are refused")
            pressed = []
            try:
                for k in parts:
                    vk = names[k]
                    self.send(
                        hwnd,
                        [self.key(vk, flags=1 if vk in (*range(33, 47), 91) else 0)],
                    )
                    pressed.append(vk)
            finally:
                # Release only keys injected by this call, even if foreground changed.
                for vk in reversed(pressed):
                    event = self.key(
                        vk, flags=2 | (1 if vk in (*range(33, 47), 91) else 0)
                    )
                    values = (InputEvent * 1)(event)
                    self.u.SendInput(1, values, ctypes.sizeof(InputEvent))
            return dict(injected_key=key, verified_application_result=False)
        if action in ("click", "scroll"):
            if any(
                isinstance(v, bool) or not isinstance(v, int) for v in (x, y, delta)
            ):
                raise PolicyError("Coordinates/delta must be integers")
            left, top, right, bottom = self.gui.GetWindowRect(hwnd)
            if not left <= x < right or not top <= y < bottom:
                raise PolicyError("Point is outside the observed target window")
            if action == "scroll" and not -1200 <= delta <= 1200:
                raise PolicyError("Scroll delta must be -1200..1200")

            def check_point():
                hit = self.gui.WindowFromPoint((x, y))
                self.u.GetAncestor.argtypes = [w.HWND, w.UINT]
                self.u.GetAncestor.restype = w.HWND
                if not hit or self.u.GetAncestor(hit, 2) != hwnd:
                    raise PolicyError(
                        "Another window covers this point; inspect before clicking or scrolling"
                    )

            check_point()
            import win32api

            win32api.SetCursorPos((x, y))
            if control:
                control.note_injected()
            down, up = {"left": (2, 4), "right": (8, 16), "middle": (32, 64)}[button]
            if action == "click":
                flags = [(down, 0), (up, 0)] * clicks
            else:
                flags = [(0x1000 if horizontal else 0x800, delta & 0xFFFFFFFF)]
            events = []
            for flag, data in flags:
                e = InputEvent()
                e.type = 0
                e.data.mi = MouseInput(0, 0, data, flag, 0, 0)
                events.append(e)
            try:
                check_point()
                self.send(hwnd, events)
            except PolicyError:
                if action == "click":
                    e = InputEvent()
                    e.type = 0
                    e.data.mi = MouseInput(0, 0, 0, up, 0, 0)
                    self.u.SendInput(1, (InputEvent * 1)(e), ctypes.sizeof(InputEvent))
                raise
            return dict(injected=True, verified_application_result=False)
        raise PolicyError("Unsupported desktop action")

    @staticmethod
    def validate_options(
        action,
        button="left",
        clicks=1,
        duration_ms=250,
        horizontal=False,
        wait_ms=1000,
        condition="exists",
    ):
        if action not in DESKTOP_ACTIONS:
            raise PolicyError("Unsupported desktop action")
        if (
            button not in ("left", "right", "middle")
            or type(clicks) is not int
            or not 1 <= clicks <= 2
        ):
            raise PolicyError("Button left/right/middle; clicks 1..2")
        if (
            type(duration_ms) is not int
            or not 0 <= duration_ms <= 1500
            or type(horizontal) is not bool
        ):
            raise PolicyError("duration_ms 0..1500; horizontal boolean")
        if (
            type(wait_ms) is not int
            or not 0 <= wait_ms <= 10000
            or condition not in ("exists", "absent", "enabled")
        ):
            raise PolicyError("wait_ms 0..10000; condition exists/absent/enabled")

    def batch(self, window_id, steps):
        """Execute one bounded desktop workflow without extra remote round trips.

        Optional when and depends_on guards use only exact equality against
        earlier observed result fields. verify examines the current result.
        All guards are validated before any Windows operation. A failed
        verification of a mutating step is outcome-unknown, never retried.
        """
        if not isinstance(steps, list) or not 1 <= len(steps) <= 12:
            raise PolicyError("Batch needs 1..12 steps")
        import inspect

        metadata = frozenset({"when", "verify", "depends_on", "return_result"})
        evidence_fields = frozenset(
            {
                "ok",
                "state",
                "visible",
                "enabled",
                "exists",
                "found",
                "foreground",
                "matched",
                "paused",
                "checked",
                "selected",
                "changed",
                "clicked",
                "injected",
                "requested",
                "closed_observed",
                "timed_out",
                "truncated",
                "text",
            }
        )
        fields = set(inspect.signature(self._dispatch).parameters) - {"steps"}
        forbidden = {
            "list",
            "batch",
            "screenshot",
            "displays",
            "open_chrome_tab",
            "open_chatgpt",
            "verified_submit",
            "chatgpt_roundtrip",
            "chatgpt_read_reply",
        }

        def validate_predicate(value, *, current, previous):
            allowed = (
                {"field", "equals", "step_index"}
                if previous
                else {
                    "field",
                    "equals",
                }
            )
            if not isinstance(value, dict) or set(value) != allowed:
                raise PolicyError("Invalid desktop batch evidence predicate")
            if (
                not isinstance(value["field"], str)
                or value["field"] not in evidence_fields
            ):
                raise PolicyError("Unsupported desktop batch observation field")
            expected = value["equals"]
            if not (
                type(expected) is bool
                or type(expected) is int
                and -1000000000 <= expected <= 1000000000
                or type(expected) is str
                and len(expected) <= 160
            ):
                raise PolicyError("Desktop batch expected value must be bounded")
            if previous and (
                type(value["step_index"]) is not int
                or not 0 <= value["step_index"] < current
            ):
                raise PolicyError("Desktop batch guards require an earlier step")

        # Validate the entire plan before sending any Windows input.
        for index, row in enumerate(steps):
            if (
                not isinstance(row, dict)
                or set(row) - fields - metadata
                or not isinstance(row.get("action"), str)
                or row.get("action") in forbidden
                or "action" not in row
            ):
                raise PolicyError("Invalid/nested batch step; capture/list separately")
            self.validate_options(
                row["action"],
                **{
                    k: row[k]
                    for k in (
                        "button",
                        "clicks",
                        "duration_ms",
                        "horizontal",
                        "wait_ms",
                        "condition",
                    )
                    if k in row
                },
            )
            if "when" in row:
                validate_predicate(row["when"], current=index, previous=True)
            if "verify" in row:
                validate_predicate(row["verify"], current=index, previous=False)
            if "return_result" in row and type(row["return_result"]) is not bool:
                raise PolicyError("Desktop batch return_result must be boolean")
            parents = row.get("depends_on", [])
            if (
                not isinstance(parents, list)
                or any(type(p) is not int or not 0 <= p < index for p in parents)
                or len(set(parents)) != len(parents)
            ):
                raise PolicyError("Desktop batch dependencies must be earlier steps")

        return self._execute_batch_local_uia(window_id, steps)

    def _execute_batch_local_uia(self, window_id, steps):
        """Amortize one PowerShell UIA startup within one prevalidated batch.

        The default one-shot UIA behavior outside batches remains unchanged.
        This scoped helper is never shared between separate batch requests.
        Each action still checks interactive access, HWND/PID and UIA policies.
        No fallback or automatic replay after any uncertain mutation.
        """
        from .uia_worker import enabled as persistent_uia_enabled

        scoped = (
            not persistent_uia_enabled()
            and sum(row["action"] in UIA_ACTIONS for row in steps) >= 2
        )
        if scoped:
            self._batch_uia = True
        try:
            return self._run_validated_batch(window_id, steps)
        finally:
            if scoped:
                self._batch_uia = False
                worker = getattr(self, "_uia_worker", None)
                self._uia_worker = None
                if worker is not None:
                    worker.close()

    def _run_validated_batch(self, window_id, steps):
        from .fastpath import matches
        from .windows_actions import READ_ACTIONS

        metadata = frozenset({"when", "verify", "depends_on", "return_result"})
        deadline = time.monotonic() + 20
        results = []
        observations = {}
        completed = 0
        for index, row in enumerate(steps):
            try:
                if time.monotonic() > deadline:
                    raise PolicyError("Batch time budget exceeded")
                if any(
                    observations[parent] is None for parent in row.get("depends_on", [])
                ):
                    observations[index] = None
                    results.append({"index": index, "skipped": True})
                    continue
                if "when" in row:
                    previous = row["when"]["step_index"]
                    if observations[previous] is None:
                        observations[index] = None
                        results.append({"index": index, "skipped": True})
                        continue
                    if not matches(observations[previous], row["when"]):
                        observations[index] = None
                        results.append({"index": index, "skipped": True})
                        continue
                args = {key: val for key, val in row.items() if key not in metadata}
                args.setdefault("window_id", window_id)
                value = self._dispatch(**args)
                if "verify" in row:
                    try:
                        verified = matches(value, row["verify"])
                    except PolicyError:
                        verified = False
                    if not verified:
                        result = {"index": index, "verified": False}
                        if row.get("return_result", True):
                            result["result"] = value
                        results.append(result)
                        return {
                            "ok": False,
                            "completed_steps": completed,
                            "failed_index": index,
                            "error": "Desktop batch verification failed",
                            "outcome_unknown": row["action"] not in READ_ACTIONS,
                            "results": results,
                            "rollback": False,
                        }
                observations[index] = value
                item = {"index": index}
                if row.get("return_result", True):
                    item["result"] = value
                if "verify" in row:
                    item["verified"] = True
                results.append(item)
                completed += 1
            except (PolicyError, OSError, ValueError, TypeError) as exc:
                return {
                    "ok": False,
                    "completed_steps": completed,
                    "failed_index": index,
                    "error": str(exc),
                    "results": results,
                    "rollback": False,
                }
        return {
            "ok": True,
            "completed_steps": completed,
            "results": results,
            "rollback": False,
        }

    def window_action(self, hwnd, action, x, y, width, height, state):
        if action == "window_state":
            modes = {"restore": 4, "minimize": 6, "maximize": 3}
            if state not in modes:
                raise PolicyError("window_state restore/minimize/maximize")
            self.gui.ShowWindow(hwnd, modes[state])
        else:
            if self.gui.IsIconic(hwnd):
                raise PolicyError("Restore the observed window before moving/resizing")
            if any(type(v) is not int for v in (x, y, width, height)):
                raise PolicyError("Integer window geometry required")
            left, top, right, bottom = self.gui.GetWindowRect(hwnd)
            box = (
                (x, y, x + right - left, y + bottom - top)
                if action == "move_window"
                else (left, top, left + width, top + height)
            )
            if action == "resize_window" and not (
                96 <= width <= 8192 and 64 <= height <= 8192
            ):
                raise PolicyError("Window dimensions out of range")
            monitors = self.display_inventory()["displays"]
            if not any(
                min(box[2], m["work_area"][2]) - max(box[0], m["work_area"][0]) >= 32
                and min(box[3], m["work_area"][3]) - max(box[1], m["work_area"][1])
                >= 32
                for m in monitors
            ):
                raise PolicyError("Window must remain visible on an active display")
            flags = 0x4 | 0x10 | (0x1 if action == "move_window" else 0x2)
            self.gui.SetWindowPos(hwnd, 0, x, y, width, height, flags)
        return dict(
            bounds=list(self.gui.GetWindowRect(hwnd)),
            minimized=bool(self.gui.IsIconic(hwnd)),
            foreground=hwnd == self.gui.GetForegroundWindow(),
        )

    def checked_point(self, hwnd, x, y):
        if type(x) is not int or type(y) is not int:
            raise PolicyError("Integer physical coordinates required")
        left, top, right, bottom = self.gui.GetWindowRect(hwnd)
        if not left <= x < right or not top <= y < bottom:
            raise PolicyError("Point outside observed window")
        hit = self.gui.WindowFromPoint((x, y))
        self.u.GetAncestor.argtypes = [w.HWND, w.UINT]
        self.u.GetAncestor.restype = w.HWND
        if not hit or self.u.GetAncestor(hit, 2) != hwnd:
            raise PolicyError("Another window covers target point")

    def mouse_action(self, hwnd, action, x, y, from_x, from_y, duration_ms, button):
        import win32api

        self.checked_point(hwnd, x, y)
        down, up = {"left": (2, 4), "right": (8, 16), "middle": (32, 64)}[button]
        pressed = False
        if action == "drag":
            self.checked_point(hwnd, from_x, from_y)
            win32api.SetCursorPos((from_x, from_y))
            if getattr(self, "control", None):
                self.control.note_injected()
            event = InputEvent()
            event.type = 0
            event.data.mi = MouseInput(0, 0, 0, down, 0, 0)
            self.send(hwnd, [event])
            pressed = True
            start = (from_x, from_y)
        else:
            start = win32api.GetCursorPos()
        last = start
        try:
            count = max(1, duration_ms // 25)
            for i in range(1, count + 1):
                self.interactive()
                if self.gui.GetForegroundWindow() != hwnd:
                    raise PolicyError("Foreground changed; pointer action stopped")
                actual = win32api.GetCursorPos()
                if i > 1 and (
                    abs(actual[0] - last[0]) > 3 or abs(actual[1] - last[1]) > 3
                ):
                    raise PolicyError("User moved pointer; action stopped")
                point = (
                    round(start[0] + (x - start[0]) * i / count),
                    round(start[1] + (y - start[1]) * i / count),
                )
                if action == "drag":
                    self.checked_point(hwnd, *point)
                if getattr(self, "control", None):
                    self.control.check()
                win32api.SetCursorPos(point)
                if getattr(self, "control", None):
                    self.control.note_injected()
                last = point
                if duration_ms:
                    time.sleep(duration_ms / count / 1000)
        finally:
            if pressed:
                event = InputEvent()
                event.type = 0
                event.data.mi = MouseInput(0, 0, 0, up, 0, 0)
                self.u.SendInput(1, (InputEvent * 1)(event), ctypes.sizeof(InputEvent))
        return dict(injected=True, cursor=list(last), verified_application_result=False)

    def display_inventory(self):
        import win32api

        rows = []
        for index, (handle, _, bounds) in enumerate(win32api.EnumDisplayMonitors()):
            info = win32api.GetMonitorInfo(handle)
            dpi = None
            try:
                sh = ctypes.WinDLL("shcore")
                fn = sh.GetDpiForMonitor
                fn.argtypes = [
                    w.HANDLE,
                    ctypes.c_int,
                    ctypes.POINTER(w.UINT),
                    ctypes.POINTER(w.UINT),
                ]
                dx = w.UINT()
                dy = w.UINT()
                if fn(int(handle), 0, ctypes.byref(dx), ctypes.byref(dy)) == 0:
                    dpi = [dx.value, dy.value]
            except (OSError, AttributeError):
                pass
            rows.append(
                dict(
                    index=index,
                    bounds=list(bounds),
                    work_area=list(info["Work"]),
                    primary=bool(info["Flags"] & 1),
                    dpi=dpi,
                    scale=None if dpi is None else [dpi[0] / 96, dpi[1] / 96],
                )
            )
        return dict(displays=rows, coordinates="physical screen pixels")

    def display_capture(self, index, region):
        displays = self.display_inventory()["displays"]
        if region is not None:
            if (
                not isinstance(region, list)
                or len(region) != 4
                or any(type(v) is not int for v in region)
            ):
                raise PolicyError("region is [left,top,right,bottom]")
            left, top, right, bottom = region
            if (
                left >= right
                or top >= bottom
                or not any(
                    left >= m["bounds"][0]
                    and top >= m["bounds"][1]
                    and right <= m["bounds"][2]
                    and bottom <= m["bounds"][3]
                    for m in displays
                )
            ):
                raise PolicyError("Region must fit inside one active display")
            return self.capture(region)
        if type(index) is not int or not 0 <= index < len(displays):
            raise PolicyError("Unknown display index; call displays first")
        return self.capture(displays[index]["bounds"])

    def screenshot(self, hwnd):
        # This backend captures screen pixels, not an isolated compositor frame.
        # Never silently return an occluding application's pixels as this window.
        identity = (
            self.process.GetWindowThreadProcessId(hwnd)[1],
            self.gui.GetClassName(hwnd),
        )
        box = self.visible_window_box(hwnd)
        result = self.capture(box)
        if self.visible_window_box(hwnd) != box or identity != (
            self.process.GetWindowThreadProcessId(hwnd)[1],
            self.gui.GetClassName(hwnd),
        ):
            raise PolicyError("Window changed during capture; screenshot discarded")
        return dict(
            result,
            source="visible_window_region",
            window_content_isolated=False,
            occlusion_checked=True,
        )

    def visible_window_box(self, hwnd):
        self.interactive()
        if (
            not self.gui.IsWindow(hwnd)
            or not self.gui.IsWindowVisible(hwnd)
            or self.gui.IsIconic(hwnd)
            or self.is_cloaked(hwnd)
            or self.gui.GetForegroundWindow() != hwnd
        ):
            raise PolicyError(
                "Window screenshot requires a visible, restored foreground window; "
                "no focus or screen-capture fallback was used"
            )
        left, top, right, bottom = self.gui.GetWindowRect(hwnd)
        displays = self.display_inventory()["displays"]
        if not displays:
            raise PolicyError("No active display for window screenshot")
        # Maximized windows can have invisible resize borders outside a monitor.
        box = (
            max(left, min(m["bounds"][0] for m in displays)),
            max(top, min(m["bounds"][1] for m in displays)),
            min(right, max(m["bounds"][2] for m in displays)),
            min(bottom, max(m["bounds"][3] for m in displays)),
        )
        if box[0] >= box[2] or box[1] >= box[3]:
            raise PolicyError("Window has no visible screen area")
        reached = False
        covered = False

        def above(other, _):
            nonlocal reached, covered
            if reached:
                return
            if other == hwnd:
                reached = True
                return
            if (
                not self.gui.IsWindowVisible(other)
                or self.gui.IsIconic(other)
                or self.is_cloaked(other)
            ):
                return
            bounds = self.gui.GetWindowRect(other)
            if min(box[2], bounds[2]) > max(box[0], bounds[0]) and min(
                box[3], bounds[3]
            ) > max(box[1], bounds[1]):
                covered = True

        self.gui.EnumWindows(above, None)  # Z-order, including untitled overlays.
        if not reached or covered:
            raise PolicyError(
                "Another window covers the screenshot target; no screen pixels returned"
            )
        return box

    def capture(self, box):
        import win32con
        import win32gui
        import win32ui

        left, top, right, bottom = box
        capture_width, capture_height = right - left, bottom - top
        if not 1 <= capture_width <= 16384 or not 1 <= capture_height <= 16384:
            raise PolicyError("Target window bounds exceed the capture limit")
        scale = min(1, 1920 / capture_width, 1440 / capture_height)
        width = max(1, round(capture_width * scale))
        height = max(1, round(capture_height * scale))
        hdc = win32gui.GetDC(None)
        src = win32ui.CreateDCFromHandle(hdc)
        dest = src.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        previous = None
        try:
            bitmap.CreateCompatibleBitmap(src, width, height)
            previous = dest.SelectObject(bitmap)
            g = ctypes.WinDLL("gdi32", use_last_error=True)
            g.StretchBlt.argtypes = [
                w.HDC,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                w.HDC,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                w.DWORD,
            ]
            if not g.StretchBlt(
                dest.GetSafeHdc(),
                0,
                0,
                width,
                height,
                src.GetSafeHdc(),
                left,
                top,
                capture_width,
                capture_height,
                win32con.SRCCOPY | 0x40000000,
            ):
                raise PolicyError("Windows refused the screen capture")
            dest.SelectObject(previous)
            previous = None
            header = BitmapHeader(
                ctypes.sizeof(BitmapHeader),
                width,
                -height,
                1,
                32,
                0,
                width * height * 4,
                0,
                0,
                0,
                0,
            )
            buffer = ctypes.create_string_buffer(width * height * 4)
            g.GetDIBits.argtypes = [
                w.HDC,
                w.HBITMAP,
                w.UINT,
                w.UINT,
                ctypes.c_void_p,
                ctypes.c_void_p,
                w.UINT,
            ]
            if (
                g.GetDIBits(
                    src.GetSafeHdc(),
                    bitmap.GetHandle(),
                    0,
                    height,
                    buffer,
                    ctypes.byref(header),
                    0,
                )
                != height
            ):
                raise PolicyError("Windows refused bitmap readback")
            # Encode directly from the owned DIB buffer into bounded PNG
            # scanlines; no full-size buffer.raw or separate RGB image copy.
            png = encode_bgrx_png(buffer, width, height)
            return dict(
                png_base64=base64.b64encode(png).decode(),
                bounds=[left, top, right, bottom],
                image_width=width,
                image_height=height,
                scale_x=capture_width / width,
                scale_y=capture_height / height,
                source="visible_screen_region",
            )
        finally:
            if previous is not None:
                dest.SelectObject(previous)
            win32gui.DeleteObject(bitmap.GetHandle())
            dest.DeleteDC()
            src.DeleteDC()
            win32gui.ReleaseDC(None, hdc)
