"""Kartograf's commands as producer-neutral commands (``ActionAdapter``, SPEC 12.2).

``list_commands`` names every command of Kartograf's catalog in its order and
``command_schema`` describes each. The options of a call are the options of
the schema without what Kartograf takes by name beside them: the store root,
``output_dir`` and the flags of a run are keyword arguments of
``run_command`` and ``check_command``, and ``check`` chooses
``check_command``. ``parse_command``, ``validate_command`` and
``format_command`` read, check and write a call. A refusal keeps
Kartograf's own description of it (``error_report``): its registry code, its
text and hint in the language of the call, and the option it names. None of
this uses the network.

``check_availability`` asks GUGiK and CUZK what they have for an area (plan of
2026-10-25, A2; ADR-035). The area goes to Kartograf as the envelope of its
polygon in the CRS Kartograf measures the area's first country in, with the
country (``auto`` for both), and the metadata cache is Archiwista's own,
``metadata.db`` in the adapter's cache directory: never ``cache=True``, which
would be Kartograf's default cache (D5). ``check_command`` plans a run in the
configured store the same way (A4, ADR-036): with ``root=`` and Archiwista's
cache, whose answers of the source younger than ``PLAN_REFRESH_TTL_S`` stand for
asking it again (Kartograf ADR-056: the plan of a report's row right after the
report asks GUGiK nothing), its ``kartograf-plan/1`` read as the
producer-neutral ``ActionPlan``.
``run_command`` runs it (A5, ADR-037): ``root=``, Archiwista's cache, the
kept plan back as ``update="upgrade", plan=…`` (or ``update="upgrade"``
without one, a re-pin of A-ADR-049), and ``kartograf-download/1`` read as the
producer-neutral ``ActionResult``; ``narrow`` leaves out of a kept plan the
positions another job fetches (ADR-047), which Kartograf then never executes.
``command_for_version`` gives the call that selects a stored version again
(A-ADR-049 D-10): ``read_sidecar`` of the version into ``command_for_file``,
offline; Kartograf's refusal ``command_not_rebuildable`` is ``UnsupportedError``
with its text.
"""

import inspect
import os
from collections.abc import Callable, Collection, Mapping
from contextlib import suppress
from dataclasses import replace
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast

import shapely
from kartograf import (
    BBox,
    CommandNotRebuildableError,
    KartografError,
    MetadataCache,
    PlanItem,
    UpdatePlan,
    check_availability,
    check_command,
    command_for_file,
    command_schema,
    error_report,
    format_command,
    list_commands,
    parse_command,
    pinned_transform,
    read_sidecar,
    run_command,
    validate_command,
)
from shapely.geometry import shape

from archiwista.adapter.kartograf import PACKAGE, PRODUCER
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
    AvailabilityArea,
    AvailabilityCampaign,
    AvailabilityCombination,
    AvailabilityFailure,
    AvailabilityNotice,
    AvailabilityReport,
    AvailabilitySheet,
    CommandCall,
    CommandChoice,
    CommandInfo,
    CommandOption,
    CommandWrites,
    GeoJSONGeometry,
    ItemStatus,
    OptionType,
    PathRole,
    PlanEntry,
    RunStatus,
    ScanScope,
)

