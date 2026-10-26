"""Models of the previews over HTTP and ``archiwista preview`` (plan v0.2, step 6).

``PreviewInfo`` describes the preview of one object (``GET …/preview``):
what it shows and in which state, why something is missing (a code with a
description and fix), its styles and legend, and the addresses of its
images, which the server builds and the client never composes (it only adds
the documented query parameters). The query models of ``preview.png``,
``tiles/…`` and ``features`` refuse unknown parameters (``422``), as do the
other query models of the API; ``WarmRequest``, the filters of ``POST
/previews/warm`` (v0.3, ADR-041), refuses unknown fields.
"""

import math
import re
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator

from archiwista.api.models import WGS84
from archiwista.jobs import JobRecord, JobState
from archiwista.messages import message
from archiwista.previews.types import (
    PreviewKind,
    PreviewReason,
    PreviewState,
    StyleName,
)

# Sides of a thumbnail in pixels; the default.
THUMBNAIL_SIZES = (128, 256, 512, 1024)
DEFAULT_THUMBNAIL_SIZE = 256
# Zoom levels of map tiles and of the features of a view (decision 13).
MAX_ZOOM = 22
# Features of one answer at most (decision 4).
FEATURES_LIMIT = 5000
_EPSG = re.compile(r"EPSG:[0-9]{4,6}")

_REF = (
    "version:zespol:nmt/pl_1992_1m_evrf2007/versions/N-34/130/D/d/2/4/"
    "2025-04-26_82710_fdd30535/N-34-130-D-d-2-4.asc"
)
_BASE = (
    "/api/v1/stores/zespol/versions/nmt/pl_1992_1m_evrf2007/versions/N-34/130/D/"
    "d/2/4/2025-04-26_82710_fdd30535/N-34-130-D-d-2-4.asc"
)
_INFO_EXAMPLE: dict[str, Any] = {
    "ref": _REF,
    "state": "ready",
    "kind": "raster",
    "reason": None,
    "styles": ["hillshade", "hypsometry"],
    "default_style": "hillshade",
    "thumbnail_url": f"{_BASE}/preview.png",
    "tiles_url": f"{_BASE}/tiles/{{z}}/{{x}}/{{y}}.png",
    "features_url": None,
    "members_url": None,
    "bounds": [19.9375, 50.0417, 19.9688, 50.0625],
    "minzoom": 10,
    "maxzoom": 19,
    "legend": None,
    "legends": {
        "hypsometry": {
            "kind": "gradient",
            "min": 212.4,
            "max": 455.1,
            "unit": "m",
            "colors": ["#2e7d48", "#96c46b", "#f2e28c", "#c48a52", "#f6f1eb"],
        }
    },
    "layers": [],
    "points": None,
    "size_bytes": 37798349,
    "auto_build": True,
    "job": None,
}


class PreviewReasonInfo(BaseModel):
    """Why a file has no preview, or no map preview."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "code": "no_georeference",
                    "message": message("preview.reason_no_georeference", "en"),
                    "fix": message("preview.fix_no_georeference", "en"),
                    "detail": None,
                }
            ]
        }
    )

    code: PreviewReason = Field(
        description=(
            "Stable code: `no_georeference`, `no_crs`, `auxiliary_file`,"
            " `archive_members_only`, `document_no_preview`,"
            " `unsupported_format`, `too_large`, `missing_file`,"
            " `store_unavailable`, `transform_unavailable`, `unreadable`,"
            " `timeout`, `memory_limit` or `changed_since_scan`."
        )
    )
    message: str = Field(description="What is missing and why.")
    fix: str = Field(description="What a person can do about it.")
    detail: str | None = Field(
        default=None,
        description=(
            "The library's own message (no paths), only in the answer that found it."
        ),
    )

    @classmethod
    def of(cls, code: PreviewReason, detail: str | None = None) -> Self:
        """Return a reason with its description and fix."""
        return cls(
            code=code,
            message=message(f"preview.reason_{code}"),
            fix=message(f"preview.fix_{code}"),
            detail=detail,
        )


class PreviewJob(BaseModel):
    """The ``preview`` job building a file's preview (`/jobs/{id}`)."""

    id: str
    state: JobState

    @classmethod
    def of(cls, job: JobRecord) -> Self:
        """Return the job of a record."""
        return cls(id=job.id, state=job.state)


class GradientLegend(BaseModel):
    """Colours from `min` to `max` of continuous values (hypsometry)."""

    kind: Literal["gradient"]
    min: float
    max: float
    unit: str | None = Field(description="Unit of the values, e.g. `m`.")
    colors: list[str] = Field(
        description="Colours of the ramp from `min` to `max`, evenly spaced, `#rrggbb`."
    )


class LegendClass(BaseModel):
    """One class of a classes legend."""

    value: float = Field(description="The value in the file.")
    color: str = Field(description="`#rrggbb`.")
    label: str = Field(description="Polish name of the class, else the value.")


