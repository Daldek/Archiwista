"""A store of preview fixtures of real sizes for the measurements (plan v0.2, step 16).

``make_preview_store(output_dir, source=…)`` writes a Kartograf store under
``output_dir`` (``data/`` and an empty ``projects/``; slot paths from
``FileStorage``, versions, links and sidecars as ARCH 3.2-3.4, like the
other fixtures) from three real files of a Kartograf store ``source``
(``SOURCES``; the live store of Kartograf 0.8.0,
``<udział>/kartograf/release-0.8.0/data``, has them), reads it back with
``iter_store`` and lists its groups in ``MANIFEST`` (``PreviewStore.load``):

- ``ortho``: the orthophoto ``ORTHO_SHEET`` of ``orto/pl_1992`` as
  downloaded, 22 528 × 24 326 px tiled by 256 with JPEG and overviews
  (decision 12);
- ``asc_year``: 35 neighbouring 1:5000 NMT sheets of 2025 in ASC 1 m, each
  the real sheet's 38 MB grid placed at the sheet, with a first cell of its
  own so that every sheet has its own content; ``asc_singles``: five more of
  2024, away from them, for builds one at a time;
- ``sm5_year``: 50 neighbouring SM5 sheets of 2024 near Ostrava, each the
  real sheet at 20 cm instead of 12.5 cm — 12 500 × 10 000 px, the 125 Mpx of
  decision 12 — encoded once, a JPEG comment of its own making every file
  distinct; each with its world file, a slot of its own as Kartograf keeps
  them; ``sm5_singles``: five more of 2023 west of them; ``sm5_sheet``: the
  real 20 000 × 16 000 px sheet ``SM5_SHEET`` with its world file;
- ``map_year``: 200 neighbouring 1:10 000 NMT sheets of 2023 as 64 × 64 px
  ASC grids, the year drawn on the map from tiles in the preview cache.

Run ``python -m tests.fixtures.preview_store --source <udział>/kartograf/
release-0.8.0/data <katalog-danych>/previews-perf``: the measurements
(``tests/perf/test_previews_perf.py``) look for it next to the 50 000-slot
store. Keep it outside the repository and outside ``/tmp``.
"""

import argparse
import copy
import hashlib
import json
import math
import os
import sys
import time
import warnings
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import rasterio
from kartograf import FileStorage, SheetParser, find_sheets_for_bbox, iter_store
from kartograf.core.bbox import BBox
from rasterio.enums import Resampling
from rasterio.errors import NotGeoreferencedWarning
from rasterio.io import MemoryFile

from tests.fixtures import store_files
from tests.fixtures.make_store import (
    CZ_ORTO,
    NMT,
    ORTO,
    PROJECTS_DIR,
    STORE_DIR,
    StoreFixtureError,
)

ORTHO_SHEET = "N-34-130-D-d-2-4"
SM5_SHEET = "CTES96"
SOURCES = {
    "ortho": f"{ORTO}/N-34/130/D/d/2/4/{ORTHO_SHEET}.tif",
    "asc": f"{NMT}/N-34/130/D/d/2/4/{ORTHO_SHEET}.asc",
    "sm5": f"{CZ_ORTO}/CTES/96/{SM5_SHEET}.jpg",
}
"""The real files the store is made of, in a Kartograf store's ``data/``."""
ASC_YEARS = {2025: ("82710", "2025-04-26"), 2024: ("80085", "2024-05-14")}
"""Campaign id and flight day of the ASC sheets of each data year."""
MAP_CAMPAIGN = ("77001", "2023-06-02")
ASC_YEAR_SHEETS = 35
ASC_SINGLE_SHEETS = 5
MAP_YEAR_SHEETS = 200
SM5_ROWS, SM5_COLUMNS = 5, 10
SM5_SINGLE_SHEETS = 5
SM5_PIXEL_M = 0.2
SM5_WIDTH_M, SM5_HEIGHT_M = 2500.0, 2000.0
SM5_WEST, SM5_NORTH = -485_000.0, -1_104_000.0
"""North-west corner of the 10 × 5 SM5 sheets (EPSG:5514), all in Czechia."""
SM5_SINGLES_WEST = SM5_WEST - 25_000.0
"""West end of the row of single SM5 sheets, 12.5 km west of the year's."""
SM5_EDITIONS = {
    2024: ("OSTR", "2024_2025-02-06", "2025-02-06T14:00:09+02:00"),
    2023: ("OPAV", "2023_2024-02-15", "2024-02-15T14:00:00+02:00"),
}
"""Letters of the sheets, edition and update of the SM5 sheets of each year."""
SM5_JPEG_QUALITY = 85
DOWNLOADED_AT = "2026-10-16T19:12:45+00:00"
MANIFEST = "preview-store.json"
"""The written groups, next to ``data/``: the measurements read them."""
_CHUNK = 8 * 2**20


