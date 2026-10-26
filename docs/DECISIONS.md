# Decision log — Archiwista

Each architectural or design decision is described below in the format of
the Kartograf log: number, date, status, context, options considered, decision,
consequences. The text of a decision describes the state at the time it was made; later
changes of facts and additional findings are appended at the end of the entry as errata
`**Erratum N (YYYY-MM-DD, source/reason):**`. The file uses LF line endings.

In `docs/SPEC.md`, references to these decisions take the form "A-ADR-0xx" —
this distinguishes them from Kartograf's ADRs (e.g. "ADR-036" = Kartograf's
versioned store).

From ADR-030 on, each decision is a separate file `docs/decisions/NNNN-slug.md` (DOC-8.2); this file keeps ADR-001 to 029 and the index of all of them.

**Status vocabulary** (the `**Status:**` line of each entry):
- `accepted`: the decision is in force;
- `proposed`: recorded in the spec, waiting for the user's decision (an open question or a mockup is indicated);
- `accepted, partly superseded by ADR-x (scope)`: the indicated part is not in force;
- `accepted, amended by ADR-x (scope)`: in force, a later decision extends it;
- `superseded by ADR-x`: not in force;
- `rejected`: considered and not accepted.

## Index

| ADR | Title | Date | Status |
|---|---|---|---|
| [ADR-001](#adr-001-separate-project-kartograf-as-a-dependency) | Separate project, Kartograf as a dependency | 2026-10-17 | accepted (amended by ADR-024; erratum 2: `kartograf>=0.8.0,<0.9`) |
| [ADR-002](#adr-002-source-of-truth-on-disk-local-index-as-a-cache) | Source of truth on disk, local index as a cache | 2026-10-17 | accepted, amended by ADR-029 (separate local database for state that is not rebuildable) |
| [ADR-003](#adr-003-read-only-store-writes-only-through-kartograf) | Read-only store, writes only through Kartograf | 2026-10-17 | accepted, partly superseded by ADR-019 |
| [ADR-004](#adr-004-python-server-with-fastapi) | Python server with FastAPI | 2026-10-17 | accepted (erratum 2: confirmed after the architecture review, 2026-10-18) |
| [ADR-005](#adr-005-interface-as-a-spa-in-svelte-api-first) | Interface as a SPA in Svelte, API first | 2026-10-17 | superseded by ADR-028 (Preact + htm without a build step; the "API first" principle stays) |
| [ADR-006](#adr-006-map-in-maplibre-gl-js) | Map in MapLibre GL JS | 2026-10-17 | accepted (erratum 3: confirmed 2026-10-18; erratum 1: "Stack" replaced by "the Fan", no 3D) |
| [ADR-007](#adr-007-background-jobs-in-separate-processes) | Background jobs in separate processes | 2026-10-17 | accepted (erratum 2: confirmed 2026-10-18) |
| [ADR-008](#adr-008-previews-via-rio-tiler-with-a-cache-keyed-by-version-hash) | Previews through rio-tiler with a cache keyed by version checksum | 2026-10-17 | accepted (erratum 2: confirmed 2026-10-18, year preview from sheet tiles; erratum 3: version cache key without `sha256`) |
| [ADR-009](#adr-009-data-merging-processing-in-kartograf-packaging-in-archiwista) | Combining data: processing in Kartograf, packaging in Archiwista | 2026-10-17 | proposed (SPEC 15: P2, P3) |
| [ADR-010](#adr-010-year-coverage-labels-and-the-store-badge) | Year coverage labels and store badge | 2026-10-17 | proposed (mockup: M2) |
| [ADR-011](#adr-011-server-side-assistant-with-human-confirmation) | Server-side assistant with human confirmation | 2026-10-17 | accepted |
| [ADR-012](#adr-012-protecting-local-mode) | Local mode protection | 2026-10-17 | accepted (erratum 1: token in the fragment, separate CSRF token, `Origin` rule, CSP with basemaps; erratum 2: CSRF token in every request instead of a cookie, agent sessions limited; erratum 3: team mode by ADR-046, file links by ADR-047) |
| [ADR-013](#adr-013-team-mode-as-a-single-server-on-the-local-network) | Team mode as a single server on a local network | 2026-10-17 | accepted, amended by ADR-029 (roles and permissions model from v0.1; user decision 2026-10-18; SPEC 15: P1), ADR-046 and ADR-047 (erratum 3: v0.4) |
| [ADR-014](#adr-014-knowledge-of-the-store-format-only-in-kartograf) | Knowledge of the store format only in Kartograf | 2026-10-17 | accepted, amended by ADR-019 (erratum 2: KA in Kartograf 0.8.0, `skip_versions`, `list_segments`, KA-5 on request) and ADR-031 (erratum 3: the marker is judged by file name) |
| [ADR-015](#adr-015-packaging-and-running) | Packaging and running | 2026-10-17 | accepted (erratum 2: confirmed 2026-10-18, no Node.js) |
| [ADR-016](#adr-016-date-format-in-the-interface-and-the-map-basemap) | Date format in the interface and map basemap | 2026-10-17 | accepted (SPEC 15: P6; mockup: M9; erratum 2: OpenFreeMap vector basemap instead of BKG TopPlusOpen) |
| [ADR-017](#adr-017-grouped-variants-without-file-format) | Grouped variants without file format | 2026-10-17 | accepted (amends ADR-010) |
| [ADR-018](#adr-018-interface-patterns-after-the-mockup-chat-stack-previews) | Interface patterns after the mockup: chat, Stack, previews | 2026-10-17 | accepted (erratum 1: "the Fan" replaces "Stack", M4/P12 resolved) |
| [ADR-019](#adr-019-two-store-producers-kartograf-and-imgwtools) | Two store producers: Kartograf and IMGWTools | 2026-10-17 | accepted (changes ADR-003, amends ADR-014; item 7 changed by ADR-023; adapters as plugins: ADR-024; the IMGW source: ADR-032) |
| [ADR-020](#adr-020-imgw-data-format-own-sidecar-parquet-geojson) | IMGW data format: own sidecar, Parquet, GeoJSON | 2026-10-17 | proposed (IMGWTools ADR; SPEC 12.8) |
| [ADR-021](#adr-021-coverage-labels-of-imgw-series) | Coverage labels of IMGW series | 2026-10-17 | accepted (P14, P15 — erratum 1; P16 — erratum 2; erratum 3: units known per ČHMÚ station; erratum 4: appearance, M11, user decision 2026-10-26) |
| [ADR-022](#adr-022-data-without-location-catalog-instead-of-the-map) | Data without location: Catalog instead of a map | 2026-10-17 | accepted (SPEC 15: P13) |
| [ADR-023](#adr-023-imgw-data-in-projects-the-imgwtools-manifest) | IMGW data in projects: IMGWTools manifest | 2026-10-17 | accepted (IMGW data in a project in v1.0 and two manifest files: SPEC 15, P18; erratum 2: shape of `imgw-project/1` from IMGWTools 3.0.0) |
| [ADR-024](#adr-024-data-sources-as-plugins-kartograf-required-imgwtools-optional) | Data sources as plugins: Kartograf required, IMGWTools optional | 2026-10-17 | accepted (amends ADR-001 and ADR-019; erratum 1: `kartograf>=0.8.0,<0.9`; amended by ADR-032) |
| [ADR-025](#adr-025-mvp-scope-and-release-order) | MVP scope and release order | 2026-10-17 | accepted (user decision; erratum 3: "PL + CZ" as v0.6 in the MVP, with ČHMÚ stations) |
| [ADR-026](#adr-026-mit-license-and-contributions-with-a-cla) | MIT license and contributions with a CLA | 2026-10-17 | accepted (MIT; CLA — erratum 1, user decision 2026-10-18) |
| [ADR-027](#adr-027-own-data-in-the-project-directory-and-archiwista-snapshots) | Own data in the project directory and Archiwista snapshots | 2026-10-18 | accepted (user decision; erratum 1: in a team the snapshot is made by the project owner or an administrator, ADR-029) |
| [ADR-028](#adr-028-ui-in-preact--htm-without-a-build-step) | Interface in Preact + htm without a build step | 2026-10-18 | accepted (user decision; supersedes ADR-005) |
| [ADR-029](#adr-029-store-write-role-and-project-sharing) | Store write role and project sharing | 2026-10-18 | accepted (user decision; amends ADR-013; permissions model from v0.1; erratum 1: the own data folder is set by an administrator until v0.4; erratum 2: the data folder by its owner, scans, LDAP/AD groups deferred, v0.4) |
| [ADR-030](decisions/0030-adopt-the-nogat-standard-2-1.md) | Adopt the Nogat standard 2.1 | 2026-10-25 | proposed (accepted when the author approves and merges `chore/nogat-2.1`) |
| [ADR-031](decisions/0031-judge-the-store-marker-in-the-adapter.md) | Judge the store marker in the adapter, and refuse a store without one | 2026-10-25 | proposed (accepted when the author approves and merges `feature/kartograf-data-output`; amends ADR-014) |
| [ADR-032](decisions/0032-imgwtools-source.md) | The IMGWTools source: one adapter, the extra, read first | 2026-10-25 | accepted (amends ADR-019 and ADR-024; the plan's approval is delegated; decision 14: a project is its directory, with the manifest of each producer, `SCHEMA_VERSION` 13, errata of ADR-039 and ADR-040) |
| [ADR-033](decisions/0033-offer-the-default-root-in-the-wizard.md) | Offer the producer's default root in the wizard, and never use it | 2026-10-25 | proposed (accepted when the author approves and merges `feature/kartograf-data-output`) |
| [ADR-034](decisions/0034-producer-commands-as-data.md) | The producers' commands as data, an optional capability of the adapters | 2026-10-25 | proposed (accepted when the author approves and merges `feature/kartograf-data-output`) |
| [ADR-035](decisions/0035-availability-at-the-source.md) | The availability at the source, a job with a stored report | 2026-10-25 | proposed (accepted when the author approves and merges `feature/kartograf-data-output`); erratum 1: a row's lines are planned by one job (ADR-044) |
| [ADR-036](decisions/0036-the-plan-of-a-run.md) | The plan of a run: a `check` job, the plan kept with it, the state `partial` | 2026-10-25 | proposed (accepted when the author approves and merges `feature/kartograf-data-output`); erratum 1: the check reads the source's answers of the last hour (Kartograf ADR-056); erratum 2: a check plans several calls (ADR-044) |
| [ADR-037](decisions/0037-the-run-of-a-command.md) | The run of a command: the capability, the `download` job and the rescan of its files | 2026-10-26 | proposed (accepted when the author approves and merges `feature/kartograf-data-output`); erratum 1: a download runs several calls (ADR-044); erratum 2: a planned download claims its positions (ADR-047, v0.4) |
| [ADR-038](decisions/0038-job-controls.md) | Job controls: cancel across processes, retry as a new job, the log's end | 2026-10-26 | proposed (accepted when the author approves and merges `feature/kartograf-data-output`); erratum 1: everyone sees the queue (ADR-047, v0.4) |
| [ADR-039](decisions/0039-project-changes.md) | Projects created and changed through their producer, where a scan finds them | 2026-10-26 | proposed (accepted when the author approves and merges `feature/kartograf-data-output`); erratum 1: a change names the manifest of a project of two (ADR-032 decision 14); erratum 3: every signed-in person creates a project and owns it (user decision 2026-10-26, v0.4) |
| [ADR-040](decisions/0040-project-jobs.md) | The jobs of a project: download, repin, check, verify, and the left lock | 2026-10-26 | proposed (accepted when the author approves and merges `feature/kartograf-data-output`); erratum 1: a job runs the tasks of one manifest (ADR-032 decision 14) |
| [ADR-041](decisions/0041-preview-warm-up.md) | The warm-up of previews: the first look, a pool of its own, the room of the cache | 2026-10-26 | proposed (accepted when the author approves and merges `feature/kartograf-data-output`) |
| [ADR-042](decisions/0042-actions-in-the-interface.md) | The actions in the interface: a pasted command, a task of a project, what a person may do | 2026-10-26 | proposed (accepted when the author approves and merges `feature/kartograf-data-output`) |
| [ADR-043](decisions/0043-downloads-in-the-background.md) | Downloads in the background: the plan window lets go, the top bar follows | 2026-10-26 | proposed (accepted when the author approves and merges `feature/kartograf-data-output`) |
| [ADR-044](decisions/0044-one-job-per-row.md) | One job per row: a `check` and a `download` take the calls of all the lines, and the worker starts lighter | 2026-10-26 | proposed (A and C chosen by delegated approval; accepted when the author approves and merges `feature/kartograf-data-output`; amends ADR-035, ADR-036 and ADR-037) |
| [ADR-046](decisions/0046-team-sign-in-sessions-and-tls.md) | Team mode: sign-in, sessions and transport security | 2026-10-26 | accepted (delegated approval 2026-10-26; plan `docs/plans/2026-10-26-plan-v0.4.md`, not built yet; amends ADR-012 and ADR-013; LDAP/AD groups deferred) |
| [ADR-047](decisions/0047-team-shared-work.md) | The team's shared work: the action log, the shared queue, limits per person, file download, preferences | 2026-10-26 | accepted (delegated approval 2026-10-26; plan `docs/plans/2026-10-26-plan-v0.4.md`, not built yet; amends ADR-012, ADR-037 and ADR-038) |

---

## ADR-001: Separate project, Kartograf as a dependency

**Date:** 2026-10-17
**Status:** accepted (user decision 2026-10-17); amended by ADR-024 (Kartograf required, IMGWTools optional)

**Context:** Kartograf's roadmap (SCOPE 3.3) provided for subproject 5 "web GUI"
(a local data manager) as an overlay on the library. The user wants
a full manager: browsing and searching the archive, a map and previews,
actions through the Kartograf API (downloading, freshness, projects),
preparing data for merging, and an assistant.

**Options:**
- A) The GUI in the Kartograf repository (e.g. a `kartograf.web` package).
- B) A separate project and repository; Kartograf as a dependency (public API and on-disk formats).
- C) Extending the Kartograf CLI with a text interface (TUI).

**Decision:** B. The `Archiwista` repository (branches `main` and `develop`, no remote)
depends on Kartograf's public API (`kartograf.__all__`) and its formats
(`kartograf-meta/1`, the `data/` layout, `kartograf-project/1`, `kartograf-plan/1`,
`kartograf-availability/1`). Archiwista replaces subproject 5 of Kartograf's
roadmap; the QGIS plugin (subproject 4) stays in Kartograf. Option A
would add web dependencies and a second release cycle to the library; option C does not
provide a map or previews.

**Consequences:** Kartograf does not depend on Archiwista and gets no web dependencies.
Archiwista declares a supported range of Kartograf versions and is tested
against its `develop` branch. Missing Kartograf features are requirements
placed on it (ADR-014, SPEC 12); the coordinator updates Kartograf's
roadmap.

**Erratum 1 (2026-10-17, user decision — ADR-024):** Kartograf becomes a required
dependency (`kartograf>=0.9,<0.10`, the range is set at release); IMGWTools is
optional (extra `archiwista[imgw]`), and source adapters are plugins registered
through entry points.

**Erratum 2 (2026-10-18, user decision — ADR-024 erratum 1):** the version range from erratum 1
no longer applies: public store reading (KA-1..KA-6) enters Kartograf 0.8.0, so the
dependency is `kartograf>=0.8.0,<0.9`.

---

## ADR-002: Source of truth on disk, local index as a cache

**Date:** 2026-10-17
**Status:** accepted, amended by ADR-029 (a separate local database for state that is not rebuildable); Kartograf's SCOPE 3.3 principles and the user decision of 2026-10-17

**Context:** A store may sit on an SMB share without byte-range locks, so a SQLite database
cannot live there; the source of truth is the sidecars and manifests, and the
"which projects use a file" index is built locally from the manifests (SCOPE 3.3).
A store has tens of thousands of files — reading the disk on every view
is too slow, especially on a share.

**Options:**
- A) No index: reading the store on every view.
- B) A local SQLite index (WAL, R*Tree, FTS5) rebuildable from Kartograf's files.
- C) A server database (PostgreSQL/PostGIS).
- D) A shared index on the share.

**Decision:** B. The index lives in the user's data directory, never on the share, and can
be deleted and rebuilt at any time. Versions (immutable) are read once,
link sidecars and manifests — on change; before answering a question
about an area, the slots of that area are refreshed; a daily control scan catches
changes that are not visible from directory times (SPEC 4.4).

**Consequences:** Two instances may briefly see different states — the interface always
shows the index time. A change of the index schema means a rebuild, without
migrations. Performance targets: SPEC 4.5.

**Erratum 1 (2026-10-18, user decision, ADR-029):** accounts, groups, roles and project
visibility do not come from files on disk, so they do not go into the index but into
a separate local state database (`<user_data_dir>/state.sqlite`, never on the share), which
an index rebuild skips; its schema changes through migrations, and the backup is
`archiwista state export` (restore: `archiwista state import`).

---

## ADR-003: Read-only store, writes only through Kartograf

**Date:** 2026-10-17
**Status:** accepted, partly superseded by ADR-019 (store writers: Kartograf and IMGWTools)

**Context:** The overlay principle (SCOPE 3.3): overlays call only the library's public API
and have no download or processing logic of their own. Kartograf's store
never silently overwrites data (Kartograf's ADR-036),
and Kartograf deletes nothing.

**Options:**
- A) Archiwista writes its own files in the store (index, thumbnails, notes).
- B) Read-only store; versions, links and manifests are changed only by the Kartograf API.
- C) Like B, but with deletion of versions by Archiwista.

**Decision:** B. Apart from local files (index, previews, logs), Archiwista
writes only the set directory in a project (SPEC 8.4) and the geometry file of
the drawn area for a new project job (`obszary/`). There is no
deletion (SPEC 15, P4).

**Consequences:** v0.1 is verified on a store mounted read-only. Every
new operation that creates data requires a Kartograf function (ADR-009).

**Erratum 1 (2026-10-17, spec review):** "the geometry file of the drawn area"
also covers an area loaded from a file (GPKG, SHP, GeoJSON): for a project
job its copy goes to the project's `obszary/`, not to a local
working directory, so that the manifest does not point to a path outside the project directory
(SPEC 4.1, 6.3, 10.1).

**Erratum 2 (2026-10-17, ADR-019):** the store has two producers — Kartograf (the `--output`
directory with the `data/` layout) and IMGWTools (a separate IMGW directory, `imgw-store/1`).
"Writes only through Kartograf" applies to the Kartograf directory; the IMGW directory
is changed only by the IMGWTools API. The "read-only store" part applies unchanged to
both directories, as do Archiwista's permitted writes (local files, the set directory,
`obszary/`); a set may contain IMGW series in CSV exported
by an IMGWTools function (SPEC 8.4).

---

## ADR-004: Python server with FastAPI

**Date:** 2026-10-17
**Status:** accepted (erratum 2, user decision 2026-10-18; previously reopened — erratum 1)

**Context:** Kartograf is a Python library; Archiwista must call its functions
rather than parse CLI output. One HTTP API is needed for the interface,
the assistant and scripts, with a typed schema.

**Options:**
- A) Python + FastAPI + Uvicorn + Pydantic 2.
- B) Python + Flask.
- C) Python + Django.
- D) Python with a UI framework (NiceGUI, Streamlit, Panel, Dash).
- E) Another language (Node.js, Go, Rust) calling the Kartograf CLI.

**Decision:** A. Typed models give an OpenAPI schema (interface types, assistant
tool descriptions); the same choice as in Hydrograf (its ADR-002). Flask does not provide
schemas without add-ons, Django brings an unnecessary ORM and admin panel, UI frameworks tie
the interface to the Python process (Streamlit reruns the script on every
interaction) and do not provide a clean API, and another language would mean parsing
CLI text — which Kartograf's ADR-037 (option C) already rejected.

**Consequences:** Python 3.12+, like Kartograf. Kartograf is imported only in the adapter
module (`archiwista/adapter/`), which an import test enforces.

**Erratum 1 (2026-10-17, user decision — open architecture):** the architecture is
reopened; the decision returns to the proposed status and will be confirmed or
changed before v0.1 (SCOPE, stage 0). The text above is the assessment so far, the starting
point for the decision.

**Erratum 2 (2026-10-18, user decision — stage 0):** decision confirmed unchanged
after comparing architecture variants; the choice is practically forced, because Kartograf
and IMGWTools are Python libraries.

---

## ADR-005: Interface as a SPA in Svelte, API first

**Date:** 2026-10-17
**Status:** superseded by ADR-028 (user decision 2026-10-18); the "API first" principle and the view state in the URL remain

**Context:** The main screen is a map application with shared state: area, product,
year layers, the "Mapa" (Map), "Stos" (Stack) and "Katalog" (Catalog) views, the "Zestawienie" (Summary) panel, the assistant
chat, job progress. The user left a free hand regarding modern interface
patterns, but wants to see a mockup before decisions on patterns.

**Options:**
- A) Server templates + htmx.
- B) SPA: Svelte 5 + TypeScript + Vite.
- C) SPA: React.
- D) SPA: Vue 3.
- E) Plain JavaScript without a framework (like Hydrograf).

**Decision:** B. A single HTTP API serves the interface, the assistant and scripts; the interface is
built into static files in the Python package (the user does not need
Node.js), the view state is in the URL, API types are generated from OpenAPI.
htmx handles lists and forms well, but the state of the map and panels would break up
into HTML fragments and manual JS; React and Vue are comparable, Svelte gives the
least code; plain JS with this many views grows into disorganised code.

**Consequences:** Two ecosystems in the repository (Python and Node.js for developers). The mockup
(SPEC 16) settles the interface patterns, not the framework.

**Erratum 1 (2026-10-17, user decision — architecture reopened):** the architecture is
reopened; the decision returns to the proposed status and will be confirmed or
changed before v0.1 (SCOPE, stage 0). The text above is the current
assessment, the starting point for the decision.

**Erratum 2 (2026-10-18, user decision — stage 0):** superseded by ADR-028:
the interface in Preact + htm without a build step (like the mockup) instead of Svelte with Vite; what remains from this
decision: a single HTTP API for the interface, scripts and the assistant, and the view state
in the URL.

---

## ADR-006: Map in MapLibre GL JS

**Date:** 2026-10-17
**Status:** accepted (erratum 3, user decision 2026-10-18; erratum 1: "Stos" (Stack) replaced by "Wachlarz" (the Fan), no 3D)

**Context:** The map must smoothly display tens of thousands of footprints, XYZ and WMS basemaps
(GUGiK, CUZK) and the "Stos" (Stack) view — year layers above the map in an
isometric projection (user requirement 2026-10-17).

**Options:**
- A) Leaflet (Hydrograf's choice, its ADR-003).
- B) OpenLayers.
- C) MapLibre GL JS.
- D) CesiumJS.
- E) deck.gl as the main library.

**Decision:** C. WebGL, camera tilt and `fill-extrusion` with a base height give
the "Stos" (Stack) without a separate 3D engine. Leaflet has no tilt or 3D, OpenLayers
no 3D view, CesiumJS is a heavy globe engine, deck.gl may come later
(point clouds, textures in the "Stos" (Stack)).

**Consequences:** Display in EPSG:3857; conversions for display are done by the server
with Kartograf's pinned transformation (KA-6). A browser with WebGL is required.

**Erratum 1 (2026-10-17, user decision after the mockup — ADR-018 erratum 1):** the
"Stos" (Stack) view was removed; it was replaced by the "Wachlarz" (the Fan), an SVG interface component with year thumbnails,
not a map layer. The arguments "camera tilt and `fill-extrusion` give the Stack" and
"textures in the Stack via deck.gl" no longer apply. Choice C remains: MapLibre is
decided by WebGL with tens of thousands of footprints and station points, vector styles
and XYZ/WMS sources (SPEC 5.2, 5.4).

**Erratum 2 (2026-10-17, user decision — architecture reopened):** the architecture is
reopened; the decision returns to the proposed status and will be confirmed or
changed before v0.1 (SCOPE, stage 0). The text above (with erratum 1) is the current
assessment, the starting point for the decision.

**Erratum 3 (2026-10-18, user decision — stage 0):** decision confirmed; MapLibre
proved itself in the mockup (thousands of footprints, year images on the map, line layers
of own data).

---

## ADR-007: Background jobs in separate processes

**Date:** 2026-10-17
**Status:** accepted (erratum 2, user decision 2026-10-18)

**Context:** Downloads, checks, verifications and merging take from seconds to hours,
use native libraries (GDAL) and must be cancellable. Kartograf
is synchronous and currently has no cancellation parameter.

**Options:**
- A) Threads in the server process.
- B) asyncio.
- C) Celery or RQ with Redis.
- D) Worker processes launched by the job supervisor in the server, queue in the index.

**Decision:** D. A worker process calls a Kartograf function and sends JSON Lines events
(progress, messages, result, error); the supervisor records them in the index
and relays them via SSE. Limits: 2 network jobs, 1 job per project.
Cancellation is ultimately cooperative (KC-1); until then an interrupt signal,
and after 30 s the process is terminated. A server restart marks jobs as "interrupted" ("przerwane").
Worker processes get a local `MetadataCache` (never in the current directory
or on a share).

**Consequences:** A native library crash does not take down the server; the process start cost
(about 1 s) is negligible for these operations. Full cancellation without the risk of a
left-over manifest lock requires KC-1.

**Erratum 1 (2026-10-17, user decision — architecture reopened):** the architecture is
reopened; the decision returns to the proposed status and will be confirmed or
changed before v0.1 (SCOPE, stage 0). The text above is the current
assessment, the starting point for the decision.

**Erratum 2 (2026-10-18, user decision — stage 0):** decision confirmed; worker
processes also handle own-data snapshots (A-ADR-027). Behaviour on Windows
(signals, `CTRL_BREAK_EVENT`) is tested before v1.0.

---

## ADR-008: Previews via rio-tiler with a cache keyed by version hash

**Date:** 2026-10-17
**Status:** accepted (erratum 2, user decision 2026-10-18; erratum 3: version cache key without `sha256`)

**Context:** Previews are to cover rasters (ASC, GeoTIFF, JPEG with JGW), GeoPackage, ZIP
packages and LAZ point clouds, without heavy map servers. ASC files have no
tiling, and versions in the store are immutable.

**Options:**
- A) rio-tiler as a library in the server, local COG for files without tiling.
- B) TiTiler as a separate service.
- C) GeoServer or MapServer.
- D) Pre-generated tiles (`gdal2tiles`).