class ClassesLegend(BaseModel):
    """Classes with their colours (CORINE, HSG, a palette of the file)."""

    kind: Literal["classes"]
    items: list[LegendClass]


class PreviewInfo(BaseModel):
    """The preview of one object: state, styles, legend, addresses, build."""

    model_config = ConfigDict(json_schema_extra={"examples": [_INFO_EXAMPLE]})

    ref: str = Field(description="The object (`version:<store>:<path>`).")
    state: PreviewState = Field(
        description=(
            "`ready` (what the file shows is available), `needs_build` (map"
            " tiles need a local preview first: POST the preview; with"
            " `auto_build` the interface does it at once), `building` (`job`"
            " builds it), `unavailable` (nothing to show: `reason`) or"
            " `failed` (a time or memory limit: try again later)."
        )
    )
    kind: PreviewKind = Field(
        description=(
            "`raster`, `image`, `vector`, `points`, `archive`, `document`,"
            " `auxiliary` or `unknown`."
        )
    )
    reason: PreviewReasonInfo | None = Field(
        description="Why something is missing (no map, no preview); null otherwise."
    )
    styles: list[StyleName] = Field(
        description="Styles of the thumbnail and tiles (`style`); empty without them."
    )
    default_style: StyleName | None = Field(
        description="The style without `style`, chosen by the product."
    )
    thumbnail_url: str | None = Field(
        description="PNG thumbnail; add `style`, `size` (128–1024) or a frame."
    )
    tiles_url: str | None = Field(
        description=(
            "Map tiles (EPSG:3857, 256 px) as a `{z}/{x}/{y}` template within"
            " `minzoom`–`maxzoom` and `bounds`; add `style` or `rescale`."
        )
    )
    features_url: str | None = Field(
        description=(
            "Features of a map view as GeoJSON in WGS84: a template with"
            " `{bbox}` (west,south,east,north) and `{zoom}`; add `layer`, `limit`."
        )
    )
    members_url: str | None = Field(description="Members of an archive.")
    bounds: list[float] | None = Field(
        description="Extent in WGS84: west, south, east, north."
    )
    minzoom: int | None
    maxzoom: int | None
    legend: GradientLegend | ClassesLegend | None = Field(
        description="Legend of the default style; null without one."
    )
    legends: dict[StyleName, GradientLegend | ClassesLegend] = Field(
        description=(
            "Legend of every style that has one (`hypsometry`, `elevation`,"
            " `classes`), by style; the thumbnail and tiles of that style."
        )
    )
    layers: list[dict[str, Any]] = Field(
        description=(
            "Layers of a vector file: name, geometry type, feature count,"
            " fields, extent, sample rows."
        )
    )
    points: dict[str, Any] | None = Field(
        description="Header, density and classes of a point cloud (LAZ, LAS)."
    )
    size_bytes: int | None
    auto_build: bool = Field(
        description=(
            "Whether the build starts at the first view: a file of at most"
            " 2 GB, a raster of at most 1 Gpx and 8 GB unpacked (decision 6)."
        )
    )
    job: PreviewJob | None = Field(description="The job building it, if any.")


class ArchiveMember(BaseModel):
    """A member of a ZIP archive, as its central directory lists it."""

    name: str = Field(description="Name in the archive, as written (not unpacked).")
    size_bytes: int
    compressed_bytes: int
    directory: bool
    format: str = Field(description="Format by the name's extension.")
    kind: PreviewKind


