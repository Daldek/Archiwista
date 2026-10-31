# Plan: projects in Archiwista's own file (`archiwista-project/1`), phases P2 to P6

Approved: 2026-10-31 (the author approved the parent plan, Nogat
`docs/plans/2026-10-31-archiwista-projects.md`, its option B and the recommended answer of
D1 to D7, recorded as ECO-054; this plan is that plan's step 5, phases P2 to P6, as
[A-ADR-049](../decisions/0049-projects-in-archiwista.md) decides them)

Requirements: A-ADR-049 (every decision); SPEC 2, 4.1, 4.3, 4.6, 4.7, 5.3, 5.6, 6.5 g and h,
8.4, 9.2, 10.1, 10.2, 12.2 (KB-6), 12.7 (IMGW-21) and 13 "Projects"; SCOPE stage 6; PRD
F8 and F11.5; ECO-054, HUB-5.2, REL-5.3, DEV-17.4. Branch `feature/archiwista-projects`
(from `feature/v0.4-team`). P1 (A-ADR-049, the SPEC, SCOPE and PRD edits, this plan) is done.

## Goal

A project is Archiwista's own: a directory with `archiwista-project.json`, written only by
Archiwista under its lock, holding a name, a description, an area, the store of each producer
and groups of pinned versions. Data the store holds is pinned offline in one step; data the
plan window downloads is pinned by that download; the jobs verify, check, re-pin and restore
the pins; the card shows the area, the groups, the pins with their state, the actions and the
activity; exports write `pliki.txt` and `ATRYBUCJE.txt`. Kartograf and IMGWTools keep no
projects. The acceptance is SPEC 13 "Projects", criteria 1 to 9.

## How to read this plan

Each phase section is complete for an agent that has read `CLAUDE.md` and A-ADR-049: it
names where the code is today (read at `0509143`), what to add, change and remove, the
shapes and routes, the tests, the acceptance and what must not break. The ADR's decision
numbers are cited as "D-n" (A-ADR-049 decision n).

## Options

| Option | Verdict |
|---|---|
| A. Five phases in the order of the parent plan: the file (P2), pinning (P3), the jobs with the producers' new function and the re-pin (P4), the card (P5), the exports (P6) | Chosen: P2 and P3 need no producer change and can land before Kartograf's and IMGWTools' commits are pushed; P4 is the only phase that re-pins them |
| B. One phase | Rejected: six to eight sessions of work; nothing reviewable in between |
| C. The jobs before pinning | Rejected: the jobs work on pins, and only P3 makes them |

## Decision

Option A, with these rules for every phase:

1. **Order and branch.** P2, P3, P4, P5, P6 on `feature/archiwista-projects`, one to three
   commits each; P6 may come before P5 (it needs P2's package and P3's pins only). Nothing
   is merged, tagged or released (DEV-3.3); a finished phase may be pushed.
2. **Gate.** Before each commit the reduced gate of the author's decision of 2026-10-25
   (`uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy src tests`,
   `scripts/check-commits.sh`) with the phase's own tests; `scripts/gate.sh` once at the end
   of each phase, before it is pushed. A change of `src/archiwista/web/` runs `tests/e2e` of
   the views it touches.
3. **No aliases** (ECO-020, D4): a removed route, command, field or table goes in the commit
   that replaces it; nothing reads `kartograf-project.json` or `imgw-project.json`, and
   nothing mentions them to people.
4. **Producer pins.** P2 and P3 keep Kartograf `745e8b18…` and IMGWTools `6bd35a49…`
   (`pyproject.toml`); P4 re-pins both to the commits that removed their projects and added
   `command_for_file` (KB-6) and `command_for_version` (IMGW-21), once those are pushed.
5. **Documents.** Each phase updates what it makes untrue in the same commit: SPEC (where
   the built behaviour differs from 4.7, 9.2 or 13; the ADR gets an erratum then), USAGE,
   AGENT_API, README (its CLI table is a contract test: `tests/contract/test_readme_examples.py`),
   ARCHITECTURE, CHANGELOG (**Breaking** for a removed route or command); PROGRESS before
   the last commit of a session. USAGE and AGENT_API carry a "Changing (A-ADR-049)" note
   at their project sections until P5 rewrites them.
6. **Texts.** Every text for people in `src/archiwista/messages/` and `web/src/labels/`
   (English and Polish); the Polish labels below are the interface's.

## Phases

| Phase | Title | Commits | Needs |
|---|---|---|---|
| P2 | The project file, its discovery and its index | 3 | — |
| P3 | Pinning: what the store holds, and the plan window | 3 | P2 |
| P4 | The jobs, the command of a version, the producers re-pinned | 2 | P3; the producers' commits pushed |
| P5 | The project card, its activity, the guide | 2 | P4 |
| P6 | Exports | 1 | P3 |

### P2. The project file, its discovery and its index (three commits)

