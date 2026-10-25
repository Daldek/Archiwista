"""The availability at the source for every interface (plan of 2026-10-25, A2, A3).

``check`` answers a request for what the source has for an area and a
product: the report the index keeps for them while it is younger than
``REPORT_TTL`` and the request does not ``force`` a new question, else the
``availability`` job that asks the source (a new one, or an active one that
asks the same question; ADR-035). ``stored`` returns the last report without
the network. ``POST /availability``, ``GET /availability`` and ``archiwista
availability`` call them.

``rows`` reads a report as the summary of SPEC 6.3 and 6.4, without I/O: a
row for each year of a country, the year's variants ranked (the formats of
one set are one variant, ADR-017) and the coverage label of each as
structure (`CoverageLabel`); the interfaces write its text. ``summary`` adds
the store badge of each variant from the index (`StoreBadge`).
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal

from archiwista.auth import Principal
from archiwista.config import AppSettings
from archiwista.errors import NotFoundError, UnsupportedError
from archiwista.index import AreaRecord, IndexQueries, StoredAvailability
from archiwista.jobs import JobRecord, JobSupervisor
from archiwista.messages import message
from archiwista.services.commands import actions
from archiwista.sources import AvailabilityCombination, AvailabilityReport
from archiwista.sources.registry import PluginRegistry

# How long a kept report answers for the source: Kartograf's metadata cache
# keeps an answer of the source as long (SPEC 6.3), so a check within it
# would mostly read the same answers again.
REPORT_TTL = timedelta(days=7)

# The formats a download takes unless the person chooses another one, first
# found first: the raster formats ready for a mosaic, ASC, then GeoTIFF
# (Kartograf's ``TIFF``; SPEC 6.4, ADR-017). A set in none of them has no
# default format, so its plan asks for an explicit choice.
DEFAULT_FORMATS = ("ASC", "TIFF")

type CoverageKind = Literal["full", "full_campaigns", "partial", "no_data"]
type BadgeState = Literal["all", "some", "none"]

# A resolution label of the producer in metres (``1m``, ``0.5m``).
_RESOLUTION = re.compile(r"(\d+(?:\.\d+)?)m")


@dataclass(frozen=True, slots=True)
class AreaAvailability:
    """The last report of an area and a product, with the area it is about."""

    area: AreaRecord
    stored: StoredAvailability


def check(
    queries: IndexQueries,
    registry: PluginRegistry,
    jobs: JobSupervisor,
    *,
    area_id: str,
    product: str,
    producer: str,
    force: bool,
    actor: Principal,
) -> AreaAvailability | JobRecord:
    """Return the area's fresh report of a product, else the job that asks the source.

    Parameters
    ----------
    queries : IndexQueries
        Reader of the local index: the area and its reports.
    registry : PluginRegistry
        Producer plugins: the products the producer checks.
    jobs : JobSupervisor
        Started supervisor of the ``availability`` job.
    area_id : str
        An area the index keeps (``POST /areas``).
    product : str
        A product of the producer's ``availability_products``.
    producer : str
        Producer id.
    force : bool
        Ask the source even when a report younger than ``REPORT_TTL`` is kept.
    actor : Principal
        Who asks: the job's actor.

    Returns
    -------
    AreaAvailability or JobRecord
        The kept report when it is fresh and ``force`` is off; else the job,
        queued or running (also one of another request that it joined).

    Raises
    ------
    NotFoundError
        The index keeps no area ``area_id``.
    SourceUnavailableError, SourceIncompatibleError
        The producer's plugin is not available.
    UnsupportedError
        The producer offers no commands (reason ``no_commands``), or checks
        no availability of ``product`` (``no_availability``,
        ``details.allowed``).
    OfflineModeError
        A job is needed and offline mode is on; nothing is recorded.
    """
    record = _area(queries, area_id)
    products = actions(registry, producer).availability_products()
    if product not in products:
        raise UnsupportedError(
            message(
                "availability.product_unsupported",
                producer=producer,
                product=product,
                allowed=", ".join(products),
            ),
            reason="no_availability",
            details={"allowed": list(products)},
        )
    if not force:
        found = queries.availability(area_id, product, producer=producer)
        if found is not None and datetime.now(UTC) - found.checked_at < REPORT_TTL:
            return AreaAvailability(record, found)
    params = {
        "area_id": area_id,
        "producer": producer,
        "product": product,
        "force": force,
    }
    return jobs.submit("availability", params=params, actor=actor)


def stored(
    queries: IndexQueries, *, area_id: str, product: str, producer: str
) -> AreaAvailability:
    """Return the last report of an area and a product, without the network.

    Raises
    ------
    NotFoundError
        The index keeps no area ``area_id``, or no report of its ``product``
        by ``producer``.
    """
    record = _area(queries, area_id)
    found = queries.availability(area_id, product, producer=producer)
    if found is None:
        raise NotFoundError(
            message(
                "availability.none", area=area_id, product=product, producer=producer
            )
        )
    return AreaAvailability(record, found)


def _area(queries: IndexQueries, area_id: str) -> AreaRecord:
    """Return a kept area or refuse with ``NotFoundError``."""
    record = queries.area(area_id)
    if record is None:
        raise NotFoundError(message("api.area_unknown", area=area_id))
    return record


@dataclass(frozen=True, slots=True)
class CoverageLabel:
    """The coverage label of a year in a variant (SPEC 6.4), as structure.

    The interfaces write its text: "pełne" (``full``), "pełne · 2 kampanie"
    (``full_campaigns``), "częściowe · 58%" (``partial``, "<1%" with
    ``below_one``) with "· 1 ark. niepełny", and "brak danych" (``no_data``).

    Parameters
    ----------
    kind : {"full", "full_campaigns", "partial", "no_data"}
        ``full``: complete, and one campaign covers the land with its full
        sheets on its own, or the records name at most one campaign;
        ``full_campaigns``: complete only from ``campaigns`` campaigns
        together; ``partial``: not complete; ``no_data``: the year has no
        combination in the active variant.
    campaigns : int
        The distinct campaigns of the records a download takes (KD-1), never
        every campaign the combination names (``campaigns`` also counts
        incomplete records).
    share : float or None
        The land in the frames of full sheets over the land of the area, the
        lower bound of what has data; ``None`` without land or a combination.
    percent : int or None
        ``share`` in whole percent rounded down, so a partial combination
        shows at most 99.
    below_one : bool
        A partial share above zero that is below 1%.
    partial_sheets, missing_sheets : int
        Sheets with partial records only, and sheets without a file (CZ).
    """

    kind: CoverageKind
    campaigns: int
    share: float | None
    percent: int | None
    below_one: bool
    partial_sheets: int
    missing_sheets: int


NO_DATA = CoverageLabel(
    kind="no_data",
    campaigns=0,
    share=None,
    percent=None,
    below_one=False,
    partial_sheets=0,
    missing_sheets=0,
)
"""The label of a year without a combination in the active variant."""


@dataclass(frozen=True, slots=True)
class VariantFilter:
    """The dimensions of the variant a person fixed (the chips, SPEC 6.3).

    ``None`` leaves a dimension open, so the ranking chooses it for each year.
    """

    horizontal: str | None = None
    resolution: str | None = None
    vertical_crs: str | None = None

    def admits(self, combination: AvailabilityCombination) -> bool:
        """Return whether a combination has each fixed value."""
        return all(
            fixed is None or fixed == value
            for fixed, value in (
                (self.horizontal, combination.horizontal),
                (self.resolution, combination.resolution),
                (self.vertical_crs, combination.vertical_crs),
            )
        )


@dataclass(frozen=True, slots=True)
class StoreBadge:
    """How much of a variant's set a store holds (SPEC 6.4, the store badge).

    Parameters
    ----------
    store : str
        Store id.
    units : int
        The set's units of which the store holds a version of the set.
    of : int
        The set's units: its full and partial sheets.
    """

    store: str
    units: int
    of: int

    @property
    def state(self) -> BadgeState:
        """``all`` ("pobrane"), ``some`` ("pobrane 5/12") or ``none``."""
        if self.units == 0:
            return "none"
        return "all" if self.units == self.of else "some"


@dataclass(frozen=True, slots=True)
class AvailabilityVariant:
    """One set of the source in each of its formats: a row or a card (ADR-017).

    A set is the combinations of one country, product, year, horizontal
    system, resolution, height system and campaigns; the format is not part
    of it, so the formats are the set's badges. Its label and sheets are
    those of `combination`.

    Parameters
    ----------
    combinations : tuple[AvailabilityCombination, ...]
        The set in each format, in the report's order.
    default_format : str or None
        The first of ``DEFAULT_FORMATS`` among the set's formats; ``None``
        when it has none, so the plan asks for an explicit choice.
    label : CoverageLabel
        What the source has of the set for the area.
    local : StoreBadge or None
        How much of it a store holds; ``None`` until `summary` counts it.
    """

    combinations: tuple[AvailabilityCombination, ...]
    default_format: str | None
    label: CoverageLabel
    local: StoreBadge | None = None

    @property
    def combination(self) -> AvailabilityCombination:
        """The combination of the default format, else the first one."""
        return _shown(self.combinations, self.default_format)

    @property
    def formats(self) -> tuple[str, ...]:
        """The set's formats, in the report's order."""
        return tuple(item.format for item in self.combinations)

    @property
    def size_bytes(self) -> int | None:
        """Size of the default format's files; ``None`` when unknown or no default."""
        if self.default_format is None:
            return None
        return self.combination.size_bytes


