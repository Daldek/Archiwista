# PROGRESS: Archiwista

Current state only (DOC-6.1). Branch, tag and remote state: ask git (`git status`,
`git log --oneline -10`). History: the git log and [CHANGELOG](CHANGELOG.md); the
Polish session notes that used to live here are in git (`docs/PROGRESS.md` before the
commit that introduced this file).

## Status

| Component | State | Note |
|---|---|---|
| Release 0.2.0 "Previews" | done | released on `develop` (`chore(release): wydanie 0.2.0`), not tagged and not merged into `main` (author's decision); `develop` carries `0.3.0.dev0` |
| Next version v0.3 "Actions" | planned | spec and plan first, then code (PRD F5.3 pre-building of previews included); producer needs: SPEC 12, SCOPE stage 4 |
| Nogat standard 2.1, structure and tooling | done | on `chore/nogat-2.1`: uv and `uv.lock`, Kartograf pinned by commit, `src/` layout, `scripts/gate.sh`, `scripts/check-commits.sh`, CI, Dependabot, editor and git files, markers, package-data and README example tests, the ruff rule set of DEV-7.2, `--verbose`, `--quiet` and `ARCHIWISTA_LOG_LEVEL` |
| Nogat standard 2.1, documentation | in progress | English and current: CHANGELOG, CLAUDE.md, CONTRIBUTING, SECURITY, USAGE, AGENT_API, PRD, SCOPE, this file; open: README, ARCHITECTURE, DECISIONS, SPEC, plans, reports (Next 1.2) |
| Nogat standard 2.1, error registry (ERR-3, ERR-4, DEV-11.1, AGI-6.3) | in progress | done: vendored registry and schemas (`schemas/nogat/`), generated `src/archiwista/_errors.py`, contract tests, problem+json with registry codes, the `archiwista-error/1` document and the exit codes of the CLI, the front end, registry codes in job documents (job rows of 0.2.0 are mapped on read, never rewritten), the message catalog `src/archiwista/messages/` (step 1 of Next 1.1); open: error texts that follow `Accept-Language` (step 2 of Next 1.1); deviations in CLAUDE.md: AGI-6.4 until then, outcome statuses and no result envelope for good |
| Data output (DEV §19) | planned | waits for the producers' development heads; call sites in Next 2 |
| IMGWTools source (plan `docs/plans/2026-10-25-archiwista-next.md`, Part 2) | in progress | local branch `feature/imgw-source`, from `plan/next-version`, both on `chore/nogat-2.1` at `093ea8c` (the message catalog). Done, each with a green gate: I1 (`EntryMeta` core, the extra `archiwista[imgw]`, the adapter and its probe), I2 commit 1 (the entry point, ADR 0032, the CI job without the extra), I2 commit 2 (`StoreConfig.imgw`, nesting by markers, the wizard field, the scan that skips an unavailable source, the producer of each problem), the re-pin to IMGWTools `7e2114e` (`30175c1`: machine codes, producer fields, `skip_versions`, `py.typed`) and I3 commit 1 (`SCHEMA_VERSION` 7: slot keys and names, provider, observations as history, segments described by the adapter). Open: I3 commits 2 (current version) and 3 (segment ownership), then I4 to I7. Next 6 gives the exact starting points |
| Gate | green | `scripts/gate.sh` passes on every commit of `chore/nogat-2.1`: ruff format, ruff check, mypy, pytest with coverage, `scripts/check-commits.sh`. The full run takes 25 to 33 minutes; start it on a machine without other test suites running: while others ran, one run each failed `tests/integration/test_jobs.py::test_preview_build_item_timeout_fails_item_only` (a build limit of 1 s) and `tests/e2e/test_map_previews.py::test_year_buttons_select_layer_and_tiles` (expectations of 5 s), and one run hung in `tests/e2e/test_timeline.py`; each of them passes alone and the rerun of the gate passed |
| CI (Linux) | written, not run | `.github/workflows/ci.yml` and `live.yml`; nothing is pushed |

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

1. **Finish the standard 2.1 adoption on `chore/nogat-2.1`** (one commit per step, gate
   green before each; the source of the rules is the Nogat branch `feature/data-output`,
   `git -C ~/workspace/Nogat show feature/data-output:standards/<file>`; Hydrolog and
   Retman have the same branch name as worked examples):
   1. **Error texts follow `Accept-Language`** (AGI-6.4, AGI-9.2; decided by the coordinator
      for the author; then shrink the AGI-6.4 line of the deviations to the stored texts).
      `detail`, `hint`, `errors[].message` and the texts inside `details` (`preview_reason`,
      `problems`) are English by default and Polish with `Accept-Language: pl` (the interface
      sends it), with `Content-Language` on every problem; `message` and `hint` of the
      `archiwista-error/1` document are English (machine output), the line before it for the
      person stays Polish. One catalog shape, as in IMGWTools
      (`src/imgwtools/messages/__init__.py`): `Text(en, pl)`, a `Message(str)` that keeps its
      key and values, `message(key, lang, **params)`, `localize`, keys `<area>.<name>`,
      modules `messages/<area>.py`, and a test that checks every call against its entry.
      Found out: pydantic turns a `str` subclass in a `str` field into a plain `str`, and so
      does `str(error)` (use `error.message`), so a `Message` survives in exceptions,
      `Problem` and dicts only; texts of response models need the language when they are
      made. Use a context variable for the language, the default of `lang`: the API
      middleware sets it from the header, the CLI sets `pl` for text and `en` under `--json`,
      otherwise `en`; `localize` at the boundaries (`problem_body`, `refuse`,
      `error_document`, a walk over `details` and `errors`). Texts that are stored (the
      `detail` column of the index, job notices) stay Polish through an explicit `"pl"` and
      remain an AGI-6.4 deviation until they keep key and values; the `detail` of a job error
      (`jobs/error.py`, `JobError`) keeps them. Other starting points: `error_document.py`
      (`Problem`, `describe`, `refuse`, `validation_problem`, `preview_reason`),
      `api/errors.py` (`problem_body`, `problem_response`, `_DOCUMENTED`), `errors.py`,
      `services/problems.py`, `config.py` (settings problems).
      **Step 1 is done** (`refactor(messages)`, the catalog without a change of behavior).
      `src/archiwista/messages/` has `__init__.py` (`Text`, `Message`, `message`, `entry`,
      `lookup`, `label`, `localize`, `with_detail`, `language`, `current_language`,
      `placeholders`, `catalogs`, `valid_key`; the language is `pl` until step 2; the spec
      `:sentence` of a field drops a closing full stop) and one module per area (the prefix
      of the old key, but `with` is `common`, `path` is `ref`, `kartograf` is `source`,
      `refresh` is `api`; `metavar` holds the placeholders of the options in `--help`). The
      language of a call is the positional `lang` after the key, else the context
      (`with language("pl"):`). `message` returns a `Message`, a `str` that keeps its key and
      values (`.key`, `.params`, `.lang`, `.localized(lang)`; copies and pickles keep it); a
      `Message` among the values is rendered in the language of its parent. Tables hold keys
      as literals (`api/errors.py` `_DOCUMENTED`, `config.py` `_PYDANTIC_KEYS`, `doctor.py`
      `_FIX_BY_CODE`, `JobConflict.message`), computed keys are f-strings of a known prefix
      (`lookup`, `label("job.state", value)`). `tests/unit/test_messages.py` checks both
      languages of every entry, every call against its entry, unused entries, entries that
      are read without values, and that no module outside the catalog holds Polish text;
      its `_DATA` and `_NAME_TABLES` list what is Polish by design (names, example values of
      the OpenAPI document, the legend names of the class tables); the entries that quote a
      description saying "Polish" go with step 2.
      **Step 2, the behavior, is one more commit.** Starting points:
      - `messages.DEFAULT_LANG` becomes `"en"`; then every test that reads Polish text needs
        `Accept-Language: pl` (API) or `language("pl")` (unit, CLI): run the suite to find them.
      - A pure ASGI middleware (`app.py`, `api/`) sets the language of a request from
        `Accept-Language` (`error_document.language_of`) with `language()`; sync routes run in
        the thread pool, which copies the context, so texts of response models follow it. Every
        problem answers `Content-Language` (now only `pl`) and `Vary: Accept-Language`.
      - CLI (`cli.py`): text output and the parser under `pl`, `--json` and the document
        `archiwista-error/1` under `en`; `refuse` prints `localize(detail, "pl")` for the person.
      - Boundaries: a walk with `localize` over `Problem.details` and `errors` (a `Message`
        anywhere inside) at `problem_body`, `refuse` and `error_document`; `describe` uses
        `error.message`, not `str(error)` (plain); `SettingsValidationError` (the `"; ".join`)
        and `_problem_from_pydantic` (`str(ctx["error"])`) lose the `Message` the same way.
      - Stored texts stay Polish through an explicit `"pl"`: the `stores.detail` column
        (`set_store_status` in `index/scanner.py` and `jobs/availability.py`) and the job
        notices (`emit.notice` in `jobs/worker.py`, `ScanNotice` in the scanner); the AGI-6.4
        line of the deviations shrinks to those.
      - `JobError` (`jobs/error.py`) keeps the `key` and `values` of its `detail` in `to_json`,
        `from_json`, `from_message` and the worker's `error` message (`jobs/worker.py` near
        line 662; protocol version 5 in `jobs/protocol.py`), so `GET /jobs/{id}` and its
        stream render it in the language of the request; an error stored without them is read
        as it is.
      - `area_reader.py` is a worker process whose answer carries a rendered `detail`: add the
        `key` and `values` so the parent renders it in the language of the request.
      - Descriptions that say a text is Polish (`grep -rn Polish src/archiwista`) and the
        entries of `_DATA` that quote them; AGENT_API 9, SPEC 9.1, USAGE, CHANGELOG,
        ARCHITECTURE 5.4 and the deviation line of CLAUDE.md.
   2. **Documents.** README in English in the order of DOC-2.1 (profile `app`: Run and
      Deploy replace Install and Quick start), absolute links (DOC-1.4), at most 400 lines,
      summary at most 400 characters and `pyproject` `description` at most 200 (DOC-2.3);
      move the project-specific rules of `docs/DEVELOPMENT_STANDARDS.md` (sections 5.1, 7, 8
      and 10) into CLAUDE.md and delete the file (DEV-1.3); `git mv docs/PLAN_v0.1.md
      docs/plans/2026-10-18-plan-v0.1.md` and `docs/PLAN_v0.2.md
      docs/plans/2026-10-19-plan-v0.2.md` (DEV-17.4); an ADR `docs/decisions/0030-...md`
      with the index entry in `docs/DECISIONS.md` (DOC-8.2): `src/` layout, uv and the
      commit pin, the gate, Linux-only CI, the deviations of CLAUDE.md. Translate the Polish
      documents (ECO-005), most useful first (`docs/AGENT_API.md` is done):
      `docs/ARCHITECTURE.md` (77 KB), `docs/DECISIONS.md` (93 KB, statuses
      of DOC-8.1), `docs/SPEC.md` (326 KB), the two plans (377 KB), `docs/reports/` (57 KB);
      `docs/IMGWTOOLS_REQUIREMENTS.md` (105 KB) is met by IMGWTools 3.0.0 (IMGW-1 to 20):
      decided (the author delegated it): delete it, keep the IMGW-n identifiers of SPEC 12.7
      and fix the references (SPEC 12.7, 12.8 and 14, SCOPE, PRD, DECISIONS A-ADR-019, 021 and
      025). `<katalog-danych>` becomes `<data-dir>` in what is translated. A model-assisted
      pipeline (code blocks masked, chunks at headings, checks of structure, code spans,
      links, identifiers and numbers, retry) translated all of them in about ten minutes in
      a trial; redo it from the committed text once the error texts (item 1; the job error
      commit has changed SPEC 9.1, ARCHITECTURE 5.4 and AGENT_API already) have changed
      them again. Terms as in the English documents (the Fan, the Timeline,
      the curtain, store, own data, the release names of SCOPE). The code blocks with Polish
      prose (ARCHITECTURE 0 and 1, DECISIONS 0, SPEC 0 to 3, 17, 19 and 29) are translated;
      the ASCII mock-ups and the JSON examples with Polish labels stay.
