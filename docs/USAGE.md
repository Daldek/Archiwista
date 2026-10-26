# User guide: Archiwista 0.3

Archiwista 0.3 "Actions" shows a Kartograf store, and the files of an IMGWTools
store, on a map, in a catalog and in file cards, with previews, the Fan, the
Timeline and comparison; projects have a folder of own data and snapshots. It
acts through the producer: it asks the source what it has for an area, plans and
runs a download into a configured store, creates and changes projects, and
downloads, checks, verifies and repins their tasks, all as background jobs, and
it prepares the first look at current versions ahead. Archiwista writes no file
of a store itself: the producer writes it, and only for a person with the
permission "zapis do magazynu"; snapshots are made only on the command of an
authorised person, in the project folder. The interface text is Polish; the
Polish label of a control is given in quotes where this guide first names it.
Running and the command line: [`README.md`](../README.md); scripts and agents:
[`AGENT_API.md`](AGENT_API.md).

## Start

1. `archiwista serve` opens the browser at a one-time address with a token
   (valid for 10 minutes). If the browser does not open, copy the address from
   the terminal.
2. The wizard "Pierwsze uruchomienie" (first run) has four steps:
   - **Stores** ("Magazyny"): a name for people, a short identifier (used in
     addresses and in the API), the full path of the Kartograf store root (the
     directory that holds `kartograf-store.json` and the product directories,
     usually called `data/`) and the kind: local disk or network share (detected
     by default). A store needs the Kartograf store root, the root of an IMGWTools
     store (the directory with `imgw-store.json`, field "Katalog IMGWTools") or
     both. The IMGW field is offered while the IMGW source is installed (`pip
     install "archiwista[imgw]"`) or the store already has such a directory; a
     directory inside another store is refused. A store written by an earlier
     version of its producer has no marker: the wizard then shows the command to
     run once, `kartograf store init --root <path>` or `imgw store init --root
     <path>`. There can be several stores.
     If the directory Kartograf or IMGWTools itself uses when a call names no store
     (`KARTOGRAF_ROOT` or `IMGW_ROOT`, `[kartograf] root` or `[imgw] root` of
     `nogat.toml`, else `<data_dir>/kartograf` or `<data_dir>/imgw`) exists and holds
     the producer's marker, the wizard offers it under the empty field of that
     producer with the button "Użyj tego katalogu"; it is entered only by your click.
   - **Projects** ("Projekty"): directories with the projects of Kartograf
     (`kartograf-project.json`) and IMGWTools (`imgw-project.json`); they can be
     added later.
   - **Mode** ("Tryb pracy"): offline mode means the browser sends no request
     outside Archiwista, so the map has no basemap.
   - **Save** ("Zapis"): a summary and "Zapisz i zindeksuj" (save and index).
3. The first full scan runs in the background, and the status bar above the
   views shows its progress. After that the scheduler scans: incrementally
   every 5 minutes (local disk) or 15 minutes (share), and in full once a day.

![First-run wizard](reports/v0.1-screenshots/01-wizard.webp)

## The window

- **Views** on the left: Map ("Mapa", the start view), Catalog ("Katalog"),
  Projects ("Projekty"), Store ("Magazyn") and, at the bottom, Settings
  ("Ustawienia"), the same form as the wizard. Saving the settings replaces
  all of them at once; a new or moved store is scanned from scratch.
- **Top bar:** the stores with a state dot, "Szukaj" (search; `Ctrl+K` or `/`
  in every view) and the current session.
- **The index status bar** under the top bar reports a scan in progress, a
  failed scan and an unavailable store (for example a disconnected share); the
  views then show the state of the index with its time, which does not prove
  that the files are gone.
- **The `</>` icon** next to a name for people shows the technical value:
  segment, dataset key, EPSG code, identifier.
- **Panels** are widened by dragging their edge (or with the arrow keys; a
  double click restores the default width) and can be collapsed.
- **The page address** keeps the view, the filters and the open file card, so
  it can be bookmarked or sent.

## Map

![Map with an area and the local state](reports/v0.1-screenshots/02-map.webp)

The panel "Wybór" (selection) leads through four steps:

1. **Area:** "Prostokąt" (rectangle: drag on the map), "Wielokąt" (polygon:
   click the vertices; finish by clicking the first point, with a double click
   or `Enter`; `Backspace` undoes, `Esc` cancels), "Widok mapy" (the current
   map view), a sheet code typed or clicked in the "Siatka godeł" (sheet grid:
   PL-1992, PL-2000, the chosen scale) and "Plik…" (file): GeoJSON,
   GeoPackage or a ZIP with one Shapefile; of a file with several layers you
   choose one.
