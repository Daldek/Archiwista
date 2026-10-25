"""Command-line entry point for Archiwista."""

import argparse
import os
import sys
import traceback
from collections.abc import Callable
from typing import Any, NoReturn, cast

from archiwista.admin import ADMIN_COMMANDS, add_admin_commands, admin_main
from archiwista.commands import (
    CommandModule,
    Commands,
    compare,
    layers,
    owndata,
    previews,
)
from archiwista.config import AppPaths
from archiwista.doctor import doctor_main
from archiwista.error_document import Problem, refuse
from archiwista.jobs.reindex import reindex_main
from archiwista.logs import (
    ENV_LOG_LEVEL,
    LOG_LEVELS,
    InvalidLogLevelError,
    configure_logging,
    resolve_log_level,
)
from archiwista.messages import MESSAGES
from archiwista.reader import READ_COMMANDS, add_read_commands, read_main
from archiwista.security import LOOPBACK_HOST
from archiwista.server import open_in_browser, serve_main, token_main
from archiwista.sources.registry import PluginRegistry, load_registry

# Modules of commands per function (contract "CLI"): one line each.
COMMAND_MODULES: tuple[CommandModule, ...] = (previews, owndata, compare, layers)


class _Parser(argparse.ArgumentParser):
    """An argument parser whose usage errors end like every refusal (ERR-4).

    Every parser, the command's too, accepts ``--verbose`` and ``--quiet``
    (DEV-12.2): they are in the namespace only when given.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        levels = self.add_mutually_exclusive_group()
        levels.add_argument(
            "--verbose",
            action="store_true",
            default=argparse.SUPPRESS,
            help=MESSAGES["cli_verbose_help"],
        )
        levels.add_argument(
            "--quiet",
            action="store_true",
            default=argparse.SUPPRESS,
            help=MESSAGES["cli_quiet_help"],
        )

    def error(self, message: str) -> NoReturn:
        """Print the usage and the error document, then exit with status 2."""
        self.print_usage(sys.stderr)
        problem = Problem(
            "validation_error", f"{self.prog}: {message}", details={"reason": "usage"}
        )
        raise SystemExit(refuse(problem, sys.stderr))


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
    parser = _Parser(prog="archiwista", description=MESSAGES["cli_description"])
    commands = cast(Commands, parser.add_subparsers(dest="command"))
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
    # Given before and after the command, the options contradict each other.
    verbose, quiet = hasattr(args, "verbose"), hasattr(args, "quiet")
    if verbose and quiet:
        parser.error(MESSAGES["cli_log_options_exclusive"])
    try:
        level = resolve_log_level(verbose=verbose, quiet=quiet)
    except InvalidLogLevelError as error:
        return refuse(_invalid_log_level(error), sys.stderr)
    configure_logging(level)
    paths = paths or AppPaths.default()
    try:
        return _dispatch(args, paths, registry, level)
    except Exception:
        # A defect: the traceback for the maintainer, the document for agents.
        traceback.print_exc()
        problem = Problem("internal_error", MESSAGES["cli_internal_error"])
        return refuse(problem, sys.stderr)


def _invalid_log_level(error: InvalidLogLevelError) -> Problem:
    """Return the refusal of an ``ARCHIWISTA_LOG_LEVEL`` that names no level."""
    message = MESSAGES["cli_log_level_invalid"].format(
        variable=ENV_LOG_LEVEL, value=error.value, allowed=", ".join(LOG_LEVELS)
    )
    details = {
        "reason": "invalid_log_level",
        "option": ENV_LOG_LEVEL,
        "value": error.value,
        "allowed": list(LOG_LEVELS),
    }
    return Problem("validation_error", message, MESSAGES["cli_log_level_hint"], details)


def _dispatch(
    args: argparse.Namespace,
    paths: AppPaths,
    registry: PluginRegistry | None,
    log_level: str,
) -> int:
    """Run the command ``args`` names and return its exit status."""
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
            log_level=log_level,
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
