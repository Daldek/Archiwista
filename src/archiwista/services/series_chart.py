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

A series of monthly statistics is drawn per variable (``unit_sources``): a
month's minimum, mean and maximum as the provider published them are its
least, mean and greatest value, and an interval's are the least minimum, the
mean of the means and the greatest maximum of its months; the label and the
known span are the mean's. Half-year characteristics are never a line: their
annual chart (``annual_chart``, A-ADR-051) gives per hydrological year the
greater of the winter and summer maxima and the lesser of their minima, with
the dates and occurrences of the half that holds each (of both, joined, when
they are equal) and the half without a value of an incomplete year. That is
all Archiwista finds in them: no mean and no other statistic, and nothing of
it is stored.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Self

from archiwista.api.models_stations import (
    AnnualExtreme,
    AnnualPoint,
    ChartChoiceVariable,
    ChartMarker,
    ChartPoint,
    ChartResolution,
    ChartVariable,
    GapSpan,
    HalfYear,
    StationChart,
    StationChartChoice,
)
from archiwista.index import CoverageVariable, StationCoverage
from archiwista.index.series import (
    GapRun,
    Interval,
    day_of,
    gap_run,
    hydrological_year,
    merge,
    subtract,
    unit_of,
)
from archiwista.sources import (
    DateRange,
    Extreme,
    SeriesValues,
    SeriesValuesAdapter,
    Statistic,
    TimeUnit,
)

# The halves of a hydrological year whose extremes give the year's (A-ADR-051).
_HALVES: tuple[HalfYear, ...] = ("winter", "summer")
# The unit of half-year characteristics: one a hydrological year and key.
_HALF_YEAR: TimeUnit = "half_year"
# The order of the charts of a station, and of the series a chart prefers:
# days, months, then the annual charts of half-year characteristics.
CHART_ORDER: Mapping[TimeUnit, int] = {"day": 0, "month": 1, "half_year": 2}

type Statistics = Mapping[str, Mapping[Statistic, str]]


@dataclass(frozen=True, slots=True)
class ChartRange:
    """The units of a chart: the first and last one, and the units of a point.

    Units are counted as the index counts them (``unit_of``): a day is its
    ordinal, a month ``year * 12 + month - 1``, a hydrological year (of
    half-year characteristics) its number.
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


@dataclass(frozen=True, slots=True)
class ChartSource:
    """A variable of a chart at its series' units and the variables it reads.

    A variable of days reads its own value, its least, mean and greatest
    (``own``). A variable whose monthly statistics a series holds reads them
    as the provider published them: ``least`` its minimum (``Q_min``),
    ``line`` its mean (``Q_mean``), whose label gives the bands and whose
    known span the default range, and ``greatest`` its maximum (``Q_max``).
    """

    key: str
    line: CoverageVariable
    least: CoverageVariable
    greatest: CoverageVariable

    @classmethod
    def own(cls, variable: CoverageVariable) -> Self:
        """Return a variable read as itself (a day's value)."""
        return cls(variable.key, variable, variable, variable)

    @property
    def own_value(self) -> bool:
        """Return whether it reads a value of its own (a day's), not statistics."""
        return self.least.key == self.line.key == self.greatest.key

    @property
    def held(self) -> tuple[CoverageVariable, ...]:
        """Return the variables of the series it reads, each once."""
        return tuple({item.key: item for item in self.read}.values())

    @property
    def read(self) -> tuple[CoverageVariable, CoverageVariable, CoverageVariable]:
        """Return its least, mean and greatest variable, in that order."""
        return (self.least, self.line, self.greatest)


@dataclass(frozen=True, slots=True)
class AnnualSource:
    """A variable of an annual chart and the half-year characteristics it reads.

    ``maximum`` and ``minimum`` name its half-year maximum and minimum
    (``Q_max``, ``Q_min``); ``labels`` are their variables of the winter and
    summer half-years the series holds (``Q_max@winter``, ...), whose gaps
    and known spans the chart takes.
    """

    key: str
    unit: str
    maximum: str
    minimum: str
    labels: tuple[CoverageVariable, ...]


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
    values: Iterable[SeriesValues],
    variable: str,
    span: ChartRange,
    *,
    least: str | None = None,
    greatest: str | None = None,
) -> tuple[list[ChartPoint], list[ChartMarker]]:
    """Return a variable's points in a range and its accumulated sums.

    Each point is a unit, or an interval of ``span.interval`` units from the
    range's first, with the least, mean and greatest value of its units; an
    accumulated sum is a marker of its day and no value of it. ``least`` and
    ``greatest`` name the variables of a unit's least and greatest value when
    they are not ``variable`` itself, whose values are then the means (a
    month's minimum, mean and maximum).
    """
    low_name = variable if least is None else least
    high_name = variable if greatest is None else greatest
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
        found = item.values
        value = found.get(variable)
        smallest = value if low_name == variable else found.get(low_name)
        largest = value if high_name == variable else found.get(high_name)
        if value is None and smallest is None and largest is None:
            continue
        unit = unit_of(item.start, time_unit)
        if unit < first or unit > last:
            continue
        if value is not None and variable in item.accumulated:
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
        if smallest is not None:
            known = low[index]
            if known is None or smallest < known:
                low[index] = smallest
        if largest is not None:
            known = high[index]
            if known is None or largest > known:
                high[index] = largest
        if value is not None:
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