@dataclass(frozen=True)
class PreviewStore:
    """The written store: where it is and its versions by group.

    Parameters
    ----------
    output_dir : Path
        The directory given (``data/``, ``projects/`` and ``MANIFEST``).
    ortho : str
        Store path of the orthophoto version.
    asc_year, asc_singles, sm5_year, sm5_singles, map_year : tuple of str
        Store paths of the versions of each group (JPEGs only for SM5).
    sm5_sheet : str
        Store path of the real SM5 sheet's JPEG version.
    """

    output_dir: Path
    ortho: str
    asc_year: tuple[str, ...]
    asc_singles: tuple[str, ...]
    sm5_year: tuple[str, ...]
    sm5_singles: tuple[str, ...]
    sm5_sheet: str
    map_year: tuple[str, ...]

    @property
    def root(self) -> Path:
        """The store's ``data/`` directory."""
        return self.output_dir / STORE_DIR

    def save(self) -> None:
        """Write the groups to ``MANIFEST``."""
        groups = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "output_dir"
        }
        (self.output_dir / MANIFEST).write_text(
            json.dumps(groups, indent=2) + "\n", encoding="utf-8"
        )

    @classmethod
    def load(cls, output_dir: Path) -> "PreviewStore":
        """Read the groups a ``make_preview_store`` of ``output_dir`` wrote."""
        groups: dict[str, Any] = json.loads(
            (output_dir / MANIFEST).read_text(encoding="utf-8")
        )
        return cls(
            output_dir,
            ortho=groups["ortho"],
            asc_year=tuple(groups["asc_year"]),
            asc_singles=tuple(groups["asc_singles"]),
            sm5_year=tuple(groups["sm5_year"]),
            sm5_singles=tuple(groups["sm5_singles"]),
            sm5_sheet=groups["sm5_sheet"],
            map_year=tuple(groups["map_year"]),
        )


def make_preview_store(output_dir: Path, *, source: Path) -> PreviewStore:
    """Write the store under ``output_dir`` from the real files of ``source``.

    Parameters
    ----------
    output_dir : Path
        A missing or empty directory.
    source : Path
        ``data/`` of a Kartograf store with the files of ``SOURCES`` and
        their sidecars at the standard path.

    Raises
    ------
    StoreFixtureError
        A source file is missing, or Kartograf reads the store otherwise
        than it was written.
    """
    output_dir = output_dir.absolute()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise StoreFixtureError(f"not an empty directory: {output_dir}")
    for relative in SOURCES.values():
        if not (source / relative).is_file():
            raise StoreFixtureError(f"the source store has no {relative}")
    root = output_dir / STORE_DIR
    root.mkdir(parents=True)
    (output_dir / PROJECTS_DIR).mkdir()
    ortho_storage = FileStorage(root, resolution=None, vertical_crs=None, subdir=ORTO)
    ortho_source = source / SOURCES["ortho"]
    ortho = _put_file(
        root,
        ortho_storage.get_versions_root(ORTHO_SHEET),
        ortho_storage.get_path(ORTHO_SHEET, ".tif"),
        ortho_source,
        _source_meta(ortho_source),
    )
    asc_year, asc_singles = _asc_sheets(root, source / SOURCES["asc"])
    sm5_year, sm5_singles, sm5_sheet = _sm5_sheets(root, source / SOURCES["sm5"])
    store = PreviewStore(
        output_dir,
        ortho,
        asc_year,
        asc_singles,
        sm5_year,
        sm5_singles,
        sm5_sheet,
        _map_year(root, _source_meta(source / SOURCES["asc"])),
    )
    _verify(store)
    store.save()
    return store


