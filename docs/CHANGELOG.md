# Changelog

Notable changes of Archiwista by release. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the version
numbers follow [SemVer](https://semver.org/). Before v1.0 the HTTP API and the
command-line interface may change.

## [Unreleased]

### Added

- `scripts/gate.sh` runs ruff format, ruff check, mypy, one pytest call with the
  coverage floor of 80% and the commit check (`scripts/check-commits.sh`: Conventional
  Commits, no AI attribution, author) before every commit; `.editorconfig`,
  `.gitattributes` (LF endings, vendored libraries byte for byte) and `.env.example`.
  (DEV-7.6, DEV-14.1, DEV-4.5)
- GitHub Actions: `.github/workflows/ci.yml` runs the gate on Linux with Python 3.12
  (required) and the newest Python (reported) after installing Chromium, and audits the
  locked PyPI dependencies with `pip-audit` (informative); `live.yml` runs the `live`
  tests weekly; Dependabot updates the pinned actions. Nothing has run yet.
  (DEV-7.7, DEV-10.3, DEV-13.6)
- `SECURITY.md` (private vulnerability reporting, scope); `CONTRIBUTING.md` describes
  `uv sync --locked`, the gate, the CLA and where to report security issues, and
  the pull request template is `.github/PULL_REQUEST_TEMPLATE.md` with the gate
  and CLA checkboxes. (DEV-13.7, DEV-16.2, DEV-16.4)
- `--verbose` (debug) and `--quiet` (errors only) on every command, before or after its
  name, and the variable `ARCHIWISTA_LOG_LEVEL` (`debug`, `info`, `warning`, `error`;
  default `warning`): the log goes to standard error through one handler, the server
  and the job and render processes follow the level, and a variable that names no level
  is a `validation_error`. Uvicorn's start-up lines show only with `--verbose` or
  `ARCHIWISTA_LOG_LEVEL=info`. (DEV-12.2)
- The first-run wizard offers the directory Kartograf uses when a call names no store
  (`KARTOGRAF_ROOT`, `[kartograf] root` of `nogat.toml`, else `<data_dir>/kartograf`,
  DEV-19.2) under an empty Kartograf field, with the button "Użyj tego katalogu", when it
  exists and holds `kartograf-store.json`. It is only offered: nothing is entered or saved
  until the person clicks and saves, and Archiwista never uses that directory for a call.
  `GET /sources` and `archiwista sources` report it as `default_root` (`path`, `source`
  `default`, `env` or `file`, `name`, `exists`, `marked`, `message`; `null` for a source
  without one); `/health` leaves it out, because Kartograf sizes the directory while it
  reports it. `archiwista doctor` prints the root, the layer of the settings that gave it
  and whether it exists and is a store. (DEV-19.2, ADR-032)

### Changed

- **Breaking:** errors follow the Nogat error registry. Every problem of the HTTP API has
  the registry's `code` (`validation_error`, `not_found`, `conflict`, `forbidden`,
  `unauthorized`, `missing_dependency`, `store_unavailable`, `data_error`,
  `unsupported`, ...), its HTTP status and the members `type` (the registry page and
  `#<code>`), `title`, `detail` and `hint`,
  `instance`, `details` and `errors[]` with JSON Pointers. The old codes are
  `details.reason` (`session_required`, `csrf_rejected`, `preview_busy`,
  `area_too_large`, ...); the extra members moved into `details` (`job`, `source`,
  `problems`, `layers`, `kartograf`, `preview_reason`, `blocked_by`); the answers `422`
  and `413` are `400`, and `invalid_host` is `403`. The command line prints nothing on
  standard output for an error, ends standard error with the `archiwista-error/1`
  document and exits with the registry's code (2 invalid input, 3 not found, 4
  conflict, 8 store unavailable, 12 forbidden, ...) instead of `1`; a job that does not
  succeed exits `11` (failed) or `130` (cancelled or interrupted), `reindex` of several
  stores `10` when only some were scanned, and `archiwista doctor` `10` or `11` when
  checks fail. The interface sends `Accept-Language: pl` and reads the new members.
  The registry and the Nogat JSON schemas are vendored in `schemas/nogat/`;
  `scripts/generate_errors.py` generates `archiwista._errors`, which a contract test
  compares with the generator's output. `docs/AGENT_API.md` is English and lists the
  codes. (ERR-1 to ERR-6, AGI-6.3, DEV-11.1)
