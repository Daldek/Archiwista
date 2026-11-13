"""Models of a station's series handed to Hydrolog (A-ADR-052).

``GET /stations/{code}/handoff`` answers a ``nogat-handoff/1`` document, the
envelope Nogat defines for data passed between the ecosystem's GUIs, around a
``hydrolog-series/1`` payload, the series Hydrolog's statistics read: the
daily values of a variable, or the annual maxima Archiwista finds in the
half-year characteristics (A-ADR-051). The query names the chart it is made
from, as ``GET /stations/{code}/series`` does.
"""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from archiwista.api.models_stations import ChartResolution, StationChartQuery

HANDOFF_SCHEMA = "nogat-handoff/1"
SERIES_SCHEMA = "hydrolog-series/1"


class StationHandoffQuery(BaseModel):
    """The station, series, variable and range of ``GET /stations/{code}/handoff``.

    ``from`` and ``to`` are read by these names (the fields ``start`` and
    ``end``); unknown parameters are refused.
    """

    model_config = ConfigDict(
        extra="forbid", validate_by_alias=True, validate_by_name=True
    )

    store: str | None = Field(
        default=None, description="Store id (/stores).", examples=["zespol"]
    )
    provider: str | None = Field(
        default=None,
        description="Provider of the stations: `IMGW-PIB` or `CHMI` (ČHMÚ).",
        examples=["IMGW-PIB"],
    )
    dataset: str | None = Field(
        default=None,
        description=(
            "Dataset key of a series of days (`pl.imgw.hydro_daily`), or with"
            " `resolution=annual` of half-year characteristics; by default the"
            " station's one, as the chart chooses it."
        ),
        examples=["pl.imgw.hydro_daily"],
    )
    resolution: ChartResolution = Field(
        default="unit",
        description=(
            "`unit`: the daily values of the variable (a series of days; a"
            " monthly series is refused, `no_daily_series`). `annual`: the annual"
            " maxima of complete hydrological years Archiwista finds in the"
            " half-year characteristics (A-ADR-051)."
        ),
    )
    variable: str = Field(
        description="The variable handed off (`Q`, `H`).", examples=["Q"]
    )
    start: date | None = Field(
        default=None,
        alias="from",
        description="First day of the range; by default the first known day.",
        examples=["1950-11-01"],
    )
    end: date | None = Field(
        default=None,
        alias="to",
        description="Last day of the range; by default the last known day.",
        examples=["2025-10-31"],
    )

    def chart_query(self) -> StationChartQuery:
        """Return the query of the chart the hand-off is made from."""
        return StationChartQuery.model_validate(
            {
                "store": self.store,
                "provider": self.provider,
                "dataset": self.dataset,
                "resolution": self.resolution,
                "variable": [self.variable],
                "from": self.start,
                "to": self.end,
            }
        )


class HandoffProducer(BaseModel):
    """The tool that wrote the hand-off."""

    tool: Literal["archiwista"] = Field(description="Always `archiwista`.")
    version: str = Field(description="Archiwista's version.")


class StationHandoff(BaseModel):
    """A ``nogat-handoff/1`` document carrying a ``hydrolog-series/1`` payload.

    Saved as ``<subject>.handoff.json`` or copied to the clipboard, it opens in
    Hydrolog's „Statystyka przepływów” with „Wczytaj z Archiwisty”.
    """

    model_config = ConfigDict(
        serialize_by_alias=True, validate_by_alias=True, validate_by_name=True
    )

    handoff_schema: Literal["nogat-handoff/1"] = Field(
        alias="schema", description="The envelope, `nogat-handoff/1`."
    )
    created_at: str = Field(
        description="When Archiwista wrote it, RFC 3339 in UTC: `2026-11-05T20:00:00Z`."
    )
    producer: HandoffProducer
    subject: str = Field(
        description="What is handed off: the station, its river, the variable and kind."
    )
    provenance: dict[str, dict[str, Any]] = Field(
        description=(
            "Where the series came from: `series` with `source` (`imgw-pib`), the"
            " provider, store, dataset, station code and series version; for"
            " annual maxima the rule and `left_out`, the years without one of"
            " their halves."
        )
    )
    attribution: list[str] = Field(
        default_factory=list,
        exclude_if=lambda lines: not lines,
        description=(
            "The lines the terms of the series' provider require (Nogat DEV-20.6,"
            " A-ADR-055), verbatim: for IMGW-PIB its source and the mark of"
            " processing, for ČHMÚ its credit and licence and what was done."
            " Hydrolog shows them with the series and carries them on."
        ),
    )
    terms_notice: list[str] = Field(
        default_factory=list,
        exclude_if=lambda lines: not lines,
        description=(
            "The links to the IMGW-PIB terms that apply (DEV-20.7, ECO-065);"
            " left out for ČHMÚ's data."
        ),
    )
    payload: dict[str, Any] = Field(
        description=(
            "The `hydrolog-series/1` document: `name`, `variable`, `unit`, `step`"
            " `day` with `dates` or `year` with `statistic` `max`, `year_type` and"
            " `years`, and `values` (`null` for a missing value)."
        )
    )
