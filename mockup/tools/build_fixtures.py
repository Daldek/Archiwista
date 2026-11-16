"""Build the static fixtures of the Archiwista mockup from Kartograf 0.8.x.

The mockup is a static page; every number it shows comes from the JSON files
written here. Run from the Kartograf repository root with its virtualenv (the
metadata cache ``.kartograf_cache.db`` stays there, no data file is
downloaded):

    cd <Kartograf>
    .venv/bin/python <Archiwista>/mockup/tools/build_fixtures.py

Outputs under ``mockup/data``:

- ``availability/{nmt,nmpt,laz}.json``: ``check_availability(...).to_json()``,
  byte for byte what ``kartograf elevation availability --json`` prints;
- ``derived/{nmt,nmpt,laz}.json``: per combination (report order) the fields
  the Archiwista spec proposes for Kartograf - ``full_m2`` (land inside the
  frames of full sheets: ``land_m2`` minus Kartograf's own ``missing`` pixels)
  and the index record each sheet would be downloaded from (campaign, flight
  date, full flag). Computed with the report's private steps on the same
  cached index answer, so they match the report exactly;
- ``derived/sheets.json``: the frame of every sheet code of the reports (and of
  ``availability/orto.json`` when present) in EPSG:4326 (map) and EPSG:2180
  (fan view), from ``SheetParser`` - 9-part LAZ tiles are the 2 x 2 x 2 x 2
  split of their 7-part sheet (1 = NW, 2 = NE, 3 = SW, 4 = SE);
- ``area.json``: the demo area;
- ``previews/{nmt_relief,orto}.jpg``: GUGiK WMS renders of the area (EPSG:2180).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import requests
from pyproj import Transformer

from kartograf import BBox, SheetParser, check_availability
from kartograf.cache.defaults import open_cache
from kartograf.download import availability as av
from kartograf.notices import NoticeSink
from kartograf.transport.http import SessionPerThread

AREA_NAME = "Kraków — śródmieście i okolice"
AREA_BBOX = (561000.0, 239000.0, 573000.0, 249000.0)  # EPSG:2180
PRODUCTS = ("nmt", "nmpt", "laz")
DATA = Path(__file__).resolve().parents[1] / "data"
PREVIEW_PX = (1440, 1200)  # width x height, the area is 12 x 10 km
PREVIEWS = {
    "nmt_relief.jpg": "https://mapy.geoportal.gov.pl/wss/service/PZGIK/NMT/GRID1/WMS/ShadedRelief",
    "orto.jpg": "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardResolution",
}
_TO_4326: dict[str, Transformer] = {}


def _transformer(src: str, dst: str) -> Transformer:
    key = f"{src}>{dst}"
    if key not in _TO_4326:
        _TO_4326[key] = Transformer.from_crs(src, dst, always_xy=True)
    return _TO_4326[key]


def _rect(w: float, s: float, e: float, n: float) -> list[tuple[float, float]]:
    """Corners clockwise from the north-west one."""
    return [(w, n), (e, n), (e, s), (w, s)]


def sheet_rings(code: str) -> dict:
    """Frame of a sheet code in EPSG:4326 and EPSG:2180 (4 corners each)."""
    if "." in code:  # PL-2000: a rectangle in the zone CRS
        native = SheetParser(code).get_bbox()
        corners = _rect(native.min_x, native.min_y, native.max_x, native.max_y)
        to_wgs = _transformer(native.crs, "EPSG:4326")
        to_92 = _transformer(native.crs, "EPSG:2180")
        ring4326 = [to_wgs.transform(x, y) for x, y in corners]
        ring2180 = [to_92.transform(x, y) for x, y in corners]
        system = "2000"
    else:
        parts = code.split("-")
        base = "-".join(parts[:7]) if len(parts) == 9 else code
        frame = SheetParser(base).get_bbox("EPSG:4326")
        w, s, e, n = frame.min_x, frame.min_y, frame.max_x, frame.max_y
        for quarter in parts[7:] if len(parts) == 9 else ():
            q = int(quarter)
            mid_x, mid_y = (w + e) / 2, (s + n) / 2
            w, e = (w, mid_x) if q in (1, 3) else (mid_x, e)
            s, n = (mid_y, n) if q in (1, 2) else (s, mid_y)
        ring4326 = _rect(w, s, e, n)
        to_92 = _transformer("EPSG:4326", "EPSG:2180")
        ring2180 = [to_92.transform(x, y) for x, y in ring4326]
        system = "1992"
    return {
        "system": system,
        "ring4326": [[round(x, 7), round(y, 7)] for x, y in ring4326],
        "ring2180": [[round(x, 2), round(y, 2)] for x, y in ring2180],
    }


def _selected(rows: list[av._Entry]) -> av._Entry:
    """The record a ``--year`` download takes for a sheet: the newest full
    record of the combination, else its newest record."""
    full = [r for r in rows if r.full is True]
    return max(full or rows, key=lambda r: (r.date, r.published or "", r.url))


def derived(product: str, report) -> dict:
    """``full_m2`` and the selected record per sheet of every combination."""
    bbox = BBox(*AREA_BBOX, "EPSG:2180")
    request = av._validated(product, "pl", None, bbox, None, None, None, None, None)
    parts = av._parts(request, None, NoticeSink(None))
    areas = parts.pl
    assert areas is not None  # a PL bbox request always has a PL part
    sessions = SessionPerThread(None)
    with open_cache(True, force=False) as metadata:
        envelope = av.area_envelope(areas)
        answers = []
        for service in av._services(product):
            types = av._feature_types(service, sessions, metadata)
            answers.append(
                (service, av._index_entries(service, types, envelope, sessions, metadata))
            )
        mask = av._land_mask(envelope, sessions, metadata)
    groups, _ = av._group(product, answers, areas)
    _, land_px, measured = av._measure(areas, envelope, mask, groups, sheet_frame=False)
    if len(groups) != len(report.combinations):
        sys.exit(f"{product}: {len(groups)} groups vs {len(report.combinations)} combinations")
    out = []
    for group, (missing, uncovered), comb in zip(
        groups, measured, report.combinations, strict=True
    ):
        key = (group.year, av._HORIZONTAL[group.system], group.variant.source, group.vertical_crs)
        if key != (comb.year, comb.horizontal, comb.source, comb.vertical_crs):
            sys.exit(f"{product}: order mismatch {key} vs {comb}")
        if (missing == 0) != comb.complete or float(uncovered) != comb.uncovered_m2:
            sys.exit(f"{product}: measurement mismatch for {key}")
        by_sheet: dict[str, list] = {}
        for entry in group.entries:
            by_sheet.setdefault(entry.sheet, []).append(entry)
        records = {}
        for sheet, rows in sorted(by_sheet.items()):
            chosen = _selected(rows)
            records[sheet] = {
                "campaign": chosen.campaign,
                "date": chosen.date,
                "full": chosen.full is True,
                "records": len(rows),
            }
        selected = sorted(
            {records[s]["campaign"] for s in comb.sheets_full if records[s]["campaign"]}
        )
        out.append(
            {
                "year": comb.year,
                "horizontal": comb.horizontal,
                "source": comb.source,
                "vertical_crs": comb.vertical_crs,
                "full_m2": float(land_px - missing),
                "campaigns_selected": selected,
                "sheet_records": records,
            }
        )
    return {
        "schema": "archiwista-mockup-derived/1",
        "note": (
            "Pola proponowane dla Kartografa (SPEC 12): full_m2 = land_m2 - piksele "
            "ladu poza ramami pelnych arkuszy (pomiar _measure raportu); "
            "sheet_records = rekord skorowidza, ktory pobierze --year (najnowszy pelny, "
            "inaczej najnowszy); campaigns_selected = kampanie pelnych arkuszy."
        ),
        "product": product,
        "land_m2": float(land_px),
        "combinations": out,
    }


def fetch_previews() -> None:
    """WMS renders of the area in EPSG:2180 (axis order N, E in WMS 1.3.0)."""
    w, s, e, n = AREA_BBOX
    for name, endpoint in PREVIEWS.items():
        params = {
            "SERVICE": "WMS",
            "REQUEST": "GetMap",
            "VERSION": "1.3.0",
            "LAYERS": "Raster",
            "STYLES": "",
            "FORMAT": "image/jpeg",
            "CRS": "EPSG:2180",
            "BBOX": ",".join(f"{v:.15g}" for v in (s, w, n, e)),
            "WIDTH": str(PREVIEW_PX[0]),
            "HEIGHT": str(PREVIEW_PX[1]),
        }
        # The ORTO service answers 404 to a percent-encoded query ("%2C",
        # "%3A") and to "239000.0": the query goes out literally.
        query = "&".join(f"{key}={value}" for key, value in params.items())
        answer = requests.get(f"{endpoint}?{query}", timeout=120)
        answer.raise_for_status()
        if not answer.headers.get("content-type", "").startswith("image/"):
            sys.exit(f"{name}: not an image ({answer.headers.get('content-type')})")
        (DATA / "previews" / name).write_bytes(answer.content)


def main() -> None:
    for sub in ("availability", "derived", "previews"):
        (DATA / sub).mkdir(parents=True, exist_ok=True)
    bbox = BBox(*AREA_BBOX, "EPSG:2180")
    codes: set[str] = set()
    for product in PRODUCTS:
        report = check_availability(product=product, country="pl", bbox=bbox)
        (DATA / "availability" / f"{product}.json").write_text(
            report.to_json(), encoding="utf-8"
        )
        (DATA / "derived" / f"{product}.json").write_text(
            json.dumps(derived(product, report), ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
        for comb in report.combinations:
            codes.update(comb.sheets_full, comb.sheets_partial)
    orto = DATA / "availability" / "orto.json"
    if orto.exists():
        for comb in json.loads(orto.read_text(encoding="utf-8"))["combinations"]:
            codes.update(comb["sheets_full"], comb["sheets_partial"])
    sheets = {code: sheet_rings(code) for code in sorted(codes)}
    (DATA / "derived" / "sheets.json").write_text(
        json.dumps(sheets, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    w, s, e, n = AREA_BBOX
    to_wgs = _transformer("EPSG:2180", "EPSG:4326")
    ring = [to_wgs.transform(x, y) for x, y in _rect(w, s, e, n)]
    area = {
        "name": AREA_NAME,
        "bbox": list(AREA_BBOX),
        "bbox_crs": "EPSG:2180",
        "area_m2": (e - w) * (n - s),
        "ring4326": [[round(x, 7), round(y, 7)] for x, y in ring],
        "previews": {
            "relief": "data/previews/nmt_relief.jpg",
            "orto": "data/previews/orto.jpg",
            "source": "GUGiK WMS (NMT GRID1 ShadedRelief, ORTO StandardResolution)",
        },
    }
    (DATA / "area.json").write_text(
        json.dumps(area, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    fetch_previews()
    print(f"OK: {len(sheets)} arkuszy, dane w {DATA}")


if __name__ == "__main__":
    main()