- **Breaking:** the `error` of a job (`GET /jobs/{id}`, `GET /jobs`, the final `state`
  event of the SSE stream) has a code of the error registry, like a problem, and the
  members `detail`, `hint` and `details`. The old job code is `details.reason`
  (`worker_crashed`, `interrupted`, `offline_mode`, `snapshot_blocked`,
  `kartograf_error`, ...): `store_unavailable` stays, a missing or incompatible plugin
  and `own_reader_failed` are `missing_dependency`, `offline_mode`, `snapshot_blocked`,
  `inconsistent_copy` and `target_exists` are `conflict`, `<package>_error`,
  `checksum_mismatch` and `integrity_failed` are `data_error`, `path_outside_root` is
  `forbidden`, `worker_crashed` and `protocol_error` are `internal_error`,
  `interrupted` is `cancelled`; `not_found`, `unsupported` and `cancelled` are as they
  were. The cause of a blocked snapshot is `details.blocked_by`, the member `reason` is
  gone, and a job error of a missing plugin carries `details.source` and a `hint` as the
  problem of a request does. Jobs recorded by 0.2.0 are read with the new codes on
  every read and are not rewritten; the history needs no migration. The command
  line and the interface show the reason where they showed the code. (ERR-1)
- **Breaking:** the texts of errors and answers follow `Accept-Language` (before, `detail`
  and `hint` were Polish always, and `title` alone followed the header). `title`,
  `detail`, `hint`, the texts inside `details`, the `message` of `errors[]` that
  Archiwista's own checks make, and the texts of the answers (the `reason` of a preview,
  the `error` of a job) are English, and Polish when the header prefers Polish; another
  language, a malformed header and no header give English. Every JSON answer under
  `/api/v1`, every problem and every event stream has `Content-Language` and `Vary:
  Accept-Language`. The interface sends `Accept-Language: pl`, so its texts stay Polish.
  The `error` of a job keeps the key and values of its `detail` and `hint`, and renders
  them in the language of the request whenever it is read, in the final `state` event
  too. The command line prints text for a person (the help, the diagnostics, the line
  before an error document) in Polish, and its `--json` answers and the `message` and
  `hint` of the `archiwista-error/1` document in English; the log is English. What is
  written when it happens stays Polish: the `detail` of a store that is not available,
  and the `message` of the notices of a job (deviation AGI-6.4 of `CLAUDE.md`).
  (AGI-6.4, AGI-9.2)
