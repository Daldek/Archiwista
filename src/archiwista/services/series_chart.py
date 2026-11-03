"""A station's series as a chart: values, or their least, mean and greatest (SPEC 6.7).

For display only (SPEC 5.7): nothing here goes into a set or the store. The
values come from the producer (``SeriesValuesAdapter.read_values``) and the
gaps from the index: they are the runs of gaps the variable's label counts
(``SeriesLabel.gap_runs``, the known units of its years y1 to y2 without a
value, SPEC 4.8.4), so a band is a gap of the label, and a unit without a
value outside them is no gap of it (not known, or outside y1 to y2). The
range is by default the variables' known span, so the label's longest gap
lies in it (ADR-045 erratum 1). A range of at most ``max_points`` units
gives each unit's value; a longer one is cut into intervals of
``ceil(units / max_points)`` units from its first, each with the least, mean
and greatest value it holds (``null`` for none: the line breaks, never
interpolated). Units are calendar units (days, months), so a unit the
station's file lacks is a unit without a value too. An accumulated sum is a
marker, never a value of its day; the extremes of the half-year
characteristics, as the provider published them with their dates, are
markers of the variable whose least and greatest values they are.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from archiwista.api.models_stations import (
    ChartMarker,
    ChartPoint,
    ChartVariable,
    GapSpan,
    StationChart,
)
from archiwista.index import CoverageVariable, StationCoverage
from archiwista.index.series import GapRun, Interval, day_of, gap_run, unit_of
from archiwista.sources import (
    DateRange,
    Extreme,
    SeriesValues,
    SeriesValuesAdapter,
    TimeUnit,
)


@dataclass(frozen=True, slots=True)
class ChartRange:
    """The units of a chart: the first and last one, and the units of a point.

    Units are counted as the index counts them (``unit_of``): a day is its
    ordinal, a month ``year * 12 + month - 1``.
    """

    time_unit: TimeUnit
    first: int
    last: int
    interval: int

    @property
    def units(self) -> int:
        """Return the units of the range."""
        return self.last - self.first + 1

    @property
    def start(self) -> date:
        """Return the first day of the range."""
        return day_of(self.first, self.time_unit)

    @property
    def end(self) -> date:
        """Return the last day of the range."""
        return day_of(self.last + 1, self.time_unit) - timedelta(days=1)


def chart_range(
    time_unit: TimeUnit, start: date, end: date, max_points: int
) -> ChartRange:
    """Return the units from ``start`` to ``end`` and the units of a point.

    The units of a point are ``ceil(units / max_points)``: 1 while the range
    has at most ``max_points`` units.
    """
    first, last = unit_of(start, time_unit), unit_of(end, time_unit)
    units = last - first + 1
    return ChartRange(time_unit, first, last, -(-units // max_points))


def chart_values(
    values: Iterable[SeriesValues], variable: str, span: ChartRange
) -> tuple[list[ChartPoint], list[ChartMarker]]:
    """Return a variable's points in a range and its accumulated sums.

    Each point is a unit, or an interval of ``span.interval`` units from the
    range's first, with the least, mean and greatest value of its units; an
    accumulated sum is a marker of its day and no value of it.
    """
    count = (span.units + span.interval - 1) // span.interval
    low: list[float | None] = [None] * count
    high: list[float | None] = [None] * count
    total = [0.0] * count
    seen = [0] * count
    accumulated: list[ChartMarker] = []
    first, last, interval, time_unit = (
        span.first,
        span.last,
        span.interval,
        span.time_unit,
    )
    for item in values:
        value = item.values.get(variable)
        if value is None:
            continue
        unit = unit_of(item.start, time_unit)
        if unit < first or unit > last:
            continue
        if variable in item.accumulated:
            accumulated.append(
                {
                    "t": item.start,
                    "kind": "accumulated",
                    "value": value,
                    "period": None,
                    "end": None,
                }
            )
            continue
        index = (unit - first) // interval
        least, greatest = low[index], high[index]
        if least is None or value < least:
            low[index] = value
        if greatest is None or value > greatest:
            high[index] = value
        total[index] += value
        seen[index] += 1
    points: list[ChartPoint] = [
        {
            "t": day_of(first + index * interval, time_unit),
            "min": low[index],
            "mean": round(total[index] / seen[index], 6) if seen[index] else None,
            "max": high[index],
        }
        for index in range(count)
    ]
    return points, accumulated


def chart_gaps(runs: Iterable[Interval], span: ChartRange) -> list[GapRun]:
    """Return the runs of gaps of a variable's label within a range, cut at its ends.

    ``runs`` are ``SeriesLabel.gap_runs``, in the units of the range.
    """
    found: list[GapRun] = []
    for first, last in runs:
        low, high = max(first, span.first), min(last, span.last)
        if low <= high:
            found.append(gap_run((low, high), span.time_unit))
    return found


def known_span(variables: Iterable[CoverageVariable]) -> DateRange | None:
    """Return the first and last known day of variables: a chart's default range.

    Every unit their labels count lies in it, so their longest gaps do too
    (ADR-045 erratum 1); a first or last value outside the known periods
    widens it. ``None`` when no variable has a known period or a value.
    """
    days: list[date] = []
    for item in variables:
        days.extend(day for period in item.known for day in period)
        days.extend(day for day in (item.first, item.last) if day is not None)
    return (min(days), max(days)) if days else None


def extreme_markers(
    records: Iterable[SeriesValues],
    names: Mapping[Extreme, str],
    *,
    start: date,
    end: date,
) -> list[ChartMarker]:
    """Return the published extremes of a variable dated within a range.

    ``records`` are a station's half-year characteristics and ``names`` the
    characteristic of each extreme of the variable (``extremes_of``). An
    extreme without a date or a value is left out: its place is unknown.
    """
    found: list[ChartMarker] = []
    for record in records:
        for kind, name in names.items():
            value = record.values.get(name)
            first, last = record.extremes.get(name, (None, None))
            moment = first if first is not None else last
            if value is None or moment is None or not start <= moment.date() <= end:
                continue
            found.append(
                {
                    "t": moment.date(),
                    "kind": kind,
                    "value": value,
                    "period": record.period,
                    "end": None if last is None else last.date(),
                }
            )
    return found


def station_chart(
    adapter: SeriesValuesAdapter,
    root: Path,
    series: StationCoverage,
    variables: Sequence[CoverageVariable],
    *,
    start: date | None,
    end: date | None,
    max_points: int,
    characteristics: StationCoverage | None,
    freshness: Mapping[str, Any],
) -> StationChart:
    """Read a station's series of a dataset and return it as a chart.

    Parameters
    ----------
    adapter : SeriesValuesAdapter
        The producer of the series.
    root : Path
        The store root of the producer.
    series : StationCoverage
        The station's series in the index: its current version and file.
    variables : Sequence[CoverageVariable]
        One or two variables of the series, each with its label (whose gap
        runs are the bands) and known periods.
    start, end : date or None
        The range; a bound left out is the variables' known span's
        (``known_span``), else the series' first or last unit.
    max_points : int
        The most points of a variable.
    characteristics : StationCoverage or None
        The station's series of the dataset's half-year characteristics, when
        the index holds one: its extremes become markers.
    freshness : Mapping[str, Any]
        The ``stale`` and ``stale_stores`` fields of the answer.

    Raises
    ------
    NotFoundError, SourceUnavailableError, ProducerError
        As ``SeriesValuesAdapter.read_values``.
    """
    known = known_span(variables)
    low = known[0] if start is None and known is not None else start
    high = known[1] if end is None and known is not None else end
    values: list[SeriesValues] = []
    # A bound asked beyond the other one's default leaves no unit to read.
    if low is None or high is None or low <= high:
        values = list(
            adapter.read_values(
                root,
                Path(series.series_version),
                station=series.code,
                variables=[item.variable for item in variables],
                start=low,
                end=high,
            )
        )
    if values:
        low = values[0].start if low is None else low
        high = values[-1].start if high is None else high
    span = (
        chart_range(series.time_unit, low, high, max_points)
        if low is not None and high is not None and low <= high
        else None
    )
    extremes = (
        {}
        if span is None
        else _extremes(adapter, root, series, variables, characteristics, span)
    )
    return StationChart.model_validate(
        {
            "store": series.store,
            "provider": series.provider,
            "code": series.code,
            "dataset": series.dataset,
            "kind": series.kind,
            "time_unit": series.time_unit,
            "year_type": series.year_type,
            "series": series.series,
            "series_version": series.series_version,
            "file": series.file,
            "sha256": series.sha256,
            "from": None if span is None else span.start,
            "to": None if span is None else span.end,
            "units": 0 if span is None else span.units,
            "interval": 1 if span is None else span.interval,
            "variables": [
                _chart_variable(values, item, span, extremes.get(item.variable, ()))
                for item in variables
            ],
            "license": series.license,
            "attribution": series.attribution,
            **freshness,
        }
    )


def _chart_variable(
    values: Sequence[SeriesValues],
    variable: CoverageVariable,
    span: ChartRange | None,
    extremes: Sequence[ChartMarker],
) -> ChartVariable:
    """Return a variable's points, gaps and markers in a range (none without one)."""
    points: list[ChartPoint] = []
    markers: list[ChartMarker] = []
    gaps: list[GapSpan] = []
    if span is not None:
        points, markers = chart_values(values, variable.variable, span)
        gaps = [
            GapSpan.model_validate(
                {"from": gap.start, "to": gap.end, "units": gap.units}
            )
            for gap in chart_gaps(variable.label.gap_runs, span)
        ]
    return ChartVariable(
        key=variable.key,
        variable=variable.variable,
        unit=variable.unit,
        points=points,
        gaps=gaps,
        markers=sorted([*markers, *extremes], key=lambda marker: marker["t"]),
    )


def _extremes(
    adapter: SeriesValuesAdapter,
    root: Path,
    series: StationCoverage,
    variables: Sequence[CoverageVariable],
    characteristics: StationCoverage | None,
    span: ChartRange,
) -> dict[str, list[ChartMarker]]:
    """Return the published extremes of each variable within a range, by variable.

    The station's half-year characteristics are read once, with the
    characteristics of every variable that has extremes.
    """
    if characteristics is None:
        return {}
    names = {
        item.variable: adapter.extremes_of(series.dataset, item.variable)
        for item in variables
    }
    wanted = sorted({name for found in names.values() for name in found.values()})
    if not wanted:
        return {}
    records = list(
        adapter.read_values(
            root,
            Path(characteristics.series_version),
            station=characteristics.code,
            variables=wanted,
        )
    )
    return {
        variable: extreme_markers(records, found, start=span.start, end=span.end)
        for variable, found in names.items()
        if found
    }
