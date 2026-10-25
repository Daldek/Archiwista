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
cache, its ``kartograf-plan/1`` read as the producer-neutral ``ActionPlan``.
"""

import inspect
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import shapely
from kartograf import (
    BBox,
    KartografError,
    MetadataCache,
    PlanItem,
    UpdatePlan,
    check_availability,
    check_command,
    command_schema,
    error_report,
    format_command,
    list_commands,
    parse_command,
    pinned_transform,
    run_command,
    validate_command,
)
from shapely.geometry import shape

from archiwista.adapter.kartograf import PACKAGE, PRODUCER
from archiwista.errors import ProducerError, UnsupportedError
from archiwista.messages import current_language, message
from archiwista.sources import (
    ActionPlan,
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
    OptionType,
    PathRole,
    PlanEntry,
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
    ``cache_dir``), never ``cache=True``. A root a run would refuse as a
    conflict (``nested_store``, ``not_empty``) is the one position of
    Kartograf's plan, its reason in ``conflict``. Kartograf's plan names no size
    of a position (KC-3), so every ``size_bytes`` is ``None``.

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
    cache = MetadataCache(cache_dir / METADATA_CACHE_FILE)
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
    """Convert one ``AvailabilityCombination`` with its KD-1 and KD-2 fields."""
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
