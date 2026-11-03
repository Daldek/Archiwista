"""The coverage of a station's series by year, from its series index (SPEC 4.8.4).

Pure functions, no I/O: the index computes each year of a variable once, when
it writes the series index of a version (``series_years``), and the labels of
any range of years come from those rows without reading a series again
(A-ADR-021). A year is counted in units of the series, as whole numbers: a
day is its ordinal, a month ``year * 12 + month - 1`` and a half-year
characteristic one unit per hydrological year (its winter, summer or annual
value), which has no calendar year (SPEC 4.8.2). The hydrological year N runs
from 1 XI of year N - 1 to 31 X of year N.

For each year of a variable: ``units`` is the length of the year, ``known``
its units within the known periods (the station's own periods, or else those
of the version: A-ADR-021 erratum 3), and ``with_value`` the known units from
the first to the last unit with a value that lie in no gap. The gap lists
decide, not the producer's count of units with a value: SPEC 4.8.4 computes
the coverage from the gap lists.

``series_label`` reads a variable's years in a range R as the label of SPEC
4.8.4, as structure (`SeriesLabel`); the interfaces write its text. A year is
known when all its units are; K1 and K2 are the first and last known year of
R, y1 and y2 the first and last known year with a value. The gaps are the
known units of y1 to y2 without a value, their share rounded up to a whole
percent, and the longest gap the longest run of them.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field

from archiwista.sources import DateRange, TimeUnit, VariableCoverage, YearType

type Interval = tuple[int, int]
type YearRange = tuple[int, int]
type SeriesState = Literal["continuous", "gaps", "partial", "no_data", "unknown"]

YEAR_TYPES: tuple[YearType, ...] = ("hydrological", "calendar")
SERIES_STATES: tuple[SeriesState, ...] = (
    "continuous",
    "gaps",
    "partial",
    "no_data",
    "unknown",
)
# The states of a variable with a value in a known year of the range.
VALUED_STATES: frozenset[SeriesState] = frozenset({"continuous", "gaps", "partial"})
# The unknown years a label names as ranges; more are only counted.
MAX_UNKNOWN_RANGES = 2
# A gap longer than this many days is counted among the long ones.
LONG_GAP_DAYS = 30
# The first month of the hydrological year (1 XI of the year before).
_HYDROLOGICAL_START = 11


class YearTypes(BaseModel):
    """The year type a person remembers for hydro and for meteo data (P15, SPEC 6.7).

    The numbering of the years of each family in the station views without
    ``year_type``: hydrological and calendar years by default, as the archives
    number them. A ``year_type`` asked for wins and changes neither; half-year
    characteristics stay hydrological (SPEC 4.8.2).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    hydro: YearType = Field(
        default="hydrological",
        description="Numbering of the years of hydro data: hydrological by default.",
    )
    meteo: YearType = Field(
        default="calendar",
        description="Numbering of the years of meteo data: calendar by default.",
    )

    def of_kind(self, kind: str | None) -> YearType:
        """Return the type of a family: hydro's for ``hydro``, else meteo's."""
        return self.hydro if kind == "hydro" else self.meteo


# What a person who chose nothing gets: the numbering of the IMGW archives.
DEFAULT_YEAR_TYPES = YearTypes()


class SeriesYear(NamedTuple):
    """A year of a variable: its units, the known ones and those with a value.

    A year is known when every unit is (``known == units``); a full year has
    a value in every unit (``with_value == units``). A named tuple: a page of
    stations reads tens of thousands of years, and a tuple is the cheapest
    immutable record to build.
    """

    year_type: YearType
    year: int
    units: int
    known: int
    with_value: int


def year_types(time_unit: TimeUnit) -> tuple[YearType, ...]:
    """Return the year types of a unit: a half-year has hydrological years only."""
    return ("hydrological",) if time_unit == "half_year" else YEAR_TYPES


def hydrological_year(day: date) -> int:
    """Return the hydrological year of a day (1 XI 2023 is in the year 2024)."""
    return day.year + 1 if day.month >= _HYDROLOGICAL_START else day.year


def unit_of(day: date, time_unit: TimeUnit) -> int:
    """Return the unit a day lies in."""
    if time_unit == "day":
        return day.toordinal()
    if time_unit == "month":
        return day.year * 12 + day.month - 1
    return hydrological_year(day)


