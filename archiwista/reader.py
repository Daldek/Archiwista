"""Read-only commands over the local index for people, scripts and AI agents.

``archiwista status``, ``sources``, ``search``, ``entry``, ``version``,
``projects`` and ``project`` (SPEC 9, plan step 12) call the services of
the HTTP routes (``read_health``, ``search_slots``, ``slot_card``,
``version_card``, ``read_projects``, ``project_card``) as the owner of the
local installation (``LOCAL_OWNER``), whose project visibility comes from the same
``Authorizer`` as ``current_principal`` gives a session, so the answers pass
the same visibility filter (A-ADR-029). ``--json`` prints exactly the
response model of the matching route on stdout; a failure prints the route's
RFC 9457 problem there instead and exits with status 1, the Polish text
always going to stderr. The options of ``search`` are generated from
``CatalogFilters``, the query model of ``GET /slots``: one option per
parameter, of the same name, validated by the same model.
"""

import argparse
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import TextIO

from pydantic import BaseModel, ValidationError

from archiwista.api.errors import service_problem, validation_problem
from archiwista.api.health import read_health, source_infos
from archiwista.api.models import (
    CatalogFilters,
    CatalogPage,
    Health,
    IndexAnswer,
    Issue,
    ProjectCard,
    SlotCard,
    SourceList,
    Version,
    VersionCard,
)
from archiwista.api.projects import project_card, read_projects
from archiwista.api.slots import search_slots, slot_card, version_card
from archiwista.auth import LOCAL_OWNER, ProjectVisibility
from archiwista.auth.authorize import Authorizer
from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    SettingsValidationError,
)
from archiwista.errors import ArchiwistaError, StateError
from archiwista.index import IndexQueries, IndexUnsupportedError
from archiwista.messages import MESSAGES, with_detail
from archiwista.sources.registry import PluginRegistry
from archiwista.state import StateStore

READ_COMMANDS = frozenset(
    {"status", "sources", "search", "entry", "version", "projects", "project"}
)
# ``q`` is the positional QUERY of ``search``; every other parameter of
# ``GET /slots`` is the option ``--<name with hyphens>``.
_QUERY = "q"

type _Commands = argparse._SubParsersAction[argparse.ArgumentParser]


@dataclass(frozen=True, slots=True)
class _Reader:
    """What a command reads with: settings, plugins, the index, visibility."""

    settings: AppSettings
    registry: PluginRegistry
    queries: IndexQueries
    visible: ProjectVisibility


@dataclass(frozen=True, slots=True)
class _Output:
    """What a command prints: the API model with ``--json``, else Polish text."""

    model: BaseModel
    text: str


class _InvalidQuery(Exception):
    """Options of ``search`` the query model refuses (``422 validation_error``)."""

    def __init__(self, problem: dict[str, object]) -> None:
        super().__init__(problem["detail"])
        self.problem = problem


type _Command = Callable[[argparse.Namespace, _Reader], _Output]


def add_read_commands(commands: _Commands) -> None:
    """Add the read commands to ``archiwista`` (see the module).

    Parameters
    ----------
    commands : argparse._SubParsersAction
        Subcommands of the ``archiwista`` parser.
    """
    _parser(commands, "status", "cli_status_help")
    _parser(commands, "sources", "cli_sources_help")
    search = _parser(commands, "search", "cli_search_help")
    search.add_argument(
        _QUERY, nargs="?", metavar="ZAPYTANIE", help=MESSAGES["cli_search_q_help"]
    )
    for name in CatalogFilters.model_fields:
        if name != _QUERY:
            search.add_argument(
                "--" + name.replace("_", "-"),
                dest=name,
                help=MESSAGES[f"cli_search_{name}_help"],
            )
    entry = _parser(commands, "entry", "cli_entry_help")
    entry.add_argument("store", metavar="MAGAZYN", help=MESSAGES["cli_store_id_help"])
    entry.add_argument("slot", metavar="SLOT", help=MESSAGES["cli_slot_help"])
    version = _parser(commands, "version", "cli_version_help")
    version.add_argument("store", metavar="MAGAZYN", help=MESSAGES["cli_store_id_help"])
    version.add_argument(
        "version", metavar="WERSJA", help=MESSAGES["cli_version_path_help"]
    )
    projects = _parser(commands, "projects", "cli_projects_help")
    projects.add_argument("--store", help=MESSAGES["cli_projects_store_help"])
    project = _parser(commands, "project", "cli_project_card_help")
    project.add_argument(
        "project", metavar="PROJEKT", help=MESSAGES["cli_project_help"]
    )


