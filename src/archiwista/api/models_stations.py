"""Stations and the coverage of their series for people and agents (SPEC 9.2, 4.8.4).

The query models of ``GET /stations``, ``/stations/timeline``,
``/stations/{code}``, ``/stations/{code}/coverage``, ``/stations/{code}/series``
and ``/map/stations`` refuse unknown parameters, and ``archiwista stations``
builds its options from them. The index gives a coverage label as structure
(`SeriesLabel`); the answers carry that structure beside its text, written
here in the language of the context for the API and the command line alike.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Annotated, Any, Literal, Self, TypedDict, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, with_config

from archiwista.api.models import WGS84, AreaRef, Cell, IndexAnswer, parse_bbox
from archiwista.config import YearTypes
from archiwista.index import (
    DEFAULT_GRID_COLUMNS,
    DEFAULT_PAGE_LIMIT,
    MAP_FOOTPRINT_LIMIT,
    MAX_GRID_COLUMNS,
    MAX_PAGE_LIMIT,
    SERIES_STATES,
    BBox,
    CoverageVariable,
    DatasetVariable,
    GapRun,
    LocationFilter,
    MeteoKind,
    RiverScope,
    SeriesLabel,
    SeriesState,
    SeriesYear,
    StationCounts,
    StationCoverage,
    StationDataset,
    StationLocation,
    StationMap,
    StationPage,
    StationQuery,
    StationRow,
    StationSort,
    YearRange,
)
from archiwista.index.series import MAX_UNKNOWN_RANGES, year_span
from archiwista.messages import message, plural_form
from archiwista.sources import GeoJSONGeometry, TimeUnit, YearType

# The range R of the labels: one year, or the first and the last.
STATION_YEARS_PATTERN = r"^\d{4}(-\d{4})?$"
# ``Q:continuous``: a variable (or variable key) and a state of its label.
COVERAGE_PATTERN = rf"^[^:\s]+:({'|'.join(SERIES_STATES)})$"
# ``Q:30``: a variable (or variable key) and its least number of full years.
MIN_YEARS_PATTERN = r"^[^:\s]+:\d{1,4}$"
# What a year of the Timeline shows (SPEC 6.7): a value in every unit, in
# some, in none, or a year that is not known.
type YearCell = Literal["full", "fraction", "none", "unknown"]
# What a marker of a chart is (SPEC 6.7): an accumulated sum of the days before
# it, or the least or greatest value of a half-year period as published.
type MarkerKind = Literal["accumulated", "min", "max"]
# The most points of each variable of a chart (SPEC 6.7, 9.2).
MAX_CHART_POINTS = 2000

_SHA256 = "fdd30535e8085f861a106824ba4401a7e96187a6c54abc33511803acd87b4623"
_SERIES_DIR = "series/versions/hydro_daily/2026-08-31_ab12cd34"
_GAP_EXAMPLE = {"from": "1981-06-02", "to": "1982-12-31", "units": 578}
_VARIABLE_EXAMPLE: dict[str, Any] = {
    "key": "Q",
    "variable": "Q",
    "unit": "m3/s",
    "period": None,
    "state": "gaps",
    "label": "gaps 3% · longest 1981.06.02–1982.12.31",
    "first": "1950-11-01",
    "last": "2025-10-31",
    "known": {"from": 1951, "to": 2025},
    "valued": {"from": 1951, "to": 2025},
    "units": 27394,
    "with_value": 26804,
    "missing_share": 0.0215,
    "percent": 3,
    "below_one": False,
    "longest_gap": _GAP_EXAMPLE,
    "gap_count": 12,
    "long_gaps": 2,
    "complete_years": 71,
    "unknown_years": [],
    "accumulated": 0,
    "only": [],
}
_SERIES_EXAMPLE = {
    "dataset": "pl.imgw.hydro_daily",
    "kind": "hydro",
    "time_unit": "day",
    "year_type": "hydrological",
    "years": {"from": 1951, "to": 2025},
    "series": "2026-08-31",
    "series_version": f"{_SERIES_DIR}/series.json",
    "file": f"{_SERIES_DIR}/stations/149190310.parquet",
    "sha256": _SHA256,
    "license": "IMGW-PIB",
    "attribution": (
        "The source of the data is the Institute of Meteorology and Water"
        " Management – National Research Institute; the data has been processed."
    ),
    "coverage": {"Q": _VARIABLE_EXAMPLE},
}
_LOCATION_EXAMPLE = {
    "kind": "point",
    "lon": 19.9247,
    "lat": 49.7963,
    "reason": None,
    "source": "api_hydro",
    "uncertainty_m": 150.0,
    "on_boundary": False,
}
_STATION_EXAMPLE = {
    "store": "zespol",
    "provider": "IMGW-PIB",
    "code": "149190310",
    "name": "STROZA",
    "kind": "hydro",
    "meteo_kind": None,
    "river": "Raba",
    "hydrographic_code": "2138",
    "river_order": 12,
    "active": True,
    "established_year": 1951,
    "gauge_zero_m": 296.47,
    "river_km": 74.3,
    "elevation_m": None,
    "catalog": "2026-10-17",
    "catalog_version": "stations/versions/2026-10-17_5c1d9a20/stations.geojson",
    "location": _LOCATION_EXAMPLE,
    "series": [_SERIES_EXAMPLE],
}
_COUNTS_EXAMPLE = {"located": 14, "boundary": 2, "unlocated": 3, "hidden": 0}
_FRESH = {"stale": False, "stale_stores": []}
_AREA_EXAMPLE = {
    "id": "5f2b9c0e7d41a3b6",
    "name": "zlewnia.gpkg",
    "area_km2": 1470.0,
    "countries": ["PL"],
}
_TIMELINE_VARIABLE_EXAMPLE = {
    "key": "Q",
    "variable": "Q",
    "unit": "m3/s",
    "period": None,
    "state": "gaps",
    "label": "gaps 3% · longest 1981.06.02–1982.12.31",
    "longest_gap": _GAP_EXAMPLE,
    "complete_years": 71,
    "years": [
        {
            "year": 1981,
            "units": 365,
            "known": 365,
            "with_value": 152,
            "cell": "fraction",
        },
        {"year": 1982, "units": 365, "known": 365, "with_value": 0, "cell": "none"},
        {"year": 1983, "units": 365, "known": 365, "with_value": 365, "cell": "full"},
    ],
}
_TIMELINE_SERIES_EXAMPLE = {
    "dataset": "pl.imgw.hydro_daily",
    "kind": "hydro",
    "time_unit": "day",
    "year_type": "hydrological",
    "years": {"from": 1981, "to": 1983},
    "series": "2026-08-31",
    "variables": [_TIMELINE_VARIABLE_EXAMPLE],
}
_TIMELINE_ITEM_EXAMPLE = {
    "store": "zespol",
    "provider": "IMGW-PIB",
    "code": "149190310",
    "name": "STROZA",
    "kind": "hydro",
    "meteo_kind": None,
    "river": "Raba",
    "hydrographic_code": "2138",
    "active": True,
    "location": _LOCATION_EXAMPLE,
    "series": [_TIMELINE_SERIES_EXAMPLE],
}
_POINT_EXAMPLE = {
    "store": "zespol",
    "provider": "IMGW-PIB",
    "code": "149190310",
    "name": "STROZA",
    "kind": "hydro",
    "meteo_kind": None,
    "river": "Raba",
    "lon": 19.9247,
    "lat": 49.7963,
    "uncertainty_m": 150.0,
    "on_boundary": False,
    "coverage": {
        "Q": {"state": "gaps", "label": "gaps 3% · longest 1981.06.02–1982.12.31"}
    },
}
_DATASET_VARIABLE_EXAMPLE = {
    "key": "Q",
    "variable": "Q",
    "unit": "m3/s",
    "period": None,
}
_DATASET_EXAMPLE = {
    "store": "zespol",
    "dataset": "pl.imgw.hydro_daily",
    "name": "Dane hydrologiczne dobowe",
    "provider": "IMGW-PIB",
    "kind": "hydro",
    "time_unit": "day",
    "year_type": "hydrological",
    "years": {"from": 1951, "to": 2025},
    "series": "2026-08-31",
    "series_version": f"{_SERIES_DIR}/series.json",
    "variables": [
        {"key": "H", "variable": "H", "unit": "cm", "period": None},
        _DATASET_VARIABLE_EXAMPLE,
        {"key": "T", "variable": "T", "unit": "degC", "period": None},
    ],
}


def _examples(*examples: dict[str, Any], aliased: bool = False) -> ConfigDict:
    """Return a model configuration with OpenAPI examples.

    ``aliased`` writes and reads the fields by their aliases (``from``,
    ``to``), and reads them by name too.
    """
    config = ConfigDict(json_schema_extra={"examples": list(examples)})
    if aliased:
        config["serialize_by_alias"] = True
        config["validate_by_alias"] = True
        config["validate_by_name"] = True
    return config


# Requests ------------------------------------------------------------------


class StationLookup(BaseModel):
    """Which station a code means, and how its coverage is labelled.

    A code belongs to its provider and store: ``store`` and ``provider`` name
    the station when the code alone means several. Unknown parameters are
    refused (``422``), so a misspelt one never silently changes an answer.
    """

    model_config = ConfigDict(extra="forbid")

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
            "Dataset key (`pl.imgw.hydro_daily`): its coverage only; `null`:"
            " every dataset with a series of the station."
        ),
        examples=["pl.imgw.hydro_daily"],
    )
    years: str | None = Field(
        default=None,
        description=(
            "Range R of the labels: `1951-2025`, or one year; by default from the"
            " dataset's first year to the last one its series knows."
        ),
        examples=["1951-2025"],
        json_schema_extra={"pattern": STATION_YEARS_PATTERN},
    )
    year_type: YearType | None = Field(
        default=None,
        description=(
            "Numbering of the years: `hydrological` (1 XI to 31 X) or `calendar`;"
            " by default the type remembered for the data's family (`year_types`"
            " of `GET /settings`: hydrological for hydro data and calendar for"
            " meteo data until changed), for a list of both families hydro's."
            " Half-year characteristics stay hydrological."
        ),
    )

    @field_validator("years")
    @classmethod
    def _check_years(cls, value: str | None) -> str | None:
        if value is not None and re.fullmatch(STATION_YEARS_PATTERN, value) is None:
            raise ValueError(message("api.station_years_invalid"))
        return value

    def year_range(self) -> YearRange | None:
        """Return ``years`` as R, its first and last year."""
        if self.years is None:
            return None
        first, _, last = self.years.partition("-")
        return int(first), int(last or first)


class StationFilters(StationLookup):
    """Filters of the stations and of the coverage of their series (SPEC 9.2)."""

    dataset: str | None = Field(
        default=None,
        description=(
            "Dataset key (`pl.imgw.hydro_daily`): only stations with a series of"
            " it, and only its coverage; `coverage` and `min_complete_years` need"
            " it."
        ),
        examples=["pl.imgw.hydro_daily"],
    )
    kind: str | None = Field(
        default=None,
        description="Station kind: `hydro` or `meteo`.",
        examples=["hydro"],
    )
    meteo_kind: list[MeteoKind] = Field(
        default_factory=list,
        description=(
            "Repeatable: meteo stations of these kinds only (`synoptic`,"
            " `climate`, `precipitation`; the station types of the map), the"
            " counts too; a station of no such kind (a water gauge) is left out."
        ),
        examples=[["precipitation"]],
    )
    active: bool | None = Field(
        default=None, description="Active (`true`) or historical (`false`) stations."
    )
    river_code: str | None = Field(
        default=None,
        description=(
            "Hydrographic code of a river (Raba: `2138`); with `river_scope` its"
            " stations only or also those of its tributaries."
        ),
        examples=["2138"],
    )
    river_scope: RiverScope = Field(
        default="exact",
        description=(
            "`exact`: the river's code; `tributaries`: also every code that begins"
            " with it (`2138` takes `21382`, never `2139`; a ČHMÚ code by whole"
            " parts)."
        ),
    )
    variable: list[str] = Field(
        default_factory=list,
        description=(
            "Repeatable: stations with a value of each variable (`Q`) or variable"
            " key (`Q_max@winter`) in a series of `dataset` (of any dataset"
            " without it)."
        ),
        examples=[["Q"]],
    )
    coverage: list[str] = Field(
        default_factory=list,
        description=(
            "Repeatable `<variable>:<state>` (`Q:continuous`, `H:gaps`): the"
            " variable's label in R has that state; several states of one"
            " variable are alternatives, different variables must all match."
            " Needs `dataset`; a station without the variable is hidden."
        ),
        examples=[["Q:continuous"]],
    )
    min_complete_years: list[str] = Field(
        default_factory=list,
        description=(
            "Repeatable `<variable>:<years>` (`Q:30`): at least that many full"
            " years of the variable in R. Needs `dataset`."
        ),
        examples=[["Q:30"]],
    )

    @field_validator("coverage")
    @classmethod
    def _check_coverage(cls, value: list[str]) -> list[str]:
        for item in value:
            if re.fullmatch(COVERAGE_PATTERN, item) is None:
                states = ", ".join(SERIES_STATES)
                raise ValueError(
                    message("api.coverage_filter_invalid", value=item, states=states)
                )
        return value

    @field_validator("min_complete_years")
    @classmethod
    def _check_min_complete_years(cls, value: list[str]) -> list[str]:
        for item in value:
            if re.fullmatch(MIN_YEARS_PATTERN, item) is None:
                raise ValueError(message("api.min_complete_years_invalid", value=item))
        return value

    def view_year_type(self, remembered: YearTypes) -> YearType | None:
        """Return the year type every label of the view takes, if one does.

        ``year_type`` when asked; else, for a view of both families (neither
        ``dataset``, ``kind`` nor ``meteo_kind`` keeps one), the type
        remembered for hydro data (P15, SPEC 6.7); else ``None``: each
        dataset takes the type remembered for its family.
        """
        if self.year_type is not None:
            return self.year_type
        one_family = self.dataset is not None or self.kind is not None
        return None if one_family or self.meteo_kind else remembered.hydro

    def station_query(
        self,
        *,
        year_types: YearTypes,
        area: GeoJSONGeometry | None = None,
        bbox: BBox | None = None,
        boundary: bool = True,
        location: LocationFilter = "any",
        limit: int = DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
        q: str | None = None,
        sort: StationSort = "river",
        labels: bool = True,
    ) -> StationQuery:
        """Return the index query of these filters with an area, view and page.

        ``year_types`` are the year types the settings remember; ``q`` and
        ``sort`` the search and order of a list (``GET /stations``).
        """
        return StationQuery(
            store=self.store,
            provider=self.provider,
            kind=self.kind,
            meteo_kinds=tuple(self.meteo_kind),
            active=self.active,
            river_code=self.river_code,
            river_scope=self.river_scope,
            q=q,
            bbox=bbox,
            location=location,
            limit=limit,
            cursor=cursor,
            sort=sort,
            area=area,
            boundary=boundary,
            dataset=self.dataset,
            variables=tuple(self.variable),
            coverage=tuple(
                (name, cast("SeriesState", state))
                for name, _, state in (item.rpartition(":") for item in self.coverage)
            ),
            min_complete_years=tuple(
                (name, int(years))
                for name, _, years in (
                    item.rpartition(":") for item in self.min_complete_years
                )
            ),
            year_type=self.view_year_type(year_types),
            year_types=year_types,
            years=self.year_range(),
            labels=labels,
        )


class StationListFilters(StationFilters):
    """Filters, search, order, area and page of ``GET /stations``."""

    q: str | None = Field(
        default=None,
        description=(
            "Search: stations whose name or river contains the text (case-folded;"
            " no character is a wildcard) or whose code begins with it."
        ),
        examples=["raba"],
    )
    sort: StationSort = Field(
        default="river",
        description=(
            "Order of the rows: `river` along rivers (the hydrographic code, so"
            " a tributary follows its river, then the provider's order on the"
            " river, then the name; stations without a code or an order last;"
            " SPEC 6.8) or `name`; then code, provider and store."
        ),
    )
    area_id: str | None = Field(
        default=None,
        description=(
            "Area kept by POST /areas: its stations and those on its boundary"
            " (closer to it than their location uncertainty)."
        ),
    )
    bbox: str | None = Field(
        default=None,
        description="Area as a rectangle `min_x,min_y,max_x,max_y` in `bbox_crs`.",
        examples=["19.5,49.5,20.5,50.2"],
    )
    bbox_crs: str = Field(
        default=WGS84,
        description=(
            "CRS of `bbox`, e.g. `EPSG:2180`; other than WGS84 it is converted"
            " with the producer's pinned operation."
        ),
    )
    boundary: bool = Field(
        default=True,
        description=(
            "Include the stations on the area's boundary (`counts.boundary` counts"
            " them either way)."
        ),
    )
    location: LocationFilter = Field(
        default="any",
        description=(
            "Location group: `any`, `with` (a position: in the area when one is"
            " given) or `none` (no position: only counted beside an area, never"
            " placed in it). `counts` counts every group whatever is chosen."
        ),
    )
    limit: int = Field(
        default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT, description="Page size."
    )
    cursor: str | None = Field(
        default=None, description="`next_cursor` of the previous page of the query."
    )

    @field_validator("bbox")
    @classmethod
    def _check_bbox(cls, value: str | None) -> str | None:
        if value is not None:
            parse_bbox(value)
        return value

    def bbox_values(self) -> BBox | None:
        """Return ``bbox`` as four numbers."""
        return None if self.bbox is None else parse_bbox(self.bbox)


class StationMapFilters(StationFilters):
    """A map view and the filters of ``GET /map/stations``."""

    bbox: str = Field(
        description="The view `min_lon,min_lat,max_lon,max_lat` in WGS84.",
        examples=["19.0,49.5,20.6,50.3"],
    )
    area_id: str | None = Field(
        default=None,
        description="Area kept by POST /areas: only its stations in the view.",
    )
    boundary: bool = Field(
        default=True, description="Include the stations on the area's boundary."
    )
    limit: int = Field(
        default=MAP_FOOTPRINT_LIMIT,
        ge=1,
        le=MAP_FOOTPRINT_LIMIT,
        description="Most stations returned; above it the view is a grid.",
    )
    grid_columns: int = Field(
        default=DEFAULT_GRID_COLUMNS,
        ge=1,
        le=MAX_GRID_COLUMNS,
        description="Columns of the aggregation grid (rows follow the view's shape).",
    )

    @field_validator("bbox")
    @classmethod
    def _check_bbox(cls, value: str) -> str:
        parse_bbox(value)
        return value

    def bbox_values(self) -> BBox:
        """Return the view as four numbers."""
        return parse_bbox(self.bbox)


class StationTimelineFilters(StationLookup):
    """The station, variables and range of ``GET /stations/{code}/coverage``."""

    variable: list[str] = Field(
        default_factory=list,
        description=(
            "Repeatable: only these variables (`Q`) or variable keys"
            " (`Q_max@winter`); by default every variable of the station."
        ),
        examples=[["Q"]],
    )


class StationTimelineListFilters(StationListFilters):
    """The filters, order and page of ``GET /stations/timeline``: one dataset."""

    dataset: str = Field(
        description=(
            "Dataset key (`pl.imgw.hydro_daily`), required: the stations with a"
            " series of it and its years."
        ),
        examples=["pl.imgw.hydro_daily"],
    )
    variable: list[str] = Field(
        default_factory=list,
        description=(
            "Repeatable: the stations with a value of each variable (`Q`) or"
            " variable key (`Q_max@winter`), and only their years; by default"
            " every variable of each station."
        ),
        examples=[["Q"]],
    )


class StationDatasetsQuery(BaseModel):
    """The store of ``GET /stations/datasets``; unknown parameters are refused."""

    model_config = ConfigDict(extra="forbid")

    store: str | None = Field(
        default=None, description="Store id (/stores).", examples=["zespol"]
    )


class StationChartQuery(BaseModel):
    """The station, series, variables and range of ``GET /stations/{code}/series``.

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
            "Dataset key (`pl.imgw.hydro_daily`); by default the one dataset whose"
            " series of the station has every variable."
        ),
        examples=["pl.imgw.hydro_daily"],
    )
    variable: list[str] = Field(
        min_length=1,
        max_length=2,
        description=(
            "Repeatable, once or twice: a variable of the series (`Q`, `H`), each"
            " with its points, gaps and markers."
        ),
        examples=[["Q"]],
    )
    start: date | None = Field(
        default=None,
        alias="from",
        description="First day of the range; by default the series' first unit.",
        examples=["1950-11-01"],
    )
    end: date | None = Field(
        default=None,
        alias="to",
        description="Last day of the range; by default the series' last unit.",
        examples=["2025-10-31"],
    )
    max_points: int = Field(
        default=MAX_CHART_POINTS,
        ge=1,
        le=MAX_CHART_POINTS,
        description=(
            "The most points of a variable: a range of more units is given as the"
            " least, mean and greatest value of intervals of equal length."
        ),
    )
    version: str | None = Field(
        default=None,
        description=(
            "The series version the chart must come from (its `series.json`,"
            " relative to the store, as `series_version` of the card); by default"
            " the index's current one, the only one whose gaps the index keeps."
        ),
    )

    @field_validator("variable")
    @classmethod
    def _once_each(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


# Answers -------------------------------------------------------------------


class YearSpan(BaseModel):
    """A range of years, both included."""

    model_config = _examples({"from": 1951, "to": 2025}, aliased=True)

    first: int = Field(alias="from", description="First year.")
    last: int = Field(alias="to", description="Last year.")

    @classmethod
    def between(cls, first: int, last: int) -> Self:
        """Return the range from ``first`` to ``last``."""
        return cls.model_validate({"from": first, "to": last})

    @classmethod
    def of(cls, years: YearRange | None) -> Self | None:
        """Return the model of a range, ``None`` without one."""
        return None if years is None else cls.between(*years)


class GapSpan(BaseModel):
    """A run of known units without a value: its first and last day, its units."""

    model_config = _examples(_GAP_EXAMPLE, aliased=True)

    first: date = Field(alias="from", description="First day of its first unit.")
    last: date = Field(alias="to", description="Last day of its last unit.")
    units: int = Field(description="Units of the run (days, months or half-years).")

    @classmethod
    def of(cls, gap: GapRun | None) -> Self | None:
        """Return the model of a gap, ``None`` without one."""
        if gap is None:
            return None
        return cls.model_validate(
            {"from": gap.start, "to": gap.end, "units": gap.units}
        )


class VariableCoverageItem(BaseModel):
    """A variable of a station's series with its coverage label in R (SPEC 4.8.4)."""

    model_config = _examples(_VARIABLE_EXAMPLE)

    key: str = Field(description="Key in the series index: `Q`, `Q_max@winter`.")
    variable: str = Field(description="The variable: `H`, `Q`, `T`, `P`, `Tmax`, …")
    unit: str = Field(description="Unit of its values, e.g. `m3/s`.")
    period: str | None = Field(
        description="Half-year period of a characteristic: `winter`, `summer`, …"
    )
    state: SeriesState = Field(
        description=(
            "`continuous` (no gap), `gaps`, `partial` (starts or ends within R),"
            " `no_data` (known years without a value) or `unknown` (no known year)."
        )
    )
    label: str = Field(
        description=(
            "The label for a person, in the request's language (dates"
            " `YYYY.MM.DD`, `YYYY.MM` for monthly and half-year characteristics)."
        )
    )
    first: date | None = Field(description="First day with a value in the series.")
    last: date | None = Field(description="Last day with a value in the series.")
    known: YearSpan | None = Field(description="K1–K2: the first and last known year.")
    valued: YearSpan | None = Field(
        description="y1–y2: the first and last known year with a value."
    )
    units: int = Field(description="Known units of y1–y2.")
    with_value: int = Field(description="Of them, the units with a value.")
    missing_share: float = Field(description="Gaps over the known units of y1–y2.")
    percent: int = Field(
        description="The gap share in whole percent, rounded up, at most 99."
    )
    below_one: bool = Field(description="A gap share above 0 below 1% (`<1%`).")
    longest_gap: GapSpan | None = Field(description="The longest run of gaps.")
    gap_count: int = Field(description="Runs of gaps in y1–y2.")
    long_gaps: int = Field(description="Runs of gaps longer than 30 days.")
    complete_years: int = Field(
        description="Full years of y1–y2: a value in every unit."
    )
    unknown_years: list[YearSpan] = Field(
        description="Years of R that are not known (not gaps), as ranges."
    )
    accumulated: int = Field(
        description="Units holding an accumulated sum of the days before them."
    )
    only: list[str] = Field(
        description=(
            "For `no_data` of a hydro series: the station's variables with a value"
            ' ("no data (only H)").'
        )
    )

    @classmethod
    def of(cls, variable: CoverageVariable, time_unit: TimeUnit) -> Self:
        """Return the model of a labelled variable."""
        label = variable.label
        return cls(
            key=variable.key,
            variable=variable.variable,
            unit=variable.unit,
            period=variable.period,
            state=label.state,
            label=series_label_text(label, time_unit=time_unit),
            first=variable.first,
            last=variable.last,
            known=YearSpan.of(label.known),
            valued=YearSpan.of(label.valued),
            units=label.units,
            with_value=label.with_value,
            missing_share=round(label.missing_share, 6),
            percent=label.percent,
            below_one=label.below_one,
            longest_gap=GapSpan.of(label.longest_gap),
            gap_count=label.gap_count,
            long_gaps=label.long_gaps,
            complete_years=label.complete_years,
            unknown_years=[YearSpan.between(*years) for years in label.unknown_years],
            accumulated=variable.accumulated,
            only=list(label.only),
        )


class StationSeriesItem(BaseModel):
    """A station's series in one dataset: its version and each variable's label."""

    model_config = _examples(_SERIES_EXAMPLE)

    dataset: str = Field(description="Dataset key.")
    kind: str | None = Field(description="Its family: `hydro`, `meteo`.")
    time_unit: TimeUnit = Field(description="Unit of the series: `day`, `month`, …")
    year_type: YearType = Field(description="Numbering of the years of R.")
    years: YearSpan | None = Field(
        description="R, the range of the labels; `null` when no period is known."
    )
    series: str | None = Field(description="Label of the series version (its date).")
    series_version: str = Field(
        description="The version's `series.json`, relative to the store."
    )
    file: str = Field(description="The station's series file, relative to the store.")
    sha256: str | None = Field(description="SHA-256 of the station's series file.")
    license: str | None = Field(description="Licence of the series version.")
    attribution: str | None = Field(
        description="The formula the source requires with its data (IMGW §5)."
    )
    coverage: dict[str, VariableCoverageItem] = Field(
        description="Each variable by its key, in the order of the series index."
    )

    @classmethod
    def of(cls, found: StationCoverage) -> Self:
        """Return the model of a station's coverage in one dataset."""
        return cls(
            dataset=found.dataset,
            kind=found.kind,
            time_unit=found.time_unit,
            year_type=found.year_type,
            years=YearSpan.of(found.span),
            series=found.series,
            series_version=found.series_version,
            file=found.file,
            sha256=found.sha256,
            license=found.license,
            attribution=found.attribution,
            coverage={
                item.key: VariableCoverageItem.of(item, found.time_unit)
                for item in found.variables
            },
        )


class StationLocationItem(BaseModel):
    """Where a station is (P13, A-ADR-022): a point, or nowhere with the reason."""

    model_config = _examples(
        _LOCATION_EXAMPLE,
        {
            "kind": "none",
            "lon": None,
            "lat": None,
            "reason": "zero",
            "source": None,
            "uncertainty_m": None,
            "on_boundary": False,
        },
    )

    kind: StationLocation = Field(description="`point`, or `none` without a position.")
    lon: float | None = Field(description="Longitude, WGS84.")
    lat: float | None = Field(description="Latitude, WGS84.")
    reason: str | None = Field(
        description=(
            "Why there is no position: `none` (no source has one), `zero` (the"
            " source said 0,0) or `outside_country`."
        )
    )
    source: str | None = Field(description="Source of the position in the catalog.")
    uncertainty_m: float | None = Field(
        description="Uncertainty of the position, metres."
    )
    on_boundary: bool = Field(
        description=(
            "Closer to the area's boundary than its uncertainty (SPEC 6.7); `false`"
            " without an area."
        )
    )

    @classmethod
    def of(cls, row: StationRow) -> Self:
        """Return the model of a station's location."""
        lon, lat = row.point or (None, None)
        return cls(
            kind=row.location,
            lon=lon,
            lat=lat,
            reason=row.location_reason,
            source=row.location_source,
            uncertainty_m=row.location_uncertainty_m,
            on_boundary=row.on_boundary,
        )


class StationItem(BaseModel):
    """A station of its provider's current catalog, with its series' coverage."""

    model_config = _examples(_STATION_EXAMPLE)

    store: str = Field(description="Store id.")
    provider: str = Field(description="`IMGW-PIB` or `CHMI`; a code is its provider's.")
    code: str = Field(description="Station code, as text.")
    name: str | None
    kind: str | None = Field(description="`hydro` or `meteo`.")
    meteo_kind: str | None = Field(
        description="Of a meteo station: `synoptic`, `climate`, `precipitation`."
    )
    river: str | None
    hydrographic_code: str | None = Field(description="The river's hydrographic code.")
    river_order: int | None = Field(description="Place of the station on its river.")
    active: bool | None
    established_year: int | None
    gauge_zero_m: float | None = Field(description="Gauge zero elevation, metres.")
    river_km: float | None = Field(description="River kilometre.")
    elevation_m: float | None = Field(description="Elevation, metres.")
    catalog: str | None = Field(description="Label of the catalog version (its date).")
    catalog_version: str | None = Field(
        description="The catalog version's file, relative to the store."
    )
    location: StationLocationItem
    series: list[StationSeriesItem] = Field(
        description=(
            "The station's series by dataset, each variable labelled separately"
            " (P16); a station has no single label."
        )
    )

    @classmethod
    def of(cls, row: StationRow, series: Iterable[StationCoverage]) -> Self:
        """Return the model of a station with the coverage of its series."""
        return cls(
            store=row.store,
            provider=row.provider,
            code=row.code,
            name=row.name,
            kind=row.kind,
            meteo_kind=row.meteo_kind,
            river=row.river,
            hydrographic_code=row.hydrographic_code,
            river_order=row.river_order,
            active=row.active,
            established_year=row.established_year,
            gauge_zero_m=row.gauge_zero_m,
            river_km=row.river_km,
            elevation_m=row.elevation_m,
            catalog=row.catalog,
            catalog_version=row.catalog_version,
            location=StationLocationItem.of(row),
            series=[StationSeriesItem.of(found) for found in series],
        )


class StationCountsItem(BaseModel):
    """Stations of the whole result by location group (SPEC 4.3 point 3)."""

    model_config = _examples(_COUNTS_EXAMPLE)

    located: int = Field(
        description=(
            "With a position, matching every filter: in the area or box when one"
            " is given (with the boundary group when `boundary` takes it)."
        )
    )
    boundary: int = Field(
        description="On the area's boundary, whether `boundary` takes them or not."
    )
    unlocated: int = Field(
        description=(
            "Without a position, matching the attribute and coverage filters:"
            ' the "N stations without location" counter; an area never takes or'
            " drops them."
        )
    )
    hidden: int = Field(
        description='Stations the coverage filters hid ("hidden by filter: 4").'
    )

    @classmethod
    def of(cls, counts: StationCounts) -> Self:
        """Return the model of a query's counts."""
        return cls(
            located=counts.located,
            boundary=counts.boundary,
            unlocated=counts.unlocated,
            hidden=counts.hidden,
        )


class StationList(IndexAnswer):
    """A page of stations in the order of ``sort``; the counts of the whole result."""

    model_config = _examples(
        {
            "area": _AREA_EXAMPLE,
            "counts": _COUNTS_EXAMPLE,
            "items": [_STATION_EXAMPLE],
            "next_cursor": None,
            **_FRESH,
        }
    )

    area: AreaRef | None = Field(description="The area of `area_id`, if given.")
    counts: StationCountsItem
    items: list[StationItem]
    next_cursor: str | None = Field(description="Cursor of the next page, if any.")

    @classmethod
    def of(
        cls, page: StationPage, area: AreaRef | None, freshness: Mapping[str, Any]
    ) -> Self:
        """Return the model of a page of stations with their coverage."""
        coverage = _by_station(page.coverage)
        return cls(
            area=area,
            counts=StationCountsItem.of(page.counts),
            items=[
                StationItem.of(row, coverage.get(_key(row), ())) for row in page.items
            ],
            next_cursor=page.next_cursor,
            **freshness,
        )


class StationCard(IndexAnswer):
    """A station's card: its catalog entry and every series labelled (SPEC 6.7)."""

    model_config = _examples({"station": _STATION_EXAMPLE, **_FRESH})

    station: StationItem


@with_config(
    _examples(
        {
            "year": 1981,
            "units": 365,
            "known": 365,
            "with_value": 152,
            "cell": "fraction",
        }
    )
)
class TimelineYear(TypedDict):
    """A year of a variable on the Timeline: its units, known and with a value.

    A record, not a model: a page of the Timeline holds tens of thousands of
    years, and a dict costs a fraction of a model to build.
    """

    year: int
    units: Annotated[int, Field(description="Units of the year.")]
    known: Annotated[int, Field(description="Of them, the known ones.")]
    with_value: Annotated[
        int, Field(description="Of the known ones, those with a value.")
    ]
    cell: Annotated[
        YearCell,
        Field(
            description=(
                "`full` (a value in every unit), `fraction`, `none` (known, no"
                " value) or `unknown` (not every unit known: not a gap)."
            )
        ),
    ]


class TimelineVariable(BaseModel):
    """A variable's years in R with its label and longest gap."""

    model_config = _examples(_TIMELINE_VARIABLE_EXAMPLE)

    key: str
    variable: str
    unit: str
    period: str | None
    state: SeriesState
    label: str = Field(description="The label, in the request's language.")
    longest_gap: GapSpan | None
    complete_years: int
    years: list[TimelineYear] = Field(description="Every year of R, in order.")

    @classmethod
    def of(cls, variable: CoverageVariable, found: StationCoverage) -> Self:
        """Return the Timeline row of a labelled variable.

        Every field comes typed from the index, and a page holds tens of
        thousands of years: the row is built without validating them again.
        """
        return cls.model_construct(
            key=variable.key,
            variable=variable.variable,
            unit=variable.unit,
            period=variable.period,
            state=variable.label.state,
            label=series_label_text(variable.label, time_unit=found.time_unit),
            longest_gap=GapSpan.of(variable.label.longest_gap),
            complete_years=variable.label.complete_years,
            years=_timeline_years(variable.years, found),
        )


class TimelineSeries(BaseModel):
    """A station's series in one dataset, year by year (the Timeline)."""

    model_config = _examples(_TIMELINE_SERIES_EXAMPLE)

    dataset: str
    kind: str | None
    time_unit: TimeUnit
    year_type: YearType
    years: YearSpan | None = Field(description="R; `null` when no period is known.")
    series: str | None = Field(description="Label of the series version.")
    variables: list[TimelineVariable]

    @classmethod
    def of(cls, found: StationCoverage, variables: Sequence[str]) -> Self:
        """Return a series year by year, of the variables asked (all: none).

        A variable is asked by its key (``Q_max@winter``) or by its name
        (``Q``, every period of it).
        """
        return cls(
            dataset=found.dataset,
            kind=found.kind,
            time_unit=found.time_unit,
            year_type=found.year_type,
            years=YearSpan.of(found.span),
            series=found.series,
            variables=[
                TimelineVariable.of(item, found)
                for item in found.variables
                if not variables or item.key in variables or item.variable in variables
            ],
        )


class StationTimeline(IndexAnswer):
    """The coverage of a station's variables by year (SPEC 6.7, the Timeline)."""

    model_config = _examples(
        {
            "store": "zespol",
            "provider": "IMGW-PIB",
            "code": "149190310",
            "name": "STROZA",
            "series": [_TIMELINE_SERIES_EXAMPLE],
            **_FRESH,
        }
    )

    store: str
    provider: str
    code: str
    name: str | None
    series: list[TimelineSeries]

    @classmethod
    def of(
        cls,
        row: StationRow,
        series: Sequence[StationCoverage],
        variables: Sequence[str],
        freshness: Mapping[str, Any],
    ) -> Self:
        """Return the Timeline of a station, of the variables asked (all: none)."""
        return cls(
            store=row.store,
            provider=row.provider,
            code=row.code,
            name=row.name,
            series=[TimelineSeries.of(found, variables) for found in series],
            **freshness,
        )


class StationTimelineItem(BaseModel):
    """A station of a Timeline page: who and where it is, its series by year."""

    model_config = _examples(_TIMELINE_ITEM_EXAMPLE)

    store: str = Field(description="Store id.")
    provider: str = Field(description="`IMGW-PIB` or `CHMI`; a code is its provider's.")
    code: str = Field(description="Station code, as text.")
    name: str | None
    kind: str | None = Field(description="`hydro` or `meteo`.")
    meteo_kind: str | None = Field(
        description="Of a meteo station: `synoptic`, `climate`, `precipitation`."
    )
    river: str | None
    hydrographic_code: str | None = Field(description="The river's hydrographic code.")
    active: bool | None
    location: StationLocationItem
    series: list[TimelineSeries] = Field(
        description=(
            "The station's series of `dataset` year by year, as"
            " `GET /stations/{code}/coverage` gives it."
        )
    )

    @classmethod
    def of(
        cls,
        row: StationRow,
        series: Iterable[StationCoverage],
        variables: Sequence[str],
    ) -> Self:
        """Return a station with its series year by year, of the variables asked."""
        return cls(
            store=row.store,
            provider=row.provider,
            code=row.code,
            name=row.name,
            kind=row.kind,
            meteo_kind=row.meteo_kind,
            river=row.river,
            hydrographic_code=row.hydrographic_code,
            active=row.active,
            location=StationLocationItem.of(row),
            series=[TimelineSeries.of(found, variables) for found in series],
        )


class StationTimelinePage(IndexAnswer):
    """A page of the stations of one dataset, each year by year (the Timeline tab)."""

    model_config = _examples(
        {
            "area": None,
            "counts": _COUNTS_EXAMPLE,
            "items": [_TIMELINE_ITEM_EXAMPLE],
            "next_cursor": None,
            **_FRESH,
        }
    )

    area: AreaRef | None = Field(description="The area of `area_id`, if given.")
    counts: StationCountsItem
    items: list[StationTimelineItem]
    next_cursor: str | None = Field(description="Cursor of the next page, if any.")

    @classmethod
    def of(
        cls,
        page: StationPage,
        variables: Sequence[str],
        area: AreaRef | None,
        freshness: Mapping[str, Any],
    ) -> Self:
        """Return the model of a page of stations with their years."""
        coverage = _by_station(page.coverage)
        return cls(
            area=area,
            counts=StationCountsItem.of(page.counts),
            items=[
                StationTimelineItem.of(row, coverage.get(_key(row), ()), variables)
                for row in page.items
            ],
            next_cursor=page.next_cursor,
            **freshness,
        )


class PointCoverage(BaseModel):
    """The state and label of a variable, for a point's colour and tooltip."""

    model_config = _examples(
        {"state": "gaps", "label": "gaps 3% · longest 1981.06.02–1982.12.31"}
    )

    state: SeriesState
    label: str


class StationPoint(BaseModel):
    """A located station drawn on the map."""

    model_config = _examples(_POINT_EXAMPLE)

    store: str
    provider: str
    code: str
    name: str | None
    kind: str | None
    meteo_kind: str | None
    river: str | None
    lon: float = Field(description="Longitude, WGS84.")
    lat: float = Field(description="Latitude, WGS84.")
    uncertainty_m: float | None = Field(description="Uncertainty of the position, m.")
    on_boundary: bool = Field(description="On the area's boundary (with `area_id`).")
    coverage: dict[str, PointCoverage] = Field(
        description=(
            "With `dataset`: each variable of its series by key (a point has one"
            " colour, its tooltip every label, P16); empty without it."
        )
    )

    @classmethod
    def of(cls, row: StationRow, series: Iterable[StationCoverage]) -> Self:
        """Return the point of a located station."""
        lon, lat = row.point or (0.0, 0.0)
        return cls(
            store=row.store,
            provider=row.provider,
            code=row.code,
            name=row.name,
            kind=row.kind,
            meteo_kind=row.meteo_kind,
            river=row.river,
            lon=lon,
            lat=lat,
            uncertainty_m=row.location_uncertainty_m,
            on_boundary=row.on_boundary,
            coverage={
                item.key: PointCoverage(
                    state=item.label.state,
                    label=series_label_text(item.label, time_unit=found.time_unit),
                )
                for found in series
                for item in found.variables
            },
        )


class StationMapView(IndexAnswer):
    """The located stations of a map view or, above `limit`, their grid."""

    model_config = _examples(
        {
            "total": 1,
            "aggregated": False,
            "items": [_POINT_EXAMPLE],
            "cells": [],
            "counts": _COUNTS_EXAMPLE,
            **_FRESH,
        }
    )

    total: int = Field(description="Stations of the view that match the filters.")
    aggregated: bool = Field(description="True: `cells` instead of `items`.")
    items: list[StationPoint]
    cells: list[Cell]
    counts: StationCountsItem = Field(
        description=(
            "Counts of the same filters as a list: `unlocated` is the 'stations"
            " without location' counter leading to the Catalog."
        )
    )

    @classmethod
    def of(cls, found: StationMap, freshness: Mapping[str, Any]) -> Self:
        """Return the model of a map view of stations."""
        coverage = _by_station(found.coverage)
        return cls(
            total=found.total,
            aggregated=found.aggregated,
            items=[
                StationPoint.of(row, coverage.get(_key(row), ())) for row in found.items
            ],
            cells=[Cell.of(cell) for cell in found.cells],
            counts=StationCountsItem.of(found.counts),
            **freshness,
        )


class DatasetVariableItem(BaseModel):
    """A variable of a dataset's station series (a "Kolor punktów" choice)."""

    model_config = _examples(_DATASET_VARIABLE_EXAMPLE)

    key: str = Field(description="Key in the series index: `Q`, `Q_max@winter`.")
    variable: str = Field(description="The variable: `H`, `Q`, `T`, `P`, `Tmax`, …")
    unit: str = Field(description="Unit of its values, e.g. `m3/s`.")
    period: str | None = Field(
        description="Half-year period of a characteristic: `winter`, `summer`, …"
    )

    @classmethod
    def of(cls, variable: DatasetVariable) -> Self:
        """Return the model of a dataset's variable."""
        return cls(
            key=variable.key,
            variable=variable.variable,
            unit=variable.unit,
            period=variable.period,
        )


class StationDatasetItem(BaseModel):
    """A dataset with station series in a store (the dataset chip of the map)."""

    model_config = _examples(_DATASET_EXAMPLE)

    store: str = Field(description="Store id.")
    dataset: str = Field(
        description="Dataset key, the `dataset` of the station routes."
    )
    name: str | None = Field(description="The producer's name of its segment.")
    provider: str = Field(description="`IMGW-PIB` or `CHMI`.")
    kind: str | None = Field(description="Its family: `hydro`, `meteo`.")
    time_unit: TimeUnit = Field(description="Unit of its series: `day`, `month`, …")
    year_type: YearType = Field(
        description=(
            "Numbering of the years of its labels and of `years` without"
            " `year_type`: the type remembered for its family (`year_types` of"
            " `GET /settings`); hydrological for half-year characteristics."
        )
    )
    years: YearSpan | None = Field(
        description=(
            "R by default: the dataset's first year to the last one its series"
            " knows; `null` when no period is known."
        )
    )
    series: str | None = Field(description="Label of the current series version.")
    series_version: str = Field(
        description="The version's `series.json`, relative to the store."
    )
    variables: list[DatasetVariableItem] = Field(
        description=(
            "The distinct variables of its stations' series, in the order of the"
            " series index (the first is the default colour of the points)."
        )
    )

    @classmethod
    def of(cls, found: StationDataset) -> Self:
        """Return the model of a dataset with station series."""
        return cls(
            store=found.store,
            dataset=found.dataset,
            name=found.name,
            provider=found.provider,
            kind=found.kind,
            time_unit=found.time_unit,
            year_type=found.year_type,
            years=YearSpan.of(found.span),
            series=found.series,
            series_version=found.series_version,
            variables=[DatasetVariableItem.of(item) for item in found.variables],
        )


class StationDatasets(IndexAnswer):
    """The datasets with station series in the index, by store and key."""

    model_config = _examples({"items": [_DATASET_EXAMPLE], **_FRESH})

    items: list[StationDatasetItem]

    @classmethod
    def of(cls, found: Iterable[StationDataset], freshness: Mapping[str, Any]) -> Self:
        """Return the model of the datasets with station series."""
        return cls(items=[StationDatasetItem.of(item) for item in found], **freshness)


@with_config(_examples({"t": "1950-11-01", "min": 2.9, "mean": 3.6, "max": 5.1}))
class ChartPoint(TypedDict):
    """A point of a chart: a unit, or an interval of units, and its values.

    A record, not a model: a chart has up to 2,000 points a variable.
    """

    t: Annotated[date, Field(description="First day of the unit or interval.")]
    min: Annotated[
        float | None,
        Field(
            description=(
                "The least value; `null` without one (the line breaks, never"
                " interpolated). A unit's own value is its least, mean and"
                " greatest."
            )
        ),
    ]
    mean: Annotated[float | None, Field(description="The mean of the values.")]
    max: Annotated[float | None, Field(description="The greatest value.")]


@with_config(
    _examples(
        {
            "t": "1997-07-09",
            "kind": "max",
            "value": 412.0,
            "period": "annual",
            "end": "1997-07-10",
        }
    )
)
class ChartMarker(TypedDict):
    """A value shown on its own: an accumulated sum, or a published extreme."""

    t: Annotated[
        date, Field(description="Its day; of an extreme, its first occurrence.")
    ]
    kind: Annotated[
        MarkerKind,
        Field(
            description=(
                "`accumulated`: a sum of the days before it, not a value of its"
                " day; `min`, `max`: the least or greatest value of a half-year"
                " period as the provider published it (SPEC 6.7)."
            )
        ),
    ]
    value: float
    period: Annotated[
        str | None,
        Field(description="Of an extreme: `winter`, `summer` or `annual`."),
    ]
    end: Annotated[
        date | None,
        Field(description="Of an extreme: the day of its last occurrence."),
    ]


class ChartVariable(BaseModel):
    """A variable of a chart: its points, the gaps of the range and its markers."""

    key: str = Field(description="Key in the series index (`Q`).")
    variable: str
    unit: str = Field(description="Unit of its values, e.g. `m3/s`.")
    points: list[ChartPoint] = Field(
        description="One a unit, or one an interval of `interval` units, in order."
    )
    gaps: list[GapSpan] = Field(
        description=(
            "The producer's gaps within the range, cut at its ends: a band each,"
            " also a gap shorter than an interval. A unit without a value outside"
            " them is not known, not a gap."
        )
    )
    markers: list[ChartMarker] = Field(
        description="Accumulated sums and published extremes of the range, by day."
    )


class StationChart(IndexAnswer):
    """A station's series as a chart, for display only (SPEC 6.7, 9.2)."""

    model_config = _examples(
        {
            "store": "zespol",
            "provider": "IMGW-PIB",
            "code": "149190310",
            "dataset": "pl.imgw.hydro_daily",
            "kind": "hydro",
            "time_unit": "day",
            "series": "2026-08-31",
            "series_version": f"{_SERIES_DIR}/series.json",
            "file": f"{_SERIES_DIR}/stations/149190310.parquet",
            "sha256": _SHA256,
            "from": "1950-11-01",
            "to": "2025-10-31",
            "units": 27394,
            "interval": 14,
            "variables": [
                {
                    "key": "Q",
                    "variable": "Q",
                    "unit": "m3/s",
                    "points": [
                        {"t": "1950-11-01", "min": 2.9, "mean": 3.6, "max": 5.1}
                    ],
                    "gaps": [_GAP_EXAMPLE],
                    "markers": [
                        {
                            "t": "1997-07-09",
                            "kind": "max",
                            "value": 412.0,
                            "period": "annual",
                            "end": "1997-07-10",
                        }
                    ],
                }
            ],
            "license": "IMGW-PIB",
            "attribution": _SERIES_EXAMPLE["attribution"],
            **_FRESH,
        },
        aliased=True,
    )

    store: str = Field(description="Store id.")
    provider: str
    code: str = Field(description="Station code, as text.")
    dataset: str = Field(description="Dataset key of the series.")
    kind: str | None = Field(description="Its family: `hydro`, `meteo`.")
    time_unit: TimeUnit = Field(description="Unit of the series: `day` or `month`.")
    series: str | None = Field(description="Label of the series version.")
    series_version: str = Field(
        description="The version's `series.json`, relative to the store."
    )
    file: str = Field(description="The station's series file, relative to the store.")
    sha256: str | None = Field(description="SHA-256 of the station's series file.")
    first: date | None = Field(
        alias="from", description="First day of the range; `null`: an empty series."
    )
    last: date | None = Field(alias="to", description="Last day of the range.")
    units: int = Field(description="Units of the range (days or months).")
    interval: int = Field(
        description=(
            "Units of a point: 1, each unit's value; more, the least, mean and"
            " greatest value of each interval (a simplified chart, its note"
            " naming the interval's length)."
        )
    )
    variables: list[ChartVariable]
    license: str | None = Field(description="Licence of the series version.")
    attribution: str | None = Field(
        description="The formula the source requires with its data (IMGW §5)."
    )


type _StationKey = tuple[str, str, str]


def _key(row: StationRow) -> _StationKey:
    return row.store, row.provider, row.code


def _by_station(
    coverage: Iterable[StationCoverage],
) -> dict[_StationKey, list[StationCoverage]]:
    """Group the coverage of a page's stations by station."""
    grouped: dict[_StationKey, list[StationCoverage]] = {}
    for found in coverage:
        grouped.setdefault((found.store, found.provider, found.code), []).append(found)
    return grouped


def _timeline_years(
    years: Iterable[SeriesYear], found: StationCoverage
) -> list[TimelineYear]:
    """Return every year of R: one the index knows nothing of is unknown.

    The records are dict literals: a page builds tens of thousands of them.
    """
    if found.span is None:
        return []
    rows = {year.year: year for year in years}
    cells: list[TimelineYear] = []
    for year in range(found.span[0], found.span[1] + 1):
        row = rows.get(year)
        if row is None:
            first, last = year_span(year, found.year_type, found.time_unit)
            units, known, with_value = last - first + 1, 0, 0
        else:
            units, known, with_value = row.units, row.known, row.with_value
        cell: YearCell
        if known < units:
            cell = "unknown"
        elif with_value == units:
            cell = "full"
        elif with_value == 0:
            cell = "none"
        else:
            cell = "fraction"
        cells.append(
            {
                "year": year,
                "units": units,
                "known": known,
                "with_value": with_value,
                "cell": cell,
            }
        )
    return cells


# Labels --------------------------------------------------------------------


def series_label_text(label: SeriesLabel, *, time_unit: TimeUnit) -> str:
    """Return a coverage label for a person, in the language of the context.

    "ciągły · 1951–2025", "luki 3% · najdł. 1981.06.02–1982.12.31",
    "częściowy · od 1972 · luki 12%", "brak danych (tylko H)" and "nieznane"
    in Polish (SPEC 4.8.4), with "· nieznane: 2011–2025" when some years of
    the range are not known (at most two ranges, else "· nieznane: 15 lat").
    A label names one year as one; a gap is written in days ``RRRR.MM.DD``,
    or in months ``RRRR.MM`` for monthly and half-year characteristics.

    Parameters
    ----------
    label : SeriesLabel
        The label of a variable.
    time_unit : TimeUnit
        The unit of the dataset's series.
    """
    if label.state == "unknown":
        return message("series.label_unknown")
    text: str
    if label.state == "no_data":
        if label.only:
            variables = ", ".join(label.only)
            text = message("series.label_no_data_only", variables=variables)
        else:
            text = message("series.label_no_data")
    else:
        text = _valued_text(label, time_unit)
    if label.unknown_years:
        years = _unknown_text(label)
        text = message("series.label_unknown_years", label=text, years=years)
    return text


def _valued_text(label: SeriesLabel, time_unit: TimeUnit) -> str:
    """Write the label of a variable with a value in a known year of the range."""
    valued = label.valued or (0, 0)
    known = label.known or valued
    if label.state == "continuous":
        return message("series.label_continuous", years=_years(valued))
    if label.state == "gaps":
        gap = _gap_text(label.longest_gap, time_unit)
        if label.below_one:
            return message("series.label_gaps_below_one", gap=gap)
        return message("series.label_gaps", percent=label.percent, gap=gap)
    if valued[0] > known[0] and valued[1] < known[1]:
        text = message("series.label_partial", years=_years(valued))
    elif valued[0] > known[0]:
        text = message("series.label_partial_from", year=valued[0])
    else:
        text = message("series.label_partial_to", year=valued[1])
    if label.below_one:
        return message("series.label_partial_gaps_below_one", label=text)
    if label.percent:
        return message("series.label_partial_gaps", label=text, percent=label.percent)
    return text


def _years(years: YearRange) -> str:
    """``1951–2025``, or one year alone."""
    first, last = years
    return str(first) if first == last else f"{first}–{last}"


def _gap_text(gap: GapRun | None, time_unit: TimeUnit) -> str:
    """``1981.06.02–1982.12.31`` (``RRRR.MM`` for characteristics), or one unit."""
    if gap is None:
        return ""
    form = "%Y.%m.%d" if time_unit == "day" else "%Y.%m"
    start, end = gap.start.strftime(form), gap.end.strftime(form)
    return start if start == end else f"{start}–{end}"


def _unknown_text(label: SeriesLabel) -> str:
    """Write the unknown years of the range: up to two ranges, else their count."""
    if len(label.unknown_years) <= MAX_UNKNOWN_RANGES:
        return ", ".join(_years(years) for years in label.unknown_years)
    count = label.unknown_count
    return message(f"series.years_{plural_form(count)}", count=count)
