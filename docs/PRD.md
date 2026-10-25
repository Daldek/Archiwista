# PRD: Archiwista

2026-10-17 · @Piotr

**Status:** draft for approval · **Licence:** MIT · **Scope and stages:**
[`SCOPE.md`](SCOPE.md) · **Details:** [`SPEC.md`](SPEC.md) · **Decisions:**
[`DECISIONS.md`](DECISIONS.md)

This document says **what** Archiwista does, **for whom** and **why**. It does
not describe technology: the architecture was settled in stage 0 (user decision
2026-10-18; SPEC 5, A-ADR-004 to 008, 013, 015, 028). Where they disagree on
scope and priorities, the PRD and SCOPE take precedence over the SPEC. The
interface is Polish; the names of views and controls are given in English with
the Polish label on first use.

## Goal and problem

Archiwista is a web application for working with a data store: the spatial
data that Kartograf writes and the IMGW-PIB measurement data that IMGWTools
writes. It shows what is in the store, checks what is available and current at
the source, and acts (downloads, updates and pins data in projects) without
knowing the CLI or the directory layout.

The problem: the Kartograf store grows quickly (tens of thousands of files,
several versions of the same sheet, many projects that pin different versions,
PL and CZ data in different systems, a local disk or a network share). Simple
questions today need the CLI, the rules of the `data/` directories and reading
JSON files:

- "What do I have in the store for this catchment, and from which year?"
- "From which year does the source have a complete set of sheets for this
  area?"
- "Is there a newer flight than the one a project uses?"
- "Which files did project X use, and are they untouched?"
- "Which gauges in this catchment have continuous daily discharge since 1951?"
- "Has IMGW published a new year or corrected an old one?"

The character of the product: a **store manager**, not a GIS program or a
calculation program. Archiwista orders data to be downloaded and updated, but
has no mechanism of its own to download or process it: every action on data is
done by the public API of the producer (Kartograf or IMGWTools), and the source
of truth is the files in the store (sidecars, manifests).

The code is open (MIT). Archiwista replaces subproject 5 of the Kartograf
roadmap ("web GUI").

## Users and their needs

| User | Stage | Key question | Needs |
| --- | --- | --- | --- |
| A hydrologist preparing data for a model (knows QGIS, rarely the CLI) | MVP | What is available for my catchment, and from which year? | area on the map → availability with coverage labels → download; gauges in the catchment with the coverage of series |
| A GIS specialist (knows Kartograf and the CLI) | MVP | Which versions do I have, are there newer ones, how do they differ? | a review of versions and campaigns, freshness, previews, PL/CZ border data |
| A project team (several people, a shared store on an SMB share) | MVP | Who downloaded what, and which projects use which data? | one server on the local network, sign-in and roles, a shared queue without double downloads, an action log |
| A developer of Hydrograf, Hydrolog, Retman | MVP | Where is the immutable version of this file or series? | version paths for scripts, store state, projects |
| A user preparing data for QGIS and calculations | after the MVP | How do I load this in one move, or order it in a sentence? | a QGIS set, a natural-language assistant, mosaics, comparisons |

A shared need: **human names and a clear plan**: "NMT 1 m · PL-1992 ·
EVRF2007", not `nmt/pl_1992_1m_evrf2007`; before every action: what, how many
files, how many are already local, how much data, where to.

## Product description

The main flow: **map → area → product → result**. The user selects an area
(rectangle, polygon, geometry file, sheet code, TERYT, KU, country), chooses a
product and at once sees the state of the store (no network), and in the
background a check at the source: years (campaigns, releases) with coverage
labels ("full", "full · 2 campaigns", "partial · 58%", "no data") and the store
badge ("downloaded 5/12"). From a year row: "Download…" → the plan window → a
background job with progress and cancellation.

The MVP views: "Map" (footprints, stations, area selection), "Fan" (Wachlarz:
the years of a result as thumbnails, each shown whole), "Catalog" (list and
search, also data without location), "File card" and "Station card",
"Projects", "Store" (usage and problems), "Jobs", "Settings". Vocabulary and
sketches: SPEC 2 and 6, the mockup `mockup/`.