**Decision:** A. Tiles on demand; the preview cache is keyed by the version's `sha256` and style (a version
does not change, so the cache is never stale), limit 20 GB (LRU),
no automatic previews for files larger than 2 GB. Vectors via
pyogrio (GeoJSON of the objects in view), LAZ via laspy (header, 2D image).

**Consequences:** The first preview of an ASC file takes longer (COG built in the background). rio-tiler
uses rasterio and GDAL, which Kartograf already installs.

**Erratum 1 (2026-10-17, user decision — architecture reopened):** the architecture is
reopened; the decision returns to the proposed status and will be confirmed or
changed before v0.1 (SCOPE, stage 0). The text above is the current
assessment, the starting point for the decision.

**Erratum 2 (2026-10-18, user decision — stage 0):** decision confirmed.
The preview of a product's year from sheets (NMT, NMPT, LAZ) is composed of the previews
of individual sheets in the store — one tile per file version, cache keyed by `sha256`;
sheets not downloaded remain footprints (PRD, "Widoki według rodzaju danych"; mockup:
tiles from real files).

**Erratum 3 (2026-10-19, v0.2 plan after review — SPEC 5.7):** a store version without
`sha256` in the sidecar (older sidecars, a version without a sidecar) has the preview cache key
`sha256("path:" + store + ":" + version path + ":" + size + ":" + modification
time)` in a separate key space. Versions are immutable, so the cache is still never
stale, but such versions do not share previews with copies of the same content.
Versions with `sha256` — unchanged.