@dataclass(frozen=True, slots=True)
class AvailabilityRow:
    """One year of one country in the active variant (SPEC 6.3 point 4).

    Parameters
    ----------
    country : str
        Country code (``AvailabilityArea.country``).
    year : int or None
        Year of the data; ``None`` where the source publishes none (CZ).
    variants : tuple[AvailabilityVariant, ...]
        The year's variants with the fixed dimensions, best first by the
        ranking of SPEC 6.4: the row shows the first, the others are "+N
        warianty"; none for "brak danych".
    """

    country: str
    year: int | None
    variants: tuple[AvailabilityVariant, ...]

    @property
    def label(self) -> CoverageLabel:
        """The label of the variant the row shows, else ``NO_DATA``."""
        return self.variants[0].label if self.variants else NO_DATA

    @property
    def other_variants(self) -> int:
        """How many more variants the year has ("+N warianty")."""
        return max(len(self.variants) - 1, 0)

    @property
    def local(self) -> StoreBadge | None:
        """The badge of the variant the row shows; ``None`` without one."""
        return self.variants[0].local if self.variants else None


def rows(
    report: AvailabilityReport, *, fixed: VariantFilter | None = None
) -> tuple[AvailabilityRow, ...]:
    """Return the summary of a report: a row for each year of each country.

    The rows follow the report's order of countries and years. A year's
    variants are those with the ``fixed`` dimensions, ranked: complete before
    partial, then the larger share of full sheets, fewer campaigns (fewer
    seams between flights), the finer resolution and the report's order. A
    year of the report without such a variant is a row of "brak danych".
    """
    admitted = fixed or VariantFilter()
    years: dict[tuple[str, int | None], list[tuple[int, AvailabilityVariant]]] = {}
    for order, variant in enumerate(variants(report)):
        combination = variant.combination
        found = years.setdefault((combination.country, combination.year), [])
        if admitted.admits(combination):
            found.append((order, variant))
    return tuple(
        AvailabilityRow(
            country=country,
            year=year,
            variants=tuple(
                variant for _, variant in sorted(found, key=lambda pair: _rank(*pair))
            ),
        )
        for (country, year), found in years.items()
    )


