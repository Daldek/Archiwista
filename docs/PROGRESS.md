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
| Nogat standard 2.1, structure and tooling | in progress | done on `chore/nogat-2.1`: uv and `uv.lock`, Kartograf pinned by commit, `src/` layout, `scripts/gate.sh`, `scripts/check-commits.sh`, CI, Dependabot, editor and git files, markers, package-data and README example tests; open: ruff rule set, `--verbose` and `--quiet` (Next 1.1 and 1.2) |
| Nogat standard 2.1, documentation | in progress | English and current: CHANGELOG, CLAUDE.md, CONTRIBUTING, SECURITY, USAGE, AGENT_API, PRD, SCOPE, this file; open: README, ARCHITECTURE, DECISIONS, SPEC, plans, reports (Next 1.3) |
| Nogat standard 2.1, error registry (ERR-3, ERR-4, DEV-11.1, AGI-6.3) | done | vendored registry and schemas (`schemas/nogat/`), generated `src/archiwista/_errors.py`, contract tests, problem+json with registry codes, the `archiwista-error/1` document and the exit codes of the CLI, the front end; deviations in CLAUDE.md (job `error.code`, outcome statuses, no result envelope, Polish `detail`) |
| Data output (DEV §19) | planned | waits for the producers' development heads; call sites in Next 2 |
| Gate | green | `scripts/gate.sh` passes on every commit of `chore/nogat-2.1`: ruff format, ruff check, mypy, pytest with coverage, `scripts/check-commits.sh`. The full run takes about 25 minutes; start it on a machine without other test suites running |
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

1. **Finish the standard 2.1 adoption on `chore/nogat-2.1`** (one commit per step, gate
   green before each; the source of the rules is the Nogat branch `feature/data-output`,
   `git -C ~/workspace/Nogat show feature/data-output:standards/<file>`; Hydrolog and
   Retman have the same branch name as worked examples):
   1. `style:` add `W` and `C4` to the ruff `select` (DEV-7.2; `uv run ruff check --select
      W,C4 .` finds 3 places, one is a `dict.fromkeys` in `tests/integration/test_snapshots.py`)
      and `[tool.ruff.format] quote-style = "double"`.
   2. `feat(cli): --verbose, --quiet and ARCHIWISTA_LOG_LEVEL` (DEV-12.2); list the variable
      in the README and `.env.example`.
   3. **Documents.** README in English in the order of DOC-2.1 (profile `app`: Run and
      Deploy replace Install and Quick start), absolute links (DOC-1.4), at most 400 lines,
      summary at most 400 characters and `pyproject` `description` at most 200 (DOC-2.3);
      move the project-specific rules of `docs/DEVELOPMENT_STANDARDS.md` (sections 5.1, 7, 8
      and 10) into CLAUDE.md and delete the file (DEV-1.3); `git mv docs/PLAN_v0.1.md
      docs/plans/2026-10-18-plan-v0.1.md` and `docs/PLAN_v0.2.md
      docs/plans/2026-10-19-plan-v0.2.md` (DEV-17.4); an ADR `docs/decisions/0030-...md`
      with the index entry in `docs/DECISIONS.md` (DOC-8.2): `src/` layout, uv and the
      commit pin, the gate, Linux-only CI, the deviations of CLAUDE.md. Translate the Polish
      documents (ECO-005), most useful first (`docs/AGENT_API.md` is done):
      `docs/ARCHITECTURE.md` (77 KB), `docs/DECISIONS.md` (93 KB, statuses
      of DOC-8.1), `docs/SPEC.md` (326 KB), the two plans (377 KB), `docs/reports/` (57 KB);
      `docs/IMGWTOOLS_REQUIREMENTS.md` (105 KB) is met by IMGWTools 3.0.0 (IMGW-1 to 20):
      delete it or translate it (see Open questions). `<katalog-danych>` becomes `<data-dir>`
      in what is translated.
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
   - Texts: `src/archiwista/messages.py:271` and `:390` (the Polish messages that name the
     `--output` directory), `src/archiwista/config.py:179`,
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
   weekly `live.yml`. Also look at `tests/unit/test_sandbox.py::
   test_sandbox_child_killed_with_its_group_at_time_limit`: it failed once with a
   `ProcessLookupError` (a `/proc` read of a process that had ended) in a scoped run while the
   machine was loaded; it passed in all full gate runs, so it is probably a race in the test
   (the child may end between listing and reading `/proc`). Not investigated yet.
5. v0.3 "Actions": spec and plan to be approved before implementation (`docs/SPEC.md` 12 and
   13, SCOPE stage 4).

## Open questions

Decisions awaiting the author:

- Machine output is English (AGI-9.2, AGI-6.4, ERR-6), but Archiwista's `detail` texts come
  from one Polish dictionary and services raise them as Polish text. CLAUDE.md now has the
  deviation line (only `title` follows `Accept-Language`). Translate the texts of the
  problems instead (hundreds of raise sites, language chosen by `Accept-Language`)?
- The `error.code` of job documents are job codes: `source_unavailable` there means a
  missing plugin, in the registry a failed remote service. Map them to registry codes with
  the old code as `details.reason` (jobs table, worker protocol, API model)? Deviation line
  ERR-1 in CLAUDE.md until then.
- DEV-5.1 lets an `app` keep its layout: confirm the `src/` move of the ADOPTION_PLAN row.
- AGI-6.2 names `/openapi.json`; Archiwista serves `/api/v1/openapi.json` behind the session
  and names operations after route functions (no command catalog). Keep, or move?
- AGI-4.1 asks a top-level `schema` in every machine-readable document; the API responses
  and `--json` outputs have none. Add `archiwista-<kind>/1`, or leave it for the catalog work?
- DEV §18 is profile `tool` only, but ECO-028 says all tools read `nogat.toml`
  (`lang`, `data_dir`, `cache_dir`). Should Archiwista, which uses its own `config.toml` and
  platform directories, read it too?
- `docs/IMGWTOOLS_REQUIREMENTS.md` and the executed plans: translate, or leave in git history
  (requests are GitHub issues now, ECO-043)?
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
