"""Commands of ``archiwista`` added per function (plan v0.2, contract "CLI").

Each module here (``previews``, and from later steps ``owndata``,
``compare``, ``layers``) has ``COMMANDS`` (the names it adds),
``add_commands`` (adds them to the parser) and ``main`` (runs one of them),
and is registered with one line in ``archiwista.cli.COMMAND_MODULES``. A
command calls the functions behind the HTTP routes, without HTTP, as the
owner of the installation (``LOCAL_OWNER``) and through the same
``Authorizer``. With ``--json`` it prints exactly the response model of the
matching route on standard output; a refusal prints the route's RFC 9457
problem there instead and exits with status 1, its Polish detail always
going to standard error. A wrong use of the command line exits with
status 2 (``argparse``).
"""

import argparse
import json
from typing import Protocol, TextIO

from archiwista.config import AppPaths
from archiwista.messages import MESSAGES
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
    text = MESSAGES[help_key]
    parser = commands.add_parser(name, help=text, description=text)
    parser.add_argument("--json", action="store_true", help=MESSAGES["cli_json_help"])
    return parser


def refuse(
    problem: dict[str, object], out: TextIO, err: TextIO, *, as_json: bool
) -> int:
    """Report a refusal: the problem on ``out`` with ``--json``; return ``1``."""
    if as_json:
        out.write(json.dumps(problem, ensure_ascii=False) + "\n")
    err.write(f"{problem['detail']}\n")
    return 1
