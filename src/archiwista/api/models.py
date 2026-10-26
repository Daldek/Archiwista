"""Models of the read API: one Pydantic set for JSON responses and OpenAPI.

Each model carries an example, so ``/api/v1/openapi.json`` shows agents a
complete answer. Field names are English ``snake_case``; texts for people
(problem messages and instructions) are English, and Polish for a request
that says ``Accept-Language: pl``. Stores are named by their
configured id and files by paths relative to the store; the only absolute
paths are the file card's "copy path" (``CopyPath``), given for this
computer and for every alias of the store (SPEC 4.6), the settings and the
default store root of a producer that ``/sources`` reports.

Answers from the index carry ``stale`` and ``stale_stores``: a store that is
unavailable (a disconnected share) is still answered from the index as it
was at its last complete pass (``indexed_at``), never as an empty result.
The ``of`` constructors turn index and service values into these models;
the command line prints the same models (``--json``).
"""

import math
import re
from collections.abc import Collection, Iterable, Sequence
from datetime import date, datetime
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from archiwista.areas import area_crs
from archiwista.auth import PrincipalKind, WritableProjects
from archiwista.config import (
    AppSettings,
    BasemapConfig,
    BasemapKind,
    DefaultProjectVisibility,
    StoreConfig,
    StoreKind,
)
from archiwista.error_document import REGISTRY_PAGE
from archiwista.index import (
    DEFAULT_GRID_COLUMNS,
    DEFAULT_PAGE_LIMIT,
    MAP_FOOTPRINT_LIMIT,
    MAX_GRID_COLUMNS,
    MAX_PAGE_LIMIT,
    AreaFilter,
    AreaRecord,
    BBox,
    FootprintPage,
    GridCell,
    GroupMember,
    IndexStatus,
    JobRef,
    LocalCoverage,
    LocalCoverageReport,
    LocationCounts,
    LocationFilter,
    LocationRef,
    MapFootprint,
    MapQuery,
    PinRef,
    PinState,
    ProductSummary,
    ProductUsage,
    ProjectManifestRef,
    ProjectPinRef,
    ProjectRef,
    ProjectTaskRef,
    RowStatus,
    ScanMode,
    SegmentRef,
    SlotDetail,
    SlotPage,
    SlotQuery,
    SlotRow,
    StoreFreshness,
    StoreIndexState,
    StoreStatus,
    StoreUsage,
    UnusedVersions,
    VersionDetail,
    VersionsMode,
    VersionState,
    VersionSummary,
)
from archiwista.index.geometry import polygon_bounds
from archiwista.jobs import JobKind, JobPage, JobRecord, JobState, LogTail, ScanHistory
from archiwista.messages import current_language, message, with_detail
from archiwista.previews.cache import CacheUsage
from archiwista.refs import version_ref
from archiwista.services import Problem, ProjectDetail, StoreSummary
from archiwista.services.project_jobs import ProjectJobKind
from archiwista.sources import (
    DefaultRoot,
    DefaultRootSource,
    LocationKind,
    SourceState,
    SourceStatus,
)

type Geometry = dict[str, Any]
type YearRange = tuple[int | None, int | None]

YEARS_PATTERN = r"^(\d{4}|\d{4}-\d{4}|\d{4}-|-\d{4})$"
WGS84 = "EPSG:4326"

_STORE = "zespol"
_PROJECT_DIRS = "/mnt/nas/projekty"
_SEGMENT = "nmt/pl_1992_1m_evrf2007"
_SLOT = f"{_SEGMENT}/N-34/130/D/d/2/4/N-34-130-D-d-2-4.asc"
_VERSION = (
    f"{_SEGMENT}/versions/N-34/130/D/d/2/4/2025-04-26_82710_fdd30535/"
    "N-34-130-D-d-2-4.asc"
)
_OLDER = (
    f"{_SEGMENT}/versions/N-34/130/D/d/2/4/2019-07-12_41022_a0b1c2d3/"
    "N-34-130-D-d-2-4.asc"
)
_SHA256 = "fdd30535e8085f861a106824ba4401a7e96187a6c54abc33511803acd87b4623"
_POLYGON: Geometry = {
    "type": "Polygon",
    "coordinates": [
        [
            [19.9375, 50.0417],
            [19.9688, 50.0417],
            [19.9688, 50.0625],
            [19.9375, 50.0625],
            [19.9375, 50.0417],
        ]
    ],
}
_SEGMENT_EXAMPLE = {
    "path": _SEGMENT,
    "label": "NMT 1 m · PL-1992 · EVRF2007",
    "producer": "kartograf",
    "product": "nmt",
    "country": "PL",
    "dataset_key": "pl.gugik.nmt_1m",
    "known": True,
}
_LOCATION_EXAMPLE = {"kind": "footprint", "reason": None, "source": "sheet"}
_PIN_EXAMPLE = {
    "project": "raba",
    "name": "Raba",
    "task": "teren",
    "sha256": _SHA256,
    "state": "ok",
}
_VERSION_EXAMPLE = {
    "path": _VERSION,
    "ref": f"version:{_STORE}:{_VERSION}",
    "label": "2025-04-26_82710",
    "label_source": "campaign",
    "data_year": 2025,
    "data_date": "2025-04-26",
    "downloaded_at": "2026-05-04T09:12:44Z",
    "sha256": _SHA256,
    "size_bytes": 37798349,
    "full_sheet": True,
    "crs": {"horizontal": "EPSG:2180", "vertical": "EPSG:9651"},
    "is_current": True,
    "is_full_sheet": True,
    "state": "present",
    "missing_since": None,
    "location": _LOCATION_EXAMPLE,
    "pinned_by": [_PIN_EXAMPLE],
}
_KARTOGRAF_FIX = message("fix.install", "en", requirement="kartograf<0.9,>=0.8.0")
_STALE_STORE_EXAMPLE = {
    "store": _STORE,
    "status": "unavailable",
    "status_at": "2026-10-18T13:40:00Z",
    "indexed_at": "2026-10-18T12:02:31Z",
    "detail": message("store.unreadable", "en", path="/mnt/nas/kartograf/data"),
}
_JOB_EXAMPLE = {
    "id": "j-2026-10-18-0007",
    "kind": "scan",
    "state": "succeeded",
    "actor": "local",
    "created_at": "2026-10-18T12:00:00Z",
    "started_at": "2026-10-18T12:00:01Z",
    "finished_at": "2026-10-18T12:02:31Z",
    "progress": {"current": 41, "total": 41},
}
_JOB_FAILURE_EXAMPLE = {
    "code": "store_unavailable",
    "detail": message("store.unreadable", "en", path="/mnt/nas/kartograf/data"),
    "hint": None,
    "details": {"reason": "store_unreadable"},
}
_JOB_DETAIL_EXAMPLE = {
    "id": "3f9c1a7e5b2d4c60",
    "kind": "scan",
    "state": "succeeded",
    "actor": "local",
    "actor_kind": "scheduler",
    "session": None,
    "store": _STORE,
    "params": {"mode": "incremental", "segment": None},
    "created_at": "2026-10-18T12:00:00Z",
    "started_at": "2026-10-18T12:00:01Z",
    "finished_at": "2026-10-18T12:00:20Z",
    "progress": {"current": 41, "total": 41, "segment": _SEGMENT, "entries": 80000},
    "result": {
        "store": _STORE,
        "mode": "incremental",
        "segment": None,
        "seconds": 19.2,
        "entries": 80000,
        "versions_written": 12,
        "links_changed": 3,
        "issues_added": 0,
        "footprints_written": 12,
        "footprints_failed": 0,
        "missing": 0,
        "reappeared": 0,
        "removed": 0,
        "slots_removed": 0,
        "unlinked": 0,
        "issues_resolved": 1,
        "segments": [
            {
                "producer": "kartograf",
                "segment": _SEGMENT,
                "entries": 52000,
                "seconds": 11.4,
            }
        ],
        "projects": {
            "found": 4,
            "read": 1,
            "unchanged": 3,
            "invalid": 0,
            "unknown_store": 0,
            "removed": 0,
            "unreadable_dirs": [],
        },
    },
    "error": None,
}
_JOB_FAILED_EXAMPLE = {
    "id": "9b2e44d01c7f3a85",
    "kind": "footprints",
    "state": "failed",
    "actor": "local",
    "actor_kind": "agent",
    "session": "5b2d4c60",
    "store": _STORE,
    "params": {},
    "created_at": "2026-10-18T13:40:00Z",
    "started_at": "2026-10-18T13:40:00Z",
    "finished_at": "2026-10-18T13:40:02Z",
    "progress": None,
    "result": None,
    "error": _JOB_FAILURE_EXAMPLE,
}
_STORE_STATE_EXAMPLE = {
    "status": "available",
    "status_at": "2026-10-18T12:02:31Z",
    "detail": None,
    "indexed_at": "2026-10-18T12:02:31Z",
    "full_scan_at": "2026-10-18T03:14:07Z",
    "slots": 50000,
    "versions": 80000,
    "missing_versions": 3,
    "unlocated_versions": 1204,
    "issues": 7,
    "last_scan": _JOB_EXAMPLE,
    "running_job": None,
    "stale": False,
}
_STORE_EXAMPLE = {
    "store": _STORE,
    "name": "Zespół",
    "kind": "share",
    "producers": ["kartograf"],
    "state": _STORE_STATE_EXAMPLE,
}
_SOURCE_EXAMPLE = {
    "producer": "kartograf",
    "status": "available",
    "package_version": "0.8.0.dev0",
    "supported_versions": ">=0.8.0.dev0,<0.9",
    "schemas": ["kartograf-meta/1", "kartograf-project/1", "kartograf-store/1"],
    "detail": None,
    "message": (
        "Wtyczka kartograf: wersja 0.8.0.dev0 (wspierane >=0.8.0.dev0,<0.9;"
        " schematy: kartograf-meta/1, kartograf-project/1, kartograf-store/1)"
    ),
    "fix": None,
}
_DEFAULT_ROOT_EXAMPLE = {
    "path": "/home/anna/.local/share/nogat/kartograf",
    "source": "default",
    "name": None,
    "exists": True,
    "marked": True,
    "message": message(
        "doctor.default_root",
        "en",
        producer="kartograf",
        path="/home/anna/.local/share/nogat/kartograf",
        origin=message("doctor.default_root_default", "en"),
        state=message("doctor.default_root_marked", "en"),
    ),
}
_LISTED_SOURCE_EXAMPLE = {
    **_SOURCE_EXAMPLE,
    "default_root": _DEFAULT_ROOT_EXAMPLE,
    "availability": ["nmt", "nmpt", "laz"],
}
_MANIFEST_EXAMPLE = {
    "producer": "kartograf",
    "store": _STORE,
    "status": "ok",
    "problem": None,
    "scanned_at": "2026-10-18T12:02:30Z",
}
_IMGW_MANIFEST_EXAMPLE = {
    "producer": "imgw",
    "store": _STORE,
    "status": "not_downloaded",
    "problem": None,
    "scanned_at": "2026-10-18T12:02:31Z",
}
_PROJECT_EXAMPLE = {
    "project": "raba",
    "name": "Raba",
    "manifests": [_MANIFEST_EXAMPLE, _IMGW_MANIFEST_EXAMPLE],
    "tasks": 2,
    "pins": 14,
    "missing_pins": 0,
    "project_write": True,
}
_PROJECT_WRITE = (
    "Whether the session's principal may change the project now (`project.write`:"
    " its owner or an administrator), read at each request: add and remove its"
    " tasks, and download and repin it with `store_write` of `GET /session`."
    " Without it those requests are `403 permission_denied`."
)
_ISSUE_EXAMPLE = {
    "code": "missing_sidecar",
    "message": message(
        "problem.missing_sidecar",
        "en",
        path="nmt/pl_1992_1m_evrf2007/versions/…/N-34-130-D-d-2-4.asc",
    ),
    "instruction": message("fix.missing_sidecar", "en", producer="kartograf"),
    "path": f"{_SEGMENT}/versions/N-34/130/D/d/2/4/2016_1a2b3c4d/N-34-130-D-d-2-4.asc",
    "segment": _SEGMENT,
    "slot": _SLOT,
    "project": None,
    "task": None,
    "origin": "scan",
    "first_seen_at": "2026-10-18T12:02:30Z",
}
_FRESH = {"stale": False, "stale_stores": []}
_SLOT_ITEM_EXAMPLE = {
    "store": _STORE,
    "slot": _SLOT,
    "name": "N-34-130-D-d-2-4.asc",
    "segment": _SEGMENT_EXAMPLE,
    "unit": "N-34-130-D-d-2-4",
    "product": "nmt",
    "country": "PL",
    "status": "ok",
    "location": _LOCATION_EXAMPLE,
    "version": _VERSION_EXAMPLE,
    "versions_count": 3,
}
_GROUPS_EXAMPLE = {"footprint": 412, "country": 3, "none": 27}
_COPY_PATH_EXAMPLE = {
    "local": f"/mnt/nas/kartograf/data/{_VERSION}",
    "aliases": [
        "Z:\\kartograf\\data\\nmt\\pl_1992_1m_evrf2007\\versions\\N-34\\130"
        "\\D\\d\\2\\4\\2025-04-26_82710_fdd30535\\N-34-130-D-d-2-4.asc"
    ],
}
_REQUEST_FILE_EXAMPLE = {
    "store": _STORE,
    "slot": "nmt/cz_dmr5g_bpv/bbox/18.5_49.6_18.9_49.8.tif",
    "version": (
        "nmt/cz_dmr5g_bpv/versions/bbox/2025-12-19_9a8b7c6d/18.5_49.6_18.9_49.8.tif"
    ),
    "segment": "nmt/cz_dmr5g_bpv",
    "country": "CZ",
    "label": "2025-12-19",
    "is_current": True,
}
_PRODUCT_EXAMPLE = {
    "product": "nmt",
    "countries": ["PL"],
    "slots": 31000,
    "versions": 52000,
    "segments": [
        {
            "store": _STORE,
            "segment": _SEGMENT_EXAMPLE,
            "slots": 31000,
            "versions": 52000,
        }
    ],
}
_FOOTPRINT_EXAMPLE = {
    "store": _STORE,
    "slot": _SLOT,
    "version": _VERSION,
    "segment": _SEGMENT,
    "product": "nmt",
    "label": "2025-04-26_82710",
    "data_year": 2025,
    "source": "sheet",
    "geometry": _POLYGON,
}
_USAGE_ROW_EXAMPLE = {
    "product": "nmt",
    "versions": 52000,
    "unique_bytes": 1960000000000,
}
_USAGE_EXAMPLE = {
    "products": [_USAGE_ROW_EXAMPLE],
    "versions": 80000,
    "unique_bytes": 2400000000000,
}
_UNUSED_EXAMPLE = {
    "products": [{"product": "nmt", "versions": 29767, "unique_bytes": 268000000}],
    "versions": 29767,
    "unique_bytes": 268000000,
    "reclaimable_bytes": 251000000,
}
_INDEX_EXAMPLE = {
    "schema_version": 3,
    "created_at": "2026-10-18T11:58:02Z",
    "size_bytes": 214958080,
}
_TASK_EXAMPLE = {
    "producer": "kartograf",
    "task": "teren",
    "command": "elevation download",
    "options": {"product": "nmt", "sheet": ["N-34-130-D-d-2-4"]},
    "status": "ok",
}
_IMGW_TASK_EXAMPLE = {
    "producer": "imgw",
    "task": "przeplywy",
    "command": "series select",
    "options": {
        "dataset": "pl.imgw.hydro_daily",
        "stations": ["149190310"],
        "years": [2024],
    },
    "status": "not_downloaded",
}
_PROJECT_PIN_EXAMPLE = {
    "producer": "kartograf",
    "task": "teren",
    "version": _OLDER,
    "sha256": _SHA256,
    "state": "ok",
    "slot": _SLOT,
    "label": "2019-07-12_41022",
    "size_bytes": 37001234,
    "is_current": False,
}
_STORE_SETTINGS_EXAMPLE = {
    "id": _STORE,
    "name": "Zespół",
    "kartograf": "/mnt/nas/kartograf/data",
    "imgw": "/mnt/nas/imgw",
    "kind": "share",
    "path_aliases": {"/mnt/nas/": "Z:\\"},
}
_BASEMAP_EXAMPLE = {
    "name": "OpenFreeMap szary",
    "kind": "vector",
    "url": "https://tiles.openfreemap.org/planet",
    "attribution": "OpenFreeMap © OpenMapTiles Data from OpenStreetMap",
    "grayscale": False,
}


