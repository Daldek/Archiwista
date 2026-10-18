"""Command-line entry point for Archiwista."""

import argparse
import importlib
import sys
from typing import cast

from archiwista.config import AppPaths, SourceRegistryView
from archiwista.doctor import doctor_main
from archiwista.messages import MESSAGES

REGISTRY_MODULE = "archiwista.sources.registry"


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
    if registry is None:
        loaded = _load_registry()
        if loaded is None:
            print(MESSAGES["cli_registry_missing"], file=sys.stderr)
            return 2
        registry = loaded
    return doctor_main(paths or AppPaths.default(), registry, sys.stdout)


def _load_registry() -> SourceRegistryView | None:
    """Load the plugin registry, or ``None`` when this installation lacks it."""
    try:
        module = importlib.import_module(REGISTRY_MODULE)
    except ModuleNotFoundError as error:
        if error.name != REGISTRY_MODULE:
            raise
        return None
    return cast(SourceRegistryView, module.load_registry())
