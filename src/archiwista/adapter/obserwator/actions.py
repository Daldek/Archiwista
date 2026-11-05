"""Obserwator's commands as producer-neutral commands (``ActionAdapter``, SPEC 12.2).

Only names of ``obserwator.__all__`` are used (A-ADR-050, D1). The catalog is
the commands of Obserwator's catalog (``data_commands``) that write its store:
``store sync`` (IMGW-PIB's and ČHMÚ's archives, then the series of their
datasets), ``store catalog`` (a provider's station catalog) and ``series
build`` (``STORE_COMMANDS``), described by ``command_schema`` in the language
of the call (Polish or English). Their options are those of the schema without
what Archiwista names beside them: the store root (``root``, taken from the
configured store, never from a request), the plain mode of a run
(``output_dir``, ``force``: a run writes no plain file) and the plan
(``plan``: Archiwista hands a kept plan to the run itself).

``parse_command``, ``validate_command`` and ``format_command`` read, check and
write a call; Obserwator's call names the root among its options, Archiwista's
beside them (``CommandCall.run``), so the adapter moves it. ``check_command``
plans a run of a call in the configured store: its ``obserwator-plan/1`` is
read as the producer-neutral ``ActionPlan`` and kept whole as its
``document``. ``run_command`` runs it, with the kept plan as the plan file of
``store sync`` (written beside the adapter's cache, outside the store, and
removed after the run); an interrupt (``KeyboardInterrupt``) goes through,
and Obserwator publishes each version whole (its ``publish``), so nothing of a
version is left. A unit that fails is an item of the result.

Positions and files are named by their slot's directory below the store root
(``archives/versions/<server path without its suffix>``,
``series/versions/<dataset slug>``, ``stations/versions[/<catalog>]``): the
path the index keeps a slot of the store under (the adapter's ``slot_path``),
so a plan's position and a run's file of one slot share it; a run's file also
names its version (``version_path``). Obserwator scans only its whole store, so
the scope of every path is the whole store (``scope``).

IMGW-PIB's archives are national files (a year or a month of the country per
file): no area narrows a download (``with_area`` refuses with
``no_area_option``), and Obserwator has no availability report of an area
(``availability_products`` is empty).
"""

import json
import os
import tempfile
from collections.abc import Callable, Collection, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import replace
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast

from obserwator import (
    CatalogReport,
    CommandResult,
    ObserwatorError,
    PlanAction,
    PlanItem,
    SeriesReport,
    StorePlan,
    SyncReport,
    check_command,
    command_schema,
    data_commands,
    format_command,
    get_dataset,
    parse_command,
    run_command,
    validate_command,
)

from archiwista.adapter.obserwator import PACKAGE, PRODUCER
from archiwista.errors import BrokenContractError, ProducerError, UnsupportedError
from archiwista.messages import current_language, message
from archiwista.sources import (
    FILE_STATUSES,
    PLAN_TODO,
    ActionFile,
    ActionItem,
    ActionPlan,
    ActionProgress,
    ActionResult,
    AreaCommand,
    AvailabilityNotice,
    AvailabilityReport,
    CommandCall,
    CommandChoice,
    CommandInfo,
    CommandOption,
    CommandWrites,
    OptionType,
    PathRole,
    PlanEntry,
    PlanStatus,
    RunStatus,
    ScanScope,
)