**Erratum 4 (2026-10-20, v0.2 implementation):** rio-tiler and GDAL do not open
store or project files in the server process. `RenderPool` manages
`archiwista.previews.worker` processes with queue, time and memory limits;
`run_preview` builds the COG in a job. A year tile is composed of version
tiles, and a raster reprojected for the map uses the pinned operation
`COORDINATE_OPERATION` via `rasterio.warp.reproject`, not `WarpedVRT`
(which changes the letter case of the PROJ pipeline). Images and tiles are served by the
API with a CSRF header; before reading the content-keyed cache `ObjectResolver`
checks the visibility of `ref`. Details: `docs/plans/2026-10-19-plan-v0.2.md`, decisions 3–4.

---

## ADR-009: Data merging: processing in Kartograf, packaging in Archiwista

**Date:** 2026-10-17
**Status:** proposed, awaiting a decision from the user and the Kartograf roadmap coordinator (SPEC 15: P2, P3)

**Context:** Four modes of preparation for merging (user decision 2026-10-17):
mosaic, PL + CZ, set for a project and QGIS, version comparison. The overlay
principle (SCOPE 3.3) rules out processing in overlays; Kartograf's
transformation policy (ADR-022, ADR-024, ADR-027) keeps pinned operations in one
place; CLI = API (ADR-037); HSG (ADR-036 D33) is the model of a
derived product in the store.

**Options:**
- A) Everything in Archiwista (its own mosaic, reprojection, differences).
- B) Processing in Kartograf as data group commands (e.g. `elevation mosaic`, like `soil hsg`) with derived products in the store; selection, plan, presentation and the QGIS set in Archiwista.
- C) Processing in Kartograf, but results in a separate directory outside the store.

**Decision:** B (SPEC 8.6). Mosaic, PL + CZ merging and the difference model are
Kartograf functions with `check_*` twins; the results are versions in the store with a sidecar,
`extra.derived` and `extra.source_files[]`; operations can be project
jobs (inputs `input`, result `output`). The QGIS set, metadata
comparison and visual comparison stay in Archiwista. Option A would duplicate
the transformation policy (risk of errors of the "135 m off the truth" class, ADR-024)
and bypass CLI = API; option C loses versioning, sharing
and pinning.

**Consequences:** Requirements KE, KF, KG (SPEC 12.5); modes 1, 2 (merged surface) and 4
(computed differences) wait for Kartograf releases, so the roadmap provides
first the QGIS set, the PL + CZ set without merging and visual comparison.
The `data/` layout extends Kartograf's ADR (tokens `mosaic`, `diff`, country
`pl-cz`, proposals SPEC 8.2-8.5).

---

## ADR-010: Year coverage labels and the store badge

**Date:** 2026-10-17
**Status:** proposed, to be confirmed on the mockup (SPEC 16, M2)

**Context:** The user wants a coverage label for each year: complete, incomplete,
incomplete but can be filled in from another campaign of the same year. The labels should be short,
elegant and based on Kartograf data (sheets `TAK`/`NIE`,
`full_sheet`, availability report).

**Options:**
- A) Numbers only (coverage percentage, number of sheets).
- B) Three states from `complete` alone (complete, partial, none).
- C) Four labels with definitions (complete, complete with N campaigns, partial with the share of full sheets, no data) and a separate store state badge.

**Decision:** C (definitions: SPEC 6.4). "pełne" (complete): one campaign alone covers the land with full
sheets; "pełne · N kampanie" (complete · N campaigns): only N campaigns together; "częściowe ·
58%" (partial · 58%): the share of land within the frames of full sheets (a lower bound), with a note
about incomplete sheets; "brak danych" (no data). Separately the badge: "pobrane" (downloaded),
"pobrane 5/12" (downloaded 5/12), "niepobrane" (not downloaded). The variant of a year is chosen by ranking: complete, share of
full sheets, fewer campaigns, finer resolution, Kartograf's
order. The server computes the labels, so the interface, the assistant and the API share one
vocabulary (agreed with the mockup).

**Consequences:** Requires extensions to Kartograf's availability report: sheet → campaign
(KD-1) and `full_m2` (KD-2); `len(campaigns)` is not enough, because it also counts
incomplete records. Definitions for CZ (without years) and single-unit products are
separate (SPEC 6.4).

**Erratum 1 (2026-10-17, A-ADR-017):** the labels and the badge apply to the variant
grouped without file format: formats of the same set (e.g. `ASC`
and `ASCII-NMT`) share one coverage label; the store badge counts
units in the selected format.

**Erratum 2 (2026-10-17, A-ADR-021):** the labels of this decision describe area coverage;
coverage over time for IMGW station series ("ciągły", "luki N%", "częściowy",
"brak danych", "nieznane") is defined by ADR-021 (SPEC 4.8.4) by the same rules:
the server computes, rounding is cautious, never color alone.

---

## ADR-011: Server-side assistant with human confirmation

**Date:** 2026-10-17
**Status:** accepted (permission boundaries: user decision 2026-10-17)

**Context:** The user wants a chat window with an LLM agent to which data
preparation can be delegated in natural language; the agent must not download or
delete anything without confirmation; the model provider must be configurable,
with privacy and cost taken into account.

**Options:**
- A) Agent in the browser with an API key.
- B) Agent on the server: tools = Archiwista API operations; actions only as proposals approved by a human.
- C) Only an external agent via MCP.
- D) Autonomous agent performing actions on its own.

**Decision:** B (SPEC 7). Read-only tools work on their own; actions are
proposals (structured data with Kartograf commands and a plan),
executed only from the interface with the user's CSRF token; there are no
deletion or settings-change tools. Providers: Anthropic, OpenAI-compatible
API (including local models); the default is none (assistant disabled).
Only metadata with relative paths goes to the provider; a monthly
cost limit applies.

**Consequences:** An evaluation set and hostile-prompt tests in the gate; MCP can be
an additional entry point to the same tools after v1.0.

---

## ADR-012: Protecting local mode

**Date:** 2026-10-17
**Status:** accepted

**Context:** A local web application without login is reachable by every page
opened in the same browser (CSRF, DNS rebinding) and by other
users of the same computer.

**Options:**
- A) No protection ("localhost is safe").
- B) `127.0.0.1` only, `Host` check, startup token, CSRF header, no CORS, CSP.
- C) Full login also locally.

**Decision:** B (SPEC 10.1). The startup token in the address opened by `archiwista serve`
is exchanged for a session cookie; starting on a different address requires team
mode with login.

**Consequences:** The first opening is always through the address from the terminal or through the automatically
opened browser; the token can be disabled in the configuration (not recommended).

**Erratum 1 (2026-10-18, v0.1 plan after review — SPEC 10.1):** clarification of option B
without changing the decision:
- the startup token is in the fragment of the address (`http://127.0.0.1:<port>/#token=…`), so it does not
  reach the server, the access log or the `Referer` header; it is single-use (10 min),
  and the interface exchanges it through `POST /api/v1/session` and removes it from the address;
- the session is an `HttpOnly`, `SameSite=Strict` cookie, and the CSRF token is a separate 128-bit
  session value (the `archiwista_csrf` cookie without `HttpOnly` and the response of
  `POST`/`GET /api/v1/session`): JavaScript cannot read an `HttpOnly` cookie, so
  the `X-Archiwista-CSRF` header cannot carry the session value; the server compares the header
  with the session token and the cookie (double-submit);
- an `Origin`, if present, must be the server address; a state-changing request with `Sec-Fetch-Site`
  (browser) must have `Sec-Fetch-Site: same-origin` and `Origin`, and a read
  with `cross-site` is rejected (`none` — an address typed in or opened from the terminal —
  passes); a client without these headers (curl, an agent script) passes only
  with a session and, for a state change, with the CSRF header;
- further sessions (external agent): a single-use token valid for 5 min from
  `POST /api/v1/session/tokens` (session and CSRF) or from `archiwista token` in the terminal
  of the owner; only the SHA-256 hash of the token is stored in the index;
- CSP has `worker-src 'self'` (the MapLibre worker from the package, a module from the same origin) and the sources
  of the configured basemaps in `connect-src` and `img-src` — only in online mode, because
  MapLibre fetches tiles through `fetch`;
- the server access log is disabled by default, and when enabled it redacts `token=`.

**Erratum 2 (2026-10-19, v0.1 security review, ARCH-SEC-001..005, 008 — SPEC 10.1):**
cookies are bound to the host, not to the port (RFC 6265 8.5), so the browser sends
`archiwista_session` and `archiwista_csrf` also to another program on
`127.0.0.1:<other port>` (e.g. another account on a shared computer), and `SameSite=Strict`
does not block this. Changes without changing option B:
- authentication is the session cookie **and** the session CSRF token in the header
  `X-Archiwista-CSRF` in **every** `/api` request (reads too); the token is returned only by
  `POST /api/v1/session`, the interface keeps it in `sessionStorage` of its own origin,
  a new tab gets it from an open tab (`BroadcastChannel`), job events go
  through `fetch` instead of `EventSource`; there is no `archiwista_csrf` cookie, `GET
  /api/v1/session` does not return the token; the double-submit from Erratum 1 no longer applies;
- `archiwista serve` opens the browser through a private redirect file (`0600`,
  removed after use or after the token expires), not through an address with the token on the command
  line;
- tokens and sessions store only the `id` and `kind` of the issuer; roles and groups are read on
  every request; an agent session does not issue tokens (`403`), ends after 12 h at the latest,
  and `archiwista token --revoke-all` ends all agent sessions; `DELETE
  /api/v1/session` logs out; jobs and the permissions log record the kind of executor
  and the session label;
- request body size is limited (4 KiB for token exchange, 1 MiB for the rest), local data
  has mode `0700` and `umask 077`.

