"""``archiwista log``: the action log at the terminal (plan v0.4 T8, A-ADR-047).

``log list`` prints a page of the log newest first, as ``GET /log`` answers it
(``ActionPage`` with ``--json``); ``log export --format jsonl|csv`` writes
every entry the filters select, the bytes of ``GET /log/export``, to standard
output or to ``--output FILE`` (mode ``0600``; an existing file is
replaced), and logs the export (``log.export``). Both take the filters of the
routes: ``--actor``, ``--action`` (a name or a group's prefix with a dot),
``--outcome``, ``--target``, ``--since`` and ``--until`` (ISO 8601 with a
zone). They act as the owner of the installation (``LOCAL_OWNER``, who may
read the log) through ``archiwista.services.log`` and the ``Authorizer``
over the state database. A refusal prints nothing on standard output and
ends standard error with its ``archiwista-error/1`` document.
"""

import argparse
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import TextIO

from pydantic import ValidationError

from archiwista.api.models import (
    ActionEntryModel,
    ActionExportQuery,
    ActionPage,
    ActionPageQuery,
)
from archiwista.auth import LOCAL_OWNER
from archiwista.auth.authorize import Authorizer
from archiwista.commands import Commands, add_parser
from archiwista.config import (
    AppPaths,
    ConfigStore,
    SettingsValidationError,
    write_text_atomic,
)
from archiwista.error_document import (
    describe,
    exception_problem,
    refuse,
    validation_problem,
)
from archiwista.errors import ArchiwistaError, StateError
from archiwista.messages import label, lookup, message, with_detail
from archiwista.services import log as log_service
from archiwista.sources.registry import PluginRegistry
from archiwista.state import OUTCOMES, StateStore

COMMANDS = frozenset({"log"})
# Filters of the routes; ``--action`` is ``action_filter`` beside the command's
# own ``action`` (``list``, ``export``).
_FILTERS = {
    "actor": "actor",
    "action": "action_filter",
    "outcome": "outcome",
    "target": "target",
    "since": "since",
    "until": "until",
}
# What keeps the command from opening the settings or the state database.
_UNUSABLE = (SettingsValidationError, StateError, OSError, sqlite3.Error)


def add_commands(commands: Commands) -> None:
    """Add ``archiwista log`` and its actions (see the module).

    Parameters
    ----------
    commands : argparse._SubParsersAction
        Subcommands of the ``archiwista`` parser.
    """
    text = message("log.help")
    parser = commands.add_parser("log", help=text, description=text)
    actions = parser.add_subparsers(
        dest="action", required=True, metavar=message("metavar.action")
    )
    listed = add_parser(actions, "list", "log.list_help")
    _add_filters(listed)
    listed.add_argument(
        "--limit", metavar=message("metavar.number"), help=message("log.limit_help")
    )
    listed.add_argument(
        "--cursor", metavar=message("metavar.cursor"), help=message("log.cursor_help")
    )
    text = message("log.export_help")
    exported = actions.add_parser("export", help=text, description=text)
    _add_filters(exported)
    exported.add_argument(
        "--format",
        choices=log_service.EXPORT_FORMATS,
        default="jsonl",
        help=message("log.format_help"),
    )
    exported.add_argument(
        "--output",
        type=Path,
        metavar=message("metavar.file"),
        help=message("log.output_help"),
    )


