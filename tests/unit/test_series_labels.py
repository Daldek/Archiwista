"""Coverage labels of a variable in a range of years (SPEC 4.8.4, A-ADR-021).

The table of SPEC 11 worked out by hand on synthetic series: zero gaps, one
day of gap ("<1%"), rounding up (2.12% is "3%"), the turn of the hydrological
year in a leap year, a series that starts or ends within the range, no value
at all, no known year, unknown years named as two ranges or counted, and the
characteristics written by month. Each label is checked as structure and as
the text of both languages.
"""

from dataclasses import replace
from datetime import date

import pytest

from archiwista.api.models_stations import series_label_text
from archiwista.index.series import (
    SeriesLabel,
    YearRange,
    default_span,
    label_year_type,
    series_label,
    series_years,
)
from archiwista.messages import language
from archiwista.sources import DateRange, TimeUnit, VariableCoverage, YearType


def _coverage(
    first: date | None, last: date | None, *gaps: DateRange
) -> VariableCoverage:
    return VariableCoverage(
        key="Q",
        variable="Q",
        unit="m3/s",
        period=None,
        first=first,
        last=last,
        with_value=0,
        accumulated=0,
        gaps=gaps,
    )


def _label(
    coverage: VariableCoverage,
    periods: list[DateRange],
    span: YearRange | None,
    *,
    time_unit: TimeUnit = "day",
    year_type: YearType = "calendar",
) -> SeriesLabel:
    years = series_years(coverage, periods=periods, time_unit=time_unit)
    return series_label(
        coverage,
        years,
        known=periods,
        time_unit=time_unit,
        year_type=year_type,
        span=span,
    )


def _texts(label: SeriesLabel, time_unit: TimeUnit = "day") -> tuple[str, str]:
    """Return the label in Polish and in English."""
    with language("pl"):
        polish = series_label_text(label, time_unit=time_unit)
    with language("en"):
        english = series_label_text(label, time_unit=time_unit)
    return polish, english


YEARS_2000_2002 = [(date(2000, 1, 1), date(2002, 12, 31))]
YEARS_2000_2004 = [(date(2000, 1, 1), date(2004, 12, 31))]


@pytest.mark.parametrize(
    ("coverage", "periods", "span", "state", "texts"),
    [
        pytest.param(
            _coverage(date(2000, 1, 1), date(2002, 12, 31)),
            YEARS_2000_2002,
            (2000, 2002),
            "continuous",
            ("ciągły · 2000–2002", "continuous · 2000–2002"),
            id="zero-gaps",
        ),
        pytest.param(
            _coverage(
                date(2000, 1, 1),
                date(2002, 12, 31),
                (date(2001, 6, 15), date(2001, 6, 15)),
            ),
            YEARS_2000_2002,
            (2000, 2002),
            "gaps",
            ("luki <1% · najdł. 2001.06.15", "gaps <1% · longest 2001.06.15"),
            id="one-day-below-one-percent",
        ),
        pytest.param(
            # 31 of 1461 days: 2.12% is rounded up.
            _coverage(
                date(2001, 1, 1),
                date(2004, 12, 31),
                (date(2002, 3, 1), date(2002, 3, 31)),
            ),
            [(date(2001, 1, 1), date(2004, 12, 31))],
            (2001, 2004),
            "gaps",
            (
                "luki 3% · najdł. 2002.03.01–2002.03.31",
                "gaps 3% · longest 2002.03.01–2002.03.31",
            ),
            id="rounded-up",
        ),
        pytest.param(
            _coverage(date(2002, 1, 1), date(2004, 12, 31)),
            YEARS_2000_2004,
            (2000, 2004),
            "partial",
            ("częściowy · od 2002", "partial · from 2002"),
            id="starts-within",
        ),
        pytest.param(
            # 184 of 1096 days after 30 VI 2002: 16.8% is 17%.
            _coverage(date(2000, 1, 1), date(2002, 6, 30)),
            YEARS_2000_2004,
            (2000, 2004),
            "partial",
            ("częściowy · do 2002 · luki 17%", "partial · to 2002 · gaps 17%"),
            id="ends-within-with-gaps",
        ),
        pytest.param(
            _coverage(
                date(2001, 1, 1),
                date(2003, 12, 31),
                (date(2002, 2, 2), date(2002, 2, 2)),
            ),
            YEARS_2000_2004,
            (2000, 2004),
            "partial",
            ("częściowy · 2001–2003 · luki <1%", "partial · 2001–2003 · gaps <1%"),
            id="starts-and-ends-within",
        ),
        pytest.param(
            _coverage(None, None),
            YEARS_2000_2002,
            (2000, 2002),
            "no_data",
            ("brak danych", "no data"),
            id="no-value",
        ),
        pytest.param(
            _coverage(date(2000, 1, 1), date(2002, 12, 31)),
            YEARS_2000_2002,
            (1990, 1995),
            "unknown",
            ("nieznane", "unknown"),
            id="no-known-year",
        ),
        pytest.param(
            _coverage(date(2000, 1, 1), date(2001, 12, 31)),
            [(date(2000, 1, 1), date(2001, 12, 31))],
            (1998, 2003),
            "continuous",
            (
                "ciągły · 2000–2001 · nieznane: 1998–1999, 2002–2003",
                "continuous · 2000–2001 · unknown: 1998–1999, 2002–2003",
            ),
            id="two-unknown-ranges",
        ),
        pytest.param(
            # No file for 2001: unknown, not a gap.
            _coverage(date(2000, 1, 1), date(2002, 12, 31)),
            [
                (date(2000, 1, 1), date(2000, 12, 31)),
                (date(2002, 1, 1), date(2002, 12, 31)),
            ],
            (1999, 2003),
            "continuous",
            (
                "ciągły · 2000–2002 · nieznane: 3 lata",
                "continuous · 2000–2002 · unknown: 3 years",
            ),
            id="three-unknown-ranges-counted",
        ),
        pytest.param(
            _coverage(date(2000, 1, 1), date(2002, 12, 31)),
            [
                (date(2000, 1, 1), date(2000, 12, 31)),
                (date(2002, 1, 1), date(2002, 12, 31)),
            ],
            (1995, 2005),
            "continuous",
            (
                "ciągły · 2000–2002 · nieznane: 9 lat",
                "continuous · 2000–2002 · unknown: 9 years",
            ),
            id="unknown-years-counted",
        ),
    ],
)
def test_the_label_of_a_daily_series_in_calendar_years(
    coverage: VariableCoverage,
    periods: list[DateRange],
    span: YearRange,
    state: str,
    texts: tuple[str, str],
) -> None:
    """Each label of SPEC 4.8.4 in Polish and English."""
    label = _label(coverage, periods, span)

    assert label.state == state
    assert _texts(label) == texts


