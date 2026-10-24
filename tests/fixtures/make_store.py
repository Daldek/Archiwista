"""Synthetic Kartograf store for Archiwista tests (plan v0.1 step 4, v0.2 step 2).

``make_store(output_dir, slots=..., seed=...)`` writes under ``output_dir``:

- ``data/`` - a Kartograf store (the ``--output`` directory, ARCH 3.2-3.3)
  with every product family Archiwista reads: 64 x 64 rasters (ASC sheets,
  GeoTIFF sheets and cutouts, a JPEG with world files), small GeoPackages,
  ZIP packages, a point cloud, collections by TERYT, KU and country and an
  HSG raster; several versions per slot, the standard-path link and
  ``full_sheet/`` links;
- on top of ``slots``, once per store, the file families of plan v0.2
  (decision 5, case ``file_family``): a CORINE WMS preview PNG without
  georeference, a CORINE class GeoTIFF with a palette, a striped RGBA
  BDOT10k map above 4096 px and its PDF, a tiled oblique EPSG:2177 GeoTIFF
  with overviews, a SoilGrids EPSG:4326 GeoTIFF, a LoD2 ZIP with CityGML and
  PDF members, a compressed LAZ with classes 2, 3 and 6 and a two-layer
  GeoPackage; a standard-path file with a 0.7.x sidecar without ``sha256``
  (``no_sha256``) and one NMT sheet in two formats, ASC and ASCII-NMT
  (``two_formats``);
- ``projects/`` - ``kartograf-project.json`` manifests with tasks and pins
  (also of an older version, a missing version and another store) and one
  invalid manifest;
- ``other-data/`` - an empty directory named by one project as its store.

Every footprint lies where its data would: the files of the Czech segments
inside ``CZ_OUTLINE``, all others inside ``PL_OUTLINE``. PL-1992 sheets come
from the 1:100 000 sheets inside Poland, bboxes and header extents are drawn
again until they lie inside the outline, and TERYT units are real powiat
codes.

Slot paths and project manifests come from Kartograf's public API where it
exists (``FileStorage``, ``init_project``, ``add_project_task``). The 0.8.0
API has no offline writer of versions, sidecars, links or pins, so those are
written here following ARCH 3.2-3.5, the way Kartograf's own reader tests do.
Only the deliberately broken cases are hand-crafted beyond that: missing and
unreadable sidecars, an unknown segment, ``kampanie/``, a stale
``.incoming``, 0.8.0-dev dataset keys and segments, a sidecar written before
ADR-031, a link sidecar naming another version than the link and an invalid
manifest.

The generator verifies its own output with Kartograf's readers before it
returns: ``iter_store`` must give exactly the expected entries (problems
included) and ``open_project`` must accept every valid manifest and reject
the invalid one. A mismatch raises ``StoreFixtureError``.

Run ``python -m tests.fixtures.make_store --slots 50000 --seed 1
<katalog-danych>/store-50k`` for the performance store; keep it outside the
repository and outside ``/tmp``.
"""

import argparse
import functools
import hashlib
import json
import math
import os
import random
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal, cast

import kartograf
import shapely
from kartograf import (
    BBox,
    FileStorage,
    SheetParser,
    StoreEntry,
    ValidationError,
    add_project_task,
    describe_segment,
    init_project,
    iter_store,
    open_project,
    transform_bbox,
)

from tests.fixtures import store_files
from tests.fixtures.store_files import Bounds

STORE_DIR = "data"
PROJECTS_DIR = "projects"
OTHER_STORE_DIR = "other-data"
MANIFEST_NAME = "kartograf-project.json"

EntryKind = Literal["version", "link", "full_sheet", "problem"]
ProblemCode = Literal[
    "missing_sidecar",
    "invalid_sidecar",
    "unknown_segment",
    "legacy_campaigns",
    "stale_incoming",
]
Family = Literal[
    "asc_sheet",
    "tif_sheet",
    "tif_bbox",
    "jpg_sheet",
    "jgw_sheet",
    "gpkg_teryt",
    "zip_teryt",
    "zip_country",
    "zip_ku",
    "laz_tile",
    "hsg_bbox",
    # plan v0.2 decision 5 (``file_families``, on top of ``slots``):
    "png_preview",
    "tif_classes",
    "tif_map",
    "pdf_map",
    "tif_oblique",
    "tif_wgs84",
    "zip_citygml",
    "laz_compressed",
    "gpkg_layers",
    "zip_ascii_nmt",
]
Case = Literal[
    "regular",
    "dev_dataset_key",
    "dev_segment",
    "pre_adr031",
    "link_mismatch",
    "missing_sidecar",
    "invalid_sidecar",
    "unknown_segment",
    "legacy_campaigns",
    "stale_incoming",
    "file_family",
    "no_sha256",
    "two_formats",
]
ProjectCase = Literal["regular", "missing_version", "other_store", "invalid_manifest"]
Row = tuple[str, str, str, str, str | None, str | None, str | None, str | None]
"""``(kind, segment, hierarchy, path, version_path, label, sha8, problem)``."""

# Segments written by the generator (the writers' names, ARCH 3.3).
NMT = "nmt/pl_1992_1m_evrf2007"
NMT_KRON86 = "nmt/pl_1992_1m_kron86"
NMT_2000 = "nmt/pl_2000_1m_evrf2007"
NMPT = "nmpt/pl_1992_1m_evrf2007"
ORTO = "orto/pl_1992"
LAZ = "laz/pl_1992_evrf2007"
CZ_ORTO = "orto/cz_sjtsk"
CZ_NMT = "nmt/cz_dmr5g_bpv"
BDOT_GPKG = "landcover/pl_bdot10k_gpkg"
EGIB_GPKG = "cadastre/pl_egib_gpkg"
BUILDINGS = "models3d/pl_buildings_lod1_2024"
BDOT_SHP = "landcover/pl_bdot10k_shp"
PRG_GML = "boundaries/pl_prg_gml"
PRG_SHP = "boundaries/pl_prg_shp"
CZ_CADASTRE = "cadastre/cz_cadastral-map_shp"
HSG = "hsg/global_soilgrids_0-5cm_mean"
DEV_SEGMENT = "orto/pl_1992_true"
UNKNOWN_SEGMENT = "newproduct/pl_experimental"
DEV_DATASET = "pl.gugik.buildings_3d"
# Segments of the plan v0.2 file families (decision 5).
CORINE_PREVIEW = "landcover/eu_corine_2018_preview"
CORINE = "landcover/eu_corine_2018"
BDOT_MAP_TIFF = "maps/pl_bdot10k_10000_tiff"
BDOT_MAP_PDF = "maps/pl_bdot10k_10000_pdf"
OBLIQUE = "oblique-orto/pl_2000"
OBLIQUE_SHEET = "6.179.12.20.1"
"""PL-2000 zone 6 (EPSG:2177) sheet 1:1000 of the oblique orthophoto."""
SOILGRIDS = "soil/global_soilgrids_clay_0-5cm_mean"
BUILDINGS_LOD2 = "models3d/pl_buildings_lod2_2017"
BDOT_GPKG_LAYERS = "landcover/pl_bdot10k_gpkg_ptwp-swrs"
NMT_ASCII = "nmt/pl_1992_ascii-nmt_1m_evrf2007"
LEGACY_KARTOGRAF = "0.7.4"
"""``kartograf_version`` of the sidecar without ``sha256`` (case no_sha256)."""

# Regular slots of the base catalogue (every family once, see base_catalogue).
MIN_SLOTS = 17
# Project directories with a special case (missing version, other store,
# invalid manifest); the rest are regular.
MIN_PROJECTS = 4
PIN_TIME = "2026-09-01T12:00:00+00:00"
STALE_MTIME = 1_577_836_800.0  # 2020-01-01: always older than 24 h

# Every footprint lies inside one of these coarse country outlines (WGS84
# longitude, latitude), taken from Natural Earth 1:10m Admin 0 - Countries
# 5.1.1 (https://www.naturalearthdata.com, public domain): the largest part of
# the country shrunk by 8 km and simplified with a 5 km tolerance in
# EPSG:3035, so every point lies at least 3 km inside the Natural Earth border.
PL_OUTLINE = shapely.from_wkt(
    "POLYGON ((14.653 53.922, 16.224 54.196, 16.613 54.488, 17.376 54.68, "
    "18.158 54.767, 18.292 54.762, 18.49 54.39, 18.862 54.28, 19.629 54.371, "
    "22.691 54.271, 22.873 54.315, 23.26 54.17, 23.763 53.133, 23.803 52.748, "
    "23.308 52.56, 23.049 52.279, 23.117 52.184, 23.539 52.027, 23.429 51.582, "
    "23.564 51.404, 23.529 51.278, 23.904 50.884, 23.847 50.778, 23.98 50.564, "
    "23.896 50.462, 23.603 50.419, 22.674 49.714, 22.531 49.535, 22.572 49.157, "
    "22.112 49.262, 21.996 49.387, 21.619 49.497, 21.046 49.49, 20.907 49.381, "
    "20.709 49.471, 20.292 49.462, 19.998 49.286, 19.475 49.671, 19.069 49.478, "
    "18.878 49.711, 18.713 49.765, 18.626 49.964, 18.019 50.118, 17.861 50.061, "
    "17.767 50.372, 17.444 50.336, 16.864 50.502, 16.754 50.429, 16.843 50.271, "
    "16.664 50.179, 16.406 50.43, 16.539 50.567, 16.406 50.698, 16.067 50.718, "
    "15.374 50.905, 15.331 51.022, 15.073 51.078, 15.067 51.453, 14.844 51.568, "
    "14.72 51.818, 14.878 52.071, 14.664 52.393, 14.755 52.603, 14.281 52.878, "
    "14.561 53.247, 14.416 53.609, 14.598 53.527, 14.743 53.626, 14.75 53.865, "
    "14.653 53.922))"
)
"""Poland: every file except those of the Czech segments."""
CZ_OUTLINE = shapely.from_wkt(
    "POLYGON ((12.348 50.092, 12.577 50.325, 12.997 50.338, 13.631 50.64, "
    "14.474 50.859, 14.816 50.746, 15.057 50.805, 15.131 50.911, 15.311 50.709, "
    "15.727 50.664, 15.96 50.533, 16.275 50.578, 16.093 50.383, 16.559 50.046, "
    "16.731 50.026, 17.074 50.152, 17.104 50.307, 17.475 50.173, 17.786 49.91, "
    "18.038 49.929, 18.455 49.827, 18.532 49.666, 18.715 49.566, 18.467 49.538, "
    "18.072 49.302, 17.989 49.093, 17.54 48.892, 17.133 48.928, 16.929 48.78, "
    "16.525 48.877, 16.105 48.816, 15.858 48.939, 14.968 49.079, 14.845 48.85, "
    "14.599 48.693, 14.425 48.712, 14.307 48.636, 14.143 48.659, 13.678 49.002, "
    "13.489 49.04, 13.069 49.351, 12.736 49.476, 12.541 49.736, 12.627 49.933, "
    "12.348 50.092))"
)
"""Czechia: the files of the Czech segments."""
_OUTLINES = {"EPSG:2180": PL_OUTLINE, "EPSG:5514": CZ_OUTLINE}
"""Outline of the country of a national CRS, the CRS of its drawn bboxes."""
_PROVIDERS = {"PL": "GUGiK", "CZ": "CUZK", "GLOBAL": "ISRIC"}
_LICENSE = {
    "id": "fixture",
    "attribution": "Archiwista synthetic test store",
    "url": None,
}

