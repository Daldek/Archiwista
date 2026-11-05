"""A station's series as a hand-off to Hydrolog's statistics (A-ADR-052).

The ``nogat-handoff/1`` envelope around a ``hydrolog-series/1`` payload, the
document Hydrograf's „Kopiuj do Hydrologa” writes for a watershed, here for a
series: every day of a variable's daily values in a range, a day without a
value (no row, or a missing or accumulated one) as ``null``; or the annual
maxima of an annual chart (A-ADR-051), only of complete hydrological years,
since a flood frequency analysis must not take one half-year's maximum for its
year's; the years left out are named in the provenance.
"""

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from importlib.metadata import version
from typing import Any

from archiwista.api.models_handoff import (
    HANDOFF_SCHEMA,
    SERIES_SCHEMA,
    HandoffProducer,
    StationHandoff,
)
from archiwista.api.models_stations import AnnualPoint
from archiwista.index import StationCoverage, StationRow
from archiwista.messages import message
from archiwista.sources import SeriesValues

# The rule by which an annual maximum is found (A-ADR-051), named in the provenance.
ANNUAL_RULE = "greater of the winter and summer maxima of the half-year characteristics"


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
    """Return the ``nogat-handoff/1`` envelope of a series payload."""
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
    return StationHandoff.model_validate(
        {
            "schema": HANDOFF_SCHEMA,
            "created_at": moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "producer": HandoffProducer(
                tool="archiwista", version=version("archiwista")
            ),
            "subject": str(subject),
            "provenance": {"series": origin},
            "payload": payload,
        }
    )


def _station_name(row: StationRow) -> str:
    """Return the station's name, else its code."""
    return row.name or row.code
