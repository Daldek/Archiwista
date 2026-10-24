# SCOPE: Archiwista

2026-10-17 · @Piotr

**Status:** MVP scope approved; v0.1 and v0.2 released · requirements:
[`PRD.md`](PRD.md) · details of each version and acceptance criteria:
[`SPEC.md`](SPEC.md) section 13 · decision on the scope: A-ADR-025
([`DECISIONS.md`](DECISIONS.md)). The interface is Polish; the names of views
and controls are given in English with the Polish label on first use.

## MVP

**MVP = release v1.0** (user decision 2026-10-17; the PL + CZ border area is in
the MVP by user decision 2026-10-18). It has six areas:

1. **Browser:** index, map, catalog, file card, projects (preview), store
   state; read-only; permissions model and project visibility.
2. **Previews and the Fan:** file previews, the "Fan" (Wachlarz) and the
   "Timeline" (Oś czasu) of years, metadata comparison and the curtain.
3. **Actions:** availability at the source with coverage labels, the plan
   window, downloads, background jobs, freshness, project actions.
4. **Team mode:** a server on the local network with sign-in, roles and
   project sharing.
5. **IMGW data:** stations, coverage of series, station card, freshness and
   synchronisation of archives, IMGW project tasks.
6. **PL + CZ:** a combined view of border data without merging, a merged border
   surface produced by Kartograf, and ČHMÚ stations through IMGWTools in the
   station views.

The QGIS set, the assistant, the mosaic and version comparison with a
difference model come **after the MVP** (v1.1 to v1.3).

## In scope of the MVP

- Configuration of stores (a Kartograf directory and/or an IMGW directory) and
  of project directories; the first-run wizard.
- A local, rebuildable index: full and incremental scan, view refresh, a
  visible index state; work on an SMB share, also read-only.
- Permissions (A-ADR-029): Archiwista enforces them only on its own surface
  (interface, API, CLI, agent tokens, preview memory); the roles "administrator"
  (`admin`), "store write" (`store_writer`, the setting `store_write_for_all`)
  and an ordinary "user"; project visibility `public` / `users` / `group` /
  `private`; a separate local state database with export. The model and its
  enforcement exist from v0.1 (one local owner), store writes are checked from
  v0.3, sign-in and screens from v0.4.
- Data sources as add-ons: Kartograf required, IMGWTools optional; a missing
  producer is "source unavailable", not a failure.
- The "Map" with footprints, area selection (rectangle, polygon, sheet code,
  TERYT, KU, file, unit name) and the state of the store for the area.
- The "Catalog" with filters, search by identifiers and a group of data without
  location.
- The "File card": version timeline, metadata in plain words, licence and
  attribution, pins in projects, version paths.
- The "Store": usage and problems with a repair command; a report of unused and
  non-current versions (nothing is deleted).
- Previews with content-addressed memory, the "Fan", the "Timeline", metadata
  comparison, the curtain.
- Own project data (a data folder, by default `<project folder>/dane/`): a
  read-only index, a preview, snapshots made by Archiwista in
  `<data folder>/.wersje/`, detection of changes since a snapshot.
- Availability at the source (PL and CZ elevation; PL images: orthophoto, true
  orthophoto, intensity; releases of unit products, for example BDOT10k) with
  coverage labels and the store badge.
- The "plan window", downloads from a form and from a pasted command,
  background jobs with progress and cancellation, freshness and "download
  newer".
- Projects: preview, status, verification, actions (project tasks, download,
  re-pinning, update check).
- Local mode with protection (`127.0.0.1` only, CSRF, DNS rebinding, paths).
- Team mode: sign-in, account management and the project sharing screen in the
  interface, optional groups from LDAP/AD, TLS, an action log, a shared queue,
  per-person limits, file download over HTTP, path aliases.
- IMGW data: stations on the map and in the "Catalog", the "summary" with the
  coverage of series for each variable and both year types, the "station card"
  with a chart, station comparison, freshness and synchronisation of archives,
  series, IMGW project tasks.