# The commands of Obserwator's catalog that write its store, in its order: the
# archives with the series of their datasets, a provider's station catalog,
# and the series of one dataset (plan 2026-11-05, A1).
STORE_COMMANDS = ("store sync", "store catalog", "series build")
# The options of a call Archiwista names beside them: the store root, the plain
# mode of a run (a directory of plain files, ``--force``) and the plan file.
_ROOT = "root"
_PLAN = "plan"
BESIDE_OPTIONS = frozenset({_ROOT, "output_dir", "force", _PLAN})
# The flags of a run of Obserwator's command line (``format_command``'s ``run``).
_RUN_FLAGS = frozenset({"check", "json", "lang"})
# The options a plan stands for in ``store sync`` (its rule: "plan excludes
# datasets, years, months and stations").
_SELECTION = frozenset({"datasets", "years", "months", "stations"})
_ROOT_ROLE = "root"
_PATH_ROLES: frozenset[str] = frozenset({"input", "output"})
_LANGUAGES = frozenset({"en", "pl"})
# Where Obserwator's store keeps the versions of each kind of slot (its layout,
# ``archives/versions/…``, ``series/versions/<slug>/…``,
# ``stations/versions/…``); contract tests compare them with the versions a
# run writes.
_ARCHIVES = PurePosixPath("archives/versions")
_SERIES = PurePosixPath("series/versions")
_CATALOGS = {
    "IMGW-PIB": PurePosixPath("stations/versions"),
    "CHMI": PurePosixPath("stations/versions/chmi_stations"),
}
_DEFAULT_PROVIDER = "IMGW-PIB"
# The place of a position about the store root itself (a root a run refuses).
_STORE = "."
# The statuses of an item of a run that is no success.
_FAILED_ITEMS = frozenset({"failed", "stale_plan", "cancelled"})
# Obserwator's plan of a series: ``outdated`` is a series to build again.
_SERIES_STATUSES: Mapping[str, PlanStatus] = {
    "current": "current",
    "outdated": "newer",
    "missing": "missing",
}
# The schema of Obserwator's plan (``StorePlan.schema``).
PLAN_SCHEMA = "obserwator-plan/1"
# The name of a plan file handed to ``store sync`` (beside the adapter's cache).
_PLAN_PREFIX = "obserwator-plan-"


def catalog() -> tuple[CommandInfo, ...]:
    """Return the commands of Obserwator's catalog that write its store.

    In the order of ``data_commands``, their summary, description and the
    descriptions of their options in the call's language (Polish or English,
    ``command_schema(lang=…)``).

    Raises
    ------
    ProducerError
        Obserwator failed to describe its catalog.
    """
    names = {command.name for command in data_commands()}
    try:
        schema = command_schema(lang=_lang())
    except ObserwatorError as error:
        raise call_error(error) from error
    entries = _mappings(schema.get("commands"))
    return tuple(
        _command_info(entry)
        for entry in entries
        if entry.get("name") in STORE_COMMANDS and entry.get("name") in names
    )


def parse(line: str) -> CommandCall:
    """Read a command line with Obserwator's parser (``parse_command``).

    Its store root (``--root``) goes beside the options (``run["root"]``), as
    Archiwista reads every producer's call; the flags of a run stay there.

    Raises
    ------
    ProducerError
        A mistake of the line: an unknown command or flag, a value outside the
        choices of a flag, a flag without its value (``validation_error``).
    """
    try:
        call = parse_command(line)
    except ObserwatorError as error:
        raise call_error(error) from error
    options = dict(call.options)
    run = dict(call.run)
    if _ROOT in options:
        run[_ROOT] = str(options.pop(_ROOT))
    return CommandCall(PRODUCER, call.command, options, run)


def validate(
    command: str, options: Mapping[str, object], *, root: Path | None
) -> Mapping[str, object]:
    """Check a call with ``validate_command``, naming the store of a store command.

    Returns the options unchanged: Obserwator reads them as they are, and a job
    keeps their JSON form.

    Raises
    ------
    ProducerError
        Obserwator refused the call: an unknown command or option, a value of a
        wrong form or outside the allowed values, a broken rule among the
        options (``validation_error``, ``details.option``).
    ValueError
        A command that works on a store without its root: Obserwator's default
        root would stand in, so the call never reaches Obserwator.
    """
    entry = _entry(command)
    if _works_on_store(entry) and root is None:
        raise ValueError(f"{command} works on a store: give its root")
    given = dict(options)
    if root is not None and _works_on_store(entry):
        given[_ROOT] = str(root)
    try:
        validate_command(command, options=given)
    except ObserwatorError as error:
        raise call_error(error) from error
    return dict(options)


