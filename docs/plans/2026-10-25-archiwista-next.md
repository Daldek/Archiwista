# Plan: Archiwista next: the data-output migration, the IMGWTools source, v0.3 "Actions"

Approved: 2026-10-25 (delegated approval: the coordinating session of the Nogat
data-output work approved this plan on the author's behalf; the author's own
confirmation is still open, see "Decisions for the author")

Requirements: DEV §19 (DEV-19.1 to DEV-19.20), DEV-17.4, DEV-17.5, DEV-18.2, ECO-051,
REL-5.3, HUB-5.2; SPEC 12 and 13. It carries out step 4 of the Nogat plan
`docs/plans/2026-10-24-data-output.md` (branch `feature/data-output`) and plans what
follows it: the IMGWTools source and v0.3 "Actions".

## Goal

Archiwista calls and reads the two store producers, Kartograf and IMGWTools, with the
names, markers and results of the data-output convention (DEV §19, ECO-051), stays in
store mode, and then builds what its roadmap needs next on the new names, in steps that
one agent can run in one session:

1. **Migration (M).** Kartograf `feature/data-output` (ADR-054) renames the store root,
   adds the marker `kartograf-store.json`, a default root and `kartograf.testing`.
   Archiwista pins that commit, renames what it reads, judges the marker in its probe
   and never relies on a default root.
2. **The IMGWTools source (I).** The planned edge of the registry (`imgw-store/1`,
   `imgw-meta/1`, `imgw-series/1`, `imgw-project/1`) becomes an adapter, an index and a
   read API on IMGWTools ADR-007: the read side of v0.5.
3. **v0.3 "Actions" (A).** Availability at the source with coverage labels, the plan
   window, downloads, background jobs, freshness, project actions and the pre-building
   of previews (SPEC 13, SCOPE stage 4), written against the new API.

Both producers are untagged, so no data is migrated and no old name stays (ECO-020).

## Options

| Option | Verdict |
|---|---|
| A. Migrate first (M1 to M5), then build the IMGWTools source (I) and v0.3 (A) on the new API, the two in parallel on separate branches | Chosen |
| B. Build v0.3 on the current pin `8e9bcbb` and migrate at the release | Rejected: at the pin `run_command(command, options, *, output_dir, ...)` takes the store root as `output_dir`, required, and returns the bare report; ADR-054 gives that keyword the meaning "plain directory", makes the store `root` optional (a forgotten one falls back to the default root without an error) and wraps the result in the envelope `kartograf-result/1`. A call written now becomes a plain write into the store root when the pin moves, and only a root that already has its marker stops it (`output_in_store`). The reports and plans v0.3 reads change too (`files[].file.path` becomes `files[].path`, the `store` of `kartograf-plan/1` becomes `root`), so v0.3 would be written twice |
| C. Wait for the tags `v0.8.0` and `v3.0.0` and pin them | Rejected: the tags need the author (DEV-3.3), and REL-5.3 allows the commit pin that the Nogat plan names |
| D. Accept both names of the store root in the adapter for a transition | Rejected: no aliases or shims (ECO-020); both producers are untagged, so one window of development heads is supported |
| E. Bring all of v0.5 (stations views, charts, synchronisation) forward with the source | Rejected: stations, charts and synchronisation need the mockup answers (SPEC 16, M5 and M11) and the v0.3 action layer; only the read side is planned (Part 2) |
| F. Let Archiwista write the marker of the author's existing stores (`kartograf store init`) | Not now: the store is read-only for Archiwista (CLAUDE.md), so the interface shows the command to copy; the author decides (D2) |

## Decision

Option A, with these rules for every step:

1. **Store mode only.** Archiwista never writes plain files through a producer. Every
   call that can write names the store: `root=` of Kartograf, `options["root"]` of
   IMGWTools. A call without it would write to the producer's default root
   (`<data_dir>/kartograf`, `<data_dir>/imgw`), not to the configured store, and no
   error says so: at the pin `output_dir` was required, now `root` is optional, and
   IMGWTools' `validate_command` fills the default in. No call passes `output_dir` or
   `output`. M4 and the tests of A5, A7 and A8 hold this with a canary default root.
2. **The store root is the directory with the marker.** The configured producer
   directory (`StoreConfig.kartograf`, later `imgw`) is the root of DEV-19.2. The
   directory called `data/` is only the usual name of it, so "its `--output` directory"
   goes out of code, texts and documents (M3). Polish: "katalog główny magazynu".
3. **The marker is judged in the adapter, by file name and schema** (DEV-19.12):
   `kartograf-store.json` (`kartograf-store/1`), `imgw-store.json` (`imgw-store/1`);
   nothing is imported from another producer. A contract test against the producer's own
   builder (`kartograf.testing`, `imgwtools.testing`) and its `store init` pins the
   judgement, so it cannot drift. A root with the layout and no marker is unusable until
   the producer's `store init` has run (DEV-19.13); Archiwista shows the command and
   does not run it (D2).
4. **Pins are commits** (REL-5.3), and the development version `0.8.0.dev0` is inside the
   supported range until the tag (D3).
5. **Gaps are requests** (DEV-17.5). What Kartograf or IMGWTools lacks is listed under
   "Requests", not worked around. A v0.3 feature that needs a missing function is built
   as far as the delivered API allows, and its step says what waits.
6. **Way of working** (the Nogat rules). M runs on the local branch `feature/data-output`
   from `chore/nogat-2.1`, after the message catalog commit of `wip/message-catalog` is
   on it (M2 and M3 add catalog entries); I runs on `feature/imgw-source` and A on
   `feature/actions-v0.3`, both from the head of M. Nothing is pushed, tagged or merged
   without the author (DEV-3.3). One commit per step unless the step names more;
   English Conventional Commits (`!` for a breaking change); `scripts/gate.sh` (about 25
   minutes, alone on the machine) green before each commit, scoped tests while working;
   the CHANGELOG `[Unreleased]` entry in the commit of a user-visible change (DOC-7.2);
   PROGRESS before the last commit of a session (DEV-17.3); a decision with alternatives
   is an ADR in `docs/decisions/`, numbered after 0030 (the adoption ADR of PROGRESS
   Next 1.2). New and edited documents are English; the Polish SPEC is edited in place
   and its translation (PROGRESS Next 1.2) starts after M3.
7. **Tests are offline.** Producers' stores come from `kartograf.testing` and
   `imgwtools.testing`, actions from a stand-in adapter registered through the entry
   points as `tests/fixtures/second_source/` is. What only a real network or a real
   store can show is a `live` test that the author runs (D10); the step says which.

## Steps

Order: M1 to M5, then I and A in parallel. They touch different modules; what they share
is the index schema number (each step that changes `SCHEMA_VERSION` takes the next free
one; the index is rebuilt, not migrated, SPEC 4.4) and `sources/`. References are
`file:line` at `2b167c3` (2026-10-25) and only locate the work. Each step ends with its
acceptance tests; "(new)" means a test file or test to write.

