"""``archiwista project-init``, ``project-edit``, ``project-area``, ``project-store``.

Projects are Archiwista's own file ``archiwista-project.json`` (A-ADR-049).
``project-init KATALOG [--name NAZWA] [--description TEKST] [--area-id
OBSZAR]`` writes a new project in a directory (``POST /projects``; a
relative directory is taken from the current one), ``project-edit PROJEKT
[--name NAZWA] [--description TEKST]`` changes its name or description
(``PATCH /projects/{project}``), ``project-area PROJEKT (--area-id OBSZAR |
--clear)`` its area (``PUT /projects/{project}/area``) and ``project-store
PROJEKT PRODUCENT --store MAGAZYN`` the store of a producer's pins (``PUT
/projects/{project}/stores/{producer}``): each prints the project's card as
the index holds it right after the change (``ProjectCard``). They call
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

from archiwista.api.models import (
    AreaChoice,
    Preferences,
    ProjectCard,
    ProjectChange,
    ProjectRequest,
    StoreChoice,
)
from archiwista.api.projects import project_card
from archiwista.auth import LOCAL_OWNER
from archiwista.auth.authorize import Authorizer
from archiwista.commands import Commands, add_parser
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
from archiwista.services.preferences import read_preferences
from archiwista.sources.registry import PluginRegistry
from archiwista.state import StateStore

COMMANDS = frozenset({"project-init", "project-edit", "project-area", "project-store"})

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

    def card(self, key: str) -> ProjectCard:
        """Return a project's card as the local owner sees it now."""
        return project_card(
            self.queries,
            self.settings,
            self.preferences(),
            key,
            visible=self.decisions.visible_projects(LOCAL_OWNER),
            writable=self.decisions.writable_projects(LOCAL_OWNER),
        )

    def preferences(self) -> Preferences:
        """Return the local owner's preferences: ``personal`` of a copy path."""
        return read_preferences(self.decisions.state, LOCAL_OWNER)


type _Action = Callable[[argparse.Namespace, _Place], _Output]


class _InvalidBody(Exception):
    """Arguments the route's request model refuses (``400 validation_error``)."""

    def __init__(self, problem: Problem) -> None:
        super().__init__(problem.detail)
        self.problem = problem