def format_line(call: CommandCall) -> str:
    """Return the canonical ``obserwator …`` line of a call (``format_command``).

    A store root beside the options (``run["root"]``) becomes ``--root``; the
    other names beside them are Obserwator's flags of a run (``check``,
    ``json``, ``lang``), and any other is left out.

    Raises
    ------
    ProducerError
        An unknown command, an option the command does not have or a value of
        a wrong form (``validation_error``).
    """
    options = dict(call.options)
    if _ROOT in call.run:
        options[_ROOT] = str(call.run[_ROOT])
    flags = {name: value for name, value in call.run.items() if name in _RUN_FLAGS}
    try:
        return format_command(call.command, options=options, run=flags)
    except ObserwatorError as error:
        raise call_error(error) from error


def availability(product: str) -> AvailabilityReport:
    """Refuse a report of an area: Obserwator checks the availability of none.

    Raises
    ------
    UnsupportedError
        Always (reason ``no_availability``, ``details.allowed`` empty).
    """
    raise UnsupportedError(
        message(
            "availability.product_unsupported",
            producer=PRODUCER,
            product=product,
            allowed="",
        ),
        reason="no_availability",
        details={"allowed": []},
    )


def check(
    command: str,
    options: Mapping[str, object],
    *,
    root: Path,
    on_notice: Callable[[AvailabilityNotice], None] | None,
) -> ActionPlan:
    """Plan a run of a command in the store at ``root`` (``check_command``).

    The positions of ``obserwator-plan/1``: each archive of ``items``, the
    series of ``series_state`` (``outdated`` is ``newer``) and each other
    action of ``actions`` (a series or a catalog to build; a root a run would
    refuse, ``nested_store`` or ``not_empty``, is ``conflict``). The size of an
    archive is the one the source tells (``content_length``).

    Raises
    ------
    ProducerError
        Obserwator refused the call (an unknown command, an invalid option, a
        root it cannot read) or the whole check failed.
    UnsupportedError
        The command is no command of the catalog that plans a store
        (``no_plan``).
    """
    if command not in STORE_COMMANDS:
        raise UnsupportedError(
            message("command.no_plan", producer=PRODUCER, command=command),
            reason="no_plan",
        )
    given = {**options, _ROOT: str(root)}
    try:
        result = check_command(
            command,
            options=given,
            on_notice=None if on_notice is None else _forward(on_notice),
        )
    except ObserwatorError as error:
        raise call_error(error) from error
    plan = result.result
    if not isinstance(plan, StorePlan):
        raise UnsupportedError(
            message("command.no_plan", producer=PRODUCER, command=command),
            reason="no_plan",
        )
    return ActionPlan(
        producer=PRODUCER,
        command=result.command,
        schema=plan.schema,
        root=str(plan.root),
        checked_at=plan.checked_at,
        entries=_plan_entries(plan, root, options),
        notices=tuple(_notice(notice) for notice in result.notices),
        document=_document(plan),
    )


def run(
    command: str,
    options: Mapping[str, object],
    *,
    root: Path,
    cache_dir: Path,
    plan: ActionPlan | None,
    on_progress: Callable[[ActionProgress], None] | None,
    on_notice: Callable[[AvailabilityNotice], None] | None,
) -> ActionResult:
    """Run a command in the store at ``root`` (``run_command``).

    With ``plan``, ``store sync`` runs that plan: its document goes back to
    Obserwator as a plan file in ``cache_dir`` (outside the store, removed
    after the run) in place of the options it stands for (datasets, years,
    months, stations), and a position whose source changed since fails as
    ``conflict`` (reason ``stale_plan``). The other commands have no plan: a
    plan of them is the same call. Without a plan Obserwator downloads what is
    new or missing at the source, newer versions included (it has no mode that
    keeps the stored ones). ``files[]`` come back below the root.

    Raises
    ------
    ProducerError
        Obserwator refused the call or the plan, or failed as a whole.
    BrokenContractError
        Obserwator reported a file outside the root, or a plain one
        (``written``, ``replaced``).
    """
    given: dict[str, object] = {**options, _ROOT: str(root)}
    progress = None if on_progress is None else _progress(on_progress)
    notices = None if on_notice is None else _forward(on_notice)
    with _plan_file(command, plan, cache_dir) as path:
        if path is not None:
            given = {k: v for k, v in given.items() if k not in _SELECTION}
            given[_PLAN] = str(path)
        try:
            result = run_command(
                command, options=given, on_progress=progress, on_notice=notices
            )
        except ObserwatorError as error:
            raise call_error(error) from error
    return _run_result(result, root)