- All documents are English (`docs/CLA.md`, the author's legal text, excepted); the Polish
  interface labels stay in quotes with the English meaning beside them. The README follows
  the order of DOC-2.1 for an app, `docs/PROGRESS.md` has the three sections of the
  standard, `docs/DEVELOPMENT_STANDARDS.md` is gone (the project rules are in `CLAUDE.md`),
  the plans of v0.1 and v0.2 are in `docs/plans/`, ADR-030 is the first decision in
  `docs/decisions/` and `docs/IMGWTOOLS_REQUIREMENTS.md` is removed (IMGWTools 3.0.0 meets
  it; SPEC 12.7 keeps the identifiers). (DEV-2.1, DEV-1.3, DEV-17.4, ECO-005, DOC-2.1,
  DOC-3.1, DOC-6.1, DOC-8.2)
- **Breaking for developers:** the environment is managed by uv. `uv sync --locked`
  replaces the pip installation from `requirements.lock`, which is removed;
  `uv.lock` pins every package with SHA-256 sums at the versions of the 0.2.0
  lock. Development tools are the `dev` dependency group, and the extra `dev` is
  gone. (DEV-6.2, DEV-6.3, DEV-6.5)
- Kartograf is pinned by commit in `pyproject.toml` instead of being installed editable
  from a sibling checkout: `8a36e977`, the head of its branch `feature/data-output` (the
  data-output convention, ADR-054; the commit is not pushed). The release pull request
  replaces the commit with the tag. The range of Kartograf versions the adapter reads is
  `SUPPORTED_VERSIONS` in `archiwista.adapter.kartograf`, `>=0.8.0.dev0,<0.9` while the
  commit is pinned, because PEP 440 sorts the development version `0.8.0.dev0` below
  `0.8.0`; the release pull request narrows it to `>=0.8.0,<0.9`. The install command in
  the repair texts is now the pin. (REL-5.3, REL-5.6)
- **Breaking:** the store root of Kartograf is `root` (the data-output convention, DEV §19,
  ECO-051). Archiwista reads the store with the pinned head, whose read API takes `root`
  and whose project manifest `kartograf-project.json` names the store of a project with
  the key `root`: a manifest written by an earlier Kartograf, with `output_dir`, is listed
  as an invalid project with Kartograf's message until Kartograf writes it again. The
  source states `kartograf-store/1` among the schemas it reads. (ECO-051)
- **Breaking:** a Kartograf directory needs its marker, `kartograf-store.json` (DEV-19.12,
  DEV-19.13; ADR-031). A directory that has the layout of a store (a file below a known
  segment) and no marker is refused: the store is `unavailable`, a scan job fails with
  `store_unavailable`, reason `no_marker` and the hint `run once: kartograf store init
  --root <path>`, `PUT /settings` answers `400` with the same reason and hint at
  `stores[n].kartograf`, and `archiwista doctor` prints the command as the fix. Archiwista
  never writes the marker: run the command once for each store an earlier Kartograf wrote.
  It verifies the layout first and refuses a store with stray entries (`invalid_layout`, the
  list is in `details.problems`), which you move out. A marker of another schema, or one
  that is not JSON, is `unsupported_marker`; the root of an IMGW store (`imgw-store.json`)
  is `foreign_store`; a directory whose segments are none of Kartograf's, such as the
  parent of a store, is `not_a_store` and its message asks for the directory that holds
  `kartograf-store.json` instead of the `--output` directory. An empty directory and one
  with known segments and no file stay available: the first download of Kartograf into them
  writes the marker. The generated stores of the tests are marked through
  `kartograf.init_store`. (DEV-19.13)
- The texts for people call the Kartograf directory the store root, the directory that holds
  `kartograf-store.json` and the product directories (usually `data`), and no longer "its
  `--output` directory": the hint of the wizard (its example, `/mnt/nas/kartograf`, no longer
  ends in `/data`), the description of the `kartograf` setting in the OpenAPI document, the
  README, USAGE and the SPEC. The SPEC also has the names of the data-output convention:
  the argument and manifest key `root`, `set_project_root`, the envelope `kartograf-result/1`
  of `run_command` (it has no `cancel` yet), and for IMGWTools `IMGW_REFERENCE_DIR`, the
  statuses `new` and `unchanged` and the marker fields `tool`, `created_at` and
  `producer_version`. (ECO-051)
- The tests find the repository from the test file, never through the installed package,
  so they run against an installed wheel; the generated stores of the tests call the
  directory that holds `data/`, `projects/` and `other-data/` `base`. (REL-2.5)
- `develop` carries the development version `0.3.0.dev0`. (REL-1.1)
- **Breaking for developers:** the package moved from `archiwista/` to
  `src/archiwista/`; import paths and package data are unchanged, and `uv sync
  --locked` reinstalls the editable package. (ECO-011, DEV-5.1)
- Kartograf ships `py.typed`, so mypy checks the calls to it; the code and tests
  that its types rejected are corrected and the `ignore_missing_imports`
  override is gone.

### Fixed

- A job worker that was interrupted ends itself `STOP_TIMEOUT_S` (30 s) after its first
  interrupt, with the stacks of its threads in the job log, wherever it waits (the
  watchdog of `faulthandler` runs in C). Before, only the supervisor's killer ended a
  worker that did not stop, so one whose supervisor was gone could stay for good: under
  `--cov` an interrupt that lands in coverage's tracer at the wrong moment leaves the
  tracer's lock held, and the worker waits for it in its exit handler.

## [0.2.0] - 2026-10-20

Release "Previews".

Known limitations:

- 30 frames per second or more on the map with 5,000 footprints stays
  unverified without a hardware GPU on the reference computer.
- IMGW data is not yet available in Archiwista (plan v0.5).
- Georeferencing of a rotated JPEG with a world file and differences between
  objects of two snapshots are not part of v0.2.

### Added

- Previews of rasters, vectors, point clouds and ZIP archives; for unsupported
  files the reason and what to do. Thumbnails, tiles and simplified objects
  are built in isolated processes, and the content-addressed cache with an LRU
  limit is kept locally.
- "Fan" (Wachlarz) and "Timeline" (Oś czasu) of local years and campaigns, the
  preview of a whole year from sheets, metadata comparison and the curtain of
  two layers (also cross-fade and side by side).
