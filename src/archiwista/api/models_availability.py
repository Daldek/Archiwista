"""Models of the availability at the source (plan of 2026-10-25, A2; SPEC 9.2).

``AvailabilityRequest`` asks ``POST /availability`` what the source has for an
area and a product, and ``AvailabilityQuery`` names the report ``GET
/availability`` returns. ``AvailabilityInfo`` is that report as the index keeps
it: the area, when the source was asked and by which job, and the producer's
report without its classes (ADR-035): the parts of the area by country, the
combinations (a year, a variant and a format, with the sheet records and the
campaigns of KD-1 and the full land of KD-2), the parts that failed and what
the producer said. The request models refuse unknown members (``400
validation_error``).
"""

from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from archiwista.api.models import AreaRef
from archiwista.services.availability import AreaAvailability
from archiwista.sources import (
    AvailabilityArea,
    AvailabilityCampaign,
    AvailabilityCombination,
    AvailabilityFailure,
    AvailabilityNotice,
    AvailabilityReport,
    AvailabilitySheet,
)

_AREA_ID = "5f2b9c0e7d41a3b6"
_CHECKED_AT = "2026-10-20T08:15:02Z"
_LAND_M2 = 120_000_000.0
_AREA_EXAMPLE: dict[str, Any] = {
    "country": "PL",
    "crs": "EPSG:2180",
    "bounds": [561000.0, 239000.0, 573000.0, 249000.0],
    "area_m2": _LAND_M2,
    "land_m2": _LAND_M2,
}
_SHEET_EXAMPLE: dict[str, Any] = {
    "sheet": "N-34-64-C-c-2-4",
    "campaign": "DFT.7211.1.2023",
    "full_sheet": True,
    "acquisition_date": "2023-04-26",
    "published": "2023-09-14",
}
_CAMPAIGN_EXAMPLE: dict[str, Any] = {
    "campaign": "DFT.7211.1.2023",
    "complete": True,
    "full_m2": _LAND_M2,
}
_COMBINATION_EXAMPLE: dict[str, Any] = {
    "country": "PL",
    "product": "nmt",
    "source": "nmt_pl",
    "year": 2023,
    "horizontal": "PL-2000",
    "resolution": "1m",
    "vertical_crs": "EVRF2007",
    "format": "ASC",
    "campaigns": ["DFT.7211.1.2023"],
    "complete": True,
    "sheets_full": ["N-34-64-C-c-2-4"],
    "sheets_partial": [],
    "sheets_missing": [],
    "uncovered_m2": 0.0,
    "full_m2": _LAND_M2,
    "size_bytes": None,
    "published": ["2023-09-14", "2023-09-14"],
    "sheet_records": [_SHEET_EXAMPLE],
    "campaign_coverage": [_CAMPAIGN_EXAMPLE],
}
_NOTICE_EXAMPLE: dict[str, Any] = {
    "level": "info",
    "code": "index_cached",
    "message": "The sheet index answered from the cache.",
}
_FAILURE_EXAMPLE: dict[str, Any] = {
    "part": "CZ",
    "detail": "CUZK did not answer within 30 s.",
    "kind": "country",
}
_REPORT_EXAMPLE: dict[str, Any] = {
    "producer": "kartograf",
    "schema": "kartograf-availability/1",
    "checked_at": _CHECKED_AT,
    "request": {
        "product": "nmt",
        "country": "pl",
        "bbox": [561000.0, 239000.0, 573000.0, 249000.0],
        "bbox_crs": "EPSG:2180",
        "min_year": None,
        "max_year": None,
    },
    "areas": [_AREA_EXAMPLE],
    "combinations": [_COMBINATION_EXAMPLE],
    "failed": [],
    "notices": [_NOTICE_EXAMPLE],
    "ok": True,
}
AVAILABILITY_EXAMPLE: dict[str, Any] = {
    "area": {
        "id": _AREA_ID,
        "name": "Krakow",
        "area_km2": 120.0,
        "countries": ["PL"],
    },
    "producer": "kartograf",
    "product": "nmt",
    "checked_at": _CHECKED_AT,
    "job_id": "3f9c1a7e5b2d4c60",
    "report": _REPORT_EXAMPLE,
}
"""An answer of ``GET /availability``, also of ``POST /availability`` (``200``)."""
AVAILABILITY_JOB_EXAMPLE: dict[str, Any] = {
    "id": "3f9c1a7e5b2d4c60",
    "kind": "availability",
    "state": "queued",
    "actor": "local",
    "actor_kind": "local_owner",
    "session": "5b2d4c60",
    "store": None,
    "params": {
        "area_id": _AREA_ID,
        "producer": "kartograf",
        "product": "nmt",
        "force": False,
    },
    "created_at": "2026-10-20T08:15:00Z",
    "started_at": None,
    "finished_at": None,
    "progress": None,
    "result": None,
    "error": None,
}
"""The job of ``POST /availability`` (``202``) that asks the source."""


