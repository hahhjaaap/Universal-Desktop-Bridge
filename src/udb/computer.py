"""Grant-gated computer operations, serialized through the existing headless worker."""

from . import computer_access as access
from .computer_files import Files
from .computer_jobs import Jobs
from .concurrency import MAX_CONCURRENT
from .core import PolicyError
from .resources import require_capacity, require_light_capacity
from .windows_actions import READ_ACTIONS


def status_report(agent, processes=None, *, worker_ready=True, usage=None, brief=False):
    """Read the owner grant afresh; report capacity without claiming free slots.

    Other terminal and background jobs share the same 10-slot pool, so the
    remaining figure is an UPPER bound rather than guaranteed availability.
    """
    from .desktop_control import browser_handoff, paused

    if (
        usage is None
        and processes is not None
        and isinstance(processes.get("jobs"), list)
    ):
        jobs = processes["jobs"]
        usage = {
            "known_computer_jobs": len(jobs),
            "active_computer_jobs": sum(
                job.get("status") in ("running", "cleanup_failed") for job in jobs
            ),
        }
    active = usage["active_computer_jobs"] if usage is not None else None
    capacity = {
        "available": usage is not None,
        "known_computer_jobs": usage["known_computer_jobs"]
        if usage is not None
        else None,
        "active_computer_jobs": active,
        "remaining_shared_slots_upper_bound": (
            max(0, MAX_CONCURRENT - active) if active is not None else None
        ),
        "other_background_jobs_not_included": True,
    }
    process_state = (
        processes if processes is not None else dict(jobs=[], available=False)
    )
    if brief and processes is not None:
        process_state = {"available": worker_ready, "jobs_omitted": True}
    return dict(
        desktop_paused=paused(agent) or browser_handoff(agent),
        **access.summary(agent),
        worker_ready=worker_ready,
        command_limits=dict(
            max_running=MAX_CONCURRENT,
            shared_background_limit=MAX_CONCURRENT,
            timeout_seconds=3600,
            output_bytes=4 * 1024 * 1024,
            memory_mib=4096,
        ),
        job_usage=capacity,
        processes=process_state,
    )


class Computer:
    def __init__(self, agent, jobs_factory=Jobs):
        self.agent = agent
        self.files = Files(agent)
        self.desktop = None
        self.utilities = None

        def token():
            grant = access.load(agent)
            return grant["id"] if grant else None

        self.jobs = jobs_factory(agent, token)

    def dispatch(self, mode, args, resource):
        if mode == "status":
            if args.get("brief") is True:
                return status_report(
                    self.agent,
                    processes={"available": True, "jobs_omitted": True},
                    usage=self.jobs.usage(),
                    brief=True,
                )
            return status_report(self.agent, self.jobs.process("list"))
        if mode == "process" and args.get("action") == "stop":
            return self.jobs.process("stop", args.get("job_id", ""))
        grant = access.require(self.agent)
        if mode == "desktop" and args.get("action") == "control_status":
            from .desktop_control import InputControl

            return (
                self.desktop.control.status()
                if self.desktop
                else InputControl(self.agent).status()
            )
        if mode == "process":
            return self.jobs.process(
                args.get("action", "read"),
                args.get("job_id", ""),
                args.get("offset", 0),
                args.get("limit", 30),
            )
        if mode == "files" or (
            mode == "desktop" and args.get("action") in READ_ACTIONS
        ):
            require_light_capacity(resource)
        else:
            require_capacity(resource, 256 if mode == "execute" else 128)
        if mode == "utilities":
            if self.utilities is None:
                from .windows_utilities import Utilities

                self.utilities = Utilities(self.agent)
            return self.utilities.dispatch(**args)
        if mode == "files":
            return self.files.dispatch(**args)
        if mode == "execute":
            # CWD is checked against explicit protected roots as well as NTFS.
            self.files.path(args.get("cwd", ""))
            return self.jobs.start(grant=grant, **args)
        if mode == "desktop":
            if self.desktop is None:
                from .computer_desktop import Desktop
                from .desktop_control import InputControl

                self.desktop = Desktop(
                    guard=lambda: access.require(self.agent) == self.desktop_grant,
                    control=InputControl(self.agent),
                )
            self.desktop_grant = grant
            return self.desktop.dispatch(**args)
        raise PolicyError("Unknown computer operation")

    def close(self):
        self.jobs.close()
