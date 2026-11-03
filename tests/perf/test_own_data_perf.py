r"""Own-data targets of plan v0.2 (decision 12) through ``archiwista serve`` (step 16).

A project with a data folder of 1000 files — a 100 MB GeoPackage (460 000
polygons), GeoTIFFs, GeoJSON files, Shapefiles of five files each and CSV
files nobody reads — lies in ``own-data-perf/`` next to the 50 000-slot store
on the local disk (written by the SSD run when missing), and in the same
directory next to the store's copy on the share (copied there by hand)::

    ARCHIWISTA_PERF_STORE=<katalog-danych>/store-50k \\
        .venv/bin/python -m pytest -m perf tests/perf/test_own_data_perf.py --no-cov -s
    rsync -a --exclude .wersje <katalog-danych>/own-data-perf/ <udział>/own-data-perf/
    ARCHIWISTA_SMB_STORE=<udział>/store-50k ARCHIWISTA_SMB_WORK=<katalog-danych> \\
        .venv/bin/python -m pytest -m smb tests/perf/test_own_data_perf.py --no-cov -s

The server runs as its own process (configuration, index and work files in
``perf-own-<ssd|smb>/``, locally); each run starts with the GeoPackage as
written and without snapshots. Measured: the ``own_scan`` of the unchanged
folder (``POST /projects/{project}/scan``, the job from start to end, p95 of
30 after the first scan read the files), and snapshots of the GeoPackage
(``POST …/files/{file_id}/snapshots``: a consistent copy, two digests,
``integrity_check``, the publication in ``.wersje/``), each after a row was
added and the folder scanned again. Coverage must be off (``--no-cov``).
"""

import os
import shutil
import sqlite3
import stat
import statistics
import struct
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pyogrio
import pytest
import rasterio
import shapely
from rasterio.transform import from_origin

from archiwista.config import AppSettings, StoreConfig, StoreKind, detect_store_kind
from archiwista.projects import ProjectDocument, StoreRoot, change_project_file
from tests.fixtures.perf_server import (
    Medium,
    ServerProcess,
    job_seconds,
    load,
    memory_status,
    p95,
    refuse_coverage,
    serve_process,
)

FIXTURES = "own-data-perf"
"""The project's directory, next to the 50 000-slot store."""
STORE = "wlasne"
PROJECT = "perf-1000"
DATA_DIR = "dane"
SNAPSHOTS_DIR = ".wersje"
GPKG = "plan.gpkg"
GPKG_BYTES = 100 * 10**6
POLYGONS = 460_000
FILES = 1000
RASTERS, GEOJSONS, SHAPEFILES = 200, 200, 100
SHAPEFILE_MEMBERS = (".shp", ".shx", ".dbf", ".prj", ".cpg")
OTHERS = FILES - 1 - RASTERS - GEOJSONS - SHAPEFILES * len(SHAPEFILE_MEMBERS)
RUNS = 30
SNAPSHOTS = 3
JOB_TIMEOUT_S = 900.0
# Kraków's west, EPSG:2180: where the polygons and rasters lie.
ORIGIN = (560_000.0, 240_000.0)


@dataclass(frozen=True)
class Target:
    """Where the folder lies and the limits of decision 12 there (seconds)."""

    name: str
    variable: str
    kind: StoreKind
    scan_s: float
    snapshot_s: float


SSD = Target("ssd", "ARCHIWISTA_PERF_STORE", "local", 2.0, 15.0)
SMB = Target("smb", "ARCHIWISTA_SMB_STORE", "share", 10.0, 60.0)


@dataclass
class _Served(ServerProcess):
    """The server over the project; its key and data folder."""

    target: Target = SSD
    project: str = ""
    folder: Path = Path()
    medium: Medium | None = None

    def scan(self) -> dict[str, Any]:
        """Scan the project's data folder in an ``own_scan`` job; return it."""
        started = self.post(f"/projects/{self.project}/scan", None)
        job: dict[str, Any] = self.wait(started["id"], JOB_TIMEOUT_S, poll_s=0.05)
        assert job["state"] == "succeeded", job
        return job


