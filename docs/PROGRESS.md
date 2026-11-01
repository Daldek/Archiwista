# PROGRESS: Archiwista

Current state only (DOC-6.1). Branch, tag and remote state: ask git (`git status`,
`git log --oneline -10`). History: the git log, [CHANGELOG](CHANGELOG.md), the plans'
Results in `docs/plans/` and the ADRs; the Polish session notes that used to live here
are in git (`docs/PROGRESS.md` before the commit that introduced this file).

## Status

The working branch is `feature/archiwista-projects` (from `feature/v0.4-team`, which
holds v0.3, v0.4, the station views and the user guide). Its head runs on the author's
team test server (port 8090, https://archiwista-test.debever.pl). Nothing after 0.2.0
is merged into `develop` or released.

| Component | State | Note |
|---|---|---|
| Projects in Archiwista's own file (A-ADR-049 and its errata 1 to 4; Nogat plan `2026-10-31-archiwista-projects.md` step 5, ECO-054; plan `docs/plans/2026-10-31-archiwista-projects.md`) | done on `feature/archiwista-projects`, deployed on the test server | A project is a directory holding `archiwista-project.json` (`archiwista-project/1`; lock and atomic write; discovery by that file alone; index schema 16, state schema 4), its area files in `obszary/`. Groups, shown as „Zestaw”, hold pins: from the store (Katalog, map, store view: "Dodaj do projektu…"; a filter or a map layer pins the versions it shows) and from the plan window (a plan group keeps the producer's calls). Jobs verify, check, re-pin and restore over `POST /projects/{project}/jobs` (`PROTOCOL_VERSION` 13), rebuilt from Kartograf's `command_for_file` and IMGWTools' `command_for_version`; a pin without a rebuildable command stays pinnable with check and restore disabled with the reason (D5). The card shows the activity from the action log. "Usuń projekt…" removes a project from Archiwista, never data (erratum 2). The export is flat: `eksport/<name>/` with one folder per category (`NMT`, `BDOT`, `ORTO`, …), copies of the files and `README.txt`, optionally `eksport/<name>.zip` (erratum 1); a ZIP holding exactly one raster is exported unpacked, an XYZ file with the coordinate system to set in QGIS (erratum 4). The producers' project manifests and ADR-039/ADR-040 are gone. Pins: Kartograf `26ee4592`, IMGWTools `4bf8bb0d` (the pushed heads of their `feature/archiwista-projects`) |
| Katalog: the variant of a row | done on `feature/archiwista-projects`, deployed on the test server | Each row, the file card and the map's "Warianty (segmenty)" name the variant (resolution and height system, `web/src/variant.js`); the „Wariant” filter is `segment` of `GET /slots`; file rows wrap their text and grow (`7252df5`, `96c72eb`) |
| Availability: a polygon area as GeoJSON | done on `feature/archiwista-projects`, deployed on the test server | Areas reach Kartograf as WGS84 GeoJSON (`<data-dir>/areas/<id>.geojson`; a plan group's call names `obszary/<id>.geojson`, A-ADR-035 erratum 2, A-ADR-049 erratum 3), and Kartograf ADR-058 selects sheets by the shape, not its envelope (`9e26138`, `c5a3d8c`). The store badge „pobrane” matches by survey work (`0509143`) |
| Plan window: bounded requests | done on `feature/archiwista-projects`, deployed on the test server | Four requests in flight (`requestEach`), a bare `503` is `server_busy`, after a 116-sheet set exceeded the server's 100 connections (`c9fd47b`); one „Zamknij” keeps a download's window reopenable from the list (`d4daea6`) |
| Previews of a ZIP of one raster (GUGiK's XYZ of 2020) | done on `feature/archiwista-projects`, deployed on the test server | Previewed as that raster through `/vsizip/`, format named "XYZ (ZIP)" (`formats.raster_member`, the rule exports share; `43c2254`) |
| Phone fields | done on `feature/archiwista-projects`, deployed on the test server | Fields at 16 px on a phone, so iOS does not zoom in after sign-in (`1f2ed39`) |
| User guide `/instrukcja` | done, in `feature/v0.4-team` | A-ADR-048 (proposed; the author decides on merging): twelve Polish slides served without a session, "Instrukcja" in the top bar; slide 9 shows the project card |
| v0.4 "Team" | built on `feature/v0.4-team` | plan `docs/plans/2026-10-26-plan-v0.4.md` T1 to T12 (ADR-046, ADR-047; security D6, D7, D10); acceptance with three people, the permission matrix, the ASVS checklist; the LAN runbook ran once on one machine with real components (`docs/reports/v0.4-lan-runbook.md`); macOS fixes (no `RLIMIT_AS`, `TCP_NODELAY`, `F_GETPATH`) |
| v0.3 "Actions" | built | plan `docs/plans/2026-10-25-archiwista-next.md` Part 3: A1 to A14 (ADR-034 to ADR-044): producer commands, availability at the source, the plan window, downloads and job controls, preview warm-up, background downloads; its project actions (A7, A8, A13) are replaced by A-ADR-049. Report `docs/reports/v0.3-measurements.md` |
| IMGWTools source and station views | done, in `feature/v0.4-team` | plan `docs/plans/2026-10-25-archiwista-next.md` Parts 2 and 4 (ADR-032, ADR-045): IMGW stores indexed, stations, series coverage, the station map, Katalog list, Timeline, card, chart and comparison |
| Data output (DEV §19, ECO-051) | done, in `feature/v0.4-team` | plan `docs/plans/2026-10-25-archiwista-next.md` Part 1 (ADR-031, ADR-033): store markers, store roots, the producers' default roots offered in the wizard, tests isolated from the producers' settings |
| Release 0.2.0 "Previews" | done | released on `develop`, not tagged and not merged into `main` (author's decision) |
| Nogat standard 2.1 | done | structure and tooling (uv, `src/` layout, `scripts/gate.sh`, CI, Dependabot), English documentation, error registry; skipped items below |
| Gate | full run pending (next session, the author's decision of 2026-11-01) | the last full run, at `07f8c71`: 2654 passed, one failure (`test_doctor_refused_store_shows_the_fix_the_producer_gave`, port 8090 taken). The commits after it ran reduced gates and the tests of each change. A full run takes about 50 to 60 minutes; start it without other test suites running |
| CI (Linux) | written, not run | `.github/workflows/ci.yml` and `live.yml`; no run of either workflow is known |

Skipped adoption items, which need the author (DEV-3.3, ADOPTION_PLAN):

| Item | Why |
|---|---|
| History rewrite (phase 1) | Archiwista needs only DEV-4.2: every commit is by `Daldek <git@debever.pl>` and has no AI trailer |
| Rulesets for `main`, `develop` and `v*` tags, private vulnerability reporting, Dependabot security updates, `main` pushed and made the default branch (DEV-3.6, DEV-13.6, DEV-13.7, ECO-008) | GitHub settings. The required check is the one job `gate (ubuntu-latest, Python 3.12)` (CI runs on Linux only) |
| `docs/CLA.md` text and signing mechanism | the author's legal text: it says "comment on the pull request", while DEV-16.5 says checkbox plus a line in `CONTRIBUTORS.md` in the same pull request |
| `Approved:` lines of the executed plans v0.1 and v0.2 (DEV-17.4) | approval is the author's statement |
| Tags, releases, replacing the producers' commit pins by tags, PyPI name `nogat-archiwista` (phases 5 and 6) | need the producers' tags and the author's approval |
| Pull request and merge of `chore/nogat-2.1` (pushed) into `develop` | approvals (DEV-3.3) |

## Next

1. Run the full gate of the branch head (next session); `feature/archiwista-projects` is
   pushed after it passes (GitHub holds `07f8c71`).
2. Merge and release, per the Nogat plan's decisions D2 and D3: one Archiwista release
   holds v0.3, v0.4 and the projects, outside the first release set (Archiwista follows
   the producers' tags in its own session, REL-5.4). Then: replace the commit pins by
   the producers' tags (REL-5.3, REL-2.1), merge with the author's approval, CHANGELOG
   version, tag, the Nogat registry (the edge Archiwista → IMGWTools is still
   `planned`). Re-pin first if a producer commits on its branch again: `uv lock
   --offline` resolves a commit only from uv's git database
   (`~/.cache/uv/git-v1/db/`), so fetch the producer's branch into it, change the commit
   in `pyproject.toml`, `uv lock --offline`, `uv sync --locked --all-extras`.
3. The author: the runbook's three-computer SMB/TLS scenario on a Linux server (CA trust
   in three browsers, the store on the share); a full `scripts/gate.sh` on the Mac; the
   live run of `tests/integration/test_live_actions.py` (`ARCHIWISTA_LIVE_ACTIONS=1`)
   and the SMB run of v0.3 criterion 8.
4. CI proof after the push: the Chromium step of `ci.yml` and the weekly `live.yml`.
5. Use `kartograf.testing` instead of the hand-made `tests/fixtures/make_store.py` where
   it covers the case (DEV-10.6).

Known gaps:

- „U źródła” offers only NMT, NMPT and LAZ until Kartograf KD-3/KD-4 (availability of
  orthophoto, BDOT10k and unit products); meanwhile paste the producer's command
  („Wklej polecenie producenta”).
- Plans show „rozmiar nieznany” until Kartograf KH (the size of a plan item).
- The „pobrane” badge cannot match LAZ: Kartograf's LAZ sidecar records no survey work
  (Open questions).
- `tests/unit/test_doctor.py::test_doctor_refused_store_shows_the_fix_the_producer_gave`
  is not hermetic: it fails while 127.0.0.1:8090 is taken.
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

- Kartograf's LAZ tile sidecar records no survey work (`extra` has `tile_sheet`, `year`,
  `nominal_density`, `url`, no `campaign` or `source.survey_work_id`), while the
  availability report names a LAZ combination's campaigns by `nr_zglosz`. A `request`
  issue in Kartograf for `survey_work_id` in the LAZ sidecar is not filed (no `gh` on
  this machine).
- DEV-5.1 lets an `app` keep its layout: confirm the `src/` move of the ADOPTION_PLAN row.
- AGI-6.2 names `/openapi.json`; Archiwista serves `/api/v1/openapi.json` behind the session
  and names operations after route functions (no command catalog). Keep, or move?
- AGI-4.1 asks a top-level `schema` in every machine-readable document; the API responses
  and `--json` outputs have none. Add `archiwista-<kind>/1`, or leave it for the catalog work?
- DEV §18 is profile `tool` only, but ECO-028 says all tools read `nogat.toml`
  (`lang`, `data_dir`, `cache_dir`). Should Archiwista, which uses its own `config.toml` and
  platform directories, read it too?
- The command that marks a store (`kartograf store init --root <path>`) is the `hint` of
  the job error, of the settings problem and of `archiwista doctor`; the status text kept
  for the store (the banner) names the cause only. Should it carry the command too?
- SPEC 13 v0.3 criterion 4 ("every action with the network or a write goes through the plan
  window"): the project card starts re-pin and restore at once, and the project's plan is
  its own action, "Sprawdź aktualizacje" (ADR-042 option I). Should a window built from
  that check stand before them as well (option H)?
- `main` of this repository is not on GitHub: push and make it the default branch (ECO-008).

Open outside this repository:

- Kartograf: the tag waits for the first release set; Archiwista's later versions need
  KA-4, KB-1 to KB-5, KB-7, KC-1 to KC-3, KD-1 to KD-4, KH; KF (merged PL + CZ surface)
  blocks v0.6.
- IMGWTools: the v0.5 adapter treats `missing_sidecar` as a non-critical, possibly
  transient problem; the IMGW actions are planned for v0.5.
- GPU: the measurement of 30 frames per second or more with 5,000 footprints needs hardware
  WebGL; the test account has no access to `/dev/dri/renderD128`.
- Basemap: one default provider (OpenFreeMap) is an availability risk outside offline mode.
- PRD "Open decisions" (the IMGW data format before v0.5, merge results as Kartograf
  products before v0.6, the ČHMÚ adapter) and the mockup questions M6 to M8 and M10
  (SPEC 16; the assistant proposal card for IMGW data is deferred after the MVP).
- The mockup (`mockup/`) is a clickable prototype, not production code; its working data
  directory is outside the repository and can be removed with the author's consent.
