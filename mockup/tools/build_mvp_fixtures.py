"""Build the Archiwista mockup fixtures added for the MVP scope (PRD 2026-10-18).

- ``previews/orto_<year>.jpg``: the orthophotomap of the demo area for every
  year of ``availability/orto.json``, from the GUGiK archival orthophoto WMS
  with a time dimension (``StandardResolutionTime``). The service draws only
  at scale denominators up to about 47 000, so the image is requested at
  1200 px and reduced to 480 px.
- ``derived/powiaty.json``: boundaries of the BDOT10k powiats of the area
  (PRG WFS, GML 3.2), simplified for display, in EPSG:2180 and WGS84.
- ``own/kanalizacja.json``: an invented sewer network ("dane przykładowe")
  in the project data folder with its snapshots - no real data.
- ``previews/nmt/<year>-<resolution>-<vertical>/<sheet>.jpg`` and
  ``derived/nmt_tiles.json``: shaded relief of every NMT sheet version in
  a Kartograf store downloaded for the mockup (real files; the store lies
  outside the repository, e.g. ``../archiwista-mockup-data/magazyn``).
  Archiwista builds an elevation year preview from the sheets in the store,
  the same way.

Run from the Kartograf repository root (its ``.venv``); optional arguments
``orto``, ``powiaty``, ``own``, ``nmt`` build only those parts (default:
all; ``nmt`` reads the store given by ``ARCHIWISTA_MOCKUP_STORE``)::

    .venv/bin/python <Archiwista>/mockup/tools/build_mvp_fixtures.py [orto] [powiaty] [own] [nmt]
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import rasterio
import requests
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.io import MemoryFile

DATA = Path(__file__).resolve().parents[1] / "data"
BBOX = (561000.0, 239000.0, 573000.0, 249000.0)  # EPSG:2180, x0 y0 x1 y1
ORTO_TIME_WMS = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardResolutionTime"
PRG_WFS = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/PRG/WFS/AdministrativeBoundaries"
GML = "{http://www.opengis.net/gml/3.2}"
MS = "{http://mapserver.gis.umn.edu/mapserver}"
TIMEOUT = 120
TO_4326 = Transformer.from_crs("EPSG:2180", "EPSG:4326", always_xy=True)


def orto_previews() -> dict[str, str]:
    """One JPEG per orthophoto year; TIME = the latest flight date of that year."""
    report = json.loads((DATA / "availability" / "orto.json").read_text(encoding="utf-8"))
    last: dict[int, str] = {}
    for combo in report["combinations"]:
        dates = [d for d in combo.get("acquisition_dates") or [] if d]
        day = max(dates) if dates else f"{combo['year']}-12-31"
        if day.endswith("-01-01"):  # year precision only: the state at the end of that year
            day = f"{day[:4]}-12-31"
        last[combo["year"]] = max(last.get(combo["year"], day), day)
    out = {}
    x0, y0, x1, y1 = BBOX
    for year in sorted(last):
        params = {
            "SERVICE": "WMS",
            "VERSION": "1.3.0",
            "REQUEST": "GetMap",
            "LAYERS": "Raster",
            "STYLES": "",
            "CRS": "EPSG:2180",
            "BBOX": f"{y0},{x0},{y1},{x1}",  # WMS 1.3.0 + EPSG:2180: (N, E)
            "WIDTH": "1200",
            "HEIGHT": "1000",
            "FORMAT": "image/jpeg",
            "TIME": last[year][:10],
        }
        answer = requests.get(ORTO_TIME_WMS, params=params, timeout=TIMEOUT)
        answer.raise_for_status()
        if not answer.headers.get("Content-Type", "").startswith("image/"):
            raise RuntimeError(f"orto {year}: {answer.text[:200]}")
        with MemoryFile(answer.content) as mem, mem.open() as src:
            pixels = src.read(out_shape=(src.count, 400, 480), resampling=Resampling.average)
        name = f"orto_{year}.jpg"
        with rasterio.open(
            DATA / "previews" / name, "w", driver="JPEG", width=480, height=400,
            count=pixels.shape[0], dtype=pixels.dtype, QUALITY=72,
        ) as dst:
            dst.write(pixels)
        out[str(year)] = f"data/previews/{name}"
        print(f"orto {year} (TIME={last[year][:10]})")
    return out


def _simplify(points: np.ndarray, tolerance: float) -> np.ndarray:
    """Douglas-Peucker of a closed ring, split at the vertex farthest from the start."""
    far = int(np.argmax(np.hypot(*(points - points[0]).T)))
    keep = np.zeros(len(points), dtype=bool)
    keep[0] = keep[far] = keep[-1] = True
    stack = [(0, far), (far, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        seg = points[b] - points[a]
        rel = points[a + 1 : b] - points[a]
        norm = math.hypot(*seg) or 1.0
        dist = np.abs(seg[0] * rel[:, 1] - seg[1] * rel[:, 0]) / norm
        i = int(np.argmax(dist))
        if dist[i] > tolerance:
            keep[a + 1 + i] = True
            stack += [(a, a + 1 + i), (a + 1 + i, b)]
    return points[keep]


def powiaty() -> list[dict]:
    """Powiats intersecting the area, outer rings simplified to 25 m."""
    x0, y0, x1, y1 = BBOX
    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": "ms:A02_Granice_powiatow",
        "BBOX": f"{y0},{x0},{y1},{x1},urn:ogc:def:crs:EPSG::2180",
    }
    answer = requests.get(PRG_WFS, params=params, timeout=TIMEOUT)
    answer.raise_for_status()
    root = ET.fromstring(answer.content)
    out = []
    for feature in root.iter(f"{MS}A02_Granice_powiatow"):
        teryt = feature.findtext(f"{MS}JPT_KOD_JE").strip()
        name = feature.findtext(f"{MS}JPT_NAZWA_").strip()
        rings = []
        for exterior in feature.iter(f"{GML}exterior"):
            values = [float(v) for v in exterior.findtext(f".//{GML}posList").split()]
            pts = np.array(values).reshape(-1, 2)[:, ::-1]  # (N, E) -> (x, y)
            pts = _simplify(pts, 25.0)
            lon, lat = TO_4326.transform(pts[:, 0], pts[:, 1])
            rings.append(
                {
                    "ring2180": [[round(x, 1), round(y, 1)] for x, y in pts],
                    "ring4326": [[round(a, 6), round(b, 6)] for a, b in zip(lon, lat)],
                }
            )
        out.append({"teryt": teryt, "name": name, "rings": rings})
        print(f"powiat {teryt} {name}: {sum(len(r['ring2180']) for r in rings)} pts")
    return sorted(out, key=lambda p: p["teryt"])


# Snapshots of the invented sewer network: label date, author, note.
SNAPSHOTS = [
    ("2025-03-04", "Ola", "inwentaryzacja po przejęciu od gminy"),
    ("2025-06-18", "Ola", "osiedle Kliny — nowe przyłącza"),
    ("2025-09-30", "Marek", "przebudowa kolektora, korekta średnic"),
]
CURRENT_MODIFIED = "2025-10-16T09:41:00"


def kanalizacja() -> dict:
    """Invented sewer lines (EPSG:2180) with the snapshot each line appears in or leaves."""
    rnd = random.Random(20251018)
    feats = []

    def line(start, heading, n, step, stage, kind, dia):
        pts = [start]
        for _ in range(n):
            heading += rnd.uniform(-0.35, 0.35)
            x, y = pts[-1]
            pts.append((x + step * math.cos(heading), y + step * math.sin(heading)))
        feats.append({"pts": pts, "added": stage, "removed": None, "kind": kind, "dia": dia})
        return pts

    # stage 0: main collector and its branches (with sub-branches)
    main = line((566200.0, 241000.0), math.radians(70), 14, 160.0, 0, "ogólnospławna", 1200)
    for i, base in enumerate(main[1:-1]):
        side = 1 if i % 2 else -1
        branch = line(base, math.radians(70 + side * 85), rnd.randint(3, 6), 110.0, 0, "sanitarna", rnd.choice([200, 250, 300]))
        for sub in branch[1:-1:2]:
            line(sub, math.radians(70 + side * 85 + rnd.choice([-80, 80])), rnd.randint(2, 4), 80.0, 0, "sanitarna", 200)
    # stage 1: a new housing estate in the south-west (storm water)
    trunk = line((565350.0, 240350.0), math.radians(20), 6, 120.0, 1, "deszczowa", 600)
    for p in trunk[1:]:
        for turn in (-90, 90):
            line(p, math.radians(20 + turn), rnd.randint(2, 4), 85.0, 1, "deszczowa", rnd.choice([300, 400]))
    # stage 2: the collector rebuilt - some branches leave, new ones arrive
    for f in rnd.sample([f for f in feats if f["added"] == 0 and f["kind"] == "sanitarna"], 4):
        f["removed"] = 2
    for _ in range(5):
        line(rnd.choice(main[2:10]), rnd.uniform(0, 2 * math.pi), rnd.randint(3, 5), 100.0, 2, "sanitarna", 400)
    # after the last snapshot: the working file changed
    for _ in range(3):
        line(rnd.choice(main[8:14]), rnd.uniform(0, 2 * math.pi), rnd.randint(3, 4), 100.0, 3, "deszczowa", 600)

    features = []
    for i, f in enumerate(feats):
        xs, ys = zip(*f["pts"])
        lon, lat = TO_4326.transform(xs, ys)
        features.append(
            {
                "id": i + 1,
                "added": f["added"],
                "removed": f["removed"],
                "kind": f["kind"],
                "dia": f["dia"],
                "line2180": [[round(x, 1), round(y, 1)] for x, y in f["pts"]],
                "line4326": [[round(a, 6), round(b, 6)] for a, b in zip(lon, lat)],
            }
        )

    def state(k):
        live = [f for f in features if f["added"] <= k and (f["removed"] is None or f["removed"] > k)]
        body = json.dumps([[f["id"], f["kind"], f["dia"], f["line2180"]] for f in live]).encode()
        xs = [p[0] for f in live for p in f["line2180"]]
        ys = [p[1] for f in live for p in f["line2180"]]
        return {
            "count": len(live),
            "length_m": round(sum(math.dist(a, b) for f in live for a, b in zip(f["line2180"], f["line2180"][1:]))),
            "sha256": hashlib.sha256(body).hexdigest(),
            "size_bytes": 98_304 + 1_536 * len(live),  # GeoPackage-like size of the invented file
            "extent2180": [min(xs), min(ys), max(xs), max(ys)],
        }

    snapshots = []
    for k, (day, author, note) in enumerate(SNAPSHOTS):
        s = state(k)
        snapshots.append({"index": k, "date": day, "author": author, "note": note, "label": f"{day}_{s['sha256'][:8]}", **s})
    current = {"index": len(SNAPSHOTS), "modified": CURRENT_MODIFIED, **state(len(SNAPSHOTS))}
    return {
        "schema": "archiwista-mockup-own/1",
        "note": "Dane przykładowe wygenerowane skryptem mockupu (tools/build_mvp_fixtures.py) — nie jest to prawdziwa sieć.",
        "project": "Kraków — hydrologia",
        "folder": "<katalog projektu>/dane/",
        "file": "kanalizacja.gpkg",
        "layer": "przewody",
        "crs": "EPSG:2180",
        "geometry": "LineString",
        "schema_fields": [["id", "INTEGER"], ["rodzaj", "TEXT"], ["srednica_mm", "INTEGER"], ["material", "TEXT"], ["rok_budowy", "INTEGER"]],
        "snapshots": snapshots,
        "current": current,
        "features": features,
    }


VCRS = {"EPSG:9651": "EVRF2007", "EPSG:9650": "KRON86"}
TILE_PX = 240  # longest side of a sheet tile


def _hillshade(z: np.ndarray, cell: float) -> np.ndarray:
    """Grey shaded relief (azimuth 315°, altitude 45°, z x5, fixed stretch): the same formula for every sheet and year."""
    dy, dx = np.gradient(z, cell)
    slope = np.arctan(5.0 * np.hypot(dx, dy))
    aspect = np.arctan2(-dx, dy)
    zen, az = math.radians(45.0), math.radians(315.0)
    shade = np.cos(zen) * np.cos(slope) + np.sin(zen) * np.sin(slope) * np.cos(az - aspect)
    return np.clip((shade - 0.3) / 0.7, 0, 1) * 235 + 20


def nmt_tiles(store: Path) -> dict:
    """Shaded-relief tile of every NMT sheet version (ASC) in ``store``, grouped by year, resolution and vertical system."""
    out: dict[str, dict] = {}
    for meta in sorted(store.glob("nmt/*/versions/**/*.asc.meta.json")):
        side = json.loads(meta.read_text(encoding="utf-8"))
        src = side.get("extra", {}).get("source", {})
        year = int(src.get("acquisition_year") or side["request"]["year"])
        sheet = src.get("sheet") or side["request"]["sheet"]
        key = f"{year}-{side['resolution']}-{VCRS.get(side['vertical_crs'], side['vertical_crs'])}"
        with rasterio.open(meta.with_name(meta.name.removesuffix(".meta.json"))) as ds:
            step = max(1, math.ceil(max(ds.width, ds.height) / TILE_PX))
            w, h = math.ceil(ds.width / step), math.ceil(ds.height / step)
            z = ds.read(1, out_shape=(h, w), resampling=Resampling.average, masked=True).astype("float64")
            cell = abs(ds.transform.a) * ds.width / w
            b = ds.bounds
        filled = z.filled(np.nan)
        shade = _hillshade(np.where(np.isnan(filled), np.nanmean(filled), filled), cell)
        shade[np.isnan(filled)] = 230
        rel = Path("previews") / "nmt" / key / f"{sheet}.jpg"
        (DATA / rel).parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(DATA / rel, "w", driver="JPEG", width=w, height=h, count=1, dtype="uint8", QUALITY=78) as dst:
            dst.write(shade.astype("uint8"), 1)
        out.setdefault(key, {})[sheet] = {"href": f"data/{rel.as_posix()}", "bbox2180": [round(b.left, 1), round(b.bottom, 1), round(b.right, 1), round(b.top, 1)]}
    for key, sheets in sorted(out.items()):
        print(f"nmt {key}: {len(sheets)} arkuszy")
    return out


def main() -> None:
    import sys

    parts = set(sys.argv[1:]) or {"orto", "powiaty", "own", "nmt"}
    built = datetime.now(UTC).isoformat(timespec="seconds")
    if "orto" in parts:
        previews = orto_previews()
        (DATA / "derived" / "orto_years.json").write_text(
            json.dumps({"built": built, "source": ORTO_TIME_WMS, "previews": previews}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
    if "powiaty" in parts:
        (DATA / "derived" / "powiaty.json").write_text(
            json.dumps({"built": built, "source": PRG_WFS, "powiaty": powiaty()}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    if "nmt" in parts:
        import os

        store = Path(os.environ.get("ARCHIWISTA_MOCKUP_STORE", "../archiwista-mockup-data/magazyn")).resolve()
        (DATA / "derived" / "nmt_tiles.json").write_text(
            json.dumps({"built": built, "source": "pliki arkuszy NMT pobrane Kartografem (magazyn mockupu)", "tiles": nmt_tiles(store)}, ensure_ascii=False, indent=1)
            + "\n",
            encoding="utf-8",
        )
    if "own" not in parts:
        return
    (DATA / "own").mkdir(exist_ok=True)
    own = kanalizacja()
    (DATA / "own" / "kanalizacja.json").write_text(json.dumps({"built": built, **own}, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"kanalizacja: {[s['count'] for s in own['snapshots']]} -> {own['current']['count']}")


if __name__ == "__main__":
    main()
