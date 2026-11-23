"""Weeks, hours and the months of one series (SPEC 4.8.4, A-ADR-059).

A week runs from Monday to Sunday, is named by its Monday and belongs to the
year of its Monday, so the last week of a year may end in the next one. An
hour is a UTC hour; a date alone is its first hour, and a range of days ends
with the last hour of its last day. ``join_months`` makes the versions of a
series kept one per month one series: a month whose source publishes every
station counts a station it lacks as known without a value, one of per-station
files leaves it unknown.
"""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from archiwista.index.series import (
    day_of,
    join_months,
    last_day_of,
    last_unit_of,
    unit_of,
    year_of,
    year_span,
)
from archiwista.sources import (
    DateRange,
    SeriesListing,
    StationSeries,
    VariableCoverage,
    YearType,
)


def _hour(month: int, day: int, hour: int = 0) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=UTC)


def test_series_unit_of_a_week_runs_from_its_monday_to_its_sunday() -> None:
    """Monday 24 XII 2012 to Sunday 30 XII 2012 is one week, named by its Monday."""
    monday, sunday = date(2012, 12, 24), date(2012, 12, 30)

    week = unit_of(monday, "week")

    assert unit_of(sunday, "week") == week
    assert unit_of(monday - timedelta(days=1), "week") == week - 1
    assert unit_of(sunday + timedelta(days=1), "week") == week + 1
    assert (day_of(week, "week"), last_day_of(week, "week")) == (monday, sunday)


@pytest.mark.parametrize(
    ("year", "year_type", "first", "last", "weeks"),
    [
        # 1 I 2012 is a Sunday: its week is 2011's; 31 XII 2012, a Monday, starts
        # the last week of 2012, which ends on 6 I 2013.
        (2012, "calendar", date(2012, 1, 2), date(2013, 1, 6), 53),
        # 1 I 2013 is a Tuesday: the week of 31 XII 2012 is 2012's.
        (2013, "calendar", date(2013, 1, 7), date(2014, 1, 5), 52),
        # 1 XI 2012 is a Thursday: the first Monday of the year is 5 XI 2012.
        (2013, "hydrological", date(2012, 11, 5), date(2013, 11, 3), 52),
    ],
)
def test_series_year_span_of_weeks_holds_the_weeks_of_its_mondays(
    year: int, year_type: YearType, first: date, last: date, weeks: int
) -> None:
    """A year's weeks are those whose Monday lies in it."""
    start, end = year_span(year, year_type, "week")

    assert (day_of(start, "week"), last_day_of(end, "week")) == (first, last)
    assert end - start + 1 == weeks
    assert year_of(start, year_type, "week") == year
    assert year_of(end, year_type, "week") == year
    assert year_of(start - 1, year_type, "week") == year - 1
    assert year_of(end + 1, year_type, "week") == year + 1


def test_series_unit_of_an_hour_is_its_utc_hour() -> None:
    """An aware time counts in UTC, a date alone is its first hour."""
    morning = unit_of(_hour(9, 15, 6), "hour")

    assert unit_of(date(2026, 9, 15), "hour") == morning - 6
    assert unit_of(_hour(9, 14, 23), "hour") == morning - 7
    warsaw = timezone(timedelta(hours=2))
    assert unit_of(datetime(2026, 9, 15, 8, tzinfo=warsaw), "hour") == morning
    assert unit_of(datetime(2026, 9, 15, 6), "hour") == morning
    assert last_unit_of(date(2026, 9, 15), "hour") == morning + 17
    assert last_unit_of(_hour(9, 15, 6), "hour") == morning


def test_series_day_of_an_hour_is_its_start_in_utc() -> None:
    """The first and the last day of an hour are its start, an aware UTC time."""
    hour = unit_of(_hour(9, 15, 6), "hour")

    start = day_of(hour, "hour")

    assert isinstance(start, datetime)
    assert (start, start.tzinfo) == (_hour(9, 15, 6), UTC)
    assert last_day_of(hour, "hour") == _hour(9, 15, 6)