def _examples(*examples: dict[str, Any], closed: bool = False) -> ConfigDict:
    """Return a model configuration with OpenAPI examples.

    ``closed`` rejects unknown fields (``additionalProperties: false``).
    """
    config = ConfigDict(json_schema_extra={"examples": list(examples)})
    if closed:
        config["extra"] = "forbid"
    return config


# Problems and freshness ----------------------------------------------------


class ProblemDetails(BaseModel):
    """An error, as ``application/problem+json`` (RFC 9457, AGI-6.3).

    ``code`` is a code of the shared error registry; ``status`` is the HTTP
    status of that code. ``details.reason`` names the project's own cause
    (the machine codes of earlier versions, e.g. ``session_required``,
    ``preview_busy``) and does not depend on the language of the ``detail``. Other
    members of ``details`` give the context: ``source`` (an unavailable
    producer plugin and the pip requirement fixing it), ``kartograf`` or
    ``imgwtools`` (the producer's exception and its unchanged message),
    ``problems`` (invalid settings, field by field), ``job`` (``id``,
    ``kind``, ``state`` of the job in the way of a ``409 conflict``),
    ``preview_reason`` (why a file has no preview), ``blocked_by`` (why a
    snapshot cannot be made now) and ``layers`` (the layers of an area file).
    ``errors`` lists the invalid values of a request.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "type": f"{REGISTRY_PAGE}#not_found",
                    "title": "Not found",
                    "status": 404,
                    "detail": message(
                        "api.slot_unknown", "en", slot=_SLOT, store="zespol"
                    ),
                    "instance": "/api/v1/stores/zespol/slots/…",
                    "code": "not_found",
                },
                {
                    "type": f"{REGISTRY_PAGE}#missing_dependency",
                    "title": "Missing optional dependency",
                    "status": 503,
                    "detail": message(
                        "api.source_problem",
                        "en",
                        message=with_detail(
                            message(
                                "source.unavailable_producer",
                                "en",
                                producer="kartograf",
                            ),
                            message("source.status_not_installed", "en"),
                        ),
                        fix=_KARTOGRAF_FIX,
                    ),
                    "instance": "/api/v1/stores",
                    "code": "missing_dependency",
                    "hint": _KARTOGRAF_FIX,
                    "details": {
                        "reason": "source_unavailable",
                        "source": {
                            "id": "kartograf",
                            "state": "not_installed",
                            "package_version": None,
                            "supported_versions": None,
                            "requirement": "kartograf<0.9,>=0.8.0",
                        },
                    },
                },
            ]
        },
    )

    type: str = Field(
        description=(
            "The code's entry on the registry page (`ERROR_REGISTRY.md#<code>`)."
        )
    )
    title: str = Field(
        description=(
            "Registry title of the code: English, Polish with `Accept-Language: pl`."
        )
    )
    status: int = Field(description="HTTP status of the code (the registry's).")
    detail: str = Field(
        description=(
            "Description: what and how to fix. English, Polish with"
            " `Accept-Language: pl`."
        )
    )
    instance: str | None = Field(
        default=None, description="The request path that failed."
    )
    code: str = Field(
        description=(
            "Registry code: validation_error, not_found, conflict,"
            " missing_dependency, data_error, store_unavailable, forbidden,"
            " calculation_error, unsupported, unauthorized, method_not_allowed,"
            " rate_limited, internal_error."
        )
    )
    hint: str | None = Field(
        default=None,
        description=(
            "Line telling how to fix it, when known; in the language of `detail`."
        ),
    )
    details: dict[str, Any] | None = Field(
        default=None,
        description="`reason` (the project's cause) and the context of the error.",
    )
    errors: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Invalid values of a request: `pointer` (JSON Pointer, e.g."
            " `/query/limit`), `type` and `message`."
        ),
    )


class StaleStore(BaseModel):
    """A store answered from the index while it is unavailable."""

    model_config = _examples(_STALE_STORE_EXAMPLE)

    store: str = Field(description="Store id.")
    status: StoreStatus = Field(description="`unavailable`.")
    status_at: datetime | None = Field(description="Since when.")
    indexed_at: datetime | None = Field(
        description="End of the last complete pass: the answer's state."
    )
    detail: str | None = Field(description="Why the store is unavailable.")

    @classmethod
    def of(cls, freshness: StoreFreshness) -> Self:
        """Return the model of a store's freshness."""
        return cls(
            store=freshness.store,
            status=freshness.status,
            status_at=freshness.status_at,
            indexed_at=freshness.indexed_at,
            detail=freshness.detail,
        )


class IndexAnswer(BaseModel):
    """An answer from the local index, with the stores it could not refresh."""

    stale: bool = Field(
        description=(
            "True when a store of the answer is unavailable: its rows are as of"
            " the store's `indexed_at`, not proof that files are gone."
        )
    )
    stale_stores: list[StaleStore] = Field(
        description="Unavailable stores of the answer; empty when it is current."
    )


def staleness(
    freshness: Iterable[StoreFreshness], stores: Collection[str] | None = None
) -> dict[str, Any]:
    """Return the ``stale`` and ``stale_stores`` fields of an index answer.

    Parameters
    ----------
    freshness : Iterable[StoreFreshness]
        Every store's freshness (``IndexQueries.freshness``).
    stores : Collection[str] or None, optional
        Stores the answer covers; all stores when omitted.
    """
    stale = [
        StaleStore.of(item)
        for item in freshness
        if item.stale and (stores is None or item.store in stores)
    ]
    return {"stale": bool(stale), "stale_stores": stale}


# Requests ------------------------------------------------------------------


def _year_range(text: str | None) -> YearRange | None:
    """Parse ``2023``, ``2020-2023``, ``2020-`` or ``-2023``."""
    if text is None:
        return None
    start, dash, end = text.partition("-")
    if not dash:
        return int(start), int(start)
    return (int(start) if start else None), (int(end) if end else None)


def parse_bbox(text: str) -> BBox:
    """Parse ``min_x,min_y,max_x,max_y`` (finite numbers) of a query parameter."""
    parts = text.split(",")
    try:
        values = [float(part) for part in parts]
    except ValueError:
        values = []
    if len(values) != 4 or not all(math.isfinite(value) for value in values):
        raise ValueError(message("api.bbox_invalid"))
    return values[0], values[1], values[2], values[3]


class CommonFilters(BaseModel):
    """Filters shared by the catalog (``/slots``) and the map (``/map/footprints``).

    Unknown parameters are refused (``422``), so a misspelt filter never
    silently widens an answer.
    """

    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(
        default=None,
        description=(
            "Search text; every word must match: the unit (sheet code, TERYT,"
            " KU), file name, segment and product name, version label, survey"
            " work number, campaign or edition (word prefix, diacritics"
            " ignored); a word of 8–64 hex digits also matches the start of a"
            " SHA-256."
        ),
        examples=["N-34-130-D-d-2-4"],
    )
    store: str | None = Field(
        default=None, description="Store id (/stores).", examples=["zespol"]
    )
    product: str | None = Field(
        default=None, description="Product (/products).", examples=["nmt"]
    )
    country: str | None = Field(
        default=None, description="Country code.", examples=["PL"]
    )
    years: str | None = Field(
        default=None,
        description=(
            "Data year (never the download year): `2023`, `2020-2023`, `2020-`"
            " or `-2023`. Rows without a data year never match."
        ),
        examples=["2020-2023"],
        json_schema_extra={"pattern": YEARS_PATTERN},
    )
    unit: str | None = Field(
        default=None,
        description="Exact unit code of the slot: sheet, TERYT or KU.",
        examples=["1465"],
    )
    versions: VersionsMode = Field(
        default="current",
        description=(
            "Rows: `current` versions (slots without one too), `all` versions,"
            " versions of `full_sheet` links, versions `pinned` in projects the"
            " session's principal sees, or `noncurrent_unpinned` (no link, no"
            " project)."
        ),
    )
    status: RowStatus | None = Field(
        default=None,
        description=(
            "Row state: `ok`, `missing`, `no_sidecar`, `unreadable` or `unrecognized`."
        ),
    )
    project: str | None = Field(
        default=None,
        description=(
            "Only versions pinned in this project (`project` of /projects), on"
            " top of `versions` (`pinned` or `all` lists every pinned version,"
            " non-current ones too); a project not visible to the session's"
            " principal is `404`."
        ),
        examples=["raba"],
    )

    @field_validator("years")
    @classmethod
    def _check_years(cls, value: str | None) -> str | None:
        if value is not None and re.fullmatch(YEARS_PATTERN, value) is None:
            raise ValueError(message("api.years_invalid"))
        return value

    def year_range(self) -> YearRange | None:
        """Return ``years`` as an inclusive range with open ends as ``None``."""
        return _year_range(self.years)


