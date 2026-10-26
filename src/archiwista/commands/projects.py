"""``archiwista project-init``, ``project-add``, ``project-remove``, ``project-status``.

Projects changed through their producer (plan of 2026-10-25, A7; ADR-039).
``project-init PRODUCENT KATALOG --store MAGAZYN`` creates a project of the
producer in a directory (``POST /projects``; a relative directory is taken
from the current one), ``project-add PROJEKT NAZWA POLECENIE [--options JSON]
[--producer PRODUCENT]`` adds a task to a project (``POST
/projects/{project}/tasks``) and ``project-remove PROJEKT NAZWA`` removes one
(``DELETE /projects/{project}/tasks/{name}``): each prints the project's card
as the index holds it right after the change (``ProjectCard``).
``project-status PROJEKT`` prints the producer's check of a project now
(``GET /projects/{project}/status``, ``ProjectStatus``). They call
``archiwista.services.projects`` and ``archiwista.api.projects`` without
HTTP, as the owner of the installation (``LOCAL_OWNER``, an administrator,
who may change every project) through the ``Authorizer`` over the state
database; ``--json`` prints the route's model, a refusal prints no model and
ends standard error with its ``archiwista-error/1`` document. Nothing here
uses the network or writes a store.
"""

import argparse
import os
import sqlite3
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from pydantic import BaseModel, ValidationError

from archiwista.api.models import ProjectRequest, ProjectStatus, TaskRequest
from archiwista.api.projects import check_project, project_card
from archiwista.auth import LOCAL_OWNER, ProjectVisibility
from archiwista.auth.authorize import Authorizer
from archiwista.commands import Commands, add_parser
from archiwista.commands.producer_commands import json_object
from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    SettingsService,
    SettingsValidationError,
)
from archiwista.error_document import (
    Problem,
    describe,
    exception_problem,
    refuse,
    validation_problem,
)
from archiwista.errors import ArchiwistaError, StateError
from archiwista.index import IndexQueries, IndexUnsupportedError
from archiwista.messages import message, with_detail
from archiwista.reader import project_text
from archiwista.services import projects as project_service
from archiwista.sources.registry import PluginRegistry
from archiwista.state import StateStore

COMMANDS = frozenset(
    {"project-init", "project-add", "project-remove", "project-status"}
)

# What an action prints: the route's model with ``--json``, else text for people.
type _Output = tuple[BaseModel, str]


@dataclass(frozen=True, slots=True)
class _Place:
    """What every action works with: the settings, the index and the decisions."""

    registry: PluginRegistry
    settings: AppSettings
    queries: IndexQueries
    index: Path
    decisions: Authorizer
    visible: ProjectVisibility


type _Action = Callable[[argparse.Namespace, _Place], _Output]


class _InvalidBody(Exception):
    """Arguments the route's request model refuses (``400 validation_error``)."""

    def __init__(self, problem: Problem) -> None:
        super().__init__(problem.detail)
        self.problem = problem


def add_commands(commands: Commands) -> None:
    """Add ``project-init``, ``project-add``, ``project-remove``, ``project-status``.

    Parameters
    ----------
    commands : argparse._SubParsersAction
        Subcommands of the ``archiwista`` parser.
    """
    created = add_parser(commands, "project-init", "cli.project_init_help")
    created.add_argument(
        "producer",
        metavar=message("metavar.producer"),
        help=message("cli.commands_producer_help"),
    )
    created.add_argument(
        "directory",
        metavar=message("metavar.directory"),
        help=message("cli.project_directory_help"),
    )
    created.add_argument(
        "--store",
        metavar=message("metavar.store"),
        help=message("cli.project_store_help"),
    )
    added = add_parser(commands, "project-add", "cli.project_add_help")
    _project(added)
    _task(added)
    # Not ``command``: the namespace's ``command`` names ``project-add`` itself.
    added.add_argument(
        "call",
        metavar=message("metavar.command"),
        help=message("cli.project_command_help"),
    )
    added.add_argument(
        "--options",
        type=json_object,
        default={},
        metavar="JSON",
        help=message("cli.commands_options_help"),
    )
    added.add_argument(
        "--producer",
        metavar=message("metavar.producer"),
        help=message("cli.project_producer_help"),
    )
    removed = add_parser(commands, "project-remove", "cli.project_remove_help")
    _project(removed)
    _task(removed)
    status = add_parser(commands, "project-status", "cli.project_status_help")
    _project(status)