@pytest.mark.parametrize(
    ("year", "year_type", "first", "last", "hours"),
    [
        (2026, "calendar", datetime(2026, 1, 1), datetime(2026, 12, 31, 23), 8760),
        (2024, "calendar", datetime(2024, 1, 1), datetime(2024, 12, 31, 23), 8784),
        (
            2026,
            "hydrological",
            datetime(2025, 11, 1),
            datetime(2026, 10, 31, 23),
            8760,
        ),
    ],
)
def test_series_year_span_of_hours_runs_to_the_last_hour_of_its_last_day(
    year: int, year_type: YearType, first: datetime, last: datetime, hours: int
) -> None:
    """A year of hours from its first hour to the last one of 31 XII (31 X)."""
    start, end = year_span(year, year_type, "hour")

    assert (day_of(start, "hour"), day_of(end, "hour")) == (
        first.replace(tzinfo=UTC),
        last.replace(tzinfo=UTC),
    )
    assert end - start + 1 == hours
    assert year_of(end, year_type, "hour") == year
    assert year_of(end + 1, year_type, "hour") == year + 1


def _month(month: int) -> DateRange:
    """Return the days of a month of 2026."""
    following = date(2026, month + 1, 1) if month < 12 else date(2027, 1, 1)
    return date(2026, month, 1), following - timedelta(days=1)


def _station(code: str, month: int, *, own: bool) -> StationSeries:
    """Return a station with H in every hour of a month of 2026."""
    first, last = _month(month)
    hours = (last - first).days * 24 + 24
    return StationSeries(
        code=code,
        file=f"series/versions/subdaily/2026-{month:02d}/{code}.parquet",
        sha256=f"{code}-{month}",
        rows=hours,
        variables=(
            VariableCoverage(
                key="H",
                variable="H",
                unit="cm",
                period=None,
                first=_hour(month, 1),
                last=_hour(month, last.day, 23),
                with_value=hours,
                accumulated=0,
                gaps=(),
            ),
        ),
        periods=(_month(month),) if own else None,
    )


def _listing(month: int, codes: tuple[str, ...], *, own: bool) -> SeriesListing:
    """Return a month's version of an hourly series of the stations ``codes``."""
    return SeriesListing(
        dataset="pl.imgw.hydro_subdaily",
        provider="IMGW",
        kind="hydro",
        time_unit="hour",
        year_type="hydrological",
        first_year=2008,
        periods=(_month(month),),
        stations=tuple(_station(code, month, own=own) for code in codes),
        month=f"2026-{month:02d}",
    )


def _months(*, own: bool) -> list[SeriesListing]:
    """Return September to November, in no order.

    A is in September and October, B in September and November.
    """
    return [
        _listing(11, ("B",), own=own),
        _listing(9, ("A", "B"), own=own),
        _listing(10, ("A",), own=own),
    ]


def test_series_join_months_counts_a_country_wide_absence_as_a_gap() -> None:
    """B is not in October of a source of every station: a gap of 744 hours."""
    joined = join_months(_months(own=False))

    stations = {station.code: station for station in joined.stations}
    (h,) = stations["B"].variables
    assert joined.month is None
    assert joined.periods == ((date(2026, 9, 1), date(2026, 11, 30)),)
    assert [station.code for station in joined.stations] == ["A", "B"]
    assert stations["B"].periods is None
    assert (h.first, h.last) == (_hour(9, 1), _hour(11, 30, 23))
    assert h.gaps == ((_hour(10, 1), _hour(10, 31, 23)),)
    assert h.with_value == 720 + 720
    # A's November is after its last value: known, but no gap.
    assert stations["A"].variables[0].gaps == ()


def test_series_join_months_keeps_a_per_station_absence_unknown() -> None:
    """B is not in October of per-station files: October stays unknown, no gap."""
    joined = join_months(_months(own=True))

    stations = {station.code: station for station in joined.stations}
    (h,) = stations["B"].variables
    assert stations["B"].periods == (_month(9), _month(11))
    assert stations["A"].periods == ((date(2026, 9, 1), date(2026, 10, 31)),)
    assert (h.first, h.last, h.gaps) == (_hour(9, 1), _hour(11, 30, 23), ())
    assert h.with_value == 1440


def test_series_join_months_takes_a_stations_file_of_its_latest_month() -> None:
    """A's file is October's, B's November's, whatever the order of the months."""
    joined = join_months(_months(own=False))

    files = {item.code: (item.file, item.sha256) for item in joined.stations}
    assert files == {
        "A": ("series/versions/subdaily/2026-10/A.parquet", "A-10"),
        "B": ("series/versions/subdaily/2026-11/B.parquet", "B-11"),
    }
