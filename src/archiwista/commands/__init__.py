"""Commands of ``archiwista`` added per function (plan v0.2, contract "CLI").

Each module here (``previews``, and from later steps ``owndata``,
``compare``, ``layers``, ``producer_commands``, ``availability``, ``jobs``,
``projects``, ``preview_warm``, ``stations`` and ``log``)
has ``COMMANDS`` (the names it adds), ``add_commands`` (adds them to the
parser) and ``main`` (runs one of them),
and is registered with one line in ``archiwista.cli.COMMAND_MODULES``. A
command calls the functions behind the HTTP routes, without HTTP, as the
owner of the installation (``LOCAL_OWNER``) and through the same
``Authorizer``. With ``--json`` it prints exactly the response model of the
matching route on standard output; a refusal prints nothing there: its
Polish detail goes to standard error, the ``archiwista-error/1`` document
(``archiwista.error_document``) is the last line of standard error, and the
exit status is the registry's exit code of its code (ERR-4). A job that
ends ``partial`` exits with 10, one that ends ``failed`` with 11, one that
ends ``cancelled`` or ``interrupted`` with 130 (ERR §1). A wrong use of the
command line exits with status 2
(``argparse``, with the same document).
"""

import argparse
from typing import Protocol, TextIO

from archiwista.config import AppPaths
from archiwista.messages import message
from archiwista.sources.registry import PluginRegistry

type Commands = argparse._SubParsersAction[argparse.ArgumentParser]


class CommandModule(Protocol):
    """What ``archiwista.cli`` needs of a module of commands."""

    COMMANDS: frozenset[str]

    def add_commands(self, commands: Commands) -> None:
        """Add the module's commands to the subcommands of ``archiwista``."""
        ...

    def main(
        self,
        args: argparse.Namespace,
        paths: AppPaths,
        registry: PluginRegistry,
        out: TextIO,
        err: TextIO,
    ) -> int:
        """Run one of the module's commands; return the exit status."""
        ...


def add_parser(commands: Commands, name: str, help_key: str) -> argparse.ArgumentParser:
    """Add a command with its help text and ``--json``; return its parser."""
    text = message(help_key)
    parser = commands.add_parser(name, help=text, description=text)
    parser.add_argument("--json", action="store_true", help=message("cli.json_help"))
    return parser
