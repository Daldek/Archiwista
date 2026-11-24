# PROGRESS: Archiwista

Current state only (DOC-6.1). Branch, tag and remote state: ask git (`git status`,
`git log --oneline -10`). History: the git log, [CHANGELOG](CHANGELOG.md), the plans'
Results in `docs/plans/` and the ADRs; the Polish session notes that used to live here
are in git (`docs/PROGRESS.md` before the commit that introduced this file).

## Status

The working branch is `chore/pins-candidate-13` (from `develop` `8805a78`, release 0.4.0, which
is merged into `main` and tagged `v0.4.0`): `develop` opens 0.4.1 (`0.4.1.dev0`) with the
producers of Nogat's candidate-13 by commit, not merged until the author approves; every
other branch named below is merged into `develop`.

**Release 0.4.0** is Archiwista's part A1 of Obserwator 3.2.0 (Nogat ECO-084, ECO-085;
A-ADR-059), a minor release with Nogat's standard 1.1 (1.2 is open on Nogat's `develop`, not
released): Obserwator 3.2.0 (extra `obserwator`, tag `v3.2.0`; `SUPPORTED_VERSIONS`
`>=3.2.0,<4`) and Kartograf `v0.8.2`; a version's tier and publication state in the API, the
CLI and the interface (downloads unchanged); ČHMÚ's groundwater stations (kind
`groundwater`, `groundwater_kind` bore or spring, a brown diamond); weekly and hourly series
indexed with their coverage, the monthly slots of an hourly series joined into one series;
no hourly or weekly chart (`400 no_chart`); a series of an unknown unit skipped with
`skipped_series` and one `series_skipped` warning; the index completed in place at schema
version 1. It is deployed before Obserwator 3.2.0 writes captures or hourly series to shared
roots, and a store Obserwator 3.2.0 wrote to first is rebuilt once with `archiwista reindex
--store <store>` (README "Upgrading to 0.4.0", USAGE "Updating to 0.4.0").
`feature/obserwator-3.2.0` is merged into `develop` (`24a43d6`); the release was merged into
`main` and `develop` and tagged `v0.4.0` on 2026-11-23 (Next 15: its deployment).

**Earlier releases**, tagged on `main`: 0.3.0 (2026-11-16, Archiwista's first tag, a member of
the first joint release of the Nogat ecosystem, ECO-074: v0.3 "Actions", v0.4 "Team", the
projects of A-ADR-049 and the built part of v0.5 "IMGW stations"), 0.3.1 (2026-11-18) and
0.3.2 (2026-11-20), defect fixes only, and 0.3.3 (2026-11-22), Archiwista's part of Nogat's
release round of 2026-11-21 (standard 1.1): Obserwator 3.1.0 with the providers' identifiers
`IMGW` and `CHMU`, the providers' strip on one line on a phone, Nogat's kit 1.1.0, the files
Archiwista names as `archiwista_<content>_<qualifiers>.<extension>` (DEV-19.21) and the fix
of Firefox's page errors on leaving a page.

