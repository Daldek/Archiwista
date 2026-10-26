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
- The first-run wizard offers the directory Kartograf and IMGWTools each use when a call
  names no store (`KARTOGRAF_ROOT` or `IMGW_ROOT`, `[kartograf] root` or `[imgw] root` of
  `nogat.toml`, else `<data_dir>/kartograf` or `<data_dir>/imgw`, DEV-19.2) under the
  empty field of that producer, with the button "Użyj tego katalogu", when it exists and
  holds `kartograf-store.json` or `imgw-store.json`. It is only offered: nothing is entered or saved
  until the person clicks and saves, and Archiwista never uses that directory for a call.
  `GET /sources` and `archiwista sources` report it as `default_root` (`path`, `source`
  `default`, `env`, `dotenv` (IMGWTools reads `.env`) or `file`, `name`, `exists`, `marked`, `message`; `null` for a source
  without one); `/health` leaves it out (it is polled; the report is on demand). Kartograf
  and IMGWTools give the root with `store_root()`, which reads no store. `archiwista doctor` prints the root, the layer of the settings that gave it
  and whether it exists and is a store. (DEV-19.2, ADR-033)
- The IMGWTools source behind the extra `archiwista[imgw]`: one plugin, `imgw`, reads a
  store root of IMGWTools for both of its providers, IMGW-PIB and ČHMÚ (archives, series
  and station catalogs as versions, the producer's own problems, the observation register
  of a slot as history), judges the marker `imgw-store.json` and says why it refuses a
  directory (`no_marker` with `imgw store init --root <path>`, `unsupported_marker`,
  `foreign_store`, `not_a_store`). A marker without `created_by` is accepted, as the
  producer accepts it. An incremental scan reads no sidecar of a version the index knows
  (`skip_versions` of `iter_store`), and a file card shows the package and the version
  that wrote the sidecar. `GET /sources` and `archiwista doctor` list the source; without
  the extra it is `not_installed` with `pip install "archiwista[imgw]"` as the fix, and
  Kartograf is unaffected. A store takes an IMGW directory beside or instead of its
  Kartograf one (the next entry). `uv sync --locked --all-extras` installs the extra; CI
  also runs the suite without it. (ADR 0032, DEV-19.12, DEV-19.13)
- A store can name an IMGWTools directory, `imgw` in the settings (`GET` and `PUT
  /settings`, `config.toml`), beside the Kartograf one or instead of it: one of the two
  is required, and a settings file with only `kartograf` loads and saves as before. The
  wizard and the settings offer the field "Katalog IMGWTools" while the source `imgw` is
  available or the store already has such a directory (a saved directory is never dropped
  by a form that cannot offer it). A scan skips the directory of a source that is not
  available, with the notice `source_skipped`, and keeps its entry in the settings: the
  Kartograf directory of the same store is still scanned and probed, and a store whose
  every source is unavailable starts no scan; the notice does not keep a routine scan
  from being forgotten. Files of an IMGW directory are indexed as versions of their
  slots (the entry on the index of IMGW slots below). (SPEC 5.5, 5.8)
