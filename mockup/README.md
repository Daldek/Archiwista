# Archiwista mockup

A clickable mockup of the Archiwista interface for decisions before
implementation (no build step: `index.html` + ES modules from a CDN — Preact, htm,
MapLibre GL).

## Running

From the repository root:

```
python3 -m http.server 8090 --directory mockup
```

and open <http://127.0.0.1:8090/>. On the local network (e.g. a phone) add
`--bind 0.0.0.0` and open `http://<computer-address>:8090/`. The browser
needs internet access (CDN for libraries and fonts, the OpenFreeMap basemap).

## Flow

1. **Obszar** (Area) — a rectangle, a polygon or "Obszar demo" (Demo area) (Kraków 12 × 10 km).
2. **Produkt** (Product) — NMT, NMPT, LAZ, orthophotomap, BDOT10k and the **own data
   of the project** (`kanalizacja.gpkg` in the `dane/` folder; the button "Wczytaj folder
   danych" (Load the data folder) instead of an availability check).
3. **Dostępność** (Availability) — a summary of the check in the selection panel (years by
   coverage, report date, source), the result in three views (switch above the
   map): **Mapa** (Map) (sheets of the selected set, campaign colours, a legend
   with flight dates, years as buttons in the top left corner of the map),
   **Wachlarz** (the Fan) (year layers on an arc like a stack of files in the macOS dock — each
   shown in full, with year, coverage and store state, the selected one enlarged
   in the arc and beside it) and **Katalog** (Catalog) (the whole set: **Kafle** (Tiles), **Lista** (List) or
   **Oś czasu** (Timeline) — years × variants × coverage). A tile, a list row
   and a timeline cell are a set: a click, `Enter` or `Spacja` (Space) selects
   it (the map, the Fan and the details panel follow the selection).
4. **Set details** (panel on the right) — only the selected set: formats
   (choice of download format), sheets YES/NO ("TAK"/"NIE"), flight, campaigns, the download
   command, "Pobierz" (Download), "Mozaika z asystentem" (Mosaic with the assistant), "Karta" (Card), and outside the Catalog
   a year variant switch. The panel appears after the availability check
   and can be collapsed with the "Szczegóły" (Details) button above the view.
5. **Asystent** (Assistant) (after the MVP, v1.2; marked "po MVP" (after the MVP) in the mockup) — e.g.
   "Przygotuj NMT 1 m dla tego obszaru, najnowszy pełny rok, jako jedna
   mozaika" → step plan → "Zatwierdź i uruchom" (Approve and run) / "Zmień rok" (Change year) / "Odrzuć" (Reject)
   → job progress (chat and "Zadania" (Jobs)) → result on the map, in the Fan
   and in the "Karta pliku" (File card). Mosaic is also a post-MVP feature (v1.3).
6. **Own data and snapshots** (MVP, v0.2; A-ADR-027) — a map of the lines
   of the selected version, "Wachlarz migawek" (Snapshot Fan) (working file on top; green —
   added since the previous snapshot, red dashed — removed), a Catalog
   of file versions, and in the details panel "Zrób migawkę…" (Take a snapshot…) → plan (copy to
   `dane/.wersje/<name>/<data>_<sha8>/`, a consistent GeoPackage copy, increment
   only) → background job → new snapshot; the same content a second time =
   "nowa migawka nie powstanie" (no new snapshot will be created).

Previews by data type (PRD, "Widoki według rodzaju danych"):
orthophotomap — every year from the archival GUGiK WMS with a time dimension
(`StandardResolutionTime`), also years not downloaded; NMT — a year assembled
from sheet tiles in the store: hillshade computed from real sheet files
downloaded with Kartograf (2023 — 5 sheets, 2019 5 m, 2017 KRON86;
2024 appears sheet by sheet after "Pobierz" in the mockup), sheets
not downloaded remain footprints; NMPT and LAZ — footprints only; BDOT10k — county
boundaries (PRG) in the colours "paczka jest / brak / w magazynie" (package available / missing / in the store); own data — the lines
of the layer. An earlier version of the mockup showed the same current
image for every year, so changes on the ground were not visible.

Layout principle: **one piece of information — one place**. Selection panel = area,
product and the check summary; centre = overview of sets (Map,
the Fan, Catalog); right panel = details of one selected set;
Assistant = conversation and plans. The year badge on the map is shown only when
the details panel is collapsed, and the Fan labels do not repeat the flight
and campaigns.

A variant = product, year, horizontal system, resolution (density), height
system and submission/campaign. File formats of the same set are
badges of one variant (e.g. NMT 2019 "5 m · EVRF2007 · ASC, ASCII-NMT");
the format is chosen only at download (badges in the details panel,
in the File card and in the assistant's plan), by default a raster ready for
mosaic (ASC, TIF). The Kartograf report stays per format — Archiwista
groups it.

Coverage labels: "pełne" (full), "pełne · N kampanie" (full · N campaigns), "częściowe · X%" (partial · X%),
"brak danych" (no data); a separate store badge: "pobrane" (downloaded), "pobrane 5/12" (downloaded 5/12),
"niepobrane" (not downloaded). Dates in the interface: RRRR.MM.DD. Basemap: grey (OpenFreeMap
"positron" in shades of grey). Layout: desktop 1440–1920 px (the selection
panel and the details panel can be collapsed; the Assistant is a pinned side panel
between the map and "Szczegóły zestawu" (Set details), the map narrows), below 1280 px —
and up to 1599 px with the Assistant open — "Szczegóły zestawu" slide out
from the right, on a phone the panels and chat are drawers from the bottom.

Wide screens (2560, 3440, 5120 px): default panel widths grow
with the screen (`src/panels.js`; the details panel least, because it holds one
set), the Catalog timeline is drawn 1:1 across the view width,
the Fan enlarges thumbnails, labels and preview and is centred,
the Catalog arranges years in columns, and when ≥ 2000 px remain for the centre,
the Fan or the Catalog stands next to the map (two halves). Every side panel has
a handle on its edge (`role="separator"`): dragging, arrows on the
handle (`Shift` — step of 64 px), `Home`/`End`, double click or `Enter` =
default width; limits: selection 260–560, Assistant 300–760,
"Szczegóły zestawu" 340–720 px, centre at least 480 px. Widths are
remembered in `localStorage` (`archiwista-mockup:panel-widths`).

## What is real and what is simulated

- Real: availability reports for NMT, NMPT and LAZ (`kartograf elevation
  availability --json`, `kartograf-availability/1`) for the demo area,
  sheet frames (sheet codes → EPSG:2180 → WGS84), GUGiK WMS previews (including
  archival orthophotomaps with a time dimension) and county boundaries from PRG WFS.
- Assembled by the mockup script on Kartograf libraries (Kartograf does not yet have
  such a report): orthophotomap (WMS index) and BDOT10k
  (county packages); the fields `full_m2`, `sheet_records`,
  `campaigns_selected` are proposals for Kartograf.
- Generated (sample data): a sewer network in the project's data folder
  and its snapshots (`data/own/kanalizacja.json`) — this is not
  real data.
- Simulated: the availability check (phases and delays), store state
  (`data/store.json`), the assistant (simple rules instead of a model), background
  jobs, downloading, mosaic (the result is a preview clipped to the area)
  and saving a snapshot, the coverage estimate for a drawn area (from the sheet
  frames of the report).

## Data

`data/` holds static fixtures. Rebuilding (from the Kartograf repo root, its
`.venv`, with network access): `.venv/bin/python <worktree>/mockup/tools/build_fixtures.py`
(NMT, NMPT, LAZ, sheets), `build_orto_bdot.py` (orthophotomap, BDOT10k)
and `build_mvp_fixtures.py` (archival orthophotomaps per year, county
boundaries, sample own data; the arguments `orto`, `powiaty`, `own`
build only the indicated parts).

## Screenshots

`screenshots/` — preview in WebP (width up to 1280 px, quality 70; about 2 MB
in total): successive steps of the flow on a 1920 × 1080 desktop (`01`–`16`;
`05a`–`05c`: the Fan with the newest, middle
and oldest year selected, `14`: the Fan with a job result and the pinned Assistant),
the Fan at 1440 px (`17`), phone 390 px (`18`–`19`), variants
with formats as badges (`20`) and the Fan (`21-wachlarz-*`: NMT with the newest
and middle year, orthophotomap, with the pinned Assistant). Wide
screens (`22-ultrawide-*`): 1920 × 1080 (control), the Fan at
2560 × 1080 and 3440 × 1440, the Catalog at 3440 × 1440, the map with the Fan
side by side at 5120 × 1440; `23-panel-resize`: dragging the handle of
the Assistant panel (2560 px); `24-katalog-wybor`: selecting a set by clicking
a Catalog tile (2023, variant PL-2000; 1920 px); `25-panel-szczegoly`:
the "Szczegóły zestawu" panel next to the map with the Fan (3440 × 1440). Screenshots
`01`–`04`, `06`–`13`, `15`–`16` and `18`–`19` show the state before the
pinned Assistant panel and before the removal of the "Stos" (Stack) view
(view switch "Mapa · Stos · Katalog"); screenshots `01`–`23` — the state
before the "Szczegóły zestawu" panel (the right panel "Zestawienie" (Summary) with a table of years
and a timeline, a list of years in the selection panel). MVP scope and views by
data type (2026-10-18, 1920 × 1080): `26` map with the archival
orthophotomap 2013, `27` orthophotomap Fan with 2009 selected, `28`
NMT Fan with sheet tiles from the store (2017), `35` NMT 2024 map
assembled from 35 sheets after download, `29`–`30` BDOT10k —
counties in the Fan and on the map, `31`–`34` own data: map, snapshot
Fan, snapshot plan, state after the snapshot.
