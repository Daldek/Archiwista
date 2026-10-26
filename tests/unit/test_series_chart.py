"""The chart of a station's series on synthetic values (plan I8.4, SPEC 6.7).

Units are calendar units counted from the range's first; a longer range than
``max_points`` units is cut into intervals of ``ceil(units / max_points)``
units with the least, mean and greatest value of each, ``null`` without one
(never interpolated). The producer's gaps are cut at the range's ends, an
accumulated sum is a marker and no value, and the extremes of the half-year
characteristics are markers at the day the provider published.
"""

from collections.abc import Iterator, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path

from archiwista.index import CoverageVariable, StationCoverage
from archiwista.index.series import GapRun, SeriesLabel
from archiwista.services.series_chart import (
    chart_gaps,
    chart_range,
    chart_values,
    extreme_markers,
    station_chart,
)
from archiwista.sources import Extreme, SeriesValues

START = date(1950, 11, 1)


def _daily(values: Sequence[float | None], start: date = START) -> list[SeriesValues]:
    return [
        SeriesValues(start=start + timedelta(days=n), period=None, values={"Q": value})
        for n, value in enumerate(values)
    ]


def _variable(gaps: tuple[tuple[date, date], ...] = ()) -> CoverageVariable:
    label = SeriesLabel(state="gaps", year_type="hydrological", span=None)
    return CoverageVariable(
        key="Q", variable="Q", unit="m3/s", period=None, first=None, last=None,
        accumulated=0, years=(), label=label, gaps=gaps,
    )  # fmt: skip


def _series(variable: CoverageVariable, dataset: str) -> StationCoverage:
    return StationCoverage(
        store="dane", provider="IMGW-PIB", code="149190310", dataset=dataset,
        kind="hydro", time_unit="day", year_type="hydrological", span=None,
        file="s.parquet", series="2026-08-31", series_version=f"{dataset}.json",
        variables=(variable,),
    )  # fmt: skip


def test_27393_days_at_2000_points_are_intervals_of_14_days() -> None:
    """1957 points, each the least, mean and greatest of its 14 days."""
    values = _daily([float(n % 100) for n in range(27393)])
    span = chart_range("day", START, START + timedelta(days=27392), 2000)

    points, markers = chart_values(values, "Q", span)

    assert (span.units, span.interval, len(points)) == (27393, 14, 1957)
    assert points[0] == {"t": START, "min": 0.0, "mean": 6.5, "max": 13.0}
    assert points[-1]["t"] == START + timedelta(days=1956 * 14)
    assert points[-1]["max"] == float(27392 % 100)
    assert markers == []


def test_an_interval_of_only_gaps_has_no_value_and_a_short_gap_its_band() -> None:
    """``null`` for an interval without a value; a one-day gap stays a gap."""
    values = _daily([1.0, 2.0, None, 4.0, None, None, None, None, None, 10.0])
    span = chart_range("day", START, START + timedelta(days=9), 4)
    gaps = (
        (START + timedelta(days=2), START + timedelta(days=2)),
        (START + timedelta(days=4), START + timedelta(days=8)),
    )

    points, _ = chart_values(values, "Q", span)
    bands = chart_gaps(gaps, span)

    assert span.interval == 3
    assert [(p["min"], p["mean"], p["max"]) for p in points] == [
        (1.0, 1.5, 2.0),
        (4.0, 4.0, 4.0),
        (None, None, None),
        (10.0, 10.0, 10.0),
    ]
    assert bands == [
        GapRun(START + timedelta(days=2), START + timedelta(days=2), 1),
        GapRun(START + timedelta(days=4), START + timedelta(days=8), 5),
    ]


def test_each_day_is_its_own_point_and_a_missing_day_has_no_value() -> None:
    """A missing day and a day without a row are ``null``; the leap day counts."""
    start = date(2024, 2, 27)
    values = [
        SeriesValues(start=start, period=None, values={"Q": 1.0}),
        SeriesValues(start=date(2024, 2, 28), period=None, values={"Q": None}),
        SeriesValues(start=date(2024, 2, 29), period=None, values={"Q": 3.0}),
        SeriesValues(start=date(2024, 3, 2), period=None, values={"Q": 5.0}),
    ]
    span = chart_range("day", start, date(2024, 3, 2), 2000)

    points, _ = chart_values(values, "Q", span)

    assert (span.units, span.interval) == (5, 1)
    assert [(p["t"], p["mean"]) for p in points] == [
        (date(2024, 2, 27), 1.0),
        (date(2024, 2, 28), None),
        (date(2024, 2, 29), 3.0),
        (date(2024, 3, 1), None),
        (date(2024, 3, 2), 5.0),
    ]


def test_an_accumulated_sum_is_a_marker_and_no_value_of_its_day() -> None:
    """The sum of the days before it never enters a point's values."""
    values = [
        SeriesValues(start=START, period=None, values={"P": 2.0}),
        SeriesValues(
            start=START + timedelta(days=1),
            period=None,
            values={"P": 30.5},
            accumulated=frozenset({"P"}),
        ),
    ]
    span = chart_range("day", START, START + timedelta(days=1), 1)

    points, markers = chart_values(values, "P", span)

    assert points == [{"t": START, "min": 2.0, "mean": 2.0, "max": 2.0}]
    assert markers == [
        {
            "t": START + timedelta(days=1),
            "kind": "accumulated",
            "value": 30.5,
            "period": None,
            "end": None,
        }
    ]