def unit_sources(
    series: StationCoverage, statistics: Statistics
) -> dict[str, ChartSource]:
    """Return the variables a chart of a series at its own units draws, by name.

    A series of days draws each of its variables; one of monthly statistics
    each variable whose minimum, mean and maximum it holds (``statistics``,
    the producer's ``statistics_of`` of its dataset); half-year
    characteristics none (their chart is annual: ``annual_sources``).
    """
    if series.time_unit == "day":
        return {item.key: ChartSource.own(item) for item in series.variables}
    if series.time_unit != "month":
        return {}
    held = {item.key: item for item in series.variables}
    found: dict[str, ChartSource] = {}
    for name, named in statistics.items():
        least = held.get(named["min"])
        line = held.get(named["mean"])
        greatest = held.get(named["max"])
        if least is not None and line is not None and greatest is not None:
            found[name] = ChartSource(name, line, least, greatest)
    return found


def annual_sources(
    series: StationCoverage, statistics: Statistics
) -> dict[str, AnnualSource]:
    """Return the variables an annual chart of half-year characteristics draws.

    Each variable whose maximum or minimum of a winter or summer half-year the
    series holds, by name; none for a series of another unit.
    """
    if series.time_unit != _HALF_YEAR:
        return {}
    found: dict[str, AnnualSource] = {}
    for name, named in statistics.items():
        extremes = (named["max"], named["min"])
        labels = tuple(
            item
            for item in series.variables
            if item.variable in extremes and item.period in _HALVES
        )
        if labels:
            found[name] = AnnualSource(
                name, labels[0].unit, named["max"], named["min"], labels
            )
    return found


def chart_choices(
    found: Iterable[StationCoverage], statistics: Callable[[str], Statistics]
) -> list[StationChartChoice]:
    """Return the charts a station's series give: days, months, then annual ones.

    A series of days offers each of its variables; one of monthly statistics
    and half-year characteristics (an annual chart) the variables with a
    value only. A series without a variable to draw is left out.
    ``statistics`` is the producer's ``statistics_of``.
    """
    choices: list[StationChartChoice] = []
    for series in sorted(found, key=lambda item: CHART_ORDER[item.time_unit]):
        named = statistics(series.dataset)
        resolution: ChartResolution = "unit"
        held: list[tuple[str, str, Sequence[CoverageVariable]]]
        if series.time_unit == _HALF_YEAR:
            resolution = "annual"
            held = [
                (source.key, source.unit, source.labels)
                for source in annual_sources(series, named).values()
            ]
        else:
            held = [
                (source.key, source.line.unit, source.held)
                for source in unit_sources(series, named).values()
            ]
        variables = [
            _choice_variable(key, unit, read, series.time_unit)
            for key, unit, read in held
        ]
        if series.time_unit != "day":
            variables = [item for item in variables if item.first is not None]
        if variables:
            choices.append(
                StationChartChoice(
                    dataset=series.dataset,
                    time_unit=series.time_unit,
                    resolution=resolution,
                    variables=variables,
                )
            )
    return choices


