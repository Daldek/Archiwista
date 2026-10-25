# PROGRESS: Archiwista

Current state only (DOC-6.1). Branch, tag and remote state: ask git (`git status`,
`git log --oneline -10`). History: the git log and [CHANGELOG](CHANGELOG.md); the
Polish session notes that used to live here are in git (`docs/PROGRESS.md` before the
commit that introduced this file).

## Status

| Component | State | Note |
|---|---|---|
| Release 0.2.0 "Previews" | done | released on `develop` (`chore(release): wydanie 0.2.0`), not tagged and not merged into `main` (author's decision); `develop` carries `0.3.0.dev0` |
| Next version v0.3 "Actions" | planned | spec and plan first, then code (PRD F5.3 pre-building of previews included); producer needs: SPEC 12, SCOPE stage 4 |
| Nogat standard 2.1, structure and tooling | done | on `chore/nogat-2.1`: uv and `uv.lock`, Kartograf pinned by commit, `src/` layout, `scripts/gate.sh`, `scripts/check-commits.sh`, CI, Dependabot, editor and git files, markers, package-data and README example tests, the ruff rule set of DEV-7.2, `--verbose`, `--quiet` and `ARCHIWISTA_LOG_LEVEL` |
| Nogat standard 2.1, documentation | in progress | English and current: CHANGELOG, CLAUDE.md, CONTRIBUTING, SECURITY, USAGE, AGENT_API, PRD, SCOPE, this file; open: README, ARCHITECTURE, DECISIONS, SPEC, plans, reports (Next 1) |
| Nogat standard 2.1, error registry (ERR-3, ERR-4, DEV-11.1, AGI-6.3) | done | vendored registry and schemas (`schemas/nogat/`), generated `src/archiwista/_errors.py`, contract tests, problem+json with registry codes, the `archiwista-error/1` document and the exit codes of the CLI, the front end, registry codes in job documents (job rows of 0.2.0 are mapped on read, never rewritten), the message catalog `src/archiwista/messages/` and the error texts that follow `Accept-Language` (English by default, Polish with the header, `Content-Language` on every JSON answer; the stored texts stay Polish); deviations in CLAUDE.md: the stored texts (AGI-6.4), outcome statuses and no result envelope for good |
| Data output (DEV §19) | planned | waits for the producers' development heads; call sites in Next 2 |
| Gate | green | `scripts/gate.sh` passes on every commit of `chore/nogat-2.1`: ruff format, ruff check, mypy, pytest with coverage, `scripts/check-commits.sh`. The last run took 37 minutes under a load of 8 (1206 tests); a quiet machine needs 25 to 33 minutes, so start it without other test suites running. Four flakes found under load are fixed (`3bc0482`, `876824f`, `d14f2f3`, `ebd8ef1`): the one-second limit that was every build's in `test_preview_build_item_timeout_fails_item_only` (only the slow file has one now, `build_timeout_s`), the 5 s that an expectation of the interface tests waited for the page and the server (30 s now), the race of `tests/unit/test_sandbox.py` (a `/proc` read of a process reaped meanwhile) and one hang of `tests/e2e/test_timeline.py` that did not reproduce (`faulthandler_timeout = 600` writes the stacks of a test that runs ten minutes). A job worker interrupted under `--cov` can stay alive: `patch = ["subprocess"]` measures it, and an interrupt that arrives while coverage's tracer holds its `data_lock` leaves the lock held, so the worker waits for it in its exit handler for good (1 of 200 interrupted processes in a stress run; the supervisor kills such a worker after `STOP_TIMEOUT_S`, only one whose supervisor is gone stays: Next 5) |
| CI (Linux) | written, not run | `.github/workflows/ci.yml` and `live.yml`; nothing is pushed |

Skipped adoption items, which need the author (DEV-3.3, ADOPTION_PLAN):

| Item | Why |
|---|---|
| History rewrite (phase 1) | Archiwista needs only DEV-4.2: every commit is by `Daldek <git@debever.pl>` and has no AI trailer |
| Rulesets for `main`, `develop` and `v*` tags, private vulnerability reporting, Dependabot security updates, `main` pushed and made the default branch (DEV-3.6, DEV-13.6, DEV-13.7, ECO-008) | GitHub settings. The required check is the one job `gate (ubuntu-latest, Python 3.12)` (CI runs on Linux only) |
| `docs/CLA.md` text and signing mechanism | the author's legal text: it says "comment on the pull request", while DEV-16.5 says checkbox plus a line in `CONTRIBUTORS.md` in the same pull request |
| `Approved:` lines of the executed plans v0.1 and v0.2 (DEV-17.4) | approval is the author's statement |
| Tags, releases, replacing the Kartograf commit pin by the tag `v0.8.0`, PyPI name `nogat-archiwista` (phases 5 and 6) | need the producers' tags and the author's approval |
| Push of `chore/nogat-2.1`, pull request, merge into `develop` | approvals (DEV-3.3) |

## Next

1. **Documents, the rest of the standard 2.1 adoption on `chore/nogat-2.1`** (one commit per
   step, gate green before each; the source of the rules is the Nogat branch
   `feature/data-output`, `git -C ~/workspace/Nogat show feature/data-output:standards/<file>`;
   Hydrolog and Retman have the same branch name as worked examples). README in English in
   the order of DOC-2.1 (profile `app`: Run and Deploy replace Install and Quick start),
   absolute links (DOC-1.4), at most 400 lines, summary at most 400 characters and
   `pyproject` `description` at most 200 (DOC-2.3); move the project-specific rules of
   `docs/DEVELOPMENT_STANDARDS.md` (sections 5.1, 7, 8 and 10) into CLAUDE.md and delete the
   file (DEV-1.3); `git mv docs/PLAN_v0.1.md docs/plans/2026-10-18-plan-v0.1.md` and
   `docs/PLAN_v0.2.md docs/plans/2026-10-19-plan-v0.2.md` (DEV-17.4); an ADR
   `docs/decisions/0030-...md` with the index entry in `docs/DECISIONS.md` (DOC-8.2): `src/`
   layout, uv and the commit pin, the gate, Linux-only CI, the deviations of CLAUDE.md.
   Translate the Polish documents (ECO-005), most useful first (`docs/AGENT_API.md` is
   done): `docs/ARCHITECTURE.md` (77 KB), `docs/DECISIONS.md` (93 KB, statuses of DOC-8.1),
   `docs/SPEC.md` (326 KB), the two plans (377 KB), `docs/reports/` (57 KB);
   `docs/IMGWTOOLS_REQUIREMENTS.md` (105 KB) is met by IMGWTools 3.0.0 (IMGW-1 to 20):
   decided (the author delegated it): delete it, keep the IMGW-n identifiers of SPEC 12.7
   and fix the references (SPEC 12.7, 12.8 and 14, SCOPE, PRD, DECISIONS A-ADR-019, 021 and
   025). `<katalog-danych>` becomes `<data-dir>` in what is translated. A model-assisted
   pipeline (code blocks masked, chunks at headings, checks of structure, code spans,
   links, identifiers and numbers, retry) translated all of them in about ten minutes in
   a trial; run it on the committed text (the error texts are final: they changed SPEC 9.1,
   ARCHITECTURE 5.3 and 5.4 and AGENT_API). Terms as in the English documents (the Fan,
   the Timeline, the curtain, store, own data, the release names of SCOPE). The code blocks
   with Polish prose (ARCHITECTURE 0 and 1, DECISIONS 0, SPEC 0 to 3, 17, 19 and 29) are
   translated; the ASCII mock-ups and the JSON examples with Polish labels stay.
2. **Data output (DEV §19, ECO-051): migrate the calls to Kartograf after Kartograf has the
   change on its development head** (not before; plan `docs/plans/2026-10-24-data-output.md`
   of Nogat, step 4). Re-pin Kartograf to that commit in `pyproject.toml` (`uv lock`).
   Archiwista keeps calling Kartograf in store mode, so the names change to `root`, not the
   behaviour. Call sites, as of 2026-10-24:
   - `src/archiwista/adapter/kartograf/adapter.py:645` reads `project.output_dir` (becomes
     `project.root`); the docstrings of lines 76, 109, 136 and 167 say "Kartograf's
     `--output` directory" (`--root`); `probe` follows the marker rules (DEV-19.12,
     DEV-19.13): a root with the layout but no `kartograf-store.json` is
     `store_unavailable` with the hint `kartograf store init --root <path>`.
   - Texts: the entries `source.kartograf_not_store` and `fix.source` (`src/archiwista/messages/`
     `source.py` and `fix.py`; they name the `--output` directory), `src/archiwista/config.py:179`,
     `src/archiwista/api/models.py:2401`, `src/archiwista/sources/types.py:4`.
   - `tests/contract/test_kartograf.py:53`, `:55` and `:60` pin the parameter names of
     `list_segments`, `list_partitions` and `iter_store` (`output_dir` becomes `root`); the
     probe tests at `:601` to `:608` and the project reads at `:633` to `:669`.
   - `tests/fixtures/make_store.py`: `StoreManifest.output_dir` (line 340) and its docstrings
     (lines 3, 5, 328, 330) name the store root; the generator writes the marker
     `kartograf-store.json` and the project manifest key `output_dir` (becomes `root`);
     follow-ups: `tests/integration/test_projects.py:88` to `:90` (`_write_manifest`),
     `tests/fixtures/api_store.py:37`, `tests/fixtures/own_data.py:542`,
     `tests/unit/test_own_data_fixture.py:246`, and the `store.output_dir` uses in
     `tests/integration/test_read_only_store.py`, `test_preview_security.py`,
     `test_agent_flow.py`, `test_projects.py`, `test_scanner.py`.
   - `docs/SPEC.md`: section 12 KB-5 (line 3684, `run_command(..., output_dir, ...)`), KA-1
     (3659), KH-1 (3717, `set_project_output_dir`), and the passages that call the
     `--output` directory the store (lines 174, 783 to 785, 813, 1431, 1445, 1458, 1459,
     3118, 3723); the same names in `docs/ARCHITECTURE.md` and `docs/USAGE.md` ("its
     `--output` directory, that is the `data/` directory").
3. Replace the Kartograf commit pin by the tag `v0.8.0` in the release pull request
   (REL-5.3, REL-2.1); use `kartograf.testing` (DEV-10.6) instead of the hand-made
   `tests/fixtures/make_store.py` when Kartograf ships it.
4. **CI proof.** The first CI run needs the push: check the Chromium step of `ci.yml` and the
   weekly `live.yml`.
5. **A worker that outlives its supervisor under coverage** (Status, Gate). Not fixed yet; the
   design: the SIGINT handler of the worker (`_handle_interrupts` in `jobs/worker.py`) arms
   `faulthandler.dump_traceback_later(STOP_TIMEOUT_S, exit=True)` once and then raises
   `KeyboardInterrupt` as before; the watchdog is in C, so it also ends a process that waits in
   an exit handler (checked: it ends with status 1 and the stacks in the log). `STOP_TIMEOUT_S`
   moves from `jobs/supervisor.py` to `jobs/protocol.py`, for the supervisor's killer and the
   worker. A test starts a process that blocks in an exit handler, interrupts it and expects it
   to end within the limit. `core = "sysmon"` only lowers the chance, and dropping
   `patch = ["subprocess"]` loses the measurement of the workers.
6. v0.3 "Actions": spec and plan to be approved before implementation (`docs/SPEC.md` 12 and
   13, SCOPE stage 4).

## Open questions

Decisions awaiting the author:

- DEV-5.1 lets an `app` keep its layout: confirm the `src/` move of the ADOPTION_PLAN row.
- AGI-6.2 names `/openapi.json`; Archiwista serves `/api/v1/openapi.json` behind the session
  and names operations after route functions (no command catalog). Keep, or move?
- AGI-4.1 asks a top-level `schema` in every machine-readable document; the API responses
  and `--json` outputs have none. Add `archiwista-<kind>/1`, or leave it for the catalog work?
- DEV §18 is profile `tool` only, but ECO-028 says all tools read `nogat.toml`
  (`lang`, `data_dir`, `cache_dir`). Should Archiwista, which uses its own `config.toml` and
  platform directories, read it too?
- The Kartograf pin is `8e9bcbb`, the head of `origin/develop`; the local `develop` is one
  docs-only commit ahead and unpushed. Pin the local head after it is pushed?
- `main` of this repository is not on GitHub: push and make it the default branch (ECO-008).

Open since the previous PROGRESS (Polish, in git):

- Kartograf: the tag `v0.8.0` waits for the author and the Kartograf team; v0.3 needs KA-4,
  KB-1 to KB-5, KB-7, KC-1 to KC-3, KD-1 to KD-4, KH-1; KF (merged PL + CZ surface) blocks v0.6.
- IMGWTools: 3.0.0 (`slave` from `0d98f3b`, untagged) meets IMGW-1 to 20; the branch
  `fix/archiwista-compat-2` and the tag wait for the author; the v0.5 adapter treats
  `missing_sidecar` as a non-critical, possibly transient problem.
- GPU: the measurement of 30 frames per second or more with 5,000 footprints needs hardware
  WebGL; the test account has no access to `/dev/dri/renderD128`.
- Basemap: one default provider (OpenFreeMap) is an availability risk outside offline mode.
- PRD "Open decisions" (coverage labels before v0.3, the IMGW data format before v0.5, merge
  results as Kartograf products before v0.6, the ČHMÚ adapter) and the mockup questions M3,
  M5 to M8, M10, M11 (SPEC 16).
- The mockup (`mockup/`) is a clickable prototype, not production code; its working data
  directory is outside the repository and can be removed with the author's consent.