class CatalogFilters(CommonFilters):
    """Filters, area and page of ``GET /slots`` (catalog and search, SPEC 6.6)."""

    location: LocationFilter = Field(
        default="any",
        description=(
            "Location group: `any`, `with` (an outline — in the area when one is"
            " given — or a whole country) or `none` (no location: shown only in"
            " the catalog). `groups` counts every group whatever is chosen."
        ),
    )
    area_id: str | None = Field(
        default=None,
        description="Area kept by POST /areas; rows meeting it, its countries' files.",
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
    limit: int = Field(
        default=DEFAULT_PAGE_LIMIT,
        ge=1,
        le=MAX_PAGE_LIMIT,
        description="Page size.",
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

    def slot_query(self, area: AreaFilter | None) -> SlotQuery:
        """Return the index query of these filters with a resolved area."""
        return SlotQuery(
            q=self.q,
            store=self.store,
            product=self.product,
            country=self.country,
            years=self.year_range(),
            unit=self.unit,
            location=self.location,
            versions=self.versions,
            status=self.status,
            project=self.project,
            area=area,
            limit=self.limit,
            cursor=self.cursor,
        )


class MapFilters(CommonFilters):
    """A map view and the filters of ``GET /map/footprints``."""

    bbox: str = Field(
        description="The view `min_lon,min_lat,max_lon,max_lat` in WGS84.",
        examples=["19.0,49.5,19.6,49.9"],
    )
    limit: int = Field(
        default=MAP_FOOTPRINT_LIMIT,
        ge=1,
        le=MAP_FOOTPRINT_LIMIT,
        description="Most outlines returned; above it the view is a grid.",
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

    def map_query(self) -> MapQuery:
        """Return the index query of this view."""
        return MapQuery(
            bbox=parse_bbox(self.bbox),
            q=self.q,
            store=self.store,
            product=self.product,
            country=self.country,
            years=self.year_range(),
            unit=self.unit,
            versions=self.versions,
            status=self.status,
            project=self.project,
            limit=self.limit,
            grid_columns=self.grid_columns,
        )


class SheetFilters(BaseModel):
    """A map view and the sheet grid of ``GET /map/sheets``."""

    model_config = ConfigDict(extra="forbid")

    bbox: str = Field(
        description="The view `min_lon,min_lat,max_lon,max_lat` in WGS84.",
        examples=["19.0,49.5,19.6,49.9"],
    )
    system: str = Field(
        description="Sheet system of the producer, e.g. Kartograf's `1992` or `2000`.",
        examples=["1992"],
    )
    scale: str = Field(description="Sheet scale, e.g. `1:10000`.", examples=["1:10000"])
    producer: str = Field(
        default="kartograf", description="Producer whose sheet grid is drawn."
    )

    @field_validator("bbox")
    @classmethod
    def _check_bbox(cls, value: str) -> str:
        parse_bbox(value)
        return value

    def bbox_values(self) -> BBox:
        """Return the view as four numbers."""
        return parse_bbox(self.bbox)


# Catalog -------------------------------------------------------------------


class Segment(BaseModel):
    """A store segment (product variant) with the producer's name for it."""

    model_config = _examples(_SEGMENT_EXAMPLE)

    path: str | None = Field(
        description="Segment path in the store; null for a producer without segments."
    )
    label: str = Field(description="Producer's human-readable name of the segment.")
    producer: str = Field(description="Producer id, e.g. `kartograf`.")
    product: str | None = Field(description="Product, e.g. `nmt`.")
    country: str | None = Field(description="Country code, e.g. `PL`.")
    dataset_key: str | None = Field(description="Producer's source key.")
    known: bool = Field(description="Whether the producer recognises the segment.")

    @classmethod
    def of(cls, segment: SegmentRef) -> Self:
        """Return the model of an indexed segment."""
        return cls(
            path=segment.segment,
            label=segment.name,
            producer=segment.producer,
            product=segment.product,
            country=segment.country,
            dataset_key=segment.dataset_key,
            known=segment.known,
        )


class Location(BaseModel):
    """Where a file is (A-ADR-022): an outline, a whole country, or nowhere."""

    model_config = _examples(
        _LOCATION_EXAMPLE, {"kind": "none", "reason": "no_source", "source": None}
    )

    kind: LocationKind = Field(description="`footprint`, `country` or `none`.")
    reason: str | None = Field(
        description=(
            "Why `none`: `no_source` (no outline), `unreadable`, `pending` (not"
            " computed yet) or `no_current` (no current version)."
        )
    )
    source: str | None = Field(
        description="Origin of a footprint: `request`, `sheet`, `header` or `unit`."
    )

    @classmethod
    def of(cls, location: LocationRef) -> Self:
        """Return the model of a location."""
        return cls(kind=location.kind, reason=location.reason, source=location.source)


class Crs(BaseModel):
    """Coordinate reference systems of a version."""

    model_config = _examples({"horizontal": "EPSG:2180", "vertical": "EPSG:9651"})

    horizontal: str | None
    vertical: str | None


class Pin(BaseModel):
    """A project task pinning a version (``Przypięta w: Raba (teren)``)."""

    model_config = _examples(_PIN_EXAMPLE)

    project: str = Field(description="Project id, as in /projects/{project}.")
    name: str = Field(description="Project name.")
    task: str | None = Field(description="Task of the project.")
    sha256: str | None = Field(description="Content the project pinned.")
    state: PinState = Field(
        description=(
            "`ok`; `missing` (not in the store); `sha256_mismatch` (other"
            " content); `unknown` (the project's store is not configured)."
        )
    )

    @classmethod
    def of(cls, pin: PinRef) -> Self:
        """Return the model of a pin."""
        return cls(
            project=pin.project_key,
            name=pin.project,
            task=pin.task,
            sha256=pin.sha256,
            state=pin.state,
        )


class Version(BaseModel):
    """A version of a file: an immutable copy under `versions/`."""

    model_config = _examples(_VERSION_EXAMPLE)

    path: str = Field(description="Version path in the store.")
    ref: str = Field(
        description=(
            "Reference of the version (`version:<store>:<path>`) for its"
            " previews, `archiwista preview` and comparisons; copy it, never"
            " build it."
        )
    )
    label: str | None = Field(description="Version label, e.g. `2025-04-26_82710`.")
    label_source: str | None = Field(
        description="What the label is: `campaign`, `edition` or `downloaded`."
    )
    data_year: int | None = Field(
        description="Year of the data (flight, edition) — never the download year."
    )
    data_date: date | None = Field(description="Date of the data.")
    downloaded_at: datetime | None = Field(description="When it was downloaded.")
    sha256: str | None
    size_bytes: int | None
    full_sheet: bool | None = Field(
        description="Producer's claim that the sheet is complete."
    )
    crs: Crs
    is_current: bool = Field(description="Held by the slot's standard path.")
    is_full_sheet: bool = Field(description="Held by the slot's `full_sheet/` link.")
    state: VersionState = Field(description="`present` or `missing` from the store.")
    missing_since: datetime | None
    location: Location
    pinned_by: list[Pin] = Field(
        description="Pins of projects the session's principal sees."
    )

    @classmethod
    def of(cls, version: VersionSummary, store: str) -> Self:
        """Return the model of an indexed version of ``store``."""
        return cls(
            path=version.path,
            ref=version_ref(store, version.path),
            label=version.label,
            label_source=version.label_source,
            data_year=version.data_year,
            data_date=version.data_date,
            downloaded_at=version.downloaded_at,
            sha256=version.sha256,
            size_bytes=version.size_bytes,
            full_sheet=version.full_sheet,
            crs=Crs(horizontal=version.horizontal_crs, vertical=version.vertical_crs),
            is_current=version.is_current,
            is_full_sheet=version.is_full_sheet,
            state=version.state,
            missing_since=version.missing_since,
            location=Location.of(version.location),
            pinned_by=[Pin.of(pin) for pin in version.pinned_by],
        )


class SlotItem(BaseModel):
    """A catalog row: a slot (a file's place) with the version the query chose."""

    model_config = _examples(_SLOT_ITEM_EXAMPLE)

    store: str = Field(description="Store id.")
    slot: str = Field(description="Slot path (the standard path) in the store.")
    name: str = Field(description="File name.")
    segment: Segment
    unit: str | None = Field(description="Unit code: sheet, TERYT or KU.")
    product: str | None
    country: str | None
    status: RowStatus = Field(
        description="`ok`, `missing`, `no_sidecar`, `unreadable` or `unrecognized`."
    )
    location: Location
    version: Version | None = Field(
        description="The row's version; null for a slot without a current one."
    )
    versions_count: int = Field(description="Versions of the slot in the index.")

    @classmethod
    def of(cls, row: SlotRow) -> Self:
        """Return the model of a catalog row."""
        return cls(
            store=row.store,
            slot=row.slot,
            name=row.name,
            segment=Segment.of(row.segment),
            unit=row.unit,
            product=row.product,
            country=row.country,
            status=row.status,
            location=Location.of(row.location),
            version=(
                None if row.version is None else Version.of(row.version, row.store)
            ),
            versions_count=row.versions_count,
        )


class LocationGroups(BaseModel):
    """Rows per location group over the whole result, whatever `location` is."""

    model_config = _examples({"footprint": 412, "country": 3, "none": 27})

    footprint: int = Field(description="With an outline (in the area, with one).")
    country: int = Field(description="Whole-country files (of the area's countries).")
    none: int = Field(description="Without location: shown only in the catalog.")

    @classmethod
    def of(cls, counts: LocationCounts) -> Self:
        """Return the model of location group counts."""
        return cls(footprint=counts.footprint, country=counts.country, none=counts.none)


class CatalogPage(IndexAnswer):
    """A page of catalog rows; `next_cursor` continues it (keyset pagination)."""

    model_config = _examples(
        {
            "items": [_SLOT_ITEM_EXAMPLE],
            "next_cursor": "WzEsImU1Y2Y0…",
            "groups": {"footprint": 412, "country": 3, "none": 27},
            **_FRESH,
        }
    )

    items: list[SlotItem]
    next_cursor: str | None = Field(
        description=(
            "Opaque cursor of the next page of the same query; null on the last"
            " page. A cursor of other filters is rejected (422)."
        )
    )
    groups: LocationGroups

    @classmethod
    def of(cls, page: SlotPage, freshness: dict[str, Any]) -> Self:
        """Return the model of a catalog page."""
        return cls(
            items=[SlotItem.of(row) for row in page.items],
            next_cursor=page.next_cursor,
            groups=LocationGroups.of(page.groups),
            **freshness,
        )


class CopyPath(BaseModel):
    """Where the file is on this computer and on aliased ones (SPEC 4.6)."""

    model_config = _examples(_COPY_PATH_EXAMPLE)

    local: str = Field(description="Absolute path on this computer.")
    aliases: list[str] = Field(
        description="The same file as mounted on other computers (path aliases)."
    )


class Issue(BaseModel):
    """A visible store or project problem with a fix instruction."""

    model_config = _examples(_ISSUE_EXAMPLE)

    code: str = Field(
        description=(
            "Stable code: missing_sidecar, invalid_sidecar, unknown_segment,"
            " legacy_campaigns, stale_incoming, link_mismatch, orphan_sidecar,"
            " missing_pin, pin_sha256_mismatch, invalid_manifest, unknown_store…"
        )
    )
    message: str = Field(description="What is wrong.")
    instruction: str = Field(description="How a person fixes it.")
    path: str | None = Field(description="Store-relative path concerned.")
    segment: str | None
    slot: str | None
    project: str | None = Field(description="Project id of a project problem.")
    task: str | None
    origin: Literal["scan", "check"] | None = Field(
        description="Found by a scan or by a check job."
    )
    first_seen_at: datetime | None

    @classmethod
    def of(cls, problem: Problem) -> Self:
        """Return the model of a problem."""
        return cls(
            code=problem.code,
            message=problem.message,
            instruction=problem.instruction,
            path=problem.path,
            segment=problem.segment,
            slot=problem.slot,
            project=problem.project,
            task=problem.task,
            origin=problem.origin,
            first_seen_at=problem.first_seen_at,
        )


class SlotCard(IndexAnswer):
    """File card: every version of a slot, current and full sheet, pins, problems."""

    model_config = _examples(
        {
            "store": _STORE,
            "slot": _SLOT,
            "name": "N-34-130-D-d-2-4.asc",
            "segment": _SEGMENT_EXAMPLE,
            "unit": "N-34-130-D-d-2-4",
            "product": "nmt",
            "country": "PL",
            "status": "ok",
            "current": _VERSION,
            "full_sheet": _VERSION,
            "paths": {
                "local": f"/mnt/nas/kartograf/data/{_SLOT}",
                "aliases": [
                    "Z:\\kartograf\\data\\nmt\\pl_1992_1m_evrf2007\\N-34\\130\\D\\d"
                    "\\2\\4\\N-34-130-D-d-2-4.asc"
                ],
            },
            "versions": [
                {
                    **_VERSION_EXAMPLE,
                    "path": _OLDER,
                    "label": "2019-07-12_41022",
                    "data_year": 2019,
                    "data_date": "2019-07-12",
                    "is_current": False,
                    "is_full_sheet": False,
                },
                _VERSION_EXAMPLE,
            ],
            "problems": [],
            **_FRESH,
        }
    )

    store: str
    slot: str
    name: str
    segment: Segment
    unit: str | None
    product: str | None
    country: str | None
    status: RowStatus
    current: str | None = Field(description="Path of the current version.")
    full_sheet: str | None = Field(description="Path of the `full_sheet/` version.")
    paths: CopyPath | None = Field(
        description="Copy path of the standard path; null if the store is gone."
    )
    versions: list[Version] = Field(description="Every version, by path.")
    problems: list[Issue]

    @classmethod
    def of(
        cls,
        detail: SlotDetail,
        problems: Sequence[Problem],
        paths: CopyPath | None,
        freshness: dict[str, Any],
    ) -> Self:
        """Return the model of a file card."""
        return cls(
            store=detail.store,
            slot=detail.slot,
            name=detail.name,
            segment=Segment.of(detail.segment),
            unit=detail.unit,
            product=detail.product,
            country=detail.country,
            status=detail.status,
            current=detail.current,
            full_sheet=detail.full_sheet,
            paths=paths,
            versions=[Version.of(item, detail.store) for item in detail.versions],
            problems=[Issue.of(problem) for problem in problems],
            **freshness,
        )


class VersionCard(IndexAnswer):
    """Every indexed value of one version, its raw sidecar and copy path."""

    model_config = _examples(
        {
            "store": _STORE,
            "slot": _SLOT,
            "ref": f"version:{_STORE}:{_VERSION}",
            "segment": _SEGMENT_EXAMPLE,
            "version": _VERSION_EXAMPLE,
            "dataset": "pl.gugik.nmt_1m",
            "dataset_key": "pl.gugik.nmt_1m",
            "product": "nmt",
            "country": "PL",
            "unit": "N-34-130-D-d-2-4",
            "campaign": "82710",
            "survey_work_id": "GK-FOTO.6201.11.2025",
            "edition": None,
            "coverage": 1.0,
            "parent_request": None,
            "license": "cc-by-4.0",
            "attribution": "Główny Urząd Geodezji i Kartografii",
            "source_files": [],
            "resolution": "1m",
            "nodata": -9999.0,
            "native_crs": "EPSG:2180",
            "footprint": _POLYGON,
            "has_meta": True,
            "paths": _COPY_PATH_EXAMPLE,
            "sidecar": {"schema": "kartograf-meta/1", "sha256": _SHA256},
            **_FRESH,
        }
    )

    store: str
    slot: str
    ref: str = Field(description="Reference of the version (`version:<store>:<path>`).")
    segment: Segment
    version: Version
    dataset: str | None
    dataset_key: str | None
    product: str | None
    country: str | None
    unit: str | None
    campaign: str | None
    survey_work_id: str | None = Field(description="Survey work (request) number.")
    edition: str | None
    coverage: float | None = Field(description="Share of the sheet with data, 0–1.")
    parent_request: str | None = Field(
        description=(
            "Key of the producer request; files of one request: /requests/{key}."
        )
    )
    license: str | None
    attribution: str | None
    source_files: list[str] = Field(
        description="Store paths of the input versions of a derived file."
    )
    resolution: str | None
    nodata: float | None
    native_crs: str | None = Field(description="CRS of the native outline.")
    footprint: Geometry | None = Field(description="Outline: GeoJSON in WGS84.")
    has_meta: bool = Field(description="Whether a readable sidecar was indexed.")
    paths: CopyPath | None = Field(
        description="Copy path of this version; null if the store is gone."
    )
    sidecar: dict[str, Any] | None = Field(
        description="The producer's raw sidecar, unchanged; null without one."
    )

    @classmethod
    def of(
        cls,
        detail: VersionDetail,
        sidecar: dict[str, Any] | None,
        paths: CopyPath | None,
        freshness: dict[str, Any],
    ) -> Self:
        """Return the model of a version."""
        return cls(
            store=detail.store,
            slot=detail.slot,
            ref=version_ref(detail.store, detail.summary.path),
            segment=Segment.of(detail.segment),
            version=Version.of(detail.summary, detail.store),
            dataset=detail.dataset,
            dataset_key=detail.dataset_key,
            product=detail.product,
            country=detail.country,
            unit=detail.unit,
            campaign=detail.campaign,
            survey_work_id=detail.survey_work_id,
            edition=detail.edition,
            coverage=detail.coverage,
            parent_request=detail.parent_request,
            license=detail.license,
            attribution=detail.attribution,
            source_files=list(detail.source_files),
            resolution=detail.resolution,
            nodata=detail.nodata,
            native_crs=detail.native_crs,
            footprint=detail.footprint,
            has_meta=detail.has_meta,
            paths=paths,
            sidecar=sidecar,
            **freshness,
        )


class RequestFile(BaseModel):
    """A file of one producer request (e.g. both sides of a border)."""

    model_config = _examples(_REQUEST_FILE_EXAMPLE)

    store: str
    slot: str
    version: str = Field(description="Version path.")
    segment: str | None
    country: str | None
    label: str | None
    is_current: bool

    @classmethod
    def of(cls, member: GroupMember) -> Self:
        """Return the model of a request's file."""
        return cls(
            store=member.store,
            slot=member.slot,
            version=member.path,
            segment=member.segment,
            country=member.country,
            label=member.label,
            is_current=member.is_current,
        )


class RequestFiles(IndexAnswer):
    """Files of one producer request (``parent_request``)."""

    model_config = _examples(
        {
            "parent_request": '{"bbox":[18.5,49.6,18.9,49.8],"bbox_crs":"EPSG:4326"}',
            "items": [_REQUEST_FILE_EXAMPLE],
            **_FRESH,
        }
    )

    parent_request: str
    items: list[RequestFile]


class ProductSegment(BaseModel):
    """An indexed segment (variant) of a product in one store."""

    model_config = _examples(
        {
            "store": _STORE,
            "segment": _SEGMENT_EXAMPLE,
            "slots": 31000,
            "versions": 52000,
        }
    )

    store: str
    segment: Segment
    slots: int
    versions: int


class Product(BaseModel):
    """An indexed product with its segments; names come from the producer."""

    model_config = _examples(_PRODUCT_EXAMPLE)

    product: str | None = Field(
        description="Product, e.g. `nmt`; null for segments not recognised."
    )
    countries: list[str]
    slots: int
    versions: int
    segments: list[ProductSegment]

    @classmethod
    def of(cls, product: ProductSummary) -> Self:
        """Return the model of an indexed product."""
        return cls(
            product=product.product,
            countries=list(product.countries),
            slots=product.slots,
            versions=product.versions,
            segments=[
                ProductSegment(
                    store=item.store,
                    segment=Segment.of(item.segment),
                    slots=item.slots,
                    versions=item.versions,
                )
                for item in product.segments
            ],
        )


class ProductList(IndexAnswer):
    """Products in the index: only what was scanned, nothing guessed."""

    model_config = _examples(
        {
            "items": [_PRODUCT_EXAMPLE],
            **_FRESH,
        }
    )

    items: list[Product]


# Map -----------------------------------------------------------------------


class Footprint(BaseModel):
    """One outline drawn on the map."""

    model_config = _examples(_FOOTPRINT_EXAMPLE)

    store: str
    slot: str
    version: str
    segment: str | None
    product: str | None
    label: str | None
    data_year: int | None
    source: str | None = Field(description="Origin of the outline.")
    geometry: Geometry = Field(description="GeoJSON in WGS84.")

    @classmethod
    def of(cls, footprint: MapFootprint) -> Self:
        """Return the model of a map footprint."""
        return cls(
            store=footprint.store,
            slot=footprint.slot,
            version=footprint.version,
            segment=footprint.segment,
            product=footprint.product,
            label=footprint.label,
            data_year=footprint.data_year,
            source=footprint.source,
            geometry=footprint.geometry,
        )


class Cell(BaseModel):
    """Number of footprints (by their centre) or stations in one grid cell (WGS84)."""

    model_config = _examples(
        {
            "min_lon": 19.0,
            "min_lat": 49.5,
            "max_lon": 19.25,
            "max_lat": 49.66,
            "count": 412,
        }
    )

    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    count: int

    @classmethod
    def of(cls, cell: GridCell) -> Self:
        """Return the model of a grid cell."""
        return cls(
            min_lon=cell.min_lon,
            min_lat=cell.min_lat,
            max_lon=cell.max_lon,
            max_lat=cell.max_lat,
            count=cell.count,
        )


class MapView(IndexAnswer):
    """Footprints of a map view or, above `limit`, their grid."""

    model_config = _examples(
        {
            "total": 2,
            "aggregated": False,
            "items": [_FOOTPRINT_EXAMPLE],
            "cells": [],
            "groups": {"footprint": 412, "country": 3, "none": 27},
            **_FRESH,
        }
    )

    total: int = Field(description="Footprints in the view.")
    aggregated: bool = Field(description="True: `cells` instead of `items`.")
    items: list[Footprint]
    cells: list[Cell]
    groups: LocationGroups = Field(
        description=(
            "Catalog counts of the same filters without the view: `none` is the"
            " 'files without outline' counter leading to the catalog."
        )
    )

    @classmethod
    def of(cls, page: FootprintPage, freshness: dict[str, Any]) -> Self:
        """Return the model of a map view."""
        return cls(
            total=page.total,
            aggregated=page.aggregated,
            items=[Footprint.of(item) for item in page.items],
            cells=[Cell.of(cell) for cell in page.cells],
            groups=LocationGroups.of(page.groups),
            **freshness,
        )


class Sheet(BaseModel):
    """A sheet of a map sheet grid with its zone and outline."""

    model_config = _examples(
        {"sheet": "N-34-130-D-d-2-4", "zone": None, "geometry": _POLYGON}
    )

    sheet: str = Field(description="Sheet code (godło).")
    zone: int | None = Field(
        description=(
            "Zone of the sheet in its system: the PL-2000 zone (5-8) of the powiats"
            " it lies over; `null` in a system without zones (PL-1992)."
        )
    )
    geometry: Geometry = Field(
        description=(
            "GeoJSON Polygon or MultiPolygon in WGS84: the sheet, or the part of a"
            " PL-2000 sheet inside its zone where a zone boundary cuts it, so the"
            " sheets of two zones never overlap."
        )
    )


class SheetList(BaseModel):
    """Sheets of a sheet system and scale in a map view."""

    model_config = _examples(
        {
            "producer": "kartograf",
            "system": "1992",
            "scale": "1:10000",
            "status": "available",
            "items": [
                {"sheet": "N-34-130-D-d-2-4", "zone": None, "geometry": _POLYGON}
            ],
        }
    )

    producer: str
    system: str
    scale: str
    status: Literal["available", "unsupported"] = Field(
        description="`unsupported` for a producer without sheet grids."
    )
    items: list[Sheet]


# Sources, stores and health ------------------------------------------------


class SourceInfo(BaseModel):
    """A producer plugin: state, versions, schemas and how to fix it (SPEC 5.8)."""

    model_config = _examples(
        _SOURCE_EXAMPLE,
        {
            "producer": "imgw",
            "status": "not_installed",
            "package_version": None,
            "supported_versions": None,
            "schemas": [],
            "detail": message("plugin.module_missing", "en", module="imgwtools"),
            "message": with_detail(
                message("doctor.source_not_installed", "en", producer="imgw"),
                message("plugin.module_missing", "en", module="imgwtools"),
            ),
            "fix": message("fix.install", "en", requirement="archiwista[imgw]"),
        },
    )

    producer: str
    status: SourceStatus = Field(
        description="`available`, `not_installed`, `incompatible` or `error`."
    )
    package_version: str | None = Field(description="Installed producer library.")
    supported_versions: str | None = Field(description="Supported range (PEP 440).")
    schemas: list[str] = Field(description="Schemas the plugin reads.")
    detail: str | None
    message: str = Field(description="Description of the state.")
    fix: str | None = Field(description="Fix; null when available.")

    @classmethod
    def of(cls, state: SourceState, message: str, fix: str | None) -> Self:
        """Return the model of a plugin's state with its description."""
        return cls(
            producer=state.producer,
            status=state.status,
            package_version=state.package_version,
            supported_versions=state.supported_versions,
            schemas=list(state.schemas),
            detail=state.detail,
            message=message,
            fix=fix,
        )


class DefaultRootInfo(BaseModel):
    """The directory a producer uses for a store when a call names none."""

    model_config = _examples(_DEFAULT_ROOT_EXAMPLE)

    path: str = Field(description="The directory; it may not exist.")
    source: DefaultRootSource = Field(
        description=(
            "Where the producer's settings found it: `default` (under the data"
            " directory), `env` (an environment variable), `dotenv` (the same"
            " variable in a `.env` file) or `file` (`nogat.toml`)."
        )
    )
    name: str | None = Field(
        description="The variable or the table that gave it; null for the default."
    )
    exists: bool = Field(description="Whether it is a directory.")
    marked: bool = Field(
        description="Whether it holds the producer's store marker (a store)."
    )
    message: str = Field(description="Description of the root.")

    @classmethod
    def of(cls, root: DefaultRoot, message: str) -> Self:
        """Return the model of a producer's default root with its description."""
        return cls(
            path=str(root.path),
            source=root.source,
            name=root.name,
            exists=root.exists,
            marked=root.marked,
            message=message,
        )


class SourceListItem(SourceInfo):
    """A producer plugin of ``GET /sources``: its state and its default store root."""

    model_config = _examples(_LISTED_SOURCE_EXAMPLE)

    default_root: DefaultRootInfo | None = Field(
        description=(
            "The directory the producer uses for a store when a call names none:"
            " nothing in it is ever used by Archiwista, it is an offer for the"
            " first-run wizard. Null when the plugin is not available or the"
            " producer has no such directory. Reading it may take as long as"
            " the producer needs to size it."
        )
    )
    availability: list[str] = Field(
        description=(
            "Products whose availability at the source the producer checks"
            " (`POST /availability`), in its order; empty when the plugin is not"
            " available or checks none."
        )
    )

    @classmethod
    def listed(
        cls,
        info: SourceInfo,
        root: DefaultRootInfo | None,
        availability: tuple[str, ...],
    ) -> Self:
        """Return the listing of a plugin: its state, default root and products."""
        return cls(
            **info.model_dump(), default_root=root, availability=list(availability)
        )


class SourceList(BaseModel):
    """Every registered producer plugin, ordered by producer."""

    model_config = _examples({"items": [_LISTED_SOURCE_EXAMPLE]})

    items: list[SourceListItem]


class Progress(BaseModel):
    """Progress of a job: its last progress event."""

    model_config = _examples({"current": 26, "total": 41})

    current: int
    total: int


class Job(BaseModel):
    """A background job next to a store's state."""

    model_config = _examples(_JOB_EXAMPLE)

    id: str
    kind: str = Field(description="`scan`, `footprints` or `link_check`.")
    state: str = Field(
        description="`queued`, `running`, `succeeded`, `failed` or `interrupted`."
    )
    actor: str = Field(description="Who started it (`local`, an account, an agent).")
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    progress: Progress | None

    @classmethod
    def of(cls, job: JobRef) -> Self:
        """Return the model of a job."""
        return cls(
            id=job.id,
            kind=job.kind,
            state=job.state,
            actor=job.actor,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            progress=None
            if job.progress is None
            else Progress(current=job.progress[0], total=job.progress[1]),
        )


# Background jobs (step 9b) -------------------------------------------------


class JobFailure(BaseModel):
    """Why a job did not succeed: a registry code, a detail, the reason."""

    model_config = _examples(
        _JOB_FAILURE_EXAMPLE,
        {
            "code": "conflict",
            "detail": message(
                "snapshot.blocked_read_only_folder",
                "en",
                path="/mnt/nas/raba/dane/.wersje",
            ),
            "hint": None,
            "details": {"reason": "snapshot_blocked", "blocked_by": "read_only_folder"},
        },
    )

    code: str = Field(
        description=(
            "Code of the shared error registry, as in a problem: `not_found`,"
            " `conflict`, `forbidden`, `unsupported`, `data_error`,"
            " `store_unavailable`, `missing_dependency`, `cancelled` or"
            " `internal_error`. The job's own cause is `details.reason`."
        )
    )
    detail: str = Field(
        description=(
            "Description in the language of the request; for a crashed worker it"
            " names the job log."
        )
    )
    hint: str | None = Field(
        description="Line telling how to fix it; null when no fix is known."
    )
    details: dict[str, Any] = Field(
        description=(
            "`reason`, the job's own cause, and the context. Reasons:"
            " `store_unreadable`, or the producer's refusal of the directory"
            " (`no_marker`, `unsupported_marker`, `foreign_store`, `not_a_store`;"
            " the `hint` has the command) (`store_unavailable`); `source_unavailable`"
            " or `source_incompatible` (a plugin; `details.source` and the fix),"
            " `own_reader_failed` (`missing_dependency`); `offline_mode` and"
            " `snapshot_blocked` (`conflict`; `details.blocked_by`:"
            " `folder_invalid`, `read_only_folder`, `insufficient_space` or"
            " `file_missing`); of a snapshot `inconsistent_copy` and"
            " `target_exists` (`conflict`), `checksum_mismatch` and"
            " `integrity_failed` (`data_error`); `path_outside_root`"
            " (`forbidden`); `kartograf_error` (`<package>_error`, a"
            " producer's own error, `data_error` or the producer's code;"
            " `details.kartograf`); `no_commands` (`unsupported`: the producer"
            " offers no actions); `run_failed` (no unit of a run, or no task of a"
            " project's download, succeeded: the code of the first failure,"
            " `details.task` the first failed task of a project); `check_failed`"
            " (`source_unavailable`: the source could be asked about nothing);"
            " `project_locked` (`conflict`: the lock of a project's manifest"
            " stays, `details.lock`) and `unknown_store` (`conflict`: the"
            " project's manifest names no configured store); `interrupted`"
            " (`cancelled`: the server stopped, safe to retry); `worker_crashed`"
            " and `protocol_error` (`internal_error`). None for `not_found`,"
            " `cancelled` and `internal_error`."
        )
    )


class JobDetail(BaseModel):
    """A background job: what it does, who asked, how far it got, how it ended.

    Its events (progress, notices, changes of state) stream from
    `GET /jobs/{job}/events`. A job only of projects the session does not
    see is not shown; a `preview` job lists only the refs (and failures) of
    visible projects, with whole counts.
    """

    model_config = _examples(_JOB_DETAIL_EXAMPLE, _JOB_FAILED_EXAMPLE)

    id: str = Field(description="Job id.")
    kind: JobKind = Field(
        description=(
            "`scan` (index the store), `footprints` (unit outlines over the"
            " network), `link_check` (which version a slot's link holds),"
            " `preview` (build local previews of files), `own_scan` (scan the"
            " projects' own data folders), `snapshot` (a snapshot of an"
            " own-data file), `availability` (what the source has for an"
            " area and a product, over the network), `check` (what a run of"
            " a producer's command would do in the store, over the network),"
            " `download` (a run of a producer's command in the store, over the"
            " network), `project_download` (a project's tasks downloaded, pinned"
            " and restored by its producer, over the network), `project_repin`"
            " (one task of a project pinned anew to the source's newer"
            " versions, over the network), `project_check` (a project's pins"
            " compared with the source, over the network), `project_verify`"
            " (a project's pinned files checked in its store) or `preview_warm`"
            " (the first look at current versions prepared in the preview"
            " cache ahead)."
        )
    )
    state: JobState = Field(
        description=(
            "`queued`, `running`, then `succeeded`, `partial` (part of its"
            " units failed: `result` names them), `failed`, `interrupted` (the"
            " server stopped meanwhile; safe to retry) or `cancelled`."
        )
    )
    actor: str = Field(
        description=(
            "Who started it: `local` or an account; an agent acts as the"
            " account that minted its token."
        )
    )
    actor_kind: PrincipalKind = Field(
        description=(
            "How: `local_owner` (the computer's owner), `user` (an account),"
            " `agent` (with a token `actor` issued) or `scheduler` (scheduled"
            " scans, for the owner)."
        )
    )
    session: str | None = Field(
        description=(
            "Label of the session it was started in (`label` of GET"
            " /api/v1/session); `null` at the terminal and for the scheduler."
        )
    )
    store: str | None = Field(
        description=(
            "Store id; `null` for `preview`, `own_scan`, `snapshot`,"
            " `availability`, the `project_*` kinds (the project's manifest"
            " names its store) and `preview_warm` (its `params.store`)."
        )
    )
    params: dict[str, Any] = Field(
        description=(
            "`scan`: `mode` and `segment`; `link_check`: `slot`; `footprints`:"
            " none; `preview`: `refs`, their `contents` and `force`; `own_scan`:"
            " `project` (none: every project); `snapshot`: `project`, `file_id`"
            " and `note`; `availability`: `area_id`, `producer`, `product` and"
            " `force`; `check`: `producer` and `calls` (each `command` and"
            " `options`, in their order); `download`: those and `plan_job` (the"
            " `check` job whose plans it runs, or `null`); the `project_*` kinds:"
            " `project` (its key) and `tasks`"
            " (task names, `null` for every task; one for `project_repin`);"
            " `preview_warm`: `store`, `product`, `segment`, `project`,"
            " `area_id` and `since` (each `null` when not given; `since` only"
            " from the warm-up after a scan)."
        )
    )
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    progress: dict[str, Any] | None = Field(
        description=(
            "The last progress: `current` of `total` (segments of a scan,"
            " versions of `footprints`, contents of `preview`, project folders"
            " of `own_scan`, phases of `snapshot`); a scan adds `segment` and"
            " `entries`, `footprints` adds `written` and `failed`, `preview`"
            " adds `built`, `cached` and `failed`, `own_scan` adds `files` and"
            " `read`, `snapshot` adds `phase`; a `check` counts its calls"
            " planned; a `download` counts the units of the call it runs and"
            " adds `call` (its place in `calls`, from 0) and `calls` (their"
            " number), `project_download` and `project_repin` count units; the"
            " three add the producer's `unit` (or `null`), `status` and"
            " `message`; `preview_warm` counts files and"
            " adds `warmed`, `cached`, `failed` and `skipped`."
        )
    )
    result: dict[str, Any] | None = Field(
        description=(
            "Summary of a job that succeeded or ended `partial`. `scan`: counts"
            " (`entries`, `versions_written`, `links_changed`, `missing`,"
            " `removed`…), `segments` and `projects`; `footprints`: `total`,"
            " `written`, `failed`; `link_check`: `status` (`confirmed`,"
            " `index_outdated`, `mismatch`, `missing` or `not_a_link`) with the"
            " `expected` and `confirmed` versions; `preview`: `built`, `cached`,"
            " `failed` (`ref`, `code`, `detail`) and `seconds`; `own_scan`:"
            " `projects`, `files`, `new`, `changed`, `missing`, `unreadable`,"
            " `snapshots`, `problems` and `seconds`; `snapshot`: `status`"
            " (`created` or `unchanged`), `label`, `content_sha256`,"
            " `size_bytes` and `seconds`; `availability`: `area_id`,"
            " `producer`, `product`, `checked_at` (when the source was asked),"
            " `ok` (every part checked), `combinations`, `kept` (false: a newer"
            " report was kept) and `seconds`; `check`: `producer`, `store`,"
            " `root`, `checked_at` (of the oldest plan), `ok`, `positions`,"
            " `counts` (of each status), `size_bytes` (of the positions to"
            " download as far as the producer tells them; `null` when it tells"
            " none), `size_complete`, `failed` (`call`, `path`, `error` of the"
            " positions not checked), `calls` (per call, in their order:"
            " `command`, `line` (the producer's command line of its run),"
            " `status` (`ok`, `partial`, `failed`: no plan), `positions`,"
            " `todo`, `error` (`code`, `reason`, `detail` of a failed call, else"
            " `null`)) and `seconds`; `download`: `producer`, `store`, `root`,"
            " `plan_job`, `status` (`ok`, `partial`), `counts` (files `new`,"
            " `unchanged`, `relabeled`), `files` (`path` and `version_path`"
            " below the root, `unit`, `status`, `size_bytes`, `sha256`, `label`,"
            " `call`), `items` (`id`, `status`, `code`, `reason`, `message` of"
            " each unit, `call`; a position the source changed since the plan:"
            " `conflict`, `stale_plan`), `failed` (units), `calls` (per call:"
            " `command`, `line`, `status` (`ok`, `partial`, `failed` or"
            " `skipped`), `reason` of a skipped one (`not_planned`: its check"
            " failed; `nothing_to_download`), `files`, `failed`, `error`),"
            " `rescanned` (units read again into the index) and `seconds`;"
            " `project_download` and `project_repin`: `producer`, `project`,"
            " `store`, `root`, `upgrade` (true for a repin), `ok`, `counts`"
            " (tasks `pinned`, `unchanged`, `restored`, `updated`, `failed`),"
            " `tasks` (`name`, `outcome`, the `pinned` and `unpinned` versions"
            " with `path` and `version_path` below the root, `unit`, `label`,"
            " `sha256`, `size_bytes`; `errors`, `code`, `reason` of a failed"
            " task), `failed`, `rescanned` and `seconds`; `project_check` and"
            " `project_verify`: `producer`, `project`, `root`, `ok`, `counts`"
            " (files of each state), `files` (`task`, `unit`, `path`, `status`:"
            " `ok`, `missing` or `corrupt` in the store; `current`, `newer`,"
            " `added`, `removed`, `missing`, `unverifiable`, `check_failed` or"
            " `conflict` at the source; `pinned_label`, `available_label`,"
            " `detail`), `not_downloaded` (tasks without pins) and `seconds`;"
            " `preview_warm`: `versions` and `files` (own files) selected,"
            " `warmed` (prepared now), `cached` (ready before), `needs_build`"
            " (map tiles waiting for a `preview` job), `failed`, `failures`"
            " (the first 100: `ref`, `code`, `detail`), `skipped` (not reached"
            " when the preview cache had no more room), `stopped` (`cache_full`"
            " or `null`), `room_bytes` and `seconds`."
        )
    )
    error: JobFailure | None = Field(
        description="Why a job ended without success (`null` otherwise)."
    )

    @classmethod
    def of(cls, job: JobRecord) -> Self:
        """Return the model of a job, its error in the language of the request."""
        error = None if job.error is None else job.error.localized(current_language())
        return cls(
            id=job.id,
            kind=job.kind,
            state=job.state,
            actor=job.actor,
            actor_kind=job.actor_kind,
            session=job.session,
            store=job.store,
            params=job.params,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            progress=job.progress,
            result=job.result,
            error=None
            if error is None
            else JobFailure(
                code=error.code,
                detail=error.detail,
                hint=error.hint,
                details=dict(error.details),
            ),
        )


class JobList(BaseModel):
    """Background jobs, newest first; `next_cursor` continues the list."""

    model_config = _examples(
        {"items": [_JOB_DETAIL_EXAMPLE, _JOB_FAILED_EXAMPLE], "next_cursor": None}
    )

    items: list[JobDetail]
    next_cursor: str | None = Field(
        description="`cursor` of the next page; `null` on the last page."
    )

    @classmethod
    def of(cls, page: JobPage) -> Self:
        """Return the model of a page of jobs."""
        return cls(
            items=[JobDetail.of(job) for job in page.items],
            next_cursor=page.next_cursor,
        )


class JobLog(BaseModel):
    """The end of a job's log: its worker's standard error, in English.

    Python's log lines of Archiwista and of the producer (`INFO` and above)
    and whatever a library writes there; it grows while the job runs.
    """

    model_config = _examples(
        {
            "job": "9b2e44d01c7f3a85",
            "size_bytes": 182,
            "truncated": False,
            "text": (
                "2026-10-26 09:12:03,418 INFO archiwista.jobs.worker: job"
                " 9b2e44d01c7f3a85 (footprints) of store zespol started\n"
                "2026-10-26 09:12:04,002 WARNING kartograf: PRG WFS timed out\n"
            ),
        }
    )

    job: str = Field(description="Job id.")
    size_bytes: int = Field(
        ge=0, description="Size of the whole log when it was read, in bytes."
    )
    truncated: bool = Field(
        description=(
            "Whether `text` leaves the start out: it holds the last MiB, from the"
            " first line that starts in it."
        )
    )
    text: str = Field(
        description="The log as UTF-8; a byte that is no UTF-8 is replaced."
    )

    @classmethod
    def of(cls, job: str, tail: LogTail) -> Self:
        """Return the model of the end of a job's log."""
        return cls(
            job=job,
            size_bytes=tail.size_bytes,
            truncated=tail.truncated,
            text=tail.text,
        )


class JobFilters(BaseModel):
    """Filters and page of `GET /jobs`; unknown parameters are refused (`422`)."""

    model_config = ConfigDict(extra="forbid")

    kind: JobKind | None = Field(default=None, description="Only jobs of this kind.")
    store: str | None = Field(
        default=None,
        description="Only jobs of this store, also one no longer configured.",
        examples=[_STORE],
    )
    state: JobState | None = Field(default=None, description="Only jobs in this state.")
    project: str | None = Field(
        default=None,
        description=(
            "Only jobs with this project's data (`project` of /projects): its"
            " own-data scans, its snapshots, previews of its files; a project"
            " not visible to the session's principal is `404`."
        ),
        examples=["raba"],
    )
    limit: int = Field(
        default=DEFAULT_PAGE_LIMIT,
        ge=1,
        le=MAX_PAGE_LIMIT,
        description="Page size.",
    )
    cursor: str | None = Field(
        default=None,
        description="`next_cursor` of the previous page of the same filters.",
    )


class ScanRequest(BaseModel):
    """What `POST /stores/{store}/scan` reads; no body scans incrementally."""

    model_config = _examples(
        {"mode": "full"}, {"mode": "incremental", "segment": _SEGMENT}, closed=True
    )

    mode: ScanMode = Field(
        default="incremental",
        description=(
            "`incremental` (versions already indexed are not read again) or"
            " `full` (every sidecar is read again)."
        ),
    )
    segment: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Only this segment (`<product>/<variant>`, see /products); the"
            " whole store and its projects when omitted. A data source that reads"
            " only its whole directory (IMGWTools: a segment is a dataset, a label)"
            " cannot scan one segment: the job fails with `unsupported`."
        ),
    )


class LinkCheckRequest(BaseModel):
    """The slot whose link `POST /stores/{store}/link-check` confirms."""

    model_config = _examples({"slot": _SLOT}, closed=True)

    slot: str = Field(
        min_length=1, description="Slot path in the store, as `slot` of /slots."
    )


class StoreState(BaseModel):
    """A store's index state: availability, counts, last scan, running job."""

    model_config = _examples(_STORE_STATE_EXAMPLE)

    status: StoreStatus = Field(
        description="`unknown` (not scanned yet), `available` or `unavailable`."
    )
    status_at: datetime | None
    detail: str | None = Field(
        description=(
            "Why the store is unavailable, as written when it was found (in Polish,"
            " whatever the language of the request)."
        )
    )
    indexed_at: datetime | None = Field(
        description="End of the last complete pass over the store."
    )
    full_scan_at: datetime | None = Field(
        description=(
            "End of the last successful full scan of the whole store;"
            " incremental scans trust known version directories, so this is"
            " the last check of their contents."
        )
    )
    slots: int
    versions: int
    missing_versions: int
    unlocated_versions: int = Field(description="Versions without location.")
    issues: int
    last_scan: Job | None = Field(description="Last finished scan, with its actor.")
    running_job: Job | None = Field(description="A queued or running job.")
    stale: bool = Field(description="Answers come from an index not refreshed.")

    @classmethod
    def of(cls, state: StoreIndexState | None) -> Self:
        """Return the model of a store's state; ``unknown`` before its first scan."""
        if state is None:
            return cls(
                status="unknown",
                status_at=None,
                detail=None,
                indexed_at=None,
                full_scan_at=None,
                slots=0,
                versions=0,
                missing_versions=0,
                unlocated_versions=0,
                issues=0,
                last_scan=None,
                running_job=None,
                stale=False,
            )
        return cls(
            status=state.status,
            status_at=state.status_at,
            detail=state.detail,
            indexed_at=state.indexed_at,
            full_scan_at=state.full_scan_at,
            slots=state.slots,
            versions=state.versions,
            missing_versions=state.missing_versions,
            unlocated_versions=state.unlocated_versions,
            issues=state.issues,
            last_scan=None if state.last_scan is None else Job.of(state.last_scan),
            running_job=None
            if state.running_job is None
            else Job.of(state.running_job),
            stale=state.stale,
        )


class StoreItem(BaseModel):
    """A configured store with its index state."""

    model_config = _examples(_STORE_EXAMPLE)

    store: str = Field(description="Store id.")
    name: str
    kind: StoreKind = Field(description="`local` disk or network `share`.")
    producers: list[str] = Field(description="Producers with a directory in it.")
    state: StoreState

    @classmethod
    def of(cls, store: StoreConfig, state: StoreIndexState | None) -> Self:
        """Return the model of a configured store."""
        return cls(
            store=store.id,
            name=store.name,
            kind=store.kind,
            producers=list(store.roots()),
            state=StoreState.of(state),
        )


class StoreList(BaseModel):
    """Configured stores in settings order."""

    model_config = _examples({"items": [_STORE_EXAMPLE]})

    items: list[StoreItem]


class UsageRow(BaseModel):
    """Disk usage of one product's present versions, each content once."""

    model_config = _examples(_USAGE_ROW_EXAMPLE)

    product: str | None
    versions: int
    unique_bytes: int

    @classmethod
    def of(cls, usage: ProductUsage) -> Self:
        """Return the model of a product's usage."""
        return cls(
            product=usage.product,
            versions=usage.versions,
            unique_bytes=usage.unique_bytes,
        )


class Usage(BaseModel):
    """Disk usage of a store: links add nothing, a content counts once."""

    model_config = _examples(_USAGE_EXAMPLE)

    products: list[UsageRow]
    versions: int
    unique_bytes: int

    @classmethod
    def of(cls, usage: StoreUsage) -> Self:
        """Return the model of a store's usage."""
        return cls(
            products=[UsageRow.of(row) for row in usage.products],
            versions=usage.versions,
            unique_bytes=usage.unique_bytes,
        )


class Unused(BaseModel):
    """Present versions neither current, a full sheet, nor pinned by any project."""

    model_config = _examples(_UNUSED_EXAMPLE)

    products: list[UsageRow]
    versions: int
    unique_bytes: int
    reclaimable_bytes: int = Field(
        description="Contents no other present version holds."
    )

    @classmethod
    def of(cls, unused: UnusedVersions) -> Self:
        """Return the model of the clean-up report."""
        return cls(
            products=[UsageRow.of(row) for row in unused.products],
            versions=unused.versions,
            unique_bytes=unused.unique_bytes,
            reclaimable_bytes=unused.reclaimable_bytes,
        )


class ProjectManifest(BaseModel):
    """One producer's manifest in a project directory, as the last scan read it."""

    model_config = _examples(_MANIFEST_EXAMPLE)

    producer: str = Field(
        description=(
            "Producer whose manifest it is: `kartograf` (`kartograf-project.json`)"
            " or `imgw` (`imgw-project.json`)."
        )
    )
    store: str | None = Field(
        description="Configured store the manifest names; null when none matches."
    )
    status: str | None = Field(
        description=(
            "Producer's status when the manifest was read: `ok`, `not_downloaded`,"
            " `missing` or `corrupt`; null when not checked."
        )
    )
    problem: str | None = Field(
        description=(
            "Producer's message for an invalid manifest, whose tasks and pins are"
            " not read; the other manifest is read all the same."
        )
    )
    scanned_at: datetime = Field(description="When the manifest was read.")

    @classmethod
    def of(cls, manifest: ProjectManifestRef) -> Self:
        """Return the model of a project's manifest."""
        return cls(
            producer=manifest.producer,
            store=manifest.store,
            status=manifest.status,
            problem=manifest.problem,
            scanned_at=manifest.scanned_at,
        )


_MANIFESTS = (
    "The producers' manifests the project directory holds, Kartograf's first: a"
    " project has one or both (SPEC 4.7), each with its store, state and problem."
)


class ProjectItem(BaseModel):
    """A discovered project the session's principal sees."""

    model_config = _examples(_PROJECT_EXAMPLE)

    project: str = Field(description="Project id: /projects/{project}.")
    name: str
    manifests: list[ProjectManifest] = Field(description=_MANIFESTS)
    tasks: int = Field(description="Tasks of every manifest.")
    pins: int = Field(description="Pins of every manifest.")
    missing_pins: int = Field(description="Pins missing from the store or other.")
    project_write: bool = Field(description=_PROJECT_WRITE)

    @classmethod
    def of(cls, project: ProjectRef, *, writable: WritableProjects) -> Self:
        """Return the model of a listed project (``writable``: ``project.write``)."""
        return cls(
            project=project.key,
            name=project.name,
            manifests=[ProjectManifest.of(item) for item in project.manifests],
            tasks=project.tasks,
            pins=project.pins,
            missing_pins=project.missing_pins,
            project_write=writable(project.access_key),
        )


class StoreDetail(BaseModel):
    """A store for the „Magazyn” view: usage, clean-up report, projects, problems."""

    model_config = _examples(
        {
            "store": _STORE,
            "name": "Zespół",
            "kind": "share",
            "producers": ["kartograf"],
            "state": _STORE_STATE_EXAMPLE,
            "usage": _USAGE_EXAMPLE,
            "unused": _UNUSED_EXAMPLE,
            "projects": [_PROJECT_EXAMPLE],
            "problems": [_ISSUE_EXAMPLE],
        }
    )

    store: str
    name: str
    kind: StoreKind
    producers: list[str]
    state: StoreState
    usage: Usage
    unused: Unused
    projects: list[ProjectItem] = Field(
        description=(
            "Projects the principal sees with a manifest naming the store, with all"
            " their manifests."
        )
    )
    problems: list[Issue]

    @classmethod
    def of(
        cls, summary: StoreSummary, store: StoreConfig, *, writable: WritableProjects
    ) -> Self:
        """Return the model of a store's summary (``writable``: ``project.write``)."""
        return cls(
            store=summary.store,
            name=summary.name,
            kind=summary.kind,
            producers=list(store.roots()),
            state=StoreState.of(summary.state),
            usage=Usage.of(summary.usage),
            unused=Unused.of(summary.unused),
            projects=[
                ProjectItem.of(project, writable=writable)
                for project in summary.projects
            ],
            problems=[Issue.of(problem) for problem in summary.problems],
        )


class IndexInfo(BaseModel):
    """The local index file."""

    model_config = _examples(_INDEX_EXAMPLE)

    schema_version: int
    created_at: datetime | None
    size_bytes: int


class PreviewsState(BaseModel):
    """The preview cache against its limit, and the render processes."""

    model_config = _examples(
        {
            "used_bytes": 1840000000,
            "limit_bytes": 21474836480,
            "objects": 5210,
            "workers": 4,
        }
    )

    used_bytes: int = Field(description="Bytes of the preview cache.")
    limit_bytes: int = Field(
        description="Its limit (`preview_cache_limit_gb`); least used go first."
    )
    objects: int = Field(description="Objects: previews of one content each.")
    workers: int = Field(description="Render processes at most.")

    @classmethod
    def of(cls, usage: CacheUsage, workers: int) -> Self:
        """Return the state of a preview cache and its render pool."""
        return cls(
            used_bytes=usage.used_bytes,
            limit_bytes=usage.limit_bytes,
            objects=usage.objects,
            workers=workers,
        )


class OwnDataState(BaseModel):
    """The scans of the projects' own data (`own_scan` of every project)."""

    model_config = _examples({"finished_at": "2026-10-18T03:20:44Z", "busy": False})

    finished_at: datetime | None = Field(
        description=(
            "End of the last scan of every project's own data, whatever its"
            " outcome; null before the first one."
        )
    )
    busy: bool = Field(description="Whether such a scan waits or runs.")

    @classmethod
    def of(cls, history: ScanHistory) -> Self:
        """Return the state of the own-data scans (``own_scan_history``)."""
        return cls(finished_at=history.finished_at, busy=history.busy)


class Health(BaseModel):
    """Versions, sources, the index and every configured store's state."""

    model_config = _examples(
        {
            "archiwista": "0.2.0",
            "sources": [_SOURCE_EXAMPLE],
            "index": _INDEX_EXAMPLE,
            "stores": [_STORE_EXAMPLE],
            "previews": {
                "used_bytes": 1840000000,
                "limit_bytes": 21474836480,
                "objects": 5210,
                "workers": 4,
            },
            "own_data": {"finished_at": "2026-10-18T03:20:44Z", "busy": False},
        }
    )

    archiwista: str = Field(description="Archiwista's version.")
    sources: list[SourceInfo] = Field(
        description="Producer plugins with their library versions."
    )
    index: IndexInfo
    stores: list[StoreItem] = Field(
        description="Configured stores: availability, last scan, running job."
    )
    previews: PreviewsState | None = Field(
        default=None,
        description=(
            "Preview cache and render processes of the server; null without"
            " them (`archiwista status`)."
        ),
    )
    own_data: OwnDataState | None = Field(
        default=None,
        description=(
            "The last scan of every project's own data and whether one waits"
            " or runs; null without the server's jobs (`archiwista status`)."
        ),
    )

    @classmethod
    def of(
        cls,
        version: str,
        sources: list[SourceInfo],
        status: IndexStatus,
        stores: Iterable[StoreConfig],
        previews: PreviewsState | None = None,
        own_data: OwnDataState | None = None,
    ) -> Self:
        """Return the health model of the index, stores, previews and own data."""
        states = {state.store: state for state in status.stores}
        return cls(
            archiwista=version,
            sources=sources,
            index=IndexInfo(
                schema_version=status.schema_version,
                created_at=status.created_at,
                size_bytes=status.size_bytes,
            ),
            stores=[StoreItem.of(store, states.get(store.id)) for store in stores],
            previews=previews,
            own_data=own_data,
        )


# Projects ------------------------------------------------------------------


class ProjectList(IndexAnswer):
    """Projects the session's principal sees, ordered by name."""

    model_config = _examples({"items": [_PROJECT_EXAMPLE], **_FRESH})

    items: list[ProjectItem]


class ProjectTask(BaseModel):
    """A task of a project's manifest with its existing command and options."""

    model_config = _examples(_TASK_EXAMPLE, _IMGW_TASK_EXAMPLE)

    producer: str = Field(description="Producer of the manifest holding the task.")
    task: str
    command: str = Field(description="Producer command as in the manifest.")
    options: dict[str, Any] = Field(description="Options as in the manifest.")
    status: str | None

    @classmethod
    def of(cls, task: ProjectTaskRef) -> Self:
        """Return the model of a project task."""
        return cls(
            producer=task.producer,
            task=task.task_id,
            command=task.command,
            options=dict(task.options),
            status=task.status,
        )


class ProjectPin(BaseModel):
    """A version a project task pinned (older versions too)."""

    model_config = _examples(_PROJECT_PIN_EXAMPLE)

    producer: str = Field(
        description=(
            "Producer of the manifest that pins it: the version lies in that"
            " producer's directory of the store."
        )
    )
    task: str | None
    version: str = Field(
        description="Pinned version path, relative to the producer's directory."
    )
    sha256: str | None
    state: PinState
    slot: str | None
    label: str | None
    size_bytes: int | None
    is_current: bool

    @classmethod
    def of(cls, pin: ProjectPinRef) -> Self:
        """Return the model of a project's pin."""
        return cls(
            producer=pin.producer,
            task=pin.task,
            version=pin.version,
            sha256=pin.sha256,
            state=pin.state,
            slot=pin.slot,
            label=pin.label,
            size_bytes=pin.size_bytes,
            is_current=pin.is_current,
        )


class ProjectCard(IndexAnswer):
    """A project: tasks with their commands, pinned versions and problems."""

    model_config = _examples(
        {
            **{
                key: value
                for key, value in _PROJECT_EXAMPLE.items()
                if key not in ("tasks", "pins")
            },
            "tasks": [_TASK_EXAMPLE, _IMGW_TASK_EXAMPLE],
            "pins": [_PROJECT_PIN_EXAMPLE],
            "problems": [],
            **_FRESH,
        }
    )

    project: str = Field(description="Project id: /projects/{project}.")
    name: str
    manifests: list[ProjectManifest] = Field(description=_MANIFESTS)
    missing_pins: int = Field(description="Pins missing from the store or other.")
    project_write: bool = Field(description=_PROJECT_WRITE)
    tasks: list[ProjectTask] = Field(
        description="Tasks of each manifest in its order, manifest after manifest."
    )
    pins: list[ProjectPin] = Field(description="Pinned versions, older ones too.")
    problems: list[Issue] = Field(
        description=(
            "Invalid manifest, unknown store, a task name in the manifests of"
            " several producers (`duplicate_task`), missing or other pinned files."
        )
    )

    @classmethod
    def of(
        cls,
        detail: ProjectDetail,
        freshness: dict[str, Any],
        *,
        writable: WritableProjects,
    ) -> Self:
        """Return the model of a project's detail (``writable``: ``project.write``)."""
        project = detail.project
        return cls(
            project=project.key,
            name=project.name,
            manifests=[ProjectManifest.of(item) for item in project.manifests],
            missing_pins=project.missing_pins,
            project_write=writable(project.access_key),
            tasks=[ProjectTask.of(task) for task in detail.tasks],
            pins=[ProjectPin.of(pin) for pin in detail.pins],
            problems=[Issue.of(problem) for problem in detail.problems],
            **freshness,
        )


class TaskStatus(BaseModel):
    """A task's state as the producer checked it."""

    model_config = _examples({"task": "teren", "status": "ok"})

    task: str
    status: str | None = Field(
        description="`ok`, `not_downloaded`, `missing` or `corrupt` (worst file)."
    )


_MANIFEST_STATUS_EXAMPLE = {
    "producer": "kartograf",
    "status": "ok",
    "checked_at": "2026-10-18T14:05:12Z",
    "stale": False,
    "stale_reason": None,
    "tasks": [{"task": "teren", "status": "ok"}],
}


class ManifestStatus(BaseModel):
    """A producer's check of its manifest of a project now."""

    model_config = _examples(_MANIFEST_STATUS_EXAMPLE)

    producer: str
    status: str | None = Field(description="The worst task status.")
    checked_at: datetime = Field(
        description="When the producer checked: now, or the last scan when stale."
    )
    stale: bool = Field(
        description="True: the store is unavailable, the scan's check is shown."
    )
    stale_reason: Literal["store_unavailable"] | None
    tasks: list[TaskStatus]


class ProjectStatus(BaseModel):
    """The producers' checks of a project now (no network, no hashing)."""

    model_config = _examples(
        {
            "project": "raba",
            "manifests": [
                _MANIFEST_STATUS_EXAMPLE,
                {
                    **_MANIFEST_STATUS_EXAMPLE,
                    "producer": "imgw",
                    "status": "not_downloaded",
                    "tasks": [{"task": "przeplywy", "status": "not_downloaded"}],
                },
            ],
        }
    )

    project: str
    manifests: list[ManifestStatus] = Field(
        description="The check of each manifest of the project, in their order."
    )


class ProjectRequest(BaseModel):
    """A new project of a producer bound to a configured store (`POST /projects`)."""

    model_config = _examples(
        {"producer": "kartograf", "path": f"{_PROJECT_DIRS}/raba", "store": _STORE},
        closed=True,
    )

    producer: str = Field(
        min_length=1,
        description="Producer that writes the project's manifest, e.g. `kartograf`.",
    )
    path: str = Field(
        min_length=1,
        description=(
            "Absolute path of the project directory, made when missing: a project"
            " directory of the settings or a directory at most four levels below"
            " one, in no hidden directory and no store, where a scan finds it."
        ),
    )
    store: str = Field(
        min_length=1,
        description=(
            "Id of the configured store whose directory of the producer the"
            " manifest names: relative to the project directory when the store has"
            " path aliases, else absolute; never the producer's default root."
        ),
    )


class TaskRequest(BaseModel):
    """A task added to a project by its producer (`POST /projects/{project}/tasks`)."""

    model_config = _examples(
        {
            "name": _TASK_EXAMPLE["task"],
            "command": _TASK_EXAMPLE["command"],
            "options": _TASK_EXAMPLE["options"],
        },
        closed=True,
    )

    name: str = Field(
        min_length=1, description="Name of the new task; the producer's rules apply."
    )
    command: str = Field(
        min_length=1,
        description="Data command of the producer's catalog (`GET /commands`).",
    )
    options: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Its options in the JSON form of the catalog, checked without the"
            " network; no option that is a file path (`path_role`)."
        ),
    )
    producer: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "The producer whose manifest gets the task; left out: the project's"
            " only one. A project holding the manifests of several producers needs"
            " it (`producer_required`); a producer without a manifest in the"
            " project is refused (`other_producer`)."
        ),
    )