# The names a call gives beside its options: the keyword arguments of
# ``run_command`` and ``check_command`` (the targets and the flags of a run),
# and ``check``, which chooses ``check_command``.
BESIDE_OPTIONS = frozenset(
    {
        name
        for function in (run_command, check_command)
        for name, parameter in inspect.signature(function).parameters.items()
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY
    }
    | {"check"}
)
# The ``path_role`` of the store root in Kartograf's schema (DEV-19.1).
_ROOT_ROLE = "root"
_PATH_ROLES: frozenset[str] = frozenset({"input", "output"})
# The file of Kartograf's metadata cache (its own name, ``metadata.db``).
METADATA_CACHE_FILE = "metadata.db"
# How old an answer of the source may be to stand, in a plan, for asking it
# again (``MetadataCache.refresh_ttl_seconds``, Kartograf ADR-056): the
# availability report's answers serve "Pobierz…" of its rows for an hour; an
# older report's row asks the source again, and a run always does.
PLAN_REFRESH_TTL_S = 3600
# The command of ``check_availability`` in Kartograf's catalog.
AVAILABILITY_COMMAND = "elevation availability"
# The CRS Kartograf measures each country's part of an area in: EPSG:2180 for
# PL, the CRS of the CZ part of its report for CZ; in the order of its report.
_AREA_CRS = {"PL": "EPSG:2180", "CZ": "EPSG:5514"}
_WGS84 = "EPSG:4326"
# Longest edge of an area before it moves to the planar CRS (about 0.5 km):
# the edges of a WGS84 polygon bend there.
_SEGMENT_DEGREES = 0.005
_LANGUAGES = frozenset({"en", "pl"})
# Kartograf's progress events (``DownloadProgress.status``) whose ``current``
# of ``total`` count the units of a run, and those whose ``sheet`` names a
# unit. ``start`` counts one transfer and may name a text, ``campaigns`` and
# ``campaign`` count the flights of one sheet.
_UNIT_COUNTS = frozenset(
    {"downloading", "skipped", "completed", "failed", "no_coverage", "tiles"}
)
_UNIT_NAMES = frozenset(
    {
        "downloading",
        "skipped",
        "completed",
        "failed",
        "no_coverage",
        "campaigns",
        "campaign",
    }
)


def catalog() -> tuple[CommandInfo, ...]:
    """Return every command of Kartograf's catalog, in its order.

    The summary and the description are Polish when the call's language is
    Polish (``i18n.pl`` of the schema), else English; the descriptions of the
    options and the meanings of their values are Kartograf's English.

    Raises
    ------
    ProducerError
        Kartograf failed to describe its catalog.
    """
    polish = current_language() == "pl"
    try:
        entries = [
            command_schema(row.name).commands[0] for row in list_commands().commands
        ]
    except KartografError as error:
        raise call_error(error) from error
    return tuple(_command_info(entry, polish=polish) for entry in entries)


def parse(line: str) -> CommandCall:
    """Read a command line with the parser of ``kartograf`` (``parse_command``).

    Raises
    ------
    ProducerError
        A mistake of the line: an unknown command or flag, a value outside the
        choices of a flag, a flag without its value (``validation_error``).
    """
    try:
        call = parse_command(line)
    except KartografError as error:
        raise call_error(error) from error
    return CommandCall(PRODUCER, call.command, call.options, call.run)


def validate(
    command: str, options: Mapping[str, object], *, root: Path | None
) -> Mapping[str, object]:
    """Check a call with ``validate_command``, naming the store of a store command.

    Returns the options unchanged: Kartograf reads them as they are.

    Raises
    ------
    ProducerError
        Kartograf refused the call: an unknown command or option, a value of a
        wrong form or outside the allowed values, a broken rule among the
        options (``validation_error``, ``details.option`` or
        ``details.options``).
    ValueError
        A command that works on a store without its root: the default root of
        Kartograf would stand in, so the call never reaches Kartograf.
    """
    try:
        schema = command_schema(command)
    except KartografError as error:
        raise call_error(error, command=command, given=options) from error
    store = _works_on_store(schema.commands[0])
    if store and root is None:
        raise ValueError(f"{command} works on a store: give its root")
    try:
        if store:
            validate_command(command, options, root=root)
        else:
            validate_command(command, options)
    except KartografError as error:
        raise call_error(error, command=command, given=options) from error
    return dict(options)