def main(
    args: argparse.Namespace,
    paths: AppPaths,
    registry: PluginRegistry,
    out: TextIO,
    err: TextIO,
) -> int:
    """Run one of the project commands; return the exit status.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments (``command`` names the command).
    paths : AppPaths
        Configuration (the stores and project directories), local index and
        state database.
    registry : PluginRegistry
        Producer plugins: the producer writes and reads its manifests.
    out, err : TextIO
        The route's model (as JSON with ``--json``); a refusal's Polish
        message and its ``archiwista-error/1`` document go to ``err``.

    Returns
    -------
    int
        ``0`` on success; a refusal returns the exit code of its registry code.
    """
    with ExitStack() as stack:
        try:
            service = SettingsService(ConfigStore(paths.config_file), registry)
            decisions = Authorizer(StateStore(paths.state_file), service.get)
            place = _Place(
                registry=registry,
                settings=service.get(),
                queries=stack.enter_context(IndexQueries(paths.index_file)),
                index=paths.index_file,
                decisions=decisions,
                visible=decisions.visible_projects(LOCAL_OWNER),
            )
        except _UNUSABLE as error:
            detail = with_detail(message("cli.project_failed"), str(error))
            return refuse(exception_problem(error, detail), err)
        try:
            model, text = _ACTIONS[args.command](args, place)
        except _InvalidBody as error:
            return refuse(error.problem, err)
        except ArchiwistaError as error:
            return refuse(describe(error), err)
    out.write((model.model_dump_json() if args.json else text) + "\n")
    return 0


def _init(args: argparse.Namespace, place: _Place) -> _Output:
    """Create a project as ``POST /projects`` does; print its card."""
    given: dict[str, Any] = {
        "producer": args.producer,
        "path": os.path.abspath(args.directory),
    }
    if args.store is not None:
        given["store"] = args.store
    body = _body(ProjectRequest, given)
    key = project_service.create_project(
        place.registry,
        place.settings,
        place.index,
        place.decisions,
        producer=body.producer,
        path=body.path,
        store=body.store,
        actor=LOCAL_OWNER,
    )
    card = project_card(place.queries, key, visible=place.visible)
    done = message("cli.project_created", project=key, path=body.path)
    return card, f"{done}\n{project_text(card)}"


def _add(args: argparse.Namespace, place: _Place) -> _Output:
    """Add a task as ``POST /projects/{project}/tasks`` does; print the card."""
    given: dict[str, Any] = {
        "name": args.task,
        "command": args.call,
        "options": args.options,
    }
    if args.producer is not None:
        given["producer"] = args.producer
    body = _body(TaskRequest, given)
    key = project_service.add_project_task(
        place.registry,
        place.settings,
        place.queries,
        place.index,
        place.decisions,
        args.project,
        name=body.name,
        command=body.command,
        options=body.options,
        producer=body.producer,
        actor=LOCAL_OWNER,
        visible=place.visible,
    )
    card = project_card(place.queries, key, visible=place.visible)
    done = message("cli.project_task_added", project=key, task=body.name)
    return card, f"{done}\n{project_text(card)}"


def _remove(args: argparse.Namespace, place: _Place) -> _Output:
    """Remove a task as ``DELETE /projects/{project}/tasks/{name}``; the card."""
    key = project_service.remove_project_task(
        place.registry,
        place.settings,
        place.queries,
        place.index,
        place.decisions,
        args.project,
        name=args.task,
        actor=LOCAL_OWNER,
        visible=place.visible,
    )
    card = project_card(place.queries, key, visible=place.visible)
    done = message("cli.project_task_removed", project=key, task=args.task)
    return card, f"{done}\n{project_text(card)}"


def _status(args: argparse.Namespace, place: _Place) -> _Output:
    """Ask the producer as ``GET /projects/{project}/status`` does."""
    status = check_project(
        place.queries,
        place.settings,
        place.registry,
        args.project,
        visible=place.visible,
    )
    return status, _status_text(status)


_ACTIONS: dict[str, _Action] = {
    "project-init": _init,
    "project-add": _add,
    "project-remove": _remove,
    "project-status": _status,
}

# What keeps a command from opening the settings, the state or the index.
_UNUSABLE = (
    SettingsValidationError,
    StateError,
    IndexUnsupportedError,
    OSError,
    sqlite3.Error,
)


def _body[Body: BaseModel](model: type[Body], given: dict[str, Any]) -> Body:
    """Return the route's request model of the arguments, or refuse them."""
    try:
        return model.model_validate(given)
    except ValidationError as error:
        located = ({**item, "loc": ("body", *item["loc"])} for item in error.errors())
        raise _InvalidBody(validation_problem(located)) from None


def _status_text(status: ProjectStatus) -> str:
    """Return the producer's check of a project for a person."""
    none = message("cli.none")
    lines = [
        message(
            "cli.project_status_line",
            project=status.project,
            producer=status.producer,
            status=status.status or none,
            checked_at=status.checked_at.astimezone().strftime("%Y-%m-%d %H:%M"),
        )
    ]
    lines += [
        message("cli.project_status_task", task=task.task, status=task.status or none)
        for task in status.tasks
    ]
    if status.stale:
        lines.append(message("cli.project_status_stale"))
    return "\n".join(lines)


def _project(parser: argparse.ArgumentParser) -> None:
    """Add the project, the first argument of a command on a project."""
    parser.add_argument(
        "project", metavar=message("metavar.project"), help=message("cli.project_help")
    )


def _task(parser: argparse.ArgumentParser) -> None:
    """Add the name of a task."""
    parser.add_argument(
        "task", metavar=message("metavar.name"), help=message("cli.project_task_help")
    )
