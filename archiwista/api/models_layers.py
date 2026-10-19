"""Models of the local layers (plan v0.2, step 11; decision 7).

``LayerSet`` answers ``GET /local-layers`` and ``archiwista layers``: the
layers of a store's product — a variant × a data year, an edition or a
label, with ``group=campaign`` a year split by campaign — newest first. With
an area each layer has its local coverage in the area's planar CRS, its
outlines in that CRS, its versions with the state of their previews and the
addresses of its thumbnail and map tiles, which the server builds and the
client never composes (it only adds ``size`` and ``style``). Without an area
only the counts. The query models refuse unknown parameters (``422``).
"""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from archiwista.api.models import AreaRef, CountryCoverage, IndexAnswer
from archiwista.api.models_previews import (
    DEFAULT_THUMBNAIL_SIZE,
    THUMBNAIL_SIZES,
    PreviewJob,
)
from archiwista.messages import MESSAGES
from archiwista.previews.types import PreviewState

type LayerKind = Literal["year", "edition", "label", "campaign"]
type LayerGroup = Literal["year", "campaign"]

_STORE = "zespol"
_AREA = "3f9c2a71d04e8b65"
_LAYER = "5d41402abc4b:2023"
_QUERY = f"store={_STORE}&product=nmt&area_id={_AREA}&group=year&layer={_LAYER}"
_VERSION = (
    "nmt/pl_1992_1m_evrf2007/versions/N-34/130/D/d/2/4/"
    "2023-06-02_82710_fdd30535/N-34-130-D-d-2-4.asc"
)
_EXAMPLE: dict[str, Any] = {
    "area": {
        "id": _AREA,
        "name": "Kraków",
        "area_km2": 12.7,
        "countries": ["PL"],
    },
    "store": _STORE,
    "product": "nmt",
    "segment": None,
    "group": "year",
    "frame": {"crs": "EPSG:2180", "bbox": [565_000.0, 241_000.0, 571_000.0, 245_000.0]},
    "layers": [
        {
            "key": _LAYER,
            "variant": {
                "product": "nmt",
                "horizontal_crs": "EPSG:2180",
                "resolution": "1m",
                "vertical_crs": "EPSG:9651",
                "segments": [
                    "nmt/pl_1992_1m_evrf2007",
                    "nmt/pl_1992_ascii-nmt_1m_evrf2007",
                ],
                "formats": ["ASCII Grid", "ZIP"],
            },
            "kind": "year",
            "year": 2023,
            "title": "2023",
            "subtitle": "Numeryczny Model Terenu 1 m (siatka ASC) · PL-1992 · EVRF2007",
            "versions_count": 4,
            "units_count": 2,
            "campaigns": ["82710"],
            "data_dates": ["2023-06-02"],
            "coverage": {
                "ratio": 0.83,
                "percent": 83,
                "label": "lokalnie 83% obszaru",
            },
            "outlines": {"type": "FeatureCollection", "features": []},
            "preview": {
                "state": "building",
                "ready": 1,
                "total": 2,
                "job": {"id": "8c2f0a91d3b4e5f6", "state": "running"},
                "thumbnail_url": (
                    f"/api/v1/local-layers/thumbnail.png?{_QUERY}&v=0b1c2d3e4f5a6b7c"
                ),
                "tiles_url": (
                    "/api/v1/local-layers/tiles/{z}/{x}/{y}.png"
                    f"?{_QUERY}&v=0b1c2d3e4f5a6b7c"
                ),
                "minzoom": 11,
            },
            "versions": [
                {
                    "ref": f"version:{_STORE}:{_VERSION}",
                    "slot": (
                        "nmt/pl_1992_1m_evrf2007/N-34/130/D/d/2/4/N-34-130-D-d-2-4.asc"
                    ),
                    "unit": "N-34-130-D-d-2-4",
                    "preview": {
                        "state": "ready",
                        "tiles_url": (
                            f"/api/v1/stores/{_STORE}/versions/{_VERSION}"
                            "/tiles/{z}/{x}/{y}.png"
                        ),
                    },
                    "bounds": [19.9375, 50.0417, 19.9688, 50.0625],
                }
            ],
        }
    ],
    "stale": False,
    "stale_stores": [],
    "stale_reason": None,
}


class LayersQuery(BaseModel):
    """The store, product, area and grouping of `GET /local-layers`."""

    model_config = ConfigDict(extra="forbid")

    store: str = Field(description="Store id.", examples=[_STORE])
    product: str = Field(description="Product, e.g. `nmt`.", examples=["nmt"])
    area_id: str | None = Field(
        default=None,
        description=(
            "Area id (`POST /areas`); without one, only the counts of the whole"
            " store's versions per layer."
        ),
        examples=[_AREA],
    )
    segment: str | None = Field(
        default=None,
        description="Only this segment of the product.",
        examples=["nmt/pl_1992_1m_evrf2007"],
    )
    group: LayerGroup = Field(
        default="year",
        description=(
            "`year`: a layer per data year; `campaign`: a year split by campaign."
        ),
    )


class LayerImageQuery(LayersQuery):
    """The layer of an image: the query of its `LayerSet`, the key and `v`."""

    area_id: str = Field(
        description="Area id of the `LayerSet` the address came from.",
        examples=[_AREA],
    )
    layer: str = Field(description="`key` of the layer.", examples=[_LAYER])
    style: str | None = Field(
        default=None,
        description="A style of the layer's versions; their usual one when left out.",
    )
    v: str | None = Field(
        default=None,
        description=(
            "Digest of the layer's ready previews, from the address; a new one"
            " comes with every preview that gets ready."
        ),
    )