2. **Data output (DEV §19, ECO-051): migrate the calls to Kartograf after Kartograf has the
   change on its development head** (not before; plan `docs/plans/2026-10-24-data-output.md`
   of Nogat, step 4). Re-pin Kartograf to that commit in `pyproject.toml` (`uv lock`).
   Archiwista keeps calling Kartograf in store mode, so the names change to `root`, not the
   behaviour. Call sites, as of 2026-10-24:
   - `src/archiwista/adapter/kartograf/adapter.py:645` reads `project.output_dir` (becomes
     `project.root`); the docstrings of lines 76, 109, 136 and 167 say "Kartograf's
     `--output` directory" (`--root`); `probe` follows the marker rules (DEV-19.12,
     DEV-19.13): a root with the layout but no `kartograf-store.json` is
     `store_unavailable` with the hint `kartograf store init --root <path>`.
   - Texts: the entries `source.kartograf_not_store` and `fix.source` (`src/archiwista/messages/`
     `source.py` and `fix.py`; they name the `--output` directory), `src/archiwista/config.py:179`,
     `src/archiwista/api/models.py:2401`, `src/archiwista/sources/types.py:4`.
   - `tests/contract/test_kartograf.py:53`, `:55` and `:60` pin the parameter names of
     `list_segments`, `list_partitions` and `iter_store` (`output_dir` becomes `root`); the
     probe tests at `:601` to `:608` and the project reads at `:633` to `:669`.
   - `tests/fixtures/make_store.py`: `StoreManifest.output_dir` (line 340) and its docstrings
     (lines 3, 5, 328, 330) name the store root; the generator writes the marker
     `kartograf-store.json` and the project manifest key `output_dir` (becomes `root`);
     follow-ups: `tests/integration/test_projects.py:88` to `:90` (`_write_manifest`),
     `tests/fixtures/api_store.py:37`, `tests/fixtures/own_data.py:542`,
     `tests/unit/test_own_data_fixture.py:246`, and the `store.output_dir` uses in
     `tests/integration/test_read_only_store.py`, `test_preview_security.py`,
     `test_agent_flow.py`, `test_projects.py`, `test_scanner.py`.
   - `docs/SPEC.md`: section 12 KB-5 (line 3684, `run_command(..., output_dir, ...)`), KA-1
     (3659), KH-1 (3717, `set_project_output_dir`), and the passages that call the
     `--output` directory the store (lines 174, 783 to 785, 813, 1431, 1445, 1458, 1459,
     3118, 3723); the same names in `docs/ARCHITECTURE.md` and `docs/USAGE.md` ("its
     `--output` directory, that is the `data/` directory").
3. Replace the Kartograf commit pin by the tag `v0.8.0` in the release pull request
   (REL-5.3, REL-2.1); use `kartograf.testing` (DEV-10.6) instead of the hand-made
   `tests/fixtures/make_store.py` when Kartograf ships it.
4. **CI proof.** The first CI run needs the push: check the Chromium step of `ci.yml` and the
   weekly `live.yml`. Also look at `tests/unit/test_sandbox.py::
   test_sandbox_child_killed_with_its_group_at_time_limit`: it failed once with a
   `ProcessLookupError` (a `/proc` read of a process that had ended) in a scoped run while the
   machine was loaded; it passed in all full gate runs, so it is a race in the test, not in
   the sandbox: `_running` reads `/proc/<pid>/stat` with `Path.read_text` and catches only
   `FileNotFoundError`, but a process that is reaped after the open makes the read fail with
   `ProcessLookupError` (ESRCH); catching both is the likely fix (not reproduced, the race
   needs the reaping to fall into the read).
5. v0.3 "Actions": spec and plan to be approved before implementation (`docs/SPEC.md` 12 and
   13, SCOPE stage 4).
6. **The IMGWTools source (plan Part 2; branch `feature/imgw-source`, from `plan/next-version`, both on `chore/nogat-2.1` at `093ea8c`).**
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
     are the adoption ADR of Next 1.2 and step M2 of the plan), the job `without-extras` of
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
   - *Base and merge with M.* The steps of M are not on the branch: the Kartograf pin is still
     `8e9bcbb`, and the consumers of `SourceState.reason` and `hint` (scanner, availability job,
     `_probe_root`, doctor, `SourceUnavailableError`) are M2's. A merge conflicts in
     `sources/types.py` and `sources/registry.py` (the two fields and their pass-through exist
     here) and `messages/source.py` (M2 adds `source.no_marker`, `source.foreign_store`,
     `source.unsupported_marker`, rewords `source.kartograf_not_store` and `fix.source`): keep
     both sides.
   - *Pin (done, `30175c1`; gate 1272 passed, coverage 92.05%).* `imgwtools[store] @
     git+https://github.com/Daldek/IMGWTools@7e2114e1424903f1fd8fc036a2cb7aa81df44287`, the head of
     `feature/data-output` on 2026-10-25: one commit after `cc9a596`, and it changes the output
     rules of IMGWTools only, nothing a reader reads. `uv lock --offline` resolves a commit only from
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
   - *I3 (commit 1 is done; commits 2 and 3 are open).* Facts: the generic scan already indexes
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
     decisions 8 and 9 and SPEC 4.4 go with commits 2 and 3. IMGW segments have no product
     (`segments.product` is NULL, IMGWTools has none), so the store view lists them under "unknown
     product" until the interface step names products (I8).
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
- The Kartograf pin is `8e9bcbb`, the head of `origin/develop`; the local `develop` is one
  docs-only commit ahead and unpushed. Pin the local head after it is pushed?
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