**What Archiwista is not** (SPEC 1.3): a GIS program (analyses belong to
QGIS); its own mechanism for downloading or processing (it orders them from the
producers); a tool for deleting data from the store; a hydrological analysis
program (Hydrolog, Retman); a source of current IMGW data (states, warnings);
a data editor or a history system of single objects; a replacement for the
Kartograf QGIS plugin.

## Views by kind of data

Views are made from unit footprints (the extent of a file from the producer),
the availability report from the source and the state of the store; previews
come only from data in the store or from source services that have a time
dimension. Years that are not downloaded and have no such service have, in the
"Fan", only footprints in the coverage colours. The mockup shows the same
current picture from the GUGiK WMS for every year; that is a simplification of
the mockup, not a property of the data.

| Kind of data | Unit and footprint | "Map" | "Fan" (layer = year, campaign, release) | Coverage and changes |
| --- | --- | --- | --- | --- |
| Rasters from sheets (NMT, NMPT, LAZ, orthophoto) | sheet (code), CZ tile | sheets in the coverage and campaign colours | footprints + a preview of downloaded sheets; for the orthophoto also years not downloaded, from the GUGiK WMS with a time dimension (1995 to 2025) | year labels (6.4); changes: metadata comparison and the curtain (v0.2), difference model (v1.3) |
| Unit products (BDOT10k, BDOO, 3D models, CORINE) | administrative unit (county, TERYT), boundaries from PRG | units of the area: package present / missing / in the store | unit footprints + a render of chosen layers from downloaded packages, clipped to the area | release labels (KD-4, v0.3); changes: a difference of releases by feature class (vector comparison at the producer, later) |
| National files and area results (PRG, ZABAGED, RUIAN…) | the country or the area of the task | extent | one "current" entry or versions by date | versions by download or release date |
| IMGW stations (also ČHMÚ from v0.6) | station point; without location: the "Catalog" | points in the coverage colours of the chosen variable, with a provider badge | none (the data describes time, not area): the "Timeline" stations × years | coverage labels of series (A-ADR-021) |
| Own project data (for example a sewer network) and the general kind (any raster or vector file) | extent from the file | extent and preview in the view, together with the project data | snapshots as layers | no remote source: no availability labels; "changed since the snapshot of …"; metadata comparison of snapshots |

## Functional requirements

The stage in brackets is the version from [`SCOPE.md`](SCOPE.md). Details of
each requirement: the SPEC section named.

**F1. Stores and index** (SPEC 4)

- F1.1 Configuration of several stores (for example local and team); a store is a Kartograf directory and/or an IMGW directory. (v0.1)
- F1.2 A local index of the store and the projects built from sidecars and manifests through the producers' APIs; full and incremental scan, view refresh before the answer. The index is a cache: it can be deleted and rebuilt. (v0.1)
- F1.3 The index state is always visible ("Index from 14:02, scan in progress: 63%"); the interface never waits for a scan. (v0.1)
- F1.4 Work on an SMB share, also mounted read-only; a disconnected share means a banner and an unchanged index, and after reconnecting a refresh without a rebuild. (v0.1)
- F1.5 Data sources as add-ons: without IMGWTools the application works in full for Kartograf data, and the IMGW source is explicitly "unavailable" (A-ADR-024). (v0.1)

**F2. Map and area** (SPEC 5.4, 6.3)

- F2.1 A map with the footprints of versions in the store and a basemap (grey OSM, offline mode). (v0.1)
- F2.2 Area selection: rectangle, polygon, sheet code, TERYT, KU, geometry file; by the name of a municipality or county. (v0.1; names: v0.3)
- F2.3 The state of the store for an area and product without a network ("83% of the area local"). (v0.1)

**F3. Catalog and search** (SPEC 6.6, 6.8)

