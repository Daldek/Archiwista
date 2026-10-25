"""``archiwista commands``: the producers' commands (plan of 2026-10-25, A1).

``commands list [--producer ID]`` prints the commands of the producers'
catalogs (``GET /commands``), ``commands parse PRODUCER LINE`` reads a pasted
command line into a call (``POST /commands/parse``), ``commands validate
PRODUCER COMMAND [--options JSON] [--store ID]`` checks a call without the
network (``POST /commands/validate``) and ``commands format PRODUCER COMMAND
[--options JSON] [--run JSON]`` writes the producer's command line of a call
(``POST /commands/format``). They call ``archiwista.services.commands``
without HTTP: ``--json`` prints the route's model, a refusal the route's
problem as the ``archiwista-error/1`` document. Nothing here uses the network
or writes.
"""

import argparse
import json
from collections.abc import Callable
from typing import Any, TextIO

from pydantic import BaseModel

from archiwista.api.models_commands import CommandCallItem, CommandLine, CommandList
from archiwista.commands import Commands, add_parser
from archiwista.config import AppPaths, ConfigStore, SettingsValidationError
from archiwista.error_document import describe, exception_problem, refuse
from archiwista.errors import ArchiwistaError
from archiwista.messages import message, with_detail
from archiwista.services.commands import (
    format_command,
    list_commands,
    parse_command,
    validate_command,
)
from archiwista.sources import CommandCall
from archiwista.sources.registry import PluginRegistry

COMMANDS = frozenset({"commands"})

# What an action prints: the route's model with ``--json``, else text for people.
type _Output = tuple[BaseModel, str]
type _Action = Callable[[argparse.Namespace, AppPaths, PluginRegistry], _Output]


def add_commands(commands: Commands) -> None:
    """Add ``archiwista commands`` and its actions (see the module).

    Parameters
    ----------
    commands : argparse._SubParsersAction
        Subcommands of the ``archiwista`` parser.
    """
    text = message("cli.commands_help")
    parser = commands.add_parser("commands", help=text, description=text)
    actions = parser.add_subparsers(
        dest="action", required=True, metavar=message("metavar.action")
    )
    listing = add_parser(actions, "list", "cli.commands_list_help")
    listing.add_argument(
        "--producer",
        metavar=message("metavar.producer"),
        help=message("cli.commands_only_producer_help"),
    )
    parse = add_parser(actions, "parse", "cli.commands_parse_help")
    _producer(parse)
    parse.add_argument(
        "line", metavar=message("metavar.line"), help=message("cli.commands_line_help")
    )
    validate = add_parser(actions, "validate", "cli.commands_validate_help")
    _call(validate)
    validate.add_argument(
        "--store",
        metavar=message("metavar.store"),
        help=message("cli.commands_store_help"),
    )
    written = add_parser(actions, "format", "cli.commands_format_help")
    _call(written)
    written.add_argument(
        "--run",
        type=json_object,
        default={},
        metavar="JSON",
        help=message("cli.commands_run_help"),
    )


def main(
    args: argparse.Namespace,
    paths: AppPaths,
    registry: PluginRegistry,
    out: TextIO,
    err: TextIO,
) -> int:
    """Run an action of ``archiwista commands``; return the exit status.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments of ``commands`` (``action`` names the action).
    paths : AppPaths
        Configuration file: the stores of ``validate``.
    registry : PluginRegistry
        Producer plugins.
    out, err : TextIO
        The route's model (as JSON with ``--json``); a refusal's Polish message
        and its ``archiwista-error/1`` document go to ``err``.

    Returns
    -------
    int
        ``0`` on success; a refusal returns the exit code of its registry code.
    """
    try:
        model, text = _ACTIONS[args.action](args, paths, registry)
    except SettingsValidationError as error:
        return refuse(
            exception_problem(
                error, with_detail(message("cli.commands_failed"), str(error))
            ),
            err,
        )
    except ArchiwistaError as error:
        return refuse(describe(error), err)
    out.write((model.model_dump_json() if args.json else text) + "\n")
    return 0


def _list(
    args: argparse.Namespace, paths: AppPaths, registry: PluginRegistry
) -> _Output:
    found = CommandList.of(list_commands(registry, producer=args.producer))
    lines = [
        message(
            "cli.commands_item",
            producer=item.producer,
            command=item.command,
            summary=item.summary,
        )
        for item in found.items
    ]
    return found, "\n".join(lines) or message("cli.commands_none")


def _parse(
    args: argparse.Namespace, paths: AppPaths, registry: PluginRegistry
) -> _Output:
    call = CommandCallItem.of(parse_command(registry, args.producer, args.line))
    lines = [
        message("cli.commands_call", producer=call.producer, command=call.command),
        message("cli.commands_options", options=_json(call.options)),
    ]
    if call.run:
        lines.append(message("cli.commands_run", run=_json(call.run)))
    return call, "\n".join(lines)


def _validate(
    args: argparse.Namespace, paths: AppPaths, registry: PluginRegistry
) -> _Output:
    settings = ConfigStore(paths.config_file).load()
    asked = CommandCall(args.producer, args.name, args.options)
    call = CommandCallItem.of(
        validate_command(registry, settings, asked, store=args.store)
    )
    lines = [
        message("cli.commands_valid", producer=call.producer, command=call.command),
        message("cli.commands_options", options=_json(call.options)),
    ]
    return call, "\n".join(lines)


def _format(
    args: argparse.Namespace, paths: AppPaths, registry: PluginRegistry
) -> _Output:
    call = CommandCall(args.producer, args.name, args.options, args.run)
    line = CommandLine.of(call, format_command(registry, call))
    return line, line.line


_ACTIONS: dict[str, _Action] = {
    "list": _list,
    "parse": _parse,
    "validate": _validate,
    "format": _format,
}


def _producer(parser: argparse.ArgumentParser) -> None:
    """Add the producer, the first argument of every action but ``list``."""
    parser.add_argument(
        "producer",
        metavar=message("metavar.producer"),
        help=message("cli.commands_producer_help"),
    )


def _call(parser: argparse.ArgumentParser) -> None:
    """Add the producer, the command and ``--options`` of a call."""
    _producer(parser)
    # Not ``command``: the namespace's ``command`` names ``commands`` itself.
    parser.add_argument(
        "name",
        metavar=message("metavar.command"),
        help=message("cli.commands_command_help"),
    )
    parser.add_argument(
        "--options",
        type=json_object,
        default={},
        metavar="JSON",
        help=message("cli.commands_options_help"),
    )


def json_object(text: str) -> dict[str, Any]:
    """Read the value of ``--options`` or ``--run``: a JSON object (a usage error)."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        detail = with_detail(message("cli.commands_json_object"), str(error))
        raise argparse.ArgumentTypeError(detail) from error
    if not isinstance(value, dict):
        raise argparse.ArgumentTypeError(message("cli.commands_json_object"))
    return value


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)