def day_of(unit: int, time_unit: TimeUnit) -> date:
    """Return the first day of a unit."""
    if time_unit == "day":
        return date.fromordinal(unit)
    if time_unit == "month":
        return date(unit // 12, unit % 12 + 1, 1)
    return date(unit - 1, _HYDROLOGICAL_START, 1)


def year_span(year: int, year_type: YearType, time_unit: TimeUnit) -> Interval:
    """Return the first and last unit of a year.

    Raises
    ------
    ValueError
        A calendar year of half-year characteristics.
    """
    if time_unit == "half_year":
        if year_type != "hydrological":
            raise ValueError("half-year characteristics have hydrological years only")
        return year, year
    if year_type == "calendar":
        start, end = date(year, 1, 1), date(year, 12, 31)
    else:
        start, end = date(year - 1, _HYDROLOGICAL_START, 1), date(year, 10, 31)
    return unit_of(start, time_unit), unit_of(end, time_unit)


def year_of(unit: int, year_type: YearType, time_unit: TimeUnit) -> int:
    """Return the year a unit lies in."""
    if time_unit == "half_year":
        return unit
    day = day_of(unit, time_unit)
    return day.year if year_type == "calendar" else hydrological_year(day)


def intervals(ranges: Iterable[DateRange], time_unit: TimeUnit) -> list[Interval]:
    """Return ranges of days as sorted, disjoint ranges of units."""
    return merge(
        (unit_of(start, time_unit), unit_of(end, time_unit)) for start, end in ranges
    )


def merge(items: Iterable[Interval]) -> list[Interval]:
    """Sort intervals and join those that overlap or touch."""
    merged: list[Interval] = []
    for start, end in sorted(item for item in items if item[0] <= item[1]):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def intersect(left: Sequence[Interval], right: Sequence[Interval]) -> list[Interval]:
    """Return the units in both lists of sorted, disjoint intervals."""
    found: list[Interval] = []
    i = j = 0
    while i < len(left) and j < len(right):
        start = max(left[i][0], right[j][0])
        end = min(left[i][1], right[j][1])
        if start <= end:
            found.append((start, end))
        if left[i][1] < right[j][1]:
            i += 1
        else:
            j += 1
    return found


def subtract(left: Sequence[Interval], right: Sequence[Interval]) -> list[Interval]:
    """Return the units of ``left`` in no interval of ``right`` (both sorted)."""
    found: list[Interval] = []
    j = 0
    for start, end in left:
        cursor = start
        while j < len(right) and right[j][1] < cursor:
            j += 1
        k = j
        while k < len(right) and right[k][0] <= end:
            if right[k][0] > cursor:
                found.append((cursor, right[k][0] - 1))
            cursor = max(cursor, right[k][1] + 1)
            k += 1
        if cursor <= end:
            found.append((cursor, end))
    return found


def length(items: Iterable[Interval]) -> int:
    """Return how many units the intervals hold."""
    return sum(end - start + 1 for start, end in items)


def value_intervals(
    coverage: VariableCoverage, known: Sequence[Interval], time_unit: TimeUnit
) -> list[Interval]:
    """Return the known units with a value of a variable.

    They are the known units from the first to the last unit with a value
    that lie in no gap; none without a value at all.
    """
    if coverage.first is None or coverage.last is None:
        return []
    span = [(unit_of(coverage.first, time_unit), unit_of(coverage.last, time_unit))]
    return subtract(intersect(known, span), intervals(coverage.gaps, time_unit))


def series_years(
    coverage: VariableCoverage, *, periods: Sequence[DateRange], time_unit: TimeUnit
) -> tuple[SeriesYear, ...]:
    """Return the years of a variable, in each year type of its unit.

    Parameters
    ----------
    coverage : VariableCoverage
        The variable's coverage in the series index.
    periods : Sequence[DateRange]
        The known periods: the station's own, else the version's.
    time_unit : TimeUnit
        The unit of the dataset's series.

    Returns
    -------
    tuple[SeriesYear, ...]
        By year type (hydrological first), then year: every year from the
        first to the last with a known unit, the years between them without
        one included (``known`` 0: unknown, never a gap). None without known
        periods.
    """
    known = intervals(periods, time_unit)
    if not known:
        return ()
    values = value_intervals(coverage, known, time_unit)
    years: list[SeriesYear] = []
    for year_type in year_types(time_unit):
        first = year_of(known[0][0], year_type, time_unit)
        last = year_of(known[-1][1], year_type, time_unit)
        for year in range(first, last + 1):
            span = [year_span(year, year_type, time_unit)]
            years.append(
                SeriesYear(
                    year_type=year_type,
                    year=year,
                    units=length(span),
                    known=length(intersect(known, span)),
                    with_value=length(intersect(values, span)),
                )
            )
    return tuple(years)


@dataclass(frozen=True, slots=True)
class GapRun:
    """A run of consecutive known units without a value (SPEC 4.8.4).

    ``start`` is the first day of its first unit and ``end`` the last day of
    its last one; ``units`` counts them.
    """

    start: date
    end: date
    units: int


@dataclass(frozen=True, slots=True)
class SeriesLabel:
    """The coverage label of a variable in a range of years, as structure.

    The interfaces write its text (SPEC 4.8.4): "ciągły · 1951–2025"
    (``continuous``), "luki 3% · najdł. 1981.06.02–1982.12.31" (``gaps``),
    "częściowy · od 1972 · luki 12%" (``partial``), "brak danych (tylko H)"
    (``no_data``) and "nieznane" (``unknown``), with "· nieznane: 2011–2025"
    when some years of the range are not known.

    Parameters
    ----------
    state : {"continuous", "gaps", "partial", "no_data", "unknown"}
        ``continuous``: y1 = K1, y2 = K2 and no gap; ``gaps``: the same with
        gaps; ``partial``: y1 > K1 or y2 < K2; ``no_data``: known years
        without a value; ``unknown``: no known year in the range.
    year_type : {"hydrological", "calendar"}
        The numbering of the years.
    span : tuple[int, int] or None
        R, the range of years; ``None`` when the series knows no period.
    known : tuple[int, int] or None
        K1 and K2, the first and last known year of R.
    valued : tuple[int, int] or None
        y1 and y2, the first and last known year of R with a value.
    units, with_value : int
        The known units of y1 to y2, and those of them with a value.
    percent : int
        The gap share in whole percent rounded up (2.15% is 3), at most 99:
        a range with a value is never all gaps; 0 without a gap.
    below_one : bool
        A gap share above zero that is below 1% ("<1%", never "0%").
    longest_gap : GapRun or None
        The longest run of gaps in y1 to y2 (the first of equal ones).
    gap_count, long_gaps : int
        The runs of gaps in y1 to y2, and those longer than
        ``LONG_GAP_DAYS`` days.
    gap_runs : tuple[tuple[int, int], ...]
        Those runs in order, each its first and last unit: a chart draws
        them as its bands (``gap_run`` gives their days), so a band is a gap
        the label counts (ADR-045 erratum 1).
    complete_years : int
        Full years of y1 to y2: a value in every unit.
    unknown_years : tuple[tuple[int, int], ...]
        The years of R that are not known, as ranges of years.
    only : tuple[str, ...]
        For ``no_data`` of a hydrological series, the station's variables
        that have a value in those years ("brak danych (tylko H)").
    """

    state: SeriesState
    year_type: YearType
    span: YearRange | None
    known: YearRange | None = None
    valued: YearRange | None = None
    units: int = 0
    with_value: int = 0
    percent: int = 0
    below_one: bool = False
    longest_gap: GapRun | None = None
    gap_count: int = 0
    long_gaps: int = 0
    gap_runs: tuple[Interval, ...] = ()
    complete_years: int = 0
    unknown_years: tuple[YearRange, ...] = ()
    only: tuple[str, ...] = ()

    @property
    def missing_share(self) -> float:
        """The gaps over the known units of y1 to y2; 0 without such units."""
        return (self.units - self.with_value) / self.units if self.units else 0.0

    @property
    def unknown_count(self) -> int:
        """How many years of R are not known."""
        return sum(end - start + 1 for start, end in self.unknown_years)


def label_year_type(
    kind: str | None, time_unit: TimeUnit, asked: YearType | None, remembered: YearTypes
) -> YearType:
    """Return the year type of a dataset's labels (SPEC 4.8.2, P15).

    The one asked, else the one remembered for the dataset's family
    (``remembered``: hydro for ``hydro`` data, meteo for the others, by
    default hydrological and calendar years); half-year characteristics stay
    in hydrological years whatever is asked, as IMGW computes them.
    """
    if time_unit == "half_year":
        return "hydrological"
    if asked is not None:
        return asked
    return remembered.of_kind(kind)


def default_span(
    first_year: int | None,
    periods: Sequence[DateRange],
    *,
    time_unit: TimeUnit,
    year_type: YearType,
) -> YearRange | None:
    """Return R by default: the dataset's first year to the last published one.

    The first year the source publishes, else the first year of the known
    periods, up to the last year of the known periods of the version; ``None``
    without known periods.
    """
    known = intervals(periods, time_unit)
    if not known:
        return None
    last = year_of(known[-1][1], year_type, time_unit)
    first = year_of(known[0][0], year_type, time_unit)
    return (min(first if first_year is None else first_year, last), last)


def year_ranges(years: Iterable[int]) -> tuple[YearRange, ...]:
    """Return years as ranges of consecutive years, in order."""
    ranges: list[YearRange] = []
    for year in sorted(set(years)):
        if ranges and year == ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], year)
        else:
            ranges.append((year, year))
    return tuple(ranges)