- F3.1 The "Catalog": a list with filters (product, data year, variant, project, state) and a group of data without location. (v0.1)
- F3.2 Search by identifier with recognition of the kind: sheet code, TERYT, request number, the beginning of a SHA-256 sum, IMGW station code. (v0.1; stations: v0.5)

**F4. File card and versions** (SPEC 3 UC-04, 6.5)

- F4.1 The version timeline of a slot: current, full, labels (campaign, release), which projects pin which version. (v0.1)
- F4.2 Metadata in plain words and the raw value one click away; the licence with "Copy attribution"; copying the version path. (v0.1)

**F5. Previews** (SPEC 5.7, 8.5 levels 1 and 2)

- F5.1 A preview of every file type in the store or the reason it has none; the same file is not computed twice; a limit of the preview memory. (v0.2)
- F5.2 The "Fan" and the "Timeline" of local data years; metadata comparison of two versions and the curtain on the map. (v0.2)
- F5.3 Pre-building of thumbnails and a low-zoom overview (without all tiles) of current versions in a background job: after an index refresh for new versions when an administrator turns it on (off by default), or on request with a product/segment, project and area filter through the CLI or API; low priority against interactive previews, cancellation, a memory limit that does not evict recently used previews, a read of the store without a network and with project visibility kept. (v0.3; user decision 2026-10-19)

**F6. Availability and coverage labels** (SPEC 6.4, A-ADR-010, 017)

- F6.1 A check at the source for an area and product (PL and CZ elevation) in the background; the last report with its date is available without a network. (v0.3)
- F6.2 Year coverage labels and the store badge; a variant is product, year, system, resolution, vertical datum, request (formats as badges). (v0.3)
- F6.3 Coverage of releases of unit products (BDOT10k and its archive, BDOO, 3D models, CORINE): which units of the area have a package in a given release (KD-4; user decision 2026-10-18). (v0.3)
- F6.4 Years of PL images (orthophoto, true orthophoto, intensity) with the completeness of sheets from the index (KD-3; user decision 2026-10-18). (v0.3)

**F7. Actions** (SPEC 3 UC-01, UC-05, UC-15; 5.6)

- F7.1 The "plan window" before every action with a network or a write: what, how many files, how many local, size, where to, a CLI command to copy. (v0.3)
- F7.2 Download from a form and from a pasted `kartograf …` command. (v0.3)
- F7.3 Background jobs: progress, producer messages unchanged, cancellation without partial versions; a server restart means "interrupted", and a retry does not download finished units. (v0.3)
- F7.4 A freshness check of a segment, an area or a project, and "Download newer" by the same plan. (v0.3)

**F8. Projects** (SPEC 4.7, UC-06, UC-07)

- F8.1 A project preview: the tasks of a project as commands, pinned versions, status, the usage index ("Pinned in: Raba (field)"). (v0.1)
- F8.2 Project actions through the producer's API: create, add and remove a task, download, re-pin, update check, verification of sums. (v0.3)
- F8.3 A project with the manifests of both producers (`kartograf-project.json`, `imgw-project.json`) in one view with a producer column. (v0.5)

**F9. Store health** (SPEC UC-13)

- F9.1 Usage by product (each version counted once) and problems with an explanation and a repair command; the reports "unused by any project" and "non-current versions", with nothing deleted. (v0.1)

**F10. Team mode** (SPEC 10.2, UC-14)

- F10.1 One server on the local network, sign-in (local accounts or a reverse proxy), account management and a project sharing screen in the interface, optional groups from LDAP/AD, on the permissions model F16. (v0.4)
- F10.2 A shared job queue without double downloads, a history and action log, limits per person, file download over HTTP, path aliases per client. (v0.4)

**F11. IMGW data** (SPEC 4.8, 6.7, UC-16, UC-17, UC-19)

