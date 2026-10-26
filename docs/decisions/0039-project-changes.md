# ADR-039: Projects created and changed through their producer, where a scan finds them

**Date:** 2026-10-26
**Status:** proposed (done on the topic branch `feature/kartograf-data-output`, step A7 of the plan `docs/plans/2026-10-25-archiwista-next.md`, whose approval is delegated; accepted when the author approves and merges the branch)

**Context:** v0.3 "Actions" creates projects and changes their tasks (SPEC 4.7 and 9.2: `POST /projects`, `POST /projects/{id}/tasks`, `DELETE /projects/{id}/tasks/{name}`; "Dodaj jako zadanie projektu" of the plan window, A11; the project actions of the interface, A13). A manifest is changed only by its producer's API (A-ADR-003, A-ADR-023). Until now a project reached the index only through a scan of the configured project directories, and nothing in Archiwista wrote a manifest. Three questions were open: which calls write the manifest and with which store, where a new project may lie, and who may create or change one.

**Options:**
- Calls:
  - A) `run_command("project init" | "project add" | "project remove", …)` of Kartograf's catalog. Rejected: its `project add` passes the options of the task in their JSON form on to `add_project_task`, which takes library arguments, so a box (`bbox` with `bbox_crs`) passes the check and is then refused (a request to Kartograf, plan "Requests").
  - B) The library functions behind `kartograf project …` (`init_project`, `add_project_task` after `validate_command`, `remove_project_task`) behind a new optional capability.
- Place of a new project:
  - C) Any directory a request names. Rejected: the next scan would not find a project outside the project directories and would drop it from the index, and the server would write wherever a request says (SPEC 10.1).
  - D) Only where a scan finds it.
- Who creates a project:
  - E) Anyone with a session, who becomes its owner. Not now: it needs the decision about owners of v0.4 (the sharing screen).
  - F) `project.write` of the new project's directory, as every change of a project.

**Decision:** B, D and F.

1. **Capability** `ProjectActionAdapter` (`sources/protocol.py`), beside `ActionAdapter`, so a producer can offer its commands before its projects (the stand-in producer of the tests offers commands only, and so will the IMGW adapter until IMGW-14 is wired): `create_project(directory, *, root, relative)`, `add_project_task(directory, *, name, command, options)` with the options in the JSON form of the catalog, and `remove_project_task(directory, *, name)`. A refusal is the producer's `ProducerError`: its code, text, hint and `details.option`.
2. **Kartograf** (`adapter/kartograf/actions.py`). `init_project` always gets `root=` the configured store's directory, never the default root. When the store has path aliases (SPEC 4.6 point 7) the root is written relative to the project directory: Kartograf writes a root given relative to the working directory that way, so it goes as the path from the working directory, or as the absolute path where there is none (another drive). A task is checked with `validate_command` on the project's store first, as `kartograf project add` checks it; then `add_project_task` gets the library arguments, in which only the box differs (`bbox` with `bbox_crs` is one `BBox`, written back in the JSON form). The manifest equals the one Kartograf's own calls write for the same arguments.
3. **Where a project lies** (`services/projects.py`). The path is absolute, equal to or below a configured project directory that exists, at most `MAX_PROJECT_DEPTH` (4) levels down, in no hidden directory and no store's producer directory, and the part of it that exists resolves inside the project directory (no symbolic link out). Outside: `403 forbidden`, reason `path_outside_root`; a place a scan would not find: `400 validation_error`, reason `project_not_discoverable`; a project directory of the settings that is missing: `project_dir_missing`. The store is a configured store (`404`) with a directory of the producer (`400`, `store_without_producer`) that can be read now (`503 store_unavailable`): Kartograf would otherwise make the missing store directory, e.g. at the mount point of a disconnected share.
4. **Who.** Every change needs `project.write` of the project's access key (its owner or an administrator), after the visibility check: a project the person does not see is `404`, one they see but may not change `403 permission_denied`. A new project has no owner, so creating one is for administrators, the local owner among them.
5. **A task** names a command of the producer's catalog (`400`, `unknown_command`) and the project's producer (`400`, `other_producer`); an option that is a file path is refused before the producer (`403 path_outside_root`, `details.option`), as for every call (ADR-034). Removing a task keeps its files in the store.
6. **The index at once.** After a change the project is read again as a scan reads it (`index/projects.py:record_project`: the manifest's stamp taken before the read, `project_status`, the store matched by path or alias) and written in the server's process, like an area; an indexed project keeps its key, and the next scan finds the same stamp.

**Consequences:**
- The routes and commands of step A7 commit 2 (`POST /projects`, `POST /projects/{project}/tasks`, `DELETE /projects/{project}/tasks/{name}` and `archiwista project-init`, `project-add`, `project-remove`, `project-status`) are thin over `services/projects.py`.
- The producer's lock (`.kartograf-project.lock`) and its conflicts stay the producer's: a lock left by an interrupted write is refused with Kartograf's text after its five-second wait; recognising it as `project_locked` with the instruction is step A8.
- An unknown task of `DELETE /projects/{id}/tasks/{name}` is Kartograf's refusal (`400`, `details.option` `name`): the manifest, not the index, decides.
- A person without the role `admin` cannot create a project before v0.4 decides who may.

**Erratum 1 (2026-10-26, ADR 0032 decision 14):** a project is its directory, which may hold the manifests of Kartograf and IMGWTools. A change acts on one manifest: the one of the `producer` the request names (`producer` of `POST /projects/{project}/tasks`, `?producer=` of `DELETE /projects/{project}/tasks/{name}`, `--producer` of `project-add` and `project-remove`), else the project's only one. A project of several manifests refuses a change that names none (`400`, `producer_required`); `other_producer` (decision 5) now means a producer without a manifest in the project; both carry `details.option` `producer`. `POST /projects` in a directory that holds another producer's manifest adds the second manifest to the same project, with its key.

**Erratum 2 (2026-10-26, Kartograf `fe1ebc70`, its ADR-052 erratum 3):** `run_command("project add", …)` converts the options of the task from their JSON form as `kartograf project add` does, so `add_task` calls it with the options as they came (after `validate_command` on the project's store, as before), and the adapter's own conversion of the box (`_task_arguments`) is gone.
