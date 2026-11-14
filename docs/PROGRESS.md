# PROGRESS: Archiwista

Current state only (DOC-6.1). Branch, tag and remote state: ask git (`git status`,
`git log --oneline -10`). History: the git log, [CHANGELOG](CHANGELOG.md), the plans'
Results in `docs/plans/` and the ADRs; the Polish session notes that used to live here
are in git (`docs/PROGRESS.md` before the commit that introduced this file).

## Status

The working branch is `develop`; every branch named below is merged into it, except
`chore/pins-candidate-4` and `chore/everything-v1`. Nothing after 0.2.0 is released.

| Component | State | Note |
|---|---|---|
| v0.1 "Browser", v0.2 "Previews" | done | released as 0.1.0 and 0.2.0 on `develop`, not tagged and not merged into `main` (the author's decision); the v0.2 criterion of 30 frames per second with 5,000 footprints is unverified (blocked below) |
| v0.3 "Actions" | done | plan `docs/plans/2026-10-25-archiwista-next.md` Part 3, A1 to A14 (ADR-034 to ADR-044); report `docs/reports/v0.3-measurements.md`; its project actions (A7, A8, A13) are replaced by A-ADR-049. Not released (Next 7); not built: Next 13 |
| v0.4 "Team" | done | plan `docs/plans/2026-10-26-plan-v0.4.md` T1 to T12 (ADR-046, ADR-047); the LAN runbook ran once on one machine with real components (`docs/reports/v0.4-lan-runbook.md`); the three-computer run is the author's (Next 8). Not released |
| Projects (A-ADR-049 and its errata 1 to 7) | done | `archiwista-project.json` (`archiwista-project/1`) with its area files in `obszary/`; sets („Zestaw”) open or closed with their pins; the jobs verify, check, re-pin and restore; the card's „Przepnij” and „Przywróć brakujące” open the plan window of the set's check (ADR-042 erratum 2); exports in `eksport/<name>/`. Not released |
| Data output (DEV §19, ECO-051) and `nogat.toml` | done | store markers and roots, the producers' default roots offered in the wizard, tests isolated from the producers' settings (ADR-031, ADR-033); `data_dir`, `cache_dir`, `lang` and the table `gui` of `nogat.toml` (A-ADR-053) |
| Obserwator source and station views | done | Obserwator stores indexed, stations, series coverage, the station map, Katalog list, Timeline, card, chart and comparison (ADR-032, ADR-045); monthly charts and annual extremes (A-ADR-051); a station's series handed to Hydrolog through Nogat's kit, with „Dane” and „Zmienna” (A-ADR-052, A-ADR-054) |
| Obserwator's commands and its two roots (A-ADR-050, A-ADR-056; Obserwator pin `0394af7`) | done | each store names Obserwator's raw root (`obserwator`, `obserwator-store.json`) and its data root (`obserwator_data`, `obserwator-data.json`, read only), each probed by its kind (reason `wrong_root`); Archiwista runs only `store sync` into the raw root. Limits: series and station catalogs are built by Obserwator offline, so a project's pins of them are `not_checkable`; Obserwator has no run mode that keeps the stored versions (a restore takes the source's current file); `pmaxtp sync` is not in Archiwista's catalog (A-ADR-050 option C) |
| The providers' lines (A-ADR-055 and its errata 1 to 4) | done | `attribution` and `terms_notice` on every station, map, Katalog, version and comparison answer, the CLI, `ATTRIBUTION.txt` in exports and the hand-off; one compact strip of Nogat's kit per view or overlay, the terms linked, the G and Z lines of station catalogs' sidecars, one CP without the detail of processing (ECO-071, branch `feat/cp-without-detail`, not merged). Not in PNG previews (Next 6) |
| Nogat's GUI kit (A-ADR-054 and its errata 1 to 4) | done | kit 0.7.1 of Nogat `05bf583` in `web/nogat/` (byte for byte, checked against `nogat-kit.json`): the menu „Aplikacje”, the hand-off, the strip `<nogat-sources>`, „Zgłoszenia” on `<nogat-admin-feedback>` |
| User guide `/instrukcja` (A-ADR-048) | done | 13 Polish slides served without a session, „Instrukcja” in the top bar; no link on the sign-in page; its pictures need taking again when the views they show change |
| Nogat standard 1.0 | done | structure and tooling (uv, `src/` layout, `scripts/gate.sh`, CI, Dependabot), English documentation, error registry (A-ADR-030); the items that need the author: Open questions |
| Test server :8090 | done | https://archiwista-test.debever.pl, user unit `archiwista-public.service`, runs `55d97a7` (`develop`) since 2026-11-14; rollback steps in `/home/claude-agent/data/archiwista-public/backup-2026-11-13/ROLLBACK.txt`. Its `nogat.toml` (in its `XDG_CONFIG_HOME`) holds only the table `gui`; its store `hydroni` names only a raw root (Next 1) |
| Tidy-up of 2026-11-14 (`refactor/tidy-2026-11-14`) | done | merged as `8573a93`: dead and duplicated code removed (`values.py`), Nogat's server logs (A-ADR-057, ECO-066), the documentation audited against the code, the info texts by Nogat DEV-15.14 |
| Pins of Nogat's release set candidate-4 (`chore/pins-candidate-4`) | in progress | Kartograf `c9afdd3f`, Obserwator `0394af7` (Hydrolog is no dependency); ruff, mypy, unit and contract tests and the integration tests that touch the producers pass; not merged, the full gate is left to the parent session |
| Every format at version 1 (`chore/everything-v1`, Nogat REL-1.4, ECO-072) | in progress | the state backup `archiwista-state/1` (a `/2` copy still imports), the job protocol 1, the index schema 1 (an index of another number is rebuilt) and the state schema 1 in one migration (a database numbered 5 is renumbered when it opens; schema 2 to 4 no longer opens); on :8090 the next start renumbers `state.sqlite` (5) and rebuilds `index.sqlite` (18) by a full scan of `hydroni`; ruff, mypy, unit and contract tests and the touched tests pass; not merged, the full gate is left to the parent session |
| Gate | done | last recorded full run: 2026-11-14 on `feat/obserwator-data-root` (`0ee0906`, merged as `55d97a7`), 3006 passed, coverage 93.45 %, 55 min with `TMPDIR` on a local disk, `GATE OK`; none yet on `refactor/tidy-2026-11-14` |
| CI (Linux) | in progress | `ci.yml` runs the gate, the suite without the extra `obserwator` and a dependency audit; on 2026-11-14 the audit (opentelemetry-api 1.45.1) and the project card's activity test failed on `develop` and were fixed in `0ee0906`, the run after it not recorded. Python 3.15 (reported, not blocking) failed on an unraisable `sqlite3` finalizer warning in an e2e test. `live.yml` has not run (Next 9) |
| v0.5 "IMGW stations" release | blocked | the Obserwator release with its store (REL-5.3: today pinned by commit); the archive badge of the stations (SPEC 9.2, 4.8.4) and the input archives of the station card need a producer capability the source interface lacks |
| v0.6 "PL + CZ" | blocked | Kartograf KF (merged PL + CZ surface) |
| Producer requirements behind open gaps | blocked | „U źródła” offers only NMT, NMPT and LAZ until Kartograf KD-3/KD-4 (meanwhile paste the producer's command, which „Obszar polecenia” runs on a project's area); plans show „rozmiar nieznany” until Kartograf KH; the „pobrane” badge cannot match LAZ, whose sidecar records no survey work (Kartograf `docs/PROGRESS.md` Next 30); A15 waits for Kartograf KB-7; Archiwista's later versions need KA-4, KB-1 to KB-5, KB-7, KC-1 to KC-3, KD-1 to KD-4, KH |
| GPU measurement (v0.2) | blocked | 30 frames per second or more with 5,000 footprints needs hardware WebGL; the test account has no access to `/dev/dri/renderD128` |