- F11.1 Stations on the map, in the "Catalog" (also without location, with a river and hydrographic code filter) and in the "summary". (v0.5)
- F11.2 Coverage labels of series for each variable separately, in hydrological and calendar years with a switch; all stations, also with gaps. (v0.5)
- F11.3 The "Station card" with a chart (gaps as breaks, no interpolation), versions and IMGW formulas; station comparison. No statistical calculations. (v0.5)
- F11.4 Freshness of archives (a new publication, a new year), synchronisation and series as IMGWTools background jobs with the plan window and an `imgw …` command. (v0.5)
- F11.5 IMGW project tasks with pins. (v0.5)

**F15. Own data and snapshots** (SPEC 4.7.1, A-ADR-027)

- F15.1 A folder of own data assigned to a project (by default `<project folder>/dane/`, another can be set); raster and vector files indexed read-only: extent, system, layers, number of objects, attribute schema, preview. (v0.2)
- F15.2 "Make a snapshot": Archiwista copies the file into `<data folder>/.wersje/` as an immutable version with a SHA-256 sum and a description (`migawka.json`); growth only, atomic write, a consistent copy of a file in use (for example a GeoPackage open in QGIS), the same content makes no new snapshot. (v0.2)
- F15.3 Snapshots as versions: the version timeline, the "Fan", the curtain, metadata comparison (object count, extent, schema). (v0.2)
- F15.4 Detection of a file change since the last snapshot and a hint "make a snapshot"; a history of observed states in the index (without content). (v0.2)

**F16. Permissions and project sharing** (SPEC 10.2, A-ADR-029)

- F16.1 Archiwista enforces permissions only on its own surface (interface, API, CLI, agent tokens, preview memory); the security of the server and the share and access to the file system are the responsibility of the server administrator. (v0.1)
- F16.2 Roles: "administrator" (`admin`; the administrator of the Archiwista system: settings, stores, accounts, groups, permissions), "store write" (`store_writer`) and an ordinary "user"; the setting `store_write_for_all` gives write to everyone. In local mode the owner has `admin` and `store_writer`. (v0.1)
- F16.3 Project visibility: public, chosen people, a chosen group (for example a department), private; the project owner; an administrator sees all. The list of projects, "Pinned in:", search and previews of own data respect visibility; permission changes go to the log. (v0.1)
- F16.4 Accounts, groups, memberships, roles and project visibility in a separate local state database with a backup (`archiwista state export`, restore with `archiwista state import`); an index rebuild does not touch it. Administration through the API and the CLI. (v0.1)
- F16.5 A write to the central store only through the producers' APIs and only with the "store write" permission. (v0.3)
- F16.6 Sign-in, account management and the sharing screen in the interface, optional groups from LDAP/AD (F10.1). (v0.4)

**F17. The PL + CZ border** (SPEC 4.8.6, 8.3, UC-09, UC-20; A-ADR-025 erratum 3)

- F17.1 PL and CZ files of one task grouped (`parent_request`) on the map and in the "Catalog"; a check of systems, vertical datum, resolution and dates with a hint for the missing download. (v0.6)
- F17.2 "Combine › PL + CZ": a merged NMT surface on a common grid with a rule and a seam report, computed by Kartograf (KF) with a plan, in the background, with a `kartograf …` command; the result as a derived product in the store and a project task. (v0.6)
- F17.3 ČHMÚ stations (daily hydro and meteo) through IMGWTools in the F11 views: map, "Catalog", "summary" with the coverage of each variable, "Station card" with a chart and CC BY 4.0 attribution, comparison with IMGW stations, freshness and synchronisation of chosen stations, IMGW project tasks. (v0.6)

**After the MVP** (details: SCOPE, "Out of the MVP")

- F12 A project and QGIS set: `.qgz`, a list of paths, attributions, also IMGW and ČHMÚ data and a PL + CZ export without merging (SPEC 8.4). (v1.1)
- F13 The assistant (an LLM agent): plans data preparation, executes only after "Approve and run"; off by default (SPEC 7). (v1.2)
- F14 Combining: mosaic, version comparison with a difference model; the processing is done in Kartograf (SPEC 8). (v1.3)