2. **Product and filters:** a product from the list (with the number of slots
   and versions), variants (segments) and filters: store, country, data
   years, unit code, versions, file state, text. Active filters show above the
   map.
3. **Local state:** how much of the area the current versions of the product
   cover in the store, for example "lokalnie 30% obszaru" (30% of the area is
   local), with km² and the number of versions, separately for every country.
   "Odśwież" (refresh) reads the slots of the area from the store again;
   "Pokaż pliki obszaru w Katalogu" (show the files of the area in the
   Catalog) opens the list.
4. **At the source** ("U źródła"): a product whose
   availability a producer checks and the target store ("Magazyn docelowy").
   "Sprawdź u źródła" asks the source (a background job); a report younger
   than seven days is shown with its date, and "Sprawdź ponownie" asks again.
   A row is a year: its coverage label ("pełne", "częściowe · 58% · 1 ark.
   niepełny"), its best variant with the formats, the size (or "rozmiar
   nieznany") and the store badge ("niepobrane", "pobrane 5/12"); "+1 wariant"
   lists the other variants. "Pobierz…" opens the plan window ("Pobrać?"):
   the producer's plan of the chosen format with the positions by status
   ("aktualne", "nowsze u źródła", "brak w magazynie", "nie do sprawdzenia"),
   what will be downloaded and its size ("co najmniej …" when the producer
   tells only some sizes), the store and the producer's command line to copy.
   Nothing is written before "Pobierz N pozycji"; above 5 GB or 500 positions
   it asks for a confirmation. The window then shows the progress, the files
   by status and the units that failed. Without the permission "zapis do
   magazynu" the plan is shown and the download is disabled with the reason;
   offline mode keeps the last report and disables both actions; without a
   report it points to step 3, which shows how much of the area the store
   already covers.

   ![Plan window of a download](reports/v0.3-screenshots/02-okno-planu.webp)

   A download runs in the background. Once it starts, the window no longer
   holds the page: it floats in a corner, "Zwiń" (minimise) hides it and
   "Zamknij" (close) or `Esc` closes it, and neither stops the download; the
   map and the other views stay usable. "Pobieranie 2/6 · 45%" in the top bar
   sums the downloads started together (those that ended of all, and how far
   their units got), also after a change of the view or a reload of the page
   and for a download of the session started elsewhere (a project's download
   or repin, another tab). It opens "Pobrania w tle" (downloads in the
   background): each download's progress, its files when done or why it
   failed, "Anuluj pobieranie" (the only way to stop one; what is already
   downloaded stays), "Pokaż okno planu" while its window is kept, and "Usuń
   z listy" once it ended. Each end shows a toast ("Pobrano: …", "Pobieranie
   nie powiodło się: …") with "Pokaż wynik", and the map and the step read the
   store again.

   ![Downloads in the background](reports/v0.3-screenshots/13-pobieranie-w-tle.webp)

   "Wklej polecenie producenta" (paste a producer's command), with or without
   an area, takes a command line as the producer's command line interface
   reads it, e.g. `kartograf elevation download --product nmt … -o ./dane`:
   the producer reads and checks it without the network against the target
   store, and its text for a mistake shows at the field. "Zaplanuj…" opens the
   same plan window for that line, which writes to the target store instead of
   the line's `-o` or `--root`. In the plan window "Dodaj jako zadanie
   projektu" (add as a project task) adds the one command as a task of a
   project with a manifest of the producer in that store ("Projekt", "Nazwa
   zadania"); with
   something to download the button reads "Dodaj zadanie i pobierz N
   pozycji" and the project's download of the new task downloads and pins
   it. The option is disabled with the reason when the variant has several
   commands, when the store has no project of the producer, or when you may
   change none of them (the project's owner or an administrator may). Adding
   a task needs no network, so it works offline too.

   ![A pasted command as a project task](reports/v0.3-screenshots/10-zadanie-projektu.webp)

File footprints are visible at once; with more than 5,000 footprints in view
the map shows a density grid, and clicking a cell zooms in. Clicking a
footprint opens the file card (when several files lie in one place, their list
comes first). Files without a footprint do not reach the map: the counter
"… bez obrysu" (without footprint) leads to them in the Catalog. The legend
changes the basemap: by default the grey "OpenFreeMap szary" (vector tiles
from OpenStreetMap data, names in Polish also abroad: Praga, Drezno, Lwów), as
options "OSM GUGiK szary (tylko Polska)" (Poland only; outside Poland it is
empty) or "bez podkładu" (no basemap). Settings saved before v0.2 keep their
list of basemaps; removing the `[[basemaps]]` tables from `config.toml` gives
the new built-in ones. Without a mouse the arrow keys pan the map, plus and
minus zoom.

![File card with the reason a preview is missing](reports/v0.2-screenshots/02-karta-pliku-powod.webp)

Sheet footprints are WGS84 polygons, not rectangular envelopes. The preview of
a file appears on the map after its tiles are prepared; larger rasters may
need the button "Zbuduj podgląd" (build the preview). Tiles, thumbnails and
the preview of a whole year are kept in the local content-addressed memory
(limit 20 GB, the least recently used go first). Every file has a preview or a
reason, in Polish, why it has none, with an instruction on what to do.

The first look at a file on an HDD or a share is slow; it can be prepared
ahead: `archiwista preview-warm` (filters `--store`,
`--product`, `--segment`, `--project`, `--area-id`; `--json`) or `POST
/api/v1/previews/warm` renders, in the background at the lowest priority,
the preview pane's thumbnail and the map's tiles at the smallest zoom of the
current versions, into the same memory. It never evicts a preview used in the
last week: when the room runs out it stops and says how many versions it
skipped. A project's own data is prepared only with `--project`, for those who
see the project. The administrator's setting `preview_warm_after_scan` (`PUT
/api/v1/settings` or `config.toml`; off by default) starts such a job for the
versions a scan has just indexed.

## Catalog

![Catalog with search and filters](reports/v0.1-screenshots/03-catalog.webp)

- **Search** (`Ctrl+K` or `/`): every word must match the beginning of a sheet
  code, TERYT, KU, file name, product, version label, request number or
  campaign, without Polish diacritics. 8 to 64 hexadecimal characters are the
  beginning of a SHA-256 sum.
- **Filters:** store, product with variants, country, data year (from to: the
  year of the flight or release, never the year of download), unit (exact
  code), versions (current, all, full sheets `full_sheet/`, pinned in
  projects, non-current and unpinned), state, and an area or a rectangle in
  the chosen coordinate system. `Ctrl+K` from the map carries its filters and
  area over.
- **Location:** "Wszystkie" (all), "Z położeniem" (with location), "Bez
  obrysu" (without footprint); the counters cover the whole result. Files
  without a footprint are only here; the reason is in the column
  "Położenie" (location).
- The list loads further pages while you scroll. Keyboard: `↑` `↓` choose,
  `Enter` opens the file card, `M` shows it on the map.
- "Pokaż wynik na mapie" (show the result on the map) opens the map with the
  same filters, and "Zapytanie API" (API query) gives the same query as an API
  address.

## File card

![File card](reports/v0.1-screenshots/04-file-card.webp)

- **Version timeline:** the newest on top; "bieżąca" (current) is the one the
  standard path points to, "pełny arkusz" (full sheet) the `full_sheet/` link,
  "brak w magazynie od …" (missing from the store since …) a version whose
  file is gone.
- **Version:** year and date of the data, label (campaign, release or download
  date), request, full sheet, resolution, horizontal and vertical systems,
  nodata, size, SHA-256, download date and the location with the source of the
  footprint.
- **Licence** with the button "Kopiuj atrybucję" (copy the attribution).
- **Paths:** the version path always points to the same content, which is the
  one to use in projects and analyses; the standard path is a link to the
  current version and points to other content once a newer one is downloaded.
  "Na innym komputerze" (on another computer) gives the same path under another
  drive letter or mount (the store setting `path_aliases`).
- **"Przypięta w:"** (pinned in): the projects that pinned this version.
- **"Pliki tego samego zapytania"** (files of the same request): files
  downloaded by one producer request, for example both sides of the PL/CZ
  border.
- **Sidecar:** the producer's raw metadata, unchanged, ready to copy.
- **"Potwierdź bieżącą wersję"** (confirm the current version) checks by
  content (SHA-256 of the whole file) which version the standard path holds;
  on a share it can take a while.

`Esc` or "×" closes the card.

## Projects and own data

![Project with a snapshot](reports/v0.2-screenshots/08-migawka-w-edycji.webp)

- **The list** of projects shows the producer ("Producent"), the store, the
  tasks, the pinned and missing versions and the own data. A project is its
  directory: it may hold the manifest of Kartograf, of IMGWTools or both, and a
  project of both shows each manifest's store, state at the scan and reading
  time on its own line, led by its producer. An invalid manifest shows the
  producer's message and hides nothing of the other. Hidden projects are
  not visible. "Nowy projekt…" is an administrator's: a
  producer, a store with a directory of that producer and the project's
  directory in a project directory of the settings (made when missing); the
  producer writes the manifest, which names that store's directory. Others see
  the button disabled with the reason.
- **The project card** shows the producers' "Stan teraz" (state now), the
  tasks and the pins of each manifest (with their producer when there are two),
  and its actions,
  each run by the producer: "Weryfikuj" (verify: checksums of the pinned files
  in the store, no network), "Sprawdź aktualizacje" (check the pins against the
  source), "Pobierz" (download and pin the tasks not downloaded yet, restore
  missing pinned files) and, at a task, "Przepnij" (repin the task to the
  source's newer versions); the job shows its progress, then its tasks by
  outcome or its files by state. In a project of two manifests "Manifest
  producenta" chooses the manifest the card's actions and "+ Zadanie" act on;
  a task's actions act on its own manifest. A task name in both manifests is
  a problem of the project. "+ Zadanie" adds a pasted producer's command
  as a task (the producer checks it without the network; its text for a
  mistake shows at the field) and "Usuń" removes a task and its pins after a
  question; the files stay in the store. A project is changed by its owner or
  an administrator, a download and a repin also need the permission "zapis do
  magazynu" and, like a check, the network: an action you may not do is
  disabled and the card says why. When a change stops at a lock of the
  manifest that an interrupted change left, the message names the lock
  directory to remove; Archiwista never removes it.

  ![Project actions after a verification](reports/v0.3-screenshots/11-akcje-projektu.webp)

- **The data folder** is `<project folder>/dane/` by default; an administrator
  can point to another folder. Its scan only reads files. Own data is on the
  map and in the project card, outside the `/slots` catalog of the store.
- **Working file and snapshots:** the card gives metadata, a preview and the
  history; "Zmieniony od migawki" (changed since the snapshot) means the
  content differs from the last saved version. First look at the plan of the
  snapshot (estimated size and any obstacle), then "Zrób migawkę" (make a
  snapshot). The permission `project.write` belongs to the owner of the
  project or an administrator; viewing a project is not enough. A consistent
  GeoPackage snapshot holds the committed changes even when an editor is open.
  The same content twice does not duplicate a version. Snapshots lie in
  `<data folder>/.wersje/`, in the open format `archiwista-snapshot/1`;
  Archiwista does not delete them.

![File changed since the snapshot](reports/v0.2-screenshots/09-zmieniony-od-migawki.webp)
![A second snapshot of the same content](reports/v0.2-screenshots/10-ta-sama-tresc.webp)

## Fan, Timeline and Comparison

![Fan of years](reports/v0.2-screenshots/04-wachlarz.webp)

After you choose an area and a product, open the "Wachlarz" (Fan): the cards
of successive years or campaigns hold the preview of the local sheets, the
newest on top. The chosen layer shows in full and on the map. For own data the
Fan shows the working file and its snapshots. The "Oś czasu" (Timeline) shows
the years with data and their local coverage of the area; the choice of a year
is shared by the map, the Fan and the page address. A missing year does not
mean the producer has no such product, only that this layer is not local.

![Timeline and coverage](reports/v0.2-screenshots/05-os-czasu.webp)

"Porównaj" (compare) sets the metadata of two versions, own files or
snapshots side by side (object differences are not computed). You can view two
previews with the curtain, by cross-fading or side by side; this is a visual
comparison and changes no data.

![Comparison and curtain](reports/v0.2-screenshots/06-porownanie-kurtyna.webp)

## Store

![Store](reports/v0.1-screenshots/06-store.webp)

- **State:** available, unavailable (since when) or not yet scanned; local disk
  or share; the last full pass, the content of the index, the last scan with
  its executor, the last full scan, the Kartograf version and the local
  index.
- **Buttons:** "Odśwież" (refresh) is an incremental scan (changes only);
  "Pełny skan" (full scan) covers the whole store, also files removed or added
  by hand in known version folders; "Uzupełnij obrysy jednostek" (complete
  unit footprints) fetches TERYT and KU boundaries from the network
  (unavailable in offline mode). The progress of the job shows in this view
  and in the status bar.
- **Usage by product:** every version counted once, without links and repeated
  content.
- **Non-current and unpinned:** versions that are neither current, nor in
  `full_sheet/`, nor pinned in projects, and how much space removing them would
  free. Archiwista deletes nothing; the report serves a decision.
- **Store problems** with a repair description (and the file card when they
  concern a file), and the **projects** that use the store.

## IMGW stations

A product of IMGWTools chosen on the map (hydro, meteo, or the station catalogs
themselves) shows its stations in place of outlines. The shape of a point is the
station type: a triangle for a water gauge, a square for a climatological or synoptic
station, a circle for a precipitation post. Its colour and fill are the coverage of
the variable chosen in "Kolor punktów" in the bar (green solid "ciągły", orange solid
"luki", orange half "częściowy", grey hollow "brak danych", grey dashed "nieznane");
the legend names each, and the tooltip of a point gives the label of every variable.
The panel chooses the dataset ("Zbiór danych"), the types of meteo stations and
whether the stations on an area's boundary count. Stations far apart at a low zoom
form a neutral cluster with their count, which zooms in on a click; stations at one
position spread around it until the next click or `Esc`. "N bez położenia" in the bar
opens the Catalog with the stations that have no position.

![Stations on the map with the legend and a tooltip](reports/v0.5-screenshots/01-stacje-na-mapie.webp)

The command line and the API (`GET /api/v1/stations`) show the stations and the
coverage of their series from the index while IMGWTools is installed:

```sh
archiwista stations list --dataset pl.imgw.hydro_daily --coverage Q:continuous --min-complete-years Q:30
archiwista stations list --area-id OBSZAR --boundary false
archiwista stations list --location none
archiwista stations list --q raba --sort name
archiwista stations show 149190310 --years 1951-2025
archiwista stations datasets
```

`stations list` prints each station with the label of every variable of its series
("Q: luki 3% · najdł. 1981.06.02–1982.12.31"; a station has no single label) and the
counters of the whole result: with a location (and of them on the area's boundary,
closer to it than the uncertainty of their location), without one (counted after the
filters, never placed in an area) and hidden by a coverage filter. Its options are
the parameters of `GET /api/v1/stations` (`archiwista stations list --help`):
`--coverage` and `--min-complete-years` need `--dataset`, `--years` and `--year-type`
set the range and the numbering of the labels, and the next page is `--cursor`.
`stations show` is the card of a station: its facts, its location with the source and
the uncertainty, each series with its file and every variable labelled, and the
licence with the formula IMGW requires. A code that two stores or providers share
needs `--store` and `--provider`. `stations datasets` names the datasets with station
series: each with the producer's name, provider and family, the version of its series,
the years of its labels by default and its variables with their units (`--dataset`
and `--variable` take them). `--meteo-kind` (repeatable: `synoptic`, `climate`,
`precipitation`) keeps the meteo stations of those kinds. The list goes along rivers
(the river's hydrographic code, so a tributary follows its river, then the station's
place on the provider's list, then the name); `--sort name` orders it by name. `--q`
finds a station whose name or river contains the text, whatever the case of the
letters, or whose code begins with it. Without IMGWTools each
refuses with the repair command `pip install "archiwista[imgw]"`.

## Session

Archiwista works only on this computer (`127.0.0.1`) and shows nothing
without a session. The session expires after 24 hours without use and ends
when the server stops; the screen "Wymagana sesja" (session required) then
appears. A new session is opened by the address `archiwista serve` printed or
a new address from `archiwista token`. Another browser tab gets its session
from an open Archiwista tab.

## When something does not work

- `archiwista doctor` checks the installation, the Kartograf plugin, the
  stores and the port, and gives a repair for every problem.
- **Store unavailable** (for example a disconnected share): the views show the
  state of the index, the status bar gives its time; after reconnecting, the
  next scan completes the changes without rebuilding the index.
- **Data source unavailable** (Kartograf missing or an unsupported version):
  the status bar gives the repair command, and `archiwista doctor` prints the
  same.

## What version 0.3 does not do

- It checks availability at the source and downloads only from the step "U
  źródła" of the map and from the project card, through Kartograf; the
  interface has no list of jobs with cancel, retry and log yet (the API and
  `archiwista jobs` have them), and an area is not chosen by the name of an
  administrative unit.
- It does not build a local COG ahead: the warm-up prepares the thumbnail of
  such a file only, and its map preview is built at the first view.
- It indexes the files of an IMGWTools store (archives, series, station
  catalogs) and its projects, and shows its stations on the map and through
  `archiwista stations` and the API, but has no station list, card or chart in
  the interface and no IMGW actions yet (v0.5): an action on an IMGWTools
  manifest is refused as not supported.
- It does not show object differences between snapshots and has no sign-in or
  team work (v0.4).
