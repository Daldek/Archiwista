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

from archiwista.api.health import read_health, source_list
from archiwista.api.models import (
    CatalogFilters,
    CatalogPage,
    Health,
    IndexAnswer,
    Issue,
    PinOutcome,
    Preferences,
    ProjectCard,
    ProjectStore,
    SlotCard,
    Version,
    VersionCard,
)
from archiwista.api.projects import project_card, read_projects
from archiwista.api.slots import search_slots, slot_card, version_card
from archiwista.auth import LOCAL_OWNER, ProjectVisibility, WritableProjects
from archiwista.auth.authorize import Authorizer
from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
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
from archiwista.messages import label, language, message, with_detail
from archiwista.services.preferences import read_preferences
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
    """What a command reads with: settings, plugins, the index, project access.

    ``preferences`` are the local owner's: their path aliases give
    ``personal`` of a copy path.
    """

    settings: AppSettings
    preferences: Preferences
    registry: PluginRegistry
    queries: IndexQueries
    visible: ProjectVisibility
    writable: WritableProjects


@dataclass(frozen=True, slots=True)
class _Output:
    """What a command prints: the API model with ``--json``, else Polish text."""

    model: BaseModel
    text: str


class _InvalidQuery(Exception):
    """Options of ``search`` the query model refuses (``400 validation_error``)."""

    def __init__(self, problem: Problem) -> None:
        super().__init__(problem.detail)
        self.problem = problem


type _Command = Callable[[argparse.Namespace, _Reader], _Output]


def add_read_commands(commands: _Commands) -> None:
    """Add the read commands to ``archiwista`` (see the module).

    Parameters
    ----------
    commands : argparse._SubParsersAction
        Subcommands of the ``archiwista`` parser.
    """
    _parser(commands, "status", "cli.status_help")
    _parser(commands, "sources", "cli.sources_help")
    search = _parser(commands, "search", "cli.search_help")
    search.add_argument(
        _QUERY,
        nargs="?",
        metavar=message("metavar.query"),
        help=message("cli.search_q_help"),
    )
    for name in CatalogFilters.model_fields:
        if name != _QUERY:
            search.add_argument(
                "--" + name.replace("_", "-"),
                dest=name,
                help=message(f"cli.search_{name}_help"),
            )
    entry = _parser(commands, "entry", "cli.entry_help")
    entry.add_argument(
        "store", metavar=message("metavar.store"), help=message("cli.store_id_help")
    )
    entry.add_argument("slot", metavar="SLOT", help=message("cli.slot_help"))
    version = _parser(commands, "version", "cli.version_help")
    version.add_argument(
        "store", metavar=message("metavar.store"), help=message("cli.store_id_help")
    )
    version.add_argument(
        "version",
        metavar=message("metavar.version"),
        help=message("cli.version_path_help"),
    )
    projects = _parser(commands, "projects", "cli.projects_help")
    projects.add_argument("--store", help=message("cli.projects_store_help"))
    project = _parser(commands, "project", "cli.project_card_help")
    project.add_argument(
        "project", metavar=message("metavar.project"), help=message("cli.project_help")
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
        decisions = Authorizer(StateStore(paths.state_file), lambda: settings)
        visible = decisions.visible_projects(LOCAL_OWNER)
        writable = decisions.writable_projects(LOCAL_OWNER)
        preferences = read_preferences(decisions.state, LOCAL_OWNER)
        queries = IndexQueries(paths.index_file)
    except (SettingsValidationError, IndexUnsupportedError, StateError) as error:
        return refuse(
            exception_problem(
                error, with_detail(message("cli.read_failed"), str(error))
            ),
            err,
        )
    with queries:
        reader = _Reader(settings, preferences, registry, queries, visible, writable)
        try:
            output = _COMMANDS[args.command](args, reader)
        except _InvalidQuery as error:
            return refuse(error.problem, err)
        except ArchiwistaError as error:
            return refuse(describe(error), err)
    out.write((output.model.model_dump_json() if args.json else output.text) + "\n")
    return 0


def search_filters(args: argparse.Namespace) -> CatalogFilters:
    """Return the ``GET /slots`` query of the given ``search`` options.

    Options left out keep the model's defaults, as parameters left out of
    the URL do; values are validated by the model as the route validates
    them, so a refusal is the same ``400 validation_error`` problem.
    """
    values = {
        name: getattr(args, name)
        for name in CatalogFilters.model_fields
        if getattr(args, name) is not None
    }
    try:
        with language("en"):  # the error document that reports a refusal is English
            return CatalogFilters.model_validate(values)
    except ValidationError as error:
        located = ({**item, "loc": ("query", *item["loc"])} for item in error.errors())
        raise _InvalidQuery(validation_problem(located)) from None


def _json_line(data: dict[str, object]) -> str:
    return json.dumps(data, ensure_ascii=False) + "\n"


# Commands.


def _status(args: argparse.Namespace, reader: _Reader) -> _Output:
    health = read_health(reader.settings, reader.registry, reader.queries)
    return _Output(health, _health_text(health))


def _sources(args: argparse.Namespace, reader: _Reader) -> _Output:
    sources = source_list(reader.registry)
    lines: list[str] = []
    for item in sources.items:
        line = message(
            "cli.source_line",
            producer=item.producer,
            version=item.package_version or message("cli.none"),
            message=item.message,
        )
        lines.append(f"{line} {item.fix}" if item.fix else line)
        if item.default_root is not None:
            lines.append(f"  {item.default_root.message}")
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
        reader.queries,
        reader.settings,
        reader.preferences,
        args.store,
        args.slot,
        visible=reader.visible,
    )
    return _Output(card, _slot_text(card))