| Step | What | Commits | After |
|---|---|---|---|
| M1 | Pin, range and names | 1 | the Nogat coordinator names the Kartograf commit |
| M2 | The marker in the probe | 2 | M1 |
| M3 | Names for people, SPEC | 1 | M2, the message catalog commit |
| M4 | Tests isolated from the user's producer settings | 1 | M1 |
| M5 | The default root in the wizard | 1 | M4, D7 |
| I1 | The IMGWTools adapter | 2 | M2 |
| I2 | Register the source, configure the directory | 2 | I1 |
| I3 | Archives, series and catalogs in the index | 3 | I2 |
| I4 | Stations | 2 | I3 |
| I5 | Series coverage | 2 | I4 |
| I6 | Read API and CLI for stations | 2 | I5 |
| I7 | Projects of IMGWTools | 1 | I3 |
| I8 | Stations on the map and in the Catalog | blocked | mockup answers, I6 |
| A1 | The action capability and the command catalog | 2 | M4 |
| A2 | Availability job and the stored report | 2 | A1 |
| A3 | Coverage labels, variants, store badge | 2 | A2 |
| A4 | The plan: the check job | 2 | A1 |
| A5 | Download job, permission, rescan | 3 | A4 |
| A6 | Job controls: cancel, retry, log | 1 | A5 |
| A7 | Projects: create and change tasks | 2 | A1 |
| A8 | Projects: download, repin, check, verify | 2 | A5, A7 |
| A9 | Pre-building of previews | 2 | M4 |
| A10 | Interface: availability rows | 2 | A3 |
| A11 | Interface: the plan window and the pasted command | 2 | A4, A5, A7 |
| A12 | Interface: jobs | 2 | A6 |
| A13 | Interface: project actions | 2 | A8 |
| A14 | Acceptance, documents, report | 2 | A1 to A13 |
| A15 | Area by unit name | blocked | KB-7 |

### Part 1. Migration to the data-output convention (M)

What the producers changed and where Archiwista meets it (read at Kartograf
`feature/data-output` `7394e8ea` and IMGWTools `feature/data-output` `a304521`):

| Name or behaviour | Pin `8e9bcbb` | After the convention | Archiwista sites |
|---|---|---|---|
| Store root of the read API | first parameter `output_dir` of `list_segments`, `list_partitions`, `iter_store` | `root` | calls at `adapter.py:120,188,317,424` are positional; the contract pins the name, `tests/contract/test_kartograf.py:53,55,60` |
| Store of a project | `Project.output_dir`, manifest key `output_dir` | `Project.root`, key `root` of `kartograf-project/1` | `adapter.py:645`; fixtures and tests of M1 |
| Version string | `0.8.0` | `0.8.0.dev0` (Kartograf commit `51fb3128`, REL-1.1) | `adapter/kartograf/__init__.py:17`; `test_kartograf.py:271` |
| Sidecar `kartograf-meta/1` | no producer fields | optional `producer`, `producer_version`; `Sidecar` has both | not read yet (I1 reads them for both producers) |
| Marker | none | `kartograf-store.json`, schema `kartograf-store/1` with `schema`, `tool`, `created_at`, `producer_version`; the first write and `kartograf store init` (public `init_store`) create it | `probe` and the fixtures (M2) |
| Default root | none | `KARTOGRAF_ROOT`, `[kartograf] root` of `nogat.toml`, else `<data_dir>/kartograf`; `get_config()` reports it with its source | never used for a call (Decision 1); suggested in the wizard (M5) |
| Builders for tests | hand-made `tests/fixtures/make_store.py` | `kartograf.testing`: `build_fixture_store`, `build_project`, `make_sidecar` (real writers, marker included) | contract tests of M2; the generator stays for scale (M2) |
| `run_command`, `check_command` (first called by A4 and A5) | `output_dir` required; they return the report and the bare plan | `root` optional (default root); they return the envelope `kartograf-result/1` (`status`, `items`, `notices`, `result`); no `cancel` | none today |
| Plan document `kartograf-plan/1` | key `store` | key `root`, plus `mode` (`store` or `plain`) and `output_dir`; a plan file of 0.8.0-dev is refused | none today; A4 and A5 read it |
| Download reports `kartograf-download/1` | `files[].file.path` and the other fields of the file | `files[]` of `{path, size_bytes, sha256, status}`; store statuses `new`, `unchanged` (also the old `local` and `reused`) and `relabeled`, with `label` and `version_path` of the immutable file; plain statuses `written` and `replaced`; also `skipped[]`, `mode`, `root` | none today; A5 reads them |

What does not change. Archiwista calls no writing function of Kartograf today (the
adapter imports readers only), so `files[]`, `skipped[]`, `mode`, the plan document and
`--check` have nothing to migrate: A4 and A5 meet them first and are written against
ADR-054. Archiwista's own `--output FILE` options (`preview`, `layers`, `state export`)
write exactly one file, which is the meaning of `--output` in DEV-19.1; they stay. The
layout of the store (`<segment>/versions/…`, hard links) is unchanged, and so is the
settings file: `stores[].kartograf` names the producer's directory, which is now called
the store root.

States of a configured Kartograf directory (the table M2 implements):

