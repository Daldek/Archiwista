"""Command-line entry point for Archiwista."""

import argparse
import os
import sys
from collections.abc import Callable

from archiwista.admin import ADMIN_COMMANDS, add_admin_commands, admin_main
from archiwista.commands import CommandModule, compare, previews
from archiwista.config import AppPaths
from archiwista.doctor import doctor_main
from archiwista.jobs.reindex import reindex_main
from archiwista.messages import MESSAGES
from archiwista.reader import READ_COMMANDS, add_read_commands, read_main
from archiwista.security import LOOPBACK_HOST
from archiwista.server import open_in_browser, serve_main, token_main
from archiwista.sources.registry import PluginRegistry, load_registry

# Modules of commands per function (contract "CLI"): one line each.
COMMAND_MODULES: tuple[CommandModule, ...] = (previews, compare)


def main(
    argv: list[str] | None = None,
    *,
    registry: PluginRegistry | None = None,
    paths: AppPaths | None = None,
) -> int:
    """Run an Archiwista command.

    Parameters
    ----------
    argv : list[str] or None, optional
        Arguments to parse, or process arguments when omitted.
    registry : PluginRegistry or None, optional
        Producer plugins; loaded from the ``archiwista.sources`` entry
        points when omitted.
    paths : AppPaths or None, optional
        Configuration and local data locations; per-user platform
        directories when omitted.

    Returns
    -------
    int
        Process exit status.
    """
    if os.name == "posix":
        # Local data (index, state, logs, area copies) is the user's alone.
        os.umask(0o077)
    parser = argparse.ArgumentParser(
        prog="archiwista", description=MESSAGES["cli_description"]
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser(
        "doctor",
        help=MESSAGES["cli_doctor_help"],
        description=MESSAGES["cli_doctor_help"],
    )
    serve = commands.add_parser(
        "serve",
        help=MESSAGES["cli_serve_help"],
        description=MESSAGES["cli_serve_help"],
    )
    serve.add_argument(
        "--host", default=LOOPBACK_HOST, help=MESSAGES["cli_serve_host_help"]
    )
    serve.add_argument(
        "--port", type=_port_type(0), help=MESSAGES["cli_serve_port_help"]
    )
    serve.add_argument(
        "--no-browser",
        action="store_true",
        help=MESSAGES["cli_serve_no_browser_help"],
    )
    serve.add_argument(
        "--access-log",
        action="store_true",
        help=MESSAGES["cli_serve_access_log_help"],
    )
    token = commands.add_parser(
        "token",
        help=MESSAGES["cli_token_help"],
        description=MESSAGES["cli_token_help"],
    )
    token.add_argument(
        "--port", type=_port_type(1), help=MESSAGES["cli_token_port_help"]
    )
    token_output = token.add_mutually_exclusive_group()
    token_output.add_argument(
        "--json", action="store_true", help=MESSAGES["cli_token_json_help"]
    )
    token_output.add_argument(
        "--revoke-all",
        action="store_true",
        help=MESSAGES["cli_token_revoke_all_help"],
    )
    reindex = commands.add_parser(
        "reindex",
        help=MESSAGES["cli_reindex_help"],
        description=MESSAGES["cli_reindex_help"],
    )
    reindex.add_argument("--store", help=MESSAGES["cli_reindex_store_help"])
    add_admin_commands(commands)
    add_read_commands(commands)
    for module in COMMAND_MODULES:
        module.add_commands(commands)
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    paths = paths or AppPaths.default()
    if args.command in ADMIN_COMMANDS:
        return admin_main(args, paths, sys.stdout, sys.stderr)
    if args.command == "token":
        return token_main(
            paths,
            sys.stdout,
            sys.stderr,
            port=args.port,
            as_json=args.json,
            revoke_all=args.revoke_all,
        )
    if registry is None:
        registry = load_registry(cache_dir=paths.cache_dir)
    if args.command == "serve":
        return serve_main(
            paths,
            registry,
            sys.stdout,
            sys.stderr,
            host=args.host,
            port=args.port,
            access_log=args.access_log,
            on_ready=None if args.no_browser else open_in_browser,
        )
    if args.command in READ_COMMANDS:
        return read_main(args, paths, registry, sys.stdout, sys.stderr)
    if args.command == "reindex":
        return reindex_main(paths, registry, sys.stdout, sys.stderr, store=args.store)
    for module in COMMAND_MODULES:
        if args.command in module.COMMANDS:
            return module.main(args, paths, registry, sys.stdout, sys.stderr)
    return doctor_main(paths, registry, sys.stdout)


def _port_type(minimum: int) -> Callable[[str], int]:
    """Return an argparse converter for ports from ``minimum`` to 65535."""

    def port(value: str) -> int:
        try:
            number = int(value)
        except ValueError:
            number = -1
        if not minimum <= number <= 65535:
            message = MESSAGES["cli_port_invalid"].format(minimum=minimum)
            raise argparse.ArgumentTypeError(message)
        return number

    return port
