"""Build the Archiwista mockup fixtures ``orto.json`` and ``bdot10k.json``.

Kartograf has no availability report for the orthophotomap nor for BDOT10k,
so this script assembles one for the fixed Krakow area from the public GUGiK
indexes, using the Kartograf libraries (sheet grids, sheet frames, the WMS
sheet-index client and parser, PRG powiat discovery, BDOT10k URL templates of
the source registry). It never downloads a data file: only index queries
(WMS GetCapabilities/GetFeatureInfo, PRG WFS GetFeature) and ``HEAD`` of the
BDOT10k packages, at most four requests in parallel.

Run from the Kartograf repository root (its ``.venv``), before
``build_fixtures.py`` (which adds the orthophoto sheet frames)::

    .venv/bin/python <Archiwista>/mockup/tools/build_orto_bdot.py

The JSON files are written to ``mockup/data/availability/``.
"""

from __future__ import annotations

import json
import math
import shlex
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime
from pathlib import Path

import numpy as np
import requests
from rasterio.features import rasterize
from rasterio.transform import from_origin

from kartograf.core.coverage import rectangle
from kartograf.core.parser_2000 import SCALE_HIERARCHY_2000
from kartograf.core.sheet_parser import (
    BBox,
    SheetParser,
    find_sheets_for_bbox,
    series_scale,
)
from kartograf.download.campaigns import record_year
from kartograf.providers.pl.bdot10k import Bdot10kProvider
from kartograf.providers.pl.gugik_orto import ORTO_KEY, GugikOrtoProvider
from kartograf.providers.pl.prg import (
    POWIAT_LAYER,
    PRG_WFS_ENDPOINT,
    discover_teryts_for_bbox,
)
from kartograf.providers.pl.skorowidz import (
    SkorowidzLayersMixin,
    SkorowidzRecord,
    query_skorowidz_layer,
)
from kartograf.providers.pl.skorowidz_wfs import overlaps_area, sheet_frame_2180
from kartograf.sources.descriptor import UnitPackageParams
from kartograf.sources.registry import get_source
from kartograf.sources.variants import resolution_label
from kartograf.transport.http import SessionPerThread, make_gugik_session
from kartograf.transport.unit_package import package_url

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "availability"
BBOX = BBox(561000.0, 239000.0, 573000.0, 249000.0, "EPSG:2180")
BBOX_TEXT = "561000,239000,573000,249000"
AREA = rectangle(BBOX.min_x, BBOX.min_y, BBOX.max_x, BBOX.max_y)
AREA_M2 = (BBOX.max_x - BBOX.min_x) * (BBOX.max_y - BBOX.min_y)
WORKERS = 4  # GUGiK services: at most four parallel requests
TIMEOUT = 60
STRIP_PX = 4_000_000  # pixels per raster strip of the 1 m coverage grid
HORIZONTAL = {"1992": "PL-1992", "2000": "PL-2000"}
COLOR_ORDER = {"RGB": 0, "CIR": 1, "B/W": 2}
# The PL-1992 orthophotomap series of Kartograf (registry: sheet_parts=7).
PL1992_SCALE = series_scale(7)
PL1992_SCALES = SheetParser.SCALE_HIERARCHY
INDEX_LABEL = "SkorowidzeOrtofotomapy"

_sessions = SessionPerThread(None)


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _write_json(name: str, payload: dict) -> Path:
    path = OUT_DIR / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path


# =============================================================================
# Orthophotomap
# =============================================================================


@dataclass(frozen=True)
class Member:
    """A record of the area with its parsed sheet."""

    record: SkorowidzRecord
    year: int
    scale: str
    color: str
    label: str
    file_format: str