def narrow(plan: ActionPlan, paths: Collection[str]) -> ActionPlan:
    """Return a plan of ``check`` keeping only the positions to download at ``paths``.

    The archives to download (``newer``, ``missing``) elsewhere go from the
    entries and from Obserwator's plan (``items`` of the document), which
    ``store sync`` then never fetches; the series and catalogs of the plan stay
    in its document (a run builds them from what the store holds, and builds
    an unchanged one as ``unchanged``). The positions a run does not download
    stay as they are.

    Raises
    ------
    ValueError
        The document is no ``obserwator-plan/1`` Obserwator reads back.
    """
    kept = frozenset(paths)
    document = dict(plan.document)
    if document.get("schema") != PLAN_SCHEMA:
        raise ValueError(f"no plan of Obserwator: {document.get('schema')!r}")
    _readable(document)
    items = [
        item
        for item in _mappings(document.get("items"))
        if _item_status(item) not in PLAN_TODO
        or _archive_slot(str(item.get("server_path", ""))) in kept
    ]
    return replace(
        plan,
        entries=tuple(
            entry
            for entry in plan.entries
            if entry.status not in PLAN_TODO or entry.path in kept
        ),
        document={**document, "items": items},
    )


def scope(path: str) -> ScanScope:
    """Return the scope that reads the slot at ``path`` again: the whole store.

    Obserwator scans only its whole store (``iter_store``), skipping the
    versions the index knows, so the scope names no segment and no unit.

    Raises
    ------
    ValueError
        ``path`` is not relative, or lies in no tree of the store's versions.
    """
    place = PurePosixPath(path)
    parts = place.parts
    trees = {_ARCHIVES.parts[0], _SERIES.parts[0], "stations", "pmaxtp"}
    if (
        place.is_absolute()
        or len(parts) < 2
        or {".", ".."} & set(parts)
        or parts[0] not in trees
    ):
        raise ValueError(f"{path!r} is no place of a slot in an Obserwator store")
    return ScanScope()


def with_area(call: CommandCall) -> AreaCommand:
    """Refuse an area: IMGW-PIB's archives are national files.

    Raises
    ------
    ProducerError
        Obserwator does not know the command.
    UnsupportedError
        Always otherwise (reason ``no_area_option``): no command of Obserwator's
        catalog that writes the store takes an area.
    """
    _entry(call.command)
    raise UnsupportedError(
        message("command.no_area_option", command=call.command),
        reason="no_area_option",
    )


def call_error(error: ObserwatorError) -> ProducerError:
    """Return Obserwator's description of an error as the error of Archiwista.

    Its registry code, its text and hint in the call's language when they are
    texts of Obserwator's catalog, and its details: what it names
    (``option``, ``value``, ``allowed``) and its own ``reason``.
    """
    hint = getattr(error, "hint", None)
    return ProducerError(
        PACKAGE,
        type(error).__name__,
        _text(error.args[0] if error.args else str(error)),
        code=error.code,
        hint=None if hint is None else _text(hint),
        details=_jsonable(dict(getattr(error, "details", {}) or {})),
    )


def _entry(command: str) -> Mapping[str, Any]:
    """Return the schema of one command of Obserwator's catalog."""
    try:
        schema = command_schema(command, lang=_lang())
    except ObserwatorError as error:
        raise call_error(error) from error
    return _mappings(schema.get("commands"))[0]


