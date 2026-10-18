"""Command-line entry point for Archiwista."""

import argparse
import sys
from collections.abc import Callable

from archiwista.config import AppPaths, SourceRegistryView
from archiwista.doctor import doctor_main
from archiwista.messages import MESSAGES
from archiwista.security import LOOPBACK_HOST
from archiwista.server import open_in_browser, serve_main, token_main
from archiwista.sources.registry import load_registry


def main(
    argv: list[str] | None = None,
    *,
    registry: SourceRegistryView | None = None,
    paths: AppPaths | None = None,
) -> int:
    """Run an Archiwista command.

    Parameters
    ----------
    argv : list[str] or None, optional
        Arguments to parse, or process arguments when omitted.
    registry : SourceRegistryView or None, optional
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
    token.add_argument(
        "--json", action="store_true", help=MESSAGES["cli_token_json_help"]
    )
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    paths = paths or AppPaths.default()
    if args.command == "token":
        return token_main(
            paths, sys.stdout, sys.stderr, port=args.port, as_json=args.json
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