def _write_folder(directory: Path) -> None:
    """Write the project, its store and its data folder of ``FILES`` files."""
    store = directory / "store"
    project = directory / "projects" / PROJECT
    store.mkdir(parents=True, exist_ok=True)
    project.mkdir(parents=True)
    change_project_file(
        project,
        create=ProjectDocument(
            name=PROJECT,
            description="",
            created_at=datetime(2026, 10, 31, tzinfo=UTC),
            created_by="local",
            stores=(StoreRoot("kartograf", str(store.absolute())),),
        ),
    )
    folder = project / DATA_DIR
    pristine = directory / "pristine"
    pristine.mkdir(parents=True)
    _write_geopackage(pristine / GPKG)
    folder.mkdir()
    for number in range(RASTERS):
        _write_raster(folder / "rastry" / f"r{number:03d}.tif", number)
    for number in range(GEOJSONS):
        _write_vectors(
            folder / "wektory" / f"w{number:03d}.geojson",
            "GeoJSON",
            [shapely.Point(19.80 + number * 1e-3, 50.05)],
            "EPSG:4326",
        )
    for number in range(SHAPEFILES):
        x, y = ORIGIN[0] + number * 30.0, ORIGIN[1] + 5_000.0
        _write_vectors(
            folder / "dzialki" / f"d{number:03d}.shp",
            "ESRI Shapefile",
            [shapely.box(x, y, x + 20.0, y + 20.0)],
            "EPSG:2180",
        )
    others = folder / "inne"
    others.mkdir()
    for number in range(OTHERS):
        (others / f"n{number:03d}.csv").write_text(
            f"x;y;h\n{ORIGIN[0] + number:.1f};{ORIGIN[1]:.1f};212.{number}\n",
            encoding="utf-8",
        )
    shutil.copyfile(pristine / GPKG, folder / GPKG)
    found = sum(1 for item in folder.rglob("*") if item.is_file())
    assert found == FILES, found


