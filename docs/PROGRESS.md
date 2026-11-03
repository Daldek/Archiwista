# PROGRESS: Archiwista

Current state only (DOC-6.1). Branch, tag and remote state: ask git (`git status`,
`git log --oneline -10`). History: the git log, [CHANGELOG](CHANGELOG.md), the plans'
Results in `docs/plans/` and the ADRs; the Polish session notes that used to live here
are in git (`docs/PROGRESS.md` before the commit that introduced this file).

## Status

The working branch is `develop`. On 2026-11-03 `feature/archiwista-projects` (`10dd702`,
which holds Nogat standard 2.1, the IMGWTools source and station views, the data output,
v0.3, v0.4, the user guide and the projects) and `plan/next-version` were merged into it
(`6f1caef`, `7b3eb79`; no pull request, the author's decision) and the merged branches
deleted; `feat/mockup` stays (Open questions). The author's team test server (port 8090,
https://archiwista-test.debever.pl) runs `4027755` (in `develop`) since 2026-11-03 about
00:00 (step A3 of Nogat's plan `2026-11-02-archiwista-sets-for-hydrograf.md`), with
`TMPDIR` on disk. Nothing after 0.2.0 is released.

| Component | State | Note |
|---|---|---|
| Projects in Archiwista's own file (A-ADR-049 and its errata 1 to 4; Nogat plan `2026-10-31-archiwista-projects.md` step 5, ECO-054; plan `docs/plans/2026-10-31-archiwista-projects.md`) | done, in `develop`, deployed on the test server | A project is a directory holding `archiwista-project.json` (`archiwista-project/1`; lock and atomic write; discovery by that file alone; index schema 16, state schema 4), its area files in `obszary/`. Groups, shown as „Zestaw”, hold pins: from the store (Katalog, map, store view: "Dodaj do projektu…"; a filter or a map layer pins the versions it shows) and from the plan window (a plan group keeps the producer's calls). Jobs verify, check, re-pin and restore over `POST /projects/{project}/jobs` (`PROTOCOL_VERSION` 13), rebuilt from Kartograf's `command_for_file` and IMGWTools' `command_for_version`; a pin without a rebuildable command stays pinnable with check and restore disabled with the reason (D5). The card shows the activity from the action log. "Usuń projekt…" removes a project from Archiwista, never data (erratum 2). The export is flat: `eksport/<name>/` with one folder per category (`NMT`, `BDOT`, `ORTO`, …), copies of the files and `README.txt`, optionally `eksport/<name>.zip` (erratum 1); a ZIP holding exactly one raster is exported unpacked, an XYZ file with the coordinate system to set in QGIS (erratum 4). The producers' project manifests and ADR-039/ADR-040 are gone. Pins: Kartograf `26ee4592`, IMGWTools `4bf8bb0d` (the pushed heads of their `feature/archiwista-projects`) |
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
| IMGWTools source and station views | done, in `develop` | plan `docs/plans/2026-10-25-archiwista-next.md` Parts 2 and 4 (ADR-032, ADR-045): IMGW stores indexed, stations, series coverage, the station map, Katalog list, Timeline, card, chart and comparison |
| Data output (DEV §19, ECO-051) | done, in `develop` | plan `docs/plans/2026-10-25-archiwista-next.md` Part 1 (ADR-031, ADR-033): store markers, store roots, the producers' default roots offered in the wizard, tests isolated from the producers' settings |
| Release 0.2.0 "Previews" | done | released on `develop`, not tagged and not merged into `main` (author's decision) |
| Nogat standard 2.1 | done | structure and tooling (uv, `src/` layout, `scripts/gate.sh`, CI, Dependabot), English documentation, error registry; skipped items below |
| Deploy on the test server (A3) | done 2026-11-03 about 00:00 | `4027755` on :8090, `Environment=TMPDIR=<data-dir>/tmp` in the unit (Kartograf unpacks BDOT10k there; `/tmp` is a small tmpfs). The index was rebuilt from schema 16 to 17, which dropped the sessions (everyone signs in again), the job history and the 18 drawn rectangles of the map. Copies taken before the restart (index 16, state 4, the old unit) and the rollback to `dd4268c`: `/home/claude-agent/data/archiwista-public/backup-2026-11-02/` and its `ROLLBACK.txt` |
| Gate | green on the A2 tree (2026-11-02, about 23:30) | full run: 2749 passed, `TMPDIR` on a local disk, the author's test server holding port 8090. `develop` after the merge has the tree of `10dd702`, which differs from the gated one in `docs/PROGRESS.md` only. The Firefox run of `tests/e2e/test_guide.py` no longer stalls it (`8d16cef`): the test resized the app's tab behind the guide's tab, and `set_viewport_size` waits without a timeout for a size Firefox may never give a covered tab. A full run takes about 50 to 60 minutes; start it without other test suites running |
| CI (Linux) | written, not run | `.github/workflows/ci.yml` and `live.yml`; no run of either workflow is known |

Skipped adoption items, which need the author (DEV-3.3, ADOPTION_PLAN):

| Item | Why |
|---|---|
| History rewrite (phase 1) | Archiwista needs only DEV-4.2: every commit is by `Daldek <git@debever.pl>` and has no AI trailer |
| Rulesets for `main`, `develop` and `v*` tags, private vulnerability reporting, Dependabot security updates, `main` pushed and made the default branch (DEV-3.6, DEV-13.6, DEV-13.7, ECO-008) | GitHub settings. The required check is the one job `gate (ubuntu-latest, Python 3.12)` (CI runs on Linux only) |
| `docs/CLA.md` text and signing mechanism | the author's legal text: it says "comment on the pull request", while DEV-16.5 says checkbox plus a line in `CONTRIBUTORS.md` in the same pull request |
| `Approved:` lines of the executed plans v0.1 and v0.2 (DEV-17.4) | approval is the author's statement |
| Tags, releases, replacing the producers' commit pins by tags, PyPI name `nogat-archiwista` (phases 5 and 6) | need the producers' tags and the author's approval |

## Next

1. The author: sign in again on :8090 (the rebuild dropped the sessions). Optionally
   restore the 18 drawn rectangles from the backup's `index.sqlite` (schema 16).
2. A welcome dialog for a first visit and its slide in the guide `/instrukcja`.
3. Release preparation (the author): `archiwista-state/2` back to `/1` (a format
   identifier not yet released on `main` stays at `/1`), then the release below.
4. Release, per decisions D2 and D3 of Nogat's plan
   `2026-10-31-archiwista-projects.md`: one Archiwista release holds v0.3, v0.4 and the
   projects (all in `develop` since 2026-11-03), outside the first release set
   (Archiwista follows the producers' tags in its own session, REL-5.4). Then: replace
   the commit pins by the producers' tags (REL-5.3, REL-2.1), CHANGELOG version and tag
   with the author's approval, the Nogat registry (the edge Archiwista → IMGWTools is
   still `planned`). Re-pin first if a producer commits on its branch again: `uv lock
   --offline` resolves a commit only from uv's git database
   (`~/.cache/uv/git-v1/db/`), so fetch the producer's branch into it, change the commit
   in `pyproject.toml`, `uv lock --offline`, `uv sync --locked --all-extras`.
5. The author: the runbook's three-computer SMB/TLS scenario on a Linux server (CA trust
   in three browsers, the store on the share); a full `scripts/gate.sh` on the Mac; the
   live run of `tests/integration/test_live_actions.py` (`ARCHIWISTA_LIVE_ACTIONS=1`)
   and the SMB run of v0.3 criterion 8.
6. CI proof after the push: the Chromium step of `ci.yml` and the weekly `live.yml`.
7. Use `kartograf.testing` instead of the hand-made `tests/fixtures/make_store.py` where
   it covers the case (DEV-10.6).
8. Adopt the ecosystem's visual identity (Nogat `design/`, plan
   `docs/plans/2026-11-01-visual-identity.md` in Nogat) once the author approves it, by
   an Archiwista plan.

Known gaps:

- „U źródła” offers only NMT, NMPT and LAZ until Kartograf KD-3/KD-4 (availability of
  orthophoto, BDOT10k and unit products); meanwhile paste the producer's command
  („Wklej polecenie producenta”), which „Obszar polecenia” now runs on a project's area.
- Plans show „rozmiar nieznany” until Kartograf KH (the size of a plan item).
- The „pobrane” badge cannot match LAZ: Kartograf's LAZ sidecar records no survey work
  (Open questions).
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
- `feat/mockup` (pushed, six commits of 2026-10-17): the first clickable mockup, superseded
  by `fb4268d` in `develop` (`mockup/`); its commits are in no other branch. Delete it?

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
