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
| IMGWTools source (plan `docs/plans/2026-10-25-archiwista-next.md`, Part 2) | in progress | local branch `feature/imgw-source`, from `plan/next-version`, both on `chore/nogat-2.1` at `093ea8c` (the message catalog); nothing pushed. Done, each with a green gate: I1 (`EntryMeta` core, the extra `archiwista[imgw]` on IMGWTools `a304521`, the adapter and its probe) and I2 commit 1 (the entry point, ADR 0032, the CI job without the extra). Open: I2 commit 2 (settings: `StoreConfig.imgw`, nesting by markers, the wizard field), I3 (index). Next 6 gives the exact starting points |
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
   - *Done, nothing pushed.* I1 commit 1 `5e3fffc`; I1 commit 2 `796ee01` (gate 1246 passed,
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
   - *Pin.* `imgwtools[store] @ git+https://github.com/Daldek/IMGWTools@a30452182b01f47cc18e48466da4edf4d0c8cb6a`;
     `uv lock` resolved it from the uv git database that holds the commit (Retman put it there
     with `git fetch ~/workspace/IMGWTools feature/data-output`). The branch has moved: `1a24930`
     ships `py.typed` (then the mypy override for `imgwtools` in `pyproject.toml` goes) and
     `7b11755` shows the nested-store refusal in every store plan; a re-pin is one commit (fetch
     into that database, change the commit, `uv lock`, gate), after the last rewrite of the branch.
   - *Requests to file at IMGWTools (DEV-17.5).* `Meta` has no `producer`, `producer_version`
     or raw sidecar (the adapter sets `written_by` to `imgwtools`, leaves `producer_version`
     empty and shows the sidecar rebuilt from `Meta`); `StoreInfo` has no machine code;
     `iter_store` takes no list of known versions, so a scan reads every sidecar; a marker
     without `created_by` is unsupported for the reader and accepted by `open_store`.
   - *I2 commit 2, settings: starting points (as of `ccdb2f3`).*
     - `StoreConfig` (`config.py:171`): `kartograf: AbsolutePath` (:193) becomes optional and
       `imgw` is added, with one validator that wants at least one directory; `_detect_kind`
       (:197) reads the first of them, `roots()` (:226) lists the present ones, and
       `dump_settings` (:1019) must skip `None` members (TOML has no null); a file with only
       `kartograf` must load and dump unchanged. `StoreSettings` (`api/models.py:2449`,
       `_STORE_SETTINGS_EXAMPLE` :402) has `kartograf: str` and needs `imgw`; `save_settings`
       (`api/settings.py`) validates with `exclude_unset`. The subclass `_ExternalStore` in
       `tests/integration/test_second_adapter.py` returns `self.kartograf`.
     - `check_nesting` (`config.py:891`, called by `validate_settings` with every root) tests
       paths only. Add the marker names of both producers (`sources/markers.py`; add helpers
       there, `config.py` may import it): the nearest ancestor of the real path that holds a
       marker, and a marker below the directory. IMGWTools' `_nested_problem`
       (`store/writer.py`) walks the whole tree below the root minus its managed trees; for
       `PUT /settings` on a store of 50,000 slots bound the descent (two levels, no links) and
       say so. Do the marker reads only for roots that are new or moved: `validate_settings`
       skips unchanged roots so that a disconnected share does not block other edits. The texts
       are `root.*` catalog entries (`root.nested` fits an ancestor; a store below needs one),
       `fix.nested` fits both.
     - Wizard (`web/src/setup.js`, `labels/setup.js`, JSDoc `types.js:789`): the field "Katalog
       IMGWTools" is shown when `health.sources` has `imgw` with `status` `available` or the
       store already holds a value (a hidden field must not drop an entry: `bodyOf` keeps it);
       `STORE_FIELDS` (:34), `draftOf`, `emptyStore`, `bodyOf`, `storeErrors` (one of the two
       directories is required), `problemFields` and the summary of `SaveStep` know both fields.
       The Playwright test: the e2e server runs in a thread of the test process and `serve`
       (`tests/e2e/conftest.py`) loads the registry at call time, so a missing package is
       simulated with `monkeypatch.setattr(importlib.metadata, "version", ...)` as in
       `tests/integration/test_sources_imgw.py`; `test_first_run_wizard_saves_settings` must
       still save a store whose `imgw` is `None`.
     - SPEC 5.8: a scan skips the directory of an unavailable source and keeps its entry in the
       settings. Today `run_scan` (`jobs/worker.py:231`) asks `registry.adapter(producer)` for
       every root and raises, and `ScanScheduler._probe` (`jobs/scheduler.py:283`) wants every
       root of a store reachable, so a store with an IMGW directory and no IMGWTools stops its
       Kartograf scans too; skip the unavailable plugin's directory there, with a test. The
       store status is one per store (`set_store_status` in `index/scanner.py`).
     - `services/stores.py:78` names the first producer of `roots()` in every store problem; the
       producer is known per issue (`_issues` in `index/queries.py:2054` joins `segments g`, and
       `IssueRef` at `index/types.py:319` has no producer yet; the slot card uses
       `detail.segment.producer`).
     - Acceptance of the plan: settings with only an IMGW directory validate (also `PUT
       /settings`); a Kartograf directory inside an IMGW store is a `root_nested` problem at
       `stores[0].kartograf` and an IMGW directory inside a Kartograf store at `stores[0].imgw`;
       the wizard test shows and hides the field; the old settings file loads unchanged. Then
       update the sentence of the CHANGELOG entry of I2 commit 1 ("a store takes an IMGW
       directory in the next step"), ARCHITECTURE section 10 ("Do zrobienia: `StoreConfig.roots`
       zwraca dziś tylko katalog `kartograf`"), the settings example of SPEC section 5.5 (line
       1445) and ADR 0032 (consequences).
   - *I3* as in the plan; the slot key is the slot directory, `current_version` is the new
     optional capability, and the generic scan already indexes IMGW entries (versions in their
     slots, no link, so no current version) until then.
   - *The gate on a loaded machine.* The full run took 33 to 47 minutes on 2026-10-25. A run
     that overlapped two other gates failed six timing tests that pass alone in 86 s
     (`tests/e2e/test_fan.py` twice, `test_file_projects_store.py::test_disconnected_store_banner`,
     `test_own_data.py` twice, `tests/integration/test_render_pool.py::test_unreadable_cached_as_code_and_timeout_not_cached`);
     the rerun was green.

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