def read_main(
    args: argparse.Namespace,
    paths: AppPaths,
    registry: PluginRegistry,
    out: TextIO,
    err: TextIO,
) -> int:
    """Run one of the commands added by ``add_read_commands``.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments (``command`` in ``READ_COMMANDS``).
    paths : AppPaths
        Configuration file, local index and state database.
    registry : PluginRegistry
        Producer plugins (sources, ``bbox`` in another CRS).
    out, err : TextIO
        Results (the API model as JSON with ``--json``) and Polish text.

    Returns
    -------
    int
        ``0`` on success, ``1`` when the request fails or the settings, the
        index or the state database cannot be used.
    """
    try:
        settings = ConfigStore(paths.config_file).load()
        visible = Authorizer(
            StateStore(paths.state_file), lambda: settings
        ).visible_projects(LOCAL_OWNER)
        queries = IndexQueries(paths.index_file)
    except (SettingsValidationError, IndexUnsupportedError, StateError) as error:
        err.write(with_detail(MESSAGES["cli_read_failed"], str(error)) + "\n")
        return 1
    with queries:
        reader = _Reader(settings, registry, queries, visible)
        try:
            output = _COMMANDS[args.command](args, reader)
        except _InvalidQuery as error:
            return _refused(error.problem, out, err, as_json=args.json)
        except ArchiwistaError as error:
            problem = service_problem(error)
            if problem is None:
                raise
            return _refused(problem, out, err, as_json=args.json)
    out.write((output.model.model_dump_json() if args.json else output.text) + "\n")
    return 0


def search_filters(args: argparse.Namespace) -> CatalogFilters:
    """Return the ``GET /slots`` query of the given ``search`` options.

    Options left out keep the model's defaults, as parameters left out of
    the URL do; values are validated by the model as the route validates
    them, so a refusal is the same ``422 validation_error`` problem.
    """
    values = {
        name: getattr(args, name)
        for name in CatalogFilters.model_fields
        if getattr(args, name) is not None
    }
    try:
        return CatalogFilters.model_validate(values)
    except ValidationError as error:
        located = ({**item, "loc": ("query", *item["loc"])} for item in error.errors())
        raise _InvalidQuery(validation_problem(located)) from None


def _refused(
    problem: dict[str, object], out: TextIO, err: TextIO, *, as_json: bool
) -> int:
    if as_json:
        out.write(_json_line(problem))
    err.write(f"{problem['detail']}\n")
    return 1


def _json_line(data: dict[str, object]) -> str:
    return json.dumps(data, ensure_ascii=False) + "\n"


# Commands.


def _status(args: argparse.Namespace, reader: _Reader) -> _Output:
    health = read_health(reader.settings, reader.registry, reader.queries)
    return _Output(health, _health_text(health))


def _sources(args: argparse.Namespace, reader: _Reader) -> _Output:
    sources = SourceList(items=source_infos(reader.registry))
    lines = [
        MESSAGES["cli_source_line"].format(
            producer=item.producer,
            version=item.package_version or MESSAGES["cli_none"],
            message=item.message,
        )
        + (f" {item.fix}" if item.fix else "")
        for item in sources.items
    ]
    return _Output(sources, "\n".join(lines))


def _search(args: argparse.Namespace, reader: _Reader) -> _Output:
    page = search_slots(
        reader.queries,
        reader.settings,
        reader.registry,
        search_filters(args),
        visible=reader.visible,
    )
    return _Output(page, _page_text(page))


def _entry(args: argparse.Namespace, reader: _Reader) -> _Output:
    card = slot_card(
        reader.queries, reader.settings, args.store, args.slot, visible=reader.visible
    )
    return _Output(card, _slot_text(card))


def _version(args: argparse.Namespace, reader: _Reader) -> _Output:
    card = version_card(
        reader.queries,
        reader.settings,
        args.store,
        args.version,
        visible=reader.visible,
    )
    return _Output(card, _version_text(card))


def _projects(args: argparse.Namespace, reader: _Reader) -> _Output:
    projects = read_projects(
        reader.queries, reader.settings, args.store, visible=reader.visible
    )
    lines = [
        MESSAGES["cli_project_line"].format(
            project=item.project,
            name=item.name,
            store=_value(item.store),
            tasks=item.tasks,
            pins=item.pins,
            missing=item.missing_pins,
        )
        for item in projects.items
    ]
    return _Output(
        projects, _with_stale(projects, lines or [MESSAGES["cli_no_projects"]])
    )


def _project(args: argparse.Namespace, reader: _Reader) -> _Output:
    card = project_card(reader.queries, args.project, visible=reader.visible)
    return _Output(card, _project_text(card))


_COMMANDS: dict[str, _Command] = {
    "status": _status,
    "sources": _sources,
    "search": _search,
    "entry": _entry,
    "version": _version,
    "projects": _projects,
    "project": _project,
}


# Text.


def _health_text(health: Health) -> str:
    lines = [
        MESSAGES["cli_status_line"].format(
            version=health.archiwista,
            schema=health.index.schema_version,
            size=_size(health.index.size_bytes),
        )
    ]
    lines.extend(
        MESSAGES["cli_source_line"].format(
            producer=item.producer,
            version=item.package_version or MESSAGES["cli_none"],
            message=item.message,
        )
        for item in health.sources
    )
    for item in health.stores:
        state = item.state
        line = MESSAGES["cli_store_line"].format(
            store=item.store,
            name=item.name,
            status=MESSAGES[f"cli_store_status_{state.status}"],
            slots=state.slots,
            versions=state.versions,
            missing=state.missing_versions,
            issues=state.issues,
            indexed_at=_time(state.indexed_at),
        )
        if state.running_job is not None:
            line += MESSAGES["cli_store_job"].format(
                kind=MESSAGES.get(
                    f"job_kind_{state.running_job.kind}", state.running_job.kind
                ),
                state=MESSAGES.get(
                    f"job_state_{state.running_job.state}", state.running_job.state
                ),
            )
        lines.append(line)
    if not health.stores:
        lines.append(MESSAGES["reindex_no_stores"])
    return "\n".join(lines)