class ProjectJobRequest(BaseModel):
    """A job of a project's tasks (`POST /projects/{project}/jobs`)."""

    model_config = _examples(
        {"kind": "download"},
        {"kind": "repin", "tasks": [_TASK_EXAMPLE["task"]]},
        {"kind": "verify", "producer": "kartograf"},
        closed=True,
    )

    kind: ProjectJobKind = Field(
        description=(
            "`download`: download and pin the tasks not downloaded yet and restore"
            " missing pinned versions with the same SHA-256 (a task whose pins the"
            " store holds is left as it is); `repin`: pin one task anew to the"
            " source's newer versions. Both run over the network and write the"
            " store and the manifest, so they need the project's owner or an"
            " administrator and the role `store_writer` or the setting"
            " `store_write_for_all`. `check`: compare the pins with the source, over"
            " the network and without effects; `verify`: check the pinned files in"
            " the store (SHA-256, size, sidecar), without the network. Both need"
            " only to see the project."
        )
    )
    tasks: list[Annotated[str, Field(min_length=1)]] | None = Field(
        default=None,
        min_length=1,
        description=(
            "The tasks by name (`task` of /projects/{project}); left out or `null`:"
            " every task of the project. A `repin` names exactly one; a name given"
            " twice counts once."
        ),
    )
    producer: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "The producer whose manifest's tasks the job runs; left out: the"
            " project's only one. A project holding the manifests of several"
            " producers needs it (`producer_required`); a producer without a"
            " manifest in the project is refused (`other_producer`)."
        ),
    )

    @model_validator(mode="after")
    def _a_repin_names_one_task(self) -> Self:
        if self.kind == "repin" and len(set(self.tasks or ())) != 1:
            raise ValueError("a repin names exactly one task")
        return self


