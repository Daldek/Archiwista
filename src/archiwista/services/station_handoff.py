"""A station's series as a hand-off to Hydrolog's statistics (A-ADR-052).

The ``nogat-handoff/1`` envelope around a ``hydrolog-series/1`` payload, the
document Hydrograf's „Kopiuj do Hydrologa” writes for a watershed, here for a
series: every day of a variable's daily values in a range, a day without a
value (no row, or a missing or accumulated one) as ``null``; or the annual
maxima of an annual chart (A-ADR-051), only of complete hydrological years,
since a flood frequency analysis must not take one half-year's maximum for its
year's; the years left out are named in the provenance. By default a hand-off
spans the variable's values, from its first to its last (A-ADR-052 erratum 4):
the known span of its label, a chart's default range, may begin decades before
them when the provider's archive lists the station without the variable. The
document carries the lines the provider's terms require with the series
(A-ADR-055).
"""

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from importlib.metadata import version
from typing import Any

from archiwista import attribution
from archiwista.api.models_handoff import (
    HANDOFF_SCHEMA,
    SERIES_SCHEMA,
    HandoffProducer,
    StationHandoff,
)
from archiwista.api.models_stations import AnnualPoint
from archiwista.index import CoverageVariable, StationCoverage, StationRow
from archiwista.messages import message
from archiwista.services.series_chart import known_span
from archiwista.sources import DateRange, SeriesValues

# The rule by which an annual maximum is found (A-ADR-051), named in the provenance.
ANNUAL_RULE = "greater of the winter and summer maxima of the half-year characteristics"


def daily_range(
    line: CoverageVariable, start: date | None, end: date | None
) -> DateRange | None:
    """Return the first and last day of a variable's daily hand-off.

    ``start`` and ``end`` are the range asked. A bound left out is the
    variable's first or last value, yet not past the other bound when that
    lies beyond its values; a variable without a value takes its label's
    known span, every day ``null``. ``None`` when a bound is neither asked
    nor known.
    """
    span = (
        (line.first, line.last)
        if line.first is not None and line.last is not None
        else known_span([line])
    )
    if span is None:
        return None if start is None or end is None else (start, end)
    first = start or (span[0] if end is None else min(span[0], end))
    last = end or (span[1] if start is None else max(span[1], start))
    return first, last


def valued_years(
    points: Sequence[AnnualPoint], *, start: bool, end: bool
) -> list[AnnualPoint]:
    """Return an annual chart's points from its first to its last year with a maximum.

    Only the ends ``start`` and ``end`` name are cut (those of a range left to
    its default, the chart's known span); the years between keep their gaps.
    Points without a maximum at all are returned whole.
    """
    valued = [index for index, point in enumerate(points) if point["max"] is not None]
    if not valued:
        return list(points)
    low = valued[0] if start else 0
    high = valued[-1] if end else len(points) - 1
    return list(points[low : high + 1])


def daily_payload(
    row: StationRow,
    variable: str,
    unit: str,
    values: Iterable[SeriesValues],
    start: date,
    end: date,
) -> dict[str, Any]:
    """Return the ``hydrolog-series/1`` of every day of a variable from start to end.

    Parameters
    ----------
    row : StationRow
        The station, which names the series.
    variable : str
        The variable read (``Q``).
    unit : str
        Its unit (``m3/s``).
    values : Iterable[SeriesValues]
        The station's rows as the producer read them.
    start, end : date
        The first and last day handed off.
    """
    by_day: dict[date, float | None] = {}
    for item in values:
        if variable in item.accumulated:
            continue
        by_day[item.start] = item.values.get(variable)
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    return {
        "schema": SERIES_SCHEMA,
        "name": f"{_station_name(row)} — {variable}",
        "variable": variable,
        "unit": unit,
        "step": "day",
        "dates": [day.isoformat() for day in days],
        "values": [by_day.get(day) for day in days],
    }


def annual_payload(
    row: StationRow, variable: str, unit: str, points: Sequence[AnnualPoint]
) -> tuple[dict[str, Any], list[int]]:
    """Return the ``hydrolog-series/1`` of the annual maxima and the years left out.

    A year whose maximum lacks one of its halves (``partial``) is ``null`` and
    left out, as is a year without one.
    """
    years: list[int] = []
    maxima: list[float | None] = []
    left_out: list[int] = []
    for point in points:
        found = point["max"]
        years.append(point["year"])
        if found is not None and found["partial"] is not None:
            left_out.append(point["year"])
            found = None
        maxima.append(None if found is None else found["value"])
    payload = {
        "schema": SERIES_SCHEMA,
        "name": f"{_station_name(row)} — {variable}",
        "variable": variable,
        "unit": unit,
        "step": "year",
        "statistic": "max",
        "year_type": "hydrological",
        "years": years,
        "values": maxima,
    }
    return payload, left_out


def handoff(
    row: StationRow,
    series: StationCoverage,
    payload: dict[str, Any],
    *,
    annual: bool,
    left_out: Sequence[int] = (),
    now: datetime | None = None,
) -> StationHandoff:
    """Return the ``nogat-handoff/1`` envelope of a series payload.

    ``attribution`` and ``terms_notice`` are the lines of the station's
    provider for its series values, written in another format.
    """
    origin: dict[str, Any] = {
        "source": row.provider.lower(),
        "provider": row.provider,
        "store": series.store,
        "dataset": series.dataset,
        "station": row.code,
        "series_version": series.series_version,
    }
    if annual:
        origin["rule"] = ANNUAL_RULE
        origin["left_out"] = list(left_out)
    names = {
        "station": _station_name(row),
        "river": f" ({row.river})" if row.river else "",
        "variable": payload["variable"],
    }
    subject = (
        message("api.handoff_subject_annual", "pl", **names)
        if annual
        else message("api.handoff_subject_daily", "pl", **names)
    )
    moment = (now or datetime.now(UTC)).replace(microsecond=0)
    lines = attribution.of([attribution.series_origin(row.provider)])
    return StationHandoff.model_validate(
        {
            "schema": HANDOFF_SCHEMA,
            "created_at": moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "producer": HandoffProducer(
                tool="archiwista", version=version("archiwista")
            ),
            "subject": str(subject),
            "provenance": {"series": origin},
            **lines.fields(),
            "payload": payload,
        }
    )


def _station_name(row: StationRow) -> str:
    """Return the station's name, else its code."""
    return row.name or row.code