# Bulk mix by regular slot (SPEC 4.5 store: mostly sheets, ~1.6 versions).
_BULK_WEIGHTS: tuple[tuple[str, int], ...] = (
    ("nmt", 38),
    ("nmpt", 14),
    ("kron86", 4),
    ("orto", 14),
    ("laz", 10),
    ("tif_bbox", 7),
    ("gpkg_teryt", 4),
    ("zip_teryt", 4),
    ("cz_orto", 3),
    ("hsg", 2),
)
_VERSION_COUNTS = (1, 2, 3, 4)
_VERSION_WEIGHTS = (55, 33, 9, 3)
_FULL_SHEET_SHARE = 0.03


class StoreFixtureError(AssertionError):
    """Kartograf's readers disagree with the store the generator wrote."""


class _UnitsUsedUp(ValueError):
    """Every unit code of a pool already has its slot."""


@dataclass(frozen=True)
class ExpectedEntry:
    """One entry ``kartograf.iter_store`` must yield for the store.

    Paths are relative to the store root (``data/``) with ``/``. ``sha256``,
    ``dataset_key``, ``unit`` and ``data_year`` are what the entry's sidecar
    gives (``None`` for problems without a readable sidecar).
    """

    kind: EntryKind
    segment: str
    hierarchy: str
    path: str
    version_path: str | None = None
    label: str | None = None
    sha8: str | None = None
    problem: ProblemCode | None = None
    family: Family | None = None
    case: Case = "regular"
    sha256: str | None = None
    size_bytes: int | None = None
    dataset_key: str | None = None
    unit: str | None = None
    data_year: int | None = None
    current: bool = False
    """A version targeted by its slot's standard-path link."""

    @property
    def row(self) -> Row:
        """The fields compared with a ``StoreEntry``."""
        return (
            self.kind,
            self.segment,
            self.hierarchy,
            self.path,
            self.version_path,
            self.label,
            self.sha8,
            self.problem,
        )


@dataclass(frozen=True)
class ExpectedPin:
    """A pinned file of a project task (``files[]`` of the manifest)."""

    path: str
    version: str
    label: str
    sha256: str
    size_bytes: int
    unit: str
    current: bool
    """The pinned version is the slot's current one."""
    present: bool
    """The pinned version exists in the store."""


@dataclass(frozen=True)
class ExpectedTask:
    """A task of a project manifest."""

    name: str
    command: str
    pins: tuple[ExpectedPin, ...] = ()


@dataclass(frozen=True)
class ExpectedProject:
    """A project directory with ``kartograf-project.json``."""

    name: str
    path: str
    """Relative to ``output_dir`` with ``/``."""
    store: str
    """Directory (relative to ``output_dir``) the manifest names as store."""
    case: ProjectCase
    valid: bool
    tasks: tuple[ExpectedTask, ...] = ()


@dataclass(frozen=True)
class StoreManifest:
    """What the generated store must look like to Kartograf's readers."""

    output_dir: Path
    seed: int
    slots: int
    """Regular slots requested (base catalogue + bulk)."""
    entries: tuple[ExpectedEntry, ...]
    projects: tuple[ExpectedProject, ...]

    @property
    def root(self) -> Path:
        """The Kartograf store (``--output`` directory)."""
        return self.output_dir / STORE_DIR

    @property
    def projects_dir(self) -> Path:
        """Directory holding every project directory."""
        return self.output_dir / PROJECTS_DIR

    @property
    def rows(self) -> frozenset[Row]:
        """Rows of every expected entry."""
        return frozenset(entry.row for entry in self.entries)

    def by_kind(self, kind: EntryKind) -> tuple[ExpectedEntry, ...]:
        """Return the expected entries of one kind."""
        return tuple(entry for entry in self.entries if entry.kind == kind)

    def by_case(self, case: Case) -> tuple[ExpectedEntry, ...]:
        """Return the expected entries of one generator case."""
        return tuple(entry for entry in self.entries if entry.case == case)

    def by_family(self, family: Family) -> tuple[ExpectedEntry, ...]:
        """Return the expected entries of one data family."""
        return tuple(entry for entry in self.entries if entry.family == family)

    def segments(self) -> tuple[str, ...]:
        """Return the sorted segments of the store."""
        return tuple(sorted({entry.segment for entry in self.entries}))

    def project(self, name: str) -> ExpectedProject:
        """Return the project called ``name``."""
        return next(project for project in self.projects if project.name == name)


def entry_row(entry: StoreEntry, root: Path) -> Row:
    """Return the comparable row of a ``StoreEntry`` yielded for ``root``."""
    version = entry.version_path
    return (
        entry.kind,
        entry.segment,
        entry.hierarchy,
        entry.path.relative_to(root).as_posix(),
        version.relative_to(root).as_posix() if version is not None else None,
        entry.label,
        entry.sha8,
        entry.problem,
    )


def make_store(
    output_dir: Path, *, slots: int, seed: int, projects: int = MIN_PROJECTS
) -> StoreManifest:
    """Write the synthetic store and projects and verify them with Kartograf.

    Parameters
    ----------
    output_dir : Path
        Missing or empty directory; receives ``data/``, ``projects/`` and
        ``other-data/``.
    slots : int
        Regular slots (standard-path links) of the store, at least
        ``MIN_SLOTS``: the base catalogue with every family, then a bulk mix
        in SPEC 4.5 proportions. Deliberate edge cases come on top.
    seed : int
        Seed of every random choice (units, dates, labels, contents).
    projects : int, optional
        Project directories, at least ``MIN_PROJECTS`` (three special cases
        plus regular projects).

    Returns
    -------
    StoreManifest
        The expected entries and projects.

    Raises
    ------
    ValueError
        Too few slots or projects, or a non-empty ``output_dir``.
    StoreFixtureError
        Kartograf's readers disagree with the written store.
    """
    if slots < MIN_SLOTS:
        raise ValueError(f"slots must be at least {MIN_SLOTS}, got {slots}")
    if projects < MIN_PROJECTS:
        raise ValueError(f"projects must be at least {MIN_PROJECTS}, got {projects}")
    output_dir = output_dir.absolute()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"output directory is not empty: {output_dir}")
    writer = _StoreWriter(output_dir, seed)
    writer.base_catalogue()
    # Edge cases first: the bulk may use up a unit pool they need.
    writer.edge_cases()
    writer.bulk(slots - writer.regular_links())
    expected_projects = writer.projects(projects)
    # Last: the v0.1 part of a seed's store stays as it was.
    writer.file_families()
    manifest = StoreManifest(
        output_dir=output_dir,
        seed=seed,
        slots=slots,
        entries=tuple(writer.entries),
        projects=expected_projects,
    )
    verify_store(manifest)
    return manifest


def verify_store(manifest: StoreManifest) -> None:
    """Compare the store with Kartograf's readers (no network).

    Raises
    ------
    StoreFixtureError
        ``iter_store`` yields other entries or other sidecar values than
        expected, or ``open_project`` disagrees with a project.
    """
    root = manifest.root
    expected = {entry.row: entry for entry in manifest.entries}
    if len(expected) != len(manifest.entries):
        raise StoreFixtureError("generator expects the same entry twice")
    seen: set[Row] = set()
    problems: list[str] = []
    for found in iter_store(root):
        row = entry_row(found, root)
        if row in seen:
            problems.append(f"yielded twice: {row}")
        seen.add(row)
        wanted = expected.get(row)
        if wanted is None:
            problems.append(f"unexpected: {row}")
            continue
        problems.extend(_sidecar_differences(wanted, found))
    problems.extend(f"missing: {row}" for row in expected.keys() - seen)
    for project in manifest.projects:
        problems.extend(_project_differences(manifest.output_dir, project))
    if problems:
        shown = "\n".join(problems[:20])
        more = f"\n... and {len(problems) - 20} more" if len(problems) > 20 else ""
        raise StoreFixtureError(
            f"Kartograf reads the fixture differently:\n{shown}{more}"
        )


def _sidecar_differences(wanted: ExpectedEntry, found: StoreEntry) -> list[str]:
    meta = found.sidecar
    actual: tuple[object, ...] = (
        (meta.sha256, meta.dataset_key, meta.unit, meta.data_year)
        if meta is not None
        else (None, None, None, None)
    )
    target = (wanted.sha256, wanted.dataset_key, wanted.unit, wanted.data_year)
    if actual != target:
        return [f"sidecar of {wanted.path}: expected {target}, read {actual}"]
    return []


def _project_differences(output_dir: Path, project: ExpectedProject) -> list[str]:
    directory = output_dir / project.path
    try:
        opened = open_project(directory)
    except ValidationError as exc:
        if project.valid:
            return [f"project {project.name} rejected: {exc}"]
        return []
    if not project.valid:
        return [f"invalid project {project.name} accepted"]
    tasks = tuple(
        (task.name, task.command, tuple(pin.version for pin in task.files))
        for task in opened.tasks
    )
    wanted = tuple(
        (task.name, task.command, tuple(pin.version for pin in task.pins))
        for task in project.tasks
    )
    if tasks != wanted:
        return [f"project {project.name}: expected {wanted}, read {tasks}"]
    return []