def summary(
    queries: IndexQueries,
    report: AvailabilityReport,
    *,
    store: str | None = None,
    fixed: VariantFilter | None = None,
) -> tuple[AvailabilityRow, ...]:
    """Return the rows of a report, each variant with its badge in ``store``.

    A unit of a variant, a full or partial sheet of its shown combination,
    counts when the store holds a present version of that combination's
    dataset (so of its format), of its year and of one of its campaigns; a
    combination without a year or campaigns asks for none. The height system
    is not compared: a combination names it as the source does (``EVRF2007``),
    a version's sidecar by its EPSG code, and the producer names no store
    segment of a combination (a request to Kartograf), so a version of the
    same sheet, year and campaign in another height system counts too.
    Without ``store`` no variant has a badge.
    """
    found = rows(report, fixed=fixed)
    if store is None:
        return found
    return tuple(
        replace(
            row,
            variants=tuple(
                replace(item, local=_badge(queries, store, item.combination))
                for item in row.variants
            ),
        )
        for row in found
    )


def known_store(settings: AppSettings, store: str | None) -> None:
    """Refuse a store the settings do not name.

    Raises
    ------
    NotFoundError
        ``store`` is not configured.
    """
    if store is not None and settings.store(store) is None:
        raise NotFoundError(message("api.store_not_configured", store=store))


