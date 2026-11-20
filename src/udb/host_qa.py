"""Disposable Windows acceptance worker. Never opens production state."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from .core import Agent, PolicyError
from .host_client import atomic_json
from .host_service import HostService

# Only this disposable acceptance worker uses the larger CI cold-browser
# budget. Production browser command timeouts and the no-replay rule stay put.
QA_SETUP_BUDGET_SECONDS = 30
QA_COMMAND_TIMEOUT_SECONDS = 20

FIXTURE = """<!doctype html><meta charset="utf-8"><title>UDB owned fixture</title>
<h1>Private UDB acceptance fixture</h1><input id="name"><button id="confirm"
onclick="document.querySelector('#result').innerText=document.querySelector('#name').value">Confirm</button><p id="result"></p>
<select id="choice"><option value="">Choose</option><option value="VN">Vietnam</option></select>
<input id="disabled" disabled><input id="readonly" readonly value="locked">
<output id="page">Page 1</output><button id="next" type="button" data-page="1"
onclick="document.querySelector('#page').innerText='Page '+ ++this.dataset.page">Next</button>"""


def prepare_fixture(browser, tab, html=FIXTURE):
    """Prepare an owned, disposable browser tab with one bounded CDP call per action.

    The old 10-second *shared* fixture budget could expire under loaded Windows
    runners even if Chrome had launched. Do not retry a timed-out CDP action,
    especially the document write: its outcome might already have occurred.
    """
    previous_deadline = browser.deadline
    browser.deadline = time.monotonic() + QA_SETUP_BUDGET_SECONDS
    try:
        session = browser.sid(tab)
        tree = browser.call(
            "Page.getFrameTree", session=session, timeout=QA_COMMAND_TIMEOUT_SECONDS
        )
        frame = tree["frameTree"]["frame"]["id"]
        browser.call(
            "Page.setDocumentContent",
            dict(frameId=frame, html=html),
            session,
            timeout=QA_COMMAND_TIMEOUT_SECONDS,
        )
    finally:
        # No fixture-specific deadline leaks into later host mailbox actions.
        browser.deadline = previous_deadline


def run(home):
    home = Path(home).resolve()
    temp = Path(tempfile.gettempdir()).resolve()
    if (
        home.parent != temp
        or not home.name.startswith("udb-hostqa-")
        or not (home / "QA-ISOLATED").is_file()
    ):
        raise PolicyError("Host acceptance requires a marked disposable OS temp home")
    setting = os.environ.get("UDB_HOST_QA_LONG_BENCHMARK", "")
    if setting not in ("", "1"):
        raise PolicyError("Invalid isolated QA benchmark setting")
    long_benchmark = setting == "1"
    agent = Agent(home)
    if agent.projects() or (agent.state / "connection.json").exists():
        raise PolicyError("Host acceptance refuses configured owner state")
    atomic_json(agent.state / "host-settings.json", dict(enabled=True))
    # A hosted Windows runner can need a longer cold Chrome startup budget;
    # the production HostService still uses Browser's 20-second default.
    ci_startup = 45 if os.environ.get("GITHUB_ACTIONS") == "true" else None
    service = HostService(agent, browser_startup_timeout=ci_startup)
    try:
        deadline = time.monotonic() + 60
        while not service.resource.get("admission_ready"):
            if time.monotonic() > deadline:
                raise PolicyError("Machine is too busy for host acceptance")
            time.sleep(0.2)
        with service.lock:
            result = service.dispatch(
                "start",
                dict(
                    kind="browser",
                    task="Disposable acceptance fixture",
                    duration_seconds=900 if long_benchmark else 180,
                ),
            )
            obj = service.sessions[result["session_id"]]["object"]
            tab = result["tabs"][0]["tab_id"]
            prepare_fixture(obj, tab)
            service.publish()
            atomic_json(
                home / "fixture-ready.json",
                dict(session_id=result["session_id"], tab_id=tab),
            )
        # Only the isolated 50-trial benchmark extends QA life; the ordinary
        # acceptance worker remains bounded at 90 seconds.
        deadline = time.monotonic() + (600 if long_benchmark else 90)
        while not (home / "stop.flag").exists() and time.monotonic() < deadline:
            time.sleep(0.1)
    finally:
        service.close()