def series_label(
    coverage: VariableCoverage,
    years: Iterable[SeriesYear],
    *,
    known: Sequence[DateRange],
    time_unit: TimeUnit,
    year_type: YearType,
    span: YearRange | None,
) -> SeriesLabel:
    """Return the label of a variable in the range of years R (SPEC 4.8.4).

    Parameters
    ----------
    coverage : VariableCoverage
        The variable's first and last unit with a value and its gaps: the
        longest gap comes from them.
    years : Iterable[SeriesYear]
        The variable's years (``series_years``); those of other year types
        are ignored, and a year without one knows no unit.
    known : Sequence[DateRange]
        The known periods: the station's own, else the version's.
    time_unit : TimeUnit
        The unit of the dataset's series.
    year_type : YearType
        The numbering of R (hydrological only for half-year characteristics).
    span : tuple[int, int] or None
        R, first and last year; ``None``: no year is known.

    Returns
    -------
    SeriesLabel
        The label; its ``only`` is left empty (the station's other
        variables decide it).
    """
    if span is None:
        return SeriesLabel(state="unknown", year_type=year_type, span=None)
    rows = {year.year: year for year in years if year.year_type == year_type}
    first, last = span
    known_years: list[int] = []
    unknown_years: list[int] = []
    for year in range(first, last + 1):
        row = rows.get(year)
        if row is not None and 0 < row.units == row.known:
            known_years.append(year)
        else:
            unknown_years.append(year)
    unknown = year_ranges(unknown_years)
    if not known_years:
        return SeriesLabel(
            state="unknown", year_type=year_type, span=span, unknown_years=unknown
        )
    bounds = (known_years[0], known_years[-1])
    valued_years = [year for year in known_years if rows[year].with_value > 0]
    if not valued_years:
        return SeriesLabel(
            state="no_data",
            year_type=year_type,
            span=span,
            known=bounds,
            unknown_years=unknown,
        )
    valued = (valued_years[0], valued_years[-1])
    units = with_value = complete_years = 0
    for year in range(valued[0], valued[1] + 1):
        if (row := rows.get(year)) is not None:
            units += row.known
            with_value += row.with_value
            if row.units == row.known == row.with_value:
                complete_years += 1
    gaps = units - with_value
    runs = _gap_intervals(coverage, known, time_unit, year_type, valued)
    longest = max(runs, key=lambda run: run[1] - run[0], default=None)
    if valued != bounds:
        state: SeriesState = "partial"
    else:
        state = "gaps" if gaps else "continuous"
    return SeriesLabel(
        state=state,
        year_type=year_type,
        span=span,
        known=bounds,
        valued=valued,
        units=units,
        with_value=with_value,
        percent=min(99, -(-100 * gaps // units)) if gaps else 0,
        below_one=0 < 100 * gaps < units,
        longest_gap=None if longest is None else gap_run(longest, time_unit),
        gap_count=len(runs),
        long_gaps=sum(1 for run in runs if _days(run, time_unit) > LONG_GAP_DAYS),
        gap_runs=tuple(runs),
        complete_years=complete_years,
        unknown_years=unknown,
    )


def _gap_intervals(
    coverage: VariableCoverage,
    known: Sequence[DateRange],
    time_unit: TimeUnit,
    year_type: YearType,
    years: YearRange,
) -> list[Interval]:
    """Return the runs of known units without a value in a range of years."""
    known_units = intervals(known, time_unit)
    window = [
        (
            year_span(years[0], year_type, time_unit)[0],
            year_span(years[1], year_type, time_unit)[1],
        )
    ]
    return subtract(
        intersect(known_units, window),
        value_intervals(coverage, known_units, time_unit),
    )


def gap_run(run: Interval, time_unit: TimeUnit) -> GapRun:
    """Return a run of units as its first and last day and its units."""
    start, end = run
    return GapRun(
        start=day_of(start, time_unit),
        end=day_of(end + 1, time_unit) - timedelta(days=1),
        units=end - start + 1,
    )


def _days(run: Interval, time_unit: TimeUnit) -> int:
    """Return the days a run of units spans."""
    start, end = run
    return (day_of(end + 1, time_unit) - day_of(start, time_unit)).days
