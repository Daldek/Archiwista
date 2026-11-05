# Plan: Obserwator's commands in Archiwista (fetch and refresh IMGW data), v0.5 „IMGW stations”

Not approved for implementation. Written on 2026-11-05 at the author's request („przygotuj nową gałąź dla tej współpracy i napisz plan, ale nie wdrażaj go”); work starts after the author approves this plan. Parent plan: Nogat `docs/plans/2026-11-05-obserwator-in-archiwista.md` (branch `plan/obserwator-in-archiwista`), its step 1 and step 2.

Requirements: SPEC 12.2 (KB-1 to KB-5, the model for a producer's commands), 12.7 (IMGW-1 to IMGW-13, IMGW-21), 14 (v0.5 „IMGW stations”); A-ADR-024 (Obserwator as an optional plugin), A-ADR-049 D5 (check, re-pin and restore of a pin by its version's command); ECO-054, ECO-057, HUB-5.2, REL-5.3, DEV-17.4. Branch `feature/obserwator-actions` (from `develop` `4ac2933`).

## Goal

A person fetches and refreshes the data of an Obserwator store from Archiwista as they do for Kartograf: Obserwator's commands appear in the plan window and the command forms, a plan shows what a run would download, a job runs it with progress and can be cancelled, and a project checks, re-pins and restores its pinned IMGW versions. The test server (:8090) then offers an Obserwator store with IMGW-PIB stations and daily hydrological series.

## What exists (2026-11-05)

- Read side, done: `src/archiwista/adapter/obserwator/adapter.py` (`ObserwatorAdapter`: `probe`, `default_root`, `iter_entries`, `read_meta`, `describe_segment`, `current_version`, station catalog, series index and values, characteristics, `footprint`, `export_folder`, `command_for_version`). `tests/contract/test_obserwator*.py`: 128 passed with Obserwator `1ee5457`. A live smoke on 2026-11-05 (a throwaway store with the IMGW-PIB catalog and `pl.imgw.hydro_daily` 2024 built by Obserwator's CLI) showed station 149180010 with its Q series of 2024, 366 of 366 days, and the IMGW-PIB licence text.
- Missing: the plugin does not implement `ActionAdapter` (`src/archiwista/sources/protocol.py:355`), so `archiwista commands list` lists Kartograf's commands only and no job can fetch IMGW data.
- Obserwator `1ee5457` (pinned, `candidate-1`) offers: `data_commands`, `list_commands`, `command_schema` (Polish and English texts), `check_command`, the parsing and formatting of command lines, `check_store` and `sync_store` with `plan`, `on_progress` and `cancel` (`src/obserwator/store/sync.py:782, 1089`), the plan document `obserwator-plan/1`, `command_for_version`. The extra `obserwator[store]` installs no CLI, which the adapter does not need.
- IMGW-PIB archives are national files (a year or a month per file): an area cannot narrow a download, it only filters stations in the views.
- :8090 runs `b2307ee` without the extra; its `config.toml` names only a Kartograf store.

## Decisions

| # | Decision |
|---|---|
| A1 | `ObserwatorAdapter` implements `ActionAdapter` with Obserwator's public API only, `adapter/kartograf/` as the model: `commands` = Obserwator's commands that write its store (`store catalog`, `store sync`, the series build, as `data_commands` names them), `parse`, `validate` (offline), `format`, `check` (`obserwator-plan/1` → `ActionPlan`), `run` (a plan, progress, cancel by `KeyboardInterrupt`, failed units as items), `scope`, `narrow`. |
| A2 | `availability_products()` is empty (Obserwator has no availability report of an area); `with_area` refuses with `no_area_option` (national files). |
| A3 | The jobs (download, check; `project_check`, `project_repin`, `project_restore`) take the producer from the pin and work for Obserwator through A1 and `command_for_version` (A-ADR-049 D5); whatever assumes Kartograf in `jobs/worker.py`, the services or the API is generalised, not duplicated. |
| A4 | The plan window and the forms read Obserwator's catalog like Kartograf's, Polish texts from the catalog (`lang="pl"`); a store with an Obserwator directory offers its commands. |
| A5 | No Obserwator change in this plan. A missing function becomes a `request` in Obserwator (DEV-17.5), never a workaround in the adapter. |
| A6 | The test server: the store `zespol` gains `obserwator = "/data/nmt/archiwista-obserwator"` (on `/data`, next to and never inside the Kartograf store); its first data are fetched by Archiwista's own jobs: the IMGW-PIB station catalog, `pl.imgw.hydro_daily` 1951–2024 and its series. |
| A7 | A new A-ADR (or an erratum of A-ADR-024) records A1 to A5. |

## Phases

| # | Change | Verified by |
|---|---|---|
| P1 | A1, A2: the adapter's actions; contract tests offline on stores of `obserwator.testing` and recorded plans: catalog, parse/format round trip, validate errors, check → `ActionPlan`, run with a plan writing a version (Obserwator's HTTP layer stubbed as its own tests do), narrow, scope, cancel; one `live` test (`store sync` of one year), not run by default | `tests/contract`, the gate |
| P2 | A3: jobs and project actions for IMGW pins | tests of a project with an IMGW pin: check, re-pin, restore |
| P3 | A4: plan window and forms; the guide `/instrukcja`; A7, SPEC, PROGRESS, CHANGELOG | browser test (GPT) on a throwaway instance |
| P4 | Smoke on a throwaway instance: a real `store catalog` IMGW-PIB and `store sync` of `pl.imgw.hydro_daily` 2024 with series, started from Archiwista; station card and chart | the job's result, `archiwista stations show 149180010`, `stations series … --variable Q` |
| P5 | A6: deploy on :8090 (backup and rollback as on 2026-11-04: SQLite `.backup` of index and state, settings, the unit; `uv sync --locked --all-extras`), the store, the first fetch through Archiwista | `archiwista status`, the public host, a GPT browser test |
| P6 | Nogat: the registry's edge Archiwista → Obserwator `active` (`via: [library, store]`), ECOSYSTEM_MAP and AGENTS.md regenerated | Nogat gate |

## Risks

- Disk: `pl.imgw.hydro_daily` 1951–2024 is 74 national archives plus the series; size measured in P4 before P5. The store lies on `/data` (236 GB free), not on `/` (about 7 GB free).
- A long `store sync` blocks one of the two network jobs per person (`network_jobs_per_person = 2`).

## Results

Pending.