def annual_points(
    records: Iterable[SeriesValues], source: AnnualSource, span: ChartRange
) -> list[AnnualPoint]:
    """Return the maximum and minimum of each hydrological year of a range.

    ``records`` are the station's half-year characteristics: the maximum is
    the greater of the winter and summer maxima and the minimum the lesser of
    their minima, with the dates and occurrences of the half that holds it
    (of both halves when they are equal: the earliest start, the latest end
    and the occurrences added) and the half without a value (``partial``).
    """
    halves: dict[tuple[int, str], SeriesValues] = {}
    for record in records:
        if record.period in _HALVES:
            year = hydrological_year(record.start)
            if span.first <= year <= span.last:
                halves[(year, record.period)] = record
    points: list[AnnualPoint] = []
    for year in range(span.first, span.last + 1):
        held = [(half, halves.get((year, half))) for half in _HALVES]
        points.append(
            {
                "t": day_of(year, _HALF_YEAR),
                "year": year,
                "max": _annual_extreme(held, source.maximum, greatest=True),
                "min": _annual_extreme(held, source.minimum, greatest=False),
            }
        )
    return points


def annual_gaps(source: AnnualSource, points: Sequence[AnnualPoint]) -> list[Interval]:
    """Return the years of an annual chart without a value that its labels count.

    A year is a gap of the variable when a label of its half-year maxima or
    minima counts it as one (known, without a value) and neither half gives
    it a maximum or a minimum.
    """
    runs = merge(run for label in source.labels for run in label.label.gap_runs)
    valued = merge(
        (point["year"], point["year"])
        for point in points
        if point["max"] is not None or point["min"] is not None
    )
    return subtract(runs, valued)


def station_chart(
    adapter: SeriesValuesAdapter,
    root: Path,
    series: StationCoverage,
    variables: Sequence[ChartSource],
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
    variables : Sequence[ChartSource]
        One or two variables of the series, each with the variable whose
        label (gap runs) gives the bands and known periods the range.
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
    known = known_span(item.line for item in variables)
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
                variables=list(
                    dict.fromkeys(
                        held.variable for item in variables for held in item.read
                    )
                ),
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
            **_chart_fields(series, span, "unit", freshness),
            "variables": [
                _chart_variable(values, item, span, extremes.get(item.key, ()))
                for item in variables
            ],
        }
    )


def annual_chart(
    adapter: SeriesValuesAdapter,
    root: Path,
    series: StationCoverage,
    variables: Sequence[AnnualSource],
    *,
    start: date | None,
    end: date | None,
    freshness: Mapping[str, Any],
) -> StationChart:
    """Read a station's half-year characteristics and return the annual chart.

    A point a hydrological year from the year of ``start`` to that of
    ``end``, by default the variables' known span: its maximum and minimum
    found in the winter and summer half-years (``annual_points``). For
    display only, never stored (A-ADR-051).

    Raises
    ------
    NotFoundError, SourceUnavailableError, ProducerError
        As ``SeriesValuesAdapter.read_values``.
    """
    known = known_span(label for item in variables for label in item.labels)
    low = known[0] if start is None and known is not None else start
    high = known[1] if end is None and known is not None else end
    span = (
        ChartRange(_HALF_YEAR, hydrological_year(low), hydrological_year(high), 1)
        if low is not None and high is not None and low <= high
        else None
    )
    records: list[SeriesValues] = []
    if span is not None and variables:
        names = [name for item in variables for name in (item.maximum, item.minimum)]
        records = list(
            adapter.read_values(
                root,
                Path(series.series_version),
                station=series.code,
                variables=list(dict.fromkeys(names)),
                start=span.start,
                end=span.end,
            )
        )
    charted: list[ChartVariable] = []
    for item in variables:
        points = [] if span is None else annual_points(records, item, span)
        gaps = [] if span is None else chart_gaps(annual_gaps(item, points), span)
        charted.append(
            ChartVariable(
                key=item.key,
                variable=item.key,
                unit=item.unit,
                points=points,
                gaps=[_gap_span(gap) for gap in gaps],
                markers=[],
            )
        )
    return StationChart.model_validate(
        {**_chart_fields(series, span, "annual", freshness), "variables": charted}
    )