def format_line(call: CommandCall) -> str:
    """Return the canonical ``kartograf …`` line of a call (``format_command``).

    Raises
    ------
    ProducerError
        An unknown command, an option the command does not have, one in both
        the options and the flags of a run, or a value of a wrong form
        (``validation_error``).
    """
    try:
        return format_command(call.command, call.options, run=call.run)
    except KartografError as error:
        raise call_error(error, command=call.command, given=call.options) from error


def availability_products() -> tuple[str, ...]:
    """Return the products ``check_availability`` reports on, in Kartograf's order.

    They are the values of the ``product`` option of its command in Kartograf's
    catalog (``elevation availability``).
    """
    entry = command_schema(AVAILABILITY_COMMAND).commands[0]
    return tuple(
        str(choice.value)
        for option in entry.options
        if option.name == "product"
        for choice in option.enum or ()
    )


def availability(
    product: str,
    *,
    area: GeoJSONGeometry,
    countries: tuple[str, ...],
    cache_dir: Path,
    force: bool,
    on_notice: Callable[[AvailabilityNotice], None] | None,
) -> AvailabilityReport:
    """Ask GUGiK and CUZK what they have for an area (``check_availability``).

    ``cache_dir`` holds Archiwista's own metadata cache of Kartograf
    (``METADATA_CACHE_FILE``); ``force`` asks the services again and writes
    the answers over the cached ones.

    Raises
    ------
    ProducerError
        Kartograf refused the request (an unknown product, an area outside
        PL and CZ) or a service failed, with Kartograf's code and text.
    """
    cache = MetadataCache(cache_dir / METADATA_CACHE_FILE)
    given: dict[str, object] = {"product": product}
    try:
        country, bbox = area_request(area, countries)
        given |= {"country": country, "bbox": list(bbox[:4]), "bbox_crs": bbox.crs}
        report = check_availability(
            product=product,
            country=country,
            bbox=bbox,
            cache=cache,
            force=force,
            on_notice=None if on_notice is None else _forward(on_notice),
        )
    except KartografError as error:
        raise call_error(error, command=AVAILABILITY_COMMAND, given=given) from error
    finally:
        cache.close()
    return _report(report)


def check(
    command: str,
    options: Mapping[str, object],
    *,
    root: Path,
    cache_dir: Path,
    on_notice: Callable[[AvailabilityNotice], None] | None,
) -> ActionPlan:
    """Plan a run of a command in the store at ``root`` (``check_command``).

    With Archiwista's own metadata cache (``METADATA_CACHE_FILE`` in
    ``cache_dir``), never ``cache=True``, whose answers younger than
    ``PLAN_REFRESH_TTL_S`` (the availability report's) are not asked again.
    A root a run would refuse as a conflict (``nested_store``, ``not_empty``)
    is the one position of Kartograf's plan, its reason in ``conflict``.
    Kartograf's plan names no size of a position (KC-3), so every
    ``size_bytes`` is ``None``.

    Raises
    ------
    ProducerError
        Kartograf refused the call: an unknown command or option, a command
        without a check (``details.kartograf.reason`` ``no_check``), a root
        without its marker (``store_unavailable``).
    UnsupportedError
        The check of the command is no plan of a store (``no_plan``):
        ``project download`` answers with the check of a project.
    """
    cache = MetadataCache(
        cache_dir / METADATA_CACHE_FILE, refresh_ttl_seconds=PLAN_REFRESH_TTL_S
    )
    try:
        result = check_command(
            command,
            options,
            root=root,
            cache=cache,
            on_notice=None if on_notice is None else _forward(on_notice),
        )
    except KartografError as error:
        raise call_error(error, command=command, given=options) from error
    finally:
        cache.close()
    plan = result.result
    if not isinstance(plan, UpdatePlan):
        raise UnsupportedError(
            message("command.no_plan", producer=PRODUCER, command=command),
            reason="no_plan",
        )
    return ActionPlan(
        producer=PRODUCER,
        command=result.command,
        schema=UpdatePlan.SCHEMA,
        root=plan.target,
        checked_at=datetime.fromisoformat(plan.checked_at),
        entries=tuple(_plan_entry(item) for item in plan.items),
        notices=tuple(_notice(notice) for notice in plan.notices),
        document=plan.to_dict(),
    )


