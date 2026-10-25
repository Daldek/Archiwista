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
| Nogat standard 2.1, structure and tooling | done | on `chore/nogat-2.1`: uv and `uv.lock`, Kartograf pinned by commit, `src/` layout, `scripts/gate.sh`, `scripts/check-commits.sh`, CI, Dependabot, editor and git files, markers, package-data and README example tests, the ruff rule set of DEV-7.2, `--verbose`, `--quiet` and `ARCHIWISTA_LOG_LEVEL` |
| Nogat standard 2.1, documentation | done | everything is English (`docs/CLA.md`, the author's legal text, excepted; the Polish interface labels stay in quotes): README in the order of DOC-2.1 (146 lines), the project rules of the former `DEVELOPMENT_STANDARDS.md` in CLAUDE.md, the plans in `docs/plans/`, ADR-030 in `docs/decisions/` with the index in `docs/DECISIONS.md`, ARCHITECTURE, DECISIONS, SPEC, the plans, the reports and the mockup README translated, `docs/IMGWTOOLS_REQUIREMENTS.md` removed (IMGWTools 3.0.0 meets it; SPEC 12.7 keeps IMGW-1 to 20) |
| Nogat standard 2.1, error registry (ERR-3, ERR-4, DEV-11.1, AGI-6.3) | done | vendored registry and schemas (`schemas/nogat/`), generated `src/archiwista/_errors.py`, contract tests, problem+json with registry codes, the `archiwista-error/1` document and the exit codes of the CLI, the front end, registry codes in job documents (job rows of 0.2.0 are mapped on read, never rewritten), the message catalog `src/archiwista/messages/` and the error texts that follow `Accept-Language` (English by default, Polish with the header, `Content-Language` on every JSON answer; the stored texts stay Polish); deviations in CLAUDE.md: the stored texts (AGI-6.4), outcome statuses and no result envelope for good |
| Data output (DEV §19, ECO-051) | done on the branch | plan `docs/plans/2026-10-25-archiwista-next.md` Part 1 on `feature/kartograf-data-output` (from `chore/nogat-2.1`): **M1 done**: Kartograf is pinned at `8a36e977` at M1, later re-pinned to `45dedf4a` (`store_root()`), the pushed head of its branch `feature/data-output` (2026-10-25; its own PROGRESS says done except a CLI smoke as a subprocess and the plain-mode prose, and its working tree held uncommitted edits), the supported range is `>=0.8.0.dev0,<0.9` (REL-5.6), the read API and `Project` say `root`, the fixtures call the directory above `data/` `base`. **M2 commit 1 done**: `SourceState` has `reason` and `hint`, which the registry, the scanner, `jobs/availability.py` (`store_unreachable`, which returns the error), the settings problems (`PUT /settings`) and the doctor carry. **M2 commit 2 done** (ADR-031): the Kartograf `probe` judges the marker by file name and schema (`adapter/kartograf/marker.py`): `no_marker` with the hint `kartograf store init --root <path>`, `unsupported_marker`, `foreign_store` and `not_a_store`; the generated stores are marked through `kartograf.init_store` (`tests/fixtures/store_marker.py`); the CHANGELOG says **Breaking**. **M3 done**: the texts, the wizard hint, README, USAGE, `.env.example` and the SPEC call the Kartograf directory the store root instead of its `--output` directory, and the SPEC has the names of the convention (`root`, `set_project_root`, the envelope `kartograf-result/1`; for IMGWTools `IMGW_REFERENCE_DIR`, `new` and `unchanged`, the marker fields). **M4 done**: every test runs as on a computer without settings of the producers: `tests/conftest.py` points `nogat.toml` (an empty file), `NOGAT_*`, `KARTOGRAF_*` and `IMGW_*` at a canary tree for the whole session and fails the test after which anything lies in it (`tests/fixtures/isolation.py`). **M5 done** (ADR-033): the Kartograf adapter reports the directory Kartograf uses when a call names no store (`DefaultRootAdapter`, from `store_root()`; the IMGW adapter does the same from `imgwtools.store_root()`, with the layer `dotenv`); `GET /sources` and `archiwista sources` carry it as `default_root` (`/health` does not: it is polled and the report is on demand), `archiwista doctor` prints it and the layer of the settings that gave it, and the first-run wizard offers each producer's root under its own empty field (Kartograf, IMGWTools) when it exists and holds that producer's marker (a click enters it; nothing is written, nothing uses it). Left for the author: D9 and the re-pin (Next 1) |
| IMGWTools source (plan `docs/plans/2026-10-25-archiwista-next.md`, Part 2) | in progress | branch `feature/imgw-source` (from `plan/next-version` on `chore/nogat-2.1` at `093ea8c`, the message catalog), merged into `feature/kartograf-data-output`. Done, each with a green gate: I1 (`EntryMeta` core, the extra `archiwista[imgw]`, the adapter and its probe), I2 commit 1 (the entry point, ADR 0032, the CI job without the extra), I2 commit 2 (`StoreConfig.imgw`, nesting by markers, the wizard field, the scan that skips an unavailable source, the producer of each problem), the re-pin to IMGWTools `7e2114e` (`30175c1`: machine codes, producer fields, `skip_versions`, `py.typed`), I3 commit 1 (`3568ba3`, `SCHEMA_VERSION` 7: slot keys and names, provider, observations as history, segments described by the adapter), I3 commit 2 (`b4c07df`: the current version of a slot from the producer), I3 commit 3 part 1 (`0bf1071`: a scan of one segment goes to the producer that owns it; full gate), part 2 (`3340b12`: an IMGW dataset has its family for a product; reduced gate) and part 3 (the read-only store test and the previous-schema rebuild test; reduced gate), then the re-pin to IMGWTools `3f7de36` with the IMGW default root (`store_root()`). Open: I4 to I7. Next 5 gives the exact starting points |
| Gate | green | `scripts/gate.sh` passes on `chore/nogat-2.1`: ruff format, ruff check, mypy, pytest with coverage, `scripts/check-commits.sh`. The last run took 32 minutes (1235 tests, coverage 92%) beside other test suites; a quiet machine needs 25 to 33 minutes, so start it without other test suites running. Four flakes found under load are fixed (`3bc0482`, `876824f`, `d14f2f3`, `ebd8ef1`): the one-second limit that was every build's in `test_preview_build_item_timeout_fails_item_only` (only the slow file has one now, `build_timeout_s`), the 5 s that an expectation of the interface tests waited for the page and the server (30 s now), the race of `tests/unit/test_sandbox.py` (a `/proc` read of a process reaped meanwhile) and one hang of `tests/e2e/test_timeline.py` that did not reproduce (`faulthandler_timeout = 600` writes the stacks of a test that runs ten minutes). A job worker interrupted under `--cov` could stay alive: `patch = ["subprocess"]` measures it, and an interrupt that lands in coverage's tracer while it holds its `data_lock` leaves the lock held, so the worker waited for it in its exit handler for good (1 of 200 interrupted processes in a stress run). The first interrupt of a worker now starts a `faulthandler` watchdog that ends it after `STOP_TIMEOUT_S` (`_handle_interrupts` in `jobs/worker.py`, status 1, stacks in the job log); it does not cover an interrupt that arrives while the worker still imports its modules, before the handler stands (the supervisor's killer ends such a worker) |
| Failures of Nogat's final integration run (2026-10-25) | fixed on the branch | Nogat `docs/plans/2026-10-25-final-integration.md` (Failures, Fixes): F8 `6e5517e` (processes that open a new preview cache together: SQLite refused the switch to WAL at once, without the busy timeout, so one could die at its start; that was the flaky `BrokenPipeError` of `test_cache_safe_across_processes`, now the switch is tried again until `BUSY_TIMEOUT_MS`, and `test_cache_opened_by_processes_at_once` failed in every run before it; the index and the state database had the same race, so the commit after it shares the retry as `archiwista.wal.use_wal` among all three, and `tests/integration/test_wal.py`, eight processes initialising each of five new databases together, failed for both in every run before it; the last bare switch, the Kartograf adapter's unit cache `unit_bboxes.sqlite`, uses it since the commit after that, and its case in the same test failed before it too), F3 `bc230d4` (`affine>=3,<4` is declared: the previews use the `@` of affine 3, and Hydrograf caps affine below 3 until pyflwdir releases its fix, so the two applications cannot share an environment), F4 `19ff4d9` and F5 `c168893` (tests made stale by the IMGW default root and the English default). The full gate ran on the branch head before the push; Nogat's report records its result |
| PL-2000 sheet grid ("Siatka godeł") | fixed on the branch | the grid of a view across a PL-2000 zone boundary drew two whole grids over each other (Kartograf took zones as longitude strips). Kartograf `34fab30b` makes a zone the area of its powiats (§ 22 of Dz.U. 2012 poz. 1247, Kartograf ADR-055): `sheet_grid` takes `find_sheet_outlines`, each sheet only inside its zone with its `zone` and the extent of the whole sheet (the view-size estimate); `GET /map/sheets` items carry `zone`, a cut sheet's `geometry` is its part inside its zone (19.3-19.7 E x 51.95-52.05 N at 1:2000: 214 zone-6 + 29 zone-7 sheets, none overlapping; was 228 + 228) |
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
   new request: Kartograf names no store segment of a combination); offline without a
   report the interface shows `GET /local-coverage` ("lokalnie 83% obszaru", A10);
   whether LAZ, the one format of point clouds, is a default format (ADR-017 names ASC
   and GeoTIFF only, so a LAZ variant has no default format and no size); "w innym
   formacie" in the row details (A10). **A4 is done** (Status row "v0.3 A4").
   **A5 (three commits): commit 1 is done** (ADR-037): `ActionAdapter.run` returns
   `ActionResult` (`files[]` below the root, `items[]`, `status`) with `ActionProgress`
   counting units, and `ActionAdapter.scope(path)` names the segment and the unit
   (`<slot directory>/<stem>` for Kartograf) a scan reads a file's slot by; Kartograf
   calls `run_command` with `root=`, its cache and a kept plan as `update="upgrade"`, and a
   plain or outside file is `BrokenContractError`; the stand-in fetches a station's
   files into its store, waits while the store holds `.standin-hold`, and reads its
   store (`tests/contract/test_kartograf_run.py`). Next, commit 2: the job kind
   `download` (`JOB_RULES`: store, network; an active download of the same store and
   call is a warning notice of the new job, SPEC 5.6), `run_download` with
   `ActionProgress` and notices as job events, `files[]` and `items[]` in the result,
   `RunFailedError` when no unit succeeded, and the rescan of the scopes of `files[]`
   (of the plan's positions or the units the progress named when interrupted) with
   `refresh_view`. Commit 3: `download` in `ActionKind`/`JobRequest`, `store.write`
   checked in `start` (`403` before a job row; the CLI acts as `LOCAL_OWNER`), the
   optional `plan_job` (a finished `check` of the same store, producer, command and
   options) and `archiwista jobs start download … --plan JOB`.
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
  results as Kartograf products before v0.6, the ČHMÚ adapter) and the mockup questions M3,
  M5 to M8, M10, M11 (SPEC 16).
- The mockup (`mockup/`) is a clickable prototype, not production code; its working data
  directory is outside the repository and can be removed with the author's consent.