**Starts from.** Discovery: `index/projects.py` (`PROJECT_MANIFESTS`, `MAX_PROJECT_DEPTH = 4`,
`scan_projects(adapter, writer, *, project_dirs, stores)`, `record_project(adapter, writer,
directory, *, stores)`, `_discover`, `_contained`, `_read` through
`SourceAdapter.project_status`/`read_project`, `_match_store`, `_same_directory`, `_inside`),
called by `index/scanner.py` after a full scan of a store (`projects = scan_projects(adapter,
…)`) and by `services/projects.py` `_record`. Index (`index/schema.py`, `SCHEMA_VERSION = 14`):
`projects (id, key, path, access_key, name)`, `manifests`, `project_tasks`, `pins (id,
project_id, producer, task_id, store_id, store_dir, version_path, sha256)`; `versions` has no
`content_sha256` (IMGW's is in `version_sidecars.raw`); `IndexWriter.write_project`,
`project_stamps`, `remove_projects`; `IndexQueries.projects`, `project`, `unused_versions`,
the pins of a slot (`PinRef`, `_PIN_STATE`, `_PINNED`, `_PINNED_VISIBLE`); `index/types.py`
`ProjectRef`, `ProjectRecord`, `ProjectManifestRef`, `ProjectTaskRef`, `ProjectPinRef`,
`PinRef`, `ManifestStamp`. Source interface: `SourceAdapter.read_project`, `project_status`,
`sources/types.py` `ProjectInfo`, `ProjectTask`, `ProjectPin`; the adapters'
`read_project`, `project_status`, `_project_info`; `SCHEMAS` of `adapter/kartograf/__init__.py`
(`kartograf-project/1`) and `adapter/imgw/__init__.py` (`imgw-project/1`); the test plugins
`tests/fixtures/action_source/standin_source_plugin.py` and
`tests/fixtures/second_source/external_source_plugin.py` implement both reads. Services:
`services/projects.py` (`ProjectDetail`, `project_detail`, `project_problems`,
`project_status`, `project_manifest`, `create_project`, `add_project_task`,
`remove_project_task`, `project_actions`, `project_directory`, `project_store`,
`_project_place`, `_require_discoverable`, `_require_inside`, `_is_project`,
`_stays_inside`), `services/project_jobs.py`. Jobs: `jobs/protocol.py` (`PROTOCOL_VERSION =
11`, `PROJECT_KINDS`), `jobs/supervisor.py` (`JOB_RULES` of the four kinds,
`_PROJECT_CONFLICT`, `_project_key`), `jobs/worker.py` (`run_project_download`,
`run_project_repin`, `run_project_check`, `run_project_verify`, `_project_download`, which
use `project_manifest`), `services/jobs.py` (retry through `project_jobs.require`). API:
`api/projects.py` (`router`, `job_router`: `GET`/`POST /projects`, `GET
/projects/{project}`, `/status`, `POST`/`DELETE …/tasks`, `POST …/jobs`); `api/models.py`
(`Pin`, `ProjectManifest`, `ProjectItem`, `ProjectList`, `ProjectTask`, `ProjectPin`,
`ProjectCard`, `TaskStatus`, `ManifestStatus`, `ProjectStatus`, `ProjectRequest`,
`TaskRequest`, `ProjectJobRequest`, `Issue.task`, `StoreDetail.projects`). CLI:
`commands/projects.py` (`project-init`, `project-add`, `project-remove`, `project-status`),
`commands/project_jobs.py`, `reader.py` `project_text`. Messages: `messages/project.py`,
`problem.py` (`invalid_manifest`, `duplicate_task`, `unknown_store`, `missing_pin`,
`pin_sha256_mismatch`), `cli.py` (`project_*_help`), `log.py`, `job.py` (`kind_project_*`,
`task_*`), `fix.py` (`project_locked`). State: `state/store.py` `ActionName`
(`project.task_add`, `project.task_remove`). Web: `views/projects.js` (list, `NewProject`,
`ProjectCard` with tasks, "+ Zadanie", "Usuń", "Pobierz", "Przepnij", the producer selector),
`views/plan.js` (`TaskChoice`, `taskOffer`), `views/file.js` (`Pins`: "Przypięta w: {project}
({task})"), `views/cards.js` (`projectSummary`, `pinStateName`), `views/jobs.js`,
`downloads.js`, `labels/projects.js`, `labels/actions.js` (`task*`), `labels/file.js`,
`labels/log.js`, `labels/common.js`, `api.js`, `types.js`. Fixtures: `tests/fixtures/make_store.py`
writes `kartograf-project.json` with `kartograf.init_project`/`add_project_task`
(`MANIFEST_NAME`, `ExpectedProject`, `ExpectedTask`, `ExpectedPin`, cases
`missing_version`, `other_store`, `invalid_manifest`) and `verify_store` checks them with
`open_project`; `tests/fixtures/team_projects.py` (`MANIFEST`).

- *Commit 1, the file* (new package `src/archiwista/projects/`, D-1 to D-4):
  - `projects/document.py`: `PROJECT_FILE = "archiwista-project.json"`, `PROJECT_SCHEMA =
    "archiwista-project/1"`, `LOCK_NAME = ".archiwista-project.lock"`, `AREAS_DIR =
    "obszary"`, `EXPORTS_DIR = "zestawy"`, `MAX_GROUP_PINS = 10_000`,
    `MAX_PROJECT_FILE_BYTES = 32 * 1024**2`; frozen dataclasses `ProjectDocument(name,
    description, created_at, created_by, area: AreaRef | None, stores: tuple[StoreRoot, ...],
    groups: tuple[PinGroup, ...])`, `AreaRef(path, sha256)`, `StoreRoot(producer, root)`,
    `PinGroup(name, origin: PlanOrigin | LocalOrigin, pins: tuple[Pin, ...])`,
    `PlanOrigin(producer, calls: tuple[CommandCall, ...])` (`sources.CommandCall`),
    `LocalOrigin(selections: tuple[Selection, ...])`, `Selection(source: Literal["local_state",
    "catalog", "file"], query: Mapping[str, object] | None)` (JSON member `from`), `Pin(producer,
    version, sha256, content_sha256, size_bytes, unit, label, pinned_at, pinned_by)`;
    `parse_document(data) -> ProjectDocument` checking every rule of D-1 and raising
    `ProjectFileError(reason, pointer, rule)` (reasons `invalid_member`, `unsupported_schema`
    for `archiwista-project/<n>` with `n` > 1); unknown members ignored.
  - `projects/files.py`: `read_project_file(directory) -> ProjectDocument` (reasons
    `unreadable`, `too_large`, `invalid_json` besides the parser's); `project_lock(directory, *,
    wait_s=5.0)` (a context manager: `os.mkdir` of the lock, `owner` written inside with
    `sandbox.process_owner()` and the UTC time, polling every 0.1 s, then `ProjectLockedError`
    with `details.lock`, `details.owner` and whether `sandbox.owner_alive` says it ended; its
    own lock removed in `finally`, never another's); `change_project_file(directory, change,
    *, create=None) -> ProjectDocument` (under the lock: read the raw JSON object, refuse an
    invalid or newer file with `ProjectFileError` (`409`, `invalid_project_file`,
    `unsupported_project_schema`), apply `change(raw)` to the dict, validate the result,
    write `.archiwista-project.json.<owner>_<token>.tmp`, `fsync`, `os.replace`, `fsync` the
    directory on POSIX; `create=` writes a new file and refuses an existing one with
    `project_exists`); `write_area_file(directory, area: AreaRecord) -> AreaRef` (D-4: a
    `FeatureCollection` of one feature, properties `name`, `source`, `area_km2`,
    `countries`; `obszary/<area id>.geojson` through a temporary name and `os.replace`; an
    identical file kept); `read_project_area(directory, ref) -> GeoJSONGeometry` (at most
    `areas.AREA_BODY_LIMIT_BYTES`, JSON only, its SHA-256 compared with `ref.sha256`; raises
    with the state `missing`, `changed` or `invalid`).
  - `errors.py`: `ProjectLockedError` now names Archiwista's lock (`details.lock`,
    `details.owner`; hint `fix.project_locked`); `ProjectFileError` (`conflict`; reasons
    `invalid_project_file`, `unsupported_project_schema`, `project_exists`) and
    `ProjectFileWriteError` (`io_error`, `project_file_write_failed`). `messages/project.py`
    and `messages/fix.py`: their texts.
  - *Tests:* `tests/unit/test_project_document.py` (each rule of D-1 with its JSON pointer;
    names NFC and compared case-folded; a pin twice in a group; a plan pin of another
    producer; `archiwista-project/2`; unknown members kept by a change);
    `tests/unit/test_project_files.py` (a held lock: a second writer waits and is refused
    with the owner; a lock of an ended process of this computer is named and kept; a failure
    in `os.replace` leaves the old file whole and no temporary file; a read-only directory is
    `project_file_write_failed`; two processes each adding 20 groups lose none).
- *Commit 2, the cutover of discovery, index, services, API and CLI:*
  - `index/projects.py`: `scan_projects(writer, *, project_dirs, stores, geo)` and
    `record_project(writer, directory, *, stores, geo)` read `PROJECT_FILE` with
    `read_project_file` (the rules of `_discover` unchanged, the stamp `(mtime_ns, size)`); an
    invalid or newer file is recorded with its `state` and `problem`; each `StoreRoot`
    (relative ones resolved against the project directory) matched by `_match_store`'s rule;
    the area read with `read_project_area` and `areas.area_from_geometry(geometry,
    adapter=geo, source="file", name=…)` into `areas` (`IndexWriter.write_area`). `geo` is the
    Kartograf adapter as `GeoAdapter`. `index/scanner.py` calls `scan_projects` after a full
    scan without the producer's adapter. `PROJECT_MANIFESTS` goes.
  - `index/schema.py`: `SCHEMA_VERSION = 15`; `versions.content_sha256 TEXT` (written from
    `EntryMeta.content_sha256`); `manifests` and `project_tasks` go; instead:

    ```sql
    CREATE TABLE projects (
        id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, path TEXT NOT NULL UNIQUE,
        access_key TEXT NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL CHECK (state IN ('ok', 'invalid', 'unsupported_schema')),
        problem TEXT, problem_detail TEXT, created_at TEXT, created_by TEXT,
        area_path TEXT, area_sha256 TEXT,
        area_id TEXT REFERENCES areas(id) ON DELETE SET NULL,
        area_state TEXT CHECK (area_state IN ('ok', 'missing', 'changed', 'invalid')),
        file_mtime_ns INTEGER NOT NULL, file_size INTEGER NOT NULL, scanned_at TEXT NOT NULL
    );
    CREATE INDEX projects_access ON projects (access_key);
    CREATE TABLE project_stores (
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        producer TEXT NOT NULL, root TEXT NOT NULL,
        store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
        PRIMARY KEY (project_id, producer)
    ) WITHOUT ROWID;
    CREATE TABLE pin_groups (
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        position INTEGER NOT NULL, name TEXT NOT NULL,
        origin TEXT NOT NULL CHECK (origin IN ('plan', 'local')),
        producer TEXT, calls TEXT, selections TEXT,
        PRIMARY KEY (project_id, position)
    ) WITHOUT ROWID;
    CREATE TABLE pins (
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        group_position INTEGER NOT NULL, producer TEXT NOT NULL,
        store_id INTEGER REFERENCES stores(id) ON DELETE SET NULL,
        version_path TEXT NOT NULL, sha256 TEXT NOT NULL, content_sha256 TEXT,
        size_bytes INTEGER NOT NULL, unit TEXT, label TEXT,
        pinned_at TEXT NOT NULL, pinned_by TEXT NOT NULL
    );
    CREATE INDEX pins_version ON pins (store_id, version_path);
    CREATE INDEX pins_project ON pins (project_id, group_position);
    ```

  - `index/writer.py`, `index/queries.py`, `index/types.py`: `write_project` (key kept as
    today), `project_stamps()`, `remove_projects(keep=…)`; `ProjectRef` (`key`, `path`,
    `access_key`, `name`, `description`, `state`, `problem`, `problem_detail`, `stores`:
    `ProjectStoreRef(producer, root, store)`, `area`: `ProjectAreaRef(path, sha256, state,
    area_id)`, `groups`, `pins`, `missing_pins`, `scanned_at`), `ProjectRecord` with
    `groups: tuple[PinGroupRef, ...]` (`name`, `origin`, `producer`, `calls`, `selections`,
    `pins: tuple[ProjectPinRef, ...]`), `ProjectPinRef` (`producer`, `store`, `version`,
    `sha256`, `content_sha256`, `size_bytes`, `unit`, `label`, `pinned_at`, `pinned_by`,
    `state`, `slot`, `is_current`); `PinRef.group` instead of `task`; `projects(store=)`
    through `project_stores`; the search rows hold project and group names;
    `ProjectManifestRef`, `ProjectTaskRef` go.
  - `sources/`, adapters, test plugins: `SourceAdapter.read_project` and `project_status`,
    `ProjectInfo`, `ProjectTask`, `ProjectPin` and the adapters' project reads go;
    `kartograf-project/1` and `imgw-project/1` leave `SCHEMAS`. `ProjectActionAdapter`, its
    types and `adapter/kartograf/actions.py`'s project functions stay unused until P4
    removes them with the re-pin (they call the producers' current functions).
  - The old project jobs go here, not in P4 as the parent plan lists them: they read
    manifests that are no longer indexed and would not import. `jobs/protocol.py`
    (`PROJECT_KINDS` and the four kinds; `PROTOCOL_VERSION = 12`), `jobs/supervisor.py`
    (their rules; `_PROJECT_CONFLICT` and `_project_key` stay for P4), `jobs/worker.py`
    (their runners), `services/project_jobs.py`, `commands/project_jobs.py`, the retry path
    of `services/jobs.py`, `POST /projects/{project}/jobs`.
  - `services/projects.py`: `project_detail` (groups, pins, problems), `project_problems`
    (`invalid_project_file`, `unsupported_project_schema`, `unknown_store`, `missing_pin`,
    `pin_sha256_mismatch`, `area_missing`, `area_changed`, `area_invalid`),
    `create_project(settings, queries, index_path, authorizer, *, path, name, description,
    area_id, actor) -> str` (the place rules of `_project_place`, `_require_discoverable` and
    `_require_inside` unchanged; D-6: `project.create` for a new directory, `project.write`
    where an access entry exists, `409 project_exists` where the file exists; the directory
    made; the area written; the access entry and `project.create` logged as today; recorded at
    once), `update_project` (`name`, `description`; `project.update`), `set_area` (`area_id`
    or `None`; `project.area`), `set_store` (`project.store`; the root through
    `written_root(store_root, directory, *, relative)`: relative to the project directory when
    the store has path aliases and a relative path exists, else absolute — the rule now in
    `adapter/kartograf/actions.py` for `init_project`, moved here and producer-neutral),
    `project_directory` (kept). `project_status`, `project_manifest`, `add_project_task`,
    `remove_project_task`, `project_actions`, `project_store` go.
  - API (`api/projects.py`, `api/models.py`): `GET /projects` (`?store=`), `POST /projects`
    (`ProjectRequest {path, name?, description?, area_id?}` → `201` card, `Location`), `GET
    /projects/{project}`, `PATCH /projects/{project}` (`ProjectChange {name?, description?}`,
    one at least), `PUT /projects/{project}/area` (`AreaChoice {area_id: str | null}`), `PUT
    /projects/{project}/stores/{producer}` (`StoreChoice {store}`), each answering the card.
    `ProjectItem {project, name, description, state, problem, stores: [{producer, root,
    store}], area: {path, sha256, state, area_id} | null, groups, pins, missing_pins,
    scanned_at, project_write}`; `ProjectCard` = item + `path` (`CopyPath`), `groups: [{name,
    origin: {kind, producer?, calls?, selections?}, pins: [ProjectPin]}]`, `problems`;
    `ProjectPin {producer, store, version, sha256, content_sha256, size_bytes, unit, label,
    pinned_at, pinned_by, state, slot, is_current}`; `Pin.group`, `Issue.group`. `/status`,
    `/tasks` and their models go. Refusals: `404` hidden, `403 permission_denied`, `403
    path_outside_root`, `400 project_not_discoverable`/`project_dir_missing`, `404` unknown
    area or store, `400 store_without_producer`, `409 project_exists`, `409 project_locked`,
    `409 invalid_project_file`/`unsupported_project_schema`, `500 io_error`
    (`project_file_write_failed`); all documented in OpenAPI.
  - CLI (`commands/projects.py`): `archiwista project-init KATALOG [--name NAZWA]
    [--description TEKST] [--area-id OBSZAR]`, `project-edit PROJEKT [--name]
    [--description]`, `project-area PROJEKT (--area-id OBSZAR | --clear)`, `project-store
    PROJEKT PRODUCENT --store MAGAZYN`, each printing the card (`--json`: the route's model);
    `project-add`, `project-remove`, `project-status` and `commands/project_jobs.py` go;
    `reader.py` `project_text` prints groups and pins.
  - `state/store.py` `ActionName`: `project.update`, `project.area`, `project.store` added,
    `project.task_add` and `project.task_remove` removed; `messages/log.py` and
    `web/src/labels/log.js` follow.
  - Fixtures: `tests/fixtures/make_store.py` writes `archiwista-project/1` files through
    `change_project_file(create=…)`: regular projects with a plan group and a local group
    pinning current and older versions, `missing_version`, `other_store` and
    `invalid_project_file` (a member breaking a rule, written by hand); `verify_store` reads
    them with `read_project_file`; `ExpectedProject` gets `groups`;
    `tests/fixtures/team_projects.py` writes Archiwista's file.
  - *Tests:* new `tests/integration/test_project_discovery.py` (the file only; a directory
    holding only `kartograf-project.json` is no project; invalid and newer files listed with
    their problem; a file linked out of the project directory is `path_outside_root`; an
    unchanged file is not read again; a removed file removes the project; the area read into
    `areas`, a changed area file not used); `tests/integration/test_projects_api.py`
    rewritten (create, edit, area and store by API and CLI with equal JSON; every refusal
    above by both; owner, administrator, another person, a hidden project, agent tokens; a
    held lock answers `409 project_locked`; OpenAPI operations); changed:
    `tests/contract/test_store_fixture.py`, `tests/integration/test_projects.py`,
    `test_project_filter_api.py`, `test_team_projects.py`, `test_project_write.py`,
    `test_action_log.py` (the new names), `tests/unit/test_project_visibility.py`,
    `test_source_protocol.py`, `test_isolation.py`, `test_doctor.py` (schemas),
    `tests/contract/test_kartograf.py`, `test_imgw.py`, `test_kartograf_marker.py`,
    `tests/perf/test_index_perf.py`, `tests/perf/test_store_50k.py`; removed:
    `tests/integration/test_imgw_projects.py`, `test_project_changes.py`,
    `test_project_jobs.py`, `test_project_jobs_api.py`, the project cases of
    `test_live_actions.py` and `test_job_controls.py` (P4 writes their successors).
- *Commit 3, the interface:* `views/projects.js` renders the new shapes (the list: name,
  stores, groups, pins, missing, scanned; the card: name, description, directory, stores
  with their match or problem, the area's state, the groups with their origin and pins with
  their state, own data and sharing as before); "Nowy projekt…" asks path, name and
  description; "+ Zadanie", "Usuń", "Pobierz", "Przepnij" and the producer selector go;
  `views/plan.js` loses "Dodaj jako zadanie projektu" (P3 brings "Dodaj do projektu");
  `views/file.js` shows "Przypięta w: {project} ({group})"; `api.js` (`createProject`,
  `updateProject`, `setProjectArea`, `setProjectStore`; the task, status and job calls go),
  `types.js`, `labels/projects.js`, `labels/actions.js`, `labels/file.js`,
  `labels/common.js`. *Tests:* `tests/e2e/test_project_actions.py` becomes
  `tests/e2e/test_projects_view.py` (a project created in the form appears with its file on
  the disk; a fixture project shows its groups and pin states; a person who may change
  nothing sees "Nowy projekt…" only); `test_file_projects_store.py`, `test_plan_window.py`,
  `test_pasted_command.py`, `test_acceptance_v03.py` (its UC-06 part goes until P5),
  `test_sharing.py` and `test_jobs_view.py` follow.
- *Documents:* SPEC 9.2 and 4.7 where the build differs; USAGE (creating and editing a
  project; the note stays), AGENT_API, README (CLI table), ARCHITECTURE (`projects/`, the
  index tables), CHANGELOG (**Breaking**: producer manifests no longer read; the task, status
  and job routes and commands removed), PROGRESS. `CLAUDE.md`'s rule of user data in the
  project folder names the project file.
- *Acceptance:* SPEC 13 "Projects" criteria 1 and 2; the store fixture's projects listed with
  their groups and pin states; `archiwista reindex` reads them back; no module outside
  `adapter/kartograf/actions.py` names a producer's project function.
- *Must not break:* own data (`dane/`, scans, snapshots, `PUT …/data-dir`), sharing (`GET`/`PUT
  …/access`), `GET /slots?project=`, `GET /map/footprints?project=`, `POST /previews/warm`
  with `project`, "Przypięta w:", the report of unused versions, the search of project names,
  the visibility matrix (A-ADR-029), the action log's completeness test, state export and
  import, `archiwista doctor`.

### P3. Pinning: what the store holds, and the plan window (three commits)

**Starts from** P2, and: `api/slots.py` `list_slots` with `CatalogFilters` (`api/models.py`)
over `IndexQueries` paging; `jobs/worker.py` `run_download` (its summary: `producer`,
`store`, `root`, `plan_job`, `status`, `files[]` of `ActionFile` with `call`, `calls[]`,
`taken`), `_kept_plans`, `_rescan`; `services/actions.py` `start` and
`api/models_actions.py` `JobRequest`; `jobs/supervisor.py` `action_details`, the download's
parameter check; web `map/coverage.js` (`LocalState`, `CoverageItem`), `views/catalog.js`,
`views/file.js`, `views/plan.js`, `downloads.js`.

- *Commit 1, local pins (D-7, D-8):* `services/pins.py` (new): `pin_local(settings, queries,
  index_path, authorizer, key, *, group, new, source, versions, query, actor, visible) ->
  PinOutcome` resolves the versions (explicit `{store, version}`, or the `CatalogFilters` of
  `query` through every page, at most `MAX_GROUP_PINS + 1` rows: more is `400
  too_many_pins` with `details.count` before anything is written), takes `producer`,
  `sha256`, `content_sha256`, `size_bytes`, `unit` and `label` from the index (new
  `IndexQueries.version_facts(store, paths)`), skips `missing` and `no_sha256` versions and
  counts `already` pinned ones, applies D-7 (`409 other_store`, `409 unknown_store`; the
  first pin of a producer adds its store with `written_root`), refuses pins into a plan group
  (`409 group_origin_plan`), writes with `change_project_file` (a new group, or pins and a
  selection appended to a local one; a taken name `409 group_exists`; a name breaking D-1
  `400 invalid_group_name`), records the project and logs `project.pin` (`{group, from,
  pins, skipped}`); `unpin(…, group, pins | None)` removes pins or the group and logs
  `project.unpin`. Routes: `POST /projects/{project}/groups` (`GroupRequest {name, from,
  versions?: [{store, version}], query?: {…CatalogFilters}}`, exactly one of `versions` and
  `query` → `201 PinOutcome {project: ProjectCard, group, pinned, already, skipped: [{store,
  version, reason}]}`), `POST /projects/{project}/groups/{group}/pins` (the same without
  `name` → `200`), `POST /projects/{project}/groups/{group}/unpin` (`{pins: [{producer,
  version}]}` → `200` card), `DELETE /projects/{project}/groups/{group}` (`200` card); `404`
  for an unknown group. CLI: `archiwista project-pin PROJEKT GRUPA (--version MAGAZYN:WERSJA
  … | --query JSON) [--from local_state|catalog|file] [--add]` (`--add`: into an existing
  local group), `project-unpin PROJEKT GRUPA [--pin PRODUCENT:WERSJA …]`. `ActionName`:
  `project.pin`, `project.unpin`. *Tests:* `tests/integration/test_project_pins.py` (a query
  pins exactly the Catalog's rows, `versions=all` every version; an older version pinned
  explicitly; skipped and already-pinned versions; `too_many_pins` with the constant patched
  to 3 and the file unchanged; `other_store`, `unknown_store`, `group_origin_plan`; unpin of
  pins and of a group; permissions and agent tokens; API equals CLI; no socket opened
  (`tests/fixtures/network.py`); the log's entries; "Przypięta w:" and `GET /slots?project=`
  show the pins).
- *Commit 2, pins of the plan window (D-9):* `JobRequest.pin: {project, group} | None` (a
  `download` only); `services/actions.py` `start` with `pin`: the project visible (`404`) and
  writable (`403`), the name valid and free (`409 group_exists`), the store as D-7 says; the
  job's `params.pin`; `services/jobs.py` retry asks the same; the supervisor checks `pin` in
  the parameters, `action_details` adds `project` and `group` from it, and `GET
  /jobs?project=` matches it. `run_download`: when `pin` is set and the job ends `ok` (no
  failed unit, nothing taken), after the rescan it builds the pins from `files[]` (their
  `version_path`, `sha256`, `size_bytes`, `label`, `unit`; `content_sha256` from the index)
  and, for each call with a kept plan, every position not in `files[]` from the version the
  index holds at its standard path (new `IndexQueries.current_version_at(store, path)`; none:
  `not_pinned` with `not_in_store`), writes the group (origin `plan`, the job's producer and
  calls) with `change_project_file`, records the project, and adds `pin: {project, group,
  pins, not_pinned}` to the summary; a write that fails adds `pin: {error}` and ends the job
  `partial`; a job that is not `ok` pins nothing and says so in `pin`. CLI: `archiwista jobs
  start download … --pin PROJEKT --pin-group GRUPA`. Web `views/plan.js`: "Dodaj do
  projektu" (a checkbox, "Projekt" from `GET /projects` with `project_write`, "Grupa"
  prefilled from the window's title), the submit "Pobierz N pozycji i przypnij" or "Przypnij
  N pozycji" when nothing is to be downloaded; disabled with its reason without a project the
  session may change, offline or without a plan, and without `store_write`; `downloads.js`
  and the top bar show the pin's outcome. *Tests:* `tests/integration/test_download_pin.py`
  (real workers, `tests/fixtures/action_worker.py` and the stand-in: a planned download pins
  every file and every `current` position; a `partial` one pins nothing; `group_exists`
  before a job; `other_store`; a retry asks `project.write`; the log names the project);
  `tests/e2e/test_plan_window.py` (the option, its group in the card, its disabled reasons).
- *Commit 3, "Dodaj do projektu…" in the views:* `views/pin-dialog.js` (new: "Projekt",
  "Nowa grupa" with its name or a local group of the project, the count; the outcome with
  pinned, already and skipped and a link to the project); `map/coverage.js` `CoverageItem`
  (`from: "local_state"`, `query`: the map's filters with `area_id`, `store`, `product`,
  `versions: "current"`); `views/catalog.js` (the result's header, `from: "catalog"`,
  disabled above `MAX_GROUP_PINS` rows with the reason); `views/file.js` (the version chosen
  on the timeline, `from: "file"`); the card's "Odepnij" at a pin and "Usuń grupę" (each
  after a question); `labels/pins.js` (new). *Tests:* `tests/e2e/test_pinning.py` (Chromium,
  the dialog in Firefox too: pins from "Stan lokalny" of an area, from the Catalog with
  filters, an older version from the file card; unpin; disabled for a person who may change
  no project; no request leaves the server).
- *Documents:* SPEC 9.2 if it differs; USAGE (pinning, the plan window's option), AGENT_API
  (the group routes, `pin` of `POST /jobs`, the commands), README, CHANGELOG, PROGRESS.
- *Acceptance:* SPEC 13 "Projects" criteria 3 and 4.
- *Must not break:* downloads without `pin` (ADR-044, the claims of ADR-047), the Catalog and
  its filters, the file card's other actions, P2's routes.

### P4. The jobs, the command of a version, the producers re-pinned (two commits)

**Starts from** P3, and the producers' pushed commits (the Nogat plan's Results table names
them): Kartograf without `kartograf.project`, `PROJECT_LOCK` and the `project` commands, with
`kartograf.command_for_file(sidecar) -> kartograf.CommandCall`; IMGWTools without
`imgwtools.project` and `imgw-project/1`, with `imgwtools.command_for_version(version, *,
root=None) -> CommandCall`; both refuse with their error class, `code` `unsupported` and
`details["reason"]` `command_not_rebuildable`. Archiwista still has `ProjectActionAdapter`,
`ProjectRun`, `ProjectTaskRun`, `PinnedVersion`, `ProjectCheck`, `ProjectFileState`,
`TASK_OUTCOMES`, `PROJECT_FILE_STATUSES` (`sources/`), the project functions of
`adapter/kartograf/actions.py` (`init_project` use, `add_task`, `remove_project_task`,
`project_download`, `project_check`, `project_verify`, `_project_error`, `_project_check`,
`_locked`, the `PROJECT_LOCK` import, `_PROJECT_*`) and
`tests/contract/test_kartograf_project_jobs.py`.

- *Commit 1, the re-pin and the capability (D-10):* `pyproject.toml` and `uv.lock` pin the
  pushed commits (REL-5.3; `SUPPORTED_VERSIONS` as their version requires, REL-5.6);
  everything listed above goes; `sources/protocol.py` gains `VersionCommandAdapter`
  (`command_for_version(self, version: str, *, root: Path) -> CommandCall`, offline,
  read-only; the coded refusal as `UnsupportedError` reason `command_not_rebuildable` with
  the producer's text, any other as `ProducerError`) and `ActionAdapter.run(…, upgrade:
  bool = False)`; the Kartograf adapter implements both (`kartograf.read_sidecar` of the
  version's sidecar into `command_for_file`, the call converted as `parse` converts one;
  `upgrade` → `update="upgrade"` without a plan), the IMGW adapter `command_for_version`;
  the stand-in source both (a deterministic call per file, a refusal for one marked family).
  `index/schema.py`: `version_calls (store_id INTEGER NOT NULL REFERENCES stores(id) ON
  DELETE CASCADE, version_path TEXT NOT NULL, producer_version TEXT NOT NULL, call TEXT,
  refusal TEXT, PRIMARY KEY (store_id, version_path)) WITHOUT ROWID`, `SCHEMA_VERSION = 16`;
  `IndexWriter.write_version_calls`, `IndexQueries.version_calls(store, paths,
  producer_version)`. `services/commands.py` `version_command(…)` over the cache; `GET
  /stores/{store}/versions/{version}/command` (`VersionCommand {producer, command, options,
  line}`; `422 command_not_rebuildable` or `no_commands`), `archiwista version-command
  MAGAZYN WERSJA`; P3's local pin service fills the cache for the pins it adds; the card's
  pins carry `command: "rebuildable" | "not_rebuildable" | "unknown"` and `command_refusal`.
  *Tests:* `tests/contract/test_kartograf_command_for_version.py` (a sheet version's call
  formats and parses back to itself; a `soil hsg` version is refused with Kartograf's text;
  `kartograf.testing` stores), `tests/contract/test_imgw.py` (an archive version's call; a
  refusal), `tests/integration/test_version_command.py` (route equals command; the cache
  filled once; `no_commands`).
- *Commit 2, the jobs (D-11, D-12):* `jobs/protocol.py` `JobKind` and `PROJECT_KINDS`
  (`project_verify`, `project_check`, `project_repin`, `project_restore`),
  `PROTOCOL_VERSION = 13`; `jobs/supervisor.py` rules (all four with `conflict=
  _PROJECT_CONFLICT`; check, repin and restore `network=True`), the parameters `project` and
  `groups` (names or `None`; a repin exactly one), `action_details` with the groups;
  `jobs/project_jobs.py` (new, imported lazily as ADR-044 C requires) with the four runners
  and their helpers: the project's file and index record, the chosen groups, a producer's
  store, a group's calls (plan: the origin's; local: each pin's from `version_calls` or the
  adapter, written back), SHA-256 of a version file in 1 MiB chunks inside its store root,
  the rescans as `run_download` does; results: verify `{groups, counts, pins: [{group,
  producer, version, status, found}]}`, check `{groups, counts, pins: [{group, producer,
  version, unit, path, status, pinned_label, available_label, detail}], added: [{group, unit,
  path, available_label}]}`, repin `{group, status: "replaced" | "unchanged", calls, files,
  pins: {kept, new, dropped}}`, restore `{groups, counts, pins: [{group, producer, version,
  status, detail}], calls}`; end states as D-11 (`PartialResult`, `CheckFailedError`,
  `RunFailedError`). `services/project_jobs.py` (new content): `start` refuses before a job a
  hidden project (`404`), a re-pin or restore without `project.write` and `store.write`
  (`403`), an unknown group (`404`), a re-pin of not exactly one group (`400`), a group whose
  producer has no `ActionAdapter` (`422 no_commands`), a re-pin of a local group with a pin
  known `not_rebuildable` (`422 command_not_rebuildable`), a store not configured (`409
  unknown_store`); `require` for a retry. `POST /projects/{project}/jobs`
  (`ProjectJobRequest {kind: "verify" | "check" | "repin" | "restore", groups?}`, `job_router`,
  `202`, `Location`); `commands/project_jobs.py` (new content: `project-verify PROJEKT
  [GRUPA …]`, `project-check …`, `project-repin PROJEKT GRUPA`, `project-restore PROJEKT
  [GRUPA …]`, in the foreground, exit 0, 10, 11 or 130). *Tests:*
  `tests/integration/test_project_jobs.py` (new content, real workers: verify finds `ok`,
  `missing`, `corrupt`, `content_match` and `no_store`; check on the stand-in's plans reports
  `current`, `newer`, `removed`, `added` and `not_checkable`; a whole re-pin replaces the pins
  and keeps the `pinned_at` of unchanged ones, a partial run changes nothing; restore gives
  `restored`, `content_match`, `not_restored` and `not_restorable` and never writes the file;
  one job per project; offline refusals; the permission matrix; API equals CLI; a retry asks
  again), `tests/integration/test_job_controls.py` (a project job's cancel and retry),
  `tests/integration/test_live_actions.py` (live: v0.3 criterion 2 through
  `project_verify`; a group pinned from a download names the CLI's versions).
- *Documents:* SPEC 5.6 and 9.2 if they differ; USAGE (the jobs from the command line),
  AGENT_API, README, ARCHITECTURE (the source interface), CHANGELOG (**Breaking**: the
  producers re-pinned; `kartograf-project/1` and `imgw-project/1` gone), PROGRESS.
- *Acceptance:* SPEC 13 "Projects" criteria 5 and 6 through API and CLI; no
  `kartograf-project`, `imgw-project`, `ProjectActionAdapter`, `download_project`,
  `check_project`, `verify_project` or `PROJECT_LOCK` left in `src/` and `tests/`.
- *Must not break:* downloads and checks (ADR-044, ADR-047), availability, the IMGW read side,
  the doctor's producer checks, the contract tests of the producers' read APIs.

### P5. The project card, its activity, the guide (two commits)

**Starts from** P4, and: `views/projects.js`, `views/cards.js` (`useJob`, `projectSummary`),
`map/own.js` (`PROJECT_PARAM`; the project's map with own data and the pinned versions of
`GET /map/footprints?project=`), `map/panel.js` (the area's badge), `views/log.js`,
`state/schema.py` (`STATE_SCHEMA_VERSION` 3; `action_log` indexed by `at`, `actor` and
`action`), `state/store.py`, `web/guide/index.html` slide "Projekty" with
`web/guide/08-projekt.webp` (taken by the interface tests with `ARCHIWISTA_SCREENSHOTS`).

- *Commit 1, the activity (D-14):* `state/schema.py` migration `_version_4`: `CREATE INDEX
  action_log_target ON action_log (target, at)` and `CREATE INDEX action_log_project ON
  action_log (json_extract(details, '$.project'), at)` (`STATE_SCHEMA_VERSION` 4);
  `StateStore.project_activity(access_key, key, *, before, limit)`: `project.*` entries with
  the project's access key as target, `job.start`, `job.retry` and `job.cancel` with
  `details.project` the key, outcome `ok` or `failed`, newest first; `GET
  /projects/{project}/activity` (`limit` ≤ 100, `cursor`) → `ProjectActivity {items: [{id,
  at, actor, actor_name, actor_kind, action, outcome, details}], next_cursor}`, without the
  client and the session; `archiwista project-activity PROJEKT [--limit N] [--cursor ID]`.
  *Tests:* `tests/integration/test_project_activity.py` (creation, pins, unpins, a job start;
  another project's entries never; a hidden project `404`; no address; paging),
  `tests/unit/test_state_migrations.py` (version 4 from 3).
- *Commit 2, the card (SPEC 6.5 g):* the header ("Zmień…" for the name and description,
  "Udostępnij…"); the area ("Pokaż na mapie" → `?view=map&area=<area_id>`, its state, "Usuń
  obszar"; "Ustaw jako obszar projektu…" in the map's area badge → `PUT …/area`); the stores
  ("Zmień magazyn…" → `PUT …/stores/{producer}`); the project's "Weryfikuj" and "Sprawdź
  aktualizacje"; each group with its origin (a plan group's command lines through `POST
  /commands/format`, the first three and "i N więcej"; a local group's selections in words),
  its "Sprawdź aktualizacje", "Przepnij", "Przywróć brakujące", "Usuń grupę", and its pins
  with the state, the command's state (D-12) and "Odepnij"; the reasons in force listed once,
  in the order of ADR-042 decision 4 with `no_commands` and `command_not_rebuildable` before
  offline mode; one `useJob` for the project's jobs, whose result marks each pin until the
  next read; the activity (20 newest, "Więcej"); own data and sharing unchanged. The guide's
  slide "Projekty" says it, with a new picture. *Tests:* `tests/e2e/test_project_card.py`
  (Chromium, the layout in Firefox too: a fixture project with both origins; "Weryfikuj"
  offline and its states; check, re-pin and restore disabled offline with the reason; a
  group of `soil hsg`-like pins shows the D-5 reason; "Pokaż na mapie" opens the area; the
  activity; a person who may not change the project), `tests/e2e/test_guide.py` (the
  picture), `tests/e2e/test_acceptance_v03.py` (UC-06 again on the new card).
- *Documents:* USAGE "Projects and own data" rewritten for the card (its "Changing" note and
  that of AGENT_API go; new pictures in place of `reports/v0.3-screenshots/10-zadanie-projektu.webp`
  and `11-akcje-projektu.webp`), SPEC 6.5 g if it differs, CHANGELOG, PROGRESS.
- *Acceptance:* SPEC 13 "Projects" criterion 7 and the interface parts of 3, 5 and 6.

### P6. Exports (one commit)

**Starts from** P3 (`projects/`, the pins), `versions.attribution` of the index.

- `projects/exports.py`: the name rule of D-13; `export_path(version_file, export_dir) ->
  str` (relative when `os.path.commonpath` of their real paths is not the file system's root
  or drive, else absolute); `write_export(directory, name, rows) -> ExportResult`
  (`zestawy/<name>/pliki.txt`, each pinned version once in the order of groups and pins;
  `ATRYBUCJE.txt`, each attribution once in the order of first use; UTF-8, LF; each file
  through a temporary name and `os.replace`); `list_exports(directory, project_mtime)`
  (`name`, `files`, `written_at`, `changed_since`). `services/projects.py`
  `export_project(…, name, groups)` (`project.write`; the pins' files resolved in their
  configured store; `skipped: {no_store, missing}`; `project.export` logged). `POST
  /projects/{project}/exports` (`ExportRequest {name, groups?}` → `201 ProjectExport {name,
  path, files, pins, skipped, written_at}`), `GET /projects/{project}/exports`
  (`ProjectExports {items}`); `archiwista project-export PROJEKT NAZWA [--group GRUPA …]`,
  `project-exports PROJEKT`. The card's "Eksportuj…" (name and groups) and its list with
  "projekt zmieniony po eksporcie — wygeneruj ponownie". *Tests:*
  `tests/unit/test_project_exports.py` (relative and absolute paths, one line per version,
  the order of attributions, a failed replace leaves the old file), 
  `tests/integration/test_project_exports.py` (API equals CLI; permissions; skipped counts;
  regenerating; `changed_since` after a pin; the log entry), an export in
  `tests/e2e/test_project_card.py`.
- *Documents:* SPEC 8.4 if it differs; USAGE, AGENT_API, README, CHANGELOG, PROGRESS.
- *Acceptance:* SPEC 13 "Projects" criterion 8; the first part of UC-10.

## Risks

| Risk | Effect | Handling |
|---|---|---|
| The producers' commits are not pushed when P3 ends | P4 waits | P2 and P3 need no producer change; P5's activity commit and P6 can go before P4 |
| The producers' final signatures differ from the contract (the argument of `command_for_file`) | P4's adapter code changes | the capability hides it (`command_for_version(version, *, root)`); the contract tests run on `kartograf.testing` and IMGWTools' fixtures |
| The fixture rewrite of P2 touches many tests | a large first commit | the store generator's projects keep their names, paths and cases; only their file changes |
| A lock left on a share by a killed process | a project nobody can change | the refusal names the lock and its owner; a person removes it (D-3) |
| Large local groups make the card slow | many pins in one answer | groups collapse in the card; the route answers the index only, never a producer |

## Not in this plan

The QGIS export and the rest of SPEC 8.4 (v1.1); the IMGWTools actions that check, re-pin
and restore IMGW pins (v0.5); "Dodaj do projektu…" of the station views (v0.5); a history
file in the project directory (D7 b); migrating producer manifests (D4).

## Results

| Phase | Commits | Result |
|---|---|---|
| P1 | — | A-ADR-049; SPEC, SCOPE, PRD; USAGE and AGENT_API notes; this plan (2026-10-31, not committed) |
| P2 | | |
| P3 | | |
| P4 | | |
| P5 | | |
| P6 | | |