# --- writer -------------------------------------------------------------------


@dataclass(frozen=True)
class _Profile:
    """Sidecar fields shared by the files of one family in one segment."""

    family: Family
    segment: str
    crs: str
    vertical_crs: str | None = None
    vertical_source: str | None = None
    resolution: str | None = None
    nodata: float | None = None
    dataset: str | None = None
    """Raw ``dataset`` of the sidecar; default: the segment's registry key."""


@dataclass(frozen=True)
class _Slot:
    segment: str
    hierarchy: str
    link: Path
    versions: Path
    full_sheet: Path | None
    unit: str


@dataclass(frozen=True)
class _Spec:
    """A version to write: label, data year and family-specific ``extra``."""

    label: str
    label_source: Literal["campaign", "edition", "downloaded"]
    data_year: int | None
    extra: dict[str, Any] = field(default_factory=dict)
    full_sheet: bool = False


@dataclass
class _Written:
    """A slot's versions as written, oldest first."""

    slot: _Slot
    profile: _Profile
    versions: list[ExpectedEntry]
    sidecars: list[dict[str, Any]]
    current: int


class _StoreWriter:
    """Writes the store and collects the expected entries."""

    def __init__(self, output_dir: Path, seed: int) -> None:
        self.output_dir = output_dir
        self.root = output_dir / STORE_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        self.rng = random.Random(seed)
        self.entries: list[ExpectedEntry] = []
        self.written: dict[str, list[_Written]] = {}
        self._nonce = seed * 10_000_000
        self._storages: dict[tuple[str | None, ...], FileStorage] = {}
        self._pools: dict[str, Iterator[str]] = {}
        self._bbox_names: set[str] = set()

    # --- helpers -------------------------------------------------------------

    def regular_links(self) -> int:
        """Count the regular slots (standard-path links) written so far."""
        return sum(
            entry.kind == "link" and entry.case == "regular" for entry in self.entries
        )

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def _next_nonce(self) -> int:
        self._nonce += 1
        return self._nonce

    def _downloaded_at(self) -> str:
        """Return a download moment in 2025-2026, after every data year."""
        day = date(2025, 1, 1) + timedelta(days=self.rng.randrange(650))
        seconds = self.rng.randrange(86_400)
        return (
            f"{day.isoformat()}T{seconds // 3600:02d}:{seconds // 60 % 60:02d}:"
            f"{seconds % 60:02d}.{self.rng.randrange(10**6):06d}+00:00"
        )

    def _storage(
        self,
        *,
        resolution: str | None = None,
        vertical_crs: str | None = None,
        product: str | None = None,
        subdir: str | None = None,
        format: str | None = None,
        suffix: str | None = None,
    ) -> FileStorage:
        key = (resolution, vertical_crs, product, subdir, format, suffix)
        storage = self._storages.get(key)
        if storage is None:
            storage = FileStorage(
                self.root,
                resolution=resolution,
                vertical_crs=vertical_crs,
                product=product,
                subdir=subdir,
                format=format,
                suffix=suffix,
            )
            self._storages[key] = storage
        return storage

    def _pool(
        self, name: str, make: Callable[[], list[str]], *, contiguous: bool = False
    ) -> str:
        """Return the next unused unit code of a pool.

        A pool is shuffled once by the seed; a ``contiguous`` one (sheets)
        is walked in order from a random start instead, like the areas
        users download, so neighbouring sheets share parent directories.
        """
        pool = self._pools.get(name)
        if pool is None:
            codes = make()
            if contiguous:
                start = self.rng.randrange(len(codes))
                codes = codes[start:] + codes[:start]
            else:
                self.rng.shuffle(codes)
            pool = iter(codes)
            self._pools[name] = pool
        try:
            return next(pool)
        except StopIteration:
            raise _UnitsUsedUp(f"no unused unit left in pool {name}") from None

    def _sheet_slot(
        self, storage: FileStorage, segment: str, sheet: str, ext: str
    ) -> _Slot:
        link = storage.get_path(sheet, ext)
        versions = storage.get_versions_root(sheet)
        return self._checked_slot(
            segment, link, versions, storage.get_full_sheet_path(sheet, ext), sheet
        )

    def _raw_slot(
        self,
        storage: FileStorage,
        segment: str,
        identifier: str,
        filename: str,
        *,
        system: str | None = None,
    ) -> _Slot:
        link = storage.get_raw_path(identifier, filename, system=system)
        versions = storage.get_raw_versions_root(identifier, system=system)
        return self._checked_slot(segment, link, versions, None, identifier)

    def _flat_slot(self, segment: str, kind: str, code: str, ext: str) -> _Slot:
        """Build ``<segment>/<kind>/<code><ext>`` (ARCH 3.3 rules 8-9).

        Kartograf 0.8.0 has no public path builder for unit slots.
        """
        base = self.root.joinpath(*segment.split("/"))
        return _Slot(
            segment=segment,
            hierarchy=kind,
            link=base / kind / f"{code}{ext}",
            versions=base / "versions" / kind,
            full_sheet=None,
            unit=code,
        )

    def _checked_slot(
        self,
        segment: str,
        link: Path,
        versions: Path,
        full_sheet: Path | None,
        unit: str,
    ) -> _Slot:
        base = self.root.joinpath(*segment.split("/"))
        if not versions.is_relative_to(base / "versions"):
            raise StoreFixtureError(f"Kartograf put {versions} outside {segment}")
        hierarchy = versions.relative_to(base / "versions").as_posix()
        return _Slot(segment, hierarchy, link, versions, full_sheet, unit)

    def _sidecar(
        self,
        profile: _Profile,
        *,
        request: dict[str, Any],
        extra: dict[str, Any],
        sha256: str | None,
        size_bytes: int | None,
    ) -> dict[str, Any]:
        info = describe_segment(profile.segment)
        country = info.country
        return {
            "schema": "kartograf-meta/1",
            "dataset": profile.dataset or info.dataset_key,
            "country": country,
            "product": info.product,
            "provider": _PROVIDERS.get(country or "", "fixture"),
            "horizontal_crs": profile.crs,
            "vertical_crs": profile.vertical_crs,
            "vertical_source": profile.vertical_source,
            "resolution": profile.resolution,
            "nodata": profile.nodata,
            "request": request,
            "license": dict(_LICENSE),
            "downloaded_at": self._downloaded_at(),
            "kartograf_version": kartograf.__version__,
            "transform": None,
            "extra": extra,
            "sha256": sha256,
            "size_bytes": size_bytes,
        }

    def _dataset_key(self, profile: _Profile) -> str | None:
        """Return the registry key Kartograf reads from ``dataset``."""
        if profile.dataset == DEV_DATASET:
            return "pl.gugik.buildings"
        if profile.dataset is not None:
            return profile.dataset
        key: str | None = describe_segment(profile.segment).dataset_key
        return key

    def _write_slot(
        self,
        slot: _Slot,
        profile: _Profile,
        specs: Sequence[_Spec],
        *,
        body: Callable[[int], bytes],
        request: dict[str, Any],
        unit: str,
        link_to: int | None = None,
        link_names: int | None = None,
        full_sheet_to: int | None = None,
        case: Case = "regular",
    ) -> _Written:
        """Versions (oldest first), the standard link and ``full_sheet/``.

        The standard link is version ``link_to`` (default: the newest) and
        its sidecar names version ``link_names`` (default: the same one).
        Identical content of another label is linked, not copied
        (Kartograf's ``relabeled`` versions).
        """
        linked = len(specs) - 1 if link_to is None else link_to
        current = linked if link_names is None else link_names
        written = _Written(slot, profile, [], [], current)
        by_sha: dict[str, Path] = {}
        for index, spec in enumerate(specs):
            data = body(self._next_nonce())
            sha256 = hashlib.sha256(data).hexdigest()
            directory = slot.versions / f"{spec.label}_{sha256[:8]}"
            directory.mkdir(parents=True)
            path = directory / slot.link.name
            if sha256 in by_sha:
                os.link(by_sha[sha256], path)
            else:
                path.write_bytes(data)
                by_sha[sha256] = path
            extra = {
                "version": {"label": spec.label, "label_source": spec.label_source},
                **spec.extra,
            }
            meta = self._sidecar(
                profile,
                request=request,
                extra=extra,
                sha256=sha256,
                size_bytes=len(data),
            )
            _write_json(_sidecar_path(path), meta)
            entry = ExpectedEntry(
                kind="version",
                segment=slot.segment,
                hierarchy=slot.hierarchy,
                path=self._rel(path),
                version_path=self._rel(path),
                label=spec.label,
                sha8=sha256[:8],
                family=profile.family,
                case=case,
                sha256=sha256,
                size_bytes=len(data),
                dataset_key=self._dataset_key(profile),
                unit=unit,
                data_year=spec.data_year,
                current=index == current,
            )
            written.versions.append(entry)
            written.sidecars.append(meta)
            self.entries.append(entry)
        self._link("link", slot.link, written, linked, case, sidecar_index=current)
        if full_sheet_to is not None:
            if slot.full_sheet is None:
                raise StoreFixtureError(f"{slot.segment} has no full_sheet/ links")
            self._link("full_sheet", slot.full_sheet, written, full_sheet_to, case)
        self.written.setdefault(slot.segment, []).append(written)
        return written

    def _link(
        self,
        kind: EntryKind,
        link: Path,
        written: _Written,
        index: int,
        case: Case,
        *,
        sidecar_index: int | None = None,
    ) -> ExpectedEntry:
        """Hardlink ``link`` to version ``index`` and write its sidecar.

        The sidecar is the version sidecar + ``extra.link``/``link_target``
        naming version ``sidecar_index`` (default: the linked one).
        """
        named = index if sidecar_index is None else sidecar_index
        version = written.versions[index]
        target = written.versions[named]
        target_path = self.root / target.path
        link.parent.mkdir(parents=True, exist_ok=True)
        os.link(self.root / version.path, link)
        meta = dict(written.sidecars[named])
        meta["extra"] = {
            **meta["extra"],
            "link": "hardlink",
            "link_target": Path(os.path.relpath(target_path, link.parent)).as_posix(),
        }
        _write_json(_sidecar_path(link), meta)
        entry = ExpectedEntry(
            kind=kind,
            segment=target.segment,
            hierarchy=target.hierarchy,
            path=self._rel(link),
            version_path=target.path,
            label=target.label,
            sha8=target.sha8,
            family=target.family,
            case=case,
            sha256=target.sha256,
            size_bytes=target.size_bytes,
            dataset_key=target.dataset_key,
            unit=target.unit,
            data_year=target.data_year,
        )
        self.entries.append(entry)
        return entry

    def _problem(
        self,
        problem: ProblemCode,
        segment: str,
        path: Path,
        *,
        hierarchy: str = "",
        label: str | None = None,
        sha8: str | None = None,
    ) -> None:
        self.entries.append(
            ExpectedEntry(
                kind="problem",
                segment=segment,
                hierarchy=hierarchy,
                path=self._rel(path),
                label=label,
                sha8=sha8,
                problem=problem,
                case=problem,
            )
        )

    # --- version labels ------------------------------------------------------

    def _versions(self) -> int:
        return self.rng.choices(_VERSION_COUNTS, _VERSION_WEIGHTS)[0]

    def _years(self, count: int, first: int = 2008, last: int = 2024) -> list[int]:
        return sorted(self.rng.sample(range(first, last + 1), count))

    def _date(self, year: int) -> str:
        day = date(year, 1, 1) + timedelta(days=self.rng.randrange(60, 300))
        return day.isoformat()

    def _campaigns(
        self, sheet: str, count: int, full: Sequence[bool] = ()
    ) -> list[_Spec]:
        """PL sheet flights: ``<acquisition date>_<id>`` (ADR-036)."""
        specs = []
        for index, year in enumerate(self._years(count)):
            day = self._date(year)
            flight = str(self.rng.randrange(10_000, 99_999))
            work = f"GK.6640.{flight}.{year}"
            full_sheet = full[index] if index < len(full) else False
            specs.append(
                _Spec(
                    label=f"{day}_{flight}",
                    label_source="campaign",
                    data_year=year,
                    full_sheet=full_sheet,
                    extra={
                        "campaign": {
                            "date": day,
                            "survey_work_id": work,
                            "full_sheet": full_sheet,
                        },
                        "source": {
                            "sheet": sheet,
                            "acquisition_date": day,
                            "acquisition_year": year,
                            "full_sheet": full_sheet,
                            "survey_work_id": work,
                        },
                    },
                )
            )
        return specs

    def _editions(self, count: int, first: int = 2018) -> list[_Spec]:
        return [
            _Spec(label=str(year), label_source="edition", data_year=year)
            for year in self._years(count, first, 2025)
        ]

    def _downloads(self, count: int) -> list[_Spec]:
        """Labels by download date: no data year (never from the download)."""
        days = sorted(
            self.rng.sample(range(600), count),
        )
        return [
            _Spec(
                label=(date(2025, 1, 1) + timedelta(days=day)).isoformat(),
                label_source="downloaded",
                data_year=None,
            )
            for day in days
        ]

    # --- families ------------------------------------------------------------

    def _pl_sheet(self, segment: str) -> str:
        return self._pool(segment, _pl1992_sheets, contiguous=True)

    def asc_sheet(
        self,
        segment: str,
        versions: int,
        *,
        full: Sequence[bool] = (),
        full_sheet_to: int | None = None,
        sheet: str | None = None,
        case: Case = "regular",
    ) -> _Written:
        """ASC NMT/NMPT sheet (PL-1992 or PL-2000) with campaign versions."""
        product = segment.split("/", 1)[0]
        vertical = "KRON86" if segment.endswith("kron86") else "EVRF2007"
        storage = self._storage(
            resolution="1m",
            vertical_crs=vertical,
            product=None if product == "nmt" else product,
        )
        code = sheet or self._pl_sheet(segment)
        slot = self._sheet_slot(storage, segment, code, ".asc")
        if not slot.link.is_relative_to(self.root / segment):
            raise StoreFixtureError(f"FileStorage put {code} in {slot.link}")
        parsed = SheetParser(code).get_bbox()
        bounds = (parsed.min_x, parsed.min_y, parsed.max_x, parsed.max_y)
        profile = _Profile(
            "asc_sheet",
            segment,
            parsed.crs,
            vertical_crs="EPSG:9650" if vertical == "KRON86" else "EPSG:9651",
            vertical_source="native",
            resolution="1m",
            nodata=float(store_files.NODATA),
        )
        return self._write_slot(
            slot,
            profile,
            self._campaigns(code, versions, full),
            body=lambda nonce: store_files.asc_grid(bounds, nonce),
            request={"sheet": code},
            unit=code,
            full_sheet_to=full_sheet_to,
            case=case,
        )

    def tif_sheet(
        self,
        versions: int,
        *,
        full: Sequence[bool] = (),
        full_sheet_to: int | None = None,
    ) -> _Written:
        """Orthophoto GeoTIFF sheet (PL-1992) with campaign versions."""
        storage = self._storage(product="orto")
        code = self._pl_sheet(ORTO)
        slot = self._sheet_slot(storage, ORTO, code, ".tif")
        parsed = SheetParser(code).get_bbox()
        bounds = (parsed.min_x, parsed.min_y, parsed.max_x, parsed.max_y)
        profile = _Profile("tif_sheet", ORTO, parsed.crs)
        return self._write_slot(
            slot,
            profile,
            self._campaigns(code, versions, full),
            body=lambda nonce: store_files.geotiff(bounds, 2180, nonce),
            request={"sheet": code},
            unit=code,
            full_sheet_to=full_sheet_to,
        )

    def _bbox_code(self, segment: str, crs: str) -> Bounds:
        """Draw a new square bbox of ``segment`` in ``crs``, inside its country."""
        extent = _extent(crs)
        while True:
            min_x = self.rng.randrange(extent[0], extent[2]) // 100 * 100
            min_y = self.rng.randrange(extent[1], extent[3]) // 100 * 100
            width = self.rng.choice((500, 1000, 1500, 2000))
            bounds = (
                float(min_x),
                float(min_y),
                float(min_x + width),
                float(min_y + width),
            )
            name = f"{segment}/{_coords(bounds)}"
            if name not in self._bbox_names and _inside(BBox(*bounds, crs)):
                self._bbox_names.add(name)
                return bounds

    def tif_bbox(self, segment: str, versions: int) -> _Written:
        """WCS cutout ``bbox/<coords>.tif`` labelled by download date."""
        czech = segment.startswith("nmt/cz_")
        crs = "EPSG:5514" if czech else "EPSG:2180"
        bounds = self._bbox_code(segment, crs)
        code = _coords(bounds)
        slot = self._flat_slot(segment, "bbox", code, ".tif")
        profile = _Profile(
            "tif_bbox",
            segment,
            crs,
            vertical_crs="EPSG:8357" if czech else "EPSG:9651",
            vertical_source="server" if czech else "native",
            resolution="2m" if czech else "1m",
            nodata=float(store_files.NODATA),
        )
        epsg = int(crs.split(":")[1])
        return self._write_slot(
            slot,
            profile,
            self._downloads(versions),
            body=lambda nonce: store_files.geotiff(bounds, epsg, nonce),
            request={"bbox": list(bounds), "bbox_crs": crs},
            unit=code,
        )

    def hsg_bbox(self, versions: int) -> _Written:
        """Write a derived HSG raster ``bbox/<coords>.tif`` (SoilGrids)."""
        bounds = self._bbox_code(HSG, "EPSG:2180")
        code = _coords(bounds)
        slot = self._flat_slot(HSG, "bbox", code, ".tif")
        profile = _Profile("hsg_bbox", HSG, "EPSG:2180", nodata=0.0)
        specs = [
            _Spec(label=f"2.{minor}", label_source="edition", data_year=None)
            for minor in range(versions)
        ]
        return self._write_slot(
            slot,
            profile,
            specs,
            body=lambda nonce: store_files.geotiff(bounds, 2180, nonce, nodata=0),
            request={"bbox": list(bounds), "bbox_crs": "EPSG:2180"},
            unit=code,
        )

    def laz_tile(
        self, versions: int, *, compressed: bool = False, case: Case = "regular"
    ) -> _Written:
        """PL point-cloud tile named after its source file (D26 labels).

        ``compressed``: a real LASzip file (``store_files.laz_points``)
        instead of the uncompressed few-point LAS of the bulk.
        """
        sheet = self._pl_sheet(LAZ)
        quarter = self.rng.randrange(1, 5)
        tile = f"{sheet}-{quarter}"
        flight = self.rng.randrange(70_000, 99_999)
        storage = self._storage(vertical_crs="EVRF2007", product="laz")
        slot = self._raw_slot(storage, LAZ, tile, f"{flight}_{tile}.laz", system="1992")
        parsed = SheetParser(sheet).get_bbox()
        half_x = (parsed.max_x - parsed.min_x) / 2
        half_y = (parsed.max_y - parsed.min_y) / 2
        west = parsed.min_x + half_x * ((quarter - 1) % 2)
        south = parsed.min_y + half_y * (1 - (quarter - 1) // 2)
        bounds = (west, south, west + half_x, south + half_y)
        area = [round(value) for value in bounds]
        specs = []
        for year in self._years(versions):
            day = self._date(year)
            work = f"GK.6640.{self.rng.randrange(1000, 9999)}.{year}"
            specs.append(
                _Spec(
                    label=f"{day}_{work.replace('.', '-')}",
                    label_source="campaign",
                    data_year=year,
                    extra={
                        "tile_sheet": tile,
                        "year": year,
                        "nominal_density": 12,
                        "url": f"https://example.invalid/laz/{flight}_{tile}.laz",
                        "acquisition_date": day,
                        "full_sheet": True,
                    },
                )
            )
        profile = _Profile(
            "laz_compressed" if compressed else "laz_tile",
            LAZ,
            "EPSG:2180",
            vertical_crs="EPSG:9651",
            vertical_source="native",
        )
        return self._write_slot(
            slot,
            profile,
            specs,
            body=(
                (lambda nonce: store_files.laz_points(bounds, nonce))
                if compressed
                else (lambda nonce: store_files.las_points(bounds, nonce))
            ),
            request={"bbox": area, "bbox_crs": "EPSG:2180"},
            unit=tile,
            case=case,
        )

    def cz_orto(self, versions: int) -> tuple[_Written, _Written]:
        """Write a CZ SM5 orthophoto: a JPEG slot and its ``.jgw`` slot.

        One edition per version; the world file does not change between
        editions, so its later versions are relabelled links to one file.
        """
        code = self._pool("sm5", _sm5_sheets)
        storage = self._storage(subdir=CZ_ORTO)
        bounds = self._sm5_bounds()
        specs = []
        for year in self._years(versions, 2012, 2025):
            updated = self._date(min(year + 1, 2026))
            label = f"{year}_{updated}"
            specs.append(
                _Spec(
                    label=label,
                    label_source="edition",
                    data_year=year,
                    extra={
                        "source": {
                            "edition": label,
                            "year": year,
                            "updated": updated,
                            "url": f"https://example.invalid/orto/{code}.zip",
                        }
                    },
                )
            )
        image = self._write_slot(
            self._raw_slot(storage, CZ_ORTO, code, f"{code}.jpg"),
            _Profile("jpg_sheet", CZ_ORTO, "EPSG:5514"),
            specs,
            body=store_files.jpeg,
            request={"sheet": code},
            unit=code,
        )
        world = self._write_slot(
            self._raw_slot(storage, CZ_ORTO, code, f"{code}.jgw"),
            _Profile("jgw_sheet", CZ_ORTO, "EPSG:5514"),
            specs,
            body=lambda _nonce: store_files.world_file(bounds),
            request={"sheet": code},
            unit=code,
        )
        return image, world

    def _sm5_bounds(self) -> Bounds:
        """Draw the 2500 x 2000 m S-JTSK extent of an SM5 sheet inside Czechia."""
        extent = _extent("EPSG:5514")
        while True:
            min_x = self.rng.randrange(extent[0], extent[2] - 2500) // 50 * 50
            min_y = self.rng.randrange(extent[1], extent[3] - 2000) // 50 * 50
            bounds = (
                float(min_x),
                float(min_y),
                float(min_x + 2500),
                float(min_y + 2000),
            )
            if _inside(BBox(*bounds, "EPSG:5514")):
                return bounds

    def _teryt(self, segments: Sequence[str]) -> tuple[str, str]:
        for segment in segments:
            try:
                return segment, self._pool(segment, _teryt_codes)
            except _UnitsUsedUp:
                continue
        raise _UnitsUsedUp(f"no unused TERYT code left in {', '.join(segments)}")

    def _teryt_bounds(self) -> Bounds:
        """Draw the EPSG:2180 extent of a powiat package inside Poland."""
        extent = _extent("EPSG:2180")
        while True:
            min_x = self.rng.randrange(extent[0], extent[2] - 40_000)
            min_y = self.rng.randrange(extent[1], extent[3] - 40_000)
            width = self.rng.randrange(15_000, 40_000)
            bounds = (
                float(min_x),
                float(min_y),
                float(min_x + width),
                float(min_y + width),
            )
            if _inside(BBox(*bounds, "EPSG:2180")):
                return bounds

    def gpkg_teryt(
        self, versions: int, segments: Sequence[str] = (BDOT_GPKG, EGIB_GPKG)
    ) -> _Written:
        """GeoPackage of a powiat (``teryt/<code>.gpkg``) by edition."""
        segment, code = self._teryt(segments)
        bounds = self._teryt_bounds()
        return self._write_slot(
            self._flat_slot(segment, "teryt", code, ".gpkg"),
            _Profile("gpkg_teryt", segment, "EPSG:2180"),
            self._editions(versions),
            body=lambda nonce: store_files.geopackage(bounds, 2180, nonce),
            request={"teryt": code},
            unit=code,
        )

    def zip_teryt(
        self,
        versions: int,
        segments: Sequence[str] = (BUILDINGS, BDOT_SHP, PRG_GML),
        *,
        dataset: str | None = None,
        case: Case = "regular",
    ) -> _Written:
        """ZIP package of a TERYT unit 1:1 (``teryt/<code>.zip``)."""
        segment, code = self._teryt(segments)
        return self._write_slot(
            self._flat_slot(segment, "teryt", code, ".zip"),
            _Profile("zip_teryt", segment, "EPSG:2180", dataset=dataset),
            self._editions(versions),
            body=lambda nonce: store_files.zip_archive(f"{code}.gml", nonce),
            request={"teryt": code},
            unit=code,
            case=case,
        )

    def zip_country(self) -> _Written:
        """National file ``country/pl.zip`` (whole country, no outline)."""
        day = self._date(2025)
        return self._write_slot(
            self._flat_slot(PRG_SHP, "country", "pl", ".zip"),
            _Profile("zip_country", PRG_SHP, "EPSG:2180"),
            [_Spec(label=day, label_source="edition", data_year=2025)],
            body=lambda nonce: store_files.zip_archive("PRG_jednostki.shp", nonce),
            request={"whole_country": True},
            unit="pl",
        )

    def zip_ku(self) -> _Written:
        """CZ cadastral map package of a KU (``ku/<code>.zip``)."""
        code = str(self.rng.randrange(600_000, 800_000))
        return self._write_slot(
            self._flat_slot(CZ_CADASTRE, "ku", code, ".zip"),
            _Profile("zip_ku", CZ_CADASTRE, "EPSG:5514"),
            self._downloads(1),
            body=lambda nonce: store_files.zip_archive(f"{code}.shp", nonce),
            request={"ku": code},
            unit=code,
        )

    # --- store content -------------------------------------------------------

    def base_catalogue(self) -> None:
        """``MIN_SLOTS`` regular slots: every family and link shape once."""
        # Three flights; the standard link takes the newest, full_sheet/ the
        # newest declared-full one (a different version).
        self.asc_sheet(NMT, 3, full=(False, True, False), full_sheet_to=1)
        # One full flight: both links name the same version (one size).
        self.asc_sheet(NMT, 1, full=(True,), full_sheet_to=0)
        # Two flights: projects pin the older one.
        self.asc_sheet(NMT, 2)
        self.asc_sheet(NMT_KRON86, 1)
        self.asc_sheet(NMT_2000, 1, sheet="6.179.12.20")
        self.asc_sheet(NMPT, 2)
        self.tif_sheet(2)
        self.tif_bbox(NMT, 2)
        self.tif_bbox(CZ_NMT, 1)
        self.cz_orto(2)
        self.gpkg_teryt(2, (BDOT_GPKG,))
        self.zip_teryt(1, (BUILDINGS,))
        self.zip_country()
        self.zip_ku()
        self.laz_tile(2)
        self.hsg_bbox(1)

    def bulk(self, count: int) -> None:
        """``count`` more regular slots in the SPEC 4.5 mix.

        A TERYT segment holds one package per powiat, as in a real store:
        once every segment of a TERYT family has a package of every powiat,
        the other families share its weight.
        """
        mix = dict(_BULK_WEIGHTS)
        remaining = count
        while remaining > 0:
            name = self.rng.choices(list(mix), list(mix.values()))[0]
            if name == "cz_orto" and remaining < 2:
                name = "nmt"
            versions = self._versions()
            if name in ("nmt", "nmpt", "kron86", "orto"):
                full, full_sheet_to = self._full_flags(versions)
                if name == "orto":
                    self.tif_sheet(versions, full=full, full_sheet_to=full_sheet_to)
                else:
                    segment = {"nmt": NMT, "nmpt": NMPT, "kron86": NMT_KRON86}[name]
                    self.asc_sheet(
                        segment, versions, full=full, full_sheet_to=full_sheet_to
                    )
            elif name == "laz":
                self.laz_tile(versions)
            elif name == "tif_bbox":
                self.tif_bbox(NMT if self.rng.random() < 0.85 else CZ_NMT, versions)
            elif name in ("gpkg_teryt", "zip_teryt"):
                try:
                    if name == "gpkg_teryt":
                        self.gpkg_teryt(versions)
                    else:
                        self.zip_teryt(versions)
                except _UnitsUsedUp:
                    del mix[name]
                    continue
            elif name == "cz_orto":
                self.cz_orto(versions)
                remaining -= 1
            else:
                self.hsg_bbox(versions)
            remaining -= 1

    def _full_flags(self, versions: int) -> tuple[tuple[bool, ...], int | None]:
        if self.rng.random() >= _FULL_SHEET_SHARE:
            return (), None
        full_index = self.rng.randrange(versions)
        flags = tuple(index == full_index for index in range(versions))
        return flags, full_index

    def edge_cases(self) -> None:
        """Deliberate oddities and problems on top of the regular slots."""
        # A 0.8.0-dev dataset key in a current segment: read under its
        # current key.
        self.zip_teryt(1, (BUILDINGS,), dataset=DEV_DATASET, case="dev_dataset_key")
        self._dev_segment()
        self._pre_adr031()
        self._link_mismatch()
        self._broken_versions()
        self._unknown_segment()
        self._legacy_and_staging()

    def _dev_segment(self) -> None:
        """Write a 0.8.0-dev segment (true orthophoto): unknown, listed."""
        sheet = self._pl_sheet(NMT)
        storage = self._storage(product="orto")
        probe = self._sheet_slot(storage, ORTO, sheet, ".tif")
        base = self.root.joinpath(*DEV_SEGMENT.split("/"))
        slot = _Slot(
            DEV_SEGMENT,
            probe.hierarchy,
            base / probe.link.relative_to(self.root / ORTO),
            base / "versions" / probe.hierarchy,
            None,
            sheet,
        )
        parsed = SheetParser(sheet).get_bbox()
        bounds = (parsed.min_x, parsed.min_y, parsed.max_x, parsed.max_y)
        self._problem("unknown_segment", DEV_SEGMENT, base)
        self._write_slot(
            slot,
            _Profile("tif_sheet", DEV_SEGMENT, "EPSG:2180", dataset="pl.gugik.orto"),
            self._campaigns(sheet, 1),
            body=lambda nonce: store_files.geotiff(bounds, 2180, nonce),
            request={"sheet": sheet},
            unit=sheet,
            case="dev_segment",
        )

    def _pre_adr031(self) -> None:
        """Write a 0.6.x file at the standard path: Polish keys, no version."""
        sheet = self._pl_sheet(NMT)
        storage = self._storage(resolution="1m", vertical_crs="EVRF2007")
        slot = self._sheet_slot(storage, NMT, sheet, ".asc")
        parsed = SheetParser(sheet).get_bbox()
        bounds = (parsed.min_x, parsed.min_y, parsed.max_x, parsed.max_y)
        slot.link.parent.mkdir(parents=True, exist_ok=True)
        slot.link.write_bytes(store_files.asc_grid(bounds, self._next_nonce()))
        _write_json(
            _sidecar_path(slot.link),
            {
                "schema": "kartograf-meta/1",
                "dataset": "pl.gugik.nmt_1m",
                "country": "PL",
                "product": "nmt",
                "horizontal_crs": "EPSG:2180",
                "request": {"godlo": sheet},
                "downloaded_at": "2024-03-01T12:00:00+00:00",
                "kartograf_version": "0.6.2",
                "extra": {
                    "source": {
                        "godlo": sheet,
                        "aktualnosc": "2019-06-01",
                        "aktualnosc_rok": 2019,
                        "numer_zgloszenia": "GK.6640.1.2019",
                    }
                },
            },
        )
        self.entries.append(
            ExpectedEntry(
                kind="link",
                segment=NMT,
                hierarchy=slot.hierarchy,
                path=self._rel(slot.link),
                family="asc_sheet",
                case="pre_adr031",
                dataset_key="pl.gugik.nmt_1m",
                unit=sheet,
                data_year=2019,
            )
        )

    def _link_mismatch(self) -> None:
        """Link the older version under a sidecar naming the newer one.

        This is the disagreement ``link_check`` must catch.
        """
        sheet = self._pl_sheet(NMT)
        storage = self._storage(resolution="1m", vertical_crs="EVRF2007")
        slot = self._sheet_slot(storage, NMT, sheet, ".asc")
        parsed = SheetParser(sheet).get_bbox()
        bounds = (parsed.min_x, parsed.min_y, parsed.max_x, parsed.max_y)
        self._write_slot(
            slot,
            _Profile(
                "asc_sheet",
                NMT,
                "EPSG:2180",
                vertical_crs="EPSG:9651",
                vertical_source="native",
                resolution="1m",
                nodata=float(store_files.NODATA),
            ),
            self._campaigns(sheet, 2),
            body=lambda nonce: store_files.asc_grid(bounds, nonce),
            request={"sheet": sheet},
            unit=sheet,
            link_to=0,
            link_names=1,
            case="link_mismatch",
        )

    def _broken_versions(self) -> None:
        """Write a slot with a version without sidecar and one unreadable.

        Also a standard-path file without any sidecar.
        """
        # Its healthy version and link belong to the case, not to ``slots``.
        written = self.asc_sheet(NMT, 1, case="missing_sidecar")
        slot = written.slot
        parsed = SheetParser(slot.unit).get_bbox()
        bounds = (parsed.min_x, parsed.min_y, parsed.max_x, parsed.max_y)
        for problem, label in (
            ("missing_sidecar", "2025-05-10_90001"),
            ("invalid_sidecar", "2025-06-10_90002"),
        ):
            data = store_files.asc_grid(bounds, self._next_nonce())
            sha8 = hashlib.sha256(data).hexdigest()[:8]
            path = slot.versions / f"{label}_{sha8}" / slot.link.name
            path.parent.mkdir(parents=True)
            path.write_bytes(data)
            if problem == "invalid_sidecar":
                _sidecar_path(path).write_text('{"schema": "kartograf-meta/1",')
            self._problem(
                cast(ProblemCode, problem),
                NMT,
                path,
                hierarchy=slot.hierarchy,
                label=label,
                sha8=sha8,
            )
        sheet = self._pl_sheet(NMT)
        storage = self._storage(resolution="1m", vertical_crs="EVRF2007")
        lone = self._sheet_slot(storage, NMT, sheet, ".asc")
        parsed = SheetParser(sheet).get_bbox()
        bounds = (parsed.min_x, parsed.min_y, parsed.max_x, parsed.max_y)
        lone.link.parent.mkdir(parents=True, exist_ok=True)
        lone.link.write_bytes(store_files.asc_grid(bounds, self._next_nonce()))
        self._problem("missing_sidecar", NMT, lone.link, hierarchy=lone.hierarchy)

    def _unknown_segment(self) -> None:
        """Write a product directory Kartograf's registry does not know."""
        base = self.root.joinpath(*UNKNOWN_SEGMENT.split("/"))
        link = base / "teryt" / "12.zip"
        link.parent.mkdir(parents=True)
        data = store_files.zip_archive("12.gml", self._next_nonce())
        link.write_bytes(data)
        sha256 = hashlib.sha256(data).hexdigest()
        _write_json(
            _sidecar_path(link),
            {
                "schema": "kartograf-meta/1",
                "dataset": "pl.experimental.product",
                "country": "PL",
                "product": "newproduct",
                "horizontal_crs": "EPSG:2180",
                "request": {"teryt": "12"},
                "downloaded_at": self._downloaded_at(),
                "kartograf_version": "0.9.0.dev0",
                "extra": {},
                "sha256": sha256,
                "size_bytes": len(data),
            },
        )
        self._problem("unknown_segment", UNKNOWN_SEGMENT, base)
        self.entries.append(
            ExpectedEntry(
                kind="link",
                segment=UNKNOWN_SEGMENT,
                hierarchy="teryt",
                path=self._rel(link),
                sha8=sha256[:8],
                family="zip_teryt",
                case="unknown_segment",
                sha256=sha256,
                unit="12",
            )
        )

    def _legacy_and_staging(self) -> None:
        """0.7.x ``kampanie/`` and a staging directory older than 24 h."""
        base = self.root.joinpath(*NMT.split("/"))
        sheet = self._pl_sheet(NMT)
        legacy = base / "kampanie" / "2020-05-01_123" / f"{sheet}.asc"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"legacy campaign file\n")
        self._problem("legacy_campaigns", NMT, base / "kampanie")
        staging = base / "versions" / ".incoming" / "fixture-host_4242_0a1b2c3d"
        staging.mkdir(parents=True)
        partial = staging / f"{sheet}.asc"
        partial.write_bytes(b"interrupted download\n")
        for path in (partial, staging):
            os.utime(path, (STALE_MTIME, STALE_MTIME))
        self._problem("stale_incoming", NMT, staging)

    # --- plan v0.2 file families ----------------------------------------------

    def file_families(self) -> None:
        """Write the plan v0.2 file families (decision 5), on top of ``slots``.

        Written after the projects, so the v0.1 part of a seed's store does
        not change. Every slot has the case ``file_family``, except the
        standard-path file with a sidecar without ``sha256`` (``no_sha256``)
        and the NMT sheet in ASC and ASCII-NMT (``two_formats``: one
        product, CRS, height system and resolution in two segments).
        """
        self._corine_preview()
        self._corine_classes()
        self._bdot10k_map(
            BDOT_MAP_TIFF,
            "tif_map",
            ".tif",
            lambda bounds, nonce: store_files.geotiff_rgba_strips(bounds, 2180, nonce),
        )
        self._bdot10k_map(
            BDOT_MAP_PDF,
            "pdf_map",
            ".pdf",
            lambda _bounds, nonce: store_files.pdf_document(f"BDOT10k {nonce}"),
        )
        self._oblique_orto()
        self._soilgrids()
        self._lod2_package()
        self.laz_tile(1, compressed=True, case="file_family")
        self._gpkg_layers()
        self._no_sha256()
        self._two_formats()

    def _sheet_bounds(self, sheet: str) -> Bounds:
        parsed = SheetParser(sheet).get_bbox()
        return (parsed.min_x, parsed.min_y, parsed.max_x, parsed.max_y)

    def _corine_preview(self) -> None:
        """CORINE WMS preview of a PL-1992 bbox: a PNG without georeference.

        By bbox, not by sheet: Kartograf 0.8.0 computes a sheet outline only
        for PL sidecars, and CORINE is ``EU`` - a preview of a sheet would
        have no outline at all (the request bbox gives one).
        """
        bounds = self._bbox_code(CORINE_PREVIEW, "EPSG:2180")
        code = _coords(bounds)
        specs = [
            _Spec(
                spec.label,
                spec.label_source,
                spec.data_year,
                extra={"fallback": "wms_png", "note": "podglad WMS, nie dane"},
            )
            for spec in self._downloads(1)
        ]
        self._write_slot(
            self._flat_slot(CORINE_PREVIEW, "bbox", code, ".png"),
            _Profile("png_preview", CORINE_PREVIEW, "EPSG:3857"),
            specs,
            body=store_files.png_image,
            request={"bbox": list(bounds), "bbox_crs": "EPSG:2180"},
            unit=code,
            case="file_family",
        )

    def _corine_classes(self) -> None:
        """CORINE (CLMS) class raster in EPSG:3035 with a colour table."""
        sheet = "-".join(self._pl_sheet(CORINE).split("-")[:4])
        bounds = store_files.reprojected_bounds(self._sheet_bounds(sheet), 2180, 3035)
        self._write_slot(
            self._sheet_slot(self._storage(subdir=CORINE), CORINE, sheet, ".tif"),
            _Profile(
                "tif_classes",
                CORINE,
                "EPSG:3035",
                resolution="100m",
                nodata=float(store_files.CLC_NODATA),
            ),
            [_Spec(label="2018", label_source="edition", data_year=2018)],
            body=lambda nonce: store_files.geotiff_classes(bounds, 3035, nonce),
            request={"sheet": sheet},
            unit=sheet,
            case="file_family",
        )

    def _bdot10k_map(
        self,
        segment: str,
        family: Family,
        ext: str,
        body: Callable[[Bounds, int], bytes],
    ) -> None:
        """BDOT10k topographic map of a 1:10 000 sheet (TIFF or PDF)."""
        sheet = self._pl_sheet(segment).rsplit("-", 1)[0]  # 1:10 000
        bounds = self._sheet_bounds(sheet)
        self._write_slot(
            self._sheet_slot(self._storage(subdir=segment), segment, sheet, ext),
            _Profile(family, segment, "EPSG:2180"),
            self._editions(1),
            body=lambda nonce: body(bounds, nonce),
            request={"sheet": sheet},
            unit=sheet,
            case="file_family",
        )

    def _oblique_orto(self) -> None:
        """Oblique orthophoto (north view) of a PL-2000 zone 6 sheet."""
        bounds = self._sheet_bounds(OBLIQUE_SHEET)
        storage = self._storage(subdir=OBLIQUE, suffix="_n")
        self._write_slot(
            self._sheet_slot(storage, OBLIQUE, OBLIQUE_SHEET, ".tif"),
            _Profile("tif_oblique", OBLIQUE, "EPSG:2177"),
            self._editions(1),
            body=lambda nonce: store_files.geotiff_tiled_overviews(bounds, 2177, nonce),
            request={"sheet": OBLIQUE_SHEET, "direction": "n"},
            unit=OBLIQUE_SHEET,
            case="file_family",
        )

    def _soilgrids(self) -> None:
        """SoilGrids layer in EPSG:4326 of a PL-1992 bbox (WCS cutout)."""
        bounds = self._bbox_code(SOILGRIDS, "EPSG:2180")
        code = _coords(bounds)
        degrees = store_files.reprojected_bounds(bounds, 2180, 4326)
        self._write_slot(
            self._flat_slot(SOILGRIDS, "bbox", code, ".tif"),
            _Profile(
                "tif_wgs84",
                SOILGRIDS,
                "EPSG:4326",
                nodata=float(store_files.SOIL_NODATA),
            ),
            [_Spec(label="2.0", label_source="edition", data_year=None)],
            body=lambda nonce: store_files.geotiff_wgs84(degrees, nonce),
            request={"bbox": list(bounds), "bbox_crs": "EPSG:2180"},
            unit=code,
            case="file_family",
        )

    def _lod2_package(self) -> None:
        """LoD2 buildings of a powiat: ZIP with CityGML and PDF members."""
        segment, code = self._teryt((BUILDINGS_LOD2,))
        bounds = self._teryt_bounds()
        self._write_slot(
            self._flat_slot(segment, "teryt", code, ".zip"),
            _Profile("zip_citygml", segment, "EPSG:2180", vertical_crs="EPSG:9650"),
            [_Spec(label="2017", label_source="edition", data_year=2017)],
            body=lambda nonce: store_files.zip_members(
                [
                    (
                        f"{code}/{code}_lod2.gml",
                        store_files.citygml(bounds, 2180, nonce),
                    ),
                    (
                        f"{code}/informacja.pdf",
                        store_files.pdf_document(f"LoD2 {code}"),
                    ),
                ]
            ),
            request={"teryt": code},
            unit=code,
            case="file_family",
        )

    def _gpkg_layers(self) -> None:
        """BDOT10k GeoPackage of chosen classes (``--layers PTWP,SWRS``).

        Its own segment, so the bulk never uses up its TERYT codes.
        """
        segment, code = self._teryt((BDOT_GPKG_LAYERS,))
        bounds = self._teryt_bounds()
        self._write_slot(
            self._flat_slot(segment, "teryt", code, ".gpkg"),
            _Profile("gpkg_layers", segment, "EPSG:2180"),
            self._editions(1),
            body=lambda nonce: store_files.geopackage_layers(bounds, 2180, nonce),
            request={"teryt": code},
            unit=code,
            case="file_family",
        )

    def _no_sha256(self) -> None:
        """Write a 0.7.x file at the standard path: no ``sha256`` in its sidecar.

        Kartograf 0.8.0 reads a ``versions/`` entry without ``sha256`` as
        ``invalid_sidecar``, so the older sidecar without it lives at the
        standard path (no version directory, no label, no ``sha8``).
        """
        sheet = self._pl_sheet(NMT)
        storage = self._storage(resolution="1m", vertical_crs="EVRF2007")
        slot = self._sheet_slot(storage, NMT, sheet, ".asc")
        bounds = self._sheet_bounds(sheet)
        profile = _Profile(
            "asc_sheet",
            NMT,
            "EPSG:2180",
            vertical_crs="EPSG:9651",
            vertical_source="native",
            resolution="1m",
            nodata=float(store_files.NODATA),
        )
        [spec] = self._campaigns(sheet, 1)
        meta = self._sidecar(
            profile,
            request={"sheet": sheet},
            extra=spec.extra,
            sha256=None,
            size_bytes=None,
        )
        del meta["sha256"], meta["size_bytes"]
        meta["kartograf_version"] = LEGACY_KARTOGRAF
        slot.link.parent.mkdir(parents=True, exist_ok=True)
        slot.link.write_bytes(store_files.asc_grid(bounds, self._next_nonce()))
        _write_json(_sidecar_path(slot.link), meta)
        self.entries.append(
            ExpectedEntry(
                kind="link",
                segment=NMT,
                hierarchy=slot.hierarchy,
                path=self._rel(slot.link),
                family="asc_sheet",
                case="no_sha256",
                dataset_key=self._dataset_key(profile),
                unit=sheet,
                data_year=spec.data_year,
            )
        )

    def _two_formats(self) -> None:
        """One NMT sheet as ASC and as the ASCII-NMT archive (XYZ member)."""
        sheet = self._pl_sheet(NMT)
        self.asc_sheet(NMT, 1, sheet=sheet, case="two_formats")
        bounds = self._sheet_bounds(sheet)
        storage = self._storage(
            resolution="1m", vertical_crs="EVRF2007", format="ASCII-NMT"
        )
        self._write_slot(
            self._sheet_slot(storage, NMT_ASCII, sheet, ".zip"),
            _Profile(
                "zip_ascii_nmt",
                NMT_ASCII,
                "EPSG:2180",
                vertical_crs="EPSG:9651",
                vertical_source="native",
                resolution="1m",
            ),
            self._campaigns(sheet, 1),
            body=lambda nonce: store_files.zip_members(
                [(f"{sheet}.xyz", store_files.xyz_grid(bounds, nonce))]
            ),
            request={"sheet": sheet, "format": "ASCII-NMT"},
            unit=sheet,
            case="two_formats",
        )

    # --- projects ------------------------------------------------------------

    def projects(self, count: int) -> tuple[ExpectedProject, ...]:
        """Write ``count`` project directories.

        Three special cases, then regular projects pinning current and
        (every second one) older versions.
        """
        base = self.output_dir / PROJECTS_DIR
        sheets = [
            written
            for written in self.written[NMT]
            if written.profile.family == "asc_sheet"
            and written.current == len(written.versions) - 1
            and written.versions[-1].case == "regular"
        ]
        older = [written for written in sheets if len(written.versions) > 1]
        gpkg = self.written[BDOT_GPKG][0]
        result = [
            self._missing_version_project(base, sheets[0]),
            self._other_store_project(base),
            self._invalid_project(base, sheets[0]),
        ]
        for number in range(1, count - 2):
            current = sheets[(number - 1) % len(sheets)]
            tasks = [self._pinned_task("teren", current, current.current)]
            if number % 2 == 1:
                old = older[(number // 2) % len(older)]
                tasks.append(self._pinned_task("archiwum", old, 0))
            if number == 1:
                tasks.append(self._pinned_task("pokrycie", gpkg, gpkg.current))
                tasks.append(ExpectedTask("plan", "elevation download"))
            result.append(
                self._project(base, f"projekt-{number:02d}", tasks, unpinned=sheets)
            )
        return tuple(result)

    def _pinned_task(self, name: str, written: _Written, index: int) -> ExpectedTask:
        version = written.versions[index]
        command = (
            "landcover download"
            if written.slot.segment == BDOT_GPKG
            else "elevation download"
        )
        pin = ExpectedPin(
            path=self._rel(written.slot.link),
            version=cast(str, version.version_path),
            label=cast(str, version.label),
            sha256=cast(str, version.sha256),
            size_bytes=cast(int, version.size_bytes),
            unit=written.slot.unit,
            current=index == written.current,
            present=True,
        )
        return ExpectedTask(name, command, (pin,))

    def _options(self, task: ExpectedTask, fallback: str) -> dict[str, object]:
        if task.command == "landcover download":
            return {"product": "bdot10k", "teryt": task.pins[0].unit}
        sheet = task.pins[0].unit if task.pins else fallback
        return {
            "product": "nmt",
            "sheet": sheet,
            "resolution": "1m",
            "vertical_crs": "EVRF2007",
        }

    def _project(
        self,
        base: Path,
        name: str,
        tasks: Sequence[ExpectedTask],
        *,
        unpinned: Sequence[_Written],
        store: Path | None = None,
        case: ProjectCase = "regular",
    ) -> ExpectedProject:
        """Write a manifest with ``init_project``/``add_project_task``.

        The pins go into ``files[]`` by hand (ARCH 3.5): Kartograf 0.8.0
        has no offline pin writer.
        """
        directory = base / name
        store_dir = store or self.root
        init_project(directory, output_dir=os.path.relpath(store_dir))
        for task in tasks:
            add_project_task(
                directory,
                name=task.name,
                command=task.command,
                options=self._options(task, unpinned[-1].slot.unit),
            )
        manifest = directory / MANIFEST_NAME
        doc = json.loads(manifest.read_text(encoding="utf-8"))
        pins = {task.name: task.pins for task in tasks}
        for task_doc in doc["tasks"]:
            files = pins[task_doc["name"]]
            if files:
                task_doc["pinned_at"] = PIN_TIME
                task_doc["kartograf_version"] = kartograf.__version__
                task_doc["files"] = [
                    {
                        "role": "output",
                        "unit": pin.unit,
                        "path": pin.path,
                        "version": pin.version,
                        "label": pin.label,
                        "sha256": pin.sha256,
                        "size_bytes": pin.size_bytes,
                    }
                    for pin in files
                ]
        _write_json(manifest, doc)
        return ExpectedProject(
            name=name,
            path=directory.relative_to(self.output_dir).as_posix(),
            store=store_dir.relative_to(self.output_dir).as_posix(),
            case=case,
            valid=True,
            tasks=tuple(tasks),
        )

    def _missing_version_project(
        self, base: Path, written: _Written
    ) -> ExpectedProject:
        """Pin a version no longer in the store (removed by hand)."""
        pinned = self._pinned_task("teren", written, written.current).pins[0]
        missing_sha = hashlib.sha256(b"removed version").hexdigest()
        slot_versions = self._rel(written.slot.versions)
        pin = ExpectedPin(
            path=pinned.path,
            version=(
                f"{slot_versions}/2011-04-01_11111_{missing_sha[:8]}/"
                f"{written.slot.link.name}"
            ),
            label="2011-04-01_11111",
            sha256=missing_sha,
            size_bytes=1234,
            unit=pinned.unit,
            current=False,
            present=False,
        )
        task = ExpectedTask("teren", "elevation download", (pin,))
        return self._project(
            base, "brak-wersji", [task], unpinned=[written], case="missing_version"
        )

    def _other_store_project(self, base: Path) -> ExpectedProject:
        """Write a project of a store Archiwista is not configured with."""
        other = self.output_dir / OTHER_STORE_DIR
        other.mkdir()
        task = ExpectedTask("teren", "elevation download")
        sheet = self.written[NMT][0]
        return self._project(
            base,
            "inny-magazyn",
            [task],
            unpinned=[sheet],
            store=other,
            case="other_store",
        )

    def _invalid_project(self, base: Path, written: _Written) -> ExpectedProject:
        """Write a manifest ``open_project`` rejects (an unknown command)."""
        task = self._pinned_task("teren", written, written.current)
        project = self._project(base, "zepsuty", [task], unpinned=[written])
        manifest = base / "zepsuty" / MANIFEST_NAME
        doc = json.loads(manifest.read_text(encoding="utf-8"))
        doc["tasks"][0]["command"] = "elevation fly"
        _write_json(manifest, doc)
        return ExpectedProject(
            name=project.name,
            path=project.path,
            store=project.store,
            case="invalid_manifest",
            valid=False,
            tasks=project.tasks,
        )


# --- country outlines ----------------------------------------------------------


def _inside(bbox: BBox) -> bool:
    """Whether ``bbox`` lies inside the outline of the country of its CRS."""
    wgs84 = transform_bbox(bbox, "EPSG:4326")
    envelope = shapely.box(wgs84.min_x, wgs84.min_y, wgs84.max_x, wgs84.max_y)
    return bool(_OUTLINES[bbox.crs].contains(envelope))


@functools.cache
def _extent(crs: str) -> tuple[int, int, int, int]:
    """Whole-metre envelope in ``crs`` of the outline of its country."""
    min_x, min_y, max_x, max_y = _OUTLINES[crs].bounds
    envelope = transform_bbox(BBox(min_x, min_y, max_x, max_y, "EPSG:4326"), crs)
    return (
        math.floor(envelope.min_x),
        math.floor(envelope.min_y),
        math.ceil(envelope.max_x),
        math.ceil(envelope.max_y),
    )


# --- unit pools ----------------------------------------------------------------


def _pl1992_sheets() -> list[str]:
    """Return the PL-1992 1:5000 sheet codes of the 1:100 000 sheets in Poland.

    The 189 sheets of ``_pl1992_hundreds`` give 48 384 codes in canonical
    form.
    """
    return [
        f"{hundred}-{fifty}-{twenty_five}-{ten}-{five}"
        for hundred in _pl1992_hundreds()
        for fifty in "ABCD"
        for twenty_five in "abcd"
        for ten in "1234"
        for five in "1234"
    ]


@functools.cache
def _pl1992_hundreds() -> tuple[str, ...]:
    """Return the 1:100 000 sheets whose WGS84 envelope is inside ``PL_OUTLINE``.

    Of the 576 sheets of M-33, M-34, N-33 and N-34 (12-24 E, 48-56 N).
    """
    sheets = (
        f"{million}-{number}"
        for million in ("M-33", "M-34", "N-33", "N-34")
        for number in range(1, 145)
    )
    return tuple(sheet for sheet in sheets if _inside(SheetParser(sheet).get_bbox()))


def _sm5_sheets() -> list[str]:
    """SM5 map sheet codes: four capital letters and two digits."""
    letters = "ABCDEFGHIJKLMNOPRSTUVZ"
    return [
        f"{a}{b}{c}{d}{n:02d}"
        for a in letters[:6]
        for b in letters[6:12]
        for c in letters[12:16]
        for d in letters[16:]
        for n in range(0, 100, 7)
    ]


def _teryt_codes() -> list[str]:
    """Return the 380 powiat TERYT codes (``_POWIATS``)."""
    return _POWIATS.split()


# Every powiat of PRG (GUGiK; ``discover_teryts_for_bbox`` over all of Poland,
# 2026-10-19), a voivodeship per group of lines: land powiats from 01, city
# powiats from 61.
_POWIATS = """
0201 0202 0203 0204 0205 0206 0207 0208 0209 0210 0211 0212 0213 0214 0215 0216
0217 0218 0219 0220 0221 0222 0223 0224 0225 0226 0261 0262 0264 0265
0401 0402 0403 0404 0405 0406 0407 0408 0409 0410 0411 0412 0413 0414 0415 0416
0417 0418 0419 0461 0462 0463 0464
0601 0602 0603 0604 0605 0606 0607 0608 0609 0610 0611 0612 0613 0614 0615 0616
0617 0618 0619 0620 0661 0662 0663 0664
0801 0802 0803 0804 0805 0806 0807 0808 0809 0810 0811 0812 0861 0862
1001 1002 1003 1004 1005 1006 1007 1008 1009 1010 1011 1012 1013 1014 1015 1016
1017 1018 1019 1020 1021 1061 1062 1063
1201 1202 1203 1204 1205 1206 1207 1208 1209 1210 1211 1212 1213 1214 1215 1216
1217 1218 1219 1261 1262 1263
1401 1402 1403 1404 1405 1406 1407 1408 1409 1410 1411 1412 1413 1414 1415 1416
1417 1418 1419 1420 1421 1422 1423 1424 1425 1426 1427 1428 1429 1430 1432 1433
1434 1435 1436 1437 1438 1461 1462 1463 1464 1465
1601 1602 1603 1604 1605 1606 1607 1608 1609 1610 1611 1661
1801 1802 1803 1804 1805 1806 1807 1808 1809 1810 1811 1812 1813 1814 1815 1816
1817 1818 1819 1820 1821 1861 1862 1863 1864
2001 2002 2003 2004 2005 2006 2007 2008 2009 2010 2011 2012 2013 2014 2061 2062
2063
2201 2202 2203 2204 2205 2206 2207 2208 2209 2210 2211 2212 2213 2214 2215 2216
2261 2262 2263 2264
2401 2402 2403 2404 2405 2406 2407 2408 2409 2410 2411 2412 2413 2414 2415 2416
2417 2461 2462 2463 2464 2465 2466 2467 2468 2469 2470 2471 2472 2473 2474 2475
2476 2477 2478 2479
2601 2602 2603 2604 2605 2606 2607 2608 2609 2610 2611 2612 2613 2661
2801 2802 2803 2804 2805 2806 2807 2808 2809 2810 2811 2812 2813 2814 2815 2816
2817 2818 2819 2861 2862
3001 3002 3003 3004 3005 3006 3007 3008 3009 3010 3011 3012 3013 3014 3015 3016
3017 3018 3019 3020 3021 3022 3023 3024 3025 3026 3027 3028 3029 3030 3031 3061
3062 3063 3064
3201 3202 3203 3204 3205 3206 3207 3208 3209 3210 3211 3212 3213 3214 3215 3216
3217 3218 3261 3262 3263
"""


def _coords(bounds: Bounds) -> str:
    """Bbox slot name (``%.10g`` joined by ``_``, ARCH 3.3 rule 3)."""
    return "_".join(format(value, ".10g") for value in bounds)


def _sidecar_path(path: Path) -> Path:
    return path.with_name(path.name + ".meta.json")


def _write_json(path: Path, content: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


# --- command line --------------------------------------------------------------


@dataclass(frozen=True)
class StoreStats:
    """Size of the generated tree on disk."""

    files: int
    directories: int
    hardlinks: int
    """Directory entries naming an already counted inode."""
    unique_bytes: int
    """Sum of file sizes, each inode once (hardlinks are not copies)."""


def store_stats(directory: Path) -> StoreStats:
    """Count files, directories and unique bytes under ``directory``."""
    files = directories = hardlinks = unique_bytes = 0
    inodes: set[tuple[int, int]] = set()
    for current, dirnames, filenames in os.walk(directory):
        directories += len(dirnames)
        files += len(filenames)
        for name in filenames:
            info = os.lstat(os.path.join(current, name))
            key = (info.st_dev, info.st_ino)
            if key in inodes:
                hardlinks += 1
            else:
                inodes.add(key)
                unique_bytes += info.st_size
    return StoreStats(files, directories, hardlinks, unique_bytes)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: Sequence[str] | None = None) -> int:
    """Generate a store from the command line and print its summary.

    Parameters
    ----------
    argv : sequence of str or None, optional
        Arguments without the program name (default: ``sys.argv[1:]``).

    Returns
    -------
    int
        Exit status: 0 on success.
    """
    parser = argparse.ArgumentParser(
        prog="python -m tests.fixtures.make_store",
        description=(
            "Write a synthetic Kartograf store with projects and verify it "
            "with Kartograf's readers. Use a data directory outside the "
            "repository and outside /tmp."
        ),
    )
    parser.add_argument("output_dir", type=Path, help="missing or empty directory")
    parser.add_argument(
        "--slots", type=int, default=50_000, help="regular slots (default: 50000)"
    )
    parser.add_argument("--seed", type=int, default=1, help="random seed (default: 1)")
    parser.add_argument(
        "--projects", type=int, default=30, help="project directories (default: 30)"
    )
    args = parser.parse_args(argv)
    output_dir = cast(Path, args.output_dir).absolute()
    if output_dir.resolve().is_relative_to(_repository_root()):
        parser.error(f"refusing to write test data into the repository: {output_dir}")
    started = time.perf_counter()
    try:
        manifest = make_store(
            output_dir, slots=args.slots, seed=args.seed, projects=args.projects
        )
    except ValueError as exc:
        parser.error(str(exc))
    elapsed_s = time.perf_counter() - started
    stats = store_stats(manifest.output_dir)
    print(f"store: {manifest.root}")
    print(f"projects: {manifest.projects_dir} ({len(manifest.projects)})")
    print(f"slots: {len(manifest.by_kind('link'))} ({manifest.slots} regular)")
    print(f"versions: {len(manifest.by_kind('version'))}")
    print(f"full_sheet links: {len(manifest.by_kind('full_sheet'))}")
    print(f"problems: {len(manifest.by_kind('problem'))}")
    print(f"segments: {len(manifest.segments())}")
    print(
        f"files: {stats.files} ({stats.hardlinks} hardlinks), "
        f"directories: {stats.directories}"
    )
    print(f"size: {stats.unique_bytes / 2**20:.1f} MiB (each inode once)")
    print(f"time: {elapsed_s:.1f} s (generation and verification)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