- The PL + CZ border: files of both countries grouped by task with a
  consistency check (systems, vertical datum, resolution) and a hint for the
  missing download; a merged DEM surface on a common grid with a seam report
  (Kartograf, KF) as a background job and a project task; ČHMÚ stations (daily
  hydro and meteo) in the same views as IMGW stations (IMGWTools, IMGW-15 to
  IMGW-19).
- Installation on Linux and Windows, user documentation, a WCAG 2.1 AA audit, a
  security review, performance measurement on a real SMB share.

## Out of the MVP

| Item | Status | Reason |
| --- | --- | --- |
| A project and QGIS set (`.qgz`, paths, attributions; also with IMGW and ČHMÚ data), PL + CZ export without merging as a set | v1.1 | decision on the MVP scope |
| "Kartograf command" and "Add to project" from the file card (KB-6), the "Catalog" as cards | v1.1 | user decision 2026-10-18: in the MVP data is added to a project from an availability result |
| The assistant (an LLM agent), also IMGW tools and the assistant budget per person | v1.2 | decision on the MVP scope |
| Sheet mosaic, version difference model, a set with a copy of the data | v1.3 | needs KE and KG in Kartograf |
| Deleting versions from the store | out of scope | only a report of candidates; deleting, if ever, belongs to Kartograf (SPEC 15 P4) |
| Pinning any older version chosen in the browser | not in v1.0 | the project task model picks the version with options (SPEC 15 P9) |
| 3D preview of LAZ point clouds | after v1.0 | the header and a 2D image are enough to recognise a file (SPEC 15 P5) |
| Direct sign-in through LDAP | later | the MVP has local accounts or a reverse proxy (a path to SSO and AD); groups from LDAP/AD are optional in v0.4 |
| macOS | no guarantee | priority is Linux and Windows (SPEC 15 P10) |
| GIS analyses | out of scope | analyses belong to QGIS |
| Hydrological calculations and statistics of series | out of scope | Hydrolog and Retman |
| Current IMGW and ČHMÚ data (states, warnings) | out of scope | only archives and series from the store |
| Own downloading or processing of data | out of scope | only the producers' APIs; a missing function is a requirement for the producer |
| QGIS plugin | out of scope | subproject 4 of the Kartograf roadmap |
| Object differences between snapshots of own data (added, removed, changed) | later | a separate decision; the MVP has metadata comparison and the curtain |
| Editing data and the history of single objects | out of scope | Archiwista is not an editor; snapshots are of whole files |
| Own data in the project manifest (pins, restoring at a colleague's, "Verify") | out of scope | only the producer writes the manifest; snapshots lie in the project directory and move with it |
| Deleting snapshots by Archiwista | out of scope | only growth; delete by hand outside Archiwista |
| File rights on the server and share | out of scope | Archiwista enforces permissions only in its interface, API, CLI, agent tokens and preview memory; file system access is the server administrator's responsibility (A-ADR-029) |

## Stages and their products

The stages follow each other. Each ends with a gate, the condition to go on.
Full acceptance criteria: SPEC 13.

1. **Stage 0: architecture and plan.** Architecture decisions, **accepted
   2026-10-18**: Python + FastAPI, a Preact + htm interface without a build
   step, MapLibre GL, worker processes, rio-tiler, a Python package, team mode
   as one server (A-ADR-004, 006, 007, 008, 013, 015, 028). The reference
   computer and the v0.1 implementation plan are in
   [`PLAN_v0.1.md`](PLAN_v0.1.md).
   - Gate: architecture ADRs accepted (met), the v0.1 plan approved by the user
     (met: the plan after the review of 2026-10-18, executed in steps 0 to 14).
2. **v0.1 "Browser"**, **released as 0.1.0 (2026-10-19)**. Index, "Map",
   "Catalog", "File card", "Projects" (preview), "Store", the source mechanism
   with a stand-in second adapter, protection of local mode, the permissions
   model (state database, `Principal`, project visibility, administrator API and
   CLI).
   - Gate (met; evidence of every SPEC 13 v0.1 criterion:
     [`reports/v0.1-measurements.md`](reports/v0.1-measurements.md)): the index
     agrees with the Kartograf read API (three live stores); the performance
     targets for 50,000 slots are met on SSD and SMB 3; a read-only store works;
     the security tests and the project visibility matrix are green. The
     Kartograf API is on `develop`; the tag `v0.8.0` awaits the user's
     decision.
3. **v0.2 "Previews", released as 0.2.0 (2026-10-20).** Previews, the "Fan",
   the "Timeline", metadata comparison and the curtain; own project data and
   snapshots.
   - Gate: every file type has a preview or a reason it has none (met); CZ
     footprints within 2 m of a control point (met); a GeoPackage snapshot made
     during editing is consistent and an interruption leaves no partial version
     (met). **30 frames per second or more with 5,000 footprints is
     unverified** without a hardware GPU. Evidence and conditions:
     [`reports/v0.2-measurements.md`](reports/v0.2-measurements.md).
4. **v0.3 "Actions".** Availability with coverage labels (also PL images and
   releases of unit products), the "plan window", downloads, background jobs,
   freshness, project actions; the "store write" permission on actions;
   pre-building of previews of current versions (user decision 2026-10-19).
   - Gate: parity with the CLI; cancellation without partial versions; labels
     for the area "Kraków" agree with a manual calculation; UC-01 and UC-06
     live; an action that writes the store is refused without the permission;
     after pre-building, the first thumbnail of a current version from an
     HDD/SMB store is served from the local memory within the target time of a
     preview from memory (SPEC 4.5).
5. **v0.4 "Team".** A server on the local network: sign-in, account management
   and project sharing in the interface, optional LDAP/AD groups, TLS, a log, a
   shared queue.
   - Gate: a live scenario with three people without double downloads; the
     permissions of the roles checked by tests.
6. **v0.5 "IMGW stations".** The IMGW add-on, stations, coverage of series,
   station card, freshness and synchronisation of archives, IMGW project tasks.
   - Gate: the IMGW catalog index agrees with the IMGWTools API; parity with
     the `imgw` CLI; coverage labels agree with the table of edge cases.
7. **v0.6 "PL + CZ".** A PL + CZ view without merging, the merged border
   surface by Kartograf (KF), ČHMÚ stations through IMGWTools in the v0.5
   views.
   - Gate: a surface at the border (Cieszyn) in EPSG:2180 and 5514 with a seam
     report, no zeros where `nodata` is, parity with the CLI; the ČHMÚ data index
     agrees with the IMGWTools API, the coverage labels of ČHMÚ stations agree
     with the table of edge cases; UC-09 and UC-20 live.
8. **v1.0 "Release" (MVP).** A stable API, installation on Linux and Windows,
   user documentation, audits, measurement on a real SMB share.
   - Gate: the MVP success criteria of the PRD.
9. **After the MVP:** v1.1 "Set", v1.2 "Assistant", v1.3 "Mosaic and
   comparison".

## Dependencies

**Producers** (requirements: SPEC 12,
[`IMGWTOOLS_REQUIREMENTS.md`](IMGWTOOLS_REQUIREMENTS.md)):

| Archiwista version | Needs from the producers |
| --- | --- |
| v0.1 | Kartograf: KA-1 to KA-6 (store read), KA-8 (dataset key convention: Kartograf 0.8.0 meets it in code, the rule is to be written in its ARCH) |
| v0.2 | none |
| v0.3 | Kartograf: KA-4 for plan items, KB-1 to KB-5, KB-7, KC-1 to KC-3, KD-1 to KD-4, KH-1 |
| v0.4 | none |
| v0.5 | IMGWTools: IMGW-1 to IMGW-14, IMGW-20 (dataset key convention) |
| v0.6 | Kartograf: KF (merged PL + CZ surface); IMGWTools: IMGW-15 to IMGW-19 (ČHMÚ stations) |
| v1.0 | releases of Kartograf and IMGWTools with all of the above |
| v1.1 | Kartograf: KB-6 |
| v1.3 | Kartograf: KE, KG |

**Data in the store and its terms** (Archiwista shows the attributions and does
not change the terms):

| Data | Source | Licence notes |
| --- | --- | --- |
| NMT, NMPT, LAZ, orthophoto, BDOT10k, PRG, EGiB and others | GUGiK (through Kartograf) | free of charge, with the source named |
| DMR, DMP, orthophoto, ZABAGED, RUIAN and others | ČÚZK (through Kartograf) | CC BY 4.0 |
| CORINE, SoilGrids | Copernicus, ISRIC (through Kartograf) | open, with attribution |
| Hydro and meteo archives, station catalog | IMGW-PIB (through IMGWTools) | IMGW-PIB terms: source formulas (section 5 items 3 and 4), purpose of use (section 3 item 2) |
| Hydro and meteo archives, station metadata (from v0.6) | ČHMÚ (through IMGWTools) | CC BY 4.0, ČHMÚ attribution |
| Map basemap | OpenFreeMap (OpenMapTiles vector tiles from OSM data, Archiwista's grey style); GUGiK OSM BaseMap (raster, Poland only) | ODbL; attributions on the map: "OpenFreeMap © OpenMapTiles Data from OpenStreetMap", "© OpenStreetMap contributors, GUGiK" |

**Test environment:** the sample live test store of Kartograf and a test IMGW
directory in `<data-dir>`; the synthetic store of 50,000 slots from the
generator (SPEC 11); an SMB 3 share for measurements.

## Risks and countermeasures

The full list: SPEC 14.

| Risk | Effect | Countermeasure |
| --- | --- | --- |
| The MVP depends on an IMGWTools release with a store (today Beta, IMGW-1 to IMGW-14) | v1.0 waits for IMGWTools | requirements agreed early; v0.1 to v0.4 without IMGWTools; the IMGW source is an add-on |
| The MVP depends on ČHMÚ stations in IMGWTools (IMGW-15 to IMGW-19; today the "Observer" sketch without code) | v0.6, and with it v1.0, waits for IMGWTools; a package rename or a separate package changes the adapter | requirements reported early (`IMGWTOOLS_REQUIREMENTS.md`); the same contracts with the supplier as an additive change; one IMGW adapter, the adapter decision at the IMGWTools release |
| Dependence on Kartograf releases (KA to KH); KF (merged surface, today R6 in the backlog) blocks the MVP | stages wait, v0.6 and v1.0 wait for KF | KA small and first; KF reported as an MVP requirement; a common schedule with the Kartograf roadmap |
| Team mode in the MVP widens the security scope | a longer way to v1.0 | v0.4 before the IMGW data; a security review in the v1.0 gate |
| An interface without type checking (Preact + htm without a build, A-ADR-028) | errors found late | browser tests (Playwright), JSDoc; Vite and TypeScript can be added later without a rewrite |
| SMB semantics | a stale index | immutable versions, view refresh, a visible index state |
| Coverage labels misunderstood | a wrong choice of year | mockup, definitions in tooltips, a test with a user |
| Scope growing into a GIS program | less simplicity | the PRD boundaries; analyses in QGIS |
| No QGIS set in the MVP | loading data into QGIS by hand | copying version paths and CLI commands in the MVP; the set in v1.1 |
| A snapshot of a file being edited (GeoPackage in QGIS, Shapefile) | an inconsistent copy | an SQLite backup copy for GeoPackage, the whole set of files for multi-file formats, a test in the v0.2 gate |
| Snapshots grow in the project directory | no disk space | the size in the snapshot plan, usage in the project view |
| The visibility filter missed in a new route or query (search, "Pinned in:", previews of own data) | a leak of names and data of private projects | the model from v0.1: a `Principal` in every service, one place of decision, the visibility matrix in the v0.1 gate (A-ADR-029) |
| Loss of the state database (accounts, groups, project visibility): it cannot be rebuilt from disk | projects return to default visibility | the database only local, migrations instead of rebuilding, `archiwista state export` / `state import` in the backup documentation |