- Own project data: folder index, files and layers on the map, detection of
  changes since a snapshot, a plan and atomic snapshots of whole files in
  `.wersje/`. Writing a snapshot needs `project.write`; the producer's store
  stays read-only. Jobs that contain project data are visible only to people
  who can access the project.
- API for previews, comparison, layers, own data, plans and snapshots; CLI
  commands `preview`, `compare`, `layers`, `files`, `file`, `snapshot` and
  `own-scan`; the `project` filter in the catalog and in jobs.

### Changed

- WGS84 footprints are polygons instead of rectangular envelopes; map queries
  limit the cost of returning footprints. The index `SCHEMA_VERSION` is 6,
  which **rebuilds the index and runs a full scan on the first start** after
  the update (also on a share that can be disconnected); the permissions
  database stays.
- The default basemap is OpenFreeMap vector tiles in a grey style with Polish
  names of places and waters (exonyms too: Praga, Drezno, Lwów). The second
  option is the GUGiK OSM BaseMap (Poland only); BKG is removed. Old
  configurations keep their own `[[basemaps]]`; to get the new basemaps,
  remove those entries from `config.toml`.
- Test data has footprints inside Poland and Czechia (`34c42ce`).

### Fixed

- Faster map footprints (`5610065`). Security and reliability review
  (`d2d3402`, `f445633`, `48ff701`, `f582d86`, `cde1349`, `ec83b7c`,
  `416dd4f`): isolation of reading and rendering, checks of paths,
  permissions and file changes, consistency of snapshots, limits of the scan
  and error messages that do not reveal other people's data. The state of a
  preview build does not reveal the job of an invisible project; the limits of
  the own-data scan do not mark unvisited files as missing.

## [0.1.0] - 2026-10-19

Release "Browser": the first release, a local browser of the Kartograf store,
read-only. It needs Kartograf 0.8.0 with the public store read API (KA-1 to
KA-6, `docs/SPEC.md` 12.1), at that time from the branch
`feat/archiwista-store-api` of the Kartograf repository (installation:
`README.md`).

Known limitations:

- Local mode only: one person on `127.0.0.1`, no sign-in (team: v0.4).
- No downloads, previews, comparisons, availability checks at the source and
  project changes; they come in v0.2 and v0.3.
- The Kartograf store read API is not yet in a tagged Kartograf release: it
  needs the branch `feat/archiwista-store-api`.
- The smoothness of a map with 5,000 footprints (30 frames per second or more,
  a v0.2 criterion) is not measured on a computer with a GPU; without a GPU
  (software WebGL) it is 8 to 9 frames per second.
- Checked on Linux (Debian 13, Python 3.13); Windows and installation with
  `pipx` or `uv tool` come in v1.0.

### Added

- **Server and first run.** `archiwista serve` on `127.0.0.1` (port 8090 by
  default) prints and opens a one-time session address; the first-run wizard
  asks for Kartograf stores, project folders and offline mode; the "Settings"
  view has the same form.
- **Local index** (SQLite, rebuildable): full and incremental scan of the
  store, refresh of the slots of the selected area, scheduled scans (local
  disk every 5 minutes, share every 15 minutes) and a full control scan every
  24 hours (`full_scan_interval_h`). On a network share the scan reads parts
  of segments in `scan_threads` threads, and the incremental scan does not
  list known version folders. A disconnected share does not clear the index:
  results are marked "from the index of <time>", and the status bar says so.
- **Map:** file footprints and a density grid (more than 5,000 footprints in
  view), an area as a rectangle, polygon, map view, sheet code (typed or
  clicked in the PL-1992 and PL-2000 sheet grids) or a file (GeoJSON,
  GeoPackage, ZIP with a Shapefile); product choice and filters; the local
  state of an area ("83% of the area local") computed in the flat national
  coordinate systems (EPSG:2180, EPSG:5514); the default grey basemap is BKG
  TopPlusOpen.
- **Catalog:** search by sheet code, TERYT, KU, file name, version label,
  request number and the beginning of a SHA-256 (`Ctrl+K` or `/` from every
  view); filters kept in the page address; cursor pagination; location groups
  with counters and a group "without location"; entries of every registered
  source plugin next to the Kartograf entries.
