# PROGRESS: Archiwista

Current state only (DOC-6.1). Branch, tag and remote state: ask git (`git status`,
`git log --oneline -10`). History: the git log, [CHANGELOG](CHANGELOG.md), the plans'
Results in `docs/plans/` and the ADRs; the Polish session notes that used to live here
are in git (`docs/PROGRESS.md` before the commit that introduced this file).

## Status

The working branch is `develop`. On 2026-11-03 `feature/archiwista-projects` (`10dd702`,
which holds Nogat standard 2.1, the Obserwator source and station views, the data output,
v0.3, v0.4, the user guide and the projects) and `plan/next-version` were merged into it
(`6f1caef`, `7b3eb79`; no pull request, the author's decision) and the merged branches
deleted; `feat/mockup` stayed and was deleted from `origin` on 2026-11-10 (Open questions,
Decided). `main` is on GitHub since 2026-11-10. The author's team test server (port 8090,
https://archiwista-test.debever.pl, user unit `archiwista-public.service`) runs `bd754b6`
(`develop`) since 2026-11-12; rollback steps in
`/home/claude-agent/data/archiwista-public/backup-2026-11-12/ROLLBACK.txt` (code and
`uv sync`: `checkout --detach cd29b6f`, sync and restart). Nothing after 0.2.0 is released.

| Component | State | Note |
|---|---|---|
| Nogat's GUI kit: the menu „Aplikacje” and the hand-off through the kit (`feature/nogat-kit`, A-ADR-054; Nogat ECO-058, plan `2026-11-12-gui-links-and-handoff` step 6) | merged into `develop` (`bd754b6`) and deployed on :8090 on 2026-11-12 (the author's request); its `nogat.toml` lists the four public GUIs | Kit 0.1.0 and the marks of Nogat `7786271` in `web/nogat/` (byte for byte, checked against `nogat-kit.json`); `[nogat.gui]` of `nogat.toml` read with the other keys and answered by `GET /session` as `gui`, the doctor names it; the station card's „Do Hydrologa” through `nogat-handoff.js` (subject file name rule, final newline, a selected field where there is no Clipboard API, „Otwórz Hydrologa”); `handoff-1` and `error_registry.json` copied again. Smoke on 2026-11-12: a server of the worktree with three GUIs in a temporary `nogat.toml`, the menu and both copies in Chromium. Gate (`scripts/gate.sh`, Python 3.12, 74 min): 2881 passed, 1 failed, the new menu test, whose click raced the first-run wizard taking the focus (which closes the kit's list); it now waits for the wizard and passes three times alone and with its files (`test_shell.py`, `test_station_chart.py`: 36 passed); the full gate did not run again. To show the menu on :8090 its `nogat.toml` needs `[nogat.gui]` (the author's list of 2026-11-12) |
| Pins of Nogat's release set candidate-2 (`chore/pins-candidate-2`, Nogat `587c909`) | merged (`a656ee1`), deployed on :8090 on 2026-11-12 | Kartograf `9deaa314` → `d0990c89`, Obserwator `1ee5457` → `f9f4ee79` (`ecosystem.py set apply`; `uv lock --check` passes). Targeted tests: `tests/contract` 380 passed; the Obserwator and source integration tests 55 passed; `tests/unit tests/integration -k "kartograf or obserwator"` 75 passed. The adapter's catalog offers `soil hsg --depth-rule` without `--depth`. The full gate (about an hour) did not run on the branch |
| The project card's re-pin and restore through the plan window of the set's check (`feature/project-plan-window`, ADR-042 erratum 2) | merged into `develop` on 2026-11-10, deployed on :8090 on 2026-11-12 | „Przepnij” and „Przywróć brakujące” of a set open a window that runs the set's check (`project_check`), shows the set's plan and starts the job with `plan_job` when it is confirmed; `POST /projects/{project}/jobs` and `project-repin`/`project-restore --plan` refuse a check without its plan (`404`) and one of another kind, project or set, or of a set changed since (`409 plan_mismatch`; the check's pin rows carry the pinned `sha256`). The worker plans again. Targeted tests: the project jobs' integration tests (65 passed) and the e2e of the card, UC-06, the sets in the making and the projects view (18 passed, Playwright); full gate: see Gate |
| Archiwista reads `nogat.toml` (`feature/nogat-settings`, A-ADR-053) | merged into `develop` on 2026-11-10, deployed on :8090 on 2026-11-12 | `data_dir` puts the local data in `<data_dir>/archiwista`, `cache_dir` the caches in `<cache_dir>/archiwista`, `lang` sets the command line's language for a person (`[archiwista]` before `[nogat]`; no `NOGAT_<KEY>` variable); an unusable file stops every command but `archiwista doctor`, which names each value's source. The `nogat.toml` of :8090 (in its `XDG_CONFIG_HOME`) holds only the table `gui`, so its directories stay. Full gate: see Gate |
| The status text of a Kartograf store without its marker names `kartograf store init --root <path>` (`fix/no-marker-banner-command`) | merged into `develop` (`bf6813b`) on 2026-11-10, deployed on :8090 on 2026-11-12 | The banner and the Store view show the command, as the job error's hint, the settings problem and `archiwista doctor` did (`source.no_marker`); full gate: see Gate |
| Obserwator's commands (plan `docs/plans/2026-11-05-obserwator-actions.md` P1 to P5, A-ADR-050; Nogat plan `2026-11-05-obserwator-in-archiwista.md` steps 1 and 2) | merged into `develop` (`b253244`) and deployed on :8090 on 2026-11-05 | The adapter offers `store sync`, `store catalog` and `series build`; „Polecenia producenta” of the Store view. P5 on 2026-11-05: :8090 at `b253244` with `uv sync --locked --all-extras`, the store `zespol` moved to the SMB share `/mnt/magazyn/agent-tmp/archiwista-zespol/` (`kartograf/`, `obserwator/`, `kind = "share"`; backup and rollback in `backup-2026-11-05/`), its first IMGW-PIB data (station catalog, daily, monthly and half-year hydrological data) fetched by the author through Archiwista's jobs. |
| Fixes and features of 2026-11-05 (`fix/distinct-notices` → `feature/monthly-annual-charts` → `fix/map-station-products` → `feature/series-handoff`) | merged into `develop` (`32d3ce4`), deployed on :8090; gate green on the top (`ec3e746`: 2852 passed, 71 min) | A repeated notice listed once; monthly charts and annual extremes (A-ADR-051); the map's station products named after their stations, „Wszystkie produkty” with the stations, a short station tooltip, no twitching map (the author confirmed it on 2026-11-06); a station's series handed to Hydrolog (A-ADR-052, with Hydrolog and Nogat). |
| „Do Hydrologa” chooses the data and the variable (`fix/handoff-choices`) | merged (`77f7fbc`), deployed on :8090; the author checked it on 2026-11-06 | A group under the station chart: „Dane” (daily values of a series of days, or annual maxima of complete hydrological years) and „Zmienna”, whatever chart is shown; the chart's range goes with its own kind only. |
| The map draws a station catalog without series (`fix/map-catalog-stations`) | merged (`cd29b6f`), deployed on :8090 on 2026-11-06 | ČHMÚ's `store catalogs` alone showed no station: the map always sends the kind's first dataset, which `GET /map/stations` used as a filter. Now `dataset` alone labels the points; a station without a series of it is „brak danych”; the „bez położenia” counter opens the Katalog without the dataset. Checked on the server's index: hydro 1751 stations (870 ČHMÚ), meteo 2389 (1602 ČHMÚ). |
| IMGWTools is called Obserwator (Nogat ECO-057; Nogat plan `2026-11-03-imgwtools-to-obserwator.md` step 3) | done on `develop`, deployed with `b253244` | Obserwator `ea158dc6` and Kartograf `9deaa314`, the commits of Nogat's release set `candidate-1` (`ecosystem.py set apply`) (it knows `obserwator-store.json`); the extra, plugin, producer and settings field `obserwator`, the reason `obserwator_error`, the ids `obserwator-*`, the adapter `archiwista.adapter.obserwator`; index schema 18 (a rebuild); A-ADR-032 erratum 2 |
| Projects in Archiwista's own file (A-ADR-049 and its errata 1 to 4; Nogat plan `2026-10-31-archiwista-projects.md` step 5, ECO-054; plan `docs/plans/2026-10-31-archiwista-projects.md`) | done, in `develop`, deployed on the test server | A project is a directory holding `archiwista-project.json` (`archiwista-project/1`; lock and atomic write; discovery by that file alone; index schema 16, state schema 4), its area files in `obszary/`. Groups, shown as „Zestaw”, hold pins: from the store (Katalog, map, store view: "Dodaj do projektu…"; a filter or a map layer pins the versions it shows) and from the plan window (a plan group keeps the producer's calls). Jobs verify, check, re-pin and restore over `POST /projects/{project}/jobs` (`PROTOCOL_VERSION` 13), rebuilt from Kartograf's `command_for_file` and Obserwator's `command_for_version`; a pin without a rebuildable command stays pinnable with check and restore disabled with the reason (D5). The card shows the activity from the action log. "Usuń projekt…" removes a project from Archiwista, never data (erratum 2). The export is flat: `eksport/<name>/` with one folder per category (`NMT`, `BDOT`, `ORTO`, …), copies of the files and `README.txt`, optionally `eksport/<name>.zip` (erratum 1); a ZIP holding exactly one raster is exported unpacked, an XYZ file with the coordinate system to set in QGIS (erratum 4). The producers' project manifests and ADR-039/ADR-040 are gone. Pins: Kartograf `9deaa314` (its `develop`), Obserwator `651d4d73` (its `feature/obserwator`; both pushed) |
| Katalog: the variant of a row | done, in `develop`, deployed on the test server | Each row, the file card and the map's "Warianty (segmenty)" name the variant (resolution and height system, `web/src/variant.js`); the „Wariant” filter is `segment` of `GET /slots`; file rows wrap their text and grow (`7252df5`, `96c72eb`) |
| Availability: a polygon area as GeoJSON | done, in `develop`, deployed on the test server | Areas reach Kartograf as WGS84 GeoJSON (`<data-dir>/areas/<id>.geojson`; a plan group's call names `obszary/<id>.geojson`, A-ADR-035 erratum 2, A-ADR-049 erratum 3), and Kartograf ADR-058 selects sheets by the shape, not its envelope (`9e26138`, `c5a3d8c`). The store badge „pobrane” matches by survey work (`0509143`) |
| Plan window: bounded requests | done, in `develop`, deployed on the test server | Four requests in flight (`requestEach`), a bare `503` is `server_busy`, after a 116-sheet set exceeded the server's 100 connections (`c9fd47b`); one „Zamknij” keeps a download's window reopenable from the list (`d4daea6`) |
| Previews of a ZIP of one raster (GUGiK's XYZ of 2020) | done, in `develop`, deployed on the test server | Previewed as that raster through `/vsizip/`, format named "XYZ (ZIP)" (`formats.raster_member`, the rule exports share; `43c2254`) |
| Phone fields | done, in `develop`, deployed on the test server | Fields at 16 px on a phone, so iOS does not zoom in after sign-in (`1f2ed39`) |
| A project's area for the map, the Katalog and a producer's call (A-ADR-049 erratum 5; the author confirmed the interface on 2026-11-02, D7 of Nogat's plan `2026-11-02-archiwista-sets-for-hydrograf.md`) | done, in `develop` (`0d4f958`, `2ceca75`), deployed on the test server | "Obszar projektu" in the map's step 1 and the Katalog's area filter; "Obszar polecenia" runs a pasted call on the area of step 1 or a project's (`POST /commands/area`, `archiwista commands area`, the source capability `AreaCommandAdapter`, Kartograf's `with_area`: the area as `--geometry`, else its box); the plan window's "Obszar" row; the project card's "Pliki obszaru w Katalogu" and file count |
| Draft sets (A-ADR-049 erratum 6; step A2 of Nogat's plan `2026-11-02-archiwista-sets-for-hydrograf.md`) | done, in `develop` (`21eff04`..`6ece8ca`), gated, deployed on the test server | A group's `state`, `open` or `closed` (no member: closed), with `closed_at`, `closed_by` and `pins_sha256` in the project file; close, „Otwórz do edycji” and uncall; one producer per set (D12); index schema 17. `archiwista-state/2` back to `/1` is deferred to release preparation (the author) |
| User guide `/instrukcja` | done, in `develop` | A-ADR-048 (proposed; merged into `develop` with the stack on 2026-11-03): twelve Polish slides served without a session, "Instrukcja" in the top bar; slide 9 shows the project card |
| v0.4 "Team" | built, in `develop` | plan `docs/plans/2026-10-26-plan-v0.4.md` T1 to T12 (ADR-046, ADR-047; security D6, D7, D10); acceptance with three people, the permission matrix, the ASVS checklist; the LAN runbook ran once on one machine with real components (`docs/reports/v0.4-lan-runbook.md`); macOS fixes (no `RLIMIT_AS`, `TCP_NODELAY`, `F_GETPATH`) |
| v0.3 "Actions" | built, in `develop` | plan `docs/plans/2026-10-25-archiwista-next.md` Part 3: A1 to A14 (ADR-034 to ADR-044): producer commands, availability at the source, the plan window, downloads and job controls, preview warm-up, background downloads; its project actions (A7, A8, A13) are replaced by A-ADR-049. Report `docs/reports/v0.3-measurements.md` |
| Obserwator source and station views | done, in `develop` | plan `docs/plans/2026-10-25-archiwista-next.md` Parts 2 and 4 (ADR-032, ADR-045): Obserwator stores indexed, stations, series coverage, the station map, Katalog list, Timeline, card, chart and comparison |
| Data output (DEV §19, ECO-051) | done, in `develop` | plan `docs/plans/2026-10-25-archiwista-next.md` Part 1 (ADR-031, ADR-033): store markers, store roots, the producers' default roots offered in the wizard, tests isolated from the producers' settings |
| Release 0.2.0 "Previews" | done | released on `develop`, not tagged and not merged into `main` (author's decision) |
| Nogat standard 2.1 | done | structure and tooling (uv, `src/` layout, `scripts/gate.sh`, CI, Dependabot), English documentation, error registry; skipped items below |
| Deploy on the test server (A3) | done 2026-11-03 about 00:00 | `4027755` on :8090, `Environment=TMPDIR=<data-dir>/tmp` in the unit (Kartograf unpacks BDOT10k there; `/tmp` is a small tmpfs). The index was rebuilt from schema 16 to 17, which dropped the sessions (everyone signs in again), the job history and the 18 drawn rectangles of the map. Copies taken before the restart (index 16, state 4, the old unit) and the rollback to `dd4268c`: `/home/claude-agent/data/archiwista-public/backup-2026-11-02/` and its `ROLLBACK.txt` |
| Deploy on the test server (Obserwator, feedback, release-set pins) | done 2026-11-04 11:08 | `b2307ee` on :8090 (`uv sync --locked`; Kartograf `9deaa314` instead of the pre-rewrite `26ee459`); about 2 s down. The index was rebuilt from schema 17 to 18 (735 versions refilled at once; sessions and the job history of 710 jobs dropped, the 2 drawn areas kept); the state database went from schema 4 to 5 (table `feedback`); the server's settings name only a Kartograf store, so nothing else changed. Checked: `/` 200 locally, the public host behind Cloudflare Access, `POST /api/v1/feedback` and `/api/v1/admin/feedback` refuse an anonymous call with 401. Copies (index 17, state 4, settings, the unit) and the rollback to `34e83f4`: `/home/claude-agent/data/archiwista-public/backup-2026-11-04/` and its `ROLLBACK.txt` |
| Gate | 2026-11-10 on `develop` `0f00025` (the three rows above): 2870 passed, 2 failed, 65 min | Both failures flaky (Next 3): they pass alone and with their files; the `sqlite3` one is fixed since. Before: green on the stack of 2026-11-05 (`ec3e746`: 2852 passed, coverage 93.7 %, 71 min with `TMPDIR` on a local disk). CI ran the full suite on `develop`. A full local run takes 65 to 70 minutes; start it without other test suites running |
| CI (Linux) | green on `develop` `8f34a4c` (2026-11-06) | First runs since the push of 2026-11-03 were red: the gate's 30 min cut the 40 min suite short (now 90), and the run without the extra `obserwator` failed at collection and on `obserwator_store` (now skipped there; `tests/conftest.py`). `test_project_card.py::test_the_activity_shows_the_newest_entries_and_a_change_made_on_the_card` failed once in two jobs and passed on the re-run (cause not found; Next). Python 3.15 (reported, not blocking) fails on an unraisable `sqlite3` finalizer warning in an e2e test. `live.yml` has not run |

Skipped adoption items, which need the author (DEV-3.3, ADOPTION_PLAN):

| Item | Why |
|---|---|
| History rewrite (phase 1) | Archiwista needs only DEV-4.2: every commit is by `Daldek <git@debever.pl>` and has no AI trailer |
| Rulesets for `main`, `develop` and `v*` tags, private vulnerability reporting, Dependabot security updates, `main` made the default branch (DEV-3.6, DEV-13.6, DEV-13.7, ECO-008) | GitHub settings. `main` was pushed on 2026-11-10 at the root commit `5578983` (0.2.0 is not merged into it, the author's decision); the default branch is still `develop`. The required check is the one job `gate (ubuntu-latest, Python 3.12)` (CI runs on Linux only) |
| `docs/CLA.md` text and signing mechanism | the author's legal text: it says "comment on the pull request", while DEV-16.5 says checkbox plus a line in `CONTRIBUTORS.md` in the same pull request |
| `Approved:` lines of the executed plans v0.1 and v0.2 (DEV-17.4) | approval is the author's statement |
| Tags, releases, replacing the producers' commit pins by tags, PyPI name `nogat-archiwista` (phases 5 and 6) | need the producers' tags and the author's approval |

On 2026-11-04 `feature/feedback` (Nogat plan
`2026-11-03-feedback-in-archiwista-and-hydrolog`, decisions D1, D2, D4–D6) added
Hydrograf's "Zgłoś uwagę": the top bar's window with its diagnostics, `POST /feedback`,
the administrators' `/admin/feedback` routes and view "Zgłoszenia", and the state
database's schema version 5 (table `feedback`); merged into `develop` after a green gate
(2,782 passed) and deployed on :8090 the same day.

## Next

1. The author decides (next session): „Pobierz CSV” on the station card, through
   Obserwator's `export_series` (CSV with the provider's attribution); today a series leaves
   as the hand-off JSON, the parquet path, or a Python call of `obserwator.export_series`.
2. The author decides (next session): a `request` to Obserwator to keep the precision of an
   occurrence date IMGW-PIB publishes without a day (`2020-03`), which the store keeps as
   the month's first (plan `2026-11-05-monthly-annual-charts.md`, Risks).
3. Flaky tests. (a) The activity test of the project card (CI, Status): after „Usuń zestaw”
   the list kept its old first entry for 30 s. The activity re-reads on `card.scanned_at`,
   which has one-second precision; whether the card was read again with the same stamp is
   not established. (b) `tests/e2e/test_sign_in.py::test_a_temporary_password_is_changed_before_the_shell_opens`
   failed once in the gate of 2026-11-10 (the heading „Logowanie” never showed in 30 s) and
   passes alone and with its file; cause not found. (c) Fixed on 2026-11-10:
   `test_timeline.py::test_timeline_shows_years_without_data` failed in that gate on an
   unclosed `sqlite3` connection that `test_store_commands.py` left to the garbage collector
   (`with sqlite3.connect(…)` commits, it does not close); it may be the Python 3.15 e2e
   warning of CI too (not rerun).
4. A welcome dialog for a first visit and its slide in the guide `/instrukcja`.
5. Release preparation (the author): `archiwista-state/2` back to `/1` (a format
   identifier not yet released on `main` stays at `/1`), then the release below.
6. Release, per decisions D2 and D3 of Nogat's plan
   `2026-10-31-archiwista-projects.md`: one Archiwista release holds v0.3, v0.4 and the
   projects (all in `develop` since 2026-11-03), outside the first release set
   (Archiwista follows the producers' tags in its own session, REL-5.4). Then: replace
   the commit pins by the producers' tags (REL-5.3, REL-2.1), CHANGELOG version and tag
   with the author's approval, the Nogat registry (the edge Archiwista → Obserwator is
   still `planned`). Re-pin first if a producer commits on its branch again: `uv lock
   --offline` resolves a commit only from uv's git database
   (`~/.cache/uv/git-v1/db/`), so fetch the producer's branch into it, change the commit
   in `pyproject.toml`, `uv lock --offline`, `uv sync --locked --all-extras`.
7. The author: the runbook's three-computer SMB/TLS scenario on a Linux server (CA trust
   in three browsers, the store on the share); a full `scripts/gate.sh` on the Mac; the
   live run of `tests/integration/test_live_actions.py` (`ARCHIWISTA_LIVE_ACTIONS=1`)
   and the SMB run of v0.3 criterion 8.
8. CI: the weekly `live.yml` has not run yet.
9. Use `kartograf.testing` instead of the hand-made `tests/fixtures/make_store.py` where
   it covers the case (DEV-10.6).
10. Adopt the ecosystem's visual identity (Nogat `design/`, plan
   `docs/plans/2026-11-01-visual-identity.md` in Nogat) once the author approves it, by
   an Archiwista plan.
11. AGI-4.1: a top-level `schema` (`archiwista-<kind>/1`) in every API response and
   `--json` output, added with the catalog work (the author's decision of 2026-11-09);
   until then the deviation of `CLAUDE.md` (AGI-3.2, AGI-4.1, AGI-4.2) stands.

Known gaps:

- Obserwator: a plan of `store catalog` has nothing to download once a catalog exists (the
  public API gives no freshness signal), so its refresh runs without a plan; Obserwator has
  no run mode that keeps the stored versions (a restore takes the source's current file);
  `pmaxtp sync` is not in Archiwista's catalog (A-ADR-050 option C).
- „U źródła” offers only NMT, NMPT and LAZ until Kartograf KD-3/KD-4 (availability of
  orthophoto, BDOT10k and unit products); meanwhile paste the producer's command
  („Wklej polecenie producenta”), which „Obszar polecenia” now runs on a project's area.
- Plans show „rozmiar nieznany” until Kartograf KH (the size of a plan item).
- The „pobrane” badge cannot match LAZ: Kartograf's LAZ sidecar records no survey work
  (request filed on 2026-11-10 as Kartograf `docs/PROGRESS.md` Next 30).
- The white rectangle over the map that the author reported was not reproduced.
- „Pokaż wynik na mapie” does not carry the Katalog's „Wariant” filter.
- The project card follows a job it started or the one a `409` names, not a job of the
  project started elsewhere.
- A map layer pins at most 500 versions.
- v0.3: the units colouring on the map (A12, M7) is not built; A15 waits for Kartograf
  KB-7; "one job per row" options B (a sheet list in Kartograf's hint) and D (a longer
  `PLAN_REFRESH_TTL_S`) are open; a variant without a default format and a plan with
  conflicts are untested in the browser (the stand-in has neither).
- Availability rows: the badge does not tell height systems apart; a LAZ variant has no
  default format and no size (ADR-017 names ASC and GeoTIFF); the row details of SPEC
  6.4 are not built.
- Stations: the archive badge (SPEC 9.2, 4.8.4) and the input archives of the station
  card need a producer capability the source interface lacks.
- User guide: no link on the sign-in page; its pictures need taking again when the views
  they show change.

## Open questions

Decisions awaiting the author:

- None.

Open outside this repository:

- Kartograf: the tag waits for the first release set; Archiwista's later versions need
  KA-4, KB-1 to KB-5, KB-7, KC-1 to KC-3, KD-1 to KD-4, KH; KF (merged PL + CZ surface)
  blocks v0.6.
- Obserwator: the v0.5 adapter treats `missing_sidecar` as a non-critical, possibly
  transient problem; the Obserwator actions are planned for v0.5.
- GPU: the measurement of 30 frames per second or more with 5,000 footprints needs hardware
  WebGL; the test account has no access to `/dev/dri/renderD128`.
- Basemap: one default provider (OpenFreeMap) is an availability risk outside offline mode.
- PRD "Open decisions" (the IMGW data format before v0.5, merge results as Kartograf
  products before v0.6, the ČHMÚ adapter) and the mockup questions M6 to M8 and M10
  (SPEC 16; the assistant proposal card for IMGW data is deferred after the MVP).
- The mockup (`mockup/`) is a clickable prototype, not production code; its working data
  directory is outside the repository and stays: the author's consent of 2026-11-09 was
  for the branch `feat/mockup` only.

### Decided

Author's decisions of 2026-11-09.

- **The project card's re-pin and restore through the plan window (ADR-042 option H).**
  „Przepnij” and „Przywróć brakujące” of a set open a window that runs the set's check
  and shows its plan, and the job starts when it is confirmed, naming that check
  (`plan_job`): done on 2026-11-10 (`feature/project-plan-window`, ADR-042 erratum 2;
  Status, CHANGELOG).
- **Status text of a store without its marker.** It carries the command too: done on
  2026-11-10 (`fix/no-marker-banner-command`; Status, CHANGELOG).
- **`nogat.toml`.** Read, for a consistent `data_dir`: done on 2026-11-10
  (`feature/nogat-settings`, A-ADR-053; Status, CHANGELOG).
- **`survey_work_id` in Kartograf's LAZ sidecar.** Filed the ecosystem way, as there is no
  `gh` here: Kartograf `docs/PROGRESS.md` Next 30 (Kartograf `034023dc`, merged into its
  `develop` as `2866fdcb` on 2026-11-10); Archiwista needs no change once it lands.
- **DEV-5.1 layout.** Kept as it is (`src/archiwista`, A-ADR-030 item 2); nothing moves.
- **AGI-6.2.** Kept: `/api/v1/openapi.json` behind the session, operations named after the
  route functions (the deviation in `CLAUDE.md`).
- **AGI-4.1 top-level `schema`.** Added with the catalog work later: planned work, Next 11.
- **`main` on GitHub.** Pushed on 2026-11-10 (`5578983`, unchanged); making it the default
  branch is the author's step on GitHub (Status, the adoption items above).
- **`feat/mockup`.** Deleted from `origin` on 2026-11-10 (tip `e25e833`), superseded by
  `fb4268d` in `develop` (`mockup/`).
