# ADR-042: The actions in the interface: a pasted command, a task of a project, what a person may do

**Date:** 2026-10-26
**Status:** proposed (done on the topic branch `feature/kartograf-data-output`, steps A11 and A13 of the plan `docs/plans/2026-10-25-archiwista-next.md`, whose approval is delegated; accepted when the author approves and merges the branch)

**Context:** v0.3 puts every action with the network or a write through the plan window (SPEC 13 v0.3 criterion 4), takes a pasted producer's command (UC-15), offers "Dodaj jako zadanie projektu" in the plan window (SPEC 6.5 h, UC-01 point 5) and the actions of a project in its card (SPEC 6.5 g: create, add and remove a task, status, verify, check, download, repin). An action a person may not do is shown disabled with the reason, never offered and then refused (SPEC 10.2). The session says whether it may write the stores (`store_write`, ADR-037) but not whether it may change a given project (`project.write`: its owner or an administrator, A-ADR-029).

**Options:**
- How the interface learns `project.write`:
  - A) Ask by trying: start the change and show the `403`. Rejected: the action is offered and then refused.
  - B) The rule in the client (the owner from `GET /projects/{id}/access`). Rejected: a second copy of the `Authorizer`, and the access entry is the owner's and administrators' to read.
  - C) Each project of a listing and the card say it (`project_write`), answered by the `Authorizer` for the session's principal.
- Where a pasted line is checked:
  - D) Only in the plan window, by its `check` job. Rejected: a mistake shows as a failed plan, not at the field, and offline the line is never checked.
  - E) At the field: the producer reads it (`POST /commands/parse`) and checks it without the network against the target store (`POST /commands/validate`); the plan window opens for a valid line only.
- What "Dodaj jako zadanie projektu" with something to download runs:
  - F) The plan's own downloads (`download` with `plan_job`) after the task is added. Rejected: the files land in the store but the task pins nothing, so the project shows the new task not downloaded.
  - G) The project's download of the new task (`POST /projects/{id}/jobs`, `download`, `tasks` the new one), which downloads and pins it, as SPEC 4.7 says for an IMGW task ("Pobierz teraz": `add_project_task`, then `download_project`).

**Decision:** C, E and G.

1. **`project_write`** (API commit). `Authorizer.writable_projects(principal)` returns a predicate of the access key, the answer of `can(principal, "project.write", key)` for every project from one read of the state database; `ProjectItem` (of `GET /projects` and of `GET /stores/{store}`) and `ProjectCard` carry it, read at each request like `store_write`.
2. **The pasted command** ("Wklej polecenie producenta", step 4 of the map's panel, with or without an area). The producer is the line's first word when that names an installed producer (`GET /sources`), else the step's producer. A refusal of either call shows the producer's text at the field (`aria-invalid`, `aria-describedby` on an alert). A valid line opens the plan window with `line` instead of a variant (no format to choose); the run writes to the target store, and the line's `-o` or `--root` stays in `run`, unused. The plan window keeps a line's call as soon as it is read, so a check refused offline (`409 offline_mode`) still leaves the call to add as a task.
3. **"Dodaj jako zadanie projektu"** takes the projects of the producer in the plan's store (`GET /projects?store=`) that the session may change; the task is the line's call as read, with the producer, added through `POST /projects/{id}/tasks` (the producer's offline validation; a refused name shows at the name field). With positions to download and `store_write`, the project's download of the task follows (G); otherwise only the task is added. The option is disabled with the reason when the variant's format has several lines (a task is one command), when the store has no project of the producer, when the session may change none, and when the line was not read.

**Consequences:**
- A client can show every project action disabled with its reason before it asks; the routes still decide.
- Adding a task works offline; downloading it needs the network, so offline the plan window adds the task alone.
- The plan shown is the command's; the project's download plans again in its worker, so a position that changed between the two is fetched as the source has it then.
- The download of a new task cannot be shown end to end without the network: the browser tests cover adding the task offline over Kartograf's fixture project, the plan and the download with the stand-in producer, and the permission with the person a project is shared with.