class ArchiveMembers(BaseModel):
    """Members of an archive, read without unpacking it."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "ref": "version:zespol:bdot10k/pl_shp/1465/bdot10k_1465.zip",
                    "total": 2,
                    "truncated": False,
                    "members": [
                        {
                            "name": "PL.PZGiK.994.1465__OT_SWRS_L.shp",
                            "size_bytes": 4417092,
                            "compressed_bytes": 2118842,
                            "directory": False,
                            "format": "Shapefile",
                            "kind": "vector",
                        }
                    ],
                }
            ]
        }
    )

    ref: str
    total: int = Field(description="Members the archive declares.")
    truncated: bool = Field(description="More than the first 10 000 are not listed.")
    members: list[ArchiveMember]


class ThumbnailQuery(BaseModel):
    """Style, size and frame of `GET …/preview.png`."""

    model_config = ConfigDict(extra="forbid")

    style: str | None = Field(
        default=None, description="A style of `styles`; the default one when left out."
    )
    size: int = Field(
        default=DEFAULT_THUMBNAIL_SIZE,
        description="Longest side in pixels: 128, 256, 512 or 1024.",
    )
    bbox: str | None = Field(
        default=None,
        description=(
            "Frame `min_x,min_y,max_x,max_y` in `bbox_crs`; the whole file without."
        ),
    )
    bbox_crs: str = Field(default=WGS84, description="CRS of `bbox`, `EPSG:<code>`.")

    @field_validator("size")
    @classmethod
    def _check_size(cls, value: int) -> int:
        if value not in THUMBNAIL_SIZES:
            raise ValueError(message("preview.size_invalid"))
        return value

    @field_validator("bbox")
    @classmethod
    def _check_bbox(cls, value: str | None) -> str | None:
        if value is not None:
            _numbers(value, 4, ordered=True)
        return value

    @field_validator("bbox_crs")
    @classmethod
    def _check_crs(cls, value: str) -> str:
        if _EPSG.fullmatch(value.upper()) is None:
            raise ValueError(message("preview.crs_invalid"))
        return value.upper()

    def frame(self) -> dict[str, Any] | None:
        """Return the frame for the render process, or ``None``."""
        if self.bbox is None:
            return None
        return {"bbox": list(_numbers(self.bbox, 4)), "crs": self.bbox_crs}


class TileQuery(BaseModel):
    """Style and value range of `GET …/tiles/{z}/{x}/{y}.png`."""

    model_config = ConfigDict(extra="forbid")

    style: str | None = Field(
        default=None, description="A style of `styles`; the default one when left out."
    )
    rescale: str | None = Field(
        default=None,
        description="`min,max` of a hypsometry's colours instead of p2–p98.",
        examples=["200,450"],
    )

    @field_validator("rescale")
    @classmethod
    def _check_rescale(cls, value: str | None) -> str | None:
        if value is not None:
            _numbers(value, 2, ordered=True)
        return value

    def rescale_values(self) -> list[float] | None:
        """Return ``rescale`` as two numbers."""
        return None if self.rescale is None else list(_numbers(self.rescale, 2))


class FeaturesQuery(BaseModel):
    """View, zoom, layer and limit of `GET …/features`."""

    model_config = ConfigDict(extra="forbid")

    bbox: str = Field(
        description="The view `west,south,east,north` in WGS84.",
        examples=["19.0,49.5,19.6,49.9"],
    )
    zoom: int = Field(
        ge=0,
        le=MAX_ZOOM,
        description="Zoom of the view: geometries are simplified to it.",
    )
    layer: str | None = Field(
        default=None, description="A layer of `layers`; the largest ones when left out."
    )
    limit: int = Field(
        default=FEATURES_LIMIT,
        ge=1,
        le=FEATURES_LIMIT,
        description="Features at most; more give `truncated`.",
    )

    @field_validator("bbox")
    @classmethod
    def _check_bbox(cls, value: str) -> str:
        west, south, east, north = _numbers(value, 4, ordered=True)
        if not (west >= -180 and east <= 180 and south >= -90 and north <= 90):
            raise ValueError(message("api.bbox_invalid"))
        return value

    def bbox_values(self) -> list[float]:
        """Return the view as four numbers."""
        return list(_numbers(self.bbox, 4))


class BuildRequest(BaseModel):
    """What `POST …/preview` reads; no body builds within the limits."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"force": False}]}
    )

    force: bool = Field(
        default=False,
        description=(
            "Build also past the auto-build limits (the build button of the interface):"
            " a file over 2 GB, a raster over 1 Gpx or 8 GB unpacked."
        ),
    )


class WarmRequest(BaseModel):
    """What `POST /previews/warm` prepares; no body: every store's current versions."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"store": "zespol", "product": "nmt"},
                {"project": "raba"},
                {"area_id": "5f2b9c0e7d41a3b6", "segment": "pl_1992_1m_evrf2007"},
            ]
        },
    )

    store: str | None = Field(
        default=None,
        min_length=1,
        description="Only the current versions of this configured store (its id).",
    )
    product: str | None = Field(
        default=None,
        min_length=1,
        description="Only the current versions of this product (`nmt`, `orto`…).",
    )
    segment: str | None = Field(
        default=None,
        min_length=1,
        description="Only the current versions of this segment (variant) of a product.",
    )
    project: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Only the current versions this project pins and the working files of"
            " its own data (`project` of /projects); without it no project's own"
            " data is prepared. A project the session does not see is `404`."
        ),
    )
    area_id: str | None = Field(
        default=None,
        min_length=1,
        description="Only the current versions within this area (`POST /areas`).",
    )


def legend_model(
    legend: dict[str, Any] | None,
) -> GradientLegend | ClassesLegend | None:
    """Return a renderer's legend (``archiwista.previews.legends``) as its model."""
    if legend is None:
        return None
    if legend.get("kind") == "classes":
        return ClassesLegend.model_validate(legend)
    return GradientLegend.model_validate(legend)


def _numbers(text: str, count: int, *, ordered: bool = False) -> tuple[float, ...]:
    """Parse ``count`` finite numbers separated by commas (``422`` otherwise).

    ``ordered``: each of the first half is below its pair in the second half
    (``min < max``).
    """
    try:
        values = tuple(float(part) for part in text.split(","))
    except ValueError:
        values = ()
    valid = len(values) == count and all(math.isfinite(value) for value in values)
    half = count // 2
    if valid and ordered:
        valid = all(values[i] < values[i + half] for i in range(half))
    if not valid:
        raise ValueError(message("preview.numbers_invalid", count=count))
    return values