def _badge(
    queries: IndexQueries, store: str, combination: AvailabilityCombination
) -> StoreBadge:
    """Count the units of a combination that ``store`` holds a version of."""
    units = tuple(
        dict.fromkeys((*combination.sheets_full, *combination.sheets_partial))
    )
    held = queries.held_units(
        store,
        dataset=combination.source,
        units=units,
        year=combination.year,
        campaigns=combination.campaigns,
    )
    return StoreBadge(store=store, units=len(held), of=len(units))


def variants(report: AvailabilityReport) -> tuple[AvailabilityVariant, ...]:
    """Return the sets of a report in the report's order, each with its formats."""
    land = {area.country: area.land_m2 for area in report.areas}
    sets: dict[tuple[object, ...], list[AvailabilityCombination]] = {}
    for item in report.combinations:
        key = (
            item.country,
            item.product,
            item.year,
            item.horizontal,
            item.resolution,
            item.vertical_crs,
            tuple(sorted(set(item.campaigns))),
        )
        sets.setdefault(key, []).append(item)
    found: list[AvailabilityVariant] = []
    for combinations in sets.values():
        formats = {item.format for item in combinations}
        default = next((name for name in DEFAULT_FORMATS if name in formats), None)
        shown = _shown(combinations, default)
        found.append(
            AvailabilityVariant(
                combinations=tuple(combinations),
                default_format=default,
                label=coverage_label(shown, land_m2=land.get(shown.country)),
            )
        )
    return tuple(found)


def coverage_label(
    combination: AvailabilityCombination, *, land_m2: float | None
) -> CoverageLabel:
    """Return the label of a combination (SPEC 6.4).

    ``land_m2`` is the land of the combination's country in the report
    (`AvailabilityArea`); without land (``None`` or zero) the share is
    unknown.
    """
    campaigns = len(
        {
            record.campaign
            for record in combination.sheet_records
            if record.campaign is not None
        }
    )
    share = combination.full_m2 / land_m2 if land_m2 else None
    percent = None if share is None else _percent(share)
    kind: CoverageKind
    if combination.complete:
        alone = campaigns <= 1 or any(
            item.complete for item in combination.campaign_coverage
        )
        kind = "full" if alone else "full_campaigns"
    else:
        kind = "partial"
        percent = None if percent is None else min(percent, 99)
    return CoverageLabel(
        kind=kind,
        campaigns=campaigns,
        share=share,
        percent=percent,
        below_one=kind == "partial" and bool(share) and percent == 0,
        partial_sheets=len(combination.sheets_partial),
        missing_sheets=len(combination.sheets_missing),
    )


def _shown(
    combinations: Sequence[AvailabilityCombination], default_format: str | None
) -> AvailabilityCombination:
    """Return the combination of the default format, else the first one."""
    return next(
        (item for item in combinations if item.format == default_format),
        combinations[0],
    )


def _rank(
    order: int, variant: AvailabilityVariant
) -> tuple[bool, float, int, float, int]:
    """Return the sort key of a year's variant, best first (SPEC 6.4)."""
    label = variant.label
    share = 0.0 if label.share is None else round(label.share * 100, 6)
    return (
        not variant.combination.complete,
        -share,
        label.campaigns,
        _metres(variant.combination.resolution),
        order,
    )


def _metres(resolution: str | None) -> float:
    """Return the metres of a resolution label; one without them sorts last."""
    match = None if resolution is None else _RESOLUTION.fullmatch(resolution)
    return math.inf if match is None else float(match[1])


def _percent(ratio: float) -> int:
    """Return whole percent rounded down, as the local coverage's ``percent``.

    Rounding to a millionth of a percent first absorbs the floating-point
    error of a measured share (69.6 km² of 120 km² is 58%, not 57%).
    """
    return math.floor(round(ratio * 100, 6))