def run(
    command: str,
    options: Mapping[str, object],
    *,
    root: Path,
    cache_dir: Path,
    plan: ActionPlan | None,
    upgrade: bool,
    on_progress: Callable[[ActionProgress], None] | None,
    on_notice: Callable[[AvailabilityNotice], None] | None,
) -> ActionResult:
    """Run a command in the store at ``root`` (``run_command``).

    With ``root=`` the configured store, Archiwista's own metadata cache
    (``METADATA_CACHE_FILE`` in ``cache_dir``), never ``cache=True``, and no
    ``output_dir``. With ``plan`` (a plan of ``check_command``) the run is
    ``update="upgrade", plan=…``, Kartograf's ``UpdatePlan`` read back from
    the plan's document; without one it is ``update="upgrade"`` with
    ``upgrade`` (the source's newer versions downloaded), else ``update`` is
    not given, so the versions the store holds are kept. ``files[]`` of
    ``kartograf-download/1`` come back below the root (``unchanged`` also
    stands for Kartograf's ``local`` and ``reused``); a command whose result
    is no download has none.

    Raises
    ------
    ProducerError
        Kartograf refused the call or the plan, or failed as a whole.
    BrokenContractError
        Kartograf reported a file outside the root, or a plain one
        (``written``, ``replaced``).
    """
    cache = MetadataCache(cache_dir / METADATA_CACHE_FILE)
    try:
        result = run_command(
            command,
            options,
            root=root,
            update="upgrade" if plan is not None or upgrade else None,
            plan=None if plan is None else UpdatePlan.from_dict(dict(plan.document)),
            cache=cache,
            on_progress=None if on_progress is None else _progress(on_progress),
            on_notice=None if on_notice is None else _forward(on_notice),
        )
    except KartografError as error:
        raise call_error(error, command=command, given=options) from error
    finally:
        cache.close()
    return _run_result(result, root)


def command_for_version(version: str, *, root: Path) -> CommandCall:
    """Return the call that selects the stored version ``version`` again.

    ``read_sidecar`` reads the sidecar of the version file ``root / version``
    (the file itself is never opened, so a version whose data are gone still
    has its call) and ``command_for_file`` rebuilds the call from it, as
    ``parse`` converts one: its options in their JSON form, no store root
    (the caller names it) and an empty ``run``. No network, nothing written.

    Raises
    ------
    UnsupportedError
        Kartograf cannot rebuild the call from the sidecar (reason
        ``command_not_rebuildable``, Kartograf's text and hint, its
        ``family`` and ``field``).
    ProducerError
        The sidecar is missing, unreadable or invalid (``data_error``).
    """
    try:
        call = command_for_file(read_sidecar(root / version))
    except CommandNotRebuildableError as error:
        refused = call_error(error)
        raise UnsupportedError(
            refused.message,
            reason="command_not_rebuildable",
            details={"producer": PRODUCER, "version": version, **refused.details},
            hint=refused.hint,
        ) from error
    except KartografError as error:
        raise call_error(error) from error
    return CommandCall(PRODUCER, call.command, call.options, call.run)


