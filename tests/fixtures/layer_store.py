"""A hand-written store of one product's years, campaigns and editions.

The local layers (plan v0.2, step 11; decision 7) group a product's versions
by variant and data year. ``make_store`` writes no campaign ids and no sheet
of one year in two formats, so ``make_layer_store`` writes a small store of
its own: slot paths from Kartograf's ``FileStorage``, versions, links and
sidecars as ARCH 3.2-3.4 describe them (as ``make_store`` writes its own),
read back with ``iter_store`` before it returns. Around the 1:25 000 sheet
``AREA_SHEET`` (PL-1992, four 1:10 000 sheets):

- the NMT ASC sheets ``SHEET_NW`` (campaigns of 2019 and 2023) and
  ``SHEET_NE`` (two campaigns of 2023) of ``nmt/pl_1992_1m_evrf2007``; they
  meet along a meridian;
- ``SHEET_NW`` of 2023 also as the ASCII-NMT archive
  (``nmt/pl_1992_ascii-nmt_1m_evrf2007``): one variant in two formats;
- ``SHEET_SW`` of 2023 with a sidecar without ``resolution`` and
  ``vertical_crs``, so its variant is its segment;
- a WCS cutout ``bbox/<coords>.tif`` in ``SHEET_SE`` labelled by its
  download date: no data year;
- ``SHEET_FAR`` of 2019, away from the area;
- a BDOT10k GeoPackage of powiat ``TERYT`` in two editions without a year.

Every version was downloaded in 2025 or 2026, never in its data year.
``add_campaign`` adds a flight later, as a download does;
``served_layer_store`` scans the store into a fresh index and serves it
with render processes and jobs (``tests.fixtures.preview_api``).
"""

import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import kartograf
from kartograf import FileStorage, SheetParser, describe_segment, iter_store

from archiwista.config import ConfigStore
from archiwista.index import IndexWriter, initialize, scan_store
from archiwista.sources.registry import load_registry
from tests.fixtures import store_files
from tests.fixtures.api_store import STORE, store_settings
from tests.fixtures.local_server import local_paths
from tests.fixtures.make_store import (
    BDOT_GPKG,
    NMT,
    NMT_ASCII,
    PROJECTS_DIR,
    STORE_DIR,
    StoreFixtureError,
    StoreManifest,
)
from tests.fixtures.preview_api import PreviewApi, serve_previews
from tests.fixtures.store_files import Bounds
from tests.fixtures.store_marker import mark_store

PRODUCT = "nmt"
AREA_SHEET = "N-34-130-D-d-2"
"""1:25 000 sheet made of the four 1:10 000 sheets below."""
SHEET_NW = "N-34-130-D-d-2-1"
SHEET_NE = "N-34-130-D-d-2-2"
SHEET_SW = "N-34-130-D-d-2-3"
SHEET_SE = "N-34-130-D-d-2-4"
SHEET_FAR = "N-34-130-D-d-4-4"
"""A sheet of the store that does not even touch ``AREA_SHEET``."""
TERYT = "1425"
EDITIONS = ("12", "13")
"""BDOT10k editions: neither a date nor a four-digit year."""
CUTOUT_LABEL = "2025-03-14"
"""Download date that labels the WCS cutout (``label_source`` ``downloaded``)."""
CUTOUT_BOUNDS: Bounds = (770_500.0, 509_000.0, 771_500.0, 510_000.0)
"""The cutout's request box in EPSG:2180, inside ``SHEET_SE``."""

_CRS = "EPSG:2180"
_EVRF2007 = "EPSG:9651"
_LICENSE = {"id": "fixture", "attribution": "Archiwista test store", "url": None}


@dataclass(frozen=True)
class StoredVersion:
    """A version of the store: its path and what its layer is made of."""

    path: str
    segment: str
    unit: str
    data_year: int | None
    campaign: str | None = None
    edition: str | None = None


@dataclass(frozen=True)
class LayerStore:
    """The written store (``manifest`` for the API fixtures) and its versions."""

    manifest: StoreManifest
    versions: tuple[StoredVersion, ...]

    @property
    def root(self) -> Path:
        """The Kartograf store root (``data/``)."""
        return self.manifest.root

    def version(self, unit: str, campaign: str, segment: str = NMT) -> StoredVersion:
        """Return the version of a sheet's flight in a segment."""
        return next(
            item
            for item in self.versions
            if (item.unit, item.campaign, item.segment) == (unit, campaign, segment)
        )

    def by_path(self, path: str) -> StoredVersion:
        """Return the version at a path of the store."""
        return next(item for item in self.versions if item.path == path)


@dataclass(frozen=True)
class ServedLayers:
    """The layer store served with render processes and jobs."""

    store: LayerStore
    api: PreviewApi