def _chart_fields(
    series: StationCoverage,
    span: ChartRange | None,
    resolution: ChartResolution,
    freshness: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the fields of a chart but its variables."""
    return {
        "store": series.store,
        "provider": series.provider,
        "code": series.code,
        "dataset": series.dataset,
        "kind": series.kind,
        "time_unit": series.time_unit,
        "year_type": series.year_type,
        "resolution": resolution,
        "derived": "annual_extremes" if resolution == "annual" else None,
        "series": series.series,
        "series_version": series.series_version,
        "file": series.file,
        "sha256": series.sha256,
        "from": None if span is None else span.start,
        "to": None if span is None else span.end,
        "units": 0 if span is None else span.units,
        "interval": 1 if span is None else span.interval,
        "license": series.license,
        "attribution": series.attribution,
        **freshness,
    }


def _chart_variable(
    values: Sequence[SeriesValues],
    source: ChartSource,
    span: ChartRange | None,
    extremes: Sequence[ChartMarker],
) -> ChartVariable:
    """Return a variable's points, gaps and markers in a range (none without one)."""
    points: list[ChartPoint] = []
    markers: list[ChartMarker] = []
    gaps: list[GapSpan] = []
    line = source.line
    if span is not None:
        points, markers = chart_values(
            values,
            line.variable,
            span,
            least=source.least.variable,
            greatest=source.greatest.variable,
        )
        gaps = [_gap_span(gap) for gap in chart_gaps(line.label.gap_runs, span)]
    return ChartVariable(
        key=source.key,
        variable=line.variable if source.own_value else source.key,
        unit=line.unit,
        points=points,
        gaps=gaps,
        markers=sorted([*markers, *extremes], key=lambda marker: marker["t"]),
    )


def _gap_span(gap: GapRun) -> GapSpan:
    """Return the model of a run of gaps."""
    return GapSpan.model_validate(
        {"from": gap.start, "to": gap.end, "units": gap.units}
    )


def _extremes(
    adapter: SeriesValuesAdapter,
    root: Path,
    series: StationCoverage,
    variables: Sequence[ChartSource],
    characteristics: StationCoverage | None,
    span: ChartRange,
) -> dict[str, list[ChartMarker]]:
    """Return the published extremes of each variable within a range, by its key.

    The station's half-year characteristics are read once, with the
    characteristics of every variable that has extremes; a variable of
    monthly statistics has none (a chart mixes no sources).
    """
    if characteristics is None:
        return {}
    names = {
        item.key: adapter.extremes_of(series.dataset, item.line.variable)
        for item in variables
        if item.own_value
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
        key: extreme_markers(records, found, start=span.start, end=span.end)
        for key, found in names.items()
        if found
    }


def _annual_extreme(
    halves: Sequence[tuple[HalfYear, SeriesValues | None]],
    name: str,
    *,
    greatest: bool,
) -> AnnualExtreme | None:
    """Return a year's maximum (``greatest``) or minimum of a characteristic.

    ``halves`` are the year's winter and summer records (``None``: absent);
    ``None`` when neither half has a value.
    """
    valued = [
        (half, record, value)
        for half, record in halves
        if record is not None and (value := record.values.get(name)) is not None
    ]
    if not valued:
        return None
    pick = max if greatest else min
    best = pick(value for _, _, value in valued)
    holders = [(half, record) for half, record, value in valued if value == best]
    starts: list[datetime] = []
    ends: list[datetime] = []
    counts: list[int] = []
    for _, record in holders:
        first, last = record.extremes.get(name, (None, None))
        start, stop = first or last, last or first
        if start is not None and stop is not None:
            starts.append(start)
            ends.append(stop)
        count = record.occurrences.get(name)
        if count is not None:
            counts.append(count)
    found = {half for half, _, _ in valued}
    missing = [half for half, _ in halves if half not in found]
    return {
        "value": best,
        "start": min(starts).date() if starts else None,
        "end": max(ends).date() if ends else None,
        "occurrences": sum(counts) if len(counts) == len(holders) else None,
        "halves": [half for half, _ in holders],
        "partial": missing[0] if missing else None,
    }


def _choice_variable(
    key: str, unit: str, read: Sequence[CoverageVariable], time_unit: TimeUnit
) -> ChartChoiceVariable:
    """Return a variable of a chart choice: its unit and days with a value.

    ``first`` is the first day of its first unit with a value and ``last`` the
    last day of its last one (a hydrological year of half-year
    characteristics), of any variable it reads.
    """
    firsts = [item.first for item in read if item.first is not None]
    lasts = [item.last for item in read if item.last is not None]
    first = min(firsts) if firsts else None
    last = max(lasts) if lasts else None
    return ChartChoiceVariable(
        key=key,
        unit=unit,
        first=None if first is None else day_of(unit_of(first, time_unit), time_unit),
        last=(
            None
            if last is None
            else day_of(unit_of(last, time_unit) + 1, time_unit) - timedelta(days=1)
        ),
    )