**Erratum 3 (2026-10-26, ADR-046 and ADR-047, delegated approval; plan v0.4):** local mode keeps
every rule above. Team mode (ADR-046) changes four of them: the `Host` and `Origin` rules compare
with the configured `origin` (an `https` address), the cookie is `__Host-archiwista_session` with
`Secure`, there is no startup token (people sign in with an account or through a trusted proxy),
and every request must come over TLS. The CSRF header stays in every `/api` request with one
exception in both modes (ADR-047 decision 5): the `GET` and `HEAD` routes of a file download
accept the session cookie without the header when `Sec-Fetch-Site` is `same-origin` or `none`,
which a page on another port of the host (`same-site`) never sends.

---

## ADR-013: Team mode as a single server on the local network

**Date:** 2026-10-17
**Status:** accepted, amended by ADR-029 (roles and permission model from v0.1), ADR-046 and ADR-047 (v0.4); user decision 2026-10-18; SPEC 15, P1

**Context:** The team is to work later on a shared store on an SMB share without
byte-range locks. Kartograf guarantees safe concurrent writes
(exclusive versions, manifest lock), but does not coordinate who downloads what.

**Options:**
- A) Each person runs their own instance on the shared share.
- B) One Archiwista server on the local network with login, roles and a shared queue.

**Decision:** B as the target team mode (v0.8); A remains supported (one person,
work without a server). The shared queue does not download the same thing twice, there is
one history and one index, and paths are on the server side.

**Consequences:** From v0.1: file access only through the API (without assuming a shared
file system of the browser and the server), an executor on every action,
path aliases. Team mode requires TLS, roles and an action log (SPEC 10.2).

**Erratum 1 (2026-10-18, user decision):** B accepted; after the numbering change
(ADR-025) team mode is v0.4, in the MVP.

**Erratum 2 (2026-10-18, user decision, ADR-029):** the roles "czytelnik" (reader), "operator" (operator),
"administrator" (administrator) replace "administrator" (`admin`), "zapis do magazynu" (store write)
(`store_writer`) and the plain "użytkownik" (user); the permission model and project visibility work
from v0.1 (one local owner), login and account screens remain in v0.4.

**Erratum 3 (2026-10-26, delegated approval; plan v0.4):** option B is built in v0.4 by ADR-046
(sign-in with local accounts or through a trusted reverse proxy, sessions, TLS in the server or
in the proxy) and ADR-047 (the action log, the shared queue without double downloads of planned
downloads, limits per person, file download, preferences and path aliases per person). Groups
come from Archiwista only; groups from LDAP/AD are deferred (ADR-046 decision 9).

---

## ADR-014: Knowledge of the store format only in Kartograf

**Date:** 2026-10-17
**Status:** accepted, amended by ADR-019 (second producer: IMGWTools) and ADR-031 (the store marker)

**Context:** The layout of `data/` (rules 1-10, `versions/`, `full_sheet/`, `bbox/`, link
sidecars, old sidecars, keys from development versions) is described
in Kartograf's ARCH 3.3, but it is evolving. The same knowledge is needed by
the QGIS plugin and Hydrograf (Kartograf backlog: `find_downloaded`).

**Options:**
- A) Archiwista's own `data/` reader according to the documentation.
- B) A temporary own reader, later replaced by the Kartograf API.
- C) A reader in Kartograf (the KA package) as a condition for v0.1.

**Decision:** C. Archiwista reads the store through `iter_store`, `read_sidecar`,
`describe_segment`, `file_footprint`, `link_target` and `pinned_transform`
(SPEC 12.1). Option A will diverge from Kartograf at the first layout
change; option B is a workaround that has to be removed later.

**Consequences:** v0.1 waits for the Kartograf release with KA; KA is small and can be first
in Kartograf's roadmap. Contract test: `iter_store` on Archiwista's
test store.

**Erratum 1 (2026-10-17, ADR-019):** the principle now reads: knowledge of the format of each
producer only at that producer. The `data/` layout and `kartograf-meta/1` are known by Kartograf
(the KA package, unchanged); the IMGW catalog (`imgw-store/1`, `imgw-meta/1`,
`imgw-series/1`), missing-value codes and encodings of IMGW archives are known only by IMGWTools,
and the IMGW adapter reads through its read API (SPEC 12.7, IMGW-10). Contract test:
IMGWTools' `iter_store` on a test catalog built by IMGWTools.

**Erratum 2 (2026-10-18, Kartograf ADR-045 and the v0.1 plan after review — SPEC 4.4, 5.3,
5.6, 12.1):** KA-1..KA-6 accepted in Kartograf 0.8.0 (ADR-045, ARCH 3.3.1). KA-1
extended with `list_segments(output_dir)` (a list of segments for a parallel scan; calls of
`iter_store` for different segments or disjoint batches of units can run at the same time)
and `iter_store(..., skip_versions=...)` (known version directories are returned without opening
the sidecar: `sidecar=None`, `skipped=True`) — an incremental scan does not reread
unchanged versions. The scan does not call `link_target` (KA-5): the current version is taken
from `StoreEntry.version_path` (link sidecar), because on a share without stable inodes
KA-5 computes SHA-256 of the whole file; KA-5 is called only on demand (the job
`link_check`). The KA-4 `cache` is a map owned by the caller (`(kind, code) → BBox`),
kept locally and read also without a network; missing unit footprints are filled in
with network access by a separate `footprints` job.

**Erratum 3 (2026-10-25, ADR-031):** one piece of the producer's format is judged in the
adapter: whether a directory is a store, by the file name and the schema of its marker
(`kartograf-store.json`, `kartograf-store/1`; `imgw-store.json` for the foreign root), because
Kartograf's public API has no function that tells a marked, an unmarked and a foreign directory
apart. It is a copy of producer knowledge kept until Kartograf offers `store_state(root)` (a
request); a contract test against the producer's own writers (`kartograf.testing`,
`kartograf.init_store`) pins it. The layout of the files below the marker stays Kartograf's.

---

## ADR-015: Packaging and running

**Date:** 2026-10-17
**Status:** accepted (erratum 2, user decision 2026-10-18)

**Context:** First a single person locally, later a team server. Users have a
Python environment with Kartograf.

**Options:**
- A) A Python package `archiwista` with a built-in, pre-built interface (`pipx`, `uv tool`).
- B) A Docker image only.
- C) A desktop application (Electron, Tauri).

**Decision:** A. The command `archiwista serve` (and `reindex` and `doctor`); configuration
in a TOML file in the user's configuration directory, index and cache
in the user's data directory. A Docker image is optional for a team
server.

**Consequences:** Node.js is needed only for developing the interface. Docker is not required
for a single person (mounting SMB in a container complicates the installation).

**Erratum 1 (2026-10-17, user decision — open architecture):** the architecture is
open again; the decision returns to the status proposed and will be confirmed or
changed before v0.1 (SCOPE, stage 0). The text above is the previous assessment, the
starting point for the decision.

**Erratum 2 (2026-10-18, user decision — stage 0):** decision confirmed. After
ADR-028 Node.js is not needed even for developing the interface: the interface
libraries are bundled with the package as ES modules files.

---

## ADR-016: Date format in the interface and the map basemap

**Date:** 2026-10-17
**Status:** accepted

**Context:** Questions M9 (date format in the interface) and P6 (online basemaps reveal
the area of interest to external servers) required a user decision after reviewing the
mockup.

**Options:**
- A) Dates `RRRR.MM.DD` in the interface, ISO `RRRR-MM-DD` in the API and files; OSM basemap
  in a monochrome version, online by default, with an offline mode.
- B) Dates `DD.MM.RRRR` as in the mockup; colour OSM.
- C) Local basemaps only (offline).

**Decision:** A. The format `RRRR.MM.DD` gives easy sorting in tables and on the Timeline;
the API, manifest, sidecars and file names stay in ISO `RRRR-MM-DD`. Version labels
(e.g. `2025-04-26_82710`) are identifiers and are not reformatted. The default
basemap is a grey OSM version (a neutral background for footprints and coverage labels), fetched
online; offline mode disables external browser requests; in a team the
administrator decides (SPEC 5.4, 15: P6).

**Consequences:** The interface formats dates from ISO at the presentation level (one helper
function); the screen sketches in SPEC use `RRRR.MM.DD`. The grey basemap style requires
a custom tile style or a browser filter; in offline mode "bez podkładu" (no basemap)
or a local basemap remains.

**Erratum 1 (2026-10-18, user decision — stage 10b of the v0.1 plan):** the default basemap
is the grey BKG TopPlusOpen ("web_grau", licence dl-de/by-2-0, attribution
"© BKG (2026), dl-de/by-2-0") instead of the grey OSM version. Archiwista sends
`Referrer-Policy: no-referrer`, and tile.openstreetmap.org without a `Referer` header returns
an "Access blocked" image instead of a tile (checked live); the terms of use for its
tiles also do not suit team work. The `Referer` policy stays unchanged. BKG tiles
are grey by nature, so a browser filter is not needed; OSM remains a basemap
that the user can add in the settings. `-m live` test:
`tests/integration/test_basemap_live.py`.

**Erratum 2 (2026-10-19, user decision — comments before the v0.2 release):** the default basemap
is OpenFreeMap vector tiles (`kind = "vector"`, TileJSON
`https://tiles.openfreemap.org/planet`, OpenMapTiles schema from OpenStreetMap data,
attribution "OpenFreeMap © OpenMapTiles Data from OpenStreetMap") in Archiwista's own
light grey style instead of BKG TopPlusOpen. TopPlusOpen is a German product: next to
Polish names it prints German exonyms ("Gdańsk / Danzig", "Wrocław / Breslau",
"Rixhöft" at Rozewie — checked live) and none of its variants omits them.
OpenFreeMap works without a key or registration, allows commercial use, responds without a
`Referer` header and with CORS `*`, and its tiles have `name:pl` worldwide (Prague,
Dresden, Vilnius, Lviv, Königsberg). The style labels only towns and waters (`name:pl`,
then `name:latin`, then `name`) with glyphs from the package, to which the ranges
U+0200–U+02FF and Cyrillic U+0400–U+04FF were added; it uses no external sprites or fonts.
The second built-in basemap is the raster OSM BaseMap of GUGiK (`grayscale = true`, attribution
"© OpenStreetMap contributors, GUGiK") — Polish names, but only in the area of Poland.
Rejected: VersaTiles (the same code, but a different schema and names without a Latin version, so
more glyphs), EOX (English names without Polish characters), CARTO (requires a key),
Wikimedia (only for Wikimedia projects), GUGiK TOPO and G2 maps (no EPSG:3857).
A configuration saved earlier (the wizard also saves the list of basemaps) keeps its
basemaps; the new built-in ones are obtained by removing the `[[basemaps]]` tables from `config.toml`. `-m live`
test: `tests/integration/test_basemap_live.py`.

---

## ADR-017: Grouped variants without file format

**Date:** 2026-10-17
**Status:** accepted

**Context:** The Kartograf availability report returns combinations with a format, so the same
set of sheets in two formats looks like two variants. Example: NMT 2019,
5 m, EVRF2007, submission DFT.7201.003.2019 is available as `ASC` and `ASCII-NMT`.
Two cards with the same year, coverage and sheets are confusing and inflate the counters
("N variants"), and the format does not change what data the area has.

**Options:**
- A) Variant = a report combination 1:1 (format in the key), as so far.
- B) Variant = (product, year, horizontal system, resolution, height system,
  submission/campaign); formats of the same set are badges on one card,
  the format is chosen at download.
- C) Change the Kartograf report so that it groups formats itself.

**Decision:** B (user decision 2026-10-17). The card carries badges, e.g. "5 m ·
EVRF2007 · ASC, ASCII-NMT". Archiwista does the grouping; `check_availability`
stays unchanged (C rejected: the report describes what the source publishes).
The counters, table, Timeline, "Stos" (Stack), "Katalog" (Catalog), file card, year ranking
and assistant plan count variants, not formats (SPEC 6.3, 6.4, 7.4). The format
is chosen only in "Pobierz…" (Download…) and "Oknie planu" (Plan window), by default the first
raster format ready for a mosaic (ASC, GeoTIFF); when there is none, the choice is
explicit. A mosaic accepts versions of a single raster format (SPEC 8.2).
The store badge counts units in the chosen format.

**Consequences:** The group key is a tuple computed from the report combination and sidecars
(the format is omitted, the submission stays); different submissions from the same year are
separate variants. The download plan must carry the format to the Kartograf command.
Extends ADR-010 (labels concern the variant, not the format).

---

## ADR-018: Interface patterns after the mockup: chat, Stack, previews

**Date:** 2026-10-17
**Status:** accepted (chat, previews; "Wachlarz" (the Fan) replaces "Stos" (Stack), erratum 1, user decision 2026-10-17)