def _version(args: argparse.Namespace, reader: _Reader) -> _Output:
    card = version_card(
        reader.queries,
        reader.settings,
        reader.preferences,
        args.store,
        args.version,
        visible=reader.visible,
    )
    return _Output(card, _version_text(card))


def _projects(args: argparse.Namespace, reader: _Reader) -> _Output:
    projects = read_projects(
        reader.queries,
        reader.settings,
        args.store,
        visible=reader.visible,
        writable=reader.writable,
    )
    lines: list[str] = [
        message(
            "cli.project_line",
            project=item.project,
            name=item.name,
            stores=_stores_text(item.stores),
            groups=item.groups,
            pins=item.pins,
            missing=item.missing_pins,
        )
        for item in projects.items
    ]
    return _Output(
        projects, _with_stale(projects, lines or [message("cli.no_projects")])
    )


def _project(args: argparse.Namespace, reader: _Reader) -> _Output:
    card = project_card(
        reader.queries,
        reader.settings,
        reader.preferences,
        args.project,
        visible=reader.visible,
        writable=reader.writable,
    )
    return _Output(card, project_text(card))


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
    lines: list[str] = [
        message(
            "cli.status_line",
            version=health.archiwista,
            schema=health.index.schema_version,
            size=_size(health.index.size_bytes),
        )
    ]
    lines.extend(
        message(
            "cli.source_line",
            producer=item.producer,
            version=item.package_version or message("cli.none"),
            message=item.message,
        )
        for item in health.sources
    )
    for item in health.stores:
        state = item.state
        line: str = message(
            "cli.store_line",
            store=item.store,
            name=item.name,
            status=message(f"cli.store_status_{state.status}"),
            slots=state.slots,
            versions=state.versions,
            missing=state.missing_versions,
            issues=state.issues,
            indexed_at=_time(state.indexed_at),
            full_scan_at=(
                message("cli.none")
                if state.full_scan_at is None
                else _time(state.full_scan_at)
            ),
        )
        if state.running_job is not None:
            line += message(
                "cli.store_job",
                kind=label("job.kind", state.running_job.kind),
                state=label("job.state", state.running_job.state),
            )
        lines.append(line)
    if not health.stores:
        lines.append(message("reindex.no_stores"))
    return "\n".join(lines)


def _page_text(page: CatalogPage) -> str:
    lines: list[str] = [
        message(
            "cli.search_row",
            store=item.store,
            slot=item.slot,
            label=_value(item.version.label if item.version else None),
            year=_value(item.version.data_year if item.version else None),
        )
        for item in page.items
    ] or [message("cli.no_rows")]
    lines.append(
        message(
            "cli.search_summary",
            count=len(page.items),
            footprint=page.groups.footprint,
            country=page.groups.country,
            none=page.groups.none,
        )
    )
    if page.next_cursor is not None:
        lines.append(message("cli.search_next", cursor=page.next_cursor))
    return _with_stale(page, lines)


def _slot_text(card: SlotCard) -> str:
    lines: list[str] = [
        message("cli.entry_title", store=card.store, slot=card.slot, name=card.name),
        message(
            "cli.entry_facts",
            segment=card.segment.label,
            unit=_value(card.unit),
            product=_value(card.product),
            country=_value(card.country),
            status=card.status,
        ),
    ]
    lines.extend(_version_line(version) for version in card.versions)
    if card.paths is not None:
        lines.append(message("cli.path_line", path=card.paths.local))
    lines.extend(_problem_lines(card.problems))
    return _with_stale(card, lines)