# Settings ------------------------------------------------------------------


class StoreSettings(BaseModel):
    """A configured store: a short id and the producers' directories."""

    model_config = _examples(_STORE_SETTINGS_EXAMPLE)

    id: str = Field(
        description="Short id in the API: lowercase letters, digits, '_', '-' (≤ 32)."
    )
    name: str
    kartograf: str | None = Field(
        default=None,
        description=(
            "Kartograf's store root: the directory that holds kartograf-store.json"
            " and the product directories (usually called data). Left out when the"
            " store has only `imgw`; one of the two is required."
        ),
    )
    imgw: str | None = Field(
        default=None,
        description=(
            "IMGWTools' store root, the directory that holds `imgw-store.json`. Left"
            " out when the store has only `kartograf`; a new or moved directory needs"
            " the source `imgw` to be available (`GET /sources`)."
        ),
    )
    kind: StoreKind | None = Field(
        default=None,
        description="`local` or `share`; detected from the file system when omitted.",
    )
    path_aliases: dict[str, str] = Field(
        default_factory=dict,
        description="Local path prefix → the same share's prefix on another computer.",
    )

    @classmethod
    def of(cls, store: StoreConfig) -> Self:
        """Return the model of a configured store."""
        return cls(
            id=store.id,
            name=store.name,
            kartograf=None if store.kartograf is None else str(store.kartograf),
            imgw=None if store.imgw is None else str(store.imgw),
            kind=store.kind,
            path_aliases=dict(store.path_aliases),
        )