class AvailabilityRequest(BaseModel):
    """What to ask the source: an area and a product (`POST /availability`)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"area_id": _AREA_ID, "product": "nmt"},
                {"area_id": _AREA_ID, "product": "laz", "force": True},
            ]
        },
    )

    area_id: str = Field(min_length=1, description="Area id (`POST /areas`).")
    product: str = Field(
        min_length=1,
        description=(
            "Product whose availability the producer checks (Kartograf: `nmt`,"
            " `nmpt`, `laz`)."
        ),
    )
    producer: str = Field(default="kartograf", min_length=1, description="Producer id.")
    force: bool = Field(
        default=False,
        description=(
            "Ask the source even when a report younger than seven days is kept;"
            " the producer does not answer from its metadata cache either."
        ),
    )


class AvailabilityQuery(BaseModel):
    """The kept report to return (`GET /availability`)."""

    model_config = ConfigDict(extra="forbid")

    area_id: str = Field(
        min_length=1, description="Area id (`POST /areas`).", examples=[_AREA_ID]
    )
    product: str = Field(min_length=1, description="Product.", examples=["nmt"])
    producer: str = Field(default="kartograf", min_length=1, description="Producer id.")


class AvailabilityAreaItem(BaseModel):
    """The part of the area in one country, as the producer measured it."""

    model_config = ConfigDict(json_schema_extra={"examples": [_AREA_EXAMPLE]})

    country: str = Field(description="Country code (`PL`, `CZ`).")
    crs: str = Field(description="CRS of `bounds` and of the measures.")
    bounds: list[float] = Field(description="`[min_x, min_y, max_x, max_y]` in `crs`.")
    area_m2: float = Field(description="Area of the part, m².")
    land_m2: float = Field(
        description="Its land, m²: what every combination is measured against."
    )

    @classmethod
    def of(cls, area: AvailabilityArea) -> Self:
        """Return the model of a part of the area."""
        return cls(
            country=area.country,
            crs=area.crs,
            bounds=list(area.bounds),
            area_m2=area.area_m2,
            land_m2=area.land_m2,
        )


class AvailabilitySheetItem(BaseModel):
    """A record of the source that a download of the combination takes (KD-1)."""

    model_config = ConfigDict(json_schema_extra={"examples": [_SHEET_EXAMPLE]})

    sheet: str = Field(description="Sheet or tile code.")
    campaign: str | None = Field(description="The survey work it comes from.")
    full_sheet: bool | None = Field(
        description="Whether it fills its sheet; null when the source does not say."
    )
    acquisition_date: str | None = Field(description="Date of the survey (ISO).")
    published: str | None = Field(description="Date of the publication (ISO).")

    @classmethod
    def of(cls, sheet: AvailabilitySheet) -> Self:
        """Return the model of a sheet record."""
        return cls(
            sheet=sheet.sheet,
            campaign=sheet.campaign,
            full_sheet=sheet.full_sheet,
            acquisition_date=sheet.acquisition_date,
            published=sheet.published,
        )


class AvailabilityCampaignItem(BaseModel):
    """One campaign of the combination on its own (KD-1)."""

    model_config = ConfigDict(json_schema_extra={"examples": [_CAMPAIGN_EXAMPLE]})

    campaign: str = Field(description="The survey work.")
    complete: bool = Field(
        description="Its full records alone cover the land of the area."
    )
    full_m2: float = Field(description="The land in their frames, m².")

    @classmethod
    def of(cls, campaign: AvailabilityCampaign) -> Self:
        """Return the model of a campaign."""
        return cls(
            campaign=campaign.campaign,
            complete=campaign.complete,
            full_m2=campaign.full_m2,
        )


class AvailabilityCombinationItem(BaseModel):
    """One downloadable combination: a year, a variant and a format."""

    model_config = ConfigDict(json_schema_extra={"examples": [_COMBINATION_EXAMPLE]})

    country: str = Field(description="Country of the part of the area it covers.")
    product: str = Field(description="Product id.")
    source: str = Field(description="The producer's dataset.")
    year: int | None = Field(
        description="Year of the data; null where the source publishes none (CZ)."
    )
    horizontal: str = Field(description="Sheet system or horizontal CRS (`PL-1992`).")
    resolution: str | None = Field(
        description="Resolution (`1m`); null for point clouds."
    )
    vertical_crs: str = Field(description="Height system (`EVRF2007`).")
    format: str = Field(description="File format (`ASC`).")
    campaigns: list[str] = Field(
        description="Every survey work among its records, complete or not."
    )
    complete: bool = Field(
        description="The land of the area lies entirely in its full sheets."
    )
    sheets_full: list[str] = Field(description="Sheets with a full record.")
    sheets_partial: list[str] = Field(description="Sheets with partial records only.")
    sheets_missing: list[str] = Field(description="Sheets without a file.")
    uncovered_m2: float = Field(description="Land outside every sheet, m².")
    full_m2: float = Field(description="Land in the frames of its full records (KD-2).")
    size_bytes: int | None = Field(
        description="Size of its files when the source tells it; null otherwise."
    )
    published: list[str] | None = Field(
        description="First and last publication date of its files."
    )
    sheet_records: list[AvailabilitySheetItem] = Field(
        description="The records a download takes, by sheet (KD-1)."
    )
    campaign_coverage: list[AvailabilityCampaignItem] = Field(
        description="Each campaign of `campaigns` on its own (KD-1)."
    )

    @classmethod
    def of(cls, item: AvailabilityCombination) -> Self:
        """Return the model of a combination."""
        return cls(
            country=item.country,
            product=item.product,
            source=item.source,
            year=item.year,
            horizontal=item.horizontal,
            resolution=item.resolution,
            vertical_crs=item.vertical_crs,
            format=item.format,
            campaigns=list(item.campaigns),
            complete=item.complete,
            sheets_full=list(item.sheets_full),
            sheets_partial=list(item.sheets_partial),
            sheets_missing=list(item.sheets_missing),
            uncovered_m2=item.uncovered_m2,
            full_m2=item.full_m2,
            size_bytes=item.size_bytes,
            published=None if item.published is None else list(item.published),
            sheet_records=[AvailabilitySheetItem.of(s) for s in item.sheet_records],
            campaign_coverage=[
                AvailabilityCampaignItem.of(c) for c in item.campaign_coverage
            ],
        )


class AvailabilityFailureItem(BaseModel):
    """A part of the request the producer could not check."""

    model_config = ConfigDict(json_schema_extra={"examples": [_FAILURE_EXAMPLE]})

    part: str = Field(description="What failed, e.g. a country code.")
    detail: str = Field(description="The producer's text.")
    kind: str = Field(description="The producer's kind of failure (`country`).")

    @classmethod
    def of(cls, failure: AvailabilityFailure) -> Self:
        """Return the model of a failed part."""
        return cls(part=failure.part, detail=failure.detail, kind=failure.kind)


class AvailabilityNoticeItem(BaseModel):
    """Something the producer said while it checked."""

    model_config = ConfigDict(json_schema_extra={"examples": [_NOTICE_EXAMPLE]})

    level: Literal["info", "warning"] = Field(description="How much it matters.")
    code: str = Field(description="The producer's stable code.")
    message: str = Field(
        description="The producer's text, in the language of the check."
    )

    @classmethod
    def of(cls, notice: AvailabilityNotice) -> Self:
        """Return the model of a notice."""
        return cls(level=notice.level, code=notice.code, message=notice.message)


class AvailabilityReportItem(BaseModel):
    """The producer's report of what the source has, without its classes."""

    model_config = ConfigDict(
        serialize_by_alias=True,
        validate_by_alias=True,
        validate_by_name=True,
        json_schema_extra={"examples": [_REPORT_EXAMPLE]},
    )

    producer: str = Field(description="Producer id.")
    report_schema: str = Field(
        alias="schema",
        description="Schema of the producer's report (`kartograf-availability/1`).",
    )
    checked_at: datetime = Field(description="When the source was asked (UTC).")
    request: dict[str, Any] = Field(
        description="The request as the producer read it (product, country, area)."
    )
    areas: list[AvailabilityAreaItem] = Field(
        description="The parts of the area, one per country."
    )
    combinations: list[AvailabilityCombinationItem] = Field(
        description="What can be downloaded, in the producer's order."
    )
    failed: list[AvailabilityFailureItem] = Field(
        description="Parts of the request that could not be checked."
    )
    notices: list[AvailabilityNoticeItem] = Field(
        description="What the producer said meanwhile."
    )
    ok: bool = Field(description="Every part of the request was checked.")

    @classmethod
    def of(cls, report: AvailabilityReport) -> Self:
        """Return the model of a producer's report."""
        return cls(
            producer=report.producer,
            schema=report.schema,
            checked_at=report.checked_at,
            request=dict(report.request),
            areas=[AvailabilityAreaItem.of(area) for area in report.areas],
            combinations=[
                AvailabilityCombinationItem.of(item) for item in report.combinations
            ],
            failed=[AvailabilityFailureItem.of(item) for item in report.failed],
            notices=[AvailabilityNoticeItem.of(item) for item in report.notices],
            ok=report.ok,
        )


class AvailabilityInfo(BaseModel):
    """The last report of what the source has for an area and a product."""

    model_config = ConfigDict(json_schema_extra={"examples": [AVAILABILITY_EXAMPLE]})

    area: AreaRef = Field(description="The area the report is about.")
    producer: str = Field(description="Producer id.")
    product: str = Field(description="Product.")
    checked_at: datetime = Field(
        description=(
            "When the source was asked (UTC, whole seconds); a report younger"
            " than seven days answers `POST /availability` without a job."
        )
    )
    job_id: str | None = Field(
        description="The `availability` job that asked; it may be pruned since."
    )
    report: AvailabilityReportItem = Field(description="The producer's report.")

    @classmethod
    def of(cls, found: AreaAvailability) -> Self:
        """Return the model of a kept report with its area."""
        stored = found.stored
        return cls(
            area=AreaRef.of(found.area),
            producer=stored.producer,
            product=stored.product,
            checked_at=stored.checked_at,
            job_id=stored.job_id,
            report=AvailabilityReportItem.of(stored.report),
        )