def _version_line(version: Version) -> str:
    marks = ""
    if version.is_current:
        marks += message("cli.version_current")
    if version.is_full_sheet:
        marks += message("cli.version_full_sheet")
    if version.state == "missing":
        marks += message("cli.version_missing")
    if version.pinned_by:
        names = ", ".join(pin.name for pin in version.pinned_by)
        marks += message("cli.version_pinned", projects=names)
    return message(
        "cli.version_line",
        path=version.path,
        label=_value(version.label),
        year=_value(version.data_year),
        marks=marks,
    )


def _version_text(card: VersionCard) -> str:
    version = card.version
    lines: list[str] = [
        message(
            "cli.version_title", store=card.store, path=version.path, slot=card.slot
        ),
        _version_line(version),
        message(
            "cli.version_facts",
            label=_value(version.label),
            year=_value(version.data_year),
            size=_size(version.size_bytes),
            crs=_value(version.crs.horizontal),
            sha256=_value(version.sha256),
        ),
        message(
            "cli.version_license",
            license=_value(card.license),
            attribution=_value(card.attribution),
        ),
    ]
    if card.paths is not None:
        lines.append(message("cli.path_line", path=card.paths.local))
    return _with_stale(card, lines)


def project_text(card: ProjectCard) -> str:
    """Return a project's card for a person: the project, its groups, pins, problems."""
    lines: list[str] = [
        message(
            "cli.project_line",
            project=card.project,
            name=card.name,
            stores=_stores_text(card.stores),
            groups=len(card.groups),
            pins=card.pins,
            missing=card.missing_pins,
        ),
        message("cli.project_path_line", path=card.path.local),
    ]
    if card.area is not None:
        lines.append(
            message(
                "cli.project_area_line",
                path=card.area.path,
                state=_value(card.area.state),
            )
        )
    for group in card.groups:
        lines.append(
            message(
                "cli.project_group_line",
                group=group.name,
                origin=group.origin.kind,
                pins=len(group.pins),
            )
        )
        lines.extend(
            message(
                "cli.pin_line",
                version=pin.version,
                producer=pin.producer,
                state=pin.state,
            )
            for pin in group.pins
        )
    lines.extend(_problem_lines(card.problems))
    return _with_stale(card, lines)


def pin_text(outcome: PinOutcome) -> str:
    """Return what a pin request did for a person: the counts and each skipped."""
    lines = [
        message(
            "cli.project_pinned",
            group=outcome.group,
            project=outcome.project.project,
            pinned=outcome.pinned,
            already=outcome.already,
            skipped=len(outcome.skipped),
        )
    ]
    lines.extend(
        message(
            "cli.project_skipped_line",
            store=item.store,
            version=item.version,
            reason=item.reason,
        )
        for item in outcome.skipped
    )
    return "\n".join(lines)


def _stores_text(stores: Iterable[ProjectStore]) -> str:
    """Return a project's stores for a person: each producer with its store."""
    return ", ".join(
        message(
            "cli.project_store_item",
            producer=item.producer,
            store=_value(item.store),
        )
        for item in stores
    ) or _value(None)


def _problem_lines(problems: Iterable[Issue]) -> list[str]:
    return [
        message(
            "cli.problem_line", message=problem.message, instruction=problem.instruction
        )
        for problem in problems
    ]


def _with_stale(answer: IndexAnswer, lines: list[str]) -> str:
    notes = [
        message("cli.stale_line", store=item.store, indexed_at=_time(item.indexed_at))
        for item in answer.stale_stores
    ]
    return "\n".join([*lines, *notes])


def _value(value: object) -> str:
    return message("cli.none") if value is None else str(value)


def _time(value: datetime | None) -> str:
    if value is None:
        return message("cli.never")
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def _size(size: int | None) -> str:
    if size is None:
        return message("cli.none")
    if size < 1_000_000:
        return f"{size / 1000:.1f} kB".replace(".", ",")
    return f"{size / 1_000_000:.1f} MB".replace(".", ",")


# Parsers.


def _parser(commands: _Commands, name: str, help_key: str) -> argparse.ArgumentParser:
    text = message(help_key)
    parser = commands.add_parser(name, help=text, description=text)
    parser.add_argument("--json", action="store_true", help=message("cli.json_help"))
    return parser