def _write_geopackage(path: Path) -> None:
    """Write ``POLYGONS`` parcels with three fields, about ``GPKG_BYTES``."""
    side = int(np.ceil(np.sqrt(POLYGONS)))
    numbers = np.arange(POLYGONS)
    x = ORIGIN[0] + (numbers % side) * 12.0
    y = ORIGIN[1] + (numbers // side) * 12.0
    boxes = shapely.box(x, y, x + 10.0, y + 10.0)
    pyogrio.raw.write(
        path,
        shapely.to_wkb(boxes),
        [
            numbers.astype(np.int32),
            np.array([f"działka {number}" for number in numbers], dtype=object),
            (100.0 + numbers % 97).astype(np.float64),
        ],
        ["numer", "nazwa", "pow"],
        layer="dzialki",
        driver="GPKG",
        geometry_type="Polygon",
        crs="EPSG:2180",
    )


def _write_raster(path: Path, number: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows, columns = np.indices((64, 64))
    values = (200.0 + number + rows * 0.5 + columns * 0.25).astype(np.float32)
    west = ORIGIN[0] + (number % 20) * 640.0
    north = ORIGIN[1] + 10_000.0 + (number // 20) * 640.0
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=64,
        height=64,
        count=1,
        dtype="float32",
        crs="EPSG:2180",
        transform=from_origin(west, north, 10.0, 10.0),
    ) as dataset:
        dataset.write(values, 1)


def _write_vectors(
    path: Path, driver: str, geometries: list[shapely.Geometry], crs: str
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pyogrio.raw.write(
        path,
        np.array([shapely.to_wkb(item) for item in geometries], dtype=object),
        [np.array(["obiekt"] * len(geometries), dtype=object)],
        ["opis"],
        layer=path.stem,
        driver=driver,
        geometry_type="Polygon" if driver == "ESRI Shapefile" else "Point",
        crs=crs,
        **({"encoding": "UTF-8"} if driver == "ESRI Shapefile" else {}),
    )


def _remove_snapshots(folder: Path) -> None:
    """Remove ``.wersje/`` (read-only files in read-only directories)."""
    snapshots = folder / SNAPSHOTS_DIR
    if not snapshots.exists():
        return
    for top, dirnames, _ in os.walk(snapshots):
        for name in dirnames:
            os.chmod(os.path.join(top, name), stat.S_IRWXU)
    os.chmod(snapshots, stat.S_IRWXU)
    shutil.rmtree(snapshots)


def _fixtures_dir(target: Target) -> Path:
    variable = os.environ.get(target.variable)
    if not variable:
        pytest.skip(f"{target.variable} names the 50 000-slot store")
    directory = Path(variable).parent / FIXTURES
    medium = Medium.of(directory.parent)
    if target is SMB:
        assert medium.share, medium
        if not (directory / "projects" / PROJECT / DATA_DIR).is_dir():
            pytest.skip(f"copy <katalog-danych>/{FIXTURES} to {directory} first")
    else:
        assert medium.rotational is False, f"not an SSD: {medium}"
        if not directory.exists():
            _write_folder(directory)
    folder = directory / "projects" / PROJECT / DATA_DIR
    _remove_snapshots(folder)
    shutil.copyfile(directory / "pristine" / GPKG, folder / GPKG)
    return directory


def _work_dir(target: Target, directory: Path) -> Path:
    if target is not SMB:
        return directory.parent
    variable = os.environ.get("ARCHIWISTA_SMB_WORK")
    if not variable:
        pytest.skip("ARCHIWISTA_SMB_WORK names a local directory for the index")
    work = Path(variable)
    assert detect_store_kind(work) == "local", work
    return work


@pytest.fixture(
    scope="module",
    params=[
        pytest.param(SSD, marks=pytest.mark.perf, id="ssd"),
        pytest.param(SMB, marks=pytest.mark.smb, id="smb"),
    ],
)
def served(request: pytest.FixtureRequest) -> Iterator[_Served]:
    """Serve the project after the scheduler's scans and a first own scan."""
    target: Target = request.param
    directory = _fixtures_dir(target)
    refuse_coverage()
    work = _work_dir(target, directory) / f"perf-own-{target.name}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    config = StoreConfig(
        id=STORE, name="Własne", kartograf=directory / "store", kind=target.kind
    )
    settings = AppSettings(
        offline=True,
        stores=(config,),
        project_dirs=(directory / "projects",),
        scan_interval_local_min=1440,
        scan_interval_share_min=1440,
    )
    with serve_process(work, settings) as server:
        served = _Served(
            server.process,
            server.client,
            server.memory,
            server.paths,
            target=target,
            folder=directory / "projects" / PROJECT / DATA_DIR,
            medium=Medium.of(directory),
        )
        deadline = time.monotonic() + 300
        while not (projects := served.get("/projects")["items"]):
            assert time.monotonic() < deadline, "no project indexed"
            time.sleep(0.5)
        served.project = projects[0]["project"]
        started = time.perf_counter()
        first = served.scan()
        print(
            f"\n[{target.name}] folder on"
            f" {served.medium.describe() if served.medium else '-'};"
            f" first own scan {job_seconds(first):.1f} s (seen"
            f" {time.perf_counter() - started:.1f} s): {first['result']}; {load()}"
        )
        yield served
        print(f"\n[{target.name}] end: {load()}")


def test_own_scan_of_1000_unchanged_files(served: _Served) -> None:
    """An ``own_scan`` of 1000 unchanged files ≤ 2 s (SSD) at p95: ``stat`` only."""
    jobs = [served.scan() for _ in range(RUNS)]
    seconds = [job_seconds(job) for job in jobs]
    listed = served.get(f"/projects/{served.project}/files", limit=1)
    disk = sum(1 for item in served.folder.rglob("*") if item.is_file())
    print(
        f"\n[{served.target.name}] own scan of {disk} unchanged files"
        f" ({listed['folder']['files']} in the index): p95 {p95(seconds):.2f} s"
        f" (median {statistics.median(seconds):.2f} s, max {max(seconds):.2f} s,"
        f" {RUNS} jobs); last result {jobs[-1]['result']}"
    )

    assert disk == FILES
    assert p95(seconds) <= served.target.scan_s


def _add_row(path: Path, number: int) -> None:
    """Rename a parcel as an editor would: another content, the same size.

    GDAL's R*Tree triggers call its SQL functions on every update; they get
    the envelope the geometry's GeoPackage header holds. The write runs
    without SQLite's locks (``nolock=1``), nothing else touching the file
    meanwhile: on a share mounted without POSIX extensions (``nounix``) a
    shared lock never becomes exclusive, and every commit ends ``database is
    locked``.
    """

    def envelope(blob: bytes) -> tuple[float, float, float, float]:
        order = "<" if blob[3] & 1 else ">"
        found: tuple[float, float, float, float] = struct.unpack(
            f"{order}4d", blob[8:40]
        )
        return found

    with sqlite3.connect(f"{path.as_uri()}?nolock=1", uri=True) as connection:
        connection.create_function("ST_IsEmpty", 1, lambda blob: int(blob[3] >> 4 & 1))
        for index, name in enumerate(("ST_MinX", "ST_MaxX", "ST_MinY", "ST_MaxY")):
            connection.create_function(
                name, 1, lambda blob, at=index: envelope(blob)[at]
            )
        connection.execute(
            "UPDATE dzialki SET nazwa = ? WHERE fid = ?",
            (f"działka po zmianie {number}", number),
        )
    connection.close()


def test_snapshot_of_100_mb_geopackage(served: _Served) -> None:
    """A snapshot of a 100 MB GeoPackage ≤ 15 s (SSD): copy, two sums, integrity."""
    found = served.get(f"/projects/{served.project}/files", q="plan")["items"]
    item = next(entry for entry in found if entry["path"] == GPKG)
    url = f"/projects/{served.project}/files/{item['file_id']}/snapshots"
    jobs = []
    for number in range(SNAPSHOTS):
        if number:
            _add_row(served.folder / GPKG, number)
            served.scan()
        started = served.post(url, {"note": f"pomiar {number + 1}"})
        job = served.wait(started["id"], JOB_TIMEOUT_S, poll_s=0.1)
        assert job["state"] == "succeeded", job
        assert job["result"]["status"] == "created", job["result"]
        jobs.append(job)
    seconds = [job_seconds(job) for job in jobs]
    status = memory_status(served.process.pid)
    assert status is not None
    print(
        f"\n[{served.target.name}] snapshot of {GPKG} ({item['size_bytes'] / 10**6:.1f}"
        f" MB): jobs " + ", ".join(f"{value:.1f}" for value in seconds) + " s"
        " (inside: "
        + ", ".join(f"{job['result']['seconds']:.1f}" for job in jobs)
        + f" s); server peak resident {status['VmHWM'] / 1024:.0f} MiB"
    )

    assert item["size_bytes"] >= GPKG_BYTES * 0.95
    assert max(seconds) <= served.target.snapshot_s
