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
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from archiwista.sources import DateRange, TimeUnit, VariableCoverage, YearType

type Interval = tuple[int, int]

YEAR_TYPES: tuple[YearType, ...] = ("hydrological", "calendar")
# The first month of the hydrological year (1 XI of the year before).
_HYDROLOGICAL_START = 11


@dataclass(frozen=True, slots=True)
class SeriesYear:
    """A year of a variable: its units, the known ones and those with a value.

    A year is known when every unit is (``known == units``); a full year has
    a value in every unit (``with_value == units``).
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