| Directory | Probe now | Probe after M2 (`status`, `reason`) |
|---|---|---|
| cannot be listed | `error` | `error`, as now |
| empty | `available` | `available`: a new store, whose first write creates the marker (DEV-19.13) |
| known segments, marker of schema `kartograf-store/1` | `available` | `available` |
| known segments but not one file below them, no marker | `available` | `available`: no layout yet (Kartograf's `has_layout` is false) |
| known segments with a file, no marker | `available` | `incompatible`, `no_marker`; hint `kartograf store init --root <path>` |
| marker of another schema, or not JSON | not seen | `incompatible`, `unsupported_marker`; the text names both schemas |
| `imgw-store.json` in the root | not seen | `incompatible`, `foreign_store`; the text says it is an IMGW store |
| segments but none known (the parent of the store) | `incompatible` | `incompatible`, `not_a_store`; the text asks for the directory that holds `kartograf-store.json` |

1. **M1. Pin, range and names** (one commit; every part is needed for a green gate).
   - *Before.* Kartograf `feature/data-output` is complete (Nogat plan step 2) and its
     head is the commit to pin. On 2026-10-25 the head is `7394e8ea` and the tree is not
     clean (plain mode of the tracks and the `output_dir`/`root` group are open), so M1
     starts when the Nogat coordinator names the commit. The commit is not pushed, so
     `uv lock` resolves it only where the uv git database of Kartograf's URL holds it
     (Nogat plan step 7, "Integration rule"): `git fetch` the local branch into the
     database below the uv cache `git-v1/db/` that holds the current pin (the one in
     which `git cat-file -t 8e9bcbb058d1…` answers `commit`), then run `uv lock`.
   - *Change.* `pyproject.toml:14-18` (the commit and its comment) and `uv.lock`;
     `SUPPORTED_VERSIONS` of `adapter/kartograf/__init__.py:17` becomes
     `>=0.8.0.dev0,<0.9`, because PEP 440 sorts `0.8.0.dev0` below `0.8.0` and the range
     `>=0.8.0,<0.9` would report Kartograf `incompatible` (checked with `packaging` on
     2026-10-25; the release pull request restores `>=0.8.0` with the tag, D3);
     `SCHEMAS` (`:18`), `api/models.py:271,275` and `tests/unit/test_doctor.py:22` add
     `kartograf-store/1`; `adapter.py:645` reads `project.root`.
   - *Fixtures and tests.* `STORE_API` of `test_kartograf.py:53,55,60` names `root`.
     `StoreManifest.output_dir` (`make_store.py:340`) is **not** the store: it is the
     directory that holds `data/`, `projects/` and `other-data/` (the store is its
     `.root`, `:348-350`), and `test_probe_accepts_store_and_rejects_its_parent`
     (`:594-608`) uses it as "the parent of the store". A rename to `root` would clash
     with that property: rename it `base`, also `PreviewStore.output_dir`
     (`preview_store.py:116,135`), the `output_dir` argument of `make_store`,
     `make_preview_store` and `make_layer_store` (`layer_store.py:126-135`) and the
     positional `output_dir` of their command lines (`make_store.py:2213`,
     `preview_store.py:590`): about 110 uses in 19 files. What is Kartograf's own becomes
     `root`: `init_project(..., output_dir=)` at `make_store.py:1931` and
     `own_data.py:543`, the manifest key written by hand at `test_projects.py:88-91`,
     `opened.output_dir` at `test_store_fixture.py:379` and `open_project(...).output_dir`
     at `test_own_data_fixture.py:246`.
   - *Acceptance.* `test_installed_kartograf_within_supported_range` and the whole
     `tests/contract` pass offline; `grep -rn output_dir src tests` finds no use that
     means a store; the Nogat integration check (plan step 7) installs Archiwista's
     offline suite at this head and passes; PROGRESS records the pinned commit and the
     state of the head.
2. **M2. The marker in the probe** (two commits).
   - *Commit 1, `SourceState` says why.* `SourceState` (`sources/types.py`) gets the
     optional `reason` and `hint` (default `None`, so the stand-in adapter of the tests
     is unchanged). They travel through `registry.py:288-320` (it rebuilds the state and
     today copies `status`, `store` and `detail` only), `index/scanner.py:956-968`,
     `jobs/availability.py:16-36`, `config.py:913` (`_probe_root`, whose problem code is
     `source_<status>`) and `doctor.py:31-45,237` (`_FIX_BY_CODE`); `SourceUnavailableError`
     (`errors.py:129`) takes `reason` and `hint`, so a refused store is
     `store_unavailable` (8) with `details.reason` `no_marker` and the hint of DEV-19.13
     instead of `store_unreadable`. *Acceptance:* a unit test per consumer with a
     stand-in state; a probe without reason behaves as before (the existing
     `test_scanner`, `test_config`, `test_doctor` pass unchanged).
   - *Commit 2, the rules (breaking; ADR 0031).* The Kartograf `probe` implements the
     table above by file name and schema after `list_segments`, and looks for a first
     file below the known segments only when the marker is missing. The texts are
     catalog entries in both languages (`source.no_marker`, `source.foreign_store`,
     `source.unsupported_marker`, and the reworded `source.kartograf_not_store` and
     `fix.source`; before the catalog commit they are `messages.py:267-270` and
     `:386-389`). The fixture generators write the marker first: one helper
     `mark_store(root)` in `tests/fixtures/` calls `kartograf.init_store` on the empty
     root, and `make_store`, `make_preview_store` and `make_layer_store` use it before
     they write a file. `make_store.py` stays the source of scale (50,000 slots, the
     file families, the deliberately broken cases), which `kartograf.testing` does not
     offer. The ADR records the rules (decision 3 above).
     The CHANGELOG says **Breaking**: a Kartograf directory needs its marker, run
     `kartograf store init --root <path>` once.
   - *Acceptance.* (new) `tests/contract/test_kartograf_marker.py` with
     `kartograf.testing.build_fixture_store`: the store is `available`; with
     `kartograf-store.json` removed it is `no_marker` with the hint; after
     `kartograf.init_store(root)` it is `available` again; known segments without any
     file and no marker are `available`; a marker with schema `kartograf-store/2` is
     `unsupported_marker`; an `imgw-store.json` in the root is `foreign_store`; an empty
     directory is `available`; the parent of the store is `not_a_store`. A scan job of
     the unmarked store ends `failed` with `error.code` `store_unavailable`,
     `error.details.reason` `no_marker` and the hint; `PUT /settings` with it answers
     `400` with the problem at `stores[0].kartograf` and the same text; `archiwista
     doctor` prints the fix. The suite still passes with every generated store marked.
3. **M3. Names for people** (one commit; before the translation of the SPEC).
   - *Texts.* The docstrings at `adapter.py:76,109,136,167`, `config.py:179`,
     `api/models.py:2455` and `sources/types.py:4`; the wizard hint
     `web/src/labels/setup.js:30`, the comment `web/src/setup.js:3` and the JSDoc
     `web/src/types.js:789`; `README.md:59`, `docs/USAGE.md:20` and `.env.example` (the
     live store must be marked). The Polish hint says: the store root, the directory that
     holds `kartograf-store.json` and the product directories, e.g.
     `/mnt/nas/kartograf` (the example no longer ends in `/data`).
   - *SPEC.* In place, in Polish: 174, 783-784 and 813 (the manifest key `root`; the
     relative path of 4.6 point 7 is about `root`), 1431 and 1445 (the wizard and the
     settings example), 3131 (`POST /projects` takes one member `root` for both
     producers, D6), 3683 (KA-1 `list_segments(root)`), 3708 (KB-5: `run_command(command,
     options, *, root, update=None, plan=None, …)`; Kartograf returns the envelope
     `kartograf-result/1`, and has no `cancel` yet), 3741 (KH-1 becomes
     `set_project_root(project_dir, *, root)`), and the IMGW names of ADR-007: 971
     (`IMGW_REFERENCE_DIR`), 3804 and 3806 (`new` and `unchanged`, not `created` and
     `reused`), 477 and 3860 (the marker has `tool`, `created_at`, `producer_version`,
     and keeps `created_by`).
   - *Acceptance.* `grep -rn -e "--output" -e output_dir` over `README.md`, `docs/SPEC.md`,
     `docs/USAGE.md`, `src` and `tests` finds only Archiwista's own `--output FILE`, the
     history of IMGWTools 2.1.1 (SPEC 3747 and 3803) and nothing that names a store;
     `tests/unit/test_messages.py` passes (both languages, every entry used).
4. **M4. Isolate the tests from the user's producer settings** (one commit). Kartograf
   now reads `nogat.toml` and `KARTOGRAF_*`/`NOGAT_*`, and IMGWTools `IMGW_*`, so a test
   would use the developer's real settings and default root. An autouse fixture in
   `tests/conftest.py` points `NOGAT_CONFIG` at a missing file and `NOGAT_DATA_DIR`,
   `NOGAT_CACHE_DIR`, `KARTOGRAF_ROOT` and `IMGW_ROOT` into a per-test canary tree, sets
   `NOGAT_LANG` and `KARTOGRAF_LANG` to a fixed value (Kartograf's default is `pl`) and
   fails the test when anything appears in the canary root. Child processes inherit it
   (`serving_*` build their environment from `os.environ`). *Acceptance:* (new) a test
   that sets the variables to different values and runs the adapter's read calls sees
   the canary untouched; a deliberate write to `kartograf.get_config().store.root` in a
   throwaway test makes the fixture fail.
5. **M5. The default root in the wizard** (one commit; D7). The Kartograf adapter gets an
   optional capability `default_root()` from `kartograf.get_config()` (`store.root`,
   `source` `default`, `env` or `file`, `exists`, and whether it carries the marker);
   `GET /sources` reports it; the first-run wizard suggests it as the Kartograf directory
   when it exists and is marked, and never writes it. `archiwista doctor` prints the root
   and its source. *Acceptance:* (new) with `KARTOGRAF_ROOT` set in the server's
   environment the suggestion is that path; with nothing set it is
   `<NOGAT_DATA_DIR>/kartograf`; an unmarked or missing root is not suggested; a
   Playwright test of the wizard fills the field from the suggestion.

Closes PROGRESS Next 2 (call sites) and the `kartograf.testing` half of Next 3. What is
left for the author: mark the real stores (D9).

### Part 2. The IMGWTools source (I)

What the adapter must know about IMGWTools after ADR-007 (read at `a304521`):

| IMGWTools | Archiwista |
|---|---|
| Marker `imgw-store.json`, schema `imgw-store/1`: `schema`, `tool` (`imgw`), `created_at`, `producer_version`, and `created_by`, which the reader still requires; a root with `archives/`, `series/`, `stations/` or `pmaxtp/` and no marker is `store_unavailable` (`no_marker`), hint `imgw store init --root <path>`; an empty root may hold only the server's `api_keys.json` | `probe` (I1) with the table of Part 1, by file name |
| `store_info(root, /)` returns `supported`, `schema`, `problems` (texts only) and never raises for a missing or unknown marker; every reader raises `IMGWStoreError` (`unsupported`) on an unsupported root | I1 uses it; the missing machine code is a request |
| `root` is an option inside the `options` of `run_command`, `check_command` and `validate_command`, which fills in the default root `<data_dir>/imgw` (`IMGW_ROOT`) when it is missing | the adapter builds `options` in one place and always sets `root` (Decision 1) |
| Readers: `iter_store(root, /, *, kind=None, provider=None)` with the kinds `archive`, `series`, `catalog`, `pmaxtp`, `observation`, `problem`; `read_meta`, `current_version(root, /, *, slot)`, `read_catalog`, `read_series_index`, `read_series`, `summarize_series`; `open_project`, `get_project_status` | I1 to I7 |
| Statuses `new`, `unchanged`, `relabeled` (a series is `unchanged`, not `reused`); `files[]` of `{path, size_bytes, sha256, status}` in every writing result | SPEC 12.7 text (M3); read by the action layer later |
| Project manifest `imgw-project.json` keeps the key `store_dir` (`init_project(dir, /, *, store_dir)`, `set_project_store`), while Kartograf's key is now `root` | `ProjectInfo.store` is producer-neutral; `POST /projects` says `root` for both (D6) |
| `run_command(command, /, *, options, on_progress, on_notice, cancel)`: IMGWTools has `cancel` | the action capability of A1 takes `cancel` as optional |
| One package for IMGW-PIB and ČHMÚ (`provider` `IMGW-PIB`, `CHMI`), extra `[store]` (`pyarrow`); importing `imgwtools` never imports `pyarrow` | one adapter; the extra is `archiwista[imgw]` (A-ADR-024) |
| `imgwtools.testing.build_fixture_store(root, *, variant=…)`: `complete` (archive in three versions, one `relabeled`; two series, one outdated; catalog with stations without location), `corrupt`, `unknown_schema`, `complete_pl_cz` (ČHMÚ files, an observation, the ČHMÚ catalog) | the fixtures of I1 to I7 (answers Q13 of the requirements) |

1. **I1. The adapter** (two commits; not registered yet).
   - *Commit 1, the common core of a sidecar.* `EntryMeta` gets the fields of DEV-19.16
     that it lacks: `provider`, `written_by` (the sidecar's `producer`) and
     `producer_version`; the Kartograf adapter fills them from `Sidecar.provider`,
     `producer` and `producer_version` (Kartograf's view already reports `kartograf` and
     `kartograf_version` for a sidecar written before them), and `STORE_RECORDS` of
     `test_kartograf.py` lists the three. The index keeps `provider` (I3).
   - *Commit 2, the dependency and the adapter.* `pyproject.toml`: the extra
     `imgw = ["imgwtools[store] @ git+https://github.com/Daldek/IMGWTools@<commit>"]`,
     the head of IMGWTools `feature/data-output`, pinned with the recipe of M1, and
     `uv.lock`. `src/archiwista/adapter/imgw/` has `__init__.py` with `PRODUCER = "imgw"`,
     `PACKAGE = "imgwtools"`, `SUPPORTED_VERSIONS = ">=3.0.0,<4"` and `SCHEMAS` (the four
     contracts of the edge), as the Kartograf package has, and an adapter that implements
     the whole `SourceAdapter`:
     `probe` (the IMGW rows of the table in Part 1, from `store_info` and file names, with
     the reasons of M2; an empty root, or one holding only `api_keys.json`, is
     `available`), `iter_entries` (every `iter_store` kind: archives, series and catalogs
     as `version` entries, `problem` entries with the producer's `problem_code`,
     observations as publication history that is never a version), `read_meta`
     (`EntryMeta` from `imgw-meta/1`, `dataset_key` `None` for an unknown key,
     `content_sha256` and `content_form` of a ČHMÚ file kept when present and `None`
     when not, never computed), `footprint` (`country` for archives and series),
     `read_project` and `project_status` (`open_project`, `get_project_status`). Only this
     package imports `imgwtools` (`tests/contract/test_imports.py` is extended), and it
     does not import `pyarrow`.
   - *Acceptance.* (new) `tests/contract/test_imgw.py` over
     `imgwtools.testing.build_fixture_store`: for `complete` the entries equal what
     `imgwtools.store.iter_store` yields (kind, slot, label, `sha256`), `relabeled` is the
     same content under a new label, an outdated series is a version; for `corrupt` and
     `unknown_schema` the producer's problem is reported and nothing is parsed; for
     `complete_pl_cz` the observation is not a version and the stations of the two
     providers do not collide; the probe table, with `init_store` of `imgwtools.store`
     turning `no_marker` into `available`; `read_meta` carries the DEV-19.16 core for an
     archive, a series and a catalog; a project built with the producer's `init_project`
     and `add_project_task` is read; the installed `imgwtools` is inside
     `SUPPORTED_VERSIONS` (`>=3.0.0,<4`).
2. **I2. Register the source and configure the directory** (two commits; an ADR).
   - *Commit 1, registration.* The entry point `imgw = "archiwista.adapter.imgw:load"`;
     `load` goes through `check_package` with the constants of I1 and creates the
     adapter, as `archiwista.adapter.kartograf.load` does; `doctor.py` and `GET /sources`
     list it; `.github/workflows/ci.yml` gets the second configuration without the extra
     (it cannot run before the push). The ADR records the source: one adapter for IMGW-PIB
     and ČHMÚ, the extra, the read-first order. Registry: the edge Archiwista to
     IMGWTools moves from `planned` to `active` (a request to Nogat, below).
   - *Commit 2, settings.* `StoreConfig` (`config.py:169`) gets the optional `imgw`
     directory and `kartograf` becomes optional, at least one required; `roots()`
     (`:224`) lists both; `check_nesting` (`config.py:886`) also looks for the marker
     names of both producers in the ancestors and descendants of a configured directory
     (DEV-19.14), beside the path test it does today; the wizard shows the IMGW field only
     when the source is available (SPEC 5.8).
   - *Acceptance.* (new) `GET /sources` lists `imgw` with versions and schemas; with the
     import failing it is `not_installed` with the fix `pip install "archiwista[imgw]"`
     and the Kartograf source is unaffected; settings with only an IMGW directory
     validate; a Kartograf directory inside an IMGW store (marker found in an ancestor) is
     a `root_nested`-class problem at the right field; a Playwright test of the wizard
     shows and hides the field; the old settings file (only `kartograf`) loads unchanged.
3. **I3. Archives, series and catalogs in the index** (three commits).
   - *Change.* The scan indexes IMGW slots (`archive:<dataset>:<path>`,
     `series:<dataset>`, `catalog:<provider>.stations`) and versions; the current
     version comes from a new optional capability of the source interface
     (`current_version`), because IMGWTools has no links; `missing_sidecar` is shown as a
     non-critical, possibly transient problem, a version of an unknown schema as a problem
     of that file, never as the state of the source (SPEC 4.1, 5.8); observations are kept
     as the history of their slot and change no count; the segment of an IMGW entry is its
     dataset (name from the dataset registry). `SCHEMA_VERSION` +1.
   - *Acceptance.* (new) over `complete` and `complete_pl_cz`: the index agrees with
     `iter_store` in versions and problems (SPEC 13 v0.5, criterion 1); the current
     version of each slot equals `current_version`; a damaged version in a slot is
     reported and an older one is not chosen silently; a store mounted read-only scans
     (`tests/fixtures/read_only_mount.py`); an index of the previous schema is rebuilt and
     `state.sqlite` is untouched.
4. **I4. Stations** (two commits). The current catalog (`read_catalog`) fills `stations`
   and the R*Tree `station_points`: code as text, kind, name, river, hydrographic code
   (with a prefix index for "the river with its tributaries", P19), provider, and for a
   station without a position its reason (`none`, `zero`, `outside_country`), which keeps
   the station (P13, A-ADR-022); a new catalog version replaces the rows. `SCHEMA_VERSION`
   +1. *Acceptance:* (new) the row count equals the catalog's, stations with `geometry`
   `null` are present with their reason, the box filter returns only located stations,
   the prefix filter of a synthetic list returns `2138` and `21382` for `2138` and not
   `2139`, and two providers' stations never collide on a code.
5. **I5. Series coverage** (two commits). `series.json` (`read_series_index`) fills
   `station_series` and `series_years`: per variable (H, Q, T; the variables of the
   meteo datasets), per station, both year types, with gaps, accumulated sums and the
   known periods (SPEC 4.8.4, P14 to P16); the labels are computed from the index
   without reading the Parquet series. *Acceptance:* (new) a table of edge cases (SPEC 11)
   built from the fixture series by hand: continuous, with gaps, empty, a year unknown
   because a ČHMÚ station has no file for it (not a gap), a variable with accumulated
   sums; hydro and meteo in both year types; `read_series` is monkeypatched to raise and
   the labels still come out.
6. **I6. Read API and CLI for stations** (two commits). `GET /stations`,
   `/stations/{code}`, `/stations/{code}/coverage` and `GET /map/stations` with the
   filters of SPEC 9.2 and 6.7 (area or box, kind, variable, coverage per variable, years
   and year type, active, location, river code with `exact` or `tributaries`); counters
   of stations without a position; `archiwista stations list|show` with `--json`
   equal to the route's model (AGENT_API); `503 source_unavailable` when the source is
   not available. *Acceptance:* (new) route and CLI agree on the fixture store; the group
   "without position" is counted after attribute filters and never joined to an area
   silently (SPEC 4.3 point 3); the OpenAPI test lists the routes.
7. **I7. Projects of IMGWTools** (one commit). Project directories are found by both
   manifests; a project can hold `kartograf-project.json` and `imgw-project.json`; tasks
   and pins carry the producer; a broken manifest of one producer does not hide the
   other; a task name used by both is warned about (SPEC 14). *Acceptance:* (new) a
   directory with both manifests built by the producers' own `init_project`
   gives one project with tasks of both; pins link to versions of the IMGW index;
   `project_status` states as in the fixture; no action exists yet (A7 and A8 are
   producer-neutral and v0.5 adds the IMGW commands).
8. **I8. Stations on the map and in the Catalog (blocked).** The interface of stations
   (symbols and clusters, the group "without position", coverage labels and their
   patterns, the station card, the chart) waits for the mockup answers M5 and M11 of
   SPEC 16, which are the author's. It is planned as a separate plan when they exist.

After A8 and I7 the IMGW actions (check and synchronise archives, build series, project
tasks of IMGWTools, export of a series, the card and comparison of stations) reuse the
action layer of v0.3 and are the plan of v0.5; ČHMÚ views are v0.6.

### Part 3. v0.3 "Actions" (A)

Scope and criteria are SPEC 13 "v0.3" (eight criteria) and SCOPE stage 4. The layer is
producer-neutral: a new optional capability `ActionAdapter` of the source interface
(commands from the producer's catalog, `parse`, `validate`, `format`, `check`, `run`,
availability, project operations) with its own types (`CommandInfo`, `CommandCall`,
`ActionPlan`, `ActionResult`), so no Kartograf class leaves `adapter/kartograf` and the
IMGW adapter can implement it in v0.5 (Kartograf: `run_command(command, options, *,
root=…)` returns the envelope `kartograf-result/1`; IMGWTools: `run_command(command, /,
*, options)` with `root` in `options`). Calls run in worker processes (`jobs/worker.py`,
one new `JobKind` each, with its `JOB_RULES` line); Kartograf's metadata cache is
Archiwista's own (`cache_dir/kartograf`, never `cache=True`, D5). Permissions: reading a
catalog, a status or a stored report needs a session; a check or a verification of a
project needs `project.view`; changing a manifest needs `project.write`; every write of
the store needs `store.write` (`store_writer` or `store_write_for_all`), refused with
`403 permission_denied` before a job exists (criterion 7). Every action test runs under
the canary of M4 and records the keyword arguments the producer received.

Criteria of SPEC 13 and where each is shown: 1 parity with the CLI: A14 (live); 2 no
partial version after a cancel: the mechanics in A5, the producer's part in A14 (live);
3 labels of the Kraków area: A3; 4 every network or write action through the plan window:
A11 and A14; 5 restart and retry: A5; 6 UC-01 and UC-06 live: A14; 7 `403` without
`store_writer`: A5 and A8; 8 the first thumbnail after pre-building: A9 and A14.

What Kartograf delivers for v0.3 and what waits (read at `7394e8ea`; the identifiers are
those of SPEC 12; Kartograf's PROGRESS files the plan item size under "KH"):

| Item | State | Interim in this plan |
|---|---|---|
| KB-1 to KB-4 | delivered as `list_commands`, `command_schema`, `parse_command`, `validate_command(…, root=)`, `format_command(…, run=)` | A1 |
| KB-5 | delivered as `run_command` and `check_command`; both return the envelope; `root` keyword; no `cancel` | A4, A5 |
| KD-1, KD-2 | delivered (`sheet_records`, `campaign_coverage`, `full_m2`) | A3 |
| KC-1 `cancel` | open | SIGINT to the worker, then kill after the timeout (SPEC 5.6); versions are published atomically |
| KC-2 phase and bytes in `on_progress` | open; `DownloadProgress` is `current`, `total`, `sheet`, `status`, `message`; `soil` and `soil hsg` take no `on_progress` | progress counts units, no bytes; no progress for soil and HSG |
| KC-3 plan item size | open | the plan says "size unknown"; an availability combination has `size_bytes` |
| KD-3, KD-4 | open | images and unit products show the units of the plan (SPEC 6.3 table) |
| KA-4 for `PlanItem` | open; `file_footprint` takes `StoreEntry` only | planned units are not drawn on the map |
| KB-7 | open | A15 waits; areas by code only |
| KH-1 | open; no setter of a project's store | no "change store" action; the interface explains |

1. **A1. The action capability and the command catalog** (two commits; an ADR).
   - *Commit 1.* The types and the protocol in `sources/`; the Kartograf adapter builds
     the catalog from `list_commands()` and `command_schema()`, and implements `parse`,
     `validate` (always with `root=`) and `format`; a stand-in action adapter for tests.
   - *Commit 2.* `GET /commands`, `POST /commands/parse`, `/validate` and `/format`
     (SPEC 9.2) and `archiwista commands list|parse|validate|format --json`
     (AGENT_API parity). The Kartograf text of an error is kept; `option` becomes
     `details.option`.
   - *Acceptance.* (new) `GET /commands` lists the ids of `kartograf commands list`; for
     the examples of each command in `kartograf-commands/1`, `format(parse(line))` is
     the line; an invalid `--year` is `400` with `details.option` `year` and Kartograf's
     text; a missing Kartograf makes only its commands `503 source_unavailable`; a
     socket guard shows that none of this touches the network.
2. **A2. Availability job and the stored report** (two commits). A job kind
   `availability` (network, offline mode answers `409 offline_mode` and records nothing)
   runs `check_availability` for elevation (NMT, NMPT, LAZ; PL and CZ) with the area (a
   box, or the copy of a geometry file in the work directory, SPEC 6.3); the report goes
   to a new table `availability` (area, product, `checked_at`, document). `POST
   /availability` answers a stored report younger than seven days without a job unless
   `force` is set, else starts the job; `GET /availability` returns the last report with
   its date and never uses the network. `SCHEMA_VERSION` +1. *Acceptance:* (new) with the
   stand-in adapter: offline refusal; fresh report without a job, `force` with one; the
   recorded call has Archiwista's `MetadataCache` and no `cache=True`; an index of the
   previous schema is rebuilt.
3. **A3. Coverage labels, variants and the store badge** (two commits). A service
   `services/availability.py` turns a report into rows: the label of SPEC 6.4
   ("pełne", "pełne · N kampanie", "częściowe · N%", "brak danych") as structure, not
   text; the ranking of variants for a year (full before partial, larger share of full
   sheets, fewer campaigns, finer resolution, the report's order); formats of one set
   grouped into one variant (A-ADR-017); the badge from the index ("pobrane", "pobrane
   5/12", "niepobrane") and, offline, "lokalnie 83% obszaru" from the local coverage that
   exists. *Acceptance:* (new) a table of the rows of 6.4: the percentage rounds down and
   a partial combination never shows 100%; a share below 1% is "<1%"; "N campaigns" counts
   the campaigns of the sheets Kartograf will download, not `len(campaigns)`; the Kraków
   2023 example ranks PL-2000 above PL-1992 with "+1 variant"; ASC and ASCII-NMT of one
   set are one variant with the size of the default format; the expected values of three
   years are computed by hand in the test from sheet records (SPEC 13 criterion 3).
4. **A4. The plan: the check job** (two commits). A job kind `check` runs
   `check_command` (and `check_project`, A8) and stores an `ActionPlan`: entries with the
   status (`current`, `newer`, `missing`, `unverifiable`, `check_failed`), the local and
   the available label, the store path, the size or `null`, the counts, the equivalent
   `kartograf …` line (`format`) and the target store. `POST /jobs` (SPEC 9.2) takes the
   kinds of A4, A5 and A8. *Acceptance:* (new) an entry's status, labels and path equal
   what the stand-in producer returned; an unknown size is `null`, never 0, and the
   total says whether it is complete; a failed check of one position is `check_failed`
   and the job ends `partial`, not `failed`. Kartograf's own plan needs the network, so
   its parity is the live test of A14.
5. **A5. The download job, the permission and the rescan** (three commits).
   - *Change.* A job kind `download` runs `run_command` (and, with the plan of a finished
     `check` job, `update="upgrade", plan=…`, so "Pobierz nowsze" runs the plan that was
     shown and positions that changed meanwhile come back `stale`); `DownloadProgress`
     and notices become job events; the result keeps `files[]` and `items[]` of
     `kartograf-download/1` (`path`, `size_bytes`, `sha256`, and `new`, `unchanged` or
     `relabeled`; `version_path` of the immutable file) and refuses a plain status
     (`written`, `replaced`) as a broken contract; when the job ends, also when it is
     cancelled, a targeted scan of the units named by `files[]` updates the index; the
     permission is checked in the service, so the API, the CLI and an agent token agree.
   - *Acceptance.* (new) a session without `store_writer` gets `403` and no job row, by
     API, CLI and agent token (criterion 7); at most two network jobs run, and an
     overlapping job on the same store, segment and units warns (SPEC 5.6); progress and
     notices reach `GET /jobs/{id}/events`; after the job the index shows the new
     versions without a manual scan; a running stand-in job is interrupted and ends
     `cancelled` with the rescan done; a server stopped mid-job leaves `interrupted`, and
     a new job with the same parameters finishes the rest without fetching the finished
     units again (criterion 5; A6 adds the button); the recorded call has `root` equal
     to the store's directory, the `update` and `plan` given, and no `output_dir`; the
     canary root stays empty. That no partial version survives is Kartograf's property
     (atomic publication, SIGINT cleanup) and is checked live (criterion 2, A14).
6. **A6. Job controls: cancel, retry, log** (one commit). `POST /jobs/{id}/cancel`
   (`JobSupervisor.cancel` exists, `jobs/supervisor.py:740`), `POST /jobs/{id}/retry` and
   `GET /jobs/{id}/log` (the job's log file), and `archiwista jobs list|show|cancel|retry|log`.
   *Acceptance:* (new) cancelling a queued job ends it without a worker; a running one
   ends `cancelled` within the stop timeout; retry of an `interrupted`, `failed` or
   `cancelled` job starts a new job with the same parameters, and of a succeeded one is
   `409`; a job of a project the session does not see is `404` for all three; the CLI's
   `--json` equals the route's model.
7. **A7. Projects: create and change tasks** (two commits). `POST /projects` (a
   `producer` and a `path`; the store is the configured directory of that producer, and
   `root` is written relative to the project directory when the store has path aliases,
   SPEC 4.6 point 7, else absolute; never the default root), `POST /projects/{id}/tasks`
   (`add_project_task`, offline validation) and `DELETE /projects/{id}/tasks/{name}`
   (`remove_project_task`), `GET /projects/{id}/status` (`project_status`); the CLI with
   the same members.
   `project.write` is the permission (the owner or an administrator). *Acceptance:*
   (new) the manifest written equals the one the producer's own calls write for the same
   arguments; an invalid option is `400` with `details.option` and the producer's text;
   a project the session does not see is `404`, one it may not change `403`; the
   canary root stays empty.
8. **A8. Projects: download, repin, check, verify** (two commits). Job kinds for
   `download_project` (`update` unset: pin or restore), the repin of one task
   (`update="upgrade"`, `tasks=[name]`), `check_project` and `verify_project`; one job per
   project; a lock left by an interrupted manifest write (`.kartograf-project.lock`) is
   recognised and the job ends `conflict` with `details.reason` `project_locked` and the
   instruction (SPEC 5.6, 14). Download and repin need `project.write` and `store.write`;
   check and verify need `project.view`. *Acceptance:* (new) the permission matrix of the
   five actions over owner, other user, administrator and agent token; a planted lock is
   reported with its path and not removed; a second job on the same project queues or is
   `409 conflict`; the recorded calls carry no `output_dir`.
9. **A9. Pre-building of previews** (two commits). A job kind `preview_warm` builds the
   thumbnail and a low-zoom overview of the current versions only, at low priority in the
   render pool, within the memory limit and the LRU (never evicting a recently used
   preview), and ends with the reason and the number of versions skipped when the budget
   runs out; `archiwista preview warm [--product P] [--segment S] [--project X]
   [--area-id N] --json`, an HTTP route for the same (SPEC 5.7), and the administrator's
   setting that starts it after a scan (off by default). It uses no network, reads the store
   read-only and follows the visibility rules of previews (A-ADR-029). *Acceptance:*
   (new) the visibility matrix (a private project's own data is not warmed for, nor
   listed to, a person who may not see it); an interactive preview is served while a warm
   job runs (latency within the target of SPEC 4.5); with store files made unreadable
   after the warm-up the first thumbnail of a warmed version is still served; a read-only
   mounted store works; criterion 8 is measured on the reference computer as a `perf`
   test (and `smb` on the share) and reported in A14.
10. **A10. Interface: availability rows** (two commits). In the main flow (area, product,
    availability) the rows with their labels, badge, chips ("+N warianty"), "Sprawdź
    ponownie" (`force`) and the offline banner "Brak sieci — pokazuję tylko magazyn"; the
    Polish texts and plural forms ("1 kampania", "2-4 kampanie", "5+ kampanii", 22-24 and
    25; "1 ark. niepełny", "2 ark. niepełne", "5 ark. niepełnych") in
    `web/src/labels/`. *Acceptance:* (new) `tests/e2e/test_availability.py` (Chromium): a
    stand-in report gives the rows with the right texts and plurals, the ranking chip and
    the badge; offline shows the banner and the local share; keyboard focus and
    text-visible labels (colour never the only carrier, SPEC 6.4).
11. **A11. Interface: the plan window and the pasted command** (two commits). "Pobierz…"
    opens the plan window: counts, size (or "rozmiar nieznany"), the target store, the
    `kartograf …` line with a copy button, the format choice (nothing chosen silently
    when no raster format is the default), "Dodaj jako zadanie projektu", and the extra
    confirmation above a threshold (SPEC 10.3); a text field takes a pasted command
    (UC-15). Every action with the network or a write goes through it (criterion 4); a
    session without the write permission sees the action disabled with the reason.
    *Acceptance:* (new) e2e: from a row to the window to a started job, from a pasted
    command to the same window, an invalid command shows the producer's text at the field,
    the size is "unknown" and not "0 MB", and the add-as-task option creates the task (A7).
12. **A12. Interface: jobs** (two commits). The "Zadania" bar and panel, units that change
    colour on the map while the job runs (mockup M7), notices, cancel, retry, the log, and
    the state "przerwane" after a restart with "Ponów". *Acceptance:* (new) e2e with a
    stand-in job that emits progress, is cancelled, is interrupted by a server restart and
    is retried.
13. **A13. Interface: project actions** (two commits). Create a project, add and remove a
    task, status, check, verify, download and repin, with the producer column and the
    instruction for a left lock. *Acceptance:* (new) e2e over the stand-in project
    operations; a hidden project is not offered; an action the person may not do is
    shown disabled with the reason.
14. **A14. Acceptance, documents and the report** (two commits).
    - (new) `tests/e2e/test_acceptance_v03.py` runs UC-01 and UC-06 offline with the
      stand-in and asserts criteria 3 to 5 and 7 on the whole path.
    - (new) `tests/integration/test_live_actions.py`, marker `live`, for the author:
      UC-01 with one NMT sheet (the same command through Archiwista and through the CLI
      into two stores gives the same versions, `sha256` and pins, sidecars equal but for
      `downloaded_at`, criterion 1), a cancel during a download followed by `kartograf
      project verify` and a clean scan (criterion 2), UC-06.
    - The report is `docs/reports/v0.3-measurements.md` (English), with criterion 8.
      USAGE, AGENT_API, SPEC 13 (status of v0.3), the CHANGELOG and PROGRESS are brought
      up to date. The release `0.3.0` is the author's (no tag, no merge).
15. **A15. Area by unit name (blocked on KB-7).** `find_admin_units` is not in Kartograf;
    until it is, an area is chosen by code as in v0.1. No workaround.

## Requests

To be opened as GitHub issues labelled `request` in the producer's repository (DEV-17.5)
by the author or by a session with access; none is a blocker of M.

| To | Request | Needed by |
|---|---|---|
| Kartograf | KC-1: `cancel` in `run_command`, `check_command`, the project functions and `check_availability` | A5 (interim: SIGINT) |
| Kartograf | KC-2: phase and `bytes_done` and `bytes_total` in `on_progress`, and `on_progress` for `soil` and `soil hsg` | A5 |
| Kartograf | KC-3: `PlanItem.size_bytes` (Kartograf's PROGRESS calls it KH; the two lists use different identifiers and should be reconciled) | A4, A11 |
| Kartograf | KD-3 and KD-4: availability of images and of releases of unit products | A2, A10 |
| Kartograf | KA-4: `file_footprint` for a `PlanItem` | A11 |
| Kartograf | KB-7: `find_admin_units` | A15 |
| Kartograf | KH-1 as `set_project_root(project_dir, *, root)` (the SPEC called it `set_project_output_dir`) | a later "change store" action (A13 explains) |
| Kartograf | a read-only `store_state(root)` in `kartograf.__all__` (`marked`, `layout`, `new`, `foreign`), so that consumers need not judge the marker by file name (Retman keeps a copy too) | M2, I1 (removes the copy) |
| IMGWTools | a machine code in `StoreInfo` (today only `problems` texts; `missing_marker` covers a layout without a marker and a foreign directory) | I1 |
| Nogat | registry: the edge to Kartograf gets `uses` and `exchange` for the command layer (`kartograf-commands/1`, `kartograf-result/1`, `kartograf-download/1`, `kartograf-availability/1`, `kartograf-testing`); the edge to IMGWTools becomes `active` with I2 and gets `imgw-plan/1`, `imgw-result/1`, `imgw-testing` | I2, A1 |

## Risks

| Risk | Effect | Handling |
|---|---|---|
| The producers' heads move: Kartograf `feature/data-output` is unfinished and will be rebased onto the message catalog (Nogat plan, Results); the commits of both producers are unpushed | a pin names a commit that changes or that GitHub does not have; Archiwista's CI cannot be green before the producers are pushed (HUB-5.2) | re-pin after the last rewrite and before Archiwista's push; the git-database recipe of M1 on this machine; the Nogat integration check installs from checkouts and does not need pushes |
| The keyword `output_dir` changes meaning (store root to plain directory) | a call left on the old meaning writes plain files into a store | no call of Archiwista writes today; M4 and the recorded-kwargs tests of A5, A7, A8 catch a call without `root`; the writer refuses a plain write into a marked store (`output_in_store`) |
| `0.8.0.dev0` is outside `>=0.8.0,<0.9` | Kartograf reported `incompatible`, nothing starts | range `>=0.8.0.dev0,<0.9` in M1 and its contract test; the release pull request restores the bound (D3) |
| Existing stores have no marker | every configured store is unavailable at the first start after M2 | the message names `kartograf store init --root <path>`; the author marks the real stores first (D9); `init_store` verifies the layout and may refuse a store with strays (`invalid_layout`, the list is in `details.problems`), which the author moves |
| The two producers differ in calling convention, envelope, plan document, progress hook and cancel | an action layer shaped by Kartograf alone | producer-neutral types in A1; Kartograf's documents are converted inside `adapter/kartograf`; the stand-in adapter has the IMGW shape of `options["root"]` in its tests |
| Open Kartograf items (KC-1 to KC-3, KD-3, KD-4, KA-4, KB-7, KH-1) | v0.3 ships with partial features: no bytes, no sizes, no name search, no "change store" | each step names its interim; none is a workaround of the producer's job; the requests are filed |
| The marker judgement is a copy of producer knowledge (also in Retman) | drift when a producer changes its marker | the contract tests against `kartograf.testing`, `imgwtools.testing` and `init_store`; the request for `store_state` |
| Index schema numbers collide between I and A | a rebuild loop or a lost step | each step takes the next free `SCHEMA_VERSION` in merge order; the index is rebuilt, `state.sqlite` is never touched |
| Gate cost: about 25 minutes per commit, about 48 commits (M 6, I 14, A 28) | about 20 hours of gate runs, each alone on the machine | one commit per step where possible; scoped tests while working; the full gate only at the commit; steps of I and A run in parallel on separate machines or sessions |
| Messages and the SPEC move under the steps (message catalog step 2, the translation) | conflicts and stale line numbers | M2 and M3 start after the catalog commit; the translation of the SPEC starts after M3; line numbers are those of `2b167c3` and the steps name symbols |
| The approval is delegated (DEV-17.4 asks for the author's) | a plan amended later | steps not yet started follow the amendment; the line stays "delegated" until the author confirms |
| `archiwista[imgw]` pulls `pyarrow` into the lock and the gate (`--all-extras`) | a heavier environment and lock | one lock for both configurations (A-ADR-024); the CI configuration without the extra proves the optional path |

## Decisions for the author

Each has a recommendation; the plan assumes it until the author says otherwise.

- **D1. Unmarked store.** Strict, as DEV-19.13 and ADR-054 leave it to the consumer: a
  directory with the layout and no marker is unavailable until `kartograf store init`.
  The other choice is to index it with a warning.
- **D2. Writing the marker.** Archiwista shows the command and never runs it. The other
  choice is an action "Utwórz znacznik" through `kartograf.init_store` in a job, with
  `store.write`, in the plan window.
- **D3. Version range.** `>=0.8.0.dev0,<0.9` until the tag, back to `>=0.8.0` in the
  release pull request (REL-5.3).
- **D4. Where the IMGW read side ships.** It is built in parallel, in its own branch, and
  ships with 0.5.0 (hidden without `archiwista[imgw]`). SPEC 13 allows the read-only
  part earlier; the author may take it into 0.3.0.
- **D5. Kartograf's metadata cache.** Archiwista's own, as SPEC 5.6 says; the other choice
  is Kartograf's default `<cache_dir>/kartograf`, shared with the user's command line.
- **D6. Store of a new project in the API.** One member `root` for both producers (it is
  `root` of Kartograf and `store_dir` of IMGWTools underneath).
- **D7. The default root in the wizard.** A suggestion read through Kartograf's
  `get_config()`, never written. It touches the open question about `nogat.toml`
  (PROGRESS): Archiwista itself still reads and writes only its `config.toml`.
- **D8. This plan.** Confirm or amend it; the approval line is delegated until then.
- **D9. Marking the real stores.** Before the first start on the new pin the author runs
  `kartograf store init --root <path>` for each real store, among them the live-test
  store and the large stores of the `perf` and `smb` runs, and moves what `init` refuses.
- **D10. Live tests.** The author runs the `live` tests of A14 on the author's network and
  stores; agents do not.
- **D11. Order when one session is available.** M, then A, then I: v0.3 is the next
  release and the IMGW source is an optional extra.

## Not in this plan

v0.4 "Team" (no producer needs; it follows A); the IMGW actions and the stations views
(v0.5, a plan of its own after A8, I7 and the mockup answers); the PL + CZ surface (KF,
v0.6); the QGIS set, the assistant and the mosaic (v1.1 to v1.3); the translation of the
documents, the first CI run and the tags (PROGRESS Next 1.2, 3 and 4).

## Results

Read on 2026-10-25; nothing was built or run beyond one version-range check with
`packaging`.

Heads: Archiwista `chore/nogat-2.1` `2b167c3` (the message catalog is one commit on
`wip/message-catalog`, `3cae3f9`); Kartograf `feature/data-output` `7394e8ea` with
uncommitted changes (plain mode of the tracks, the `output_dir`/`root` group, documents);
IMGWTools `feature/data-output` `a304521` (done on the branch, a smoke run on the real
servers is open); Nogat `feature/data-output` `68d44f3`.

Facts found that the first drafts of the call-site lists did not have:

- `kartograf.__version__` is `0.8.0.dev0` on `chore/nogat-2.1` and `feature/data-output`
  (the pin reports `0.8.0`), and `>=0.8.0,<0.9` rejects it.
- `StoreManifest.output_dir` of the fixtures is the parent of the store, and `.root` is
  the store; a rename to `root` would clash.
- The SPEC line numbers of PROGRESS Next 2 (KA-1 3659, KB-5 3684, KH-1 3717) do not match
  `2b167c3` (3683, 3708, 3741), and `POST /projects` is at 3131, not 3118; the list of M3
  is of `2b167c3`.
- Kartograf's read API does not require the marker and offers no function that tells a
  marked, an unmarked and a foreign directory apart; IMGWTools' `store_info` reports an
  empty root as unsupported, and gives its problems as text only.
- `kartograf.testing` and `imgwtools.testing` exist and build stores with the marker; the
  IMGWTools one covers `relabeled` versions, an outdated series, stations without a
  position, a corrupt sidecar, an unknown schema and the ČHMÚ provider.
- Kartograf's `run_command` and `check_command` return the envelope `kartograf-result/1`,
  and `init_project` without `root` writes the default root into the manifest.