class BasemapSettings(BaseModel):
    """An online basemap, used only when offline mode is off."""

    model_config = _examples(_BASEMAP_EXAMPLE)

    name: str
    kind: BasemapKind = Field(
        default="xyz",
        description=(
            "`xyz` raster tiles, `wms`, or `vector`: the TileJSON of OpenMapTiles"
            " vector tiles, drawn in Archiwista's grey style with Polish names."
        ),
    )
    url: str = Field(
        description=(
            "Tile template with {z}/{x}/{y}, a WMS address, or a TileJSON address"
            " (its tiles on the same origin)."
        )
    )
    attribution: str = ""
    grayscale: bool = Field(default=False, description="Raster tiles in grey.")

    @classmethod
    def of(cls, basemap: BasemapConfig) -> Self:
        """Return the model of a basemap."""
        return cls(
            name=basemap.name,
            kind=basemap.kind,
            url=basemap.url,
            attribution=basemap.attribution,
            grayscale=basemap.grayscale,
        )


class Settings(BaseModel):
    """All settings; PUT replaces all of them (omitted fields take defaults)."""

    model_config = _examples(
        {
            "port": 8090,
            "offline": False,
            "scan_threads": 8,
            "scan_interval_local_min": 5,
            "scan_interval_share_min": 15,
            "full_scan_interval_h": 24,
            "project_dirs": [_PROJECT_DIRS],
            "stores": [_STORE_SETTINGS_EXAMPLE],
            "basemaps": [_BASEMAP_EXAMPLE],
            "store_write_for_all": False,
            "default_project_visibility": "public",
            "preview_cache_limit_gb": 20,
            "preview_warm_after_scan": False,
        },
        closed=True,
    )

    port: int = Field(default=8090, ge=1024, le=65535, description="Port on 127.0.0.1.")
    offline: bool = Field(
        default=False,
        description="No external request from the browser (no online basemaps).",
    )
    scan_threads: int = Field(
        default=8, ge=1, le=64, description="Threads reading a store on a share."
    )
    scan_interval_local_min: int = Field(default=5, ge=1, le=1440)
    scan_interval_share_min: int = Field(default=15, ge=1, le=1440)
    full_scan_interval_h: int = Field(
        default=24,
        ge=1,
        le=720,
        description=(
            "Hours between scheduled full control scans; only a full scan"
            " notices files deleted or added inside known version directories."
        ),
    )
    project_dirs: list[str] = Field(
        default_factory=list, description="Absolute directories searched for projects."
    )
    stores: list[StoreSettings] = Field(default_factory=list)
    basemaps: list[BasemapSettings] = Field(
        default_factory=list,
        description=(
            "Grey OpenFreeMap (vector) and OSM GUGiK (raster, Poland only) when"
            " omitted."
        ),
    )
    store_write_for_all: bool = Field(
        default=False,
        description="Everyone may write to stores, not only `store_writer` (v0.3).",
    )
    default_project_visibility: DefaultProjectVisibility = Field(
        default="public",
        description="Visibility of a project without its own access entry.",
    )
    preview_cache_limit_gb: int = Field(
        default=20,
        ge=1,
        le=10_000,
        description="Preview cache limit in GB; the least recently used go first.",
    )
    preview_warm_after_scan: bool = Field(
        default=False,
        description=(
            "After a scan that indexed new versions of a store, prepare the first"
            " look at them (a `preview_warm` job of the scheduler, `params.since`"
            " the scan's start); off by default."
        ),
    )
    own_data_dirs: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Data folder of a project by its directory (after realpath); set with"
            " `PUT /projects/{project}/data-dir`. Without one: `<project>/dane`."
        ),
    )

    @classmethod
    def of(cls, settings: AppSettings) -> Self:
        """Return the model of the settings in effect."""
        return cls(
            port=settings.port,
            offline=settings.offline,
            scan_threads=settings.scan_threads,
            scan_interval_local_min=settings.scan_interval_local_min,
            scan_interval_share_min=settings.scan_interval_share_min,
            full_scan_interval_h=settings.full_scan_interval_h,
            project_dirs=[str(path) for path in settings.project_dirs],
            stores=[StoreSettings.of(store) for store in settings.stores],
            basemaps=[BasemapSettings.of(basemap) for basemap in settings.basemaps],
            store_write_for_all=settings.store_write_for_all,
            default_project_visibility=settings.default_project_visibility,
            preview_cache_limit_gb=settings.preview_cache_limit_gb,
            preview_warm_after_scan=settings.preview_warm_after_scan,
            own_data_dirs=dict(settings.own_data_dirs),
        )