def make_layer_store(base: Path) -> LayerStore:
    """Write the store under ``base`` (``data/`` and an empty ``projects/``).

    Raises
    ------
    StoreFixtureError
        Kartograf reads the store otherwise than it was written.
    """
    base = base.absolute()
    root = base / STORE_DIR
    root.mkdir(parents=True)
    mark_store(root)
    (base / PROJECTS_DIR).mkdir()
    versions = [
        add_campaign(root, SHEET_NW, "2019-05-10", "41022", downloaded="2025-02-03"),
        add_campaign(root, SHEET_NW, "2023-06-02", "82710", downloaded="2026-01-15"),
        add_campaign(root, SHEET_NE, "2023-06-02", "82710", downloaded="2025-11-20"),
        add_campaign(root, SHEET_NE, "2023-09-14", "83501", downloaded="2026-03-02"),
        _ascii_nmt(root, SHEET_NW, "2023-06-02", "82710", downloaded="2026-01-15"),
        add_campaign(
            root,
            SHEET_SW,
            "2023-06-02",
            "82710",
            downloaded="2025-12-01",
            described=False,
        ),
        _cutout(root),
        add_campaign(root, SHEET_FAR, "2019-04-23", "40987", downloaded="2025-06-30"),
        *(_edition(root, edition, number) for number, edition in enumerate(EDITIONS)),
    ]
    _verify(root, versions)
    return LayerStore(StoreManifest(base, 0, 0, (), ()), tuple(versions))


@contextmanager
def served_layer_store(directory: Path) -> Iterator[ServedLayers]:
    """Write the store under ``directory``, scan it fully and serve it."""
    store = make_layer_store(directory / "store")
    paths = local_paths(directory)
    settings = store_settings(store.manifest)
    ConfigStore(paths.config_file).save(settings)
    registry = load_registry(cache_dir=paths.cache_dir)
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: {"kartograf": store.root}})
        scan_store(registry.adapter("kartograf"), writer, settings, STORE, mode="full")
    with serve_previews(store.manifest, paths) as api:
        yield ServedLayers(store, api)


def add_campaign(
    root: Path,
    sheet: str,
    day: str,
    campaign: str,
    *,
    downloaded: str,
    described: bool = True,
) -> StoredVersion:
    """Write an ASC version of a flight over an NMT sheet and link it.

    The standard path names it from then on, as after its download.
    ``downloaded`` is the day of the download; ``described`` ``False``
    leaves ``resolution`` and ``vertical_crs`` out of the sidecar. The
    flight's number is the first cell, so every flight has its own content.
    """
    storage = FileStorage(root, resolution="1m", vertical_crs="EVRF2007")
    meta = _meta(
        NMT,
        resolution="1m" if described else None,
        vertical_crs=_EVRF2007 if described else None,
        request={"sheet": sheet},
        extra=_campaign_extra(sheet, day, campaign),
        downloaded=downloaded,
    )
    path = _put(
        root,
        storage.get_versions_root(sheet),
        storage.get_path(sheet, ".asc"),
        store_files.asc_grid(sheet_bounds(sheet), int(campaign)),
        meta,
    )
    return StoredVersion(path, NMT, sheet, int(day[:4]), campaign=campaign)


def survey_work(campaign: str, day: str) -> str:
    """Return the survey work of a flight: what a source's report names it by."""
    return f"GK.6640.{campaign}.{day[:4]}"


def sheet_bounds(sheet: str) -> Bounds:
    """Return a PL-1992 sheet's box in EPSG:2180 (what its ASC grid covers)."""
    found = SheetParser(sheet).get_bbox()
    return (found.min_x, found.min_y, found.max_x, found.max_y)


def sheet_polygon(sheet: str) -> dict[str, Any]:
    """Return a PL-1992 sheet as a GeoJSON polygon in WGS84 (a lon/lat box)."""
    found = SheetParser(sheet).get_bbox(crs="EPSG:4326")
    west, south, east, north = found.min_x, found.min_y, found.max_x, found.max_y
    ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
    return {"type": "Polygon", "coordinates": [ring]}


def _ascii_nmt(
    root: Path, sheet: str, day: str, campaign: str, *, downloaded: str
) -> StoredVersion:
    """Write a flight over a sheet as the ASCII-NMT archive (an XYZ member)."""
    storage = FileStorage(
        root, resolution="1m", vertical_crs="EVRF2007", format="ASCII-NMT"
    )
    grid = store_files.xyz_grid(sheet_bounds(sheet), int(campaign))
    meta = _meta(
        NMT_ASCII,
        resolution="1m",
        vertical_crs=_EVRF2007,
        request={"sheet": sheet, "format": "ASCII-NMT"},
        extra=_campaign_extra(sheet, day, campaign),
        downloaded=downloaded,
    )
    path = _put(
        root,
        storage.get_versions_root(sheet),
        storage.get_path(sheet, ".zip"),
        store_files.zip_members([(f"{sheet}.xyz", grid)]),
        meta,
    )
    return StoredVersion(path, NMT_ASCII, sheet, int(day[:4]), campaign=campaign)