def neighbour_sheets(centre: tuple[float, float], scale: str, count: int) -> list[str]:
    """Return the ``count`` PL-1992 sheets of ``scale`` nearest a point (EPSG:2180).

    Nearest by the centre of their box, so the sheets make one patch.
    """
    x, y = centre
    reach = 3_000.0 * math.sqrt(count) * (2.0 if scale == "1:10000" else 1.0)
    found = find_sheets_for_bbox(
        BBox(x - reach, y - reach, x + reach, y + reach, "EPSG:2180"), scale, "1992"
    )

    def distance(sheet: str) -> float:
        box = SheetParser(sheet).get_bbox()
        return math.hypot(
            (box.min_x + box.max_x) / 2 - x, (box.min_y + box.max_y) / 2 - y
        )

    nearest = sorted(found, key=distance)[:count]
    if len(nearest) < count:
        raise StoreFixtureError(f"only {len(nearest)} sheets of {scale} near {centre}")
    return sorted(nearest)


def _asc_sheets(root: Path, grid: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Write the real ASC grid at each sheet of the year and of the singles."""
    data = grid.read_bytes()
    lines = data.split(b"\n", 6)
    header = {
        key.lower(): value
        for key, value in (line.decode("ascii").split() for line in lines[:6])
    }
    body = lines[6]
    first = body.split(b" ", 1)[1]
    meta = _source_meta(grid)
    source_box = SheetParser(ORTHO_SHEET).get_bbox()
    width = source_box.max_x - source_box.min_x
    height = source_box.max_y - source_box.min_y
    storage = FileStorage(root, resolution="1m", vertical_crs="EVRF2007")
    written: dict[int, list[str]] = {}
    patches = {
        2025: neighbour_sheets(
            (source_box.max_x + 4 * width, source_box.max_y + 3 * height),
            "1:5000",
            ASC_YEAR_SHEETS,
        ),
        2024: neighbour_sheets(
            (source_box.max_x + 4 * width, source_box.min_y - 12 * height),
            "1:5000",
            ASC_SINGLE_SHEETS,
        ),
    }
    for year, sheets in patches.items():
        campaign, day = ASC_YEARS[year]
        for number, sheet in enumerate(sheets, start=1):
            box = SheetParser(sheet).get_bbox()
            text = (
                f"ncols {header['ncols']}\nnrows {header['nrows']}\n"
                f"xllcenter {math.ceil(box.min_x):.2f}\n"
                f"yllcenter {math.ceil(box.min_y):.2f}\n"
                f"cellsize {header['cellsize']}\n"
                f"nodata_value {header['nodata_value']}\n"
                f"{year}.{number:02d} "
            )
            sheet_meta = _campaign_meta(meta, sheet, campaign, day)
            written.setdefault(year, []).append(
                _put_bytes(
                    root,
                    storage.get_versions_root(sheet),
                    storage.get_path(sheet, ".asc"),
                    text.encode("ascii") + first,
                    sheet_meta,
                )
            )
    return tuple(written[2025]), tuple(written[2024])


def _map_year(root: Path, meta: dict[str, Any]) -> tuple[str, ...]:
    """Write 200 small ASC sheets of 1:10 000, one patch in western Poland.

    ``meta``: the real ASC sheet's sidecar, which each sheet's is made of.
    """
    campaign, day = MAP_CAMPAIGN
    storage = FileStorage(root, resolution="1m", vertical_crs="EVRF2007")
    written = []
    for number, sheet in enumerate(
        neighbour_sheets((330_000.0, 470_000.0), "1:10000", MAP_YEAR_SHEETS), start=1
    ):
        box = SheetParser(sheet).get_bbox()
        bounds = (box.min_x, box.min_y, box.max_x, box.max_y)
        written.append(
            _put_bytes(
                root,
                storage.get_versions_root(sheet),
                storage.get_path(sheet, ".asc"),
                store_files.asc_grid(bounds, number),
                _campaign_meta(meta, sheet, campaign, day),
            )
        )
    return tuple(written)


def _sm5_sheets(
    root: Path, image: Path
) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    """Write the SM5 sheets at 20 cm and the real one with their world files.

    Returns the JPEGs of the year's 50 sheets, of the single sheets and the
    real sheet's.
    """
    storage = FileStorage(root, resolution=None, vertical_crs=None, subdir=CZ_ORTO)
    meta = _source_meta(image)
    world = image.with_suffix(".jgw")
    world_meta = _source_meta(world)
    _put_file(
        root,
        storage.get_raw_versions_root(SM5_SHEET),
        storage.get_raw_path(SM5_SHEET, world.name),
        world,
        world_meta,
    )
    real = _put_file(
        root,
        storage.get_raw_versions_root(SM5_SHEET),
        storage.get_raw_path(SM5_SHEET, image.name),
        image,
        meta,
    )
    encoded = _smaller_jpeg(image)
    places = {
        2024: [
            (
                row,
                column,
                SM5_WEST + column * SM5_WIDTH_M,
                SM5_NORTH - row * SM5_HEIGHT_M,
            )
            for row in range(SM5_ROWS)
            for column in range(SM5_COLUMNS)
        ],
        2023: [
            (0, column, SM5_SINGLES_WEST + column * SM5_WIDTH_M, SM5_NORTH)
            for column in range(SM5_SINGLE_SHEETS)
        ],
    }
    written: dict[int, list[str]] = {}
    for year, sheets in places.items():
        letters = SM5_EDITIONS[year][0]
        for row, column, west, north in sheets:
            sheet = f"{letters}{row}{column}"
            half = SM5_PIXEL_M / 2
            lines = (SM5_PIXEL_M, 0.0, 0.0, -SM5_PIXEL_M, west + half, north - half)
            versions = storage.get_raw_versions_root(sheet)
            _put_bytes(
                root,
                versions,
                storage.get_raw_path(sheet, f"{sheet}.jgw"),
                "".join(f"{value:.6f}\n" for value in lines).encode("ascii"),
                _sm5_meta(world_meta, sheet, year),
            )
            written.setdefault(year, []).append(
                _put_bytes(
                    root,
                    versions,
                    storage.get_raw_path(sheet, f"{sheet}.jpg"),
                    _with_comment(encoded, f"Archiwista perf {sheet}"),
                    _sm5_meta(meta, sheet, year),
                )
            )
    return tuple(written[2024]), tuple(written[2023]), real


def _smaller_jpeg(image: Path) -> bytes:
    """Return the real sheet at ``SM5_PIXEL_M`` as a JPEG (pixel averages)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with rasterio.open(image, driver="JPEG") as dataset:
            width = round(dataset.width * dataset.res[0] / SM5_PIXEL_M)
            height = round(dataset.height * dataset.res[0] / SM5_PIXEL_M)
            pixels = dataset.read(
                out_shape=(dataset.count, height, width), resampling=Resampling.average
            )
        with MemoryFile() as memory:
            with memory.open(
                driver="JPEG",
                width=width,
                height=height,
                count=int(pixels.shape[0]),
                dtype="uint8",
                QUALITY=SM5_JPEG_QUALITY,
            ) as encoded:
                encoded.write(np.ascontiguousarray(pixels))
            return bytes(memory.read())


def _with_comment(jpeg: bytes, text: str) -> bytes:
    """Return a JPEG with a comment (``COM``) after its start: same image, new bytes."""
    comment = text.encode("ascii")
    segment = b"\xff\xfe" + (len(comment) + 2).to_bytes(2, "big") + comment
    return jpeg[:2] + segment + jpeg[2:]


def _source_meta(path: Path) -> dict[str, Any]:
    """Return a real file's sidecar without what names its own bytes and link."""
    meta: dict[str, Any] = json.loads(
        path.with_name(path.name + ".meta.json").read_text("utf-8")
    )
    for key in ("sha256", "size_bytes"):
        meta.pop(key, None)
    for key in ("link", "link_target"):
        meta["extra"].pop(key, None)
    return meta


def _campaign_meta(
    meta: dict[str, Any], sheet: str, campaign: str, day: str
) -> dict[str, Any]:
    """Return an NMT sidecar for a sheet flown on ``day`` in ``campaign``."""
    found = copy.deepcopy(meta)
    found["request"] = {"sheet": sheet, "campaigns": "newest"}
    found["downloaded_at"] = DOWNLOADED_AT
    source = found["extra"].setdefault("source", {})
    source.update(
        sheet=sheet,
        acquisition_date=day,
        acquisition_year=day[:4],
        url=f"https://opendata.geoportal.gov.pl/NumDaneWys/NMT/{campaign}/{sheet}.asc",
    )
    found["extra"]["campaign"] = {
        **found["extra"].get("campaign", {}),
        "id": campaign,
        "date": day,
    }
    found["extra"]["version"] = {
        "label": f"{day}_{campaign}",
        "label_source": "campaign",
    }
    return found


def _sm5_meta(meta: dict[str, Any], sheet: str, year: int) -> dict[str, Any]:
    """Return the sidecar of an SM5 sheet's file of ``year``, from the real sheet's."""
    _, edition, updated = SM5_EDITIONS[year]
    found = copy.deepcopy(meta)
    found["request"] = {"sheet": sheet}
    extra = found["extra"]
    extra["mapname"] = f"{sheet[:4]} {sheet[4]}-{sheet[5]}"
    extra["cz_share"] = 1.0
    extra.pop("http", None)
    extra.pop("world_files", None)
    package = f"WRTO{year % 100}.{year}.{sheet}"
    extra["source"].update(
        url=f"https://openzu.cuzk.cz/opendata/ORTOFOTO/{package}.zip",
        member=f"{package}{Path(extra['source']['member']).suffix}",
        edition=edition,
        year=year,
        updated=updated,
    )
    extra["version"] = {"label": edition, "label_source": "edition"}
    return found


def _put_bytes(
    root: Path, versions: Path, link: Path, data: bytes, meta: dict[str, Any]
) -> str:
    """Write a version of ``data`` and point the standard path at it.

    Returns the version's path in the store.
    """
    sha256 = hashlib.sha256(data).hexdigest()
    version = _version_path(versions, link, meta, sha256)
    version.write_bytes(data)
    return _link(root, version, link, meta, sha256, len(data))


def _put_file(
    root: Path, versions: Path, link: Path, source: Path, meta: dict[str, Any]
) -> str:
    """Copy a file into a version and point the standard path at it."""
    digest = hashlib.sha256()
    with source.open("rb") as file:
        while chunk := file.read(_CHUNK):
            digest.update(chunk)
    sha256 = digest.hexdigest()
    version = _version_path(versions, link, meta, sha256)
    with source.open("rb") as file, version.open("wb") as out:
        while chunk := file.read(_CHUNK):
            out.write(chunk)
    copied = hashlib.sha256(version.read_bytes()).hexdigest()
    if copied != sha256:
        raise StoreFixtureError(f"{source} changed while it was copied")
    return _link(root, version, link, meta, sha256, version.stat().st_size)


def _version_path(
    versions: Path, link: Path, meta: dict[str, Any], sha256: str
) -> Path:
    label = meta["extra"]["version"]["label"]
    version = versions / f"{label}_{sha256[:8]}" / link.name
    version.parent.mkdir(parents=True)
    return version


def _link(
    root: Path,
    version: Path,
    link: Path,
    meta: dict[str, Any],
    sha256: str,
    size: int,
) -> str:
    """Write the version's sidecar, hard-link the standard path, write its sidecar."""
    meta = {**meta, "sha256": sha256, "size_bytes": size}
    _write_json(version, meta)
    link.parent.mkdir(parents=True, exist_ok=True)
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


def _verify(store: PreviewStore) -> None:
    """Check that Kartograf reads every version as written, without problems."""
    expected = {
        store.ortho: 2025,
        store.sm5_sheet: 2024,
        **dict.fromkeys(store.asc_year, 2025),
        **dict.fromkeys(store.asc_singles, 2024),
        **dict.fromkeys(store.sm5_year, 2024),
        **dict.fromkeys(store.sm5_singles, 2023),
        **dict.fromkeys(store.map_year, 2023),
    }
    found: dict[str, int | None] = {}
    problems = []
    for entry in iter_store(store.root):
        if entry.problem is not None:
            problems.append(f"{entry.path}: {entry.problem}")
        elif entry.kind == "version" and entry.sidecar is not None:
            path = entry.path.relative_to(store.root).as_posix()
            if path.endswith(".jgw"):
                continue
            found[path] = entry.sidecar.data_year
    if problems or found != expected:
        wrong = {
            path: year for path, year in found.items() if expected.get(path) != year
        }
        raise StoreFixtureError(
            f"Kartograf reads the preview store otherwise: {problems or wrong}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Write the store from the command line and print its groups.

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
        prog="python -m tests.fixtures.preview_store",
        description=(
            "Write the store of preview fixtures of real sizes from the real files "
            "of a Kartograf store. Use a data directory outside the repository "
            "and outside /tmp."
        ),
    )
    parser.add_argument("output_dir", type=Path, help="missing or empty directory")
    parser.add_argument(
        "--source",
        type=Path,
        required=True,
        help="data/ of a Kartograf store holding " + ", ".join(SOURCES.values()),
    )
    args = parser.parse_args(argv)
    output_dir = cast(Path, args.output_dir).absolute()
    repository = Path(__file__).resolve().parents[2]
    if output_dir.resolve().is_relative_to(repository):
        parser.error(f"refusing to write test data into the repository: {output_dir}")
    started = time.perf_counter()
    try:
        store = make_preview_store(output_dir, source=cast(Path, args.source))
    except StoreFixtureError as exc:
        parser.error(str(exc))
    # Each file once: versions (the standard paths are their hard links), sidecars.
    sizes = Counter[str]()
    for top, _, names in os.walk(store.root):
        segment = "/".join(Path(top).relative_to(store.root).parts[:2])
        for name in names:
            info = os.lstat(os.path.join(top, name))
            if info.st_nlink == 1 or "versions" in Path(top).parts:
                sizes[segment] += info.st_size
    print(f"store: {store.root}")
    print(f"orthophoto: {store.ortho}")
    print(
        f"ASC sheets: {len(store.asc_year)} of 2025, {len(store.asc_singles)} of 2024"
    )
    print(
        f"SM5 sheets: {len(store.sm5_year)} of 2024, {len(store.sm5_singles)} of 2023"
        f" at {SM5_PIXEL_M} m; real: {store.sm5_sheet}"
    )
    print(f"map year: {len(store.map_year)} sheets of 1:10 000")
    print(
        "size: "
        + ", ".join(
            f"{name} {size / 10**6:.0f} MB" for name, size in sorted(sizes.items())
        )
    )
    print(f"time: {time.perf_counter() - started:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