| Component | State | Note |
|---|---|---|
| v0.1 "Browser", v0.2 "Previews" | done | released as 0.1.0 and 0.2.0 on `develop`, not tagged and not merged into `main` (the author's decision); the v0.2 criterion of 30 frames per second with 5,000 footprints is unverified (blocked below) |
| v0.3 "Actions" | done | plan `docs/plans/2026-10-25-archiwista-next.md` Part 3, A1 to A14 (ADR-034 to ADR-044); report `docs/reports/v0.3-measurements.md`; its project actions (A7, A8, A13) are replaced by A-ADR-049. In release 0.3.0; not built: Next 13 |
| v0.4 "Team" | done | plan `docs/plans/2026-10-26-plan-v0.4.md` T1 to T12 (ADR-046, ADR-047); the LAN runbook ran on 2026-10-30 on one machine and on the LAN (SMB 3.1.1 share, TLS, two computers with three people's sessions; a third computer untested; `docs/reports/v0.4-lan-runbook.md`, Next 8). In release 0.3.0 |
| Projects (A-ADR-049 and its errata 1 to 9) | done | `archiwista-project.json` (`archiwista-project/1`) with its area files in `obszary/`; sets („Zestaw”) open or closed with their pins; the jobs verify, check, re-pin and restore; the card's „Przepnij” and „Przywróć brakujące” open the plan window of the set's check (ADR-042 erratum 2); exports in `eksport/<name>/`. In release 0.3.0 |
| Data output (DEV §19, ECO-051) and `nogat.toml` | done | store markers and roots, the producers' default roots offered in the wizard, tests isolated from the producers' settings (ADR-031, ADR-033); `data_dir`, `cache_dir`, `lang` and the table `gui` of `nogat.toml` (A-ADR-053) |
| Obserwator source and station views | done | Obserwator stores indexed, stations, series coverage, the station map, Katalog list, Timeline, card, chart and comparison (ADR-032, ADR-045); monthly charts and annual extremes (A-ADR-051); a station's series handed to Hydrolog through Nogat's kit, with „Dane” and „Zmienna” (A-ADR-052, A-ADR-054) |
| Obserwator's commands and its two roots (A-ADR-050, A-ADR-056) | done | each store names Obserwator's raw root (`obserwator`, `obserwator-store.json`) and its data root (`obserwator_data`, `obserwator-data.json`, read only), each probed by its kind (reason `wrong_root`); Archiwista runs only `store sync` into the raw root. Obserwator's catalog kind `synop` (its daily synoptic data, Obserwator ADR-022) is shown as `synoptic`, „stacja synoptyczna”; its four download-only datasets (ADR-023) are not indexed. Limits: series and station catalogs are built by Obserwator offline, so a project's pins of them are `not_checkable`; Obserwator has no run mode that keeps the stored versions (a restore takes the source's current file); `pmaxtp sync` is not in Archiwista's catalog (A-ADR-050 option C) |
| The providers' lines (A-ADR-055 and its errata 1 to 5) | done | `attribution` and `terms_notice` on every station, map, Katalog, version and comparison answer, the CLI, `ATTRIBUTION.txt` in exports and the hand-off; one compact strip of Nogat's kit per view or overlay, the terms linked, the G and Z lines of station catalogs' sidecars, one CP without the detail of processing (ECO-071); ČHMÚ's origins `chmu_file` and `chmu_processed` (ECO-082). Not in PNG previews (Next 6) |
| Nogat's GUI kit (A-ADR-054 and its errata 1 to 7) | done, in 0.3.3 | kit 1.1.0 of Nogat `4d755ee` in `web/nogat/` (byte for byte, checked against `nogat-kit.json`): the menu „Aplikacje”, the hand-off (saved as `archiwista_handoff_<subject>.json`, ECO-083), the strip `<nogat-sources>` (one line with „więcej” on a phone, Nogat ECO-080, ECO-081), the regulamin's block `chmu` (ECO-082), „Zgłoszenia” on `<nogat-admin-feedback>`; `error_registry.json` of the standard 1.1 (Nogat `975136e`, unchanged in `4d755ee`). |
| User guide `/instrukcja` (A-ADR-048) | done | 13 Polish slides served without a session, „Instrukcja” in the top bar; no link on the sign-in page; its pictures need taking again when the views they show change |
| Nogat standard 1.1 | done | 1.0: structure and tooling (uv, `src/` layout, `scripts/gate.sh`, CI, Dependabot), English documentation, error registry (A-ADR-030); 1.1, in 0.3.3: the providers' identifiers by their national acronyms (DEV-2.5), the files Archiwista names (DEV-19.21), the strip folded on a phone (DEV-20.5), kit 1.1.0 and the error registry of 1.1; 0.4.0 follows 1.1 (1.2 is open on Nogat's `develop`, not released); the items that need the author: Open questions |
| Test server :8090 | done | https://archiwista-test.debever.pl, user unit `archiwista-public.service`, its checkout `<data-dir>/archiwista-public/app` is at `v0.3.1` (`0b66beb`; it ran `7a11c76` of `develop` from 2026-11-15). One store, `agent-tmp` („Magazyn agent-tmp”, kind share), the author's single place for downloaded data (2026-11-15): `kartograf` = `<share>/agent-tmp/hydroni/kartograf` and `obserwator` = `<share>/agent-tmp/obserwator` on the NAS (CIFS), `obserwator_data` = `<data-dir>/obserwator-target/data` on the local disk (processed, served fast). Projects `h07` (4 sets, 2909 pins) and `kaczawa` (Hydrograf :8080's Kaczawa, set `2026-1`, 205 pins) use `agent-tmp`, 0 missing; one known problem (`missing_sidecar` of an `.aux.xml`). State schema 1 and index schema 1 since `1c18fb3`. Backups in `<data-dir>/archiwista-public/backup-2026-11-14-v1/`, rollback steps in `<data-dir>/archiwista-public/backup-2026-11-13/ROLLBACK.txt` |
| Producers' pins | done | on `chore/pins-candidate-13`, for Nogat's candidate-13 (REL-5.3, REL-5.6; A-ADR-024 erratum 3): Kartograf `05052b3a` (`0.9.0.dev0`, `>=0.9.0.dev0,<0.10`) and Obserwator `ffcaa23` (3.2.1 of `hotfix/3.2.1`, extra `obserwator`, `>=3.2.0,<4`) in `pyproject.toml` and `uv.lock`; release 0.4.1 replaces them with the tags `v0.9.0` and `v3.2.1` and narrows Kartograf's range to `>=0.9.0,<0.10`. Release 0.4.0 pinned the tags `v0.8.2` (`>=0.8.0,<0.9`) and `v3.2.0` |
| Obserwator 3.1.0 for Nogat's release round of 2026-11-21 | done, in 0.3.3 | `chore/obserwator-3.1.0`, merged (`58f4c5c`); Obserwator 3.1.0, Kartograf `v0.8.2`; a series version of chosen stations and years (Obserwator ADR-026) is read as any version (`tests/integration/test_obserwator_subset.py`, SPEC 4.8.4), ČHMÚ's snow files and variables (SPEC 4.8.6); Nogat's `handoff-1.schema.json` of `263e83c` (Nogat plan `2026-11-19-hydrolog-0.9.0-consumers.md`, step 6). Full gate passed on `4d42cf7` (3,049 passed, 93.32 %, 3,249 s) |
| Obserwator 3.2.0, Archiwista's A1 (Nogat ECO-084, ECO-085; A-ADR-059) | done, in 0.4.0 | `feature/obserwator-3.2.0`, merged (`24a43d6`): tier and publication of a version (`Version.tier`, `Version.publication`, the CLI's version lines, the badges of the „Katalog” and the file card; downloads unchanged, signed-in people download private versions); ČHMÚ's groundwater stations (`groundwater_kind`, the diamond, the kind filter, the location sources and the variables `H_asl`, `spring_yield`); weekly and hourly series indexed with their coverage (`index/series.py`: the week of its Monday, UTC hours; `join_months` of the monthly slots, `months` in the station and dataset answers, „Miesiące szeregu”); no hourly or weekly chart (`400 no_chart`); `skipped_series` and `series_skipped` for an unknown unit; the index completed in place at schema 1 (`initialize` gives `completed`). Tests: `tests/e2e/test_version_tiers.py`, `tests/e2e/test_groundwater_stations.py`, the fixture store `tests/fixtures/obserwator_tiers.py` (`tiers_store`) |
| Providers' national names and the files Archiwista names (Nogat ECO-082, ECO-083, DEV-2.5, DEV-19.21; A-ADR-032 errata 3 and 4, A-ADR-055 erratum 5) | done, in 0.3.3 | merged into `develop` (`bfd42c8`): the providers `IMGW` and `CHMU`, the keys `cz.chmu.*`, each provider's slugs and store directories `imgw_*` and `chmu_*` (`stations/versions/imgw_stations` beside `chmu_stations`; PMAXTP's product `imgw_pmaxtp`), a station's `location_source` the key of its dataset; old names are neither read nor translated, the index is rebuilt from a data root Obserwator 3.1.0 built; the files Archiwista names for a person are `archiwista_<content>_<qualifiers>.<extension>` (`file_names.py`) |
| Every format at version 1 (Nogat REL-1.4, ECO-072) | done | merged and deployed (`1c18fb3`): the state backup `archiwista-state/1` (a `/2` copy still imports), the job protocol 1, the index schema 1 (an index of another number is rebuilt) and the state schema 1 in one migration (a database numbered 5 is renumbered when it opens; schema 2 to 4 no longer opens) |
| Project files readable by the folder's group (A-ADR-058, finding E2-01 of the scenario test of 2026-11-15) | done | merged as `800231c`: what Archiwista writes in a project's directory takes the folder's permissions instead of `umask 077`; its full gate: 3,025 passed, 2 failed only through TMPDIR in a setgid directory (E7-12, Next 14) |
| Gate | done | 2026-11-23, `feature/obserwator-3.2.0` (0.4.0, Obserwator `v3.2.0`): the full gate passed, 3,132 passed, 93.36 %, 3,293 s. Nogat's `set verify` of candidate-11 (Obserwator `4bf0ce3`) passed; in one of its runs `tests/integration/test_jobs.py::test_worker_logs_warnings_and_errors_as_app_records_and_deletes_nothing` failed once and passed alone 5 of 5 (a race, Next 2). 2026-11-22, `chore/copies-round` (Obserwator `4bf0ce3`): the full gate passed, 3,059 passed, 93.69 %, 4,200 s. 2026-11-22, `chore/round-integration` (`37346f1`, Obserwator `de06926`): the full gate passed, 3,059 passed, 93.69 %, 4,576 s. The gates of its merged branches had failed only under load: `feat/phone-sources-strip` 17 (preview warm-up and `serve` tests, timeouts in a run of 3 h 28 min) and `fix/national-provider-names` 2 (`test_pasted_command.py` offline, `test_jobs.py::test_second_index_job_for_store_conflicts`); each passed alone on the integration branch. |
| CI (Linux) | done | `ci.yml` runs the gate (Python 3.12, the required check, and 3.15), the suite without the extra `obserwator` and a dependency audit; every job passed on `develop` at `1c18fb3`, `7a11c76` and `747ee1f` (2026-11-14 and 2026-11-15). `live.yml` ran once, on its schedule of 2026-11-09 (`90c5ac9`), and passed (Next 9) |
| v0.5 "IMGW stations", the rest | blocked | its built part (the Obserwator source and the station views above) is in release 0.3.0 with Obserwator 3.0.0, in 0.3.3 with Obserwator 3.1.0 and in 0.4.0 with Obserwator 3.2.0; the archive badge of the stations (SPEC 9.2, 4.8.4) and the input archives of the station card need a producer capability the source interface lacks |
| v0.6 "PL + CZ" | blocked | Kartograf KF (merged PL + CZ surface) |
| Producer requirements behind open gaps | blocked | „U źródła” offers only NMT, NMPT and LAZ until Kartograf KD-3/KD-4 (meanwhile paste the producer's command, which „Obszar polecenia” runs on a project's area); plans show „rozmiar nieznany” until Kartograf KH; the „pobrane” badge cannot match LAZ, whose sidecar records no survey work (Kartograf `docs/PROGRESS.md` Next 30); A15 waits for Kartograf KB-7; Archiwista's later versions need KA-4, KB-1 to KB-5, KB-7, KC-1 to KC-3, KD-1 to KD-4, KH |
| GPU measurement (v0.2) | blocked | 30 frames per second or more with 5,000 footprints needs hardware WebGL; the test account has no access to `/dev/dri/renderD128` |

## Next

1. Hydrograf's admin panel cannot re-process from a store; the author moved that fix to the
   release after the first joint release (2026-11-15). Kaczawa's re-processing runs from the
   command line with project `kaczawa`, set `2026-1` (Hydrograf PROGRESS).
2. Flaky tests, for the next release:
   - `tests/integration/test_jobs.py::test_worker_logs_warnings_and_errors_as_app_records_and_deletes_nothing`
     failed once in Nogat's `set verify` of candidate-11 and passed alone 5 of 5: a race, not
     fixed. The earlier inference (the worker's warning „Job … interrupted” written after the
     state `cancelled`) does not hold: the supervisor sets `cancelled` only after
     `process.wait()`, and the worker writes the record synchronously (`os.write`). Likelier
     causes: the interrupt lands outside the runner's `try` in `jobs/worker.py` (about lines
     306–319) when the scan has already finished, or the 30 s `faulthandler` or the killer
     stops a stalled exit. Settling it needs the failing run's job log.
   - Still open in the page: `src/boot.js` loads the page once more when an import fails,
     and Firefox fails the imports of a page being left the same way, so leaving the page
     while its modules load reloads the page it left (probe: `page.goto` fails with
     `NS_BINDING_ABORTED`, a link ends on the old address). When the import fails the page
     cannot tell this from a network change (`pagehide` comes later); it needs a decision.
   - Still open in Chromium: with a network change (`net::ERR_NETWORK_CHANGED`) at 7 s of
     the reproduction of `test_sign_in.py::test_a_temporary_password_is_changed_before_the_shell_opens[chromium]`
     an import neither resolved nor failed in 45 s (no reload, no message); [INFERENCE]
     Chromium left a request pending. A time bound in `boot.js` would cover it, but its
     mechanism is not confirmed.
   - Fixed: `test_map_previews.py::test_year_buttons_select_layer_and_tiles` (the test
     waits for the map to frame the area, 0.3.2), the boot's reload after a failed import
     (`4704325`, 0.3.2), `Tab.settle` waiting for a request Chromium dropped
     (`test_pinning.py`, the fixture forgets the requests of a document left, 0.3.3) and
     Firefox's page errors on leaving a page (`api.js` `readBody`, the shell's stylesheets
     and a card's modules; `test_shell.py::test_loads_the_browser_stops_on_leaving_a_page_raise_no_error_of_the_page`,
     0.3.3); the causes are in the CHANGELOG and the git log.