class OrtoIndex:
    """Every record of the orthophotomap WMS index around the area."""

    def __init__(self) -> None:
        self.provider = GugikOrtoProvider(color=GugikOrtoProvider.DEFAULT_COLOR)
        self.endpoint = self.provider.WMS_INDEX_ENDPOINT
        # Yearly index layers from GetCapabilities, the Kartograf discovery.
        self.layers = self.provider._layers(self.endpoint, TIMEOUT)
        self.records: dict[str, SkorowidzRecord] = {}
        self.queried: set[str] = set()
        self.requests = 0

    def _query(self, sheet: str) -> list[SkorowidzRecord]:
        """All layers at the centre of one sheet (one GetFeatureInfo)."""
        parser = SheetParser(sheet)
        return query_skorowidz_layer(
            _sessions.get(),
            self.endpoint,
            ",".join(self.layers),
            query_bbox=SkorowidzLayersMixin._query_bbox(parser),
            sheet=parser.sheet,
            timeout=TIMEOUT,
            label=INDEX_LABEL,
        )

    def query_sheets(self, sheets: list[str]) -> None:
        todo = [s for s in sheets if s not in self.queried]
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for records in pool.map(self._query, todo):
                for record in records:
                    self.records.setdefault(record.url, record)
        self.queried.update(todo)
        self.requests += len(todo)


def _rank(system: str, scale: str) -> int:
    order = PL1992_SCALES if system == "1992" else SCALE_HIERARCHY_2000
    return order.index(scale)


def collect_orto() -> tuple[OrtoIndex, list[tuple[str, str]]]:
    """Query the index at the centre of every grid sheet of the area.

    Start with the PL-1992 series of Kartograf and the PL-2000 1:2000 grid
    (the usual GUGiK PL-2000 module); when records of a finer sheet level
    appear, query the centres of that finer grid as well, so every sheet of
    every level found contains at least one query point.
    """
    index = OrtoIndex()
    finest = {"1992": PL1992_SCALE, "2000": "1:2000"}
    grids = [("1992", PL1992_SCALE), ("2000", "1:2000")]
    queried_grids: list[tuple[str, str]] = []
    while grids:
        for system, scale in grids:
            index.query_sheets(find_sheets_for_bbox(BBOX, scale, system))
            queried_grids.append((system, scale))
        grids = []
        for record in index.records.values():
            system = SheetParser(record.sheet).sheet_system
            scale = SheetParser(record.sheet).scale
            if _rank(system, scale) > _rank(system, finest[system]):
                finest[system] = scale
                grids.append((system, scale))
        grids = sorted(set(grids))
    return index, queried_grids


_FRAMES: dict[str, tuple] = {}


def frame(sheet: str) -> tuple:
    if sheet not in _FRAMES:
        _FRAMES[sheet] = sheet_frame_2180(sheet)
    return _FRAMES[sheet]


def classify(
    records: list[SkorowidzRecord],
) -> tuple[list[Member], dict[str, dict]]:
    """Records of the area: members of combinations and unsupported ones.

    A record belongs to the area when its sheet frame overlaps the bbox by
    more than the edge sliver (``overlaps_area``, as in the Kartograf
    availability report). It is unsupported when Kartograf cannot download
    it by the sheet grid: a PL-1992 code outside the 7-part series, no CRS or
    pixel, a CRS other than the system of its code, no year.
    """
    members: list[Member] = []
    unsupported: dict[str, dict] = {}

    def reject(reason: str, record: SkorowidzRecord) -> None:
        entry = unsupported.setdefault(
            reason, {"records": 0, "sheets": set(), "years": set()}
        )
        entry["records"] += 1
        entry["sheets"].add(record.sheet)
        entry["years"].add(record.raw.get("aktualnoscRok") or record.aktualnosc[:4])

    for record in records:
        if not overlaps_area(frame(record.sheet), AREA):
            continue
        parser = SheetParser(record.sheet)
        year = record_year(record)
        if record.system is None or record.resolution_m is None or year is None:
            reject("record without a CRS, pixel or year", record)
            continue
        if record.system != parser.sheet_system or (
            record.system == "2000" and record.zone != int(record.sheet.split(".")[0])
        ):
            reject("declared CRS differs from the system of the sheet code", record)
            continue
        if parser.sheet_system == "1992" and parser.scale != PL1992_SCALE:
            reject(
                f"PL-1992 sheet of scale {parser.scale} outside the Kartograf "
                f"orthophotomap series {PL1992_SCALE} (7-part codes); a coarser "
                "code expands to 7-part sheets, so these files are not downloadable",
                record,
            )
            continue
        suffix = Path(record.url).suffix.lstrip(".").upper()
        members.append(
            Member(
                record=record,
                year=year,
                scale=parser.scale,
                color=record.raw.get("kolor") or "?",
                label=resolution_label(Decimal(str(record.resolution_m))),
                file_format="TIF" if suffix in ("TIF", "TIFF") else suffix,
            )
        )
    return members, unsupported