def _page_text(page: CatalogPage) -> str:
    lines = [
        MESSAGES["cli_search_row"].format(
            store=item.store,
            slot=item.slot,
            label=_value(item.version.label if item.version else None),
            year=_value(item.version.data_year if item.version else None),
        )
        for item in page.items
    ] or [MESSAGES["cli_no_rows"]]
    lines.append(
        MESSAGES["cli_search_summary"].format(
            count=len(page.items),
            footprint=page.groups.footprint,
            country=page.groups.country,
            none=page.groups.none,
        )
    )
    if page.next_cursor is not None:
        lines.append(MESSAGES["cli_search_next"].format(cursor=page.next_cursor))
    return _with_stale(page, lines)


def _slot_text(card: SlotCard) -> str:
    lines = [
        MESSAGES["cli_entry_title"].format(
            store=card.store, slot=card.slot, name=card.name
        ),
        MESSAGES["cli_entry_facts"].format(
            segment=card.segment.label,
            unit=_value(card.unit),
            product=_value(card.product),
            country=_value(card.country),
            status=card.status,
        ),
    ]
    lines.extend(_version_line(version) for version in card.versions)
    if card.paths is not None:
        lines.append(MESSAGES["cli_path_line"].format(path=card.paths.local))
    lines.extend(_problem_lines(card.problems))
    return _with_stale(card, lines)


def _version_line(version: Version) -> str:
    marks = ""
    if version.is_current:
        marks += MESSAGES["cli_version_current"]
    if version.is_full_sheet:
        marks += MESSAGES["cli_version_full_sheet"]
    if version.state == "missing":
        marks += MESSAGES["cli_version_missing"]
    if version.pinned_by:
        names = ", ".join(pin.name for pin in version.pinned_by)
        marks += MESSAGES["cli_version_pinned"].format(projects=names)
    return MESSAGES["cli_version_line"].format(
        path=version.path,
        label=_value(version.label),
        year=_value(version.data_year),
        marks=marks,
    )


def _version_text(card: VersionCard) -> str:
    version = card.version
    lines = [
        MESSAGES["cli_version_title"].format(
            store=card.store, path=version.path, slot=card.slot
        ),
        _version_line(version),
        MESSAGES["cli_version_facts"].format(
            label=_value(version.label),
            year=_value(version.data_year),
            size=_size(version.size_bytes),
            crs=_value(version.crs.horizontal),
            sha256=_value(version.sha256),
        ),
        MESSAGES["cli_version_license"].format(
            license=_value(card.license), attribution=_value(card.attribution)
        ),
    ]
    if card.paths is not None:
        lines.append(MESSAGES["cli_path_line"].format(path=card.paths.local))
    return _with_stale(card, lines)


def _project_text(card: ProjectCard) -> str:
    lines = [
        MESSAGES["cli_project_line"].format(
            project=card.project,
            name=card.name,
            store=_value(card.store),
            tasks=len(card.tasks),
            pins=len(card.pins),
            missing=card.missing_pins,
        )
    ]
    lines.extend(
        MESSAGES["cli_task_line"].format(
            task=task.task, command=task.command, status=_value(task.status)
        )
        for task in card.tasks
    )
    lines.extend(
        MESSAGES["cli_pin_line"].format(
            version=pin.version, task=_value(pin.task), state=pin.state
        )
        for pin in card.pins
    )
    lines.extend(_problem_lines(card.problems))
    return _with_stale(card, lines)


def _problem_lines(problems: Iterable[Issue]) -> list[str]:
    return [
        MESSAGES["cli_problem_line"].format(
            message=problem.message, instruction=problem.instruction
        )
        for problem in problems
    ]


def _with_stale(answer: IndexAnswer, lines: list[str]) -> str:
    notes = [
        MESSAGES["cli_stale_line"].format(
            store=item.store, indexed_at=_time(item.indexed_at)
        )
        for item in answer.stale_stores
    ]
    return "\n".join([*lines, *notes])


def _value(value: object) -> str:
    return MESSAGES["cli_none"] if value is None else str(value)


def _time(value: datetime | None) -> str:
    if value is None:
        return MESSAGES["cli_never"]
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def _size(size: int | None) -> str:
    if size is None:
        return MESSAGES["cli_none"]
    if size < 1_000_000:
        return f"{size / 1000:.1f} kB".replace(".", ",")
    return f"{size / 1_000_000:.1f} MB".replace(".", ",")


# Parsers.


def _parser(commands: _Commands, name: str, help_key: str) -> argparse.ArgumentParser:
    text = MESSAGES[help_key]
    parser = commands.add_parser(name, help=text, description=text)
    parser.add_argument("--json", action="store_true", help=MESSAGES["cli_json_help"])
    return parser
