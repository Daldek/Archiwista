"""Command-line entry point for Archiwista."""

import argparse
import sys

from archiwista.config import AppPaths, SourceRegistryView
from archiwista.doctor import doctor_main
from archiwista.messages import MESSAGES
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
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    paths = paths or AppPaths.default()
    if registry is None:
        registry = load_registry(cache_dir=paths.cache_dir)
    return doctor_main(paths, registry, sys.stdout)