**Context:** After reviewing the mockup, the user decided open question M6 (chat
position), formulated the requirement for the "Stos" (Stack) (M4, P12) and set the rule
for the weight of screenshots and previews.

**Options:**
- Chat: A) pinned side panel on desktop, drawer on phone;
  B) bottom panel; C) floating window.
- "Stos" (Stack): A) tilted slabs as before; B) a fan of layers like a stack of files
  in the macOS dock (every year visible, the selected one enlarged); C) removal of the view.
- Previews: A) full data and PNG; B) low resolution from overview overlays,
  screenshots WebP/JPEG about 1280 px.

**Decision:**
1. Chat: A. On desktop a pinned side panel (the map narrows), on phone a
   drawer (SPEC 6.2, 7.5).
2. "Stos" (Stack): requirement: the selected year is fully visible (SPEC 5.4, 6.5 c). Direction:
   B (fan); whether B is the final variant will be decided by checking
   in the mockup (M4, P12): open decision.
3. Previews: B. Raster previews in the application are low resolution, generated
   from overview overlays, not from full data (SPEC 5.7; amends ADR-008).
   Screenshots and previews in the repository are WebP or JPEG, width about 1280 px.

**Consequences:** Resolves M6 (position) and narrows M4/P12 to the choice of a layout
variant; the layout of the "Stos" (Stack) from the template of tilted slabs may change. Previews
serve recognition, not analysis; full data is opened in QGIS.

**Erratum 1 (2026-10-17, user decision after checking the mockup):** "Wachlarz" (the Fan)
**completely replaces "Stos"** (Stack): item 2 of the decision is resolved with variant B, and the
"Stos" (Stack) view (tilted slabs, option A) is removed from the spec and from the mockup together with the
"Wachlarz / Stos" switch. The view is called "Wachlarz" (the Fan) (the "Mapa / Wachlarz /
Katalog" switch, i.e. Map / Fan / Catalog): layers of years (campaigns, releases) as thumbnails of the area on an arc like a stack
of files in the macOS dock, the newest year on top, each thumbnail whole in its own
place, the selected one enlarged in the arc and large beside it; thumbnails show sheet footprints
in coverage colours, and sheets in the store, with a light preview (item 3). It is an
SVG interface component, not a map layer: `fill-extrusion`, camera tilt
and textures in deck.gl are dropped (erratum 1 of ADR-006). Resolves M4 and P12 (SPEC 5.4, 6.5 c, 15, 16).
Mentions of the "Stos" (Stack) in ADR-005, ADR-006 and ADR-017 describe the state at the time of the decision;
"Wachlarz" (the Fan) applies.

---

## ADR-019: Two store producers: Kartograf and IMGWTools

**Date:** 2026-10-17
**Status:** accepted (user decision 2026-10-17); partly supersedes ADR-003, amends ADR-014; amended by ADR-024 (adapters as plugins) and ADR-032 (the IMGW source: one plugin, the extra, read first)

**Context:** The user wants IMGW-PIB measurement data in Archiwista v1.0: daily
hydro (H, Q, T), monthly and half-year characteristics, and meteo (precipitation,
temperature), without current data. ADR-003 ("writes only through Kartograf")
and ADR-014 ("knowledge of the format only in Kartograf") assumed a single store
producer. IMGWTools 2.1.1 (Beta) knows the IMGW format (URLs, parsers, station lists), but
has no store: it writes flat and non-atomically, without sidecars, sums and versions, and the names
of daily and term meteo archives collide. The analysis of 2026-10-17
recommended IMGW as a Kartograf source; the user chose an IMGW adapter
in Archiwista, and Kartograf stays with spatial data.

**Options:**
- A) Archiwista reads the flat directory of `imgw fetch` or the IMGWTools SQLite cache with its own reader.
- B) IMGW as a Kartograf source: Kartograf the only writer, IMGWTools its optional dependency.
- C) IMGWTools writes in Kartograf's tree and format (`data/`, `kartograf-meta/1`).
- D) Two producers, each in its own directory and with its own documented
  format contract; Archiwista reads each through a separate adapter behind a common
  source interface.
- E) A common store contract library for both producers.

**Decision:** D (user decision 2026-10-17):
1. A store in Archiwista is a named set of producer directories: the Kartograf directory
   (`output_dir`, `data/` layout) and the IMGW directory (IMGWTools, `imgw-store/1`); neither
   lies inside the other. Each producer writes only its own directory and is the sole
   owner of its format.
2. Archiwista still never writes to the store; the index is local and rebuildable,
   with no SQLite on the share (ADR-002 and the "read-only" part of ADR-003 unchanged).
3. A separate adapter per producer (`archiwista/adapter/kartograf/`,
   `archiwista/adapter/imgw/`) is the only place that imports its library (import
   test as in ADR-004); the adapters implement a common source interface
   (SPEC 5.3), and the rest of Archiwista knows only that interface.
4. The IMGW adapter does not parse files: it reads through the public read API of IMGWTools
   (IMGW-10), just as the Kartograf adapter does through KA.
5. Actions on IMGW data (archive synchronisation, series, export) are performed by
   IMGWTools in worker processes; Archiwista shows the plan and the `imgw …` command.
6. IMGWTools writes raw IMGW archives 1:1 as immutable versions with a sidecar,
   `sha256`, `ETag` and `Last-Modified`, and station series as a derived product;
   the contract is requirements IMGW-1..IMGW-13 (SPEC 12.7) and the format from ADR-020.
7. IMGW data are not jobs of a Kartograf project (the manifest accepts only its
   commands); reproducibility is provided by immutable versions and the set (SPEC 4.7, 8.4; P18).

A gives no versions and no reproducibility, half-written files and SQLite (WAL) ruled out on a
share, and moves knowledge of the IMGW format into Archiwista (breaks ADR-014). B extends the
scope of Kartograf beyond spatial data, which the user does not want. C is two
implementations of one format in one tree: Kartograf's `iter_store` would see
foreign segments, `kartograf_version` and spatial fields would mean nothing, and the first
divergence breaks Kartograf's guarantees. E requires refactoring Kartograf's freshly released store
and three repositories in a step; with two producers that is premature
(it remains an option when a third arrives).

**Consequences:** Erratum to ADR-003 (writers: Kartograf or IMGWTools, each in its
own directory) and ADR-014 (knowledge of the format at each producer). Requirements
IMGW-1..IMGW-13 for IMGWTools; IMGW data enter in v0.9 (SPEC 13) and depend on the
release of IMGWTools with the contract. The version semantics are implemented by two repositories
(Kartograf's ADR-036 and the IMGW directory); the limitation is the simpler IMGW contract
(append-only, no links and no mutable files) and contract tests on both sides
(SPEC 11, 14). The source interface is created in v0.1 with one adapter, and a test with a stub
of the second ensures that the layers above do not depend on Kartograf. The store configuration
points to the producer directories; background jobs and assistant proposals carry the commands
of both producers (`producer`, SPEC 9.1).

**Erratum 1 (2026-10-17, user decision, SPEC 15, P18):** item 7 no longer applies:
IMGW data are project jobs and pins in v1.0, in the IMGWTools manifest
`imgw-project.json` (`imgw-project/1`) next to `kartograf-project.json`, changed
only through the IMGWTools API (requirement IMGW-14; ADR-023). The principle of a single owner of
the format (item 1) stays: the Kartograf manifest does not change. The requirements for
IMGWTools are from now on IMGW-1..IMGW-14 (SPEC 12.7).

**Erratum 2 (2026-10-17, user decision, ADR-024):** producer adapters are
plugins: Kartograf is a required dependency, IMGWTools the extra `archiwista[imgw]`;
a missing IMGWTools means an unavailable source, not a failure (SPEC 5.3).

**Erratum 3 (2026-10-19, user decision, IMGWTools 3.0.0 write model):**
in the Consequences "no links" means: no permanent hard links in the IMGW
directory (after publication every file has one name). IMGWTools 3.0.0 publishes versions
according to the Kartograf model (erratum to IMGWTools ADR-001 of 2026-10-19; Kartograf's ADR-036 D18, D21,
D22): files from `.incoming/` go into the version directory by hard
links `os.link`, the sidecar of the main file, linked last, commits the version,
and the `imgw-store.json` marker is also created by a hard link. A share
with the store must therefore support hard links for both producers (SPEC 4.6
items 1 and 9, checked by `archiwista doctor`); without them an IMGWTools write ends with
`IMGWStoreConflictError` (`not_atomic`). A version directory without a sidecar is an interrupted
or ongoing publication, not a version: `current_version` skips it, `iter_store`
reports `missing_sidecar`, and the IMGW adapter treats this as a non-critical
and possibly transient problem (SPEC 4.4, IMGW-2, IMGW-10). The simpler IMGW contract (append-only,
no overwriting and no mutable files) stays; the publication model is
now shared with Kartograf, which reduces the divergence between the two implementations (SPEC 14).

---

## ADR-020: IMGW data format: own sidecar, Parquet, GeoJSON

**Date:** 2026-10-17
**Status:** proposed, a requirement for IMGWTools; the final shape will be set by an IMGWTools ADR (SPEC 12.7–12.8)

**Context:** ADR-019 leaves the writing of IMGW data to IMGWTools with its own
format contract. A choice is needed for the sidecar schema (own or compatible with `kartograf-meta/1`),
the format of station series and the format of the station catalog. A station's daily series for 1951–2025 is
about 27 thousand days with several variables and flags; there are about 1,300 hydro and about
2,150 meteo stations. The catalog may sit on SMB without byte-range locks, and the IMGWTools core
is lightweight (`httpx`, `pydantic`).

**Options:**
- Sidecar: A) compatibility with `kartograf-meta/1`; B) own `imgw-meta/1` with a shared field envelope.
- Series: C) GeoPackage (points, observations and coverage in one file per area or
  country); D) Parquet, one file per station in an immutable version of the dataset's series, with an index
  `series.json`; E) CSV.
- Station catalog: F) GeoPackage; G) GeoJSON (RFC 7946).

**Decision:** B, D and G.
- B: only its producer knows and develops the format (ADR-019), and the schema name says who
  wrote the file; `kartograf-meta/1` written by IMGWTools would confuse Kartograf's `read_sidecar`, the QGIS
  plugin and Hydrograf (e.g. through the `kartograf_version` field). The spatial fields
  (`horizontal_crs`, `vertical_crs`, `resolution`, `nodata`, `transform`) mean nothing
  for archives and series, while units, missing-value codes, periods
  and stations are needed. A shared envelope (the same names and meanings of `schema`, `dataset`,
  `country`, `provider`, `request`, `license`, `downloaded_at`, `sha256`,
  `size_bytes`, `extra.version`, `extra.http`, `extra.derived`,
  `extra.source_files[]`) gives what compatibility would give: shared index columns,
  the same logic of versions and inputs, the HSG shape, without coupling the producers.
- D: typed columns (date, values, flags) with compression; the file is immutable and without
  locks, so it is safe to read on SMB; read directly by pandas, polars,
  pyarrow, DuckDB and R (Hydrolog, Retman, scripts); a file per station gives a small read
  for a chart and a set, and the `series.json` index with gap lists gives a coverage index
  from a single file. GeoPackage is SQLite: writing on a share requires building locally
  and copying, an area file duplicates stations between jobs, and a country file has to be
  read through queries; CSV carries neither types nor metadata, so it remains the export format
  for the set (IMGW-12).
- G: a few thousand points; written without GDAL (lightweight IMGWTools core), the file is readable
  and comparable between versions, and opens directly in QGIS; a missing location is expressed
  explicitly (`geometry: null`).

**Consequences:** Parquet writing and reading go into an IMGWTools extra (e.g.
`imgwtools[store]` with pyarrow); the core stays lightweight. Excel does not read Parquet, and QGIS
only with GDAL built with Arrow support, so the set gets series as CSV from the IMGWTools
export. A dataset's series version is a snapshot of all stations (simple identity
and years known from a single index) at the price of a full copy of the files with every new version;
the limit is `reused` when the set of input `sha256` values and the schema version are the same
(the HSG pattern, ADR-036 D33), which also protects against versions that differ only in the
bytes written by the Parquet library. The envelope is a candidate for a shared `store-meta/1`
if a third producer appears.

**Erratum 1 (2026-10-17, user decisions — SPEC 15, P13–P15, P18):** the column
`hydro_year` is in the series files of all datasets, including meteo (both kinds of years
for both kinds of data, P15); a dataset's series cover all stations, including those
with gaps (P14); a station without a location is in `stations.geojson` with `geometry: null`
and the reason for the missing location (P13, ADR-022); the schema `imgw-project/1` is added (ADR-023), covered by the
same version policy (SPEC 12.7: IMGW-7, IMGW-9, IMGW-13, IMGW-14).