class LayerThumbnailQuery(LayerImageQuery):
    """`GET /local-layers/thumbnail.png`: a layer's image in the area's frame."""

    size: int = Field(
        default=DEFAULT_THUMBNAIL_SIZE,
        description="Longest side in pixels: 128, 256, 512 or 1024.",
    )

    @field_validator("size")
    @classmethod
    def _check_size(cls, value: int) -> int:
        if value not in THUMBNAIL_SIZES:
            raise ValueError(MESSAGES["preview_size_invalid"])
        return value


class LayerTileQuery(LayerImageQuery):
    """`GET /local-layers/tiles/{z}/{x}/{y}.png`: a layer's map tile."""


class LayerFrame(BaseModel):
    """The area's box in its planar CRS: where outlines and thumbnails are drawn."""

    crs: str = Field(description="Planar CRS, e.g. `EPSG:2180` (PL), `EPSG:5514` (CZ).")
    bbox: list[float] = Field(description="`[min_x, min_y, max_x, max_y]` in `crs`.")


class LayerVariant(BaseModel):
    """The variant of a layer: no file format in it (A-ADR-017, SPEC 6.4)."""

    product: str | None
    horizontal_crs: str | None
    resolution: str | None
    vertical_crs: str | None
    segments: list[str] = Field(description="Segments of the layer's versions.")
    formats: list[str] = Field(
        description="Formats of the layer's files, shown as badges, e.g. `ASCII Grid`."
    )


class LayerCoverage(BaseModel):
    """Share of the area under the layer's versions, in the frame's CRS."""

    ratio: float | None = Field(
        description="0–1, overlaps counted once; null for an area without surface."
    )
    percent: int | None = Field(
        description="`ratio` in whole percent, rounded down: 100 only if fully covered."
    )
    label: str = Field(description="Polish text, e.g. „lokalnie 83% obszaru”.")

    @classmethod
    def of(cls, coverage: CountryCoverage) -> "LayerCoverage":
        """Return the share of a measure made like `/local-coverage`."""
        return cls(ratio=coverage.ratio, percent=coverage.percent, label=coverage.label)


class LayerPreview(BaseModel):
    """The previews of a layer's versions and the addresses of its images."""

    state: PreviewState = Field(
        description=(
            "`ready` when every version that can be shown is, `building` while a"
            " `preview` job builds the missing ones, `needs_build` without one,"
            " `unavailable` when no version can be shown on a map."
        )
    )
    ready: int = Field(description="Versions with a ready preview.")
    total: int = Field(description="Versions that can have one.")
    job: PreviewJob | None = Field(
        description="The `preview` job building the missing ones (`/jobs/{id}`)."
    )
    thumbnail_url: str | None = Field(
        description=(
            "The layer's image in `frame` (add `size`, `style`); null without a frame."
        )
    )
    tiles_url: str | None = Field(
        description="Map tiles of the layer, one raster source (add `style`)."
    )
    minzoom: int | None = Field(
        description=(
            "Zoom from which a typical sheet of the layer has at least 32 pixels;"
            " below it the tiles are `404` (show the outlines)."
        )
    )


class LayerVersionPreview(BaseModel):
    """The preview of one version of a layer."""

    state: PreviewState
    tiles_url: str | None = Field(description="Map tiles of the version when ready.")


class LayerVersion(BaseModel):
    """A version of a layer in the area."""

    ref: str = Field(description="The version's `ref` (decision 10).")
    slot: str = Field(description="Its slot path.")
    unit: str | None = Field(description="Its sheet or unit, e.g. `N-34-130-D-d-2-4`.")
    preview: LayerVersionPreview
    bounds: list[float] | None = Field(
        description="WGS84 `[west, south, east, north]`."
    )


class Layer(BaseModel):
    """A layer: a variant's data year, edition, label or campaign."""

    key: str = Field(
        description=(
            "`<variant>:<year|edition|label>[:<campaign>]`; the variant is 12"
            " characters of the SHA-256 of its key, or the segment."
        )
    )
    variant: LayerVariant
    kind: LayerKind
    year: int | None = Field(description="Data year, never the download's.")
    title: str = Field(description="Polish, e.g. `2023` or `wydanie 2021`.")
    subtitle: str = Field(description="The variant's name.")
    versions_count: int
    units_count: int = Field(
        description="Sheets or units: one in two formats counts once."
    )
    campaigns: list[str]
    data_dates: list[date]
    coverage: LayerCoverage | None = Field(description="With an area only.")
    outlines: dict[str, Any] | None = Field(
        description=(
            "GeoJSON `FeatureCollection` of `versions` in `frame.crs` (`ref` in"
            " `properties`); with an area in a planar CRS only."
        )
    )
    preview: LayerPreview | None = Field(description="With an area only.")
    versions: list[LayerVersion] | None = Field(
        description="At most 500, newest first; with an area only."
    )


class LayerSet(IndexAnswer):
    """Layers of a product in the store (decision 7), newest first.

    With an area, its slots are rescanned first (at most 500), unless they
    were in the last minute; an unavailable store, a rescan out of time or
    too many slots answer from the index, with `stale` and `stale_reason`.
    """

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE]})

    area: AreaRef | None
    store: str = Field(description="Store id.")
    product: str = Field(description="Product, e.g. `nmt`.")
    segment: str | None = Field(description="The only segment, if asked for.")
    group: LayerGroup
    frame: LayerFrame | None = Field(
        description="Null without an area, or for one outside PL and CZ."
    )
    layers: list[Layer]
    stale_reason: str | None = Field(
        description=(
            "Why the slots were not rescanned first: `store_unavailable`,"
            " `refresh_timeout` or `too_many_slots`; null when they were."
        )
    )
