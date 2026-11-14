"""The public command-line entry point: udb or python -m udb."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections.abc import Sequence
from contextlib import contextmanager

from ._version import VERSION
from .config import Settings, activate, checked, load


@contextmanager
def _settings_scope(settings: Settings):
    """Restore the previous runtime settings even on cancellation or failure."""
    previous = activate(settings)
    try:
        yield
    finally:
        activate(previous)


def _run_legacy_proxy(args: Sequence[str]) -> int:
    """Keep the old proxy worker arguments callable for existing launchers."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--udb-home", required=True)
    parser.add_argument("--companion", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--enable-terminal", action="store_true")
    parser.add_argument("--core-exe")
    parsed = parser.parse_args(args)

    from .proxy import run

    settings = load(
        home=parsed.udb_home,
        root=parsed.root,
        enable_terminal=parsed.enable_terminal,
        core_exe=parsed.core_exe,
    )
    return run(settings)


def worker(role: str, args: Sequence[str]) -> int:
    """Dispatch private worker processes started by the package launcher."""
    if role == "core":
        from .core_entry import main

        return main(args)
    if role == "companion":
        from .companion.runtime import main

        return main(args)
    if role == "document":
        from .companion.documents import worker as run

        return run()
    if role == "search":
        from .companion.background import search_worker

        return search_worker()
    if role == "cloud-proxy":
        from .config import prepare_workspace
        from .proxy import run

        parser = argparse.ArgumentParser(prog="udb Cloud Agent worker")
        add_settings(parser)
        options = parser.parse_args(args)
        settings = load(
            home=options.home,
            config=options.config,
            root=options.root,
            enable_terminal=options.enable_terminal,
            core_exe=options.core_exe,
        )
        prepare_workspace(settings)
        return run(settings)
    if role == "legacy-proxy":
        return _run_legacy_proxy(args)
    raise ValueError("Unknown worker role")


def add_settings(
    parser: argparse.ArgumentParser, suppress: bool = False, hide_help: bool = False
) -> None:
    """Register common path and terminal settings on a CLI parser."""
    default = argparse.SUPPRESS if suppress else None
    help_text = argparse.SUPPRESS if hide_help else None
    for name in ("home", "config", "root", "core-exe"):
        parser.add_argument(f"--{name}", default=default, help=help_text)

    terminal = parser.add_mutually_exclusive_group()
    terminal.add_argument(
        "--enable-terminal",
        dest="enable_terminal",
        action="store_true",
        default=default,
        help=help_text,
    )
    terminal.add_argument(
        "--disable-terminal",
        dest="enable_terminal",
        action="store_false",
        default=default,
        help=help_text,
    )


# Commands promoted in the standard help. Keep all other commands callable for
# existing shortcuts, installers, scripts and unattended recovery workflows.
# A command missing from this table is intentionally *not* advertised in -h.
SIMPLE_COMMAND_HELP = {
    "setup": "Set up this Windows device and connect to ChatGPT",
    "connect": "Open ChatGPT authorization for an enrolled UDB device",
    "start": "Start UDB (also the default: udb)",
    "stop": "Stop the UDB headless agent",
    "gui": "Open the UDB Manager",
    "status": "Show current UDB status",
    "doctor": "Diagnose UDB and Cloudflare readiness",
    "live": "Watch UDB tool activity (--gui for a window)",
    "update": "Check for a reviewed update with --check",
    "help": "Show easy commands (or: udb help advanced)",
}


SIMPLE_COMMAND_HELP_VI = {
    "setup": "Tự thiết lập Windows, Cloudflare và kết nối ChatGPT",
    "connect": "Kết nối UDB riêng tư với ChatGPT",
    "start": "Khởi động UDB (cũng có thể chỉ gõ udb)",
    "stop": "Dừng UDB",
    "gui": "Mở trình quản lý UDB",
    "status": "Xem trạng thái hoạt động",
    "doctor": "Chẩn đoán lỗi và kết nối",
    "live": "Theo dõi hoạt động (--gui để mở cửa sổ)",
    "update": "Kiểm tra bản cập nhật bằng --check",
    "help": "Xem hướng dẫn",
}

ADVANCED_COMMAND_HELP = """Advanced UDB commands (kept for compatibility)

Connection and recovery:
  udb mcp-config         Show the paired HTTPS MCP endpoint
  udb connect            Open ChatGPT for an owner-enrolled device
  udb connect --enroll   Request private, owner-approved device pairing
  udb reconnect          Reconnect the existing Cloud Agent
  udb cloud-pair         Attended device pairing (alternative to setup)
  udb cloud-agent        Run the Cloud Agent directly
  udb autostart status   Check Windows sign-in startup
  udb autostart enable   Enable Windows sign-in startup (owner only)
  udb autostart disable  Disable Windows sign-in startup
  udb rollback           Restore the previous managed release
  udb quickstart         Start/check local support components
  udb update --yes       Skip attended confirmation for an intentional update
  udb rollback --yes     Skip attended confirmation for an intentional rollback

Permissions (owner-attended):
  udb --access computer   Attended opt-in to broad Windows access
  udb revoke-access      Revoke broad Windows computer access
  udb allow-source       Grant source access (--path required)
  udb revoke-source      Revoke source access (--path required)

Diagnostics and development:
  udb tools              Show the actual MCP tool catalog
  udb logs               Older name for the terminal Live viewer
  udb test               Run the installed-agent test
  udb runtime --probe    Inspect bundled runtime components
  udb version --json     Show the exact installed build identity
  udb build-info         Show build metadata
  udb manifest           Show package manifest
  udb init               Create a new local configuration
  udb build              Build a release from source

The obsolete `udb setup --edit` flag is accepted for compatibility only.
Legacy internal worker launchers remain private. Use udb <command> --help
for command-specific options. Existing commands remain supported;
nothing here grants permissions or changes the Cloudflare connection.
"""


def _everyday_help() -> str:
    """Keep the human-facing CLI compact; legacy dispatch remains available."""
    lines = [
        "UDB - everyday commands",
        "Usage: udb [command] [options]",
        "",
        "  udb                      Start UDB (same as udb start)",
    ]
    for name, description in SIMPLE_COMMAND_HELP.items():
        display = "update --check" if name == "update" else name
        lines.append(f"  udb {display:<22} {description}")
    lines.extend(
        [
            "",
            "  udb --version            Show installed UDB version",
            "",
            "For uncommon commands: udb help advanced",
            "Vietnamese commands: udb help vi",
            "For command options: udb help <command> or udb <command> --help",
            "Help does not start UDB, grant access, or change owner state.",
        ]
    )
    return "\n".join(lines)


def _everyday_help_vi() -> str:
    """Optional Vietnamese help without changing the machine-readable CLI."""
    lines = [
        "UDB - lệnh thường dùng",
        "Cách dùng: udb [lệnh] [tùy chọn]",
        "",
        "  udb                      Khởi động UDB (như udb start)",
    ]
    for name, description in SIMPLE_COMMAND_HELP_VI.items():
        display = "update --check" if name == "update" else name
        lines.append(f"  udb {display:<22} {description}")
    lines.extend(
        [
            "",
            "  udb --version            Xem phiên bản hiện tại",
            "",
            "Lệnh nâng cao: udb help advanced",
            "Hướng dẫn từng lệnh: udb help <command>",
            "Các lệnh trợ giúp không khởi động UDB hay cấp thêm quyền.",
        ]
    )
    return "\n".join(lines)


class _UdbArgumentParser(argparse.ArgumentParser):
    """Offer one concrete hint for a misspelled command, not 28 choices."""

    def error(self, message):
        if message.startswith("argument COMMAND: invalid choice:"):
            match = re.search(
                r"invalid choice: '([A-Za-z][A-Za-z0-9_-]{0,31})'", message
            )
            if match:
                wrong = match.group(1)
                commands = next(
                    (
                        action.choices.keys()
                        for action in self._actions
                        if isinstance(action, argparse._SubParsersAction)
                    ),
                    (),
                )
                suggestion = difflib.get_close_matches(wrong, commands, n=1, cutoff=0.6)
                hint = f" Did you mean 'udb {suggestion[0]}'?" if suggestion else ""
                self.exit(
                    2,
                    f"UDB: Unknown command '{wrong}'.{hint}\n"
                    "Try 'udb help' (Vietnamese: 'udb help vi').\n",
                )
            self.exit(2, "UDB: Unknown command. Try 'udb help'.\n")
        super().error(message)


class _EverydayHelpAction(argparse.Action):
    """Print concise root help without altering internal/legacy CLI parsers."""

    def __call__(self, parser, namespace, values, option_string=None):
        print(_everyday_help())
        parser.exit(0)


def _exclusive_flags(parser, *names, inherit=False, hidden=False):
    """Share flags without subcommands overwriting a parent's parsed values."""
    group = parser.add_mutually_exclusive_group()
    for name in names:
        group.add_argument(
            f"--{name}",
            action="store_true",
            default=argparse.SUPPRESS if inherit else False,
            help=argparse.SUPPRESS if hidden else None,
        )


def _add_subcommands(parser: argparse.ArgumentParser) -> None:
    subcommands = parser.add_subparsers(dest="action", metavar="COMMAND")
    command_names = (
        "start",
        "quickstart",
        "setup",
        "connect",
        "gui",
        "live",
        "runtime",
        "cloud-agent",
        "cloud-pair",
        "status",
        "reconnect",
        "logs",
        "stop",
        "doctor",
        "autostart",
        "update",
        "rollback",
        "test",
        "revoke-access",
        "allow-source",
        "revoke-source",
        "tools",
        "init",
        "build",
        "build-info",
        "version",
        "manifest",
        "mcp-config",
        "help",
    )
    for name in command_names:
        if name in SIMPLE_COMMAND_HELP:
            command = subcommands.add_parser(name, help=SIMPLE_COMMAND_HELP[name])
        else:
            command = subcommands.add_parser(name)
        add_settings(command, suppress=True)
        if name == "setup":
            command.add_argument("--status", action="store_true", help="Read-only setup diagnostics")
            command.add_argument("--no-browser", action="store_true", help="Inspect only; make no setup changes")
            command.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Read-only JSON diagnostics")
        if name == "connect":
            command.add_argument(
                "--enroll",
                action="store_true",
                help="Request owner-approved private pairing without an invite",
            )
            command.add_argument(
                "--relay",
                help="Private Cloudflare workers.dev HTTPS origin (with --enroll)",
            )
            command.add_argument(
                "--setup",
                action="store_true",
                help="One-time private device pairing in a local Windows console",
            )
            command.add_argument(
                "--autostart",
                action="store_true",
                help="Opt in Cloud Agent startup for an already paired device at Windows logon",
            )
            command.add_argument(
                "--no-browser",
                action="store_true",
                help="Inspect pairing without launching ChatGPT",
            )
            command.add_argument(
                "--json",
                action="store_true",
                default=argparse.SUPPRESS,
            )
        if name == "help":
            command.add_argument(
                "topic", nargs="?", choices=("advanced", "vi", *command_names)
            )
        if name in ("autostart", "update", "rollback", "version"):
            command.add_argument(
                "--json", action="store_true", default=argparse.SUPPRESS
            )
        if name == "autostart":
            command.add_argument(
                "operation",
                choices=("enable", "disable", "status"),
                default="status",
                nargs="?",
            )
            command.add_argument(
                "--cloud-agent",
                action="store_true",
                help="Opt in to Cloudflare Cloud Agent at Windows logon (local console only)",
            )
        if name in ("update", "rollback"):
            command.add_argument(
                "--yes",
                action="store_true",
                help="Skip attended confirmation; for an intentional local action",
            )
        if name == "update":
            command.add_argument(
                "--check",
                action="store_true",
                help="Check latest version without installing",
            )
        if name in (
            "start",
            "quickstart",
            "status",
            "reconnect",
            "stop",
            "doctor",
            "test",
            "revoke-access",
        ):
            command.add_argument(
                "--json", action="store_true", default=argparse.SUPPRESS
            )
            command.add_argument("--wait", type=int, default=argparse.SUPPRESS)
            command.add_argument(
                "--access", choices=("computer",), default=argparse.SUPPRESS
            )
        if name == "doctor":
            command.add_argument(
                "--cloud",
                action="store_true",
                help="Check public Cloudflare endpoints using existing pairing (no credentials)",
            )
            command.add_argument(
                "--cloud-auth-mode", choices=("cloudflare-access", "jwt")
            )
        if name == "quickstart":
            command.add_argument(
                "--autostart",
                action="store_true",
                help="Opt in to local-only startup at Windows sign-in",
            )
        if name == "start":
            _exclusive_flags(command, "detach", "follow", inherit=True)
            _exclusive_flags(command, "offline", "online", inherit=True, hidden=True)
        if name == "status":
            command.add_argument(
                "--watch",
                action="store_true",
                help="Watch metadata-only headless status",
            )
            command.add_argument("--interval", type=float, default=1.0)
            command.add_argument(
                "--count",
                type=int,
                default=0,
                help="Number of samples; 0 watches until Ctrl+C",
            )
        if name == "setup":
            command.add_argument("--edit", action="store_true", help=argparse.SUPPRESS)
        if name == "runtime":
            command.add_argument("--probe", action="store_true")
        if name in ("logs", "live"):
            if name == "live":
                command.add_argument(
                    "--gui", action="store_true", help="Open the activity window"
                )
            command.add_argument(
                "--once", action="store_true", help="Print retained activity and exit"
            )
            command.add_argument("--tail", type=int, default=30, metavar="0..2000")
            command.add_argument(
                "--details",
                action="store_true",
                help="Show safe argument/result metadata",
            )
            command.add_argument(
                "--json", action="store_true", default=argparse.SUPPRESS
            )
        if name in ("allow-source", "revoke-source"):
            command.add_argument(
                "--path", required=True, help="Exact protected source project folder"
            )
        if name == "build":
            command.add_argument("--exe", action="store_true")
            command.add_argument(
                "--layout", choices=("onefile", "onedir"), default="onefile"
            )
            command.add_argument("--output")
            command.add_argument(
                "--assets", help="Inventoried public runtime helper directory"
            )


def _initialize_config(args: argparse.Namespace, settings: Settings) -> int:
    target = (
        checked(args.config) if args.config else checked(settings.home / "udb.toml")
    )
    values = {
        "home": str(settings.home),
        "project_root": str(settings.project_root),
        "core_backend": settings.core_backend,
        "enable_terminal": settings.enable_terminal,
    }
    if settings.core_exe:
        values["core_exe"] = str(settings.core_exe)

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        stream.write(
            "[bridge]\n"
            + "".join(
                f"{key} = {json.dumps(value, ensure_ascii=False)}\n"
                for key, value in values.items()
            )
        )
    print("Created runtime configuration; no connection or permission was granted.")
    return 0


def _run_setup(args: argparse.Namespace, settings: Settings) -> int:
    if args.access or args.offline or args.online:
        raise ValueError("Use udb setup without --access/--offline/--online")
    if getattr(args, "edit", False):
        print("UDB: --edit is obsolete; using automatic Cloudflare setup.", file=sys.stderr)
    readonly = args.json or getattr(args, "status", False) or getattr(args, "no_browser", False)
    with _settings_scope(settings):
        if readonly:
            from .setup import run

            return run(settings, readonly=True, json_output=args.json)
        from .onboarding import setup_cloud

        return setup_cloud(settings)


def _prepare_startup(args: argparse.Namespace, settings: Settings) -> int | None:
    from . import onboarding
    from .owner_command import headless_state

    if args.offline or onboarding.paired_cloud(settings.home):
        return None
    if args.online:
        raise ValueError(
            "Pair this Windows device with Cloudflare first using udb setup."
        )
    if (headless_state(settings.home) or {}).get("connection_mode") == "offline":
        args.offline = True
        return None
    if not (args.detach or args.json or args.access) and onboarding.attended_console():
        with _settings_scope(settings):
            try:
                result = onboarding.setup_cloud(settings)
                if result:
                    return result
            except KeyboardInterrupt:
                print("\nSetup canceled.", file=sys.stderr)
                return 130
    if not onboarding.paired_cloud(settings.home):
        # The local support worker is required for approvals and can start
        # before enrollment. It does not expose an MCP transport.
        args.offline = True


def _print_mcp_config(args: argparse.Namespace, settings: Settings) -> int:
    from .connection import cloud_mcp_url
    from .onboarding import paired_cloud

    servers = {}
    if paired_cloud(settings.home):
        servers["universal-desktop-bridge"] = {
            "type": "streamable-http",
            "url": cloud_mcp_url(settings.home),
        }
    print(json.dumps({"mcpServers": servers}, indent=2))
    return 0


def _run_gui(args: argparse.Namespace, settings: Settings) -> int:
    if args.access:
        raise ValueError("Owner activation requires the separate attended command")
    import subprocess

    from .config import prepare_workspace
    from .launcher import worker_command

    prepare_workspace(settings)
    with _settings_scope(settings):
        from .config import manager_options

        return subprocess.run(
            worker_command(
                "core",
                [
                    "--gui",
                    "--home",
                    str(settings.home),
                    *manager_options(settings.home),
                ],
            ),
            shell=False,
        ).returncode


def _confirm_attended_maintenance(
    action: str, args: argparse.Namespace, *, incoming=None, outgoing=None
) -> bool:
    """Require a typed confirmation for human-attended update/rollback.

    Preserve pre-existing noninteractive and JSON automation; those already
    have their own owner/update guards. Never confirm permission grants here.
    """
    if action == "update" and getattr(args, "check", False):
        return True
    if getattr(args, "yes", False) or getattr(args, "json", False):
        return True
    incoming = sys.stdin if incoming is None else incoming
    outgoing = sys.stderr if outgoing is None else outgoing
    if not incoming.isatty() or not outgoing.isatty():
        return True
    token = "ROLLBACK" if action == "rollback" else "UPDATE"
    outgoing.write(
        f"UDB: {action} changes the active Windows installation. "
        "Keep an independent owner-state backup.\n"
        f"Type {token} to continue, or Enter to cancel: "
    )
    outgoing.flush()
    try:
        return incoming.readline().strip() == token
    except (KeyboardInterrupt, OSError):
        return False


def _run_maintenance(action: str, args: argparse.Namespace, settings: Settings) -> int:
    if args.access or args.offline or args.online:
        raise ValueError(
            "Maintenance does not activate owner access or select connection mode"
        )
    from .owner_command import CommandError

    try:
        if action == "autostart":
            from .autostart import run

            return run(
                settings,
                args.operation,
                as_json=args.json,
                cloud_agent=args.operation == "enable" or args.cloud_agent,
            )
        from .maintenance import run

        return run(
            action,
            settings,
            check=getattr(args, "check", False),
            as_json=args.json,
        )
    except CommandError as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}))
        else:
            print("UDB: " + str(exc), file=sys.stderr)
        return 2


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_worker"]:
        if len(argv) < 2:
            raise SystemExit("Worker role required")
        return worker(argv[1], argv[2:])

    parser = _UdbArgumentParser(
        prog="udb",
        description="Universal Desktop Bridge: one package, one command",
        add_help=False,
    )
    parser.add_argument(
        "-h",
        "--help",
        action=_EverydayHelpAction,
        nargs=0,
        help="Show everyday UDB commands",
    )
    parser.add_argument("--version", action="version", version=VERSION)
    add_settings(parser, hide_help=True)
    parser.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    _exclusive_flags(parser, "detach", "follow", hidden=True)
    parser.add_argument("--wait", type=int, default=30, help=argparse.SUPPRESS)
    _exclusive_flags(parser, "offline", "online", hidden=True)
    _add_subcommands(parser)
    parser.add_argument("--access", choices=("computer",), help=argparse.SUPPRESS)

    args = parser.parse_args(argv)
    action = args.action or "start"
    if action == "help":
        if args.topic == "advanced":
            print(ADVANCED_COMMAND_HELP)
        elif args.topic == "vi":
            print(_everyday_help_vi())
        elif args.topic:
            # Reuse argparse subcommand help without loading runtime settings.
            try:
                return main([args.topic, "--help"])
            except SystemExit as exc:
                return exc.code if isinstance(exc.code, int) else 2
        else:
            print(_everyday_help())
        return 0
    try:
        if args.offline and args.online:
            raise ValueError("Choose either --offline or --online")
        if (args.detach or args.follow) and action != "start":
            raise ValueError("--detach/--follow apply only to start")
        if args.follow and args.json:
            raise ValueError("--follow cannot be combined with --json")
        if action == "manifest":
            from .metadata import manifest

            print(json.dumps(manifest(), indent=2))
            return 0
        if action == "build":
            from .build import run

            return run(args.exe, args.output, assets=args.assets, layout=args.layout)
        if action == "runtime":
            from .components import runtime_report

            print(json.dumps(runtime_report(args.probe), ensure_ascii=True))
            return 0
        if action == "build-info":
            from .build import build_info

            print(json.dumps(build_info(), sort_keys=True))
            return 0
        if action == "version":
            from .build_identity import display_identity, runtime_identity

            print(
                json.dumps(runtime_identity(), sort_keys=True)
                if args.json
                else display_identity()
            )
            return 0
        if action == "tools":
            from .registry import catalog

            print(json.dumps({"version": VERSION, **catalog()}, ensure_ascii=True))
            return 0

        settings = load(
            home=args.home,
            config=args.config,
            root=args.root,
            enable_terminal=args.enable_terminal,
            core_exe=args.core_exe,
            allow_missing_config=action == "init",
        )
        if action == "setup":
            return _run_setup(args, settings)
        if action == "connect":
            if args.access or args.offline or args.online:
                raise ValueError(
                    "Connect does not change Windows access or startup mode"
                )
            from .connect_chatgpt import run as connect_chatgpt

            return connect_chatgpt(
                settings,
                as_json=args.json,
                open_browser=not args.no_browser,
                setup=args.setup,
                autostart=args.autostart,
                enroll=args.enroll,
                relay=args.relay,
            )
        if action == "quickstart":
            if args.access or args.offline or args.online:
                raise ValueError(
                    "Quickstart is local-only and cannot activate owner or remote access"
                )
            from .quickstart import run as run_quickstart

            with _settings_scope(settings):
                return run_quickstart(
                    settings,
                    wait=args.wait,
                    as_json=args.json,
                    enable_autostart=args.autostart,
                )
        if action in ("autostart", "update", "rollback"):
            if action in ("update", "rollback") and not _confirm_attended_maintenance(
                action, args
            ):
                print("UDB: Cancelled; no update or rollback started.", file=sys.stderr)
                return 2
            return _run_maintenance(action, args, settings)
        if action == "start":
            startup_result = _prepare_startup(args, settings)
            if startup_result is not None:
                return startup_result
        if action == "mcp-config":
            return _print_mcp_config(args, settings)
        if (args.offline or args.online) and action != "start":
            raise ValueError("--offline/--online apply only to start")
        if action == "init":
            return _initialize_config(args, settings)
        if action in ("logs", "live"):
            if args.access:
                raise ValueError("Log viewing does not activate owner access")
            if getattr(args, "gui", False):
                if args.once or args.json or args.details or args.tail != 30:
                    raise ValueError("Use terminal log options without --gui")
                from .activity_gui import run

                return run(settings.home)
            from .activity import watch

            return watch(
                settings.home,
                tail=args.tail,
                once=args.once,
                details=args.details,
                as_json=args.json,
            )
        if action == "gui":
            return _run_gui(args, settings)
        if action in ("allow-source", "revoke-source"):
            if args.access or args.json:
                raise ValueError(
                    "Source permission requires a separate attended local command"
                )
            from .source_access import command

            return command(settings.home, args.path, revoke=action == "revoke-source")
        if action == "cloud-agent":
            if args.access:
                raise ValueError("Cloud agent does not grant owner access")
            from .cloud_agent import run as run_cloud_agent

            return run_cloud_agent(settings)
        if action == "cloud-pair":
            if args.access:
                raise ValueError("Cloud pairing does not grant owner access")
            from .cloud_pair import run as run_cloud_pair
            from .onboarding import console_input

            if not console_input():
                raise ValueError("Cloud pairing requires an attended Windows terminal.")
            return run_cloud_pair(settings)
        from . import owner_command

        legacy_args = [
            action,
            "--home",
            str(settings.home),
            "--wait",
            str(getattr(args, "wait", 30)),
        ]
        if action == "status" and args.watch:
            if args.access:
                raise ValueError("Status monitoring cannot activate owner access")
            from .status_monitor import watch

            return watch(
                settings.home,
                owner_command.executable(settings.home),
                interval=args.interval,
                count=args.count,
                as_json=args.json,
            )
        if getattr(args, "json", False):
            legacy_args.append("--json")
        if args.detach:
            legacy_args.append("--detach")
        if args.follow:
            legacy_args.append("--follow")
        if args.access:
            legacy_args.extend(["--access", args.access])
        if args.offline:
            legacy_args.append("--offline")
        if getattr(args, "cloud", False):
            legacy_args.append("--cloud")
        if getattr(args, "cloud_auth_mode", None):
            legacy_args.extend(["--cloud-auth-mode", args.cloud_auth_mode])

        with _settings_scope(settings):
            return owner_command.main(legacy_args)
    except (ValueError, OSError) as exc:
        print(f"UDB: {exc}", file=sys.stderr)
        return 2