---

## ADR-021: Coverage labels of IMGW series

**Date:** 2026-10-17
**Status:** accepted (P14, P15 — erratum 1; P16 — erratum 2; user decisions 2026-10-17; erratum 3: units known per ČHMÚ station; erratum 4: appearance, user decision 2026-10-26, M11)

**Context:** The user wants labels for the coverage of station series over time, e.g. "ciągły
1951–2024", "luki 3%", defined precisely. A station's coverage is known
only from the archives in the store (IMGW does not publish a station index); hydro archives
are numbered by hydrological year, meteo by calendar year; a missing Q does not mean
a missing H; Hydrolog warns for series shorter than 30 years.

**Options:**
- A) Numbers only (percentage of days with a value).
- B) "Ciągły" (continuous) with a tolerance (e.g. up to 0.1% of gaps).
- C) Five labels with definitions: "ciągły" (continuous; zero gaps), "luki N%" (gaps N%; rounded
  up, "<1%") with the longest gap, "częściowy" (partial; the station starts or ends
  within the range), "brak danych" (no data), "nieznane" (unknown; without archives); separately for each
  variable; the kind of years according to the dataset with a switch.

**Decision:** C (definitions: SPEC 4.8.4). "Ciągły" is a fact, not an assessment; a tolerance
would hide gaps that Hydrolog will encounter anyway; suitability is expressed separately by the number of full years
and the filter "≥ 30 lat pełnych" (≥ 30 full years). Rounding gaps up is cautious, like
"never 100%" in ADR-010. Unknown years (archives not downloaded, series not prepared)
are not gaps and get the suffix "· nieznane". The server computes the labels from the gap lists
in the series index (IMGW-8), so changing the range and the kind of years does not require reading
the series.

**Consequences:** IMGWTools writes the first and last date and the
gap list for each variable in the series index; Archiwista computes the labels, full years and the timeline
(the `series_years` index), and the interface, API and assistant share one vocabulary.
It extends ADR-010 (area labels) with the time dimension.

**Erratum 1 (2026-10-17, user decisions — SPEC 15, P14, P15):**
- P14: "ciągły" = zero gaps (confirmed). **All** data is downloaded and shown,
  including data with gaps, with a label; nothing is filtered out because of gaps:
  the map, "Zestawienie" (Summary), "Katalog" (Catalog), the set, export and assistant proposals cover
  every station, and coverage filters ("≥ 30 lat pełnych") work only when explicitly applied
  (SPEC 4.8.4).
- P15: both kinds of years for **both** kinds of data (hydro and meteo) with a switch
  (previously: "the kind of years according to the dataset with a switch"). By default hydro is
  hydrological and meteo is calendar; the choice is remembered separately for hydro and meteo
  in the user settings (in the team, with the account), `year_type` in the URL
  takes precedence; the mixed view uses the choice for hydro; half-year and annual
  characteristics stay in hydrological years, because IMGW computes them in the half-years XI–IV
  and V–X (SPEC 4.8.2, 6.7). Confirmed by the user on 2026-10-17:
  IMGW half-year and annual characteristics exist only in hydrological years,
  and the year-type switch does not apply to them.
- P16: see erratum 2.

**Erratum 2 (2026-10-17, user decision — SPEC 15, P16):** P16 resolved:
coverage labels are computed and shown **separately for each quantity**, not one
per station: hydro: H, Q and T; meteo: precipitation, air temperature (Tmax, Tmin, Tśr)
and other variables of the dataset. A station has no summary label. This changes the earlier
recommendation ("one variable at a time"): the station panel, "Zestawienie", "Katalog"
and the station card show the labels of all the station's variables together; the map colors
a point by one variable chosen with a chip ("Kolor punktów", Point color), but the point tooltip lists
all of them; coverage filters (full years, label) apply to the selected
variable and are combined with "and", so a missing Q does not hide H; the API returns
`coverage` separately for each variable (SPEC 9, `GET /stations`). The model (SPEC 4.8.4,
the `series_years` index) and IMGW-8 already computed coverage per variable, so what changes is the presentation,
the filtering and the shape of the API response, not the IMGWTools format contract
(IMGWTools requirements: IMGW-8).

**Erratum 3 (2026-10-19, compatibility audit with IMGWTools 3.0.0, answering question 11
of ADR-003 of IMGWTools; SPEC 4.8.6):** in datasets with station files (ČHMÚ), the units known
for a station are the units of its periods from the series index (`stations[<code>].periods`, ADR-003 D10
of IMGWTools), not of the periods of the whole dataset: a year without a station file, including one not
published by ČHMÚ, is "unknown", not a gap, while missing rows within a known period are a gap;
K₁, K₂ and the "known year" are computed per station. For IMGW-PIB national archives nothing changes
(the dataset's `periods`). The label definitions are unchanged (SPEC 4.8.4).

**Erratum 4 (2026-10-26, user decision — SPEC 16, M11):** the appearance of the labels
is decided. The colours are those of "pełne" (green) and "częściowe" (amber) of ADR-010,
told apart also by fill and outline for colour-blind users: "ciągły" green with a solid
fill, "luki" orange with a solid fill, "częściowy" orange with a half fill, "brak danych"
grey and hollow, "nieznane" a grey dashed outline. On the map the fill is that of the point
and its shape says the station type (water gauge a triangle, climatological station a
square, precipitation post a circle), so colour carries only coverage; clusters are
neutral. In the Timeline (a tab of the "Katalog") the colour saturation of a year's cell
is the share of units with a value. The previous appearance (gaps green with dashes,
partial amber with hatching, no data grey with dots, unknown with "?") is replaced. The
label definitions are unchanged (SPEC 4.8.4, 6.7).

---

## ADR-022: Data without location: Catalog instead of the map

**Date:** 2026-10-17
**Status:** accepted (user decision 2026-10-17; SPEC 15, P13)

**Context:** Part of the data has no location: of the 2,149 codes on the IMGWTools meteo list,
the public IMGW API has coordinates for 562 stations, 32 stations of the hydro API have placeholder
`0,0`, closed stations often have no coordinates in any source; on the Kartograf side
there are files for which `file_footprint` finds no extent ("no
footprint"), and IMGW archives and series have the extent of the whole country. Question P13 concerned the
source of meteo station coordinates; the user decided that stations without
coordinates are not shown on the map, and that Archiwista needs a second way of
presenting data with no spatial reference — in general, not only for IMGW.

**Options:**
- A) Approximate location on the map (e.g. the centre of a 1° square from the station code) with a marker.
- B) A separate "Bez położenia" (No location) list only for IMGW stations, next to the map.
- C) A general rule for all producers: the map shows only objects
  with a location, and all objects — including those without a location — are shown by a view without a map
  (the "Katalog" (Catalog): a list and cards with search and attribute filters); the map has a counter
  of objects without a location with a link to the "Katalog" (Catalog).

**Decision:** C (user decision 2026-10-17). A guesses the location (a 1° square is
tens of kilometres) and breaks the "never guess" rule; B solves one
case and leaves Kartograf's files "without footprint" without a view. Rules (SPEC 4.3,
6.8):
1. Every index object has a location kind: `footprint`, `point`, `country` or
   `none` with a reason (files: `no_source`, `unreadable`; stations: the reason from the station catalog of
   IMGWTools — `none`, `zero`, `outside_country`).
2. The map draws only `footprint` and `point`; location is never guessed.
3. The "Katalog" (Catalog) (a navigation item and a mode of the "Mapy" (Maps) view) shows all location kinds;
   the area filter splits the result into the groups "w obszarze" (in the area), "na granicy obszaru" (on the area boundary), "cały
   kraj" (whole country), "bez położenia" (no location) with counters, and the "bez położenia" group is never added to
   the area nor silently removed from it. Objects without a location are selected with
   attribute filters (river and hydrographic code with tributaries — P19, name, code, country,
   unit); the 1° square from the station code is only a rough hint.
4. Every map view with a result shows a counter of objects without a location with a link to
   the "Katalog" (Catalog) with the same filters.
5. The producer supplies the location (e.g. a new version of the IMGWTools station catalog with a
   user coordinates file); Archiwista does not write it.

**Consequences:** The index stores the location kind and the reason for its absence (`versions`,
`stations`); the API `GET /slots` and `GET /stations` accept `location` and return groups
with counters; the IMGWTools station catalog stores stations without a location as full
entries (`geometry: null` with a reason, IMGW-9). Stations without a location go into project
jobs and sets only explicitly, and in a set they are a table, not a map layer. The "Katalog" (Catalog)
is in v0.1 (files "without footprint") and in v0.9 (stations). The coordinate sources from P13 (IMGW
API, user file, a request to IMGW-PIB for a list) remain a supplement.

---

## ADR-023: IMGW data in projects: the IMGWTools manifest

**Date:** 2026-10-17
**Status:** accepted (IMGW data in the project manifest in v1.0 and two manifest files, `kartograf-project.json` and `imgw-project.json` — user decision 2026-10-17, confirmed; SPEC 15, P18; erratum 2: shape of `imgw-project/1` from IMGWTools 3.0.0)

**Context:** ADR-019 point 7 and the previous recommendation for P18 excluded IMGW data
from projects in v1.0, because the `kartograf-project/1` manifest accepts only Kartograf
commands; rebuildability was provided by the set itself (`zestaw.json`). The user decided that
IMGW data should be in the project manifest already in v1.0: jobs (stations, variables, years)
and pinned versions, with "Status" (Status), "Weryfikuj" (Verify), update and restoring on a colleague's machine
— just like Kartograf data. An IMGW job is to get into the project through the IMGWTools API.

**Options:**
- A) IMGW jobs in `kartograf-project.json` (Kartograf accepts foreign commands or
  calls IMGWTools).
- B) A shared producer manifest (e.g. `store-project/1`) and a shared
  project library for both producers.
- C) An IMGWTools manifest `imgw-project.json` (`imgw-project/1`) in the same project
  directory next to `kartograf-project.json`; each manifest has one owner,
  and Archiwista shows the project as the sum of both.
- D) No manifest: IMGW selection only in the set (the previous recommendation).

**Decision:** C. Consistent with ADR-019 (each producer is the sole owner of its
format, no dependency between Kartograf and IMGWTools) and with ADR-014 (Archiwista does not
write producers' formats). A breaks both: Kartograf would have to know IMGW commands or run them,
and `kartograf-project/1` would change beyond additive extensions. B is a
refactor of Kartograf's freshly released manifest and of three repositories in one step —
premature with two producers (like option E in ADR-019). D does not meet the user's
decision. Shape (SPEC 12.7, IMGW-14): `schema`, `store_dir`, `tasks[]` (`name`,
`command`, `options` — a dataset, stations as an explicit list of codes, variables, years,
`year_type`; for area selection also `geometry` and `geometry_sha256`), `pinned_at`,
`imgwtools_version`, `files[]` (`role`, version `path` relative to `store_dir`,
`sha256`, `station`); API = CLI (`init_project`, `open_project`, `add_project_task`,
`remove_project_task`, `download_project`, `check_project`, `verify_project`,
`get_project_status`; `imgw project …`); atomic write under the lock
`.imgw-project.lock` — following Kartograf's manifest.

**Consequences:** New requirement IMGW-14 (v0.9, needed for v1.0). Archiwista
discovers projects by both files, shows the jobs of both producers with a producer
column, and "Dodaj do projektu…" (Add to project…) for stations opens the "Okno planu" (Plan window) with the command
`imgw project add` and calls the IMGWTools API in a worker process (SPEC 4.7). The set takes
IMGW versions from the pins, `zestaw.json` stores the sums of both manifests, `polecenia.sh` —
`imgw project download` (SPEC 8.4). The risk of inconsistency between the two manifests (e.g. the same
job name) is limited by a project view with a warning (SPEC 14). When a third
producer appears, option B returns. Changes point 7 of ADR-019 (erratum 1).

**Erratum 1 (2026-10-17, user decision — SPEC 15, P18):** two manifest files
confirmed (option C): `kartograf-project.json` and `imgw-project.json`; status
changed from "Proponowana" (proposed) to "Przyjęta" (accepted). The field names of `imgw-project/1` recorded
in requirement IMGW-14 remain the names from the requirements for IMGWTools (as in
all IMGW-n requirements), with no effect on the status of the decision.

**Erratum 2 (2026-10-19, compliance audit with IMGWTools 3.0.0 — answer to question 13
of ADR-003 of IMGWTools):** the shape of `imgw-project/1` in IMGWTools 3.0.0 (ADR-001 and ADR-003
of IMGWTools) differs from the names in requirement IMGW-14: in `files[]` the station is `station_code`,
and a dataset pin with a canonical form (ČHMÚ) also has `content_sha256` and `content_form`; the file
of area selection is in `options.geometry`, and `geometry_sha256` is a job field (a map
path → SHA-256); the manifest may have `extensions`; `set_project_store`
(`imgw project set-store`) was added. A job concerns one dataset, and so one provider —
a project combines IMGW and ČHMÚ jobs. Restoring: identical `sha256` or — for ČHMÚ —
explicitly by content (`restored_by_content`, job state `content_match`, message
`pin_restored_by_content`); Archiwista shows this state separately from "bieżące" (current), not as an
error, and never re-pins silently. The decision (option C) is unchanged; SPEC 12.7 (IMGW-14,
IMGW-19), 13 v0.6 criterion 7.

---

## ADR-024: Data sources as plugins: Kartograf required, IMGWTools optional

**Date:** 2026-10-17
**Status:** accepted (user decision 2026-10-17); amends ADR-001 and ADR-019; amended by ADR-032 (the IMGW source)

**Context:** ADR-001 adopted Kartograf as a dependency, and ADR-019 added a second
producer, IMGWTools, behind a common source interface. They did not settle how
Archiwista declares both libraries in the package. IMGWTools 2.1.1 is in Beta,
still without a store contract (IMGW-1..IMGW-14), while Kartograf is the basis of v0.1..v0.8.
Archiwista releases cannot wait for IMGWTools, and version conflicts between the
scientific libraries of the two producers must not prevent installation for people who
are not interested in IMGW. The user decided on the plugin model.

**Options:**
- A) Both libraries required.
- B) Kartograf required, IMGWTools optional (extra), source adapters registered
  as plugins through entry points.