def _command_info(entry: Mapping[str, Any]) -> CommandInfo:
    """Convert one command of ``obserwator-commands/1``."""
    effects = _mapping(entry.get("effects"))
    name = str(entry["name"])
    return CommandInfo(
        producer=PRODUCER,
        command=name,
        group=str(entry.get("group") or name.partition(" ")[0]),
        summary=str(entry.get("summary") or ""),
        description=str(entry.get("description") or ""),
        options=tuple(
            _option(option)
            for option in _mappings(entry.get("options"))
            if option.get("name") not in BESIDE_OPTIONS
        ),
        read_only=bool(effects.get("read_only", False)),
        writes=cast(CommandWrites, effects.get("writes", "none")),
        network=bool(effects.get("network", False)),
        check=entry.get("check") is not None,
        store=_works_on_store(entry),
        examples=tuple(
            str(example["call"])
            for example in _mappings(entry.get("examples"))
            if "call" in example
        ),
    )


def _option(option: Mapping[str, Any]) -> CommandOption:
    """Convert one option of a command's schema."""
    role = option.get("path_role")
    return CommandOption(
        name=str(option["name"]),
        type=cast(OptionType, option["type"]),
        required=bool(option.get("required", False)),
        description=str(option.get("description") or ""),
        choices=tuple(
            CommandChoice(choice["value"], str(choice.get("meaning") or ""))
            for choice in _mappings(option.get("enum"))
        ),
        default=option.get("default"),
        minimum=option.get("min"),
        maximum=option.get("max"),
        items=_items(option.get("items")),
        group=option.get("one_of"),
        path_role=cast(PathRole, role) if role in _PATH_ROLES else None,
    )


def _items(items: object) -> OptionType | None:
    """Return the type of the items of an array: one type, or a choice of texts.

    ``None`` for items of several types (``years``: a number or a range).
    """
    if not isinstance(items, Mapping):
        return None
    if "type" in items:
        return cast(OptionType, items["type"])
    if "enum" in items:
        return "string"
    return None


def _works_on_store(entry: Mapping[str, Any]) -> bool:
    """Whether a command takes the store root (an option with that path role)."""
    return any(
        option.get("path_role") == _ROOT_ROLE
        for option in _mappings(entry.get("options"))
    )


def _plan_entries(
    plan: StorePlan, root: Path, options: Mapping[str, object]
) -> tuple[PlanEntry, ...]:
    """Return the positions of a plan: archives, series, then the other actions."""
    entries = [_archive_entry(item, root) for item in plan.items]
    entries += [
        PlanEntry(
            path=str(_SERIES / slug),
            unit=slug,
            status=_SERIES_STATUSES.get(state, "unverifiable"),
        )
        for slug, state in plan.series_state.items()
    ]
    entries += [_action_entry(action, options) for action in plan.actions]
    return tuple(entries)


def _archive_entry(item: PlanItem, root: Path) -> PlanEntry:
    """Convert an archive of ``items``, named by its slot's directory."""
    archive = item.archive
    local = None if item.local_path is None else _relative(item.local_path, root)
    return PlanEntry(
        path=_archive_slot(archive.server_path),
        unit=archive.server_path,
        status=item.status,
        local_label=None if local is None else _label(local),
        available_label=_date_label(item.remote_last_modified),
        size_bytes=item.content_length,
        error=item.error if item.status == "check_failed" else None,
    )


def _action_entry(action: PlanAction, options: Mapping[str, object]) -> PlanEntry:
    """Convert an action of ``actions``: a series, a catalog or a refused root."""
    conflict = action.reason if action.action == "conflict" else None
    if conflict is not None:
        path = _STORE
    elif action.command == "series build":
        path = str(_SERIES / _slug(options.get("dataset")))
    elif action.command == "store catalog":
        provider = str(options.get("provider") or _DEFAULT_PROVIDER)
        path = str(_CATALOGS.get(provider, _CATALOGS[_DEFAULT_PROVIDER]))
    else:
        path = _STORE
    return PlanEntry(
        path=path,
        unit=action.command,
        status=action.status,
        error=_text(action.detail)
        if action.status == "check_failed" or conflict
        else None,
        conflict=conflict,
    )