- **File card:** a timeline of all versions with the current one and the full
  sheet (`full_sheet/`), data year told apart from download date, metadata in
  plain words next to the technical values, the licence with copying of the
  attribution, version paths and the standard path to copy (also under other
  drive letters), pins in projects, files of the same producer request, the
  raw sidecar and confirmation of the current version by content.
- **Projects** (preview): `kartograf-project.json` manifests from project
  folders, tasks with the producer's commands, pinned and missing versions,
  the current state from the producer (without network).
- **Store:** state and data source, last scan and last full scan, the
  buttons "Refresh", "Full scan" and "Complete unit footprints", usage by
  product (each version counted once), a report of non-current and unpinned
  versions (nothing is deleted), problems with a repair description, projects
  that use the store.
- **Background jobs** in separate worker processes: scan, unit footprints
  (TERYT, KU: from the network), confirmation of the current version;
  progress through SSE with resuming after `Last-Event-ID`; for a busy store
  `409 conflict` with the running job.
- **HTTP API `/api/v1`:** state (`/health`, `/sources`, `/stores`), catalog
  (`/slots`, `/products`), slot and version cards with the sidecar, request
  files (`/requests/{parent_request}`), map (`/map/footprints`,
  `/map/sheets`), areas and local coverage (`/areas`, `/local-coverage`),
  projects, settings, jobs; RFC 9457 errors with a stable `code` and a Polish
  `detail`; an OpenAPI document with examples and the local `/api/docs`.
- **Command line:** `doctor`, `status`, `sources`, `search`, `entry`,
  `version`, `projects`, `project` with `--json` in the schema of the API
  response, `reindex`, `token` for an agent session.
- **Permissions** (A-ADR-029): a local state database (accounts, groups,
  shares, change log), the roles `admin` and `store_writer`, the project
  visibility `public` / `users` / `group` / `private` in the services, the API
  and the CLI; the commands `users`, `groups`, `share`, `state export` /
  `state import` and their HTTP routes.
- **Source plugins** (A-ADR-024): adapters from the `archiwista.sources` entry
  points, the Kartograf adapter, source states; a missing or incompatible
  producer version is `503 source_unavailable` / `source_incompatible` with a
  repair description, not a server failure.
- Documentation: `docs/USAGE.md` (views), `docs/AGENT_API.md` (scripts and AI
  agents), `docs/reports/v0.1-measurements.md` (measurements and acceptance).
- Performance: the targets of SPEC 4.5 are met on a synthetic store of 50,000
  slots through a real `archiwista serve` (SSD: measured on the release code;
  SMB 3: run 3). First full scan 48.3 s on SSD and 225.6 s on the share;
  incremental scan 12.4 s and 74.7 s; view refresh (p95) 408 ms and 1.83 s;
  list, search and card at most 143 ms (p95, threshold 200 ms), footprints
  198 ms (threshold 300 ms); peak server RSS 168 to 179 MiB with a 256 MB
  index. Method and all figures: `docs/reports/v0.1-measurements.md`.

### Security

- The server refuses to start outside `127.0.0.1`, accepts only the `Host`
  header `127.0.0.1:<port>` or `localhost:<port>` and has no CORS.
- A one-time token in the address fragment (start 10 minutes, agent 5
  minutes; only its SHA-256 in the index); the browser gets the address
  through a private `0600` file, not through the command line.
- The session is an `HttpOnly`, `SameSite=Strict` cookie and a CSRF token in
  the `X-Archiwista-CSRF` header in every `/api` request, reads included;
  rules for `Origin` and `Sec-Fetch-Site`; `DELETE /api/v1/session` ends the
  session.
- Roles and groups are read on every request: taking a role away works at
  once, and a disabled or deleted account ends its sessions; an agent session
  lasts 12 hours at most, and `archiwista token --revoke-all` ends all of them.
- Request body limits (4 KiB token exchange, 1 MiB others, 50 MB area file);
  area files are read in a process with a time limit and without fetching
  coordinate systems from the network.
- Files are opened only under paths from the index in the store roots; a
  project manifest that points outside the project folders is not read.
- CSP computed from the settings, `Referrer-Policy: no-referrer`,
  `X-Content-Type-Options: nosniff`; the interface libraries ship with the
  package (no CDN) with SHA-256 sums checked in tests; `requirements.lock`
  with SHA-256 sums.
- Private local data: a `0700` folder and `umask 077`; `archiwista doctor`
  warns about access by other accounts.