def add_commands(commands: Commands) -> None:
    """Add ``project-init``, ``project-edit``, ``project-area``, ``project-store``.

    Parameters
    ----------
    commands : argparse._SubParsersAction
        Subcommands of the ``archiwista`` parser.
    """
    created = add_parser(commands, "project-init", "cli.project_init_help")
    created.add_argument(
        "directory",
        metavar=message("metavar.directory"),
        help=message("cli.project_directory_help"),
    )
    _texts(created)
    _area_id(created)
    edited = add_parser(commands, "project-edit", "cli.project_edit_help")
    _project(edited)
    _texts(edited)
    area = add_parser(commands, "project-area", "cli.project_area_help")
    _project(area)
    chosen = area.add_mutually_exclusive_group(required=True)
    _area_id(chosen)
    chosen.add_argument(
        "--clear", action="store_true", help=message("cli.project_clear_help")
    )
    store = add_parser(commands, "project-store", "cli.project_store_cmd_help")
    _project(store)
    store.add_argument(
        "producer",
        metavar=message("metavar.producer"),
        help=message("cli.commands_producer_help"),
    )
    store.add_argument(
        "--store",
        required=True,
        metavar=message("metavar.store"),
        help=message("cli.project_store_help"),
    )


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
        Producer plugins: the coordinate operations that read a project's
        area into the index.
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
            place = _Place(
                registry=registry,
                settings=service.get(),
                queries=stack.enter_context(IndexQueries(paths.index_file)),
                index=paths.index_file,
                decisions=Authorizer(StateStore(paths.state_file), service.get),
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
    given = _given(args, "name", "description", "area_id")
    body = _body(ProjectRequest, {"path": os.path.abspath(args.directory), **given})
    key = project_service.create_project(
        place.registry,
        place.settings,
        place.queries,
        place.index,
        place.decisions,
        path=body.path,
        name=body.name,
        description=body.description,
        area_id=body.area_id,
        actor=LOCAL_OWNER,
    )
    card = place.card(key)
    done = message("cli.project_created", project=key, path=body.path)
    return card, f"{done}\n{project_text(card)}"


def _edit(args: argparse.Namespace, place: _Place) -> _Output:
    """Change a project as ``PATCH /projects/{project}`` does; print the card."""
    body = _body(ProjectChange, _given(args, "name", "description"))
    key = project_service.update_project(
        place.registry,
        place.settings,
        place.queries,
        place.index,
        place.decisions,
        args.project,
        name=body.name,
        description=body.description,
        actor=LOCAL_OWNER,
        visible=place.decisions.visible_projects(LOCAL_OWNER),
    )
    return _changed(place, key)


def _area(args: argparse.Namespace, place: _Place) -> _Output:
    """Set a project's area as ``PUT /projects/{project}/area``; print the card."""
    body = _body(AreaChoice, {"area_id": None if args.clear else args.area_id})
    key = project_service.set_area(
        place.registry,
        place.settings,
        place.queries,
        place.index,
        place.decisions,
        args.project,
        area_id=body.area_id,
        actor=LOCAL_OWNER,
        visible=place.decisions.visible_projects(LOCAL_OWNER),
    )
    return _changed(place, key)


def _store(args: argparse.Namespace, place: _Place) -> _Output:
    """Set a producer's store as ``PUT …/stores/{producer}``; print the card."""
    body = _body(StoreChoice, {"store": args.store})
    key = project_service.set_store(
        place.registry,
        place.settings,
        place.queries,
        place.index,
        place.decisions,
        args.project,
        producer=args.producer,
        store=body.store,
        actor=LOCAL_OWNER,
        visible=place.decisions.visible_projects(LOCAL_OWNER),
    )
    return _changed(place, key)


def _changed(place: _Place, key: str) -> _Output:
    card = place.card(key)
    done = message("cli.project_changed", project=key)
    return card, f"{done}\n{project_text(card)}"


_ACTIONS: dict[str, _Action] = {
    "project-init": _init,
    "project-edit": _edit,
    "project-area": _area,
    "project-store": _store,
}

# What keeps a command from opening the settings, the state or the index.
_UNUSABLE = (
    SettingsValidationError,
    StateError,
    IndexUnsupportedError,
    OSError,
    sqlite3.Error,
)


def _given(args: argparse.Namespace, *names: str) -> dict[str, Any]:
    """Return the options among ``names`` the command line gave."""
    return {
        name: getattr(args, name) for name in names if getattr(args, name) is not None
    }


def _body[Body: BaseModel](model: type[Body], given: dict[str, Any]) -> Body:
    """Return the route's request model of the arguments, or refuse them."""
    try:
        return model.model_validate(given)
    except ValidationError as error:
        located = ({**item, "loc": ("body", *item["loc"])} for item in error.errors())
        raise _InvalidBody(validation_problem(located)) from None


def _project(parser: argparse.ArgumentParser) -> None:
    """Add the project, the first argument of a command on a project."""
    parser.add_argument(
        "project", metavar=message("metavar.project"), help=message("cli.project_help")
    )


def _texts(parser: argparse.ArgumentParser) -> None:
    """Add ``--name`` and ``--description``."""
    parser.add_argument(
        "--name", metavar=message("metavar.name"), help=message("cli.project_name_help")
    )
    parser.add_argument(
        "--description",
        metavar=message("metavar.text"),
        help=message("cli.project_description_help"),
    )


def _area_id(
    parser: argparse.ArgumentParser | argparse._MutuallyExclusiveGroup,
) -> None:
    """Add ``--area-id``."""
    parser.add_argument(
        "--area-id",
        metavar=message("metavar.area"),
        help=message("cli.project_area_id_help"),
    )
