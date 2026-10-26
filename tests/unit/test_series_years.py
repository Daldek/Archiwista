"""Each year of a variable, from its gap list and the known periods (SPEC 4.8.4).

``series_years`` counts a year in units of the series: days, months, or one
half-year characteristic per hydrological year (1 XI to 31 X), which has no
calendar year. The worked examples cross the boundaries a count can slip on:
a leap year, the turn of the hydrological year, a gap over a year's end and a
year without a known unit between two known ones.
"""

from datetime import date

import pytest

from archiwista.index.series import SeriesYear, series_years
from archiwista.sources import DateRange, TimeUnit, VariableCoverage


def _coverage(
    first: date | None, last: date | None, *gaps: DateRange, key: str = "Q"
) -> VariableCoverage:
    return VariableCoverage(
        key=key,
        variable=key.partition("@")[0],
        unit="m3/s",
        period=key.partition("@")[2] or None,
        first=first,
        last=last,
        with_value=0,
        accumulated=0,
        gaps=gaps,
    )


def _years(
    found: tuple[SeriesYear, ...], year_type: str
) -> list[tuple[int, int, int, int]]:
    return [
        (year.year, year.units, year.known, year.with_value)
        for year in found
        if year.year_type == year_type
    ]


def test_days_cross_the_hydrological_year_and_a_leap_year() -> None:
    """31 X and 1 XI fall in two hydrological years; 2024 has 366 days."""
    # Arrange
    coverage = _coverage(
        date(2023, 10, 31),
        date(2024, 11, 1),
        (date(2023, 12, 31), date(2024, 1, 1)),
    )
    periods = [(date(2023, 1, 1), date(2024, 12, 31))]

    # Act
    found = series_years(coverage, periods=periods, time_unit="day")

    # Assert
    assert _years(found, "calendar") == [
        (2023, 365, 365, 61),  # 31 X to 30 XII
        (2024, 366, 366, 305),  # 2 I to 1 XI
    ]
    assert _years(found, "hydrological") == [
        (2023, 365, 304, 1),  # 31 X 2023 only
        (2024, 366, 366, 364),  # without 31 XII and 1 I
        (2025, 365, 61, 1),  # 1 XI 2024 only
    ]


def test_a_year_without_a_known_unit_between_two_known_years_is_listed_empty() -> None:
    """No file for 2005: unknown units are never gaps and never values."""
    # Arrange
    coverage = _coverage(date(2004, 1, 1), date(2006, 12, 31))
    periods = [
        (date(2004, 1, 1), date(2004, 12, 31)),
        (date(2006, 1, 1), date(2006, 12, 31)),
    ]

    # Act
    found = series_years(coverage, periods=periods, time_unit="day")

    # Assert
    assert _years(found, "calendar") == [
        (2004, 366, 366, 366),
        (2005, 365, 0, 0),
        (2006, 365, 365, 365),
    ]


def test_months_count_twelve_units_in_either_year() -> None:
    """A monthly series: a gap of two months over the turn of a calendar year."""
    # Arrange
    coverage = _coverage(
        date(1999, 11, 1),
        date(2001, 10, 1),
        (date(2000, 12, 1), date(2001, 1, 1)),
    )
    periods = [(date(1999, 11, 1), date(2001, 10, 31))]

    # Act
    found = series_years(coverage, periods=periods, time_unit="month")

    # Assert
    assert _years(found, "hydrological") == [(2000, 12, 12, 12), (2001, 12, 12, 10)]
    assert _years(found, "calendar") == [
        (1999, 12, 2, 2),
        (2000, 12, 12, 11),
        (2001, 12, 10, 9),
    ]


def test_half_year_characteristics_have_hydrological_years_only() -> None:
    """One unit per hydrological year and key: a winter value of XI to IV."""
    # Arrange
    coverage = _coverage(
        date(1990, 11, 1),
        date(1993, 11, 1),
        (date(1991, 11, 1), date(1991, 11, 1)),
        key="Q_max@winter",
    )
    periods = [(date(1990, 11, 1), date(1994, 10, 31))]

    # Act
    found = series_years(coverage, periods=periods, time_unit="half_year")

    # Assert
    assert {year.year_type for year in found} == {"hydrological"}
    assert _years(found, "hydrological") == [
        (1991, 1, 1, 1),
        (1992, 1, 1, 0),
        (1993, 1, 1, 1),
        (1994, 1, 1, 1),
    ]


@pytest.mark.parametrize("time_unit", ["day", "month", "half_year"])
def test_a_variable_without_a_value_has_known_years_and_no_value(
    time_unit: TimeUnit,
) -> None:
    """No first and last date: every known unit lacks a value ("brak danych")."""
    # Arrange
    coverage = _coverage(None, None)
    periods = [(date(2000, 11, 1), date(2001, 10, 31))]

    # Act
    found = series_years(coverage, periods=periods, time_unit=time_unit)

    # Assert
    hydrological = _years(found, "hydrological")
    assert [
        (year, known == units, value) for year, units, known, value in hydrological
    ] == [(2001, True, 0)]


def test_without_known_periods_there_is_no_year() -> None:
    """A series index without periods knows no unit: every year is unknown."""
    assert series_years(_coverage(None, None), periods=(), time_unit="day") == ()