def main(
    args: argparse.Namespace,
    paths: AppPaths,
    registry: PluginRegistry,
    out: TextIO,
    err: TextIO,
) -> int:
    """Run an action of ``archiwista log``; return the exit status.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments of ``log`` (``action`` names the action).
    paths : AppPaths
        Configuration and state database.
    registry : PluginRegistry
        Unused: the log needs no producer.
    out, err : TextIO
        The page (as JSON with ``--json``) or the export; the count of an
        export, and a refusal's Polish message with its ``archiwista-error/1``
        document, go to ``err``.

    Returns
    -------
    int
        ``0``; the exit code of the registry code of a refusal.
    """
    given = {name: getattr(args, option) for name, option in _FILTERS.items()}
    model: type[ActionPageQuery | ActionExportQuery]
    if args.action == "list":
        model = ActionPageQuery
        given.update(limit=args.limit, cursor=args.cursor)
    else:
        model = ActionExportQuery
        given.update(format=args.format)
    try:
        query = model.model_validate(
            {name: value for name, value in given.items() if value is not None}
        )
    except ValidationError as error:
        located = ({**item, "loc": ("query", *item["loc"])} for item in error.errors())
        return refuse(validation_problem(located), err)
    try:
        settings = ConfigStore(paths.config_file).load()
        decisions = Authorizer(StateStore(paths.state_file), lambda: settings)
    except _UNUSABLE as error:
        return _unusable(error, err)
    try:
        if isinstance(query, ActionPageQuery):
            found = log_service.read(decisions, LOCAL_OWNER, query.query())
            out.write(_page_output(ActionPage.of(found), as_json=args.json) + "\n")
            return 0
        export = log_service.export(decisions, LOCAL_OWNER, query.query(), query.format)
        if args.output is None:
            _write(export.chunks(), out)
            err.write(message("log.exported", count=export.count) + "\n")
        else:
            write_text_atomic(args.output, "".join(export.chunks()))
            text = message("log.exported_file", path=args.output, count=export.count)
            err.write(text + "\n")
    except ArchiwistaError as error:
        return refuse(describe(error), err)
    except _UNUSABLE as error:
        return _unusable(error, err)
    return 0


def _add_filters(parser: argparse.ArgumentParser) -> None:
    """Add the filters of ``GET /log`` to an action's parser."""
    parser.add_argument(
        "--actor", metavar=message("metavar.person"), help=message("log.actor_help")
    )
    parser.add_argument(
        "--action",
        dest="action_filter",
        metavar=message("metavar.action"),
        help=message("log.action_help"),
    )
    parser.add_argument("--outcome", choices=OUTCOMES, help=message("log.outcome_help"))
    parser.add_argument(
        "--target", metavar=message("metavar.target"), help=message("log.target_help")
    )
    parser.add_argument(
        "--since", metavar=message("metavar.time"), help=message("log.since_help")
    )
    parser.add_argument(
        "--until", metavar=message("metavar.time"), help=message("log.until_help")
    )


def _unusable(error: Exception, err: TextIO) -> int:
    """Refuse a command whose settings or state database cannot be opened."""
    detail = with_detail(message("log.failed"), str(error))
    return refuse(exception_problem(error, detail), err)


def _page_output(page: ActionPage, *, as_json: bool) -> str:
    """Return a page as the route's JSON, or for a person: a line per entry."""
    if as_json:
        return page.model_dump_json()
    lines = [_entry_line(item) for item in page.items] or [message("log.list_none")]
    lines.append(message("log.list_count", shown=len(page.items), total=page.total))
    if page.next_cursor is not None:
        lines.append(message("log.list_next", cursor=page.next_cursor))
    return "\n".join(lines)


def _entry_line(item: ActionEntryModel) -> str:
    """Return an entry for a person: when, who, what, about what, the outcome."""
    actor: str
    if item.actor_kind == "agent":
        actor = message("log.agent_of", actor=item.actor)
    elif item.actor_kind == "scheduler":
        actor = message("log.scheduler")
    else:
        actor = item.actor
    return message(
        "log.list_line",
        at=item.at.isoformat(timespec="seconds"),
        actor=actor,
        action=lookup(f"log.action_{item.action.replace('.', '_')}", item.action),
        target=item.target,
        outcome=label("log.outcome", item.outcome),
    )


def _write(chunks: Iterable[str], out: TextIO) -> None:
    """Write an export to standard output as UTF-8, its line ends untouched."""
    binary = getattr(out, "buffer", None)
    if binary is None:
        out.writelines(chunks)
        return
    out.flush()
    for chunk in chunks:
        binary.write(chunk.encode())
    binary.flush()