def _archive_slot(server_path: str) -> str:
    """Return the slot directory of an archive (its server path without suffix)."""
    place = PurePosixPath(server_path)
    return str(_ARCHIVES / place.parent / place.stem)


def _slug(dataset: object) -> str:
    """Return the series directory of a dataset (its slug in the registry)."""
    try:
        return get_dataset(str(dataset)).slug
    except ObserwatorError as error:
        raise call_error(error) from error


def _label(version: PurePosixPath) -> str:
    """Return the label of a version, its directory ``<label>_<sha8>``."""
    return version.parent.name.rpartition("_")[0] or version.parent.name


def _date_label(value: str | None) -> str | None:
    """Return the date of an HTTP ``Last-Modified``, the form of a label."""
    if not value:
        return None
    with suppress(TypeError, ValueError):
        return parsedate_to_datetime(value).date().isoformat()
    return None


def _relative(path: Path | str, root: Path) -> PurePosixPath | None:
    """Return a path Obserwator reported as its place below the root, or ``None``."""
    place = Path(os.path.normpath(path))
    if not place.is_absolute():
        return PurePosixPath(place.as_posix())
    for base in (root, root.resolve(), root.expanduser().absolute()):
        with suppress(ValueError):
            relative = place.relative_to(base)
            if relative.parts:
                return PurePosixPath(relative.as_posix())
    return None


def _document(plan: StorePlan) -> dict[str, object]:
    """Return ``obserwator-plan/1`` as JSON, as Obserwator writes it (``to_json``)."""
    with tempfile.TemporaryDirectory(prefix=_PLAN_PREFIX) as directory:
        written = plan.to_json(Path(directory) / "plan.json")
        document = json.loads(Path(written).read_text(encoding="utf-8"))
    return cast(dict[str, object], document)


def _readable(document: Mapping[str, object]) -> StorePlan:
    """Read a document back as Obserwator's plan (``StorePlan.from_json``).

    Raises
    ------
    ValueError
        Obserwator does not read it.
    """
    with tempfile.TemporaryDirectory(prefix=_PLAN_PREFIX) as directory:
        path = Path(directory) / "plan.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        try:
            return StorePlan.from_json(path)
        except (ObserwatorError, KeyError, TypeError, ValueError) as error:
            raise ValueError(f"no plan of Obserwator: {error}") from error


@contextmanager
def _plan_file(
    command: str, plan: ActionPlan | None, cache_dir: Path
) -> Iterator[Path | None]:
    """Write a kept plan of ``store sync`` as Obserwator's plan file, for a run.

    In ``cache_dir`` (the adapter's, outside every store), removed after the
    run; ``None`` for no plan or a command without one.
    """
    if plan is None or command != "store sync":
        yield None
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=_PLAN_PREFIX, suffix=".json", dir=cache_dir
    )
    path = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(dict(plan.document), file)
        yield path
    finally:
        path.unlink(missing_ok=True)


def _run_result(result: CommandResult[object], root: Path) -> ActionResult:
    """Convert the envelope of a run and its report (sync, catalog or series)."""
    report = result.result
    files: tuple[Any, ...] = ()
    items: list[ActionItem] = []
    schema = None
    if isinstance(report, SyncReport):
        files = report.files
        items = [_sync_item(item) for item in report.items]
        items += [_built_item(series, "series build", root) for series in report.series]
        schema = report.SCHEMA
    elif isinstance(report, SeriesReport | CatalogReport):
        files = report.files
        command = (
            "series build" if isinstance(report, SeriesReport) else "store catalog"
        )
        items = [_built_item(report, command, root)]
    status = result.status
    run_status: RunStatus = "failed" if status == "cancelled" else status
    return ActionResult(
        producer=PRODUCER,
        command=result.command,
        root=str(root),
        status=run_status,
        files=tuple(_file(file, root) for file in files),
        items=tuple(items),
        notices=tuple(_notice(notice) for notice in result.notices),
        schema=schema,
    )