## Non-functional requirements

**N1. Simplicity (the overriding principle)**

- N1.1 Every technical value has a human name, and every human name gives access to the technical value.
- N1.2 No silent changes: nothing is downloaded, re-pinned or overwritten without an explicit human decision.
- N1.3 Producer messages are shown unchanged; every action can be repeated from the CLI (a command to copy).
- N1.4 The interface is Polish; dates are `RRRR.MM.DD` in the interface and ISO in the API and in files (A-ADR-016).

**N2. Data integrity**

- N2.1 A read-only store: Archiwista writes nothing in the producers' directories; a write goes only through the Kartograf and IMGWTools APIs.
- N2.2 Parity with the CLI: an action through Archiwista and the same CLI command give the same versions, `sha256` and pins.
- N2.3 Archiwista's state (index, previews, job history) is only local and rebuildable; accounts, groups and project visibility are in a separate local state database with an export, because they cannot be rebuilt from disk; nothing on a network share or in the store.
- N2.4 Knowledge of the store format lives only at the producers (A-ADR-014): a missing function is a requirement for the producer (SPEC 12).
- N2.5 Apart from the index Archiwista writes only on the user's command and only in the project directory (snapshots of own data, area files, sets), in an open format readable without Archiwista.

**N3. Performance** (reference store: 50,000 slots, 80,000 versions, 30 projects; SPEC 4.5)

- N3.1 The first full scan 10 minutes or less on SMB, 2 minutes or less on a local disk; an incremental scan without changes 3 minutes or less / 20 seconds or less.
- N3.2 View refresh (area + product) 5 s or less / 1 s or less; list, search, file card p95 200 ms or less; footprints in view p95 300 ms or less.
- N3.3 IMGW data: the station layer and the coverage table p95 300 ms or less; a chart of a full daily series p95 500 ms or less (SMB).
- N3.4 Server memory 500 MB or less without previews; the index 500 MB or less.

**N4. Work without a network and on an SMB share**

- N4.1 Browsing the store works without the internet ("No network, showing only the store"); the basemap in offline mode.
- N4.2 Correctness on SMB without byte-range locks and without stable inodes.

**N5. Security** (SPEC 10)

- N5.1 Local mode: the server only on `127.0.0.1`, protection against CSRF and DNS rebinding, access only for the person who started the server; refusal to start outside `127.0.0.1` without team mode.
- N5.2 Team mode: sign-in, roles, TLS outside `127.0.0.1`, an action log; from v0.1 every service and query checks the permissions of the `Principal` (F16).
- N5.3 Files are read only in the roots of the configured stores and projects; untrusted input (geometry files, IMGW archives) is no risk for the server.
- N5.4 Secrets only on the server side; dependencies with pinned versions and a vulnerability audit in the release gate.

**N6. Platforms and installation**

- N6.1 Linux and Windows from v1.0; macOS without a guarantee.
- N6.2 Installation with one command; the IMGW add-on is optional; the team server is easy to deploy on a local network.
- N6.3 Digital accessibility: WCAG 2.1 AA (an audit before v1.0); desktop and ultrawide monitors first.

**N7. Code and licences**

- N7.1 Open code under the MIT licence; contributions with a CLA (A-ADR-026, [`CONTRIBUTING.md`](../CONTRIBUTING.md)).
- N7.2 Dependencies with licences compatible with MIT; a dependency with a copyleft licence needs a decision (ADR) before it is added.
- N7.3 Compliance with the data terms: GUGiK and ČÚZK (CC BY 4.0) attributions, the IMGW-PIB formulas (terms, section 5), OSM (ODbL) for the basemap, in the file card and the station card.

**N8. Extensibility**

