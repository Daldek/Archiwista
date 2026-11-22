# PROGRESS: Archiwista

Current state only (DOC-6.1). Branch, tag and remote state: ask git (`git status`,
`git log --oneline -10`). History: the git log, [CHANGELOG](CHANGELOG.md), the plans'
Results in `docs/plans/` and the ADRs; the Polish session notes that used to live here
are in git (`docs/PROGRESS.md` before the commit that introduced this file).

## Status

The working branch is `develop`; every branch named below is merged into it. Release 0.3.0
is tagged `v0.3.0` on `main`.

**Release 0.3.0 is closed** (the author, 2026-11-16): Archiwista's first tag, a member of
the first joint release of the Nogat ecosystem (Nogat release set candidate-6; ECO-074). It
holds what `develop` held: v0.3 "Actions", v0.4 "Team", the projects (A-ADR-049) and the
built part of v0.5 "IMGW stations" (decision D2 of Nogat's plan
`2026-10-31-archiwista-projects.md`).

**Release 0.3.1** (the author's approval of 2026-11-17: defect fixes only) is prepared on
`fix/0.3.1` from `develop` `a61412c`, at `0.3.1.dev0`; it is not merged until the author
approves. Its items: the known defects of Next 14 named there as fixed in 0.3.1.

| Component | State | Note |
|---|---|---|
| v0.1 "Browser", v0.2 "Previews" | done | released as 0.1.0 and 0.2.0 on `develop`, not tagged and not merged into `main` (the author's decision); the v0.2 criterion of 30 frames per second with 5,000 footprints is unverified (blocked below) |
| v0.3 "Actions" | done | plan `docs/plans/2026-10-25-archiwista-next.md` Part 3, A1 to A14 (ADR-034 to ADR-044); report `docs/reports/v0.3-measurements.md`; its project actions (A7, A8, A13) are replaced by A-ADR-049. In release 0.3.0; not built: Next 13 |
| v0.4 "Team" | done | plan `docs/plans/2026-10-26-plan-v0.4.md` T1 to T12 (ADR-046, ADR-047); the LAN runbook ran on 2026-10-30 on one machine and on the LAN (SMB 3.1.1 share, TLS, two computers with three people's sessions; a third computer untested; `docs/reports/v0.4-lan-runbook.md`, Next 8). In release 0.3.0 |
| Projects (A-ADR-049 and its errata 1 to 7) | done | `archiwista-project.json` (`archiwista-project/1`) with its area files in `obszary/`; sets („Zestaw”) open or closed with their pins; the jobs verify, check, re-pin and restore; the card's „Przepnij” and „Przywróć brakujące” open the plan window of the set's check (ADR-042 erratum 2); exports in `eksport/<name>/`. In release 0.3.0 |
| Data output (DEV §19, ECO-051) and `nogat.toml` | done | store markers and roots, the producers' default roots offered in the wizard, tests isolated from the producers' settings (ADR-031, ADR-033); `data_dir`, `cache_dir`, `lang` and the table `gui` of `nogat.toml` (A-ADR-053) |
| Obserwator source and station views | done | Obserwator stores indexed, stations, series coverage, the station map, Katalog list, Timeline, card, chart and comparison (ADR-032, ADR-045); monthly charts and annual extremes (A-ADR-051); a station's series handed to Hydrolog through Nogat's kit, with „Dane” and „Zmienna” (A-ADR-052, A-ADR-054) |
| Obserwator's commands and its two roots (A-ADR-050, A-ADR-056; Obserwator pin `3816b3c`) | done | each store names Obserwator's raw root (`obserwator`, `obserwator-store.json`) and its data root (`obserwator_data`, `obserwator-data.json`, read only), each probed by its kind (reason `wrong_root`); Archiwista runs only `store sync` into the raw root. Obserwator's catalog kind `synop` (its daily synoptic data, Obserwator ADR-022) is shown as `synoptic`, „stacja synoptyczna”; its four download-only datasets (ADR-023) are not indexed. Limits: series and station catalogs are built by Obserwator offline, so a project's pins of them are `not_checkable`; Obserwator has no run mode that keeps the stored versions (a restore takes the source's current file); `pmaxtp sync` is not in Archiwista's catalog (A-ADR-050 option C) |
| The providers' lines (A-ADR-055 and its errata 1 to 4) | done | `attribution` and `terms_notice` on every station, map, Katalog, version and comparison answer, the CLI, `ATTRIBUTION.txt` in exports and the hand-off; one compact strip of Nogat's kit per view or overlay, the terms linked, the G and Z lines of station catalogs' sidecars, one CP without the detail of processing (ECO-071). Not in PNG previews (Next 6) |
| Nogat's GUI kit (A-ADR-054 and its errata 1 to 5) | done | kit 1.1.0 in `web/nogat/`, its files of Nogat `5f8cce0` and its manifest of `0e128be` (byte for byte, checked against `nogat-kit.json`): the menu „Aplikacje”, the hand-off, the strip `<nogat-sources>` (one line with „więcej” on a phone, Nogat ECO-080, ECO-081; branch `feat/phone-sources-strip`, step 4 of Nogat's plan `2026-11-21-phone-sources-strip`, not merged, with `error_registry.json` of Nogat `975136e`), „Zgłoszenia” on `<nogat-admin-feedback>` |
| User guide `/instrukcja` (A-ADR-048) | done | 13 Polish slides served without a session, „Instrukcja” in the top bar; no link on the sign-in page; its pictures need taking again when the views they show change |
| Nogat standard 1.0 | done | structure and tooling (uv, `src/` layout, `scripts/gate.sh`, CI, Dependabot), English documentation, error registry (A-ADR-030); the items that need the author: Open questions |
| Test server :8090 | done | https://archiwista-test.debever.pl, user unit `archiwista-public.service`, runs `7a11c76` (`develop`) since 2026-11-15. One store, `agent-tmp` („Magazyn agent-tmp”, kind share), the author's single place for downloaded data (2026-11-15): `kartograf` = `<share>/agent-tmp/hydroni/kartograf` and `obserwator` = `<share>/agent-tmp/obserwator` on the NAS (CIFS), `obserwator_data` = `<data-dir>/obserwator-target/data` on the local disk (processed, served fast). Projects `h07` (4 sets, 2909 pins) and `kaczawa` (Hydrograf :8080's Kaczawa, set `2026-1`, 205 pins) use `agent-tmp`, 0 missing; one known problem (`missing_sidecar` of an `.aux.xml`). State schema 1 and index schema 1 since `1c18fb3`. Backups in `<data-dir>/archiwista-public/backup-2026-11-14-v1/`, rollback steps in `<data-dir>/archiwista-public/backup-2026-11-13/ROLLBACK.txt` |
| Pins of Nogat's release set candidate-5 | done | Kartograf `e14bc78`, Obserwator `f4f6a8d` (Next 7) |
| Obserwator 3.1.0 for Nogat's release round of 2026-11-21 | done | `chore/obserwator-3.1.0`, not merged: Obserwator pinned to `1a11df5` (`3.1.0.dev0`), Kartograf stays `v0.8.2`; a series version of chosen stations and years (Obserwator ADR-026) is read as any version (`tests/integration/test_obserwator_subset.py`, SPEC 4.8.4), ČHMÚ's snow files and variables (SPEC 4.8.6); Nogat's `handoff-1.schema.json` of `263e83c` (Nogat plan `2026-11-19-hydrolog-0.9.0-consumers.md`, step 6). Full gate passed on `4d42cf7` (3,049 passed, 93.32 %, 3,249 s). The version number and Nogat's kit copy wait for the coordinator |
| Every format at version 1 (Nogat REL-1.4, ECO-072) | done | merged and deployed (`1c18fb3`): the state backup `archiwista-state/1` (a `/2` copy still imports), the job protocol 1, the index schema 1 (an index of another number is rebuilt) and the state schema 1 in one migration (a database numbered 5 is renumbered when it opens; schema 2 to 4 no longer opens) |
| Project files readable by the folder's group (A-ADR-058, finding E2-01 of the scenario test of 2026-11-15) | done | merged as `800231c`: what Archiwista writes in a project's directory takes the folder's permissions instead of `umask 077`; its full gate: 3,025 passed, 2 failed only through TMPDIR in a setgid directory (E7-12, Next 14) |
| Gate | done | 2026-11-16, Nogat's integration run of candidate-5 (`800231c`): on Archiwista's own lock 3,026 passed, 1 failed (C2), 93.77 %, 4,464 s; in the candidate's environment 3,024 passed, 3 failed (C2, C3); both in Next 14. 2026-11-15: the full gate passed on `chore/pins-candidate-5` (`4f37655`, 4885 s; merged as `e534b40`); on `docs/session-2026-11-15` one e2e test, `test_map_previews.py::test_year_buttons_select_layer_and_tiles`, failed under load and passed alone three times (Next 2) |
| CI (Linux) | done | `ci.yml` runs the gate (Python 3.12, the required check, and 3.15), the suite without the extra `obserwator` and a dependency audit; every job passed on `develop` at `1c18fb3`, `7a11c76` and `747ee1f` (2026-11-14 and 2026-11-15). `live.yml` ran once, on its schedule of 2026-11-09 (`90c5ac9`), and passed (Next 9) |
| v0.5 "IMGW stations", the rest | blocked | its built part (the Obserwator source and the station views above) is in release 0.3.0 with Obserwator `v3.0.0`; the archive badge of the stations (SPEC 9.2, 4.8.4) and the input archives of the station card need a producer capability the source interface lacks |
| v0.6 "PL + CZ" | blocked | Kartograf KF (merged PL + CZ surface) |
| Producer requirements behind open gaps | blocked | „U źródła” offers only NMT, NMPT and LAZ until Kartograf KD-3/KD-4 (meanwhile paste the producer's command, which „Obszar polecenia” runs on a project's area); plans show „rozmiar nieznany” until Kartograf KH; the „pobrane” badge cannot match LAZ, whose sidecar records no survey work (Kartograf `docs/PROGRESS.md` Next 30); A15 waits for Kartograf KB-7; Archiwista's later versions need KA-4, KB-1 to KB-5, KB-7, KC-1 to KC-3, KD-1 to KD-4, KH |
| GPU measurement (v0.2) | blocked | 30 frames per second or more with 5,000 footprints needs hardware WebGL; the test account has no access to `/dev/dri/renderD128` |

## Next

1. Hydrograf's admin panel cannot re-process from a store; the author moved that fix to the
   release after the first joint release (2026-11-15). Kaczawa's re-processing runs from the
   command line with project `kaczawa`, set `2026-1` (Hydrograf PROGRESS).
2. Flaky e2e tests, causes found (`fix/flaky-e2e`, for 0.3.2):
   - `tests/e2e/test_map_previews.py::test_year_buttons_select_layer_and_tiles` (gate of
     2026-11-15) read the outline count before the map framed the area (the home view's 16,
     not the area's 11) when the area's answer came late. Fixed in the test (`54f9ba5`): it
     waits until the address's centre lies in the area.
   - `tests/e2e/test_pinning.py::test_an_older_version_pinned_from_the_file_card_is_unpinned_on_the_card[chromium]`
     (CI of `develop` `58f4c5c`, 2026-11-21; older than the Obserwator 3.1.0 pin, which
     changes no interface code): „the page did not settle” on a `/map/footprints` request of
     the start view, still in flight when the test opened the Katalog. Chromium drops such a
     request and Playwright never reports its end, so `Tab.settle` waited for it in vain
     (locally 3 of 30 runs failed, 4 of 30 under CPU load). Fixed in the fixture
     (`fix/ci-2026-11-21`): `Tab` forgets the requests of a document when the next one
     commits (30 of 30 runs, idle and under load).
   - `tests/e2e/test_preferences.py::test_the_basemap_and_the_year_type_follow_a_person_not_a_colleague[firefox]`
     (CI of `develop` `9e9e365`, 2026-11-21): a page error „The operation was aborted.” of
     the downloads' discovery in a page the test left. Firefox stops the loads of a page
     being left before `pagehide` and still runs the page's handlers (a probe page: a
     request still waiting rejects with a `TypeError`, a body being read with `AbortError`,
     a stylesheet fires `error`, an import rejects); the shell's readers (the downloads, the
     count of running jobs) rethrew the `AbortError` as a fault of the page, and the
     stylesheets the shell adds after it is shown and a card's modules rejected unhandled
     („Stylesheet not loaded”). Not the map: MapLibre's loads end in its `error` event, and
     `map.remove()` on `pagehide` would come after the handlers ran. Locally 1 of 140 runs of
     the test (1 of 40 idle, 0 of 40 under CPU load, 0 of 60 idle) and 1 of 180 rounds of
     its steps. Fixed in the page (`fix/map-teardown`): `api.js` reads every body through
     `readBody` (a body that does not come whole is the network's problem unless the
     caller's signal stopped it), and those stylesheets and a card's modules that do not
     load leave the part unstyled or the card unshown.
     `tests/e2e/test_shell.py::test_loads_the_browser_stops_on_leaving_a_page_raise_no_error_of_the_page`
     makes both happen in Chromium and Firefox: it fails without the fix (the CI's „The
     operation was aborted.” and „Stylesheet not loaded”) and passed 20 of 20 runs with it
     idle and 20 of 20 under CPU load. With the fix the CI's test and
     `test_project_card.py::test_verify_runs_offline_and_marks_each_pin_while_network_jobs_say_why[firefox]`
     (its „Stylesheet not loaded”, 1 in 55 local runs, is [INFERENCE] one of those
     stylesheets; 0 of 80 runs reproduced it before) passed 80 of 80 runs idle and 80 of 80
     under CPU load.
     Still open: `src/boot.js` loads the page once more when an import fails, and Firefox
     fails the imports of a page being left the same way, so leaving the page while its
     modules load reloads the page it left (probe: `page.goto` fails with
     `NS_BINDING_ABORTED`, a link ends on the old address). When the import fails the page
     cannot tell this from a network change (`pagehide` comes later); it needs a decision.
   - `tests/e2e/test_sign_in.py::test_a_temporary_password_is_changed_before_the_shell_opens[chromium]`
     (gate of 2026-11-10): a network change on the computer (a Docker veth, Tailscale) makes
     Chromium cancel the queued module requests of the boot (`net::ERR_NETWORK_CHANGED`), and
     the interface stayed on its spinner. Fixed in the page (`4704325`): `src/boot.js` loads
     `main.js`, reloads once after a failed import, then shows „Nie udało się wczytać
     Archiwisty.” with „Wczytaj ponownie”. Reproduced in a private network namespace.
     Still open: with the event at 7 s of the reproduction the import neither resolved nor
     failed in 45 s (no reload, no message); [INFERENCE] Chromium left a request pending. A
     time bound in `boot.js` would cover it, but its mechanism is not confirmed.
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
7. Release 0.3.0 (closed, Status): the coordinator re-pins Kartograf and Obserwator to the
   commits of Nogat's release set candidate-6 (REL-5.4), then makes the release commit
   (version `0.3.0`, CHANGELOG heading, `uv.lock`, the pins replaced by the tags `v0.8.0` and
   `v3.0.0`, the ranges narrowed), merges `develop` into `main` and tags `v0.3.0`. After the
   tag: the Nogat registry (the edge Archiwista → Obserwator is still `planned`). A re-pin to
   a commit: `uv lock --offline` resolves a commit only from uv's git database
   (`~/.cache/uv/git-v1/db/`), so fetch the producer's branch into it, change the commit
   in `pyproject.toml`, `uv lock --offline`, `uv sync --locked --all-extras`.
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
14. Deferred to the next release (the author's decision of 2026-11-16): the known failures C2,
    C3 and C6 of Nogat's integration run of candidate-5 and the findings of the scenario test
    of 2026-11-15 and 2026-11-16 on the Barycz and the Bóbr (its report's section 4; "§6 B3"
    names a row of its section 6):
    - C2: `tests/integration/test_projects_api.py::test_a_project_the_server_writes_is_readable_by_its_folders_group`
      depended on the process umask: only `cli.main` sets `umask 077` (`cli.py:141`), and the
      test's index was made before it set one, so under umask 022 `index.sqlite` got `0644`.
      Fixed on `fix/0.3.1`: its installation is made under `umask 077`.
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
      known on `fix/0.3.1`: the two `[firefox]` cases are a strict `xfail` under Playwright
      1.65.2 (`FIREFOX_KNOWN_CRASH`, `tests/fixtures/browser.py`).
    - C6: `tests/integration/test_render_pool.py::test_unreadable_cached_as_code_and_timeout_not_cached` hit its 1 s
      `PreviewTimeoutError` once under load: the limit also covered the start of the render
      process. Fixed on `fix/0.3.1`: only the slow file's requests have the 1 s limit, also in
      `test_retry_passes_over_cached_verdict_and_remembered_timeout`, which failed the same way.
    - E2-05: an area's `countries` come from its bounding box, so a PL-only and a CZ-only
      area both get `["CZ","PL"]`. Not a defect of Archiwista to fix in 0.3.1: Kartograf's
      `countries_for_bbox` compares rectangular envelopes, which overlap along the whole PL–CZ
      border, so Archiwista waits for a Kartograf function giving the countries of a geometry by
      their real borders.
    - E2-06: `archiwista jobs list` during a scan ended with exit 8 `store_unavailable`
      ("database is locked"), a wrong message for a read. Fixed on `fix/0.3.1`: the command's
      supervisor leaves its upkeep (pruning, stores, recovery) for later while the index is
      busy, and a read that cannot open the jobs says „Nie można odczytać zadań”.
    - E2-07 (with Nogat, §6 B7): `archiwista-project/1` has no JSON Schema; only Hydrograf's
      reader validates the file.
    - E2-10 = G08-1: an export (567 pins, 2.8 GB) is one synchronous request of about
      3.5 min; the interface shows neither its size nor its progress.
    - E3-05 (§6 B6): the daily hand-off started at 1950-11-01 (7,305 `null` days), not at the
      variable's values; the annual one had 20 empty years. Fixed on `fix/handoff-range`
      (`86ea01a`, ADR-052 erratum 4): without `from`/`to` a daily hand-off runs from the
      variable's first value to its last, an annual one from the first to the last year with
      a maximum (Łąki Q: 1970-11-01 to 2025-10-31, as Obserwator's GUI hands it off).
    - E5a-03: no `GET /projects/{p}/groups/{g}` (405); a set is only in the project card.
    - E7-01 (§6 A5): `PUT /projects/{p}/area` with a closed set answered 200: the area changed
      and the set stayed `digest_state: ok`. Fixed on `fix/0.3.1` (A-ADR-049 erratum 9): another
      area or none is `409 set_closed` while the project holds a closed set. The other option of
      §6 A5, the area in a set's identity (several parts in one project), is a format change
      left to the author.
    - E7-03: two downloads at once ended one BDOT10k call with `Errno 12 ENOMEM`. Not the
      cgroup's page cache: `close()` of the file Kartograf copied into the store on the SMB
      share failed, because the kernel's CIFS client could not get an order-4 buffer to
      encrypt a 4 MiB write (`seal`, default `rsize`/`wsize`; kernel log of
      2026-11-15T22:12:07Z, `crypt_message`). Documented on `fix/download-memory` (`b8abe75`):
      USAGE and the LAN runbook mount such a share with `rsize=wsize=1048576`. This
      computer's `/etc/fstab` still mounts `agent-tmp` with the default (the author's change).
    - E7-12: two permission tests failed when TMPDIR lay in a setgid directory. Fixed on
      `fix/permission-tests` (`fc43879`): `test_published_files_read_only` sets its data
      folder's mode; the other test had failed through the umask (C2, fixed in 0.3.1) and now
      checks the folder's group with a group other than the account's own.
    - ENV-01: `archiwista doctor` checks the port on `127.0.0.1` only and has no `--host`.
    - G01-1 (§6 C3): „Projekty” had no sources strip and no „Źródła i warunki”. Fixed on
      `fix/projects-sources-strip` (`f0b53b7`): `GET /projects` and `GET /projects/{project}`
      carry `attribution` and `terms_notice` of the pinned data, the view shows them in its
      strip and the CLI ends its text with them.
    - G08-2 (§6 C3): an export's `README.txt` and `ATTRIBUTION.txt` cannot be opened from the
      interface.
    - §6 B1: an e2e test that a project file is readable by the folder's group. Added on
      `fix/permission-tests` (`fc43879`): `test_a_project_written_in_the_form_is_readable_by_its_folders_group`.
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
  and the pins by tags are decided (Status, release 0.3.0).
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