# Areas and local coverage ---------------------------------------------------

_AREA_ID = "5f2b9c0e7d41a3b6"
_AREA_EXAMPLE = {
    "id": _AREA_ID,
    "name": "N-34-64-C-c-2-4",
    "source": "sheet",
    "geometry": _POLYGON,
    "bbox": [19.9375, 50.0417, 19.9688, 50.0625],
    "area_km2": 5.17,
    "area_crs": "EPSG:2180",
    "countries": ["PL"],
    "created_at": "2026-10-18T12:05:00Z",
}
_COUNTRY_COVERAGE_EXAMPLE = {
    "country": "PL",
    "crs": "EPSG:2180",
    "ratio": 0.8312,
    "percent": 83,
    "area_km2": 5.17,
    "covered_km2": 4.297,
    "versions_count": 3,
    "reason": None,
    "label": message("local.coverage_percent", "en", percent=83),
}


class AreaInput(BaseModel):
    """An area drawn on the map, the map view or a sheet: GeoJSON in WGS84.

    A file (GeoJSON, GeoPackage, Shapefile in a ZIP archive) is sent as the
    raw body instead (see `POST /areas`).
    """

    model_config = _examples(
        {"geometry": _POLYGON, "name": "N-34-64-C-c-2-4", "source": "sheet"},
        closed=True,
    )

    geometry: Geometry = Field(
        description=(
            "GeoJSON `Polygon` or `MultiPolygon` in WGS84 (longitude, latitude),"
            " at most 100 000 vertices."
        )
    )
    name: str | None = Field(
        default=None,
        max_length=200,
        description="Name shown with the area, e.g. a sheet code.",
    )
    source: Literal["drawn", "view", "sheet"] = Field(
        default="drawn",
        description=(
            "How the area was chosen: `drawn` (rectangle or polygon), `view` (the"
            " map view) or `sheet`."
        ),
    )