3. The author decides: „Pobierz CSV” on the station card, through Obserwator's
   `export_series` (CSV with the provider's attribution); today a series leaves as the
   hand-off JSON, the parquet path, or a Python call of `obserwator.export_series`.
4. The author decides: a `request` to Obserwator to keep the precision of an occurrence
   date IMGW-PIB publishes without a day (`2020-03`), which the store keeps as the month's
   first (plan `2026-11-05-monthly-annual-charts.md`, Risks).
5. A welcome dialog for a first visit and its slide in the guide `/instrukcja`; it shows
   the full lines and terms of the data on screen with the kit's `fillSources` (Nogat
   DEV-20.5). Until then the dialog of each view's strip is the only place for them.
6. The providers' lines (A-ADR-055): draw them in PNG previews (DEV-20.5; today they are
   shown only inside views that carry the lines); the regulamin of DEV-15.7 (ECO-061; its
   files are in the kit's copy, but Archiwista serves no `regulamin.html`, as it runs
   without `[nogat.operator]`).
7. A re-pin of a producer to a commit for a coming release round (REL-5.3, REL-5.6): `uv lock
   --offline` resolves a commit only from uv's git database (`~/.cache/uv/git-v1/db/`), so
   fetch the producer's branch into it, change the commit in `pyproject.toml`, `uv lock
   --offline`, `uv sync --locked --all-extras`.
8. The author: the runbook's scenario on a third computer (the LAN run of 2026-10-30 had
   two computers with three people's sessions); a full `scripts/gate.sh` on the Mac; the
   live run of `tests/integration/test_live_actions.py` (`ARCHIWISTA_LIVE_ACTIONS=1`)
   and the SMB run of v0.3 criterion 8.
9. CI: read the weekly `live.yml` runs; without `ARCHIWISTA_LIVE_STORE` and
   `ARCHIWISTA_LIVE_ACTIONS` its store and action tests skip there (Next 8 runs them).
10. Use `kartograf.testing` instead of the hand-made `tests/fixtures/make_store.py` where
    it covers the case (DEV-10.6).
11. Adopt the ecosystem's visual identity (Nogat `design/`, plan
    `docs/plans/2026-11-01-visual-identity.md` in Nogat) once the author approves it, by
    an Archiwista plan.
12. AGI-4.1: a top-level `schema` (`archiwista-<kind>/1`) in every API response and
    `--json` output, added with the catalog work (the author's decision of 2026-11-09);
    until then the deviation of `CLAUDE.md` (AGI-3.2, AGI-4.1, AGI-4.2) stands.
13. Known gaps of Archiwista: v0.3's units colouring on the map (A12, M7) is not built;
    "one job per row" options B (a sheet list in Kartograf's hint) and D (a longer
    `PLAN_REFRESH_TTL_S`) are open; a variant without a default format and a plan with
    conflicts are untested in the browser (the stand-in has neither). Availability rows:
    the badge does not tell height systems apart; a LAZ variant has no default format and
    no size (ADR-017 names ASC and GeoTIFF); the row details of SPEC 6.4 are not built.
    „Pokaż wynik na mapie” does not carry the Katalog's „Wariant” filter. The project
    card follows a job it started or the one a `409` names, not a job of the project
    started elsewhere. A map layer pins at most 500 versions. The white rectangle over
    the map that the author reported was not reproduced.
14. Known problems from Nogat's integration run of candidate-5 and the scenario test of
    2026-11-15 and 2026-11-16 on the Barycz and the Bóbr (its report's section 4; "§6 B3"
    names a row of its section 6), open after 0.4.0. Fixed: C2, C6, E2-06 and E7-01 in 0.3.1;
    E3-05, E7-12, G01-1 and §6 B1 in 0.3.2, and E7-03 documented there (USAGE mounts an
    encrypted SMB share with `rsize=wsize=1048576`; this computer's `/etc/fstab` still mounts
    `agent-tmp` with the default, the author's change); the CHANGELOG has each.
    - C3: `tests/e2e/test_station_chart.py::test_an_incomplete_year_is_a_hollow_dot_whose_tooltip_names_the_missing_half[firefox]`
      and `tests/e2e/test_stations_map.py::test_legend_counter_and_chips_stand_beside_the_map[firefox]`
      crash the page with Playwright 1.65.2 and Firefox 159, the set's version; they pass with
      the Playwright 1.64.0 of Archiwista's lock. The cause is no feature of the page (not the
      tooltip, a CSS rule or the map's canvas, which headless Firefox does not draw): Playwright
      1.65 names an element by its `aria-labelledby` through `ariaLabelledByElements`, and
      Firefox 159 crashes when an element named so in Playwright's own world is named again in
      the page's world (`evaluate_all` or `all_inner_texts` under a `get_by_role(name=...)`; a
      page of one `<section role="dialog" aria-labelledby>` crashes too). The pages pass once
      each `aria-labelledby` is an `aria-label`, but that is no small change: 50 in the
      interface, two of them in Nogat's kit, whose files are checked by their SHA-256. Marked
      known in 0.3.1: the two `[firefox]` cases are a strict `xfail` under Playwright
      1.65.2 (`FIREFOX_KNOWN_CRASH`, `tests/fixtures/browser.py`).
    - E2-05: an area's `countries` come from its bounding box, so a PL-only and a CZ-only
      area both get `["CZ","PL"]`. Not a defect of Archiwista: Kartograf's
      `countries_for_bbox` compares rectangular envelopes, which overlap along the whole PL–CZ
      border, so Archiwista waits for a Kartograf function giving the countries of a geometry by
      their real borders.
    - E2-07 (with Nogat, §6 B7): `archiwista-project/1` has no JSON Schema; only Hydrograf's
      reader validates the file.
    - E2-10 = G08-1: an export (567 pins, 2.8 GB) is one synchronous request of about
      3.5 min; the interface shows neither its size nor its progress.
    - E5a-03: no `GET /projects/{p}/groups/{g}` (405); a set is only in the project card.
    - ENV-01: `archiwista doctor` checks the port on `127.0.0.1` only and has no `--host`.
    - G08-2 (§6 C3): an export's `README.txt` and `ATTRIBUTION.txt` cannot be opened from the
      interface.
    - With Kartograf: E7-02 (§6 B3; a download from a good plan fails whole when PRG's WFS is
      down, and a `partial` run pins nothing), E7-04 (§6 B3; one team's jobs on overlapping
      positions end `partial` with nothing pinned), E2-03 (§6 B2, with Hydrograf; a plan over a
      project's area takes the BDOT10k counties of the area, Hydrograf needs those of the
      sheet mosaic), E2-04 = G08-3 (§6 C1; legacy ASCII lines in the export's
      `ATTRIBUTION.txt`, the version card and the sidecars, not the DEV §20 lines),
      E2-09 = G04-1 (the plan has no size; an unverifiable item shows "do pobrania 0"),
      E2-08 = E7-05 (`unverifiable` positions are downloaded again in one call, not in
      another), E2-02-A = E2-02-C = E7-06 (§6 B2; `no_coverage_some` lists 10 codes and "…", and
      the plan window cannot fill NMT 5 m gaps with 1 m).
    - With Obserwator: E3-02 (synoptic and climate term data are not in Obserwator's store;
      Archiwista refuses them with 400).
15. Release 0.4.0 (A-ADR-059) is merged and tagged `v0.4.0`. Deploy it on a shared store
    before Obserwator 3.2.0 writes captures or hourly series there (ECO-085; the test
    server's `agent-tmp`, which runs `v0.3.1`), and run `archiwista reindex --store <store>`
    once if Obserwator 3.2.0 wrote there first: USAGE, "Updating to 0.4.0".
16. Release 0.4.1 for Nogat's candidate-13: `chore/pins-candidate-13` (Kartograf `05052b3a`,
    Obserwator `ffcaa23`, `0.4.1.dev0`) is merged into `develop` with the author's approval;
    once Kartograf `v0.9.0` and Obserwator `v3.2.1` are tagged, the release pull request pins
    the tags and narrows Kartograf's range to `>=0.9.0,<0.10` (REL-2.1, REL-5.6).

## Open questions

Decisions awaiting the author:

- The providers' lines (A-ADR-055), choices made by the agents: the guide gained a slide
  (13, not 12) because a card could not hold the terms notice then (it no longer quotes N,
  ECO-065); the Katalog's paged station list merges its lines in the browser, so their
  order can slip across pages (every line is still in the strip's dialog).
- GitHub settings (DEV-3.6, DEV-13.6, DEV-13.7, ECO-008): rulesets for `main`, `develop`
  and `v*` tags, private vulnerability reporting, Dependabot security updates, `main` made
  the default branch. `main` is on GitHub at the root commit `5578983` (0.2.0 is not
  merged into it, the author's decision); the default branch is still `develop`. The
  required check is the one job `gate (ubuntu-latest, Python 3.12)`.
- `docs/CLA.md` text and signing mechanism: the author's legal text says "comment on the
  pull request", while DEV-16.5 says checkbox plus a line in `CONTRIBUTORS.md` in the same
  pull request.
- `Approved:` lines of the executed plans v0.1 and v0.2 (DEV-17.4): approval is the
  author's statement.
- PyPI name `nogat-archiwista` and publishing (adoption phases 5 and 6); the tag `v0.3.0`
  and the pins by tags are decided (Status: releases 0.3.0 to 0.4.0).
- Basemap: one default provider (OpenFreeMap) is an availability risk outside offline mode.
- PRD "Open decisions" (merge results as Kartograf products before v0.6, the ČHMÚ
  adapter) and the mockup questions M6 to M8 and M10 (SPEC 16; the assistant proposal
  card for IMGW data is deferred after the MVP).
- The mockup (`mockup/`) is a clickable prototype, not production code; its working data
  directory outside the repository stays until the author decides: the consent of
  2026-11-09 was for the branch `feat/mockup` only.
- Obserwator 3.1.0's series of chosen stations and years (ADR-026): Archiwista reads such a
  version as any other (the years not chosen unknown, the stations not chosen without the
  dataset's series) but does not say that the version is a subset. Showing it (the
  `subset` of `series.json` in `SeriesListing`, `GET /stations/datasets` and the card,
  e.g. „wersja częściowa: 12 stacji, lata 2020–2024”) changes the source interface and
  the API, so it needs a plan the author approves (DEV-17.4).
- Private versions (Obserwator ADR-030 D5, Nogat ECO-084): 0.4.0 shows a version's tier and
  publication state and leaves the downloads as they were, so every signed-in person may
  download a private version (the coordinator's ruling). ECO-084's „honours `private` in its
  downloads in a later minor” is for a future public view without sign-in, which needs a
  plan the author approves.
- Hourly series in the labels of SPEC 4.8.4: a year is known only when all its units are,
  so the label of an hourly series whose months do not fill a year is „nieznane” (the card
  still gives its first and last values and its gaps in UTC hours). Whether such a series
  should be labelled over its known months instead is the author's decision.