def _campaign_key(record: SkorowidzRecord) -> tuple[str, str, str]:
    # Kartograf's campaign order (newest first): aktualnosc, dt_pzgik, url.
    return (record.aktualnosc, record.dt_pzgik or "", record.url)


def _span(values: list[str]) -> list[str] | None:
    present = sorted(v for v in values if v)
    return [present[0], present[-1]] if present else None


def _shapes(frames: set[tuple]) -> list[dict]:
    return [
        {"type": "Polygon", "coordinates": [[*map(list, f), list(f[0])]]}
        for f in frames
    ]


def _covered(geometries: list[dict], shape: tuple[int, int], transform) -> int:
    """Pixels of the strip whose centre lies in any of ``geometries``."""
    if not geometries:
        return 0
    burnt = rasterize(
        [(g, 1) for g in geometries],
        out_shape=shape,
        transform=transform,
        fill=0,
        all_touched=False,
        dtype=np.uint8,
    )
    return int(np.count_nonzero(burnt))


def measure_coverage(groups: list[list[Member]]) -> list[tuple[int, int]]:
    """``(uncovered_px, full_px)`` per group on the 1 m grid of the bbox:
    pixels (1 m2) outside the frames of the group's sheets, and pixels inside
    the frames of sheets with a full record of the group.

    Same grid rule as the Kartograf availability report: 1 m pixels aligned
    to the bbox, a pixel counts by its centre, row strips of 4 Mpx.
    """
    x0, y1 = math.floor(BBOX.min_x), math.ceil(BBOX.max_y)
    width = math.ceil(BBOX.max_x) - x0
    height = y1 - math.floor(BBOX.min_y)
    rows = max(1, STRIP_PX // width)
    every = [_shapes({frame(m.record.sheet) for m in group}) for group in groups]
    full = [
        _shapes({frame(m.record.sheet) for m in group if m.record.full_sheet is True})
        for group in groups
    ]
    uncovered = [0] * len(groups)
    full_px = [0] * len(groups)
    for top in range(0, height, rows):
        shape = (min(rows, height - top), width)
        transform = from_origin(x0, y1 - top, 1.0, 1.0)
        for i in range(len(groups)):
            uncovered[i] += shape[0] * shape[1] - _covered(every[i], shape, transform)
            full_px[i] += _covered(full[i], shape, transform)
    return list(zip(uncovered, full_px, strict=True))


def sheet_record(rows: list[SkorowidzRecord]) -> dict:
    """The record of a sheet that ``--year`` fetches within the combination:
    the newest full one, else the newest (order: date, published, url)."""
    full_rows = [r for r in rows if r.full_sheet is True]
    chosen = max(full_rows or rows, key=_campaign_key)
    return {
        "campaign": chosen.raw.get("numerZgloszeniaPracy") or None,
        "date": chosen.aktualnosc,
        "full": chosen.full_sheet is True,
        "records": len(rows),
    }


def _grid_selection(system: str, scale: str) -> frozenset[str]:
    """Sheets a ``--bbox`` download of this system and scale plans."""
    return frozenset(find_sheets_for_bbox(BBOX, scale, sheet_system=system))


def _scale_rank(system: str, scale: str) -> int:
    return _rank(system, scale)


def _picked(
    rows: list[SkorowidzRecord], *, full_sheet: bool, all_campaigns: bool
) -> list[SkorowidzRecord]:
    """Records ``imagery download --year`` fetches for one sheet (rows: the
    RGB records of the sheet and year, any pixel - orto has no pixel filter)."""
    ordered = sorted(rows, key=_campaign_key, reverse=True)
    if all_campaigns:
        return ordered
    picked = [ordered[0]]
    if full_sheet and ordered[0].full_sheet is not True:
        picked += [r for r in ordered if r.full_sheet is True][:1]
    return picked


def download_hint(
    system: str,
    year: int,
    group: list[Member],
    rgb_year_rows: dict[str, list[SkorowidzRecord]],
) -> list[str]:
    """``imagery download`` commands of an RGB combination (no ``kartograf ``
    prefix, no ``--output``), built by the rules of the Kartograf report.

    Area: one ``--bbox`` command per scale when the sheets that download plans
    are all sheets of the combination, else one ``--sheet`` command per sheet.
    Flags: ``--year``; ``--full-sheet`` when a sheet's newest record of the
    combination is partial while a full one exists; ``--all-campaigns`` when
    the newest RGB flight of the year on some sheet (any pixel) is not a
    record of the combination, so the plain command would fetch another pixel.
    """
    by_sheet: dict[str, list[SkorowidzRecord]] = defaultdict(list)
    for member in group:
        by_sheet[member.record.sheet].append(member.record)
    flags = ["--year", str(year)]
    full_sheet = any(
        max(rows, key=_campaign_key).full_sheet is not True
        and any(r.full_sheet is True for r in rows)
        for rows in by_sheet.values()
    )
    if full_sheet:
        flags.append("--full-sheet")
    reachable = all(
        {r.url for r in rows}
        & {
            r.url
            for r in _picked(
                rgb_year_rows[sheet], full_sheet=full_sheet, all_campaigns=False
            )
        }
        for sheet, rows in by_sheet.items()
    )
    if not reachable:
        flags.append("--all-campaigns")
    base = ["--country", "pl", "--bbox", BBOX_TEXT, "--sheet-system", system]
    scales = sorted({SheetParser(s).scale for s in by_sheet}, key=lambda s: _scale_rank(system, s))
    areas: list[list[str]] = []
    for scale in scales:
        own = sorted(s for s in by_sheet if SheetParser(s).scale == scale)
        if _grid_selection(system, scale) <= set(own):
            areas.append(base + (["--scale", scale] if system == "2000" else []))
        else:
            areas.extend(["--sheet", sheet] for sheet in own)
    return [
        shlex.join(["imagery", "download", "--product", "orto", *area, *flags])
        for area in areas
    ]


def build_orto() -> dict:
    started = time.monotonic()
    checked_at = _iso_now()
    index, grids = collect_orto()
    members, unsupported = classify(list(index.records.values()))

    groups: dict[tuple, list[Member]] = defaultdict(list)
    rgb_year_rows: dict[tuple, dict[str, list[SkorowidzRecord]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for member in members:
        record = member.record
        groups[
            (member.year, record.system, member.label, member.color, member.file_format)
        ].append(member)
        if member.color == GugikOrtoProvider.DEFAULT_COLOR:
            rgb_year_rows[(member.year, record.system)][record.sheet].append(record)

    keys = sorted(
        groups,
        key=lambda k: (-k[0], k[1], Decimal(k[2][:-1]), COLOR_ORDER.get(k[3], 9), k[4]),
    )
    coverage = measure_coverage([groups[k] for k in keys])

    combinations = []
    for key, (missing_px, full_px) in zip(keys, coverage, strict=True):
        year, system, label, color, file_format = key
        group = groups[key]
        by_sheet: dict[str, list[SkorowidzRecord]] = defaultdict(list)
        for member in group:
            by_sheet[member.record.sheet].append(member.record)
        full = sorted(
            s for s, rows in by_sheet.items() if any(r.full_sheet is True for r in rows)
        )
        partial = sorted(s for s in by_sheet if s not in full)
        records = [m.record for m in group]
        sizes = [r.raw.get("rozmiarPlikuMB") for r in records]
        hint = (
            download_hint(system, year, group, rgb_year_rows[(year, system)])
            if color == GugikOrtoProvider.DEFAULT_COLOR
            else []
        )
        sheet_records = {s: sheet_record(by_sheet[s]) for s in sorted(by_sheet)}
        combinations.append(
            {
                "country": "PL",
                "product": "orto",
                "source": ORTO_KEY,
                "year": year,
                "acquisition_dates": _span([r.aktualnosc for r in records]),
                "published": _span([r.dt_pzgik or "" for r in records]),
                "campaigns": sorted(
                    {
                        r.raw["numerZgloszeniaPracy"]
                        for r in records
                        if r.raw.get("numerZgloszeniaPracy")
                    }
                ),
                "horizontal": HORIZONTAL[system],
                "resolution": label,
                "color": color,
                "vertical_crs": None,
                "format": file_format,
                "densities": [],
                "complete": missing_px == 0 and not partial,
                "sheets_full": full,
                "sheets_partial": partial,
                "sheets_missing": [],
                "uncovered": missing_px > 0,
                "uncovered_m2": float(missing_px),
                "full_m2": float(full_px),
                "size_bytes": None,
                "files": len(records),
                "index_size_mb": (
                    sum(int(s) for s in sizes)
                    if all(s and s.isdigit() for s in sizes)
                    else None
                ),
                "download_hint": hint,
                "sheet_records": sheet_records,
                "campaigns_selected": sorted(
                    {
                        sheet_records[s]["campaign"]
                        for s in full
                        if sheet_records[s]["campaign"]
                    }
                ),
            }
        )

    notices = [
        {
            "level": "info",
            "code": "index_unsupported",
            "text": (
                f"{info['records']} index records of {len(info['sheets'])} sheets "
                f"(years {', '.join(sorted(info['years']))}; e.g. "
                f"{', '.join(sorted(info['sheets'])[:3])}) are not combinations: "
                f"{reason}"
            ),
        }
        for reason, info in sorted(unsupported.items())
    ]
    elapsed = time.monotonic() - started
    note = (
        f"Built by tools/build_orto_bdot.py on {checked_at} in {elapsed:.0f} s "
        f"from the GUGiK orthophotomap WMS sheet index {index.endpoint} "
        f"(layers {', '.join(index.layers)} from GetCapabilities; one "
        "GetFeatureInfo with all layers at the centre of every grid sheet of "
        "the bbox: "
        + ", ".join(
            f"PL-{s} {sc} ({len(find_sheets_for_bbox(BBOX, sc, s))})" for s, sc in grids
        )
        + f"; {index.requests} requests, {len(index.records)} distinct records, "
        "parsed by Kartograf's query_skorowidz_layer). Every colour variant of "
        "the index (RGB, CIR, B/W) is listed; Kartograf's CLI downloads only "
        "RGB (image_provider uses color=RGB), so CIR and B/W have no "
        "download_hint. Key = (year of aktualnoscRok, PL-1992/PL-2000, "
        "wielkoscPiksela label, kolor, file format). A record belongs to the "
        "area when its sheet frame overlaps the bbox by more than 1 m "
        "(overlaps_area). sheets_full/sheets_partial from the index flag "
        "calyArkuszWyeplnionyTrescia (TAK/NIE). uncovered_m2 = 1 m pixels of "
        "the bbox outside the frames (sheet_frame_2180, PL-2000 zone frames "
        "transformed to EPSG:2180) of the combination's sheets, measured by "
        "pixel centre; the whole bbox is land, no PRG land mask is applied. "
        "complete = uncovered_m2 == 0 and no partial-only sheet. full_m2 = 1 m "
        "pixels of the bbox inside the frames of sheets with a full record of "
        "the combination. sheet_records = per sheet the record --year fetches "
        "within the combination (newest full, else newest; order date, "
        "published, url) and the number of its records there; "
        "campaigns_selected = distinct campaigns of sheet_records of the "
        "sheets_full. size_bytes "
        "is null (no HEAD of image files); index_size_mb = sum of the index "
        "field rozmiarPlikuMB over the combination's files. download_hint: the "
        "orthophotomap has no pixel filter, so a hint adds --all-campaigns when "
        "the newest RGB flight of the year on a sheet has another pixel. A "
        "partial record whose footprint misses every query point would not be "
        "found (same limitation as Kartograf's sheet-centre lookup)."
    )
    return {
        "schema": "archiwista-mockup-orto/1",
        "note": note,
        "request": {
            "product": "orto",
            "country": "pl",
            "bbox": [BBOX.min_x, BBOX.min_y, BBOX.max_x, BBOX.max_y],
            "bbox_crs": BBOX.crs,
        },
        "checked_at": checked_at,
        "areas": [
            {
                "country": "PL",
                "crs": "EPSG:2180",
                "bounds": [BBOX.min_x, BBOX.min_y, BBOX.max_x, BBOX.max_y],
                "area_m2": AREA_M2,
                "land_m2": AREA_M2,
            }
        ],
        "combinations": combinations,
        "notices": notices,
        "ok": True,
    }


# =============================================================================
# BDOT10k
# =============================================================================

_MS = "{http://mapserver.gis.umn.edu/mapserver}"


def powiat_names(session: requests.Session) -> dict[str, str]:
    """Names of the powiats of the bbox (PRG WFS, attribute JPT_NAZWA_)."""
    response = session.get(
        PRG_WFS_ENDPOINT,
        params={
            "SERVICE": "WFS",
            "VERSION": "2.0.0",
            "REQUEST": "GetFeature",
            "TYPENAMES": POWIAT_LAYER,
            "PROPERTYNAME": "JPT_KOD_JE,JPT_NAZWA_",
            "BBOX": (
                f"{BBOX.min_y:.0f},{BBOX.min_x:.0f},{BBOX.max_y:.0f},{BBOX.max_x:.0f},"
                "urn:ogc:def:crs:EPSG::2180"
            ),
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    root = ET.fromstring(response.content)
    names = {}
    for feature in root.iter(f"{_MS}A02_Granice_powiatow"):
        code = feature.findtext(f"{_MS}JPT_KOD_JE")
        name = feature.findtext(f"{_MS}JPT_NAZWA_")
        if code and name:
            names[code.strip()] = name.strip()
    return names


def head(url: str) -> dict:
    """One ``HEAD`` (a second one after any failure other than 404)."""
    error = None
    for _ in range(2):
        try:
            response = _sessions.get().head(url, timeout=TIMEOUT, allow_redirects=True)
        except requests.RequestException as exc:
            error = f"{type(exc).__name__}: {exc}"
            continue
        if response.status_code == 404:
            return {"exists": False, "size_bytes": None, "last_modified": None, "url": url}
        if response.status_code == 200:
            length = response.headers.get("Content-Length", "")
            modified = response.headers.get("Last-Modified")
            return {
                "exists": True,
                "size_bytes": int(length) if length.isdigit() else None,
                "last_modified": (
                    parsedate_to_datetime(modified).date().isoformat()
                    if modified
                    else None
                ),
                "url": url,
            }
        error = f"HTTP {response.status_code}"
    return {
        "exists": None,
        "size_bytes": None,
        "last_modified": None,
        "url": url,
        "error": error,
    }


def build_bdot10k() -> dict:
    started = time.monotonic()
    checked_at = _iso_now()
    session = make_gugik_session()
    # The Kartograf discovery of `landcover download --product bdot10k --bbox`
    # (Bdot10kProvider.teryts_for_area): powiats of PRG intersecting the bbox.
    teryts = discover_teryts_for_bbox(BBOX, session=session, cache=None, timeout=30)
    names = powiat_names(session)

    current = {
        teryt: Bdot10kProvider.OPENDATA_PATTERNS["GPKG"].format(
            base=Bdot10kProvider.OPENDATA_BASE, woj=teryt[:2], teryt=teryt
        )
        for teryt in teryts
    }
    archive = next(
        channel.params
        for channel in get_source("pl.gugik.bdot10k").channels
        if isinstance(channel.params, UnitPackageParams)
    )
    releases: list[tuple[int, str, dict[str, str]]] = []
    for variant in archive.variants:
        choice = dict(variant.choice)
        releases.append(
            (
                int(choice["year"]),
                choice["format"],
                {t: package_url(variant, teryt=t) for t in teryts},
            )
        )
    format_order = {"GML": 0, "SHP": 1}
    releases.sort(key=lambda r: (-r[0], format_order.get(r[1], 9)))

    urls = list(current.values()) + [u for _, _, m in releases for u in m.values()]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        heads = dict(zip(urls, pool.map(head, urls), strict=True))
    dated = sum(1 for h in heads.values() if h["last_modified"] is not None)
    found = sum(1 for h in heads.values() if h["exists"] is True)
    elapsed = time.monotonic() - started
    note = (
        f"Built by tools/build_orto_bdot.py on {checked_at} in {elapsed:.0f} s. "
        "Powiats: PRG WFS A02_Granice_powiatow intersecting the bbox "
        "(Kartograf discover_teryts_for_bbox, the method of landcover download "
        "--bbox; names from JPT_NAZWA_ of the same service). Current package: "
        "the GPKG URL of Bdot10kProvider (schemat2021); releases: the archive "
        "variants of the registry (pl.gugik.bdot10k, years 2014-2025, GML and "
        f"SHP). {len(urls)} files checked with one HEAD each (a second HEAD after "
        "a failure other than 404; 404 = exists:false, a repeated failure = "
        "exists:null with error); no file was downloaded. last_modified = date "
        "of the HTTP Last-Modified header, null when the server sends none "
        f"({found} files found, {dated} of them with Last-Modified in this run)."
    )
    return {
        "schema": "archiwista-mockup-bdot10k/1",
        "note": note,
        "request": {
            "product": "bdot10k",
            "country": "pl",
            "bbox": [BBOX.min_x, BBOX.min_y, BBOX.max_x, BBOX.max_y],
            "bbox_crs": BBOX.crs,
        },
        "checked_at": checked_at,
        "units": [{"teryt": t, "name": names.get(t)} for t in teryts],
        "current": {
            "format": "GPKG",
            "units": {t: heads[url] for t, url in current.items()},
        },
        "releases": [
            {
                "year": year,
                "format": fmt,
                "units": {t: heads[url] for t, url in by_unit.items()},
            }
            for year, fmt, by_unit in releases
        ],
        "download_hint": {
            "current": f"landcover download --product bdot10k --bbox {BBOX_TEXT}",
            "release": (
                f"landcover download --product bdot10k --bbox {BBOX_TEXT} "
                "--year {year} --format {format}"
            ),
        },
    }


def main() -> None:
    for name, build in (("orto.json", build_orto), ("bdot10k.json", build_bdot10k)):
        started = time.monotonic()
        path = _write_json(name, build())
        print(f"{path} ({time.monotonic() - started:.1f} s)")


if __name__ == "__main__":
    main()