class Area(BaseModel):
    """An area kept in the index: geometry in WGS84, planar area, countries."""

    model_config = _examples(_AREA_EXAMPLE)

    id: str = Field(
        description="Area id; it comes from the geometry, so the same area keeps it."
    )
    name: str | None = Field(description="Name shown with the area.")
    source: str = Field(description="`drawn`, `view`, `sheet` or `file`.")
    geometry: Geometry = Field(description="GeoJSON polygon in WGS84.")
    bbox: list[float] = Field(description="`[min_lon, min_lat, max_lon, max_lat]`.")
    area_km2: float | None = Field(
        description="Area in km², measured in `area_crs`; null without a planar CRS."
    )
    area_crs: str | None = Field(
        description=(
            "Planar CRS of `area_km2`: of the first of `countries` in the order"
            " PL (EPSG:2180), CZ (EPSG:5514); null for other countries."
        )
    )
    countries: list[str] = Field(description="The producer's countries the area meets.")
    created_at: datetime

    @classmethod
    def of(cls, record: AreaRecord) -> Self:
        """Return the model of a kept area."""
        measured = record.area_km2 is not None
        return cls(
            id=record.id,
            name=record.name,
            source=record.source,
            geometry=record.geometry,
            bbox=list(polygon_bounds(record.geometry) or ()),
            area_km2=record.area_km2,
            area_crs=area_crs(record.countries) if measured else None,
            countries=list(record.countries),
            created_at=record.created_at,
        )


class AreaRef(BaseModel):
    """The area an answer is about."""

    model_config = _examples(
        {key: _AREA_EXAMPLE[key] for key in ("id", "name", "area_km2", "countries")}
    )

    id: str
    name: str | None
    area_km2: float | None
    countries: list[str]

    @classmethod
    def of(cls, record: AreaRecord) -> Self:
        """Return the reference of a kept area."""
        return cls(
            id=record.id,
            name=record.name,
            area_km2=record.area_km2,
            countries=list(record.countries),
        )


class CountryCoverage(BaseModel):
    """Local coverage of the area by the product in one country (decision 5)."""

    model_config = _examples(
        _COUNTRY_COVERAGE_EXAMPLE,
        {
            **_COUNTRY_COVERAGE_EXAMPLE,
            "country": None,
            "crs": None,
            "ratio": None,
            "percent": None,
            "area_km2": None,
            "covered_km2": None,
            "versions_count": 1,
            "reason": "no_planar_crs",
            "label": message("local.coverage_no_planar_crs", "en"),
        },
    )

    country: str | None = Field(
        description="Country of the files, e.g. `PL`; null for files without one."
    )
    crs: str | None = Field(description="Planar CRS of the measurement.")
    ratio: float | None = Field(
        description=(
            "Share of the area under the outlines of the current versions, 0–1"
            " (overlaps count once); null with `reason`."
        )
    )
    percent: int | None = Field(
        description="`ratio` in whole percent, rounded down: 100 only if fully covered."
    )
    area_km2: float | None = Field(description="The area in `crs`, km².")
    covered_km2: float | None = Field(description="Its covered part, km².")
    versions_count: int = Field(
        description="Current versions whose outline shares interior with the area."
    )
    reason: str | None = Field(
        description="Why there is no share: `no_planar_crs` or `empty_area`."
    )
    label: str = Field(description="Text for a person, e.g. `locally 83% of the area`.")

    @classmethod
    def of(cls, item: LocalCoverage) -> Self:
        """Return the model of one country's local coverage."""
        percent = None if item.ratio is None else _percent(item.ratio)
        return cls(
            country=item.country,
            crs=item.crs,
            ratio=item.ratio,
            percent=percent,
            area_km2=item.area_km2,
            covered_km2=item.covered_km2,
            versions_count=item.versions_count,
            reason=item.reason,
            label=_coverage_label(item, percent),
        )


class AreaCoverage(IndexAnswer):
    """Local state of a product for an area („lokalnie 83% obszaru”).

    The slots of the area are rescanned first (at most 500); when the store is
    unavailable, the rescan runs out of time or the area holds more slots, the
    answer comes from the index with `stale` and `stale_reason`.
    """

    model_config = _examples(
        {
            "area": {
                key: _AREA_EXAMPLE[key]
                for key in ("id", "name", "area_km2", "countries")
            },
            "store": _STORE,
            "product": "nmt",
            "segment": None,
            "results": [_COUNTRY_COVERAGE_EXAMPLE],
            "stale_reason": None,
            **_FRESH,
        }
    )

    area: AreaRef
    store: str = Field(description="Store id.")
    product: str = Field(description="Product, e.g. `nmt`.")
    segment: str | None = Field(description="The only segment measured, if asked for.")
    results: list[CountryCoverage] = Field(
        description=(
            "One result per country; empty when the store holds no version of the"
            " product for the area."
        )
    )
    stale_reason: str | None = Field(
        description=(
            "Why the slots were not rescanned first: `store_unavailable`,"
            " `refresh_timeout` or `too_many_slots`; null when they were."
        )
    )

    @classmethod
    def of(
        cls,
        record: AreaRecord,
        report: LocalCoverageReport,
        *,
        segment: str | None,
        freshness: Iterable[StoreFreshness],
    ) -> Self:
        """Return the answer of a local coverage report (``stale`` included)."""
        fields = staleness(freshness, {report.store})
        return cls(
            area=AreaRef.of(record),
            store=report.store,
            product=report.product,
            segment=segment,
            results=[CountryCoverage.of(item) for item in report.results],
            stale=report.stale or fields["stale"],
            stale_reason=report.stale_reason,
            stale_stores=fields["stale_stores"],
        )


class CoverageQuery(BaseModel):
    """The area, product and store of ``GET /local-coverage``."""

    model_config = ConfigDict(extra="forbid")

    area_id: str = Field(description="Area id (`POST /areas`).", examples=[_AREA_ID])
    product: str = Field(description="Product, e.g. `nmt`.", examples=["nmt"])
    store: str = Field(description="Store id.", examples=[_STORE])
    segment: str | None = Field(
        default=None,
        description="Only this segment (variant) of the product.",
        examples=[_SEGMENT],
    )


def _percent(ratio: float) -> int:
    """Whole percent rounded down, so that 100 means fully covered.

    Rounding to a millionth of a percent first absorbs the floating-point
    error of a measured full coverage.
    """
    return math.floor(round(ratio * 100, 6))


def _coverage_label(item: LocalCoverage, percent: int | None) -> str:
    if item.ratio is None or percent is None:
        if item.reason == "empty_area":
            return message("local.coverage_empty_area")
        return message("local.coverage_no_planar_crs")
    if percent == 0 and item.ratio > 0:
        return message("local.coverage_below_one")
    return message("local.coverage_percent", percent=percent)