def test_the_row_details_count_full_years_runs_of_gaps_and_long_ones() -> None:
    """A month without a value in 2002: three full years, one gap over 30 days."""
    coverage = _coverage(
        date(2001, 1, 1), date(2004, 12, 31), (date(2002, 3, 1), date(2002, 3, 31))
    )

    label = _label(coverage, [(date(2001, 1, 1), date(2004, 12, 31))], (2001, 2004))

    assert (label.known, label.valued) == ((2001, 2004), (2001, 2004))
    assert (label.units, label.with_value, label.percent) == (1461, 1430, 3)
    assert label.missing_share == pytest.approx(31 / 1461)
    assert (label.complete_years, label.gap_count, label.long_gaps) == (3, 1, 1)
    assert label.longest_gap is not None
    assert (label.longest_gap.start, label.longest_gap.end) == (
        date(2002, 3, 1),
        date(2002, 3, 31),
    )
    assert label.unknown_years == ()


def test_a_gap_over_the_turn_of_a_hydrological_year_in_a_leap_year() -> None:
    """31 X and 1 XI lie in two hydrological years; 2004 has 366 days."""
    coverage = _coverage(
        date(2002, 11, 1), date(2004, 10, 31), (date(2003, 10, 31), date(2003, 11, 1))
    )

    label = _label(
        coverage,
        [(date(2002, 11, 1), date(2004, 10, 31))],
        (2003, 2004),
        year_type="hydrological",
    )

    assert (label.state, label.units, label.with_value) == ("gaps", 731, 729)
    assert label.complete_years == 0
    assert _texts(label) == (
        "luki <1% · najdł. 2003.10.31–2003.11.01",
        "gaps <1% · longest 2003.10.31–2003.11.01",
    )


def test_characteristics_write_their_gaps_by_month() -> None:
    """Monthly and half-year series: the longest gap as RRRR.MM."""
    monthly = _coverage(
        date(2000, 1, 1), date(2000, 12, 1), (date(2000, 3, 1), date(2000, 4, 1))
    )
    winter = _coverage(
        date(1990, 11, 1), date(1993, 11, 1), (date(1991, 11, 1), date(1991, 11, 1))
    )

    by_month = _label(
        monthly,
        [(date(2000, 1, 1), date(2000, 12, 31))],
        (2000, 2000),
        time_unit="month",
    )
    by_half_year = _label(
        winter,
        [(date(1990, 11, 1), date(1994, 10, 31))],
        (1991, 1994),
        time_unit="half_year",
        year_type="hydrological",
    )

    assert _texts(by_month, "month") == (
        "luki 17% · najdł. 2000.03–2000.04",
        "gaps 17% · longest 2000.03–2000.04",
    )
    assert _texts(by_half_year, "half_year") == (
        "luki 25% · najdł. 1991.11–1992.10",
        "gaps 25% · longest 1991.11–1992.10",
    )


def test_no_data_names_the_variables_that_have_a_value() -> None:
    """Hydro: "brak danych (tylko H)"; a missing Q never hides H (P16)."""
    label = _label(_coverage(None, None), YEARS_2000_2002, (2000, 2002))

    assert _texts(replace(label, only=("H",))) == (
        "brak danych (tylko H)",
        "no data (only H)",
    )
    assert _texts(replace(label, only=("H", "T")))[0] == "brak danych (tylko H, T)"


@pytest.mark.parametrize(
    ("kind", "time_unit", "asked", "expected"),
    [
        ("hydro", "day", None, "hydrological"),
        ("meteo", "day", None, "calendar"),
        ("hydro", "day", "calendar", "calendar"),
        ("meteo", "month", "hydrological", "hydrological"),
        ("hydro", "half_year", "calendar", "hydrological"),
    ],
)
def test_the_year_type_of_a_label(
    kind: str, time_unit: TimeUnit, asked: YearType | None, expected: YearType
) -> None:
    """Hydro by hydrological years, meteo by calendar ones; half-years stay (P15)."""
    assert label_year_type(kind, time_unit, asked) == expected


def test_the_range_runs_from_the_first_year_to_the_last_published_one() -> None:
    """The dataset's first year, else the first known one; none without periods."""
    periods = [(date(2023, 11, 1), date(2024, 10, 31))]

    assert default_span(1951, periods, time_unit="day", year_type="hydrological") == (
        1951,
        2024,
    )
    assert default_span(None, periods, time_unit="day", year_type="calendar") == (
        2023,
        2024,
    )
    assert default_span(None, (), time_unit="day", year_type="calendar") is None