## Next

1. :8090 with the author: its store `hydroni` names an empty raw root
   (`/mnt/magazyn/agent-tmp/hydroni/obserwator`), which keeps working unchanged; to show
   series and station catalogs add `obserwator_data` (e.g. Obserwator's production data
   root `/home/claude-agent/data/obserwator-target/data`) and restart. The old combined
   store `/mnt/magazyn/agent-tmp/archiwista-zespol/obserwator` (not configured on :8090)
   must be split (USAGE, "Obserwator's raw root and data root") before use.
2. Flaky test: `tests/e2e/test_sign_in.py::test_a_temporary_password_is_changed_before_the_shell_opens`
   failed once in the gate of 2026-11-10 (the heading „Logowanie” never showed in 30 s) and
   passes alone and with its file; cause not found.
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
7. Release, per decisions D2 and D3 of Nogat's plan
   `2026-10-31-archiwista-projects.md`: one Archiwista release holds v0.3, v0.4 and the
   projects (all in `develop` since 2026-11-03), outside the first release set
   (Archiwista follows the producers' tags in its own session, REL-5.4). Then: replace
   the commit pins by the producers' tags (REL-5.3, REL-2.1), CHANGELOG version and tag
   with the author's approval, the Nogat registry (the edge Archiwista → Obserwator is
   still `planned`). Re-pin first if a producer commits on its branch again: `uv lock
   --offline` resolves a commit only from uv's git database
   (`~/.cache/uv/git-v1/db/`), so fetch the producer's branch into it, change the commit
   in `pyproject.toml`, `uv lock --offline`, `uv sync --locked --all-extras`.
8. The author: the runbook's three-computer SMB/TLS scenario on a Linux server (CA trust
   in three browsers, the store on the share); a full `scripts/gate.sh` on the Mac; the
   live run of `tests/integration/test_live_actions.py` (`ARCHIWISTA_LIVE_ACTIONS=1`)
   and the SMB run of v0.3 criterion 8.
9. CI: the weekly `live.yml` has not run yet.
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
- Tags, releases, replacing the producers' commit pins by tags, PyPI name
  `nogat-archiwista` (adoption phases 5 and 6): need the producers' tags and the author's
  approval.
- Basemap: one default provider (OpenFreeMap) is an availability risk outside offline mode.
- PRD "Open decisions" (merge results as Kartograf products before v0.6, the ČHMÚ
  adapter) and the mockup questions M6 to M8 and M10 (SPEC 16; the assistant proposal
  card for IMGW data is deferred after the MVP).
- The mockup (`mockup/`) is a clickable prototype, not production code; its working data
  directory outside the repository stays until the author decides: the consent of
  2026-11-09 was for the branch `feat/mockup` only.