- C) No dependency on producers: Archiwista reads file formats and calls the CLI.
- D) Producers as HTTP services.

**Decision:** B (user decision 2026-10-17):
1. Kartograf is a required dependency of the `archiwista` package (`kartograf>=0.9,<0.10`;
   the exact range is set at the Archiwista release).
2. IMGWTools is the extra `archiwista[imgw]`; installation: `pip install archiwista`
   or `pip install "archiwista[imgw]"`.
3. Source adapters (ADR-019 item 3) are registered through entry points, e.g. in the group
   `archiwista.sources`. A missing producer package means "source unavailable",
   not an application failure:
   - the interface hides the IMGW station views (the station layer, "Zestawienie" (Summary) and the "Karta
     stacji" (Station card));
   - the API returns a clear source-unavailable error (code and message in Polish, SPEC 9.1);
   - the assistant does not offer IMGW tools (SPEC 7.3).
4. At startup (and in `archiwista doctor`) Archiwista checks the versions of the producers
   and the schemas it reads: `kartograf-meta/1`, `kartograf-project/1`, `imgw-meta/1`,
   `imgw-project/…`; a mismatch ends with a readable message in Polish (what is
   installed, what range is supported, what to do) and affects only the source
   concerned.
5. One dependency lock file for a consistent set of scientific libraries
   (including the `[imgw]` extra), so that both sources work in one environment.
6. CI in two configurations: without `[imgw]` and with `[imgw]`, plus contract tests
   against the producers' `develop` branches (early detection of breaking changes).
7. A third producer is a new plugin (a new adapter and entry point) with no changes
   in the layers above.

Rejected: A — IMGWTools in Beta would block Archiwista releases, and version conflicts
between the scientific libraries would make installation harder; C — no dependency, reading
formats and calling the CLI, breaks ADR-014 (knowledge of the format only at the producer);
D — HTTP services: cost (additional processes, authentication, deployment).

**Consequences:** Changes in SPEC: 5.1–5.3 and 5.5 (source interface, plugin
registration, installation and configuration), 7.3 (tools depending on available sources),
9.1 (source-unavailable error), 11 (two CI configurations, contract tests), 13
(v0.1: plugin mechanism with a mock second adapter; v0.9: the `[imgw]` extra), 14
(the dependency on IMGWTools is now optional). The import test from ADR-019 stays,
and Archiwista without IMGWTools passes the full test suite except the IMGW tests.
The dependency on IMGWTools now limits only v0.9, not releases v0.1..v0.8.

**Erratum 1 (2026-10-18, user decision):** item 1 — the range is `kartograf>=0.8.0,<0.9`,
not `>=0.9,<0.10`: public store reading (KA-1..KA-6) enters Kartograf 0.8.0
(a prepared, not yet tagged release; `__version__` = `0.8.0`). The contract test
checks the presence of KA in `kartograf.__all__` and that the installed `kartograf.__version__`
falls within the range from `pyproject.toml`; before the Archiwista release it is repeated
against the tagged Kartograf 0.8.0. SPEC 5.8.

---

## ADR-025: MVP scope and release order

**Date:** 2026-10-17
**Status:** accepted (user decision 2026-10-17)

**Context:** The SPEC 13 roadmap had ten versions, and v1.0 covered everything:
browsing, previews, actions, the QGIS set, the assistant, merging, team mode
and IMGW data. Before the implementation plan, the user wants to establish exactly the product
requirements and scope (new documents `docs/PRD.md` and `docs/SCOPE.md`, the pattern of the project
family: Hydraulik, Kartograf, Hydrolog).

**Options:**
- A) Leave v1.0 as the whole roadmap.
- B) Separate the MVP from selected areas, move the rest beyond the MVP.

**Decision:** B (user decision 2026-10-17). MVP = v1.0 and covers: the Browser, 
Previews and the Fan, Actions, Team mode, IMGW data. After the MVP: the QGIS set,
the Assistant, Merging. New numbering (old → new): v0.1, v0.2, v0.3 unchanged;
v0.8 "Zespół" (Team) → v0.4; v0.9 "Stacje IMGW" (IMGW stations) → v0.5; v1.0 "Wydanie" (Release) → v1.0 "Wydanie
(MVP)" (Release (MVP)); v0.4 "Zestaw" (Set) → v1.1; v0.5 "Asystent" (Assistant) → v1.2; v0.6 "Mozaika i porównanie" (Mosaic and comparison)
→ v1.3; v0.7 "PL + CZ" → v1.4. The parts of the former v0.9 that depend on the set and the assistant
(the set with IMGW data, the assistant's IMGW tools, UC-18) move to v1.1 and v1.2.
Requirements KB-6, KD-3, KD-4 go with the "Zestaw" (Set) (v1.1) — to be confirmed (PRD, open
decisions). Before v0.1 comes stage 0 "Architecture and plan" (open architecture:
ADR-004..008, 015).

**Consequences:** The order and scope of releases are defined by `docs/SCOPE.md`; SPEC 13 holds
the details and acceptance criteria in the new numbering; SPEC and the requirements list of IMGWTools
(since removed, see SPEC 12.7) renumbered. Earlier entries of this log keep the numbering from the time of the decision
(e.g. "v0.9" in ADR-019..024 = today's v0.5, "v0.8" = v0.4). The MVP depends on the release of
IMGWTools with IMGW-1..IMGW-14; team mode enters the MVP before IMGW data.

**Erratum 1 (2026-10-18, user decision):** KD-4 (availability of releases of single-sheet
products, e.g. BDOT10k) moves from v1.1 to v0.3, so that products without sheets have in the
MVP coverage labels and full views (PRD F6.3, "Widoki według rodzaju danych" (Views by data type)).
KD-3 and KB-6 stay in v1.1 — still to be decided.

**Erratum 2 (2026-10-18, user decision):** KD-3 (availability of PL images: years
and sheet completeness of orthophotomap, true ortho and intensity) moves to v0.3 — without
it the orthophotomap in the MVP has no years with coverage labels (PRD F6.4). KB-6 ("Polecenie
Kartografa" (Kartograf command) and "Dodaj do projektu" (Add to project) from the file card) stays in v1.1: in the MVP data is added to the project
from the availability result.

**Erratum 3 (2026-10-18, user decision):** the "PL + CZ" release changes its number
from v1.4 to v0.6 and enters the MVP (between v0.5 "Stacje IMGW" (IMGW stations) and v1.0). Scope of v0.6:
PL + CZ summary without merging (the `parent_request` group, consistency check),
merged border-area surface through KF of Kartograf (SPEC 8.3) and ČHMÚ stations
through IMGWTools in the v0.5 views (SPEC 4.8.6, requirements IMGW-15..IMGW-19). Export
of PL + CZ without merging to the QGIS set stays in v1.1. After the MVP: v1.1 "Zestaw" (Set), v1.2
"Asystent" (Assistant), v1.3 "Mozaika i porównanie" (Mosaic and comparison). Consequences: KF (today R6 in the Kartograf
backlog, outside the public API 0.8.0) and the ČHMÚ provider in IMGWTools (today a draft
"Obserwator", without code) block the MVP — risks in SCOPE and SPEC 14. ČHMÚ stations go
through the IMGW adapter (the plugin from ADR-024); a separate adapter only if IMGWTools
releases ČHMÚ as a separate package (open question in the PRD). Changes: SPEC header, 2,
3 (UC-09, UC-20), 4.8.6, 5.3, 6.7, 8.3, 8.6, 10.2, 11, 12.5, 12.7, 13, 14; PRD F12,
F14, F17, assumptions, success measures, open decisions; SCOPE; README; plan v0.1
(scope boundaries); the requirements list of IMGWTools (IMGW-15..IMGW-19; since removed, see SPEC 12.7).

---

## ADR-026: MIT license and contributions with a CLA

**Date:** 2026-10-17
**Status:** accepted (MIT license — SPEC 15, P8; CLA — Erratum 1, user decision 2026-10-18)

**Context:** The repository had no license file and no contribution rules. All of the author's
projects (Kartograf, Hydraulik, Hydrograf, Hydrolog, IMGWTools, Retman) are under the
MIT license; Hydraulik additionally has `CONTRIBUTING.md`, `CONTRIBUTORS.md` (a register
of signatures) and `docs/CLA.md` — an adaptation of the Apache ICLA 2.2 with the recipient named as a person
(Piotr de Bever), not as a project.

**Options:**
- A) MIT, contributions with a CLA as in Hydraulik (signature as a comment in the pull request).
- B) MIT, DCO (`Signed-off-by`) without transfer of rights.
- C) MIT without a CLA (contribution under the same license, inbound = outbound).

**Decision:** A — the pattern of the project family. Files: `LICENSE` (MIT, Copyright (c) 2026
Piotr de Bever), `CONTRIBUTING.md` and `CONTRIBUTORS.md` in Polish (Archiwista's language
rule), `docs/CLA.md` unchanged from Hydraulik (legal text in English;
the recipient is a person, so the same text applies in every project of the author). The choice of the CLA
over B and C awaits the user's confirmation.

**Consequences:** The CLA preserves the option of changing the license in the future; it requires
manual maintenance of `CONTRIBUTORS.md` when merging. Archiwista's dependencies must have
licenses compatible with MIT; a copyleft dependency requires a separate decision (PRD N7.2). The CLA was not
reviewed by a lawyer (disclaimer in `docs/CLA.md`).

**Erratum 1 (2026-10-18, user decision):** the CLA is accepted ("we use what we
already have"). IMGWTools already has the same process (commit `999c8a7`: `docs/CLA.md` identical
to Hydraulik's, `CONTRIBUTING.md`, `CONTRIBUTORS.md`, the pull request template
`.github/pull_request_template.md`); the other projects (Kartograf, Hydrograf, Hydrolog,
Retman) have only the MIT `LICENSE`, and none uses the DCO. Archiwista also gets a pull request
template with a CLA signature field (in Polish; without items about tests until there is code).

**Erratum 2 (2026-10-18, user decision):** Polish in `CONTRIBUTING.md`,
`CONTRIBUTORS.md` and the pull request template is an error — files for contributors are in
English, as in Hydraulik and IMGWTools (all code and everything that describes it is in English;
`CLAUDE.md`, DEV-2.1). The translation is the first job of the
implementation (`docs/PROGRESS.md`).

---

## ADR-027: Own data in the project directory and Archiwista snapshots

**Date:** 2026-10-18
**Status:** accepted (user decision 2026-10-18)

**Context:** Users have their own datasets (e.g. a linear layer of a sewer network)
that they want to see on the map together with the project data and to version. Until now Archiwista indexed
only the producers' directories (Kartograf, IMGWTools), and a file without a sidecar was
a store "problem"; Kartograf does not know files it did not download. The user chose a
read-only folder in the MVP, versioning by snapshots of whole files, and decided that
Archiwista makes the snapshots, because users will not make them consistently themselves.

**Options:**
- Where own data lives: A) a folder assigned to the project; B) folders in the store settings,
  independent of projects; C) both.