def _cutout(root: Path) -> StoredVersion:
    """Write a WCS cutout of NMT labelled by its download date."""
    code = "_".join(format(value, ".10g") for value in CUTOUT_BOUNDS)
    base = root.joinpath(*NMT.split("/"))
    meta = _meta(
        NMT,
        resolution="1m",
        vertical_crs=_EVRF2007,
        request={"bbox": list(CUTOUT_BOUNDS), "bbox_crs": _CRS},
        extra={"version": {"label": CUTOUT_LABEL, "label_source": "downloaded"}},
        downloaded=CUTOUT_LABEL,
    )
    path = _put(
        root,
        base / "versions" / "bbox",
        base / "bbox" / f"{code}.tif",
        store_files.geotiff(CUTOUT_BOUNDS, 2180, 1),
        meta,
    )
    return StoredVersion(path, NMT, code, None)


def _edition(root: Path, edition: str, number: int) -> StoredVersion:
    """Write an edition of the BDOT10k GeoPackage of a powiat (``teryt/``)."""
    min_x, min_y, max_x, max_y = sheet_bounds(AREA_SHEET)
    bounds = (min_x + 500.0, min_y + 500.0, max_x - 500.0, max_y - 500.0)
    base = root.joinpath(*BDOT_GPKG.split("/"))
    meta = _meta(
        BDOT_GPKG,
        resolution=None,
        vertical_crs=None,
        request={"teryt": TERYT},
        extra={"version": {"label": edition, "label_source": "edition"}},
        downloaded=f"2025-0{number + 4}-01",
    )
    path = _put(
        root,
        base / "versions" / "teryt",
        base / "teryt" / f"{TERYT}.gpkg",
        store_files.geopackage(bounds, 2180, number),
        meta,
    )
    return StoredVersion(path, BDOT_GPKG, TERYT, None, edition=edition)


def _campaign_extra(sheet: str, day: str, campaign: str) -> dict[str, Any]:
    """``extra`` of a flight's version (ADR-036 label, ``extra.campaign``)."""
    work = survey_work(campaign, day)
    return {
        "version": {"label": f"{day}_{campaign}", "label_source": "campaign"},
        "campaign": {
            "id": campaign,
            "date": day,
            "survey_work_id": work,
            "full_sheet": False,
        },
        "source": {
            "sheet": sheet,
            "acquisition_date": day,
            "acquisition_year": int(day[:4]),
            "survey_work_id": work,
            "full_sheet": False,
        },
    }


def _meta(
    segment: str,
    *,
    resolution: str | None,
    vertical_crs: str | None,
    request: dict[str, Any],
    extra: dict[str, Any],
    downloaded: str,
) -> dict[str, Any]:
    """Return a ``kartograf-meta/1`` sidecar without ``sha256``, ``None`` left out."""
    info = describe_segment(segment)
    meta: dict[str, Any] = {
        "schema": "kartograf-meta/1",
        "dataset": info.dataset_key,
        "country": info.country,
        "product": info.product,
        "provider": "GUGiK",
        "horizontal_crs": _CRS,
        "vertical_crs": vertical_crs,
        "vertical_source": None if vertical_crs is None else "native",
        "resolution": resolution,
        "nodata": float(store_files.NODATA) if segment == NMT else None,
        "request": request,
        "license": dict(_LICENSE),
        "downloaded_at": f"{downloaded}T12:00:00+00:00",
        "kartograf_version": kartograf.__version__,
        "extra": extra,
    }
    return {key: value for key, value in meta.items() if value is not None}


def _put(
    root: Path, versions: Path, link: Path, data: bytes, meta: dict[str, Any]
) -> str:
    """Write a version directory and point the standard path at it.

    Returns the version's path in the store.
    """
    sha256 = hashlib.sha256(data).hexdigest()
    label = meta["extra"]["version"]["label"]
    version = versions / f"{label}_{sha256[:8]}" / link.name
    version.parent.mkdir(parents=True)
    version.write_bytes(data)
    meta = {**meta, "sha256": sha256, "size_bytes": len(data)}
    _write_json(version, meta)
    link.parent.mkdir(parents=True, exist_ok=True)
    link.unlink(missing_ok=True)
    os.link(version, link)
    target = Path(os.path.relpath(version, link.parent)).as_posix()
    extra = {**meta["extra"], "link": "hardlink", "link_target": target}
    _write_json(link, {**meta, "extra": extra})
    return version.relative_to(root).as_posix()


def _write_json(path: Path, content: dict[str, Any]) -> None:
    sidecar = path.with_name(path.name + ".meta.json")
    sidecar.write_text(
        json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _verify(root: Path, versions: list[StoredVersion]) -> None:
    """Check that Kartograf reads every version as written, without problems."""
    expected = {
        item.path: (item.unit, item.data_year, item.campaign, item.edition)
        for item in versions
    }
    found: dict[str, tuple[object, ...]] = {}
    problems = []
    for entry in iter_store(root):
        if entry.problem is not None:
            problems.append(f"{entry.path}: {entry.problem}")
        elif entry.kind == "version" and entry.sidecar is not None:
            meta = entry.sidecar
            campaign = (meta.campaign or {}).get("id")
            path = entry.path.relative_to(root).as_posix()
            found[path] = (meta.unit, meta.data_year, campaign, meta.edition)
    if problems or found != expected:
        raise StoreFixtureError(
            f"Kartograf reads the layer store otherwise: {problems or found}"
        )