def narrow(plan: ActionPlan, paths: Collection[str]) -> ActionPlan:
    """Return a plan of ``check`` keeping only the positions to download at ``paths``.

    Kartograf's ``UpdatePlan`` is read back from the plan's document and
    written again without the other positions to download, and the entries
    lose them alike: Kartograf never executes positions removed from a plan
    (``kartograf/download/plan.py``). The positions a run does not download
    stay as they are.

    Raises
    ------
    ValueError
        The document is no ``kartograf-plan/1`` Kartograf reads back.
    """
    kept = frozenset(paths)
    try:
        document = UpdatePlan.from_dict(dict(plan.document))
    except KartografError as error:
        raise ValueError(f"no plan of Kartograf: {error}") from error
    items = tuple(
        item
        for item in document.items
        if item.status not in PLAN_TODO or item.store_path in kept
    )
    return replace(
        plan,
        entries=tuple(
            entry
            for entry in plan.entries
            if entry.status not in PLAN_TODO or entry.path in kept
        ),
        document=replace(document, items=items).to_dict(),
    )


def scope(path: str) -> ScanScope:
    """Return the scope of ``iter_store`` that reads the file at ``path`` again.

    A standard path is ``<product>/<variant>/<slot directory>/<file>``: the
    segment is its first two parts and the unit ``<slot directory>/<stem>``
    (the name without its last suffix), the form of a unit that ``iter_store``
    reads as the files of that stem in that directory, whatever kind of unit
    the slot is of (a sheet, a TERYT, a box, a country).

    Raises
    ------
    ValueError
        ``path`` is not relative, or has no segment and file name.
    """
    place = PurePosixPath(path)
    parts = place.parts
    if place.is_absolute() or len(parts) < 3 or {".", ".."} & set(parts):
        raise ValueError(f"{path!r} is no place of a file in a Kartograf store")
    product, variant, *hierarchy, name = parts
    stem = name.rpartition(".")[0] or name
    return ScanScope(
        segment=f"{product}/{variant}", units=("/".join((*hierarchy, stem)),)
    )


def area_request(area: GeoJSONGeometry, countries: tuple[str, ...]) -> tuple[str, BBox]:
    """Return Kartograf's ``country`` and ``bbox`` of an area (ADR-035).

    The box is the envelope of the polygon, its edges densified, in the CRS
    Kartograf measures the first of the area's countries in, so it is what
    Kartograf takes of a geometry file with that polygon; the country is
    ``pl`` or ``cz``, or ``auto`` for both. An area in neither country goes as
    its WGS84 envelope with ``auto``, for Kartograf to refuse.

    Raises
    ------
    KartografError
        No pinned operation to the CRS.
    """
    polygon = shape(area)
    named = {country.upper() for country in countries}
    known = [country for country in _AREA_CRS if country in named]
    if not known:
        min_x, min_y, max_x, max_y = (float(value) for value in polygon.bounds)
        return "auto", BBox(min_x, min_y, max_x, max_y, _WGS84)
    crs = _AREA_CRS[known[0]]
    points = shapely.get_coordinates(shapely.segmentize(polygon, _SEGMENT_DEGREES))
    xs, ys = pinned_transform(_WGS84, crs).transform(points[:, 0], points[:, 1])
    country = known[0].lower() if len(known) == 1 else "auto"
    return country, BBox(
        float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()), crs
    )


def call_error(
    error: KartografError,
    *,
    command: str | None = None,
    given: Mapping[str, object] | None = None,
) -> ProducerError:
    """Return Kartograf's description of an error as the error of Archiwista.

    ``error_report`` gives Kartograf's registry code, its text and hint in the
    language of the call (the hint's example follows the command and the
    options given), and its details: what it names (``option``, ``options``,
    ``allowed``) and its own ``reason``.
    """
    report = error_report(error, command=command, given=given, lang=current_language())
    return ProducerError(
        PACKAGE,
        type(error).__name__,
        report.message,
        code=report.code,
        hint=report.hint,
        details=report.details,
    )


def _forward(
    on_notice: Callable[[AvailabilityNotice], None],
) -> Callable[[Any], None]:
    """Pass each of Kartograf's notices on as a producer-neutral one."""

    def forward(notice: Any) -> None:
        on_notice(_notice(notice))

    return forward