- Who makes snapshots: A) the user (copies with a date in the name), Archiwista recognizes them;
  B) Archiwista in the project directory; C) Kartograf through the API (own data in the store);
  D) a separate small producer as a plugin.
- What a version is: A) a snapshot of the whole file; B) the history of individual objects.

**Decision:** a folder assigned to the project (A), snapshots made by Archiwista in the project
directory (B), version = a snapshot of the whole file (A):
1. The project's own-data folder — by default `<project directory>/dane/`, another one can be
   specified; the assignment is in Archiwista's configuration, not in the producer's manifest. The folder is
   indexed read-only (generic kind, PRD N8.3).
2. "Zrób migawkę" (Make a snapshot) copies the file to `<data folder>/.wersje/<name>/<YYYY-MM-DD>_<sha8>/`
   with `migawka.json` (`archiwista-snapshot/1`; the directory and schema names are a proposal for the
   v0.2 plan). The contract is deliberately the simplest: append only (no overwriting, deleting
   or links), atomic write (working directory `.incoming/`, publication by rename, error
   if the target exists), a consistent copy of a file in use (GeoPackage through the SQLite
   backup, multi-file formats as a complete set), the same content = no new snapshot.
3. Snapshots are file versions in the interface (version axis, "Wachlarz" (the Fan), curtain, comparison of
   metadata); a change to the file since the last snapshot is detected by a scan.
4. Scope: v0.2 (MVP); in a team the snapshot is made by the "operator".

Rejected: recognizing manually made copies — users will not make them
consistently; Kartograf — private data in a public-data store, a new role for
Kartograf and an MVP dependency on its release; a separate producer — a third library to
maintain; object history — a class of editing tool, outside Archiwista's boundaries.

**Consequences:** Archiwista writes data for the first time (copies of user files),
but only in the project directory and on the user's command — like area files
and sets; the producers' store remains read-only (ADR-003, ADR-019 unchanged).
Snapshots are not Archiwista state: they cannot be rebuilt, so they are in an open format,
readable without Archiwista, and move with the project directory. This is the third implementation
of version semantics (besides Kartograf's ADR-036 and the IMGW catalog) — hence the minimal contract
and the interruption tests. Own data does not go into the project manifest (no pins,
"Weryfikuj" (Verify) and no reproduction on a colleague's machine). Changes in SPEC: 1.3, 2, 4.7.1, 10.1, 13 (v0.2);
PRD F15, N2.5; SCOPE.

**Erratum 1 (2026-10-18, user decision, ADR-029):** in a team the snapshot is made by
the project owner or an administrator (the "operator" role is gone); the visibility of own data and snapshots
follows the project's visibility.

**Erratum 2 (2026-10-20, v0.2 implementation):** the names `.wersje/`,
`migawka.json` and `archiwista-snapshot/1` are accepted. A folder other
than the default is set by the administrator, and the default one is also checked
against the store roots and the local data directory; a problem
with the folder or an unfinished snapshot is shown at the project, not in "Magazyn" (Store).
The GeoPackage reader distinguishes three states of SQLite files and does not write
next to the source file; content identity is a logical SQLite hash
that omits derived spatial indexes. The permission for
a snapshot is `project.write` (the owner or an administrator).

---

## ADR-028: UI in Preact + htm without a build step

**Date:** 2026-10-18
**Status:** accepted (user decision 2026-10-18); supersedes ADR-005

**Context:** Stage 0 (SCOPE) settles the architecture again. ADR-005 chose Svelte
with Vite, which introduces a second ecosystem (Node.js, a build step) — a maintenance-cost
risk (SPEC 14). Meanwhile the mockup (SPEC 16) works in Preact + htm without a build
and has tested the main screen: the map, the Fan, the Catalog, panels, jobs, own data.

**Options:**
- A) Svelte 5 + TypeScript + Vite (ADR-005).
- B) Preact + htm, ES modules without a build step, libraries bundled in the package.
- C) Server templates + htmx.

**Decision:** B. One tooling ecosystem (Python); the mockup is the starting point of the
interface; the libraries (Preact, htm, MapLibre) sit in the package as ES module files —
no CDN, works offline and satisfies the CSP from SPEC 10.1. The principles from ADR-005 stay: one HTTP
API ("API first"), view state in the URL.

Rejected: A — a second ecosystem to maintain and a rewrite of the mockup; C — the main screen is
a map application with shared state, which in htmx falls apart into HTML fragments
and hand-written JS.

**Consequences:** No type checking in the interface — limited by browser tests
(Playwright) and JSDoc annotations. Reversibility: adding Vite and TypeScript later does not
require rewriting the components. Changes in SPEC: 5.1, 5.2, 14 (the "two ecosystems" risk),
15 (P11).

---

## ADR-029: Store write role and project sharing

**Date:** 2026-10-18
**Status:** accepted (user decision 2026-10-18); amends ADR-013; erratum 1: the own-data folder is set by the administrator until v0.4; erratum 2: the owner sets it from v0.4, scans, LDAP/AD groups deferred

**Context:** A company deploys Archiwista with one central Kartograf store.
Users also have their own projects with versioned own data (ADR-027) and want to
decide who sees them: a public project (the whole company), selected people, a selected group
(e.g. a department) or a private one (the owner only). Team mode (ADR-013, v0.4) provided
login and the roles "czytelnik" (reader), "operator" (operator), "administrator" (administrator) (SPEC 10.2), but did not say
who may write to the central store or how to share projects. It must also be decided
where Archiwista's responsibility for security ends. The user wants these
requirements early, not as an add-on after the MVP.

**Options:**
- Permission boundary: A) Archiwista enforces permissions only within its own surface;
  B) Archiwista also manages file permissions on the server and the share.
- Writing to the store: A) any "operator"; B) a separate permission for the Archiwista
  administrator and selected people, with a setting "everyone".
- When the permission model: A) together with login in v0.4; B) model and enforcement from v0.1
  (one local owner), login and screens in v0.4; C) after the MVP.

**Decision:** boundary A, writing B, model B:
1. **Responsibility boundary.** Archiwista enforces permissions only within its own
   surface: the interface, the HTTP API, the CLI, agent tokens and the preview cache.
   The security of the server and the share, and who has access to the file system, belong to the
   server administrator, not to Archiwista. A person with access to the share sees the files
   regardless of the project settings in Archiwista; the deployment documentation says this
   explicitly.
2. **Roles:** "administrator" (`admin`; the administrator of the Archiwista system, not of the server:
   settings, stores, accounts, groups, permissions), "zapis do magazynu" (store write)
   (`store_writer`) and an ordinary "użytkownik" (user) (no roles). They replace the roles "czytelnik" (reader),
   "operator" (operator), "administrator" (administrator) from SPEC 10.2. Writing to the central store only
   through the Kartograf API (and IMGWTools) and only with `store_writer`; the setting
   `store_write_for_all` grants it to everyone. Project changes (manifest, snapshots,
   sharing) are for the owner and the administrator; downloading into the store additionally requires
   `store_writer`.
3. **Project visibility:** `public` (everyone), `users` (selected people), `group`
   (a selected group, e.g. a department), `private` (the owner only); the administrator sees
   all projects (management, ownership transfer). A project without an entry (found
   by a scan) has the visibility from the setting `default_project_visibility` (default `public`).
   Everyone sees the central store; visibility applies to projects, their own data,
   snapshots and pins. Index queries (project list, "Przypięta w:" (Pinned in:), search)
   and the preview cache of own data filter by visibility; an invisible project
   = `404`, lack of permission for an action = `403`.
4. **Order:** v0.1: the model, enforcement in the API, CLI and queries for one
   local owner, verified by tests with multiple identities at the service and API level;
   administrative API and CLI for accounts, groups and sharing; a log of permission changes.
   v0.3: `store_writer` checked for actions (downloading through
   Kartograf). v0.4: login, account management in the interface, the sharing
   screen, optionally groups from LDAP/AD.
5. **`Principal`** (`id`, `kind`, `roles`, `groups`) is accepted by every service and every query.
   In local mode it is the owner with the roles `admin` and `store_writer` (the dependency
   `current_principal`, step 8 of the v0.1 plan); authorization: `can(principal, action,
   resource)` and the filter `visible_projects(principal)`.
6. **State that is not rebuildable, separate from the index.** Accounts, groups, memberships, roles, project
   visibility entries and the permission change log do not result from files on disk,
   so they live in a separate local state database (`<user_data_dir>/state.sqlite`), never on
   the share or in the store. Rebuilding the index does not touch it; backup through
   `archiwista state export`, restore through `archiwista state import` into an empty
   database. The project key in the state database does not depend on the index
   (the project directory after `realpath`).

Rejected: managing file permissions on the server, because it requires system privileges, duplicates
server administration and gives a false sense of protection; writing for every "operator",
because in a company the central store is shared and its growth should be controlled by a designated person;
the model together with login or after the MVP, because filters added to finished layers are easy to
miss (a leak through search, "Przypięta w:", previews), while a model from v0.1 is
cheap when services accept `Principal` from the start.

**Consequences:** From v0.1 Archiwista has a second local database: the index (rebuildable)
and the state (not rebuildable: schema migrations instead of rebuilding, export). The principle "Archiwista's
state can be rebuilt" applies to the index, previews and job history, not to the state database.
Local mode works as before (one owner with all permissions); accounts
created in v0.1 cannot log in before v0.4. Aggregate reports (e.g. "not used by
any project") count all projects, but give names only for visible ones. Changes:
SPEC 1.3, 1.4, 3 (UC-14), 4.3, 4.7.1, 5.3, 9.1, 9.2, 10.2, 11, 13 (v0.1, v0.3, v0.4,
v0.5), 14; PRD F10, F16, N2.3, N5.2; SCOPE; v0.1 plan (step 8b, steps 9a, 11, 12,
gate).

**Erratum 1 (2026-10-19, v0.2 plan after review — SPEC 4.7.1):** item 2 ("project
changes: the owner and the administrator") in v0.2 and v0.3 does not cover the own-data
folder: a folder other than the default (`<project directory>/dane/`) is set only by the
administrator (`settings.write`, `PUT /projects/{project}/data-dir`), because the folder is
the place where snapshots are written and must lie outside the stores, Archiwista directories and the folders
of other projects; setting it by the project owner is a decision for v0.4 together with the sharing screen.
Snapshots (`project.write`: the owner or the administrator) follow
item 2. Scanning the data folder is a read, not a project change: anyone who sees the
project may request it (only that project's folder), while a pass through the folders of all projects
is done only by the scheduler; the results are filtered by visibility (item 3).

**Erratum 2 (2026-10-26, v0.4 decisions by delegated approval, ADR-047; plan
`docs/plans/2026-10-26-plan-v0.4.md` step T7):** what erratum 1 left to v0.4.
- The data folder of a project is set by its owner or an administrator (`project.write`, `PUT
  /projects/{project}/data-dir`), with the rules of erratum 1 (absolute; after `realpath` outside
  the stores, Archiwista's data directory and the folders of other projects; no symbolic link
  out). For an owner who is not an administrator the folder must also lie inside the project's
  directory (after `realpath`; reason `own_data_dir_outside_project`): Archiwista reads the folder's
  files, previews them and from v0.4 serves them to everyone who sees the project, so a folder
  elsewhere would let an owner expose any directory the server can read. A change is logged
  (`project.data_dir`).
- A scan of one project's data folder: anyone who sees the project, as before, at most one
  waiting or running per person and one start per project a minute (`429 rate_limited`, reasons
  `scan_running` and `scan_too_soon`, with `Retry-After`; a waiting scan covering the folder is
  still joined). Scans of a store (`scan`, `footprints`, `link_check`: the new action
  `store.scan`) and the pass over every project's folder: administrators and the scheduler.
- Creating a project: ADR-039 erratum 3 (the author's decision: every signed-in person, who
  becomes the owner).
- Item 4's "optionally groups from LDAP/AD" is deferred (ADR-046 decision 9); groups are
  managed in Archiwista.

---

## New ADR template

Copy the block below when adding a decision: the next number, a status from the
vocabulary at the beginning of the file, a new row in the index and cross-references on both
sides of the relation. Add errata at the end of the entry.

```markdown
## ADR-XXX: Title

**Date:** YYYY-MM-DD
**Status:** accepted | proposed | accepted, partly superseded by ADR-YYY (scope) | accepted, amended by ADR-YYY (scope) | superseded by ADR-YYY | rejected

**Context:** Why the topic arose.

**Options:**
- A) ...
- B) ...

**Decision:** Which option and why.

**Consequences:** What follows from this.

**Erratum 1 (YYYY-MM-DD, source/reason):** Added later.
```