- A producer directory that lies inside a store of any producer, or holds one, is refused
  as `root_nested` at its own field: an ancestor of the directory holds `kartograf-store.json`
  or `imgw-store.json`, or a directory up to two levels below it does (no link is
  followed; the producer's own writer looks at the whole tree). Only a new or a moved
  directory is looked around, so an unplugged share does not block other edits. (DEV-19.14)
- The index of an IMGW directory keeps what IMGWTools calls things (`SCHEMA_VERSION` 7:
  an existing index is rebuilt when it is opened and filled by the next full scan, as
  with every schema change). The segment of an archive, a series or a station catalog
  is its dataset, named in Polish from the producer's registry (`Dane hydrologiczne
  dobowe`, `Katalog stacji ČHMÚ`) with the country of its provider and, as its product,
  the family the producer declares for it (`hydro`, `meteo`, `pmaxtp`; `stations` for a
  catalog), so the store view and the Map group the datasets instead of listing them as
  unrecognised segments; a slot keeps the producer's own key
  (`archive:pl.imgw.hydro_daily:2024/codz_2024.zip`) and is named by its file (a catalog
  by its key); a version keeps its provider (`IMGW-PIB`, `CHMI`).
  The observation register of an archive (a source republished the same content under a
  new signal) is kept as the history of its slot (`IndexQueries.observations`) and is
  neither a version, a current version nor part of any count; a record the producer no
  longer lists is forgotten. A producer that lists no segments can describe the ones
  its entries name (`SegmentDescriptionAdapter`). (SPEC 4.3, ADR 0032)
- The index knows the current version of an IMGW slot, which no link names: at the end of
  a scan IMGWTools is asked (`current_version`; the capability `CurrentVersionAdapter`)
  for the slots the scan touched (a version written, back or gone, a problem found or
  resolved) and for those a scan that did not finish left without one; a scan that
  changed nothing asks for none. A slot with a damaged version (an invalid sidecar,
  another schema, a size that differs) has no current version and no older one stands in
  its place: it is `unreadable` with its problem. The catalog and the card show the
  current version and the clean-up report counts only the versions before it as unused.
  A version directory without its sidecar (`missing_sidecar`, a download in progress or an
  interrupted one) is no version and is explained as a non-critical, usually temporary
  problem; a sidecar of another schema (`unknown_schema`) has its own text. (SPEC 4.4,
  4.8.1, ADR 0032)
- A scan of one segment (`segment` of `POST /stores/{store}/scan`) goes only to the data
  source that owns the segment in the index (`IndexQueries.segment_producers`), so a
  Kartograf segment is never offered to the IMGW directory of the same store; a name the
  index does not know goes to the sources that scan by segment, as it did before. IMGWTools
  reads only its whole directory (its dataset is a label), so a job that names a segment
  it owns fails as `unsupported` before anything is scanned. (SPEC 4.4, ADR 0032)
- The producers' commands as data, for people and agents (ADR-034): `GET /commands` and
  `archiwista commands list` list the commands of every producer whose plugin offers
  them (Kartograf's catalog of `list_commands` and `command_schema`; `producer` keeps
  one) with their options (JSON type, whether required, the allowed values and their
  meanings, the default, bounds, the group of mutually exclusive options and the path
  role of a file path), what a run does (`read_only`, `writes`, `network`, `check`,
  `store`) and example lines, the summary and the description in the language of the
  request. `POST /commands/parse` (`commands parse PRODUCER LINE`) reads a pasted
  command line into a call (`options`, and `run`: the store root and the flags beside
  them), `POST /commands/validate` (`commands validate PRODUCER COMMAND --options JSON
  [--store ID]`) checks a call without the network, a command on a store with the
  directory of a configured store and never with the producer's default root, and `POST
  /commands/format` (`commands format …`) writes the producer's canonical line of a
  call, which parses back into the same call. The producer's refusal keeps its own text
  and hint, with the option in `details.option` (`400 validation_error`,
  `kartograf_error`); Archiwista refuses an option that is a file path (`403
  path_outside_root`), a command outside the catalog (`unknown_command`) and a command
  on a store without its store (`store_required`, `store_without_producer`; `404` for an
  unknown store). A producer whose plugin is missing refuses only its own commands
  (`503 source_unavailable`), one without commands answers `422 unsupported`
  (`no_commands`). Nothing of this uses the network or writes. (SPEC 9.2, SPEC 12
  KB-1 to KB-4, ADR-034)
- The availability at the source, as a background job (ADR-035): the job `availability`
  asks the producer what the source has for a kept area and a product (Kartograf's
  `check_availability` for NMT, NMPT and LAZ in PL and CZ: years, variants, the sheets
  and campaigns a download takes, the land in full sheets) and keeps the report in the
  index as the area's last one (`SCHEMA_VERSION` 8: an existing index is rebuilt when it
  is opened and filled by the next full scan). It needs the network: offline mode refuses
  it before a job exists (`409 conflict`, `offline_mode`). A check of the same area,
  producer and product joins an active one, except that a forced check (asking the source
  again) never waits for an unforced one. Kartograf's metadata cache is Archiwista's own,
  `metadata.db` in `cache/kartograf/` of the data directory, never Kartograf's default;
  the area goes to Kartograf as the envelope of its polygon in EPSG:2180 (EPSG:5514 for
  an area only in CZ), with the country `pl`, `cz` or `auto`. The producer's notices
  become the job's. (SPEC 5.6, 6.3, D5, ADR-035)
- The availability at the source over HTTP and the command line (ADR-035): `POST
  /availability` (`{area_id, product, producer?, force?}`; `archiwista availability check
  AREA --product PRODUCT [--producer ID] [--force]`) answers a kept report younger than
  seven days at once (`200`, the model `AvailabilityInfo`: the area, `checked_at`, the
  job that asked and the producer's report), else starts the `availability` job (`202`
  with `Location: /api/v1/jobs/{job}`; the command runs it in the foreground and then
  prints the report it kept); `force` asks the source even with a fresh report. Offline
  mode refuses a check that needs the source (`409 conflict`, `offline_mode`; exit 4) and
  records nothing, while a fresh report still answers. `GET /availability`
  (`archiwista availability show …`) returns the last report of an area and a product
  without the network, `404` without one. An unknown area is `404`, a producer whose
  plugin is missing `503`, a product the producer does not check `422 unsupported`
  (`no_availability`, the products it checks in `details.allowed`). (SPEC 6.3, 9.2,
  ADR-035)
- The rows of an availability report (SPEC 6.3, 6.4, ADR-010, ADR-017): every
  `AvailabilityInfo` of `GET` and `POST /availability` and of `archiwista availability`
  has `rows`, one per year of each country, with the coverage label of its best variant
  as text in the language of the request ("pełne", "pełne · 2 kampanie", "częściowe ·
  58% · 1 ark. niepełny", "brak danych", with the Polish plural forms) and as structure
  (`coverage`), `other_variants` and the `variants` ranked complete, larger full share,
  fewer campaigns, finer resolution, the report's order; the formats of one set are one
  variant with its default format (ASC, then TIFF) and its size. `store` (`--store`)
  adds the store badge ("pobrane", "pobrane 5/12", "niepobrane") from the index;
  `horizontal`, `resolution` and `vertical_crs` (`--horizontal`, `--resolution`,
  `--vertical-crs`) fix those dimensions, and a year without such a variant is "brak
  danych". The command's text prints a line per year. A store that is not configured is
  `404`. The badge does not tell height systems apart (Kartograf names no store segment
  of a combination; a request in the plan).
- The plan of a download, as a background job (ADR-036): the job `check` asks the
  producer what a run of a command of its catalog would do in a configured store
  (Kartograf's `check_command` with `root=` the store's directory, never its default
  root, and Archiwista's metadata cache): each position with its status (`current`,
  `newer`, `missing`, `unverifiable`, `check_failed`), the labels of the local and of the
  available version, its path below the store root and its size when the producer tells
  it, else `null`, never 0 (Kartograf tells none yet, KC-3). The plan is kept in the index
  with its job (`SCHEMA_VERSION` 9: an existing index is rebuilt when it is opened), and
  the job's result has the counts, the size of the positions to download with
  `size_complete`, the producer's command line of the run (`kartograf … --root …`) and the
  store. It needs the network: offline mode refuses it before a job exists (`409
  conflict`, `offline_mode`). (SPEC 5.6, 6.5, 12.2 KB-5, ADR-036)
- A job may end `partial`: it did part of its work, and its `result` names what failed (a
  plan some of whose positions the source could not tell about: `result.failed`). It is a
  final state with a result and no error; a command following such a job exits 10. A plan
  with none of its positions checked fails the job (`source_unavailable`, reason
  `check_failed`). A client that lists the final states of a job must add `partial`.
  (ERR §1, ADR-036)
- `POST /jobs` starts a job of a command of a producer's catalog on a configured store,
  kind `check` for now (the plan of a run, `202` with the job), and `GET /jobs/{job}/plan`
  returns the plan a `check` job kept (`ActionPlanInfo`: the counts, `todo`, the size or
  `null`, the producer's command line and each position), from the index without the
  network. Before a job exists the request is refused as the job's worker would refuse
  it: a store that is not configured (`404`), a command outside the catalog (`400`,
  `unknown_command`), one on no store or without a check (`422`, `no_store`,
  `no_check`), an option that is a file path (`403`), the producer's refusal of the
  options (`400`, its text) and offline mode (`409`); the job keeps the options as the
  producer read them. `archiwista jobs start check PRODUCENT POLECENIE --store ID
  [--options JSON]` runs the job in the foreground and prints it as it ended (exit 0, 10
  for `partial`), `archiwista jobs plan ZADANIE` prints the plan; `--json` gives the
  route's model. (SPEC 9.2, ADR-036)
- A producer plugin that offers its commands (`ActionAdapter`) also runs them in a store:
  `run(command, options, *, root, plan, on_progress, on_notice)` returns the
  producer-neutral `ActionResult` (`files[]` below the store root with `path`,
  `version_path`, `unit`, `size_bytes`, `sha256`, `label` and `status` `new`,
  `unchanged` or `relabeled`; `items[]` with the code and reason of each unit that
  failed), and `scope(path)` names the segment and the unit a scan reads a file's slot
  by. The Kartograf adapter calls `run_command` with `root=` the store's directory,
  Archiwista's metadata cache and, for the plan of a check, `update="upgrade", plan=…`;
  a plain file (`written`, `replaced`) or one outside the store is `data_error`, reason
  `broken_contract`. (SPEC 12.2 KB-5, ADR-037)
- The download, as a background job (ADR-037): the job `download` runs a command of a
  producer's catalog in a configured store (Kartograf's `run_command` with `root=` the
  store's directory), with `plan_job` the plan a `check` job kept (`update="upgrade"`: only
  its positions to download; one whose source changed since is a failed item,
  `conflict`, `stale_plan`). Its progress events carry the producer's `unit`, `status`
  and `message`, its notices are the producer's, and its result keeps `files[]` and
  `items[]` with the counts of `new`, `unchanged` and `relabeled` files. When it ends the
  index shows the new versions without a scan (the slots of its files are read again);
  cancelled or stopped, it reads the slots of the units it named again first. A run with
  failed units ends `partial`, one with none done fails (reason `run_failed`). A download
  of the call an active download of the store runs starts with the warning notice
  `overlapping_job`. Offline mode refuses it before a job exists. (SPEC 5.6, 12.2 KB-5,
  ADR-037)
- `POST /jobs` starts a download too (`"kind": "download"`, optionally `"plan_job"`: the
  `check` job whose kept plan the run runs), and `archiwista jobs start download PRODUCENT
  POLECENIE --store ID [--options JSON] [--plan ZADANIE]` runs it in the foreground and
  prints the files by status and the units that failed. A download writes the store, so
  it needs the role `store_writer` or the setting `store_write_for_all`: without them a
  session or an agent token (which has the roles of the person who issued it) gets `403`
  (`permission_denied`) and no job is recorded; a plan needs no such permission. A
  `plan_job` the session does not see, or one that kept no plan, is `404`; one of another
  store, command or options is `409` (`plan_mismatch`). (SPEC 9.2, 10.2, SPEC 13 v0.3
  criterion 7, ADR-037)
- Every combination of an availability report has `commands`, the producer's own command
  lines that download it (Kartograf's `download_hint`, without the program name and the
  store), and every variant of a row names them by format (`commands`): `POST
  /commands/parse` reads a line into the call that `POST /jobs` plans and runs, so the
  interface needs no knowledge of a producer's flags. A report kept before reads with no
  commands. `GET /sources` and `archiwista sources --json` list for each producer the
  products whose availability at the source it checks (`availability`). (SPEC 6.3,
  ADR-035)
- `POST` and `GET /session` say whether the session may write the stores now
  (`store_write`: the role `store_writer` or the setting `store_write_for_all`, read at
  each request like `roles`): the permission `POST /jobs` asks of a download, known to a
  client before it asks. (SPEC 9.2, 10.2)
- The map's panel "Wybór" has a fourth step, "U źródła": a product whose availability a
  producer checks (`GET /sources`) and the target store, the area's last report with its
  date (`GET /availability`), "Sprawdź u źródła" and "Sprawdź ponownie" (the
  `availability` job, followed live), and a row per year with its coverage label, its best
  variant (sheet system, resolution, height system, formats, size or "rozmiar nieznany"),
  the store badge and the chip "+N wariantów" that lists the others. "Pobierz…" of a
  variant opens the plan window: each of its lines in the chosen format is read by `POST
  /commands/parse` and planned by a `check` job (no format is chosen for a variant without
  a default one), and the window shows the positions by status, what a run downloads with
  its size ("co najmniej …" when the producer tells only some sizes, "rozmiar nieznany"
  when none, never 0), each position, the positions the producer would refuse to write,
  the store with the producer's directory and each command line to copy. "Pobierz N
  pozycji" starts one `download` per plan (`plan_job`), asks to confirm first above 5 GB
  or 500 positions, and shows the progress, the files by status and the failed units; a
  session without `store_write` sees it disabled with the reason, and offline mode keeps
  the report and disables both actions; without a kept report, offline, the step says it
  cannot ask the source and points to "Stan lokalny", which shows what of the area the
  store holds ("lokalnie 76% obszaru"). A job that ended `partial` shows its summary
  too. (SPEC 6.3, 6.4, 6.5 h, 10.3, UC-02; plan A10, A11)
- Job controls (ADR-038): `POST /jobs/{job}/cancel` cancels a job that waits (at once,
  without a worker) or runs (it ends `cancelled` when its worker has stopped, within the
  stop timeout of 30 s) and answers `202` with the job as it is then; only whoever started
  the job or an administrator may (`403 permission_denied` otherwise, the new permission
  `job.cancel`), and a job that has ended is `409` (`job_finished`). A job another process
  supervises (a server's job cancelled at the terminal, or a terminal's job from the
  interface) is stopped by that process: a request file `<jobs>/<id>.cancel` that each
  supervisor carries out within half a second. `POST /jobs/{job}/retry` starts a job that
  ended `partial`, `failed`, `interrupted` or `cancelled` again as a new job of the session
  with its kind, store and parameters (`202`); one that succeeded or has not ended is `409`
  (`job_succeeded`, `job_active`), and what the kind needs is asked again (a download:
  `store.write`; a snapshot: `project.write`). `GET /jobs/{job}/log` returns the end of the
  job's log (`JobLog`: the last MiB, `truncated`, `size_bytes`); a job without a log is
  `404`, a `preview` job that also builds files of projects the session does not see
  `403`. A job the session does not see is `404` for all three. `archiwista jobs list`
  (the filters of `GET /jobs`), `jobs show`, `jobs cancel`, `jobs retry` (in the
  foreground, as `jobs start`) and `jobs log` give the routes' models with `--json`.
  (SPEC 5.6, 9.2; plan A6)
- Projects created and changed through their producer (ADR-039): `POST /projects`
  (`producer`, `path`, `store`) has the producer write a new project's manifest in a
  project directory of the settings or at most four levels below one, where the next scan
  finds it (`400 project_not_discoverable` in a hidden directory, a store or deeper; `403
  path_outside_root` outside), naming the store's directory of the producer (relative to
  the project directory when the store has path aliases, never the producer's default
  root); the store is configured (`404`), has a directory of the producer (`400
  store_without_producer`) and can be read now (`503 store_unavailable`). A new project
  has no owner yet, so only an administrator creates one. `POST
  /projects/{project}/tasks` adds a task (a command of the producer's catalog with its
  options, checked without the network: the producer's refusal keeps its text and
  `details.option`, an option that is a file path is `403`) and `DELETE
  /projects/{project}/tasks/{name}` removes one with its pins (its files stay in the
  store), for the project's owner or an administrator (`404` for a project the session
  does not see, `403 permission_denied` for one it may not change). Each answers the
  project's card as the index holds it right after the change (`201` with `Location` for
  a new project); a producer that changes no projects is `422 unsupported`
  (`no_project_actions`). `archiwista project-init PRODUCER DIR --store STORE`,
  `project-add PROJECT NAME COMMAND [--options JSON] [--producer PRODUCER]`,
  `project-remove PROJECT NAME` and `project-status PROJECT` give the routes' models with
  `--json`. (SPEC 4.7, 9.2; plan A7)
- A lock of a project's manifest that stays past the producer's wait (Kartograf's
  `.kartograf-project.lock`, left by a change that was interrupted while it wrote) is
  named: creating a project and adding or removing a task answer `409 conflict` with the
  reason `project_locked`, the lock's path in `details.lock`, the producer's own text and
  the instruction to remove the directory when no program is changing the project.
  Archiwista never removes it. (SPEC 5.6, 14; plan A8, ADR-040)
- The jobs of a project (ADR-040): `POST /projects/{project}/jobs` (`kind` `download`,
  `repin`, `check` or `verify`; optionally `tasks`, every task when left out, exactly one
  for a repin) answers `202` with the job and `Location`. `download` has the producer
  download and pin the tasks not downloaded yet and restore missing pinned versions in
  the configured store the manifest names, `repin` pins one task anew to the source's
  newer versions, `check` compares the pins with the source without effects and
  `verify` checks the pinned files in the store without the network. A download and a
  repin need the project's owner or an administrator and the permission to write the
  stores (`403 permission_denied`, no job); a check and a verification need only to see
  the project, and a project the session does not see is `404`. Refused before a job
  exists: a manifest that names no configured store (`409`, `unknown_store`), a producer
  that runs no project jobs (`422 unsupported`, `no_project_actions`), a second job of
  the project (`409 conflict` naming it) and offline mode for all but `verify` (`409
  offline_mode`). A retry of a project's download or repin asks both permissions again.
  `archiwista project-download PROJECT [TASK ...]`, `project-repin PROJECT TASK`,
  `project-check PROJECT [TASK ...]` and `project-verify PROJECT [TASK ...]` run the job
  in the foreground and print the route's `JobDetail` with `--json` (exit `0`, `10`
  partial, `11` failed, `130`); the interface names the four kinds of jobs. (SPEC 4.7,
  5.6, 9.2, SPEC 13 v0.3 criterion 7; plan A8)
- The job `preview_warm` prepares the first look at current versions ahead (ADR-041):
  the preview pane's thumbnail and the map's tiles at the file's smallest zoom, of the
  versions its filters select (`store`, `product`, `segment`, `project` with its own
  data, `area_id`), in a render process of its own at the lowest CPU priority, within
  the room the preview cache has without evicting previews used in the last week; when
  the room runs out it stops with `stopped: cache_full`, the number of files `skipped`
  and a warning, and ends `partial` (also when a file failed). It never builds a local
  COG (`needs_build` counts the files waiting for one), uses no network and reads the
  stores only; a second warm-up finds the work ready without reading the store. `GET
  /jobs` and `archiwista jobs show` show it; the job protocol is version 9. (SPEC 5.6,
  5.7, SPEC 13 v0.3 criterion 8; plan A9)
- A warm-up of previews on request (ADR-041): `POST /previews/warm` (optional `store`,
  `product`, `segment`, `project`, `area_id`; no body: every store's current versions)
  answers `202` with the `preview_warm` job and `Location`, and `archiwista preview-warm
  [--store] [--product] [--segment] [--project] [--area-id]` runs it in the foreground
  and prints the route's `JobDetail` with `--json` (exit `0`, `10` partial, `11`,
  `130`). Any session may warm; a store that is not configured, a project the session
  does not see and an area the index does not keep are `404` before a job. A project's
  own data is warmed only with `project`, and that job is shown only to those who see
  the project. The setting `preview_warm_after_scan` (off by default) has the scheduler
  warm the versions a store's scan has just indexed, once per scan. (SPEC 5.7, 9.2,
  SPEC 13 v0.3 criterion 8; plan A9)
- Each project of `GET /projects`, of a store's `GET /stores/{store}` and the card of
  `GET /projects/{project}` say whether the session may change the project now
  (`project_write`: its owner or an administrator, read at each request like `roles`):
  the permission adding and removing tasks and a project's download and repin ask, known
  to a client before it asks; `archiwista projects` and `project` print it with
  `--json`. (SPEC 9.2, 10.2; plan A11, A13)
- "U źródła" takes a pasted producer's command ("Wklej polecenie producenta", with or
  without an area; UC-15): the producer is the line's first word when it names an
  installed producer, else the step's; the producer reads the line and checks it without
  the network against the target store, and its text for a mistake shows at the field.
  "Zaplanuj…" opens the plan window for the line (no format to choose), which writes to
  the target store instead of the line's `-o` or `--root`. The plan window offers
  "Dodaj jako zadanie projektu": a project of the producer in that store that the session
  may change and the task's name; it adds the command as the project's task through the
  producer (offline too; a name the producer refuses shows at the name field) and, with
  something to download and the permission to write the stores, starts the project's
  download of the new task, which downloads and pins it ("Dodaj zadanie i pobierz N
  pozycji"). The option is disabled with the reason for a variant of several commands, a
  store without a project of the producer and a session that may change none. A project's
  job in a window shows its tasks by outcome or its files by state, and a failed job its
  instruction (the producer's lock). (SPEC 6.5 h, 10.3, UC-15; plan A11, ADR-042)

### Changed

- `GET /map/sheets` items carry `zone`: the PL-2000 zone (5-8) of the powiats the sheet lies
  over, `null` in PL-1992; the `geometry` of a PL-2000 sheet that a zone boundary cuts is its
  part inside its zone (a `Polygon` or `MultiPolygon`). The adapter's `sheet_grid` takes
  Kartograf's `find_sheet_outlines` (Kartograf pinned at `34fab30b`), and `SheetGrid` holds
  the `zones` and the `extents` of the whole sheets; a view is sized by the extent of the
  sheet at its centre, not by its outline.
- The problems of a store, the problems of a file card and the pins of a project name the
  producer they belong to in their fix instructions, not the first producer of the store.
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
  from a sibling checkout: `c31ca04c`, the head of its branch `feature/data-output` (the
  data-output convention, ADR-054; the commit is on GitHub). The release pull request
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

- A job refused in offline mode said that unit footprints need the network, whatever
  the job was (a check, a download, a project's job); it says that the job needs the
  network.
- The PL-2000 sheet grid ("Siatka godeł") of a view across a zone boundary drew two whole
  grids over each other: Kartograf took the zones as longitude strips and gave every zone's
  sheets over the whole view (19.3-19.7 E x 51.95-52.05 N at 1:2000: 228 + 228 sheets, 862
  pairs of sheets of different zones overlapping). A zone is now the area of its powiats
  (§ 22 of the regulation on the national spatial reference system, Dz.U. 2012 poz. 1247;
  Kartograf ADR-055), and each zone's sheets are drawn only inside it (the same view: 214
  zone-6 and 29 zone-7 sheets, none overlapping).
- A job worker that was interrupted ends itself `STOP_TIMEOUT_S` (30 s) after its first
  interrupt, with the stacks of its threads in the job log, wherever it waits (the
  watchdog of `faulthandler` runs in C). Before, only the supervisor's killer ended a
  worker that did not stop, so one whose supervisor was gone could stay for good: under
  `--cov` an interrupt that lands in coverage's tracer at the wrong moment leaves the
  tracer's lock held, and the worker waits for it in its exit handler.
- Processes that open a new index, state database, preview cache or unit cache of the
  Kartograf adapter at the same moment all open it (the server, the job workers, the
  build processes and the command line share them). SQLite refused the switch of
  `index.sqlite`, `state.sqlite`, `cache.sqlite` or `unit_bboxes.sqlite` to WAL with
  "database is locked" at once, without the busy timeout, in a process that read the
  file's header while another one wrote it, and that process ended at its start; now
  it tries again for up to the busy timeout.
- Archiwista declares `affine>=3,<4`. The previews transform with the `@` operator of
  affine 3; rasterio also admits affine 2, where `@` raises `TypeError`, so in an
  environment that resolved affine 2 every preview was unreadable (Hydrograf caps
  affine below 3, and the environment of the ecosystem's integration run held both).
  A resolver now refuses such an environment.
- The OpenAPI document keeps the `422` problems a route documents itself (`unsupported`
  and `calculation_error` of the preview routes, `unsupported` of `/commands`): only
  FastAPI's own `422` of invalid request data becomes the `400` the API answers.

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