def _progress(
    on_progress: Callable[[ActionProgress], None],
) -> Callable[[Any], None]:
    """Pass each ``DownloadProgress`` on, counting the units of the run.

    An event that counts something other than units (not ``_UNIT_COUNTS``)
    keeps the last counts of the units, and only an event about a unit
    (``_UNIT_NAMES``) names it.
    """
    counts = [0, 0]

    def forward(event: Any) -> None:
        status = str(event.status)
        if status in _UNIT_COUNTS:
            counts[:] = [int(event.current), int(event.total)]
        unit = str(event.sheet) if status in _UNIT_NAMES and event.sheet else None
        on_progress(
            ActionProgress(counts[0], counts[1], unit, status, str(event.message))
        )

    return forward


def _run_result(result: Any, root: Path) -> ActionResult:
    """Convert the envelope ``kartograf-result/1`` of a run.

    Read from its JSON form, the documented contract: ``files[]`` and
    ``items[]`` of ``kartograf-download/1``.
    """
    envelope = result.to_dict()
    document = envelope["result"]
    domain: Mapping[str, Any] = document if isinstance(document, Mapping) else {}
    return ActionResult(
        producer=PRODUCER,
        command=str(envelope["command"]),
        root=str(root),
        status=cast(RunStatus, envelope["status"]),
        files=tuple(_file(entry, root) for entry in domain.get("files", ())),
        items=tuple(
            ActionItem(
                id=str(item["id"]),
                status=cast(ItemStatus, item["status"]),
                code=item.get("code"),
                reason=item.get("reason"),
                message=item.get("message"),
            )
            for item in envelope["items"]
        ),
        notices=tuple(_notice(notice) for notice in result.notices),
        schema=None if document is None else str(domain.get("schema")),
    )


def _file(entry: Mapping[str, Any], root: Path) -> ActionFile:
    """Convert one entry of ``files[]``; a plain file breaks the contract."""
    status = str(entry["status"])
    path = str(entry["path"])
    if status not in FILE_STATUSES:
        raise _outside(path, status, root)
    version = entry.get("version_path")
    return ActionFile(
        path=_below(root, path, status),
        unit=str(entry["unit"]),
        status=status,
        size_bytes=int(entry["size_bytes"]),
        sha256=str(entry["sha256"]),
        label=entry.get("label"),
        version_path=None if version is None else _below(root, str(version), status),
    )


def _below(root: Path, path: str, status: str) -> str:
    """Return a file Kartograf reported as its place below the root."""
    place = Path(os.path.normpath(path))
    for base in (root, root.resolve()):
        with suppress(ValueError):
            relative = place.relative_to(base)
            if relative.parts:
                return relative.as_posix()
    raise _outside(path, status, root)


def _outside(path: str, status: str, root: Path) -> BrokenContractError:
    """Return the refusal of a file that is no file of the store at ``root``."""
    return BrokenContractError(
        message(
            "command.file_outside_store",
            producer=PRODUCER,
            path=path,
            status=status,
            root=root,
        )
    )


def _report(report: Any) -> AvailabilityReport:
    """Convert ``kartograf-availability/1`` (``AvailabilityReport``)."""
    return AvailabilityReport(
        producer=PRODUCER,
        schema=str(report.schema),
        checked_at=datetime.fromisoformat(report.checked_at),
        request=dict(report.request),
        areas=tuple(
            AvailabilityArea(
                country=area.country,
                crs=area.crs,
                bounds=(
                    float(area.bounds[0]),
                    float(area.bounds[1]),
                    float(area.bounds[2]),
                    float(area.bounds[3]),
                ),
                area_m2=float(area.area_m2),
                land_m2=float(area.land_m2),
            )
            for area in report.areas
        ),
        combinations=tuple(_combination(item) for item in report.combinations),
        failed=tuple(
            AvailabilityFailure(failure.unit, str(failure.error), failure.kind)
            for failure in report.failed
        ),
        notices=tuple(_notice(notice) for notice in report.notices),
        ok=bool(report.ok),
    )