def _sync_item(item: Any) -> ActionItem:
    """Convert one archive of a sync (``OperationResult``)."""
    failed = item.status in _FAILED_ITEMS
    stale = item.status == "stale_plan"
    return ActionItem(
        id=str(item.slot or "archive"),
        status="failed" if failed else "ok",
        code="conflict" if stale else item.error_code if failed else None,
        reason="stale_plan" if stale else None,
        message=_text(item.error) if failed and item.error else None,
    )


def _built_item(report: Any, command: str, root: Path) -> ActionItem:
    """Convert a series or catalog built (``SeriesReport``, ``CatalogReport``).

    Its id is the slot's directory of the version built, else the command.
    """
    failed = report.status in ("failed", "cancelled")
    version = None if report.version is None else _relative(report.version, root)
    problems = tuple(str(problem) for problem in report.problems)
    slot = None if version is None or len(version.parts) < 3 else version.parent.parent
    return ActionItem(
        id=command if slot is None else slot.as_posix(),
        status="failed" if failed else "ok",
        code="data_error" if failed else None,
        message="; ".join(problems) if failed and problems else None,
    )


def _file(entry: Any, root: Path) -> ActionFile:
    """Convert one entry of ``files[]``; a plain file breaks the contract."""
    status = str(entry.status)
    relative = _relative(entry.path, root)
    if status not in FILE_STATUSES or relative is None or len(relative.parts) < 3:
        raise BrokenContractError(
            message(
                "command.file_outside_store",
                producer=PRODUCER,
                path=entry.path,
                status=status,
                root=root,
            )
        )
    slot = relative.parent.parent
    return ActionFile(
        path=slot.as_posix(),
        unit=slot.as_posix(),
        status=status,
        size_bytes=int(entry.size_bytes),
        sha256=str(entry.sha256),
        label=_label(relative),
        version_path=relative.as_posix(),
    )


def _forward(
    on_notice: Callable[[AvailabilityNotice], None],
) -> Callable[[Any], None]:
    """Pass each of Obserwator's notices on as a producer-neutral one."""

    def forward(notice: Any) -> None:
        on_notice(_notice(notice))

    return forward


def _progress(on_progress: Callable[[ActionProgress], None]) -> Callable[[Any], None]:
    """Pass each ``Progress`` on: its counts, status and text.

    Obserwator counts the units of each step of a run (archives, then the
    stations of a series) and names their kind, not one unit (``unit`` is
    ``archive``, ``station``), so no event names a unit.
    """

    def forward(event: Any) -> None:
        on_progress(
            ActionProgress(
                int(event.current),
                int(event.total),
                None,
                str(event.status),
                _text(event.message),
            )
        )

    return forward


def _notice(notice: Any) -> AvailabilityNotice:
    """Convert a ``Notice``; a text of Obserwator's catalog in the call's language."""
    return AvailabilityNotice(notice.level, notice.code, _text(notice.message))


def _text(value: object) -> str:
    """Return a text of Obserwator's catalog in the call's language, else as it is."""
    localized = getattr(value, "localized", None)
    language = current_language()
    if callable(localized) and language in _LANGUAGES:
        return str(localized(language))
    return str(value)


def _lang() -> Any:
    """Return the call's language for Obserwator's ``lang`` (``en`` or ``pl``)."""
    language = current_language()
    return language if language in _LANGUAGES else "en"


def _item_status(item: Mapping[str, Any]) -> str:
    return str(item.get("status", ""))


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mappings(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _jsonable(details: Mapping[str, object]) -> dict[str, object]:
    """Return the details of an error with texts for what JSON has no form of."""
    return cast(dict[str, object], json.loads(json.dumps(details, default=str)))
