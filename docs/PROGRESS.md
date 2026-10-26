# PROGRESS: Archiwista

Current state only (DOC-6.1). Branch, tag and remote state: ask git (`git status`,
`git log --oneline -10`). History: the git log and [CHANGELOG](CHANGELOG.md); the
Polish session notes that used to live here are in git (`docs/PROGRESS.md` before the
commit that introduced this file).

## Status

| Component | State | Note |
|---|---|---|
| Release 0.2.0 "Previews" | done | released on `develop` (`chore(release): wydanie 0.2.0`), not tagged and not merged into `main` (author's decision); `develop` carries `0.3.0.dev0` |
| Next version v0.3 "Actions" | in progress | plan `docs/plans/2026-10-25-archiwista-next.md` Part 3 on `feature/kartograf-data-output` (D11: M, then A, then I): **A1 done** (both commits with the reduced gate; ADR-034). Commit 1: the optional capability `ActionAdapter` with `CommandInfo`, `CommandOption`, `CommandChoice` and `CommandCall`, Kartograf's catalog from `list_commands` and `command_schema` with `parse`, `validate` (`root=` for a command on a store) and `format` (`adapter/kartograf/actions.py`), the service of both interfaces (`services/commands.py`: a command of the catalog, the configured store's root, no file path of a request), `ProducerError` with the producer's code, hint and `details.option`, the stand-in producer with IMGWTools' shape (`tests/fixtures/action_source`) and the socket guard (`tests/fixtures/network.py`). Commit 2: `GET /commands`, `POST /commands/parse`, `/commands/validate` and `/commands/format` (`api/commands.py`, `api/models_commands.py`) and `archiwista commands list\|parse\|validate\|format` (`commands/producer_commands.py`); the API answers `UnsupportedError` (`422`, `no_commands`) and `CommandRequestError`, and the OpenAPI document keeps a route's own `422`; `tests/integration/test_commands.py` runs the routes and the commands over the installed Kartograf and the stand-in under the socket guard. **A2 done** (both commits with the reduced gate; ADR-035). Commit 1: `ActionAdapter.availability_products()` and `availability(product, *, area, countries, force, on_notice)` returning the producer-neutral `AvailabilityReport` (`sources/types.py`, with `to_json`/`from_json`); Kartograf's `check_availability` with `MetadataCache(<cache>/kartograf/metadata.db)` and the area as the envelope of its densified polygon in EPSG:2180 (EPSG:5514 for CZ alone), `country` `pl`/`cz`/`auto`; the job kind `availability` (network, joins an active check of the same question unless it forces) with `run_availability`; the index table `availability` (`SCHEMA_VERSION` 8, an older report never replaces a newer one; `IndexWriter.write_availability`, `IndexQueries.availability`, `StoredAvailability`); the stand-in's `check_availability`; tests `tests/contract/test_kartograf_actions.py` (A2 part) and `tests/integration/test_availability_job.py`. Commit 2: `POST /availability` and `GET /availability` (`api/availability.py`, `api/models_availability.py`; the `POST` is in `job_router`, served with the supervisor) and `archiwista availability show\|check` (`commands/availability.py`) over `services/availability.py`: `check` refuses an unknown area (`404`), a missing plugin (`503`) and a product outside `availability_products()` (`422 unsupported`, `no_availability`, `details.allowed`), answers a kept report younger than `REPORT_TTL` (seven days) with `200` and no job unless `force`, else submits the job (`202`, `Location`; offline `409 offline_mode`, nothing recorded); `stored` returns the kept report (`AvailabilityInfo`: the area as `AreaRef`, `checked_at`, `job_id`, the report with the key `schema`) without the network, `404` without one; the command runs the job in the foreground and prints the report it kept (a check that does not succeed prints its `JobDetail`, exit 11 or 130); tests `tests/integration/test_availability_api.py` (the stand-in helpers shared in `tests/fixtures/availability.py`; `running_api(jobs=)`). **A3 commit 1 done** (reduced gate): `services/availability.py` reads a report as rows without I/O: `rows(report, *, fixed=VariantFilter(...))` gives one `AvailabilityRow` per country and year in the report's order, its `AvailabilityVariant`s (the combinations of one set in several formats grouped by country, product, year, horizontal system, resolution, height system and sorted campaigns; `default_format` the first of `DEFAULT_FORMATS` = ASC, TIFF, else `None` for an explicit choice; `size_bytes` of the default format) ranked complete, full share (compared to a millionth of a percent, so a measure's floating-point error does not decide), fewer campaigns, finer resolution, report order, with `other_variants`; a year without a variant of the fixed dimensions is `NO_DATA`; `coverage_label` gives `CoverageLabel` (`full`, `full_campaigns`, `partial`, `no_data`; `campaigns` the distinct campaigns of `sheet_records`, `share`, `percent` rounded down after rounding to a millionth and at most 99 when partial, `below_one`, `partial_sheets`, `missing_sheets`); tests `tests/unit/test_availability_rows.py` (three years of the Kraków area worked out by hand, the precedence of the ranking, the percent boundaries, the campaigns of the records, formats and campaigns as variants, a border area measured on each country's land). Next 4 gives the starting points |
| v0.3 A4 "the plan" | done | (both commits with the reduced gate; ADR-036) Commit 1: `ActionAdapter.check(command, options, *, root, on_notice) -> ActionPlan` (`sources/types.py`: `PlanEntry` with `path`, `unit`, `status`, `local_label`, `available_label`, `size_bytes` `None` when unknown, `error`, `conflict`; `ActionPlan.counts()`, `todo`, `size_bytes` `None` when no size of a position to download is known, `size_complete`, `document` = the producer's own plan for the run of the plan, `to_json`/`from_json`); Kartograf: `check_command` with `root=` and Archiwista's `MetadataCache`, `kartograf-plan/1` converted, a root a write would refuse is the plan's one `conflict`, no plan of a store (`project download`) is `422 unsupported` `no_plan`; the job kind `check` (`JobRule(store=True, network=True)`, params `producer`, `command`, `options`) with `run_check` (root from `services.commands.store_root`, the plan kept in the new index table `plans` with the store and the producer's line of the run, `SCHEMA_VERSION` 9; all positions `check_failed` = `CheckFailedError` `source_unavailable`/`check_failed`, not kept); the job state `partial` (`PartialResult` in the worker, message `partial`, `PROTOCOL_VERSION` 6, the summary kept, no error, exit 10, the jobs schema CHECK, `_FINISHED_SQL`, the web final states and labels); tests `tests/contract/test_kartograf_check.py`, `tests/integration/test_check_job.py` (real workers through `tests/fixtures/action_worker.py`, which gives each store's Kartograf directory to the stand-in as `tests/fixtures/actions.py` does in process). Commit 2: `POST /jobs` (kind `check`; `202` with the job) and `GET /jobs/{job}/plan` (`api/actions.py`, served with the supervisor; `api/models_actions.py`: `JobRequest`, `ActionPlanInfo`, `PlanEntryItem`) over `services/actions.py`: `start` refuses before a job exists a store that is not configured (`404`), a command outside the catalog (`400` `unknown_command`), one on no store or without a check (`422` `no_store`, `no_check`, the catalog entries `command.no_store`, `command.no_check`), a file path (`403`), the producer's refusal (`400`) and offline mode (`409`), and the job keeps the options as the producer read them; `kept_plan` is `404` for a job the session does not see (`job.not_found`) and for one without a plan (`job.no_plan`); `services/commands.py` gives `command_info` and `checked_call` (the parts of `validate_command`); `archiwista jobs start KIND PRODUCER COMMAND --store ID [--options JSON]` (foreground, prints the `JobDetail` as it ended, exit 0/10/11/130) and `archiwista jobs plan JOB` (`commands/jobs.py`); tests `tests/integration/test_check_api.py` (18: refusals by API and CLI alike, the plan read back, a hidden job, the foreground run, OpenAPI; `standin_in_settings` of `tests/fixtures/actions.py` maps the stand-in in the test's process). A real Kartograf `store init` check ran end to end through `archiwista jobs start` (one `missing` position, nothing written) |
| v0.3 A4 follow-up "the plan from the report's answers" | done | (one commit with the reduced gate; ADR-036 erratum 1, Kartograf ADR-056 at `70ef08ef`) The check's cache reads the source's answers younger than an hour (`PLAN_REFRESH_TTL_S`), so "Pobierz…" right after "Sprawdź u źródła" asks GUGiK nothing. The per-line worker cost is solved by ADR-044 (next row) |
| v0.3 "one job per row" | done | (one commit with the reduced gate; ADR-044, A and C chosen by delegated approval; errata of ADR-035, ADR-036, ADR-037) A `check` and a `download` take `calls[]` (`POST /jobs`, `jobs start … --call JSON`), keep and run one plan per call (`SCHEMA_VERSION` 12, `PROTOCOL_VERSION` 10); the plan window starts one check and one download per row; `archiwista.jobs` loads lazily. Tests: `tests/integration/test_row_jobs.py`, the three-line row in `tests/e2e/test_plan_window.py`. Open: options B (a sheet list in Kartograf's hint) and D (a longer `PLAN_REFRESH_TTL_S`) |
| v0.3 A6 "job controls" | done | (one commit with the reduced gate; ADR-038) `POST /jobs/{job}/cancel` (`202` with the job as it is then; `job.cancel`, a new action of the `Authorizer`: whoever started the job or an administrator, else `403`; an ended job `409 job_finished`), `POST /jobs/{job}/retry` (a `partial`, `failed`, `interrupted` or `cancelled` job submitted again with its kind, store and `params` as the session sees them, as a new job of the session; `409 job_succeeded`, `job_active`; a download asks `store.write` again, a snapshot `project.write`), `GET /jobs/{job}/log` (`JobLog`: the last MiB of the worker's stderr, `truncated`, `size_bytes`; `404 job.no_log` without a worker; `403` for a `preview` job holding files of hidden projects, `JobSupervisor.sees_whole`); a job the session does not see is `404` for all three (`services/jobs.py`, `visible_job` shared with `GET /jobs/{job}`, its events and its plan). `JobSupervisor.cancel` reaches a job of another supervisor, also of another process, through the request file `<jobs>/<id>.cancel` that each supervisor's thread carries out every `CANCEL_POLL_S` (0.5 s); the file goes when the job ends and `prune` removes strays. `archiwista jobs list\|show\|cancel\|retry\|log` (`retry` in the foreground as `start`). Tests `tests/integration/test_job_controls.py` (10: a waiting job cancelled without a worker, a running one within the stop timeout, retry of cancelled, failed and interrupted scans, `job_active`, the download's `job.cancel` and `store.write`, the visibility matrix of a private project's own-scan and a mixed preview, a cancel across processes through `tests.fixtures.job_owner`, the commands' JSON equal to the routes') |
| v0.3 A7 "projects: create and change tasks" | done | (both commits with the reduced gate; ADR-039) **Commit 1:** the optional capability `ProjectActionAdapter` (`create_project(directory, *, root, relative)`, `add_project_task(directory, *, name, command, options)`, `remove_project_task(directory, *, name)`), beside `ActionAdapter` (the stand-in has commands only); Kartograf: `init_project` with `root=` the configured store (relative from the working directory when the store has path aliases, so Kartograf writes it relative to the project directory; else absolute), `validate_command` on the project's store and then `add_project_task` with the box as one `BBox` (Kartograf's `run_command("project add")` refuses a box: a new request of the plan), `remove_project_task`; `services/projects.py` `create_project` (an absolute path equal to or at most four levels below a configured project directory that exists, no hidden directory, no store directory, no link out: else `403 path_outside_root`, `400 project_not_discoverable`, `project_dir_missing`; a configured store with a directory of the producer that can be read now; `project.write` of the directory, so an administrator), `add_project_task` and `remove_project_task` (`404` hidden, `403` not owner or administrator, `other_producer`, `unknown_command`, a path option `403`, the producer's refusal with `details.option`), each recorded at once by `index/projects.py:record_project`; `services/commands.refuse_path_options`; messages `project.no_actions`, `not_discoverable`, `other_producer`, `outside_project_dirs`. `tests/integration/test_project_changes.py` (38). **Commit 2:** `POST /projects` (`201`, `Location: /api/v1/projects/{project}`), `POST /projects/{project}/tasks` (`201`) and `DELETE /projects/{project}/tasks/{name}` (`200`), each answering the project's card as the index holds it after the change (`api/projects.py`, the closed request models `ProjectRequest` and `TaskRequest`, the `422 unsupported` of `no_project_actions` and `no_commands` documented); `archiwista project-init PRODUCENT KATALOG --store MAGAZYN` (a relative directory is the current one's), `project-add PROJEKT NAZWA POLECENIE [--options JSON] [--producer P]`, `project-remove PROJEKT NAZWA`, `project-status PROJEKT` (`commands/projects.py`, as `LOCAL_OWNER` through the `Authorizer`; `reader.project_text` shared); `tests/integration/test_projects_api.py` (29: the journey offline, the commands' JSON equal to the routes', creation by an administrator only, a task changed by the owner or an administrator, also through agent tokens, nine refusals equal by API and command, a Polish detail, the OpenAPI operations) |
| v0.3 A8 "projects: download, repin, check, verify" | done | (both commits with the reduced gate; ADR-040) **Commit 1:** `ProjectActionAdapter` gains `download_project(directory, *, tasks, upgrade, on_progress, on_notice) -> ProjectRun`, `check_project(directory, *, tasks, on_notice) -> ProjectCheck` and `verify_project(directory, *, tasks) -> ProjectCheck` (`sources/types.py`: `ProjectRun` with `ok`, `failed`, `counts`; `ProjectTaskRun`; `PinnedVersion`; `TASK_OUTCOMES`; `ProjectCheck` with `counts`; `ProjectFileState`; `PROJECT_FILE_STATUSES`); Kartograf: `download_project` (`update` unset or `"upgrade"`), `check_project` with Archiwista's `MetadataCache`, `verify_project`; a refusal or a failed task while `.kartograf-project.lock` stays is `ProjectLockedError` (`409 conflict`, `project_locked`, `details.lock`, the hint `fix.project_locked`; never removed), also for A7's changes; the job kinds `project_download`, `project_repin` (one task), `project_check` and `project_verify` (`PROTOCOL_VERSION` 8, `PROJECT_KINDS`, no store, `params.project` and `tasks`; one job per project, the conflict domain `project`; all but the verification need the network); the worker reads the manifest again, requires its store to be configured (`409`, `unknown_store`) and readable, records the project and rereads the pinned files' slots; all tasks failed is `RunFailedError`, some `partial`; a check with no pin asked is `CheckFailedError`. Tests: `tests/contract/test_kartograf_project_jobs.py` (9), `tests/integration/test_project_jobs.py` (15). **Commit 2:** `services/project_jobs.py` (`start`: a project the principal sees, else `404`; a download or a repin needs `project.write`, then `store.write`; a producer without project jobs `422 no_project_actions`; the directory inside the project directories; for a download or a repin a configured store, `409 unknown_store`; then the supervisor: a second job of the project `409`, offline `409 offline_mode`; `require` asks the same of a retry in `services/jobs.retry`), `POST /projects/{project}/jobs` (`ProjectJobRequest`, closed: `kind` `download`, `repin`, `check` or `verify`, `tasks` with exactly one for a repin; `202` with `Location`; `job_router` of `api/projects.py`, served with the supervisor), `archiwista project-download`, `project-repin`, `project-check` and `project-verify` (`commands/project_jobs.py`, in the foreground through `commands/jobs.foreground`; the text lines `cli.jobs_project_tasks` and `cli.jobs_project_files` with the labels `job.task_*` and `job.project_file_*`), the `JobDetail` and `JobFailure` descriptions, the 409 description (`unknown_store`), the web's `job_kind` labels and the kind union of `types.js`. Tests: `tests/integration/test_project_jobs_api.py` (25: the matrix of the status and the four jobs over owner, listed, other and administrator with a startup and an agent token; `store.write`; the job at its address; the model's refusals; four refusals and a second job by API and CLI alike; the retry; the commands' `--json` equal to `GET /jobs/{job}` with exit 0, 10 and 11; OpenAPI) |
| v0.3 A9 "pre-building of previews" | done | (both commits with the reduced gate; ADR-041) **Commit 1:** the job `preview_warm` (`PROTOCOL_VERSION` 9; `previews/warm.py`): `WARM_FILTERS` `store`, `product`, `segment`, `project`, `area_id`, `since`, each `None` when not given (`JobRule(store=False, exclusive=True)`, a request of a waiting one's filters joins it); `IndexQueries.warm_selection(WarmQuery)` (the present current versions as the catalog's current rows; a project's pinned current versions and its own working files); `previews.service.first_look` (pane thumbnail 512 in the default style, map tiles at `minzoom` within the bounds; nothing past the auto-build limits, thumbnail only for vectors and files waiting for a build); `PreviewCache.peek` (no use) and `room(used_before=)`; its own `RenderPool(workers=1)` at `nice` 19; `RECENT_S` 7 days, `RESERVE_BYTES` 4 MiB, `stopped: cache_full` with `skipped` and the notice `cache_full`; `partial` with failures or skips; never a COG (`needs_build`). Tests: `tests/integration/test_preview_warm_job.py` (5), fixture `tests/fixtures/warm_worker.py`. **Commit 2:** `services/warm.py` `start` (a store not configured, a project the principal does not see, an area the index does not keep: each `404` before a job; any session may warm), `POST /previews/warm` (`job_router` of `api/previews.py`, closed `WarmRequest`, `202` with `Location`), `archiwista preview-warm [--store] [--product] [--segment] [--project] [--area-id] [--json]` (`commands/preview_warm.py`, a command of its own because `preview REF` takes a ref; SPEC 5.7 says so now), the setting `preview_warm_after_scan` (`AppSettings`, the API's `Settings`, `types.js`; off by default; `ScanScheduler.tick` submits, as the scheduler, one `preview_warm` with `store` and `since` = the scan's `started_at` for a store's newest succeeded scan with `versions_written` > 0, once per scan, while no job of the store's index waits or runs). Tests: `tests/integration/test_preview_warm_api.py` (11: the visibility matrix with startup and agent tokens, own data cold after a store warm-up and warm after the project's, refusals by API and CLI alike, `--json` equal to `GET /jobs/{job}`, a person's thumbnail within 2 s while a slowed warm-up runs under a second supervisor, the warmed thumbnails served with every store file at mode 000, a read-only store unchanged, OpenAPI), `tests/unit/test_scheduler_warm.py`, and the `perf`/`smb` test of criterion 8 `tests/perf/test_warm_perf.py` (the scheduler's warm-up after the start scan of the preview fixtures, then the first description and thumbnail of 40 warmed versions; not run yet: A14) |
| v0.3 A10 "interface: availability rows" | done | (commit 1 was A11 commit 2, `ce9471e`: the step "U źródła" with its rows; commit 2 with the reduced gate) Offline without a kept report the step says it cannot ask the source and points to "Stan lokalny" (`actions.source.offline_no_report`), which shows the local share of the product ("lokalnie 76% obszaru", SPEC 6.4's badge without a source report); the share is not repeated in the step: the panel gives each piece of information one place (`map/panel.js`), and `tests/e2e/test_map.py` expects one such badge offline. `tests/e2e/test_availability.py` (Chromium): a hand-written report of the stand-in producer over a Kartograf store of three flights (`tests/fixtures/layer_store`) gives six years whose labels need every Polish form of SPEC 6.4 (2, 5, 22 and 25 campaigns; 1, 2 and 5 partial sheets; "<1%"; a partial set of the whole land at 99%), the chips "+1 wariant", "+2 warianty", "+5 wariantów" with the ranking, the badges "pobrane", "pobrane 1/3", "pobrane 1/5", "niepobrane" from the index, formats of one set as one variant with the size of ASC, the chip reached and opened by keyboard with its focus ring, every label and badge as text (the ring `aria-hidden`); "Sprawdź ponownie" starts one `availability` job with `force` on a two-day-old report and the stand-in's rows replace it; offline without a report the banner, the pointer, the disabled check, "Stan lokalny" with the share of `GET /local-coverage` (partial), no job and no request off the machine. Screenshots `07-wiersze-u-zrodla`, `08-offline-lokalnie` in `docs/reports/v0.3-screenshots/` |
| v0.3 A11 "interface: the plan window and the pasted command" | done | (commits 1 and 2 are in Next: `d257b13`, `ce9471e`; then two commits with the reduced gate; ADR-042) **API:** `project_write` on each project of `GET /projects`, `GET /stores/{store}` and on `GET /projects/{project}` (`Authorizer.writable_projects`, the dependency `writable_projects`; the CLI as the local owner), `tests/integration/test_project_write.py`. **Web:** "Wklej polecenie producenta" in step 4 (with or without an area; producer = the line's first word if installed, else the step's; `POST /commands/parse` then `/commands/validate` with the target store, the producer's text at the field), `DownloadPlan` takes `line` (no format row) and keeps a line's call before its check (an offline refusal leaves it), "Dodaj jako zadanie projektu" (projects of the producer in the store with `project_write`; `POST /projects/{project}/tasks`, a refused name at the name field; with something to download and `store_write` the project's download of the task, `POST /projects/{project}/jobs`), disabled with the reason (several lines, no project, none writable, line not read); `projectSummary` and a failed job's hint in `views/cards.js`; the generic offline refusal no longer names unit footprints. `tests/e2e/test_pasted_command.py` (5 tests: stand-in line → plan → download; two refusals at the field; offline Kartograf line → task through Kartograf, a refused name first; a person who may not change the project). Screenshots `09`, `10`. Not covered end to end: "Dodaj zadanie i pobierz" (needs the network). |
| v0.3 A13 "interface: project actions" | done | (one commit with the reduced gate: the API was A11's; ADR-042 decision 4 and option I) `views/projects.js`: the list's column "Producent" and "Nowy projekt…" (`POST /projects`; administrators only, others see it disabled with the reason; producer of `health.sources` with a store directory, the store, the directory prefilled with the first project directory; a refused `path` or `store` at its field); the card's "Weryfikuj", "Sprawdź aktualizacje", "Pobierz" and each task's "Przepnij" (`POST /projects/{project}/jobs`, one `useJob`, `projectSummary`, a `409` naming a running job followed; at the end the card, "Stan teraz" and the list are read again), "+ Zadanie" (`POST /commands/parse` with the project's producer, then `POST /projects/{project}/tasks`; the producer's text at the line, a refused name at the name) and "Usuń" with a question (`DELETE …/tasks/{name}`; a `409 project_locked` shows the instruction naming the lock). `blocked()` gives each action its first reason (`write`, `store`, `store_write`, `offline`, `busy`); the card lists the reasons in force once and each disabled button points at its own (`aria-describedby`). `L.card.readonly` removed. `tests/e2e/test_project_actions.py` (4 tests over `kartograf.testing` with workers refusing the network: create → add (refusals at the line and the name) → remove; verify and download of held pins; the listed person with every change disabled and the hidden project unseen; offline reasons and a left lock). Screenshots `11`, `12`. Not run in the browser: a check and a repin (they need the source). |
| v0.3 A12 (part) "downloads in the background" | done | (one commit with the reduced gate; ADR-043; the author's request of 2026-10-26) `web/src/downloads.js`: the session's downloads (`download`, `project_download`, `project_repin`) followed by the shell (a store outside Preact, one context, each reader subscribes; an event stream for each running download and at most two queued ones, the others looked up in `GET /jobs?state=queued` every 2 s; `GET /jobs` queued and running of the session's label when the page opens or comes back into view; the list in `sessionStorage`), the top bar's "Pobieranie 2/6 · 45%" with the list "Pobrania w tle" (progress, notices, files or failure, "Anuluj pobieranie" via the new `api.js` `cancelJob`, "Pokaż okno planu", "Usuń z listy"), toasts at each end, `useDownloadEnd` (the map and "U źródła" read the store again); the plan window is hosted by the shell (`openPlan`), modal only while planning, then floating with "Zwiń" and "Zamknij"; the banner leaves a followed download out; the Projects card hands its download and repin over; `downloadSummary` moved to `views/cards.js`. `tests/e2e/test_plan_window.py`: two held downloads with their windows closed and minimised, the map panned and zoomed, the Catalog, a third download of the session started through the API and queued, a reload, the toasts and the files in the list; a cancel from the list; screenshot 13. Retry, the log and the other job kinds came with the view "Zadania" (v0.4 T9); the units colouring on the map (M7) is not built |
| v0.3 A14 "acceptance, documents, report" | done | (both commits with the reduced gate) the offline acceptance `tests/e2e/test_acceptance_v03.py` (criteria 3, 4, 5, 7), the live test `tests/integration/test_live_actions.py` (criteria 1, 2, 6; marker `live`, `ARCHIWISTA_LIVE_ACTIONS=1`, the author's), the report `docs/reports/v0.3-measurements.md` (criterion 8 on the SSD: first thumbnail p95 4.1 ms), USAGE and AGENT_API for 0.3, the status of v0.3 in SPEC 13 and SCOPE; details in Next 4. v0.3 is built, not released: A12 is done with v0.4 T9 (the jobs view) but for the units colouring on the map, A15 waits for KB-7 |
| Next version v0.4 "Team" | in progress | plan `docs/plans/2026-10-26-plan-v0.4.md` (approval delegated, 2026-10-26) on `feature/v0.4-team`, from `31e7e4d`: steps T1 to T12 (team mode settings, refusal to start and TLS; passwords, the action log store and the first administrator; sign-in and sessions; the reverse proxy; the sign-in page and the account menu; accounts and groups; projects of every person, sharing, the data folder by its owner, scans; the action log; the shared queue without double downloads, limits per person and the jobs view (A12); file download; preferences and path aliases; acceptance with three people, the permission matrix, the security checklist and the LAN runbook). **T1 is done** (two commits, reduced gate): the table `[team]` and the settings `network_jobs_per_person` and `action_log_retention_days`, `team_refusal` before anything binds (`host_refused`, `tls_required`, `tls_unusable`, `proxy_bind_wildcard`, `proxy_bind_not_loopback`), `bind_address`, `AppServer` with the TLS files, `Transport` and `client_address`, the rules `proxy_required` and `tls_required`, `Host` and `Origin` against `origin`, HSTS, `__Host-archiwista_session`, `/api/docs` in local mode only, the doctor's team lines, USAGE "Team server"; the deviations are in the plan's Results. Next: T2 (the state schema 3, passwords, the first administrator). Decisions: ADR-046 (sign-in, sessions, TLS; LDAP/AD groups deferred) and ADR-047 (the log, the queue, limits, files, preferences) by delegated approval; the author's own decision that every signed-in person creates a project and owns it (ADR-039 erratum 3); errata ADR-012 3, ADR-013 3, ADR-029 2, ADR-037 2, ADR-038 1. SPEC 4.3, 5.5, 5.6, 6.2, 6.5 f and n to s, 9.2, 10.1 to 10.3, 11 and 13, SCOPE and PRD say what v0.4 does. T11 waits for I8.2 commit 1 (the remembered year types) on `feature/kartograf-data-output`, merged into this branch |
| v0.4 T9 "the shared queue" | done | (three commits on `feature/v0.4-shared`, each with the reduced gate; ADR-047; the deviations are in the plan's Results) **Commit 1** (`cad5112`): a download with a plan claims the positions it downloads (`job_claims`, `SCHEMA_VERSION` 14; `JobSpec.claimed` and `taken`, `PROTOCOL_VERSION` 11; `ActionAdapter.narrow`), leaves the positions another live download holds to it (`taken_by_job`, `result.taken`, then `partial`), and a download without a plan of a running call waits (`waiting_for_job`); `tests/integration/test_shared_queue.py`. **Commit 2** (`e141e64`): `network_jobs_per_person` (a free network place goes to the person with the fewest running network jobs; an agent counts as its account, the scheduler is no person), `GET /jobs` lists the jobs of hidden projects bare (`JobDetail.hidden`); `tests/integration/test_job_limits.py`, the hidden job of `test_jobs_api.py`. **Commit 3** (`abe8981`): the view "Zadania" (sketch f; `views/jobs.js`, `labels/jobs.js`; filters in the address, who, progress, `taken`, "Anuluj", "Ponów", "Szczegóły", "Dziennik", hidden rows bare), the navigation's count of running jobs (`queue.js`, `ViewRoute.count`), `TakenList` in `views/cards.js` (also in "Pobrania w tle"), `api.js` `retryJob` and `getJobLog`; `tests/e2e/test_jobs_view.py` (Chromium and Firefox), screenshot 08, USAGE "Jobs" |
| v0.4 T10 "file download over HTTP" | done | (two commits on `feature/v0.4-shared`, each with the reduced gate; ADR-047 decision 5; the deviations are in the plan's Results) **Commit 1** (`a2ecfea`): `GET` and `HEAD` of `/stores/{store}/versions/{version}/file`, `/projects/{project}/files/{file_id}/file` and `…/snapshots/{label}/file` (`member`: `OwnFileCard.members`, `SnapshotItem.members`) in `api/files.py` over `services/files.py`: only what the index knows and the session sees, inside its root; Starlette's `FileResponse` (`Range`) as an attachment with the type of its format (`FileFormat.media_type`) and `Cache-Control: private, no-store`; `FileStreams` (two per person, `429 too_many_downloads`); `file.download` logged from byte 0; `security.file_link` (a link passes without the CSRF header with `Sec-Fetch-Site` `same-origin` or `none`); `RateLimitedError` as on `feature/v0.4-team`; `tests/integration/test_file_download.py`. **Commit 2**: "Pobierz plik" (`api.js` `fileAddress`, `views/cards.js` `DownloadLink`) in the file card and in the card of an own file, "Pliki zestawu", the fix of `document_no_preview` pointing to it; `tests/e2e/test_file_download.py` (Chromium and Firefox), USAGE. Next: the merge with `feature/v0.4-team`; T11 needs T5 and I8.2, T12 all steps |
| v0.4 T8 "the action log" | done | (three commits on `feature/v0.4-shared`, each with the reduced gate; A-ADR-047; the deviations are in the plan's Results) **Commit 1** (`d9e0295`): `job.start` and `job.retry` (`JobSupervisor(record=…)`, never the scheduler's jobs), `job.cancel`, `settings.update` (the settings that changed, before and after), `project.task_add` and `project.task_remove`, `permission.denied` (`api/errors.py` `DenialLog`: at most one entry per person, action and minute) and `log.prune` (`ScanScheduler` deletes the entries older than `action_log_retention_days` at the start and hourly); `tests/integration/test_action_log.py` performs every `ActionName` (those of `feature/v0.4-team` wait in `AWAITING_TEAM_MERGE`). **Commit 2** (`e645879`): `log.read` (administrators); `services/log.py` (pages with `total`; the export logged as `log.export` first and streamed as JSON Lines or CSV with formula-safe cells); `GET /log`, `GET /log/export` (`api/log.py`); `archiwista log list\|export` (`commands/log.py`); `messages/log.py`. **Commit 3**: the view "Dziennik" (`views/log.js`, `labels/log.js`; `ViewRoute.admin` keeps it out of the navigation of anyone but administrators): 50 entries a page through the API's cursors, the filters "Kto", "Działanie", "Wynik", "Od dnia" and "Do dnia" in the address, a row's state before and after, "Eksportuj CSV" and "Eksportuj JSON Lines" (`api.js` `getLog`, `exportLog`); `tests/e2e/test_action_log_view.py` (Chromium and Firefox), screenshot 07 |
| Nogat standard 2.1, structure and tooling | done | on `chore/nogat-2.1`: uv and `uv.lock`, Kartograf pinned by commit, `src/` layout, `scripts/gate.sh`, `scripts/check-commits.sh`, CI, Dependabot, editor and git files, markers, package-data and README example tests, the ruff rule set of DEV-7.2, `--verbose`, `--quiet` and `ARCHIWISTA_LOG_LEVEL` |
| Nogat standard 2.1, documentation | done | everything is English (`docs/CLA.md`, the author's legal text, excepted; the Polish interface labels stay in quotes): README in the order of DOC-2.1 (146 lines), the project rules of the former `DEVELOPMENT_STANDARDS.md` in CLAUDE.md, the plans in `docs/plans/`, ADR-030 in `docs/decisions/` with the index in `docs/DECISIONS.md`, ARCHITECTURE, DECISIONS, SPEC, the plans, the reports and the mockup README translated, `docs/IMGWTOOLS_REQUIREMENTS.md` removed (IMGWTools 3.0.0 meets it; SPEC 12.7 keeps IMGW-1 to 20) |
| Nogat standard 2.1, error registry (ERR-3, ERR-4, DEV-11.1, AGI-6.3) | done | vendored registry and schemas (`schemas/nogat/`), generated `src/archiwista/_errors.py`, contract tests, problem+json with registry codes, the `archiwista-error/1` document and the exit codes of the CLI, the front end, registry codes in job documents (job rows of 0.2.0 are mapped on read, never rewritten), the message catalog `src/archiwista/messages/` and the error texts that follow `Accept-Language` (English by default, Polish with the header, `Content-Language` on every JSON answer; the stored texts stay Polish); deviations in CLAUDE.md: the stored texts (AGI-6.4), outcome statuses and no result envelope for good |
| Data output (DEV §19, ECO-051) | done on the branch | plan `docs/plans/2026-10-25-archiwista-next.md` Part 1 on `feature/kartograf-data-output` (from `chore/nogat-2.1`): **M1 done**: Kartograf is pinned at `8a36e977` at M1, later re-pinned to `45dedf4a` (`store_root()`), the pushed head of its branch `feature/data-output` (2026-10-25; its own PROGRESS says done except a CLI smoke as a subprocess and the plain-mode prose, and its working tree held uncommitted edits), the supported range is `>=0.8.0.dev0,<0.9` (REL-5.6), the read API and `Project` say `root`, the fixtures call the directory above `data/` `base`. **M2 commit 1 done**: `SourceState` has `reason` and `hint`, which the registry, the scanner, `jobs/availability.py` (`store_unreachable`, which returns the error), the settings problems (`PUT /settings`) and the doctor carry. **M2 commit 2 done** (ADR-031): the Kartograf `probe` judges the marker by file name and schema (`adapter/kartograf/marker.py`): `no_marker` with the hint `kartograf store init --root <path>`, `unsupported_marker`, `foreign_store` and `not_a_store`; the generated stores are marked through `kartograf.init_store` (`tests/fixtures/store_marker.py`); the CHANGELOG says **Breaking**. **M3 done**: the texts, the wizard hint, README, USAGE, `.env.example` and the SPEC call the Kartograf directory the store root instead of its `--output` directory, and the SPEC has the names of the convention (`root`, `set_project_root`, the envelope `kartograf-result/1`; for IMGWTools `IMGW_REFERENCE_DIR`, `new` and `unchanged`, the marker fields). **M4 done**: every test runs as on a computer without settings of the producers: `tests/conftest.py` points `nogat.toml` (an empty file), `NOGAT_*`, `KARTOGRAF_*` and `IMGW_*` at a canary tree for the whole session and fails the test after which anything lies in it (`tests/fixtures/isolation.py`). **M5 done** (ADR-033): the Kartograf adapter reports the directory Kartograf uses when a call names no store (`DefaultRootAdapter`, from `store_root()`; the IMGW adapter does the same from `imgwtools.store_root()`, with the layer `dotenv`); `GET /sources` and `archiwista sources` carry it as `default_root` (`/health` does not: it is polled and the report is on demand), `archiwista doctor` prints it and the layer of the settings that gave it, and the first-run wizard offers each producer's root under its own empty field (Kartograf, IMGWTools) when it exists and holds that producer's marker (a click enters it; nothing is written, nothing uses it). Left for the author: D9 and the re-pin (Next 1) |
| IMGWTools source (plan `docs/plans/2026-10-25-archiwista-next.md`, Part 2) | in progress | branch `feature/imgw-source` (from `plan/next-version` on `chore/nogat-2.1` at `093ea8c`, the message catalog), merged into `feature/kartograf-data-output`. Done, each with a green gate: I1 (`EntryMeta` core, the extra `archiwista[imgw]`, the adapter and its probe), I2 commit 1 (the entry point, ADR 0032, the CI job without the extra), I2 commit 2 (`StoreConfig.imgw`, nesting by markers, the wizard field, the scan that skips an unavailable source, the producer of each problem), the re-pin to IMGWTools `7e2114e` (`30175c1`: machine codes, producer fields, `skip_versions`, `py.typed`), I3 commit 1 (`3568ba3`, `SCHEMA_VERSION` 7: slot keys and names, provider, observations as history, segments described by the adapter), I3 commit 2 (`b4c07df`: the current version of a slot from the producer), I3 commit 3 part 1 (`0bf1071`: a scan of one segment goes to the producer that owns it; full gate), part 2 (`3340b12`: an IMGW dataset has its family for a product; reduced gate) and part 3 (the read-only store test and the previous-schema rebuild test; reduced gate), then the re-pin to IMGWTools `3f7de36` with the IMGW default root (`store_root()`). I4 (reduced gate): commit 1 `de2dbf6` (the stations of each provider's current catalog in the index, `SCHEMA_VERSION` 10, `StationCatalogAdapter`, ADR 0032 decision 11) and commit 2 `78ac2c2` (the station queries: box, river with tributaries, counts by location). I5 (reduced gate): commit 1 `3dc92af` (the coverage of each dataset's current series with its years, `SCHEMA_VERSION` 11, `SeriesIndexAdapter`, ADR 0032 decision 12) and commit 2 (the labels of SPEC 4.8.4 from the index, `IndexQueries.station_coverage`, the catalog `series.*`). I6 (reduced gate): commit 1 `2536e27` (`GET /stations`, `/stations/{code}`, `/stations/{code}/coverage` and `/map/stations`: an area with its boundary group by the location uncertainty, the coverage filters before paging with the hidden count, `503` without IMGWTools, an ambiguous code refused; ADR 0032 decision 13) and commit 2 `e4f21e2` (`archiwista stations list` and `stations show`, `--json` equal to the routes). I7 (reduced gate, one commit): the projects of IMGWTools, one project per directory with the manifest of each producer (`SCHEMA_VERSION` 13, ADR 0032 decision 14). Open: I8, the station views of the web interface, planned on 2026-10-26 after the mockup answers M5 and M11 (plan Part 4, steps I8.1 to I8.6; not started). Next 5 gives the details |
| Gate | green | `scripts/gate.sh` passes on `chore/nogat-2.1`: ruff format, ruff check, mypy, pytest with coverage, `scripts/check-commits.sh`. The last run took 32 minutes (1235 tests, coverage 92%) beside other test suites; a quiet machine needs 25 to 33 minutes, so start it without other test suites running. Four flakes found under load are fixed (`3bc0482`, `876824f`, `d14f2f3`, `ebd8ef1`): the one-second limit that was every build's in `test_preview_build_item_timeout_fails_item_only` (only the slow file has one now, `build_timeout_s`), the 5 s that an expectation of the interface tests waited for the page and the server (30 s now), the race of `tests/unit/test_sandbox.py` (a `/proc` read of a process reaped meanwhile) and one hang of `tests/e2e/test_timeline.py` that did not reproduce (`faulthandler_timeout = 600` writes the stacks of a test that runs ten minutes). A job worker interrupted under `--cov` could stay alive: `patch = ["subprocess"]` measures it, and an interrupt that lands in coverage's tracer while it holds its `data_lock` leaves the lock held, so the worker waited for it in its exit handler for good (1 of 200 interrupted processes in a stress run). The first interrupt of a worker now starts a `faulthandler` watchdog that ends it after `STOP_TIMEOUT_S` (`_handle_interrupts` in `jobs/worker.py`, status 1, stacks in the job log); it does not cover an interrupt that arrives while the worker still imports its modules, before the handler stands (the supervisor's killer ends such a worker) |
| Failures of Nogat's final integration run (2026-10-25) | fixed on the branch | Nogat `docs/plans/2026-10-25-final-integration.md` (Failures, Fixes): F8 `6e5517e` (processes that open a new preview cache together: SQLite refused the switch to WAL at once, without the busy timeout, so one could die at its start; that was the flaky `BrokenPipeError` of `test_cache_safe_across_processes`, now the switch is tried again until `BUSY_TIMEOUT_MS`, and `test_cache_opened_by_processes_at_once` failed in every run before it; the index and the state database had the same race, so the commit after it shares the retry as `archiwista.wal.use_wal` among all three, and `tests/integration/test_wal.py`, eight processes initialising each of five new databases together, failed for both in every run before it; the last bare switch, the Kartograf adapter's unit cache `unit_bboxes.sqlite`, uses it since the commit after that, and its case in the same test failed before it too), F3 `bc230d4` (`affine>=3,<4` is declared: the previews use the `@` of affine 3, and Hydrograf caps affine below 3 until pyflwdir releases its fix, so the two applications cannot share an environment), F4 `19ff4d9` and F5 `c168893` (tests made stale by the IMGW default root and the English default). The full gate ran on the branch head before the push; Nogat's report records its result |
| PL-2000 sheet grid ("Siatka godeł") | fixed on the branch | the grid of a view across a PL-2000 zone boundary drew two whole grids over each other (Kartograf took zones as longitude strips). Kartograf `34fab30b` makes a zone the area of its powiats (§ 22 of Dz.U. 2012 poz. 1247, Kartograf ADR-055): `sheet_grid` takes `find_sheet_outlines`, each sheet only inside its zone with its `zone` and the extent of the whole sheet (the view-size estimate); `GET /map/sheets` items carry `zone`, a cut sheet's `geometry` is its part inside its zone (19.3-19.7 E x 51.95-52.05 N at 1:2000: 214 zone-6 + 29 zone-7 sheets, none overlapping; was 228 + 228) |
| The map panel "did not scroll" to "U źródła" in the author's Firefox | fixed on the branch | not the layout: the panel scrolls itself in Firefox 157 and Chromium 156 (1280×720, 1366×768, 1920×1080, 125%, the phone sheet; wheel and keys, also headful with real input). Firefox ran the old demo's modules (`6c8349a`, steps 1-3) after the upgrade: without `Cache-Control` both engines reused the page and the modules by heuristic freshness, F5 revalidates the page only and Ctrl+Shift+R the page's first modules only, never a view's (imported later). `no-cache` (`8d87318`) makes every file revalidate; a browser that cached a version before it needs its cached web content cleared once (CHANGELOG). `engine_tab` runs the panel's wheel test and the upgrade test in Chromium and Firefox; headless Firefox has no WebGL2, and the map now says so instead of an uncaught error |
| CI (Linux) | written, not run | `.github/workflows/ci.yml` and `live.yml`; `feature/kartograf-data-output` and `feature/imgw-source` are on GitHub, and no run of either workflow is known |

Skipped adoption items, which need the author (DEV-3.3, ADOPTION_PLAN):

| Item | Why |
|---|---|
| History rewrite (phase 1) | Archiwista needs only DEV-4.2: every commit is by `Daldek <git@debever.pl>` and has no AI trailer |
| Rulesets for `main`, `develop` and `v*` tags, private vulnerability reporting, Dependabot security updates, `main` pushed and made the default branch (DEV-3.6, DEV-13.6, DEV-13.7, ECO-008) | GitHub settings. The required check is the one job `gate (ubuntu-latest, Python 3.12)` (CI runs on Linux only) |
| `docs/CLA.md` text and signing mechanism | the author's legal text: it says "comment on the pull request", while DEV-16.5 says checkbox plus a line in `CONTRIBUTORS.md` in the same pull request |
| `Approved:` lines of the executed plans v0.1 and v0.2 (DEV-17.4) | approval is the author's statement |
| Tags, releases, replacing the Kartograf commit pin by the tag `v0.8.0`, PyPI name `nogat-archiwista` (phases 5 and 6) | need the producers' tags and the author's approval |
| Push of `chore/nogat-2.1`, pull request, merge into `develop` | approvals (DEV-3.3) |

## Next

1. **Data output (DEV §19, ECO-051): Part 1 of
   `docs/plans/2026-10-25-archiwista-next.md` is done**, on `feature/kartograf-data-output`, one
   commit per step with the gate green before each. Done: M1 (the Kartograf pin
   `8a36e977`, the range `>=0.8.0.dev0,<0.9`, the names `root` and `base`, and REL-2.5 in
   `tests/contract/test_package_data.py`) and M2 (`SourceState` says why: `reason` and
   `hint` travel through every consumer of a probe; the Kartograf `probe` judges
   `kartograf-store.json` and `imgw-store.json` by file name and schema, ADR-031: the
   states `no_marker`, `unsupported_marker`, `foreign_store` and `not_a_store`, the
   generated stores marked through `kartograf.init_store`, contract tests on
   `kartograf.testing`, the CHANGELOG **Breaking** line). A copy of producer knowledge
   stays in the adapter until Kartograf offers `store_state(root)` (a request of the
   plan, not filed), M3 (the names for people: docstrings, the wizard hint, README,
   USAGE, `.env.example`, the SPEC lines), M4 (every test runs with the settings and the
   default roots of the producers pointed at a canary tree that must stay empty) and M5
   (the default roots of Kartograf and IMGWTools are offered in the wizard, never entered by itself or
   used, ADR-033; the request for a size-free `store_root()` is closed: Kartograf `45dedf4a`, the adapter uses it). The
   large `perf` and `smb` stores
   are generated: generate them again with the generator (it marks first), because
   `kartograf store init` refuses their deliberate defects. Then the
   IMGWTools source (I) and v0.3 "Actions" (A) on their own branches. The pinned commit is
   not pushed, so `uv lock` resolves it only in a uv git database that holds it: fetch
   the branch into the database below `~/.cache/uv/git-v1/db/` in which `git cat-file -t
   8e9bcbb058d1…` answers `commit` (`git --git-dir=<db>/.git fetch ~/workspace/Kartograf
   feature/data-output:local-feature-data-output`), then `uv lock --offline`. Re-pin when
   Kartograf rewrites its branch again, before Archiwista is pushed.
2. Replace the Kartograf commit pin by the tag `v0.8.0` in the release pull request
   (REL-5.3, REL-2.1); use `kartograf.testing` (DEV-10.6) instead of the hand-made
   `tests/fixtures/make_store.py` when Kartograf ships it.
3. **CI proof.** The first CI run needs the push: check the Chromium step of `ci.yml` and the
   weekly `live.yml`.
4. **v0.3 "Actions" (plan Part 3).** A1, A2 and A3 are done. A3 commit 1 is in Status.
   *A3 commit 2 (reduced gate):* `AvailabilityInfo` of `GET`/`POST /availability` and of
   `archiwista availability` has `store`, `variant` (the fixed `horizontal`,
   `resolution`, `vertical_crs`) and `rows` (`AvailabilityRowItem`: `label` in the
   request's language, `coverage`, `local`, `other_variants`, `variants` with `formats`,
   `default_format`, `size_bytes`); `services/availability.py` `summary` adds the
   `StoreBadge` (`all`, `some`, `none`; `units` of `of`) from `IndexQueries.held_units`
   (present versions of the shown combination's dataset, its full and partial sheets, its
   year and campaigns) and `known_store` refuses a store that is not configured (`404`,
   before a job); `messages.plural_form` and the catalog entries `availability.label_*`,
   `campaigns_*`, `partial_sheets_*`, `missing_sheets_*`, `other_variants_*`, `local_*`;
   the CLI options `--store`, `--horizontal`, `--resolution`, `--vertical-crs` and a text
   line per year. Tests: `tests/unit/test_availability_labels.py`,
   `tests/unit/test_availability_badges.py`, `tests/integration/test_availability_rows_api.py`
   (the extra member of the refusal table in `test_availability_api.py` is `segment` now:
   `store` is a member). Open: the badge does not tell height systems apart (the plan's
   new request: Kartograf names no store segment of a combination); whether LAZ, the one
   format of point clouds, is a default format (ADR-017 names ASC and GeoTIFF only, so a
   LAZ variant has no default format and no size); the row details of SPEC 6.4 ("w
   ramkach arkuszy: 92%", the list of partial sheets, "w innym formacie: ASCII-NMT" for a
   unit held only in another format of the set) are not built: the API names no unit held
   in another format and no step of the plan builds the details (offline without a
   report the local share is the one of "Stan lokalny": A10). **A4 is done** (Status row
   "v0.3 A4").
   **A5 is done** (three commits, ADR-037). Commit 1:
   `ActionAdapter.run` returns `ActionResult` (`files[]` below the root, `items[]`,
   `status`) with `ActionProgress` counting units, and `ActionAdapter.scope(path)` names
   the segment and the unit (`<slot directory>/<stem>` for Kartograf) a scan reads a
   file's slot by; Kartograf calls `run_command` with `root=`, its cache and a kept plan
   as `update="upgrade"`, a plain or outside file is `BrokenContractError`; the stand-in
   fetches a station's files into its store, waits while the store holds
   `.standin-hold` and reads its store. Commit 2: the job kind `download` (`JOB_RULES`:
   store, network, `JobOverlap`: the same store and call as an active download is the
   warning notice `overlapping_job`; `PROTOCOL_VERSION` 7), `run_download` (progress with
   `unit`, `status`, `message`; `files[]`, `items[]` and `counts` in the result; `partial`
   with failed units, `RunFailedError` with none done; `refresh_view` of the files'
   scopes, of the units the progress named when interrupted, within `RESCAN_STOP_S`),
   `tests/integration/test_download_job.py`. Commit 3: `download` in `ActionKind` and
   `JobRequest` with the optional `plan_job`; `services/actions.start` asks
   `Authorizer.require(actor, "store.write")` first for a download (`403
   permission_denied`, no job row; the route takes `Depends(authorizer)`, the CLI an
   `Authorizer` over `StateStore` as `LOCAL_OWNER`, who holds the role), keeps `no_check`
   for a download, and takes `plan_job` only as a job the principal sees with a kept plan
   (`404` `job.not_found`, `job.no_plan`) of the same store and call (`409`,
   `plan_mismatch`, message `job.mismatched_plan`); `archiwista jobs start download …
   [--plan JOB]` prints the files by status (`job.file_*`) and the failed units;
   `tests/integration/test_download_api.py` (the permission matrix of role, setting and
   agent token, the refusals of a plan by API and CLI, a hidden plan job, the foreground
   run). The CLI always acts as the local owner, so its `403` cannot be shown; it calls
   the same check. **A11 (the plan window), commit 1 is done** (ADR-035 point 6): a
   combination's `commands` (Kartograf's `download_hint`), each variant's `commands` by
   format, the stand-in's lines (`series fetch --station … --kind hydro`), `GET /sources`
   `availability` (`read_availability_products`),
   `tests/integration/test_availability_commands.py`. **A11 commit 2 (the web client) is
   done** with the rows of A10: `SessionState.store_write` (`Authorizer.can(principal,
   "store.write")`, in `POST` and `GET /session`); `api.js` `getAvailability`,
   `checkAvailability`, `parseCommand`, `startJob`, `getJobPlan`; the step "U źródła" of
   the map's panel (`map/source.js`: product of `GET /sources` `availability`, target
   store, report date, "Sprawdź u źródła"/"Sprawdź ponownie", rows with label, best
   variant, badge and "+N wariantów"); the plan window `views/plan.js` (one `check` per
   line of the chosen format, summed counts, size or "co najmniej"/"rozmiar nieznany",
   positions, conflicts, lines to copy, the confirmation above 5 GB or 500 positions, one
   `download` per plan with `plan_job`, progress, files and failed units; disabled with
   the reason without `store_write`; offline disables both actions); labels in
   `labels/actions.js`; `JobStatus` shows the summary of a `partial` job; `bytes()` moved
   to `format.js`. `tests/e2e/test_plan_window.py` (owner journey, non-writer, offline);
   screenshots in `docs/reports/v0.3-screenshots/` (`01`-`06`, paths covered). **A6 is
   done** (Status row "v0.3 A6"; ADR-038). **A7 is done** (Status row "v0.3 A7";
   ADR-039). **A8 is done** (Status row "v0.3 A8"; ADR-040). **A9 is done** (Status row
   "v0.3 A9"; ADR-041; the interface has no control of the warm-up or of its setting).
   **A10 is done** (Status row "v0.3 A10"). **A11 is done** (Status row "v0.3 A11";
   ADR-042). **A13 is done** (Status row "v0.3 A13"; ADR-042 decision 4: a project's
   download and repin start from the card, "Sprawdź aktualizacje" being the project's
   plan; whether criterion 4 wants a window before them too is an open question for the
   author). **A14 is done** (both commits with the reduced gate). Commit 1:
   `tests/e2e/test_acceptance_v03.py` (3 tests, no network): UC-01 with the stand-in
   from the kept area's report to files in the store, the labels of both years and the
   ranking computed by hand from the report the index keeps (criterion 3), nothing
   downloaded before the plan window's confirmation (criterion 4), a server stopped
   during the download leaves it `interrupted` and its retry fetches only the rest
   (criterion 5, retry by `POST /jobs/{job}/retry`: no jobs panel yet); a person without
   `store_writer` gets the download disabled and `403` with no job (criterion 7); UC-06
   over Kartograf's fixture project: status, verify, download of the held pins, the year
   2025 added as a task, and the owner without `store_writer` refused a download and a
   repin (criterion 7). Commit 2: `tests/integration/test_live_actions.py` (marker
   `live`, opted in by `ARCHIWISTA_LIVE_ACTIONS=1`, so the weekly `live.yml` skips it; 3
   tests for the author, about 400 MB from GUGiK): UC-01 (availability of an area inside
   `N-34-130-D-d-2-4`, the plan, the download with the plan, the badge) compared with
   `kartograf elevation download --root` and the same task in a project of each
   (criterion 1: `iter_store` entries, SHA-256, sidecars but `downloaded_at`, pins); a
   project's download of `N-34-130-D-d-2` (four sheets) cancelled after its first sheet:
   no `.incoming`, no problem, no pin, no lock, a clean full scan, and after a run again
   `kartograf project verify` exit 0 (criterion 2); UC-06: status, verify, check, repin,
   then `kartograf project verify` (criterion 6). Archiwista runs in the test process
   (`archiwista.cli.main`), Kartograf's command line as `python -m kartograf` with
   `KARTOGRAF_CACHE_DIR` in the test directory (the canary stays empty). Not run live (D10);
   an offline run with every connection refused (a `sitecustomize` outside the
   repository) failed each test at its first network step only. The report
   `docs/reports/v0.3-measurements.md` (criterion 8 as measured on 2026-10-26: scan 1.4 s,
   warm-up 94.9 s for 353 versions, first thumbnail p95 4.1 ms; the evidence of every
   criterion; screenshots 01–12), USAGE (0.3), AGENT_API (0.3, its limits), SPEC 13 and
   SCOPE stage 4 (status of v0.3), ARCHITECTURE (the report), the CHANGELOG. Open: the
   units colouring on the map of A12 (its jobs view is v0.4 T9); A15 (KB-7); a variant
   without a default format and a plan with conflicts are untested in the browser (the
   stand-in has neither); the live run and the SMB run of criterion 8 are the author's.
   Kartograf's example of `project add` (`… soil hsg --sheet N-34-130-D --depth 0-5cm`)
   is not its canonical line, so the contract test compares calls, not text (a request
   to Kartograf).
5. **The IMGWTools source (plan Part 2; branch `feature/imgw-source`, from `plan/next-version`, both on `chore/nogat-2.1` at `093ea8c`; merged into `feature/kartograf-data-output`).**
   - *Done (local commits; ask git for the remote state).* I1 commit 1 `5e3fffc`; I1 commit 2 `796ee01` (gate 1246 passed,
     coverage 92.04%): the extra `archiwista[imgw]`, `sources/markers.py`, `adapter/imgw/`
     (`PRODUCER` `imgw`, `PACKAGE` `imgwtools`, `SUPPORTED_VERSIONS` `>=3.0.0,<4`, the four
     schemas, `load` through `check_package`; `ImgwAdapter` implements the source interface and
     no optional capability, imports only names of `imgwtools.__all__` and never `pyarrow`),
     `EntryKind` `observation` (the index writer ignores it), `SourceState.reason` and `hint`
     with their pass-through in `SourceRegistry.probe`, `EntryMeta.content_sha256` and
     `content_form`, the catalog entries `source.imgw_*` and `source.schema_unknown`, the shared
     fixture `imgw_store(variant)` and `tests/contract/test_imgw.py` (36 tests over
     `imgwtools.testing`; the probe table is pinned to what `init_store`, `open_store` and
     `iter_store` do with each directory); I2 commit 1 `ccdb2f3` (gate 1248 passed, coverage
     92.00%): the entry point `imgw = "archiwista.adapter.imgw:load"`, ADR 0032
     (`docs/decisions/0032-imgwtools-source.md`, index row in `docs/DECISIONS.md`; 0030 and 0031
     are the adoption ADR and step M2 of the plan), the job `without-extras` of
     `ci.yml` (never run: nothing is pushed), `tests/conftest.py` does not collect
     `contract/test_imgw.py` without IMGWTools, `tests/integration/test_sources_imgw.py`. The
     commits `5e3fffc` and `0c4c8e7` were rebased onto `093ea8c` and got scoped tests only; the
     gate of `796ee01` covers their tree. The environment without the extra, which the CI job
     runs, was checked locally with `UV_PROJECT_ENVIRONMENT=<dir> uv sync --locked` and
     `uv run --no-sync pytest tests/unit tests/integration tests/contract
     tests/e2e/test_shell.py tests/e2e/test_acceptance.py`: 1139 passed, 2 skipped and one
     failure, the set of sources that `tests/e2e/test_acceptance.py` asserted, which was
     corrected and passes with and without the extra. The whole interface suite was not run
     without the extra.
   - *Base and merge with M (done).* `feature/imgw-source` did not have the steps of M: the Kartograf pin
     was `8e9bcbb`, and `SourceState.reason` and `hint` and their consumers were M2's. The merge into
     `feature/kartograf-data-output` kept both sides everywhere. Conflicts, by file: `sources/types.py`,
     `sources/protocol.py`, `sources/registry.py` and `sources/__init__.py` (the doc of `SourceState`
     joined, `CurrentVersionAdapter` beside `DefaultRootAdapter`, the exports of both),
     `services/stores.py` (`issue_problem(issue)` names the producer of the issue, as the IMGW side
     built it, instead of the first producer of the store), `config.py`, `api/models.py` and
     `web/src/types.js` (both directories of a store, each optional), `web/src/setup.js` (the field of
     each producer in the wizard), `tests/conftest.py` (the canary fixtures and the `imgw_store` fixture),
     `tests/contract/test_plugins.py`, `test_source_protocol.py`, `tests/integration/test_doctor_cli.py`
     and `test_read_only_store.py` (the helpers `tree` and `set_read_only` of
     `tests/fixtures/read_only_mount.py`, the directory `base` of the store), `uv.lock`, and the
     documents. The documents of this side are English, so the IMGW passages (SPEC 4.3, 4.4, 4.8.1 and
     5.5, ARCHITECTURE 2.1, 4, 5.1 and 10, DECISIONS) were translated into them; the report and plan
     files kept their translated text (the IMGW side only hid a share name there, which the translation
     had done). Both sides numbered an ADR 0032: the IMGWTools source, written first, keeps 0032 and the
     wizard ADR is 0033. `sources/markers.py` (names of the markers of all producers) and
     `adapter/kartograf/marker.py` (its `OTHER_MARKERS`) both know the name `imgw-store.json`.
   - *Pin (done, `30175c1`; gate 1272 passed, coverage 92.05%).* `imgwtools[store] @
     git+https://github.com/Daldek/IMGWTools@3f7de36f98f1ba40d72ab5556942567cfbc55b92`, the head of
     `feature/data-output` on 2026-10-25 (first pinned at `7e2114e`, one commit after `cc9a596`, which
     changes the output rules of IMGWTools only; `3f7de36` adds `store_root()` from `79ca281`, the
     PMAXTP accessors and the refusal of an unreadable marker). `uv lock --offline` resolves a commit only from
     the uv git database of this URL, here `~/.cache/uv/git-v1/db/a7524ceee79a212b` (`dda4ecb8d2e4e42d`
     is another URL form and unused; uv names its database in the error of a failed fetch, and the
     `https` transport is not allowed here, so a commit the database lacks is not fetched): `git -C
     <that database>/.git fetch --no-tags ~/workspace/IMGWTools feature/data-output`, change the
     commit in `pyproject.toml`, `uv lock --offline`, `uv sync --locked --all-extras`. Used:
     `StoreInfo.problem_codes` (a refused marker is `invalid_marker` or `unsupported_store`;
     `missing_marker` covers a layout without its marker, a directory that is no store and the marker
     of another producer, so the names in the directory still decide), `Meta.producer` and
     `Meta.producer_version` (the sidecar's own, also in the raw sidecar of a file card),
     `iter_store(skip_versions=)` fed with `ScanScope.known_versions`, the reader that needs only the
     `schema` of the marker (a marker without `created_by` is available), `py.typed` (the mypy
     override is gone). A marker that is no JSON is a `data_error` of `open_store` now
     (`IMGWDataError`, reason `invalid_marker`), not an `IMGWStoreError`.
   - *Requests to IMGWTools (DEV-17.5).* The four (a machine code in `StoreInfo`, `producer` and
     `producer_version` in `Meta`, known versions for `iter_store`, a marker without `created_by`)
     are met at the pin; what remains is the registry edge Archiwista to IMGWTools, `planned` to
     `active`, a request to Nogat.
   - *I2 commit 2 `eafd687` (done; gate 1268 passed, coverage 92.05%).* `StoreConfig.kartograf` is
     optional and `imgw` is new (`STORE_PRODUCERS`; a before-validator wants one of them:
     `settings.store_needs_directory`, a problem at `stores[i]`); `roots()` lists the present ones
     and `dump_settings` leaves out `None`; the `StoreSettings` of the API has both (null allowed).
     `check_nesting(roots, skip_markers=...)` adds the markers of `sources/markers.py`
     (`store_around`, `store_below` to `NESTING_DEPTH` 2, no link; the texts `root.in_store` and
     `root.holds_store`, the code `root_nested`) around new or moved roots only (ADR 0032, decision
     6). The wizard offers "Katalog IMGWTools" by `imgwOffered` (`health.sources` has `imgw`
     available, or the store has a directory, saved or typed); `bodyOf` sends `null` for an empty
     directory. `run_scan` skips the directory of a source whose `registry.adapter` raises
     `SourceStateError`, with the notice `source_skipped` (`job.source_skipped`; the routine-scan
     pruning of the supervisor ignores it); `ScanScheduler._available_roots` leaves such a directory
     out of the probe and starts no scan for a store with no available source (it asks
     `registry.states()`, so a test server needs the real registry, not `NoSources`). `IssueRef`,
     `OrphanLink` and `PinRef` carry `producer`, and `issue_problem(issue)` takes none. Tests:
     `test_config.py`, `test_sources_imgw.py` (PUT /settings), `test_unavailable_source.py` (real
     workers; `tests/fixtures/missing_package.py` and the worker hook
     `ARCHIWISTA_TEST_MISSING_PACKAGES`), `tests/e2e/test_setup_imgw.py` (the wizard indexes a store
     of only IMGW files through the scheduler), `test_store_summary.py`. The CHANGELOG, ARCHITECTURE
     4 and 10, SPEC 5.5, USAGE and ADR 0032 are updated.
   - *I3 (commit 1 `3568ba3` is done: gate 1307 passed, coverage 92.48%, 36 min 45 s, load about 3; commit 2 `b4c07df` is done: gate 1341 passed, coverage 92.13%, 34 min 10 s, load about 2; commit 3 is done: part 1 `0bf1071`, part 2 `3340b12` and part 3, two tests).* Facts: the generic scan already indexes
     IMGW entries (`complete` fixture: 11 versions in 8 slots, none current; slots
     `archives/versions/<server dir>/<file stem>`, `series/versions/<slug>`, `stations/versions`, and
     the ČHMÚ catalog in `stations/versions/chmi_stations`); `imgwtools.current_version(root, slot=)`
     reads every sidecar of the slot and raises `IMGWDataError` while any version of it is broken (an
     older one is never chosen; `missing_sidecar` is skipped), so ask it only for slots that changed.
     *Commit 1, the data model and the scan (done)* (`SCHEMA_VERSION` 7, every schema change of I3 in it, so
     the step is +1): `SourceEntry.slot_key` (IMGWTools' `StoreEntry.slot`), `slot_name` (a name for
     people: the file name of an archive, the catalog key for a catalog, else the directory) and
     `observation: SourceObservation` (`seen_at`, `url`, `etag`, `last_modified`, `size_bytes`,
     `sha256`; `version_path` is `<slot>/<same_content_as>/<file>`); the columns `slots.slot_key` and
     `versions.provider` (`_META_COLUMNS`) and the table `observations` (seen by every pass, deleted
     when unseen, never a count, kept only when its slot is known by the end of its batch: it never
     makes a slot; `IndexQueries.observations(store, slot)`); the optional capability
     `SegmentDescriptionAdapter` (`describe_segment` without `segments`; `SegmentedAdapter` extends
     it), and `scan_store` writes the description of each segment the entries named for a producer
     that lists none (`_Totals.segments_seen`); the IMGW adapter describes a dataset from the registry
     (`get_dataset(key).title.localized("pl")`, the country of `get_provider(dataset.provider)`,
     `dataset_key` the key; the catalogs `pl.imgw.stations` and `cz.chmi.stations` are no registry
     datasets: known, named after the provider's `short_name`; any other key is `known=False`, named
     by itself). *Commit 2, the current version:* the optional capability
     `CurrentVersionAdapter.current_version(root, slot_key) -> Path | None` (the version path relative
     to the store); `IndexWriter.finish_pass(current=...)` asks it, outside the transaction, for the
     slots with a `slot_key` that the pass touched (a new or changed version, a new issue, a version
     that reappeared; at the end a version gone missing or removed, an issue resolved), so an
     unchanged incremental scan asks for none, and writes `current_path` only for a version the index
     holds (a dangling one would show as `orphan_sidecar`); the unlinked rule of `finish_pass` skips
     slots with a key; the adapter gives `None` for a slot without a version or with a broken one (an
     `IMGWDataError` that is not `io_error`), and `io_error` stays `SourceUnavailableError`;
     `_SLOT_STATUS` reads the slot's issues by `slot_id` (`no_sidecar` for `missing_sidecar`,
     `unreadable` for the other sidecar codes of both producers), so a slot without a current version
     because of a damaged one is `unreadable`; texts for the IMGW codes in `explain` (`missing_sidecar`
     is an interrupted or running publication, non-critical and usually temporary; `unknown_schema` a
     file of another schema; the others generic); contract and integration tests over `complete`,
     `complete_pl_cz`, `corrupt` and `unknown_schema`. *Commit 3:* the segment ownership below, ADR
     0032 decisions 7 to 9, SPEC 4.3 and 4.4, a read-only store test (chmod 555/444 as
     `test_read_only_store.py`, the tree identical afterwards) and a test that an index of the
     previous schema is rebuilt while `state.sqlite` stays byte for byte. *Segment ownership
     (decided):* `run_scan` finds the producers that own the job's `segment` in the `segments`
     table (a new `IndexQueries` method over `segments.producer`) and scans only their directories;
     a name the index does not know belongs to the producers that scan by segment
     (`SegmentedAdapter`: Kartograf today, so a Kartograf-only store behaves as before); a producer
     that cannot scan one segment (IMGW: `iter_store` has no scope below the directory, and a pass per
     dataset would walk the whole store once per dataset) refuses with `UnsupportedError`, as the
     link check does, instead of the `ValueError` of `scan_store`; there the segment is a label only.
     ADR 0032 decision 7, the SPEC 4.3 tables, ARCHITECTURE 4 and the CHANGELOG went with commit 1;
     decisions 8, 9 and 10 and SPEC 4.4 go with commits 2 and 3. An IMGW dataset has its family for
     a product (decided by the coordinator, ADR 0032 decision 10), so the store view groups the
     datasets instead of listing them under "unknown product".
   - *I3 commits 2 and 3: what building commit 1 added to the design.* `imgwtools.current_version` on the
     fixtures: every slot of `complete` and `complete_pl_cz` answers its newest version (the hydro
     archive `2026-10-19_b6a19f65`, the series `2026-10-19_9a64f921`); in `corrupt` (`invalid_json`) and
     `unknown_schema` (the series version `2026-10-20_c0d4eacd`) the slot raises `IMGWDataError`
     (`data_error`), as it does for `size_mismatch` and `invalid_meta`; a newest version without its
     sidecar (`missing_sidecar`) is skipped and the older one answers; a stray file in a slot directory or
     a linked version directory makes `iter_store` report the whole slot directory as `unknown_entry` with
     no slot, so that slot gets no current version and no issue by `slot_id` (status `missing`).
     *Writer (commit 2):* `_PassState.touched` (slot ids from `batch.versions`, `batch.reappeared` and the
     slots of `batch.issues`; at the end the slots of versions gone missing or removed and of resolved
     issues) plus one rule the first design lacked: slots with a key, no `current_path` and a version
     seen in the pass are asked too, because `current_path` is written only at the end of the pass and a
     pass killed after its batches would leave versions with no current for ever (a broken slot is asked
     again every scan, a few sidecars); `PassSummary.current` counts the slots whose `current_path` the
     answers changed (the job result lists none, so no schema change); `current_path` is written only for
     a version in `state.versions`; the unlinked rule needs `slot.key is None`; the answers are taken
     before the transaction, applied with one `executemany`, and the changed slots go to `_refresh_slots`.
     `_SLOT_STATUS` by `i.slot_id = slots.id` keeps the order of today (`no_sidecar`, then `unreadable`
     for `invalid_sidecar`, `invalid_json`, `invalid_meta`, `unknown_schema` and `unreadable`; not
     `size_mismatch`, which leaves `missing`): run `test_index.py`, `test_scanner.py` and the
     fixture's broken slots of `make_store` for any change of a Kartograf status. `explain` chooses
     `problem.imgw_missing_sidecar` and `fix.imgw_missing_sidecar` by the pair (producer, code) (a set
     `PRODUCER_TEXTS` in `services/problems.py`) and `unknown_schema` joins `KNOWN_PROBLEMS`; a problem has
     no severity, so "non-critical and usually temporary" is the text. The adapter's
     `current_version(root, slot_key)` calls `imgwtools.current_version(root, slot=)` (import it under
     another name), turns `IMGWDataError` with the code `io_error` into `SourceUnavailableError` through
     `_failure`, any other `IMGWDataError` into `None`, and returns `found.version` relative to
     `root.expanduser().absolute()`; `scan_store` passes `current=` to `finish_pass` when
     `isinstance(adapter, CurrentVersionAdapter)`. Tests: contract (each slot equals the producer's, a
     store-relative path; `None` for `corrupt` and `unknown_schema`; the older version for a missing
     sidecar; `io_error` with a sidecar at mode 000, skipped for root) and, in
     `tests/integration/test_imgw_index.py`, `current_path` of every slot equals `current_version`, a
     damaged version is `unreadable` with its issue and no older version is chosen, an unchanged
     incremental scan asks for none (count the calls with a wrapping adapter), a new version moves the
     current one, a pass without `finish_pass` heals at the next scan. CHANGELOG (the entry of commit 1
     says the current version follows), ARCHITECTURE 10 ("indeks nie zna wersji bieżącej"), SPEC 4.4 and
     4.8.1, ADR 0032 decision 8 and the line "without a current version" of its consequences.
     *Commit 3:* `IndexQueries.segment_producers(store, segment)` for `run_scan`, the message
     `job.segment_scan_unsupported`, `ScanRequest.segment` and AGENT_API say that a producer that cannot
     read one segment answers `unsupported`, the doc of `SegmentRef.segment` (a label for IMGWTools), SPEC 4.4
     ("Katalog IMGW jest tylko przyrostowy") and ARCHITECTURE 5, ADR 0032 decision 9. Tests: a store of only
     an IMGW directory refuses a segment scan with `unsupported` and a mixed store scans only the owner
     of a Kartograf segment; the read-only store test over the IMGW fixture (`_tree` and `_read_only`
     of `tests/integration/test_read_only_store.py` move to a fixture module); the previous-schema test
     takes an IMGW index, drops `observations`, `slots.slot_key` and `versions.provider`, sets
     `user_version` to `SCHEMA_VERSION - 1`, expects `initialize` to say `rebuilt` with the digest of
     `state.sqlite` unchanged (as `test_index_rebuild_leaves_state_untouched` does), and a scan to fill it.
   - *I3 commit 2 `b4c07df` as built (the current version; code and tests as designed above, with these differences).*
     (1) An answer is written only when it names a version the pass saw (`state.seen_versions`), not
     merely one the index holds: a version published between the listing and the end of the pass is
     taken by the next scan, and a version this same pass marks missing is never current. (2) The
     adapter answers `None` for every IMGWTools error whose code is `data_error` or `validation_error`
     (`_SLOT_UNREADABLE`), not only for `IMGWDataError`: a slot whose directory is a link, or whose key
     the installed IMGWTools no longer knows, has no current version instead of raising a
     `ProducerError`, because a slot an earlier pass indexed is asked when its versions go missing and
     would fail every scan for ever; `io_error` (and an `OSError`) is `SourceUnavailableError` and
     `store_unavailable` (the marker is gone) stays a `ProducerError`. (3) Names: `CurrentVersionAdapter`
     (`sources/protocol.py`), `CurrentVersionLookup` (`index/types.py`, exported by `archiwista.index`),
     `PassSummary.current`, `_PassState.touched` and `_current_versions` (`index/writer.py`),
     `_current_lookup` (`index/scanner.py`; the view refresh passes it too, which no test exercises:
     no producer has both units and keys), `PRODUCER_TEXTS` (`services/problems.py`), the catalog entries
     `problem.imgw_missing_sidecar`, `fix.imgw_missing_sidecar`, `problem.unknown_schema` and
     `fix.unknown_schema`, and `write_pass(current=)` in `tests/fixtures/index_data.py`. (4) Tests: the
     contract tests of the adapter, the writer's rules in `test_index.py` (a keyed slot, only touched
     slots asked, a version gone, no answer, an answer the pass did not see, a pass killed after its
     batches, the status of each code), the fixtures in `test_imgw_index.py` and the texts in
     `test_store_summary.py`. ADR 0032 decision 8, SPEC 4.4 and 4.8.1, ARCHITECTURE 2.1, 5.1 and 10 and
     the CHANGELOG are written. The current version of a store with 11 versions in 8 slots makes 3 of
     them "unused" in the clean-up report (before it, all 11 were).
   - *I3 commit 3 as built (part 1 `0bf1071`, part 2 `3340b12`, part 3 the commit of two tests).* Part 1 (full gate:
     1345 passed, coverage 92.16%, 31 min 26 s): `IndexQueries.segment_producers(store, segment)` (the
     owners, sorted, from `segments.producer`); `run_scan` loads the adapters of the available directories
     first (so the notices `source_skipped` now come before the scans), then for a `segment` takes the
     owners, or for a name nobody owns the producers that scan by segment (`_segment_scanners` in
     `jobs/worker.py`), and refuses with `UnsupportedError` (`job.segment_scan_unsupported`, no reason)
     before anything is scanned when an asked producer is no `SegmentedAdapter`, which includes a name
     nobody owns in a store with no such producer (an IMGW-only store). `ScanRequest.segment`, `types.js`,
     `SegmentRef` and the protocol doc say so. Tests: `test_queries_segment_producers_name_the_owners_of_a_segment`
     and `tests/integration/test_segment_scan.py` (Kartograf-only store: a name the index knows and one it
     does not; IMGW-only store: a known and an unknown name refused, the index unchanged; mixed store: the
     Kartograf segment scanned alone, the IMGW dataset refused with no progress event). ADR 0032 decision 9,
     SPEC 4.4, ARCHITECTURE 5.1, AGENT_API and the CHANGELOG are written.
   - *Part 2 and the product of an IMGW dataset.* The coordinator's wording was "the dataset family label
     derived from the dataset key"; SPEC 4.2.1 says Archiwista never derives a product from a key, so the
     adapter reads the family from the registry entry the key names (`DatasetDescriptor.kind`: `hydro`,
     `meteo`; the dataset without a kind, PMAXTP, has its slug `pmaxtp`; a station catalog `stations`; an
     unrecognised key none): the same four labels, and the producer's own word for them. Tests: the contract
     of `describe_segment` over every dataset of the registry and
     `test_the_store_view_groups_the_datasets_of_both_providers_by_their_family`; ADR 0032 decision 10 (and
     decision 7 amended), SPEC 4.3, ARCHITECTURE and the CHANGELOG. Part 2 was checked with the reduced gate
     (`ruff format --check`, `ruff check`, `mypy`, `scripts/check-commits.sh`: on 2026-10-25 the coordinator
     dropped pytest and the full gate before commits); the 93 tests of `tests/contract/test_imgw.py` and
     `tests/integration/test_imgw_index.py` had passed before that, and the full gate of part 2 was stopped.
   - *Part 3 as built (tests only; the reduced gate).* `set_read_only(directory, *, read_only)` joined `tree()` in
     `tests/fixtures/read_only_mount.py`, and `tests/integration/test_read_only_store.py` uses both
     (`tests/integration/test_scanner.py` and `tests/e2e/test_acceptance.py` keep their own copies). In
     `tests/integration/test_imgw_index.py`: `test_a_store_without_write_permission_is_scanned_and_read_unchanged`
     (`complete_pl_cz` at modes 555/444; `tree` equal after a full scan, an incremental one and a `read_meta`;
     the modes restored in a `finally`; the versions and problems equal to `iter_store`; skipped for root) and
     `test_an_index_of_the_previous_schema_is_rebuilt_and_a_scan_fills_it_again` (on the index file `DROP TABLE
     observations`, `ALTER TABLE slots DROP COLUMN slot_key`, `ALTER TABLE versions DROP COLUMN provider` and
     `PRAGMA user_version = SCHEMA_VERSION - 1`; `initialize` says `rebuilt`, `index_info.rebuilt_from` is `6`
     and the tables are empty; a new writer, `sync_stores` and a full scan give back the same versions, current
     versions, keys, providers and observations; the file digest and `snapshot()` of a `StateStore` filled with
     `add_people` stay). `DROP COLUMN` needs SQLite 3.35, the minimum the index requires anyway. By the author's
     rule of 2026-10-25 pytest did not run; the bodies of both tests ran once outside pytest against the fixture
     store and passed. Then I4 to I7.
   - *I4 commit 1 as built (the reduced gate).* `Station` (`sources/types.py`) and the optional capability
     `StationCatalogAdapter` (`station_catalog(slot_key)`, `read_stations(root, version)`); the IMGW adapter maps
     `catalog:<key prefix>.stations` of `imgwtools.providers()` to the provider's id and reads a version with
     `read_catalog` (errors through `_failure`/`_unavailable`). `SCHEMA_VERSION` 10: `station_catalogs` (store,
     provider: producer, slot, version, `read_at`), `stations` (UNIQUE store, provider, code; `location` `point` or
     `none` with the catalog's reason; indexes on `code`, `hydrographic_code` and the unlocated rows) and the R*Tree
     `station_points` with the trigger `stations_point_delete` (also fired by the cascade of a removed store).
     `IndexWriter.keyed_slots`, `station_catalogs`, `replace_stations` (one transaction; a code met twice keeps its
     first row) and `drop_stations`; `scan_store` calls `_index_stations` after `finish_pass` of a whole-store pass:
     a catalog is read when its current version is not the recorded one (a full scan reads all), a provider
     without a current catalog is dropped, a `ProducerError` drops the provider and emits `stations_unreadable`
     (`scan.stations_unreadable`), a `SourceUnavailableError` marks the store unavailable and keeps the rows.
     Tests: `tests/contract/test_imgw_stations.py` (10) and `tests/integration/test_imgw_stations.py` (9), run
     alone; both are in `collect_ignore` of `tests/conftest.py` without IMGWTools. Pushed as `de2dbf6`.
   - *I4 commit 2 as built (the reduced gate).* `StationQuery` (store, provider, code, kind, active,
     `river_code` with `river_scope` `exact` or `tributaries`, `bbox`, `location`, `limit`, `cursor`),
     `StationRow` (with `catalog`, the label of the catalog version, and `catalog_version`), `StationCounts`
     (`located` in the box when one is given, `unlocated` after the attribute filters only) and `StationPage`;
     `IndexQueries.stations` (by name, then code, provider and store; keyset cursor bound to the query) and
     `IndexQueries.station(store, provider, code)`. A box takes located stations only (R*Tree candidates, then
     the stored coordinates, edges included) and `location="none"` lists the unlocated whatever the box; a
     river with its tributaries is the range `code <= x < next` plus whole parts for codes with `-`
     (`index.invalid_river_code` for an empty code). Tests: `tests/integration/test_station_queries.py` (8,
     synthetic catalogs, no IMGWTools needed). I6 adds the area (a polygon of `areas`, the boundary group by
     the location uncertainty) and the coverage filters on top of these queries.
   - *I5 commit 1 as built (the reduced gate).* `SeriesListing`, `StationSeries`, `VariableCoverage`,
     `DateRange`, `TimeUnit` and `YearType` (`sources/types.py`) and the optional capability
     `SeriesIndexAdapter` (`series_dataset(slot_key)`, `read_series_index(root, version)`); the IMGW adapter
     maps `series:<dataset key>` of the registry and reads a version with `read_series_index` (errors through
     `_failure`/`_unavailable`; a unit other than day, month or half-year is a `ProducerError`,
     `source.imgw_series_unit`), the provider, family, unit and first year from `get_dataset`, the year type
     from the listing and each file relative to the store. `SCHEMA_VERSION` 11: `series_catalogs` (store,
     dataset: producer, provider, kind, `time_unit`, `year_type`, `first_year`, `periods` as JSON, slot,
     version, `read_at`), `station_series` (UNIQUE store, dataset, code, `variable_key`; `first_date`,
     `last_date`, `with_value`, `accumulated`, `gaps` and `periods` as JSON, `file`, `sha256`, `row_count`;
     index on provider and code) and `series_years` (series id, year type, year: `units`, `known`,
     `with_value`; cascades with its variable). `index/series.py` counts the years (day: ordinal; month:
     `y*12+m-1`; half-year: the hydrological year, hydrological years only), from the first year with a
     known unit to the last; `IndexWriter.series_catalogs`, `replace_series` (one transaction) and
     `drop_series`; `scan_store` calls `_index_series` after `_index_stations`, with the notice
     `series_unreadable` (`scan.series_unreadable`). On the fixture the gap lists give H of `149190310`
     33 days with a value in the hydrological year 2024 where the listing says 2; the ČHMÚ station
     `0-203-1-900002` has 2005 with nothing known. Tests: `tests/contract/test_imgw_series.py` (11),
     `tests/integration/test_imgw_series.py` (17), both in `collect_ignore` without IMGWTools, and
     `tests/unit/test_series_years.py` (8); run alone; pushed as `3dc92af`.
   - *I5 commit 2 as built (the reduced gate).* `index/series.py` gives the label as structure: `SeriesLabel`
     (state `continuous`, `gaps`, `partial`, `no_data`, `unknown`; R, K1-K2, y1-y2, units and units with a
     value of y1-y2, `percent` rounded up and capped at 99, `below_one`, `longest_gap` as `GapRun`,
     `gap_count`, `long_gaps` over 30 days, `complete_years`, `unknown_years` as ranges, `only`),
     `series_label`, `label_year_type`, `default_span`, `year_ranges`. `IndexQueries.station_coverage(store,
     provider, code, *, dataset, year_type, years)` reads `station_series`, `series_years` and
     `series_catalogs` and returns `StationCoverage` per dataset with `CoverageVariable` (the years of R
     and the label; `only` set for a hydro `no_data`); `index.invalid_years` for a reversed range.
     `api/models_stations.py` `series_label_text` writes the text from the catalog `series.*` (en, pl;
     `RRRR.MM.DD`, `RRRR.MM` for characteristics). Tests: `tests/unit/test_series_labels.py` (21, synthetic,
     both languages) and `tests/integration/test_series_labels.py` (17, the fixture with `read_series`
     refusing; in `collect_ignore`).
   - *I6 commit 1 as built (the reduced gate).* `StationQuery` gains `area` (a WGS84 polygon), `boundary`,
     `dataset`, `variables`, `coverage`, `min_complete_years`, `year_type`, `years` and `labels`; `StationRow`
     `on_boundary`; `StationCounts` `boundary` and `hidden`; `StationPage` `coverage`; `StationCoverage`
     `sha256`, `license` and `attribution` (the series version's); new `StationMap`.
     `IndexQueries.stations` applies the attribute filters in SQL, then the area (R*Tree candidates in its
     bounds widened by the largest location uncertainty, `geometry.widen_bounds`, placed by
     `geometry.area_places`: a station whose circle of uncertainty, an ellipse at its latitude, meets the
     boundary is on it), then the coverage filters (the variables they name labelled in R before the page
     is cut), then the keyset page; `IndexQueries.station_map(query, *, limit, grid_columns)` gives points
     or the grid of `footprints` (`_grid`, `_Grid`); `_series_coverage` reads only the years of R in each
     dataset's numbering. `api/stations.py`: `GET /stations` (`StationList`), `/stations/{code}`
     (`StationCard`), `/stations/{code}/coverage` (`StationTimeline`), `/map/stations` (`StationMapView`), all
     `503` without the source (`require_station_source`, `STATION_PRODUCER`); `find_station` refuses a code of
     several stations (`ambiguous_station`, `details.stations`); `_bbox` of `api/models.py` is `parse_bbox`;
     the query models refuse unknown parameters and check `Q:continuous`, `Q:30` and `YYYY[-YYYY]`; the
     catalog entries `api.station_*`, `api.coverage_filter_invalid`, `api.min_complete_years_invalid` and
     `index.coverage_without_dataset`. ADR 0032 decision 13 (the `dataset` parameter
     where SPEC 9.2 had `product`), SPEC 9.2 and 9.3, ARCHITECTURE, AGENT_API (section 5, the errors, the
     limits), CHANGELOG. Tests:
     `tests/integration/test_station_areas.py` (17, synthetic stations, area and series, no IMGWTools) and
     `tests/integration/test_stations_api.py` (24, `complete_pl_cz`; in `collect_ignore`); run alone, with
     `test_station_queries.py`, both `test_series_labels.py`, `test_imgw_series.py` and
     `test_imgw_stations.py` (72) still passing. Not built: the archive badge of SPEC 9.2 and 4.8.4 and the
     input archives of the station card (they need the archives of a dataset's years from the producer, a
     capability over `imgwtools` that the source interface lacks). Pushed as `2536e27`.
   - *I6 commit 2 as built (the reduced gate).* `commands/stations.py`: `archiwista stations list` (its
     options generated from `StationListFilters`, one per parameter of `GET /stations`, a repeatable one
     with `action="append"`, validated by the same model through `query_of`) and `stations show KOD` (the
     options of `StationLookup`), both over `station_list` and `station_card`; `--json` prints the route's
     model, a refusal the route's problem (exit 6 without IMGWTools); Polish lines for a person
     (`cli.stations_*`, `cli.station_*`, `series.year_type_*`, `metavar.code`; "czynna: tak/nie" by
     `cli.station_active_*`). USAGE ("IMGW stations"), AGENT_API (section 1 and 5), ARCHITECTURE,
     CHANGELOG, ADR 0032 decision 13. Tests: `tests/integration/test_stations_cli.py` (26: list and show
     with `--json` equal to the routes over every page, the options equal to the OpenAPI parameters, eight
     refusals equal by API and CLI, `missing_dependency` without the source, the Polish text; in
     `collect_ignore`), run alone. Not exercised by a test: a `bbox` in another CRS (it goes through the
     producer's pinned operation as for `/slots`). Pushed as `e4f21e2`.
   - *I7 as built (the reduced gate; one commit).* A project is its directory (ADR 0032 decision 14):
     `SCHEMA_VERSION` 13 (`projects` one per directory and key, `manifests` per producer, `project_tasks`
     and `pins` with the producer, deleted with their manifest); `PROJECT_MANIFESTS` gains
     `imgw-project.json`; `write_project` joins the directory's project and replaces only its producer's
     tasks and pins; `remove_projects` removes a producer's manifests and a project left without one.
     API (breaking, no alias): `manifests[]` in `ProjectItem` and `ProjectCard`, `producer` on tasks and
     pins, `ProjectStatus.manifests[]` (`ManifestStatus`; the first refusal of a producer is the answer),
     `producer` of `TaskRequest`, `ProjectJobRequest` and `DELETE …/tasks/{name}?producer=`;
     `project_manifest` refuses `producer_required` and `other_producer` (`400`, `details.option`); the
     problem `duplicate_task`; `--producer` of `project-remove` and the four job commands. Web: each
     manifest's values in the list, the card and the store view, "Manifest producenta" on a card of two,
     a task's actions on its own manifest; the plan window offers the projects with a manifest of the
     producer naming the store and names the producer of a download in a project of two. Docs: ADR 0032
     decision 14, errata 1 of ADR-039 and ADR-040, SPEC 4.3, 4.7 and 9.2, ARCHITECTURE, AGENT_API,
     USAGE, CHANGELOG. Tests: `tests/integration/test_imgw_projects.py` (19, both producers' own
     writers, in `collect_ignore`), two in `tests/unit/test_index.py` (two producers in the writer and
     the queries; an index of schema 12 rebuilt), the JSON of `test_projects_api.py` and `test_api.py`
     adapted; unit, integration and contract (1870 passed before the adaptation; the one other failure,
     `test_doctor.py::test_doctor_refused_store_shows_the_fix_the_producer_gave`, is the default port
     8090 in use on this machine) and the project e2e tests (`test_file_projects_store.py`,
     `test_project_actions.py`, `test_pasted_command.py`, `test_acceptance*.py`: 30 passed after the
     plan window's fix) were run; a browser check of a project of one manifest and one of two on a port
     other than 8090 (list, card, store view; Kartograf's verification of the mixed project from the
     card; IMGWTools' refused with `422`). Open: the card enables the actions of an IMGWTools manifest,
     which the API refuses (`no_project_actions`) until v0.5; a broken manifest makes `GET
     /projects/{project}/status` the producer's refusal (the card shows each manifest's stored state).
   - *The gate on a loaded machine.* The full run took 33 to 47 minutes on 2026-10-25. A run
     that overlapped two other gates failed six timing tests that pass alone in 86 s
     (`tests/e2e/test_fan.py` twice, `test_file_projects_store.py::test_disconnected_store_banner`,
     `test_own_data.py` twice, `tests/integration/test_render_pool.py::test_unreadable_cached_as_code_and_timeout_not_cached`);
     the rerun was green. The gate of I2 commit 2 failed twice before it was green, with the load at
     4 to 7: the first run found a real regression (`test_server_scans_configured_store_at_start`
     ran its server with `NoSources`, which now starts no scan; the test passes the real registry
     now) and two timing tests (`test_file_projects_store.py::test_link_check_result_on_file_card`
     and one more); the second failed `tests/e2e/test_map_previews.py::
     test_year_buttons_select_layer_and_tiles` (16 footprints within 5 s; it passes alone in 38 s);
     the third was green. The gate of the re-pin `30175c1` was green at the first run (1272 passed,
     36 min 15 s, load about 3.7).

## Open questions

Decisions awaiting the author:

- DEV-5.1 lets an `app` keep its layout: confirm the `src/` move of the ADOPTION_PLAN row.
- AGI-6.2 names `/openapi.json`; Archiwista serves `/api/v1/openapi.json` behind the session
  and names operations after route functions (no command catalog). Keep, or move?
- AGI-4.1 asks a top-level `schema` in every machine-readable document; the API responses
  and `--json` outputs have none. Add `archiwista-<kind>/1`, or leave it for the catalog work?
- DEV §18 is profile `tool` only, but ECO-028 says all tools read `nogat.toml`
  (`lang`, `data_dir`, `cache_dir`). Should Archiwista, which uses its own `config.toml` and
  platform directories, read it too?
- The pins are the fixed heads of the producers' `feature/data-output` branches, Kartograf
  `34fab30b` (the PL-2000 zones of powiats with `find_sheet_outlines`, Kartograf ADR-055)
  and IMGWTools `6bd35a49` (`e5b4c22`, after Nogat's final integration run); re-pin when a
  producer commits on its branch again before Archiwista is merged.
- The command that marks a store (`kartograf store init --root <path>`) is the `hint` of
  the job error, of the settings problem and of `archiwista doctor`; the status text kept
  for the store (the banner) names the cause only. Should it carry the command too
  (D2)?
- SPEC 13 v0.3 criterion 4 ("every action with the network or a write goes through the plan
  window"): the project card starts a project's download and repin at once, and the
  project's plan is its own action, "Sprawdź aktualizacje" (ADR-042 option I). Should a
  window built from that check stand before the two jobs as well (option H)?
- `main` of this repository is not on GitHub: push and make it the default branch (ECO-008).

Open since the previous PROGRESS (Polish, in git):

- Kartograf: the tag `v0.8.0` waits for the author and the Kartograf team; v0.3 needs KA-4,
  KB-1 to KB-5, KB-7, KC-1 to KC-3, KD-1 to KD-4, KH-1; KF (merged PL + CZ surface) blocks v0.6.
- IMGWTools: 3.0.0 (`slave` from `0d98f3b`, untagged) meets IMGW-1 to 20; the branch
  `fix/archiwista-compat-2` and the tag wait for the author; the v0.5 adapter treats
  `missing_sidecar` as a non-critical, possibly transient problem.
- GPU: the measurement of 30 frames per second or more with 5,000 footprints needs hardware
  WebGL; the test account has no access to `/dev/dri/renderD128`.
- Basemap: one default provider (OpenFreeMap) is an availability risk outside offline mode.
- PRD "Open decisions" (coverage labels before v0.3, the IMGW data format before v0.5, merge
  results as Kartograf products before v0.6, the ČHMÚ adapter) and the mockup questions
  M6 to M8 and M10 (SPEC 16; M5 resolved 2026-10-26, M3 and M11 resolved 2026-10-26 with
  the station views: shapes for the station type, neutral clusters, the coverage fills of
  SPEC 4.8.4, the Timeline as a tab of the Catalog, the stacked comparison; the assistant
  proposal card for IMGW data is deferred after the MVP).
- The mockup (`mockup/`) is a clickable prototype, not production code; its working data
  directory is outside the repository and can be removed with the author's consent.