def _combination(item: Any) -> AvailabilityCombination:
    """Convert one ``AvailabilityCombination`` with its KD-1 and KD-2 fields.

    Its ``download_hint`` (command lines after ``kartograf``, without the
    store) are the combination's ``commands``.
    """
    published = item.published
    return AvailabilityCombination(
        country=item.country,
        product=item.product,
        source=item.source,
        year=item.year,
        horizontal=item.horizontal,
        resolution=item.resolution,
        vertical_crs=item.vertical_crs,
        format=item.format,
        campaigns=tuple(item.campaigns),
        complete=bool(item.complete),
        sheets_full=tuple(item.sheets_full),
        sheets_partial=tuple(item.sheets_partial),
        sheets_missing=tuple(item.sheets_missing),
        uncovered_m2=float(item.uncovered_m2),
        full_m2=float(item.full_m2),
        size_bytes=item.size_bytes,
        published=None if published is None else (str(published[0]), str(published[1])),
        sheet_records=tuple(
            AvailabilitySheet(
                sheet=record.sheet,
                campaign=record.campaign,
                full_sheet=record.full_sheet,
                acquisition_date=record.acquisition_date,
                published=record.published,
            )
            for record in item.sheet_records
        ),
        campaign_coverage=tuple(
            AvailabilityCampaign(
                campaign=campaign.campaign,
                complete=bool(campaign.complete),
                full_m2=float(campaign.full_m2),
            )
            for campaign in item.campaign_coverage
        ),
        commands=tuple(str(line) for line in item.download_hint),
    )


def _notice(notice: Any) -> AvailabilityNotice:
    """Convert a ``Notice``; a text of Kartograf's catalog in the call's language."""
    text = notice.message
    language = current_language()
    localized = getattr(text, "localized", None)
    if callable(localized) and language in _LANGUAGES:
        text = localized(language)
    return AvailabilityNotice(notice.level, notice.code, str(text))


def _plan_entry(item: PlanItem) -> PlanEntry:
    """Convert one position of ``kartograf-plan/1`` (``PlanItem``)."""
    return PlanEntry(
        path=item.store_path,
        unit=item.unit,
        status=item.status,
        local_label=item.local_label,
        available_label=item.available_label,
        error=item.error,
        conflict=item.reason if item.action == "conflict" else None,
    )


def _command_info(entry: Any, *, polish: bool) -> CommandInfo:
    """Convert one command of ``kartograf-commands/1``."""
    effects = entry.effects
    return CommandInfo(
        producer=PRODUCER,
        command=entry.name,
        group=entry.name.partition(" ")[0],
        summary=entry.i18n.pl.summary if polish else entry.summary,
        description=entry.i18n.pl.description if polish else entry.description,
        options=tuple(
            _option(option)
            for option in entry.options
            if option.name not in BESIDE_OPTIONS
        ),
        read_only=effects.read_only,
        writes=cast(CommandWrites, effects.writes),
        network=effects.network,
        check=entry.check is not None,
        store=_works_on_store(entry),
        examples=tuple(example.call for example in entry.examples),
    )


def _option(option: Any) -> CommandOption:
    """Convert one option of a command's schema."""
    role = option.path_role
    return CommandOption(
        name=option.name,
        type=cast(OptionType, option.type),
        required=option.required,
        description=option.description,
        choices=tuple(
            CommandChoice(choice.value, choice.meaning) for choice in option.enum or ()
        ),
        default=option.default,
        minimum=option.minimum,
        maximum=option.maximum,
        items=cast(OptionType | None, option.items),
        group=option.one_of,
        path_role=cast(PathRole, role) if role in _PATH_ROLES else None,
    )


def _works_on_store(entry: Any) -> bool:
    """Whether a command takes the store root (an option with that path role)."""
    return any(option.path_role == _ROOT_ROLE for option in entry.options)