- N8.1 A new source of an existing producer (for example data from Germany in Kartograf) appears in Archiwista without changes in its code: names, variants, commands and footprints come from the producer's API. Missing elements (availability report, footprints, transformations for new systems) are requirements for the producer.
- N8.2 A new producer is a new plugin (adapter) without changes in the layers above (A-ADR-024).
- N8.3 Every kind of data without a dedicated view gets a general view: extent, metadata, versions and preview; a missing remote source does not break the views (no availability labels instead of an error).

## Assumptions and limits

| Assumption | Effect | How it is communicated |
| --- | --- | --- |
| The producers deliver the required APIs (Kartograf KA to KH, IMGWTools IMGW-1 to 20) | Archiwista releases wait for the producers' releases | requirements in SPEC 12; the "needs" column in SCOPE |
| IMGWTools (2.1.1, Beta) has no store today | IMGW data (v0.5), and so the MVP, depends on IMGWTools | requirements agreed early; the IMGW source is an add-on |
| KF (merged PL + CZ surface) is not yet in the public Kartograf API; ČHMÚ stations in IMGWTools are only in preparation | v0.6, and so the MVP, depends on both releases | requirements KF (SPEC 12.5) and IMGW-15 to IMGW-19 (SPEC 12.7) reported early; the risk in SCOPE and SPEC 14 |
| IMGW publication lag (10 to 19 months), republished archives | an incomplete last year, changed data | published years and publication dates in the interface; new versions instead of overwriting |
| Some IMGW stations have no location | stations outside the map | the "Catalog" with the group "without location" and a counter on the map; a location is never guessed |
| SMB semantics (attribute cache, inodes) | the index may be briefly stale | view refresh before the answer, a visible index state |
| Archiwista deletes nothing | the store only grows | a report of deletion candidates with usage (a human decides, deleting is possibly in Kartograf) |
| An online basemap reveals the area of interest | project confidentiality | offline mode; in a team the administrator decides |
| Snapshots lie in the project directory and only grow | the project disk usage grows | the size in the snapshot plan; snapshot usage in the project view; deleting only by hand outside Archiwista |
| Snapshots are a third implementation of versions (next to Kartograf and IMGWTools) | divergent guarantees | the simplest contract: growth only, no links, atomic write, interruption tests (A-ADR-027) |

## Success measures

MVP success criteria (v1.0):

- [ ] The MVP scenarios (SPEC 3: UC-01 to UC-07, UC-09, UC-13 to UC-17, UC-19, UC-20) pass live and are described in a report.
- [ ] The index of a sample store agrees with the producers' read API (the same versions, links and problems).
- [ ] Parity with the CLI for downloads, projects, PL + CZ merging and the synchronisation of IMGW and ČHMÚ (the same versions and `sha256`).
- [ ] The N3 performance targets are met on a real SMB share.
- [ ] Cancellation and restart during jobs leave no partial versions.
- [ ] A team of three on a shared store: no unit is downloaded twice; the roles are checked by tests.
- [ ] Installation on Linux and Windows; a WCAG 2.1 AA audit and a security review without critical remarks.
- [ ] (proposal, to be approved) A person who knows QGIS and not the CLI completes UC-01 without instructions (a test with a user; the coverage labels understood without explanation).

## Open decisions

| Decision | Options / working value | When to decide |
| --- | --- | --- |
| Coverage labels and their look | working ones from SPEC 6.4 (A-ADR-010; mockup M2) | before v0.3 |
| The IMGW data format | `imgw-meta/1`, Parquet, GeoJSON (A-ADR-020) | with the IMGWTools team, before v0.5 |
| Merge results as derived Kartograf products | yes, on the HSG model (A-ADR-009; SPEC 15 P2, P3) | before v0.6 |
| The reference computer for the performance targets | to be set | before v0.1 |
| The ČHMÚ station adapter | one IMGW adapter while ČHMÚ is a provider inside the IMGWTools package; a separate adapter (plugin) only if IMGWTools releases ČHMÚ as a separate package; a package rename (for example "Observer") changes the import and the extra name (SPEC 4.8.6, A-ADR-024) | at the IMGWTools release with ČHMÚ stations, before v0.6 |