def test_months_are_units_of_their_own_length() -> None:
    """A monthly series: a point a month, intervals counted in months."""
    values = [
        SeriesValues(
            start=date(2024, month, 1), period=None, values={"Q": float(month)}
        )
        for month in range(1, 13)
    ]
    span = chart_range("month", date(2024, 1, 1), date(2024, 12, 31), 5)

    points, _ = chart_values(values, "Q", span)

    assert (span.units, span.interval, span.end) == (12, 3, date(2024, 12, 31))
    assert [(p["t"], p["min"], p["max"]) for p in points] == [
        (date(2024, 1, 1), 1.0, 3.0),
        (date(2024, 4, 1), 4.0, 6.0),
        (date(2024, 7, 1), 7.0, 9.0),
        (date(2024, 10, 1), 10.0, 12.0),
    ]


def test_gaps_are_cut_at_the_ends_of_the_range() -> None:
    """A gap across an end keeps its part in the range; one outside is gone."""
    span = chart_range("day", date(2024, 1, 10), date(2024, 1, 20), 2000)
    gaps = (
        (date(2024, 1, 1), date(2024, 1, 4)),
        (date(2024, 1, 8), date(2024, 1, 11)),
        (date(2024, 1, 19), date(2024, 2, 3)),
    )

    assert chart_gaps(gaps, span) == [
        GapRun(date(2024, 1, 10), date(2024, 1, 11), 2),
        GapRun(date(2024, 1, 19), date(2024, 1, 20), 2),
    ]


def _half_year(
    start: date, period: str, maximum: float | None, at: datetime | None
) -> SeriesValues:
    return SeriesValues(
        start=start,
        period=period,
        values={"Q_min": 1.0, "Q_max": maximum},
        extremes={
            "Q_min": (datetime(start.year, start.month, 5), None),
            **({} if at is None else {"Q_max": (at, at + timedelta(days=1))}),
        },
    )


def test_published_extremes_are_markers_at_their_day_within_the_range() -> None:
    """An extreme outside the range, without a date or a value is left out."""
    records = [
        _half_year(date(2023, 11, 1), "winter", 40.0, datetime(2024, 3, 2, 6, 0)),
        _half_year(date(2024, 5, 1), "summer", 90.0, datetime(2024, 7, 9)),
        _half_year(date(2023, 11, 1), "annual", 90.0, datetime(2024, 7, 9)),
        _half_year(date(2024, 11, 1), "winter", None, datetime(2025, 1, 2)),
        _half_year(date(2025, 5, 1), "summer", 12.0, None),
    ]

    found = extreme_markers(
        records, {"max": "Q_max"}, start=date(2024, 1, 1), end=date(2025, 10, 31)
    )

    assert found == [
        {
            "t": date(2024, 3, 2),
            "kind": "max",
            "value": 40.0,
            "period": "winter",
            "end": date(2024, 3, 3),
        },
        {
            "t": date(2024, 7, 9),
            "kind": "max",
            "value": 90.0,
            "period": "summer",
            "end": date(2024, 7, 10),
        },
        {
            "t": date(2024, 7, 9),
            "kind": "max",
            "value": 90.0,
            "period": "annual",
            "end": date(2024, 7, 10),
        },
    ]


class _Producer:
    """A stand-in producer: a daily series and its half-year characteristics."""

    def __init__(self, daily: list[SeriesValues], half: list[SeriesValues]) -> None:
        self.read: dict[str, list[str]] = {}
        self._versions = {"pl.daily.json": daily, "pl.half.json": half}

    def read_values(
        self,
        root: Path,
        version: Path,
        *,
        station: str,
        variables: Sequence[str],
        start: date | None = None,
        end: date | None = None,
    ) -> Iterator[SeriesValues]:
        self.read[str(version)] = list(variables)
        return iter(self._versions[str(version)])

    def characteristics_dataset(self, dataset: str) -> str | None:
        return "pl.half"

    def extremes_of(self, dataset: str, variable: str) -> dict[Extreme, str]:
        return {"min": "Q_min", "max": "Q_max"} if variable == "Q" else {}


def test_a_chart_has_the_extremes_and_sums_of_its_range_by_day() -> None:
    """The characteristics are read once; markers of the range, by day."""
    daily = _daily([5.0] * 10, start=date(2024, 3, 1))
    daily[5] = SeriesValues(
        start=date(2024, 3, 6),
        period=None,
        values={"Q": 50.0},
        accumulated=frozenset({"Q"}),
    )
    half = [_half_year(date(2023, 11, 1), "winter", 40.0, datetime(2024, 3, 2))]
    producer = _Producer(daily, half)
    variable = _variable(gaps=((date(2024, 3, 4), date(2024, 3, 4)),))

    chart = station_chart(
        producer,
        Path("store"),
        _series(variable, "pl.daily"),
        [variable],
        start=None,
        end=None,
        max_points=2000,
        characteristics=_series(variable, "pl.half"),
        freshness={"stale": False, "stale_stores": []},
    )

    assert producer.read == {"pl.daily.json": ["Q"], "pl.half.json": ["Q_max", "Q_min"]}
    assert (str(chart.first), str(chart.last), chart.units) == (
        "2024-03-01",
        "2024-03-10",
        10,
    )
    (found,) = chart.variables
    assert [(m["t"], m["kind"]) for m in found.markers] == [
        (date(2024, 3, 2), "max"),
        (date(2024, 3, 6), "accumulated"),
    ]
    assert [(gap.first, gap.last, gap.units) for gap in found.gaps] == [
        (date(2024, 3, 4), date(2024, 3, 4), 1)
    ]
