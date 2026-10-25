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
| Nogat standard 2.1, documentation | done | everything is English (`docs/CLA.md`, the author's legal text, excepted; the Polish interface labels stay in quotes): README in the order of DOC-2.1 (146 lines), the project rules of the former `DEVELOPMENT_STANDARDS.md` in CLAUDE.md, the plans in `docs/plans/`, ADR-030 in `docs/decisions/` with the index in `docs/DECISIONS.md`, ARCHITECTURE, DECISIONS, SPEC, the plans, the reports and the mockup README translated, `docs/IMGWTOOLS_REQUIREMENTS.md` removed (IMGWTools 3.0.0 meets it; SPEC 12.7 keeps IMGW-1 to 20) |
| Nogat standard 2.1, error registry (ERR-3, ERR-4, DEV-11.1, AGI-6.3) | done | vendored registry and schemas (`schemas/nogat/`), generated `src/archiwista/_errors.py`, contract tests, problem+json with registry codes, the `archiwista-error/1` document and the exit codes of the CLI, the front end, registry codes in job documents (job rows of 0.2.0 are mapped on read, never rewritten), the message catalog `src/archiwista/messages/` and the error texts that follow `Accept-Language` (English by default, Polish with the header, `Content-Language` on every JSON answer; the stored texts stay Polish); deviations in CLAUDE.md: the stored texts (AGI-6.4), outcome statuses and no result envelope for good |
| Data output (DEV §19, ECO-051) | in progress | plan `docs/plans/2026-10-25-archiwista-next.md` Part 1 on `feature/kartograf-data-output` (from `chore/nogat-2.1`): **M1 done**: Kartograf is pinned at `8a36e977`, the head of its unpushed branch `feature/data-output` (2026-10-25; its own PROGRESS says done except a CLI smoke as a subprocess and the plain-mode prose, and its working tree held uncommitted edits), the supported range is `>=0.8.0.dev0,<0.9` (REL-5.6), the read API and `Project` say `root`, the fixtures call the directory above `data/` `base`. **M2 commit 1 done**: `SourceState` has `reason` and `hint`, which the registry, the scanner, `jobs/availability.py` (`store_unreachable`, which returns the error), the settings problems (`PUT /settings`) and the doctor carry; no probe sets them yet. Open: M2 commit 2, M3 to M5 (Next 1) |
| Gate | green | `scripts/gate.sh` passes on `chore/nogat-2.1`: ruff format, ruff check, mypy, pytest with coverage, `scripts/check-commits.sh`. The last run took 32 minutes (1235 tests, coverage 92%) beside other test suites; a quiet machine needs 25 to 33 minutes, so start it without other test suites running. Four flakes found under load are fixed (`3bc0482`, `876824f`, `d14f2f3`, `ebd8ef1`): the one-second limit that was every build's in `test_preview_build_item_timeout_fails_item_only` (only the slow file has one now, `build_timeout_s`), the 5 s that an expectation of the interface tests waited for the page and the server (30 s now), the race of `tests/unit/test_sandbox.py` (a `/proc` read of a process reaped meanwhile) and one hang of `tests/e2e/test_timeline.py` that did not reproduce (`faulthandler_timeout = 600` writes the stacks of a test that runs ten minutes). A job worker interrupted under `--cov` could stay alive: `patch = ["subprocess"]` measures it, and an interrupt that lands in coverage's tracer while it holds its `data_lock` leaves the lock held, so the worker waited for it in its exit handler for good (1 of 200 interrupted processes in a stress run). The first interrupt of a worker now starts a `faulthandler` watchdog that ends it after `STOP_TIMEOUT_S` (`_handle_interrupts` in `jobs/worker.py`, status 1, stacks in the job log); it does not cover an interrupt that arrives while the worker still imports its modules, before the handler stands (the supervisor's killer ends such a worker) |
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

1. **Data output (DEV §19, ECO-051): the rest of Part 1 of
   `docs/plans/2026-10-25-archiwista-next.md`**, on `feature/kartograf-data-output`, one
   commit per step with the gate green before each. Done: M1 (the Kartograf pin
   `8a36e977`, the range `>=0.8.0.dev0,<0.9`, the names `root` and `base`, and REL-2.5 in
   `tests/contract/test_package_data.py`) and the first commit of M2 (`SourceState`
   says why: `reason` and `hint` travel through every consumer of a probe). Open: the
   second commit of M2, the rules (the Kartograf `probe` judges `kartograf-store.json` and
   `imgw-store.json` by file name and schema: the states `no_marker`,
   `unsupported_marker`, `foreign_store` and `not_a_store`, the catalog entries
   `source.no_marker`, `source.foreign_store`, `source.unsupported_marker` and the
   reworded `source.kartograf_not_store` and `fix.source`, the generated stores marked
   through `kartograf.init_store` by one helper `mark_store(root)` in `tests/fixtures/`,
   `tests/contract/test_kartograf_marker.py` on `kartograf.testing`, ADR 0031, the
   CHANGELOG **Breaking** line), M3 the names for people (docstrings, the wizard hint,
   README, USAGE, `.env.example`, the SPEC lines), M4 the tests isolated from the user's
   producer settings, M5 the default root in the wizard. Then the
   IMGWTools source (I) and v0.3 "Actions" (A) on their own branches. The pinned commit is
   not pushed, so `uv lock` resolves it only in a uv git database that holds it: fetch
   the branch into the database below `~/.cache/uv/git-v1/db/` in which `git cat-file -t
   8e9bcbb058d1…` answers `commit` (`git --git-dir=<db>/.git fetch ~/workspace/Kartograf
   feature/data-output:local-feature-data-output`), then `uv lock --offline`. Re-pin when
   Kartograf rewrites its branch again, before Archiwista is pushed.
2. Replace the Kartograf commit pin by the tag `v0.8.0` in the release pull request
   (REL-5.3, REL-2.1); use `kartograf.testing` (DEV-10.6) instead of the hand-made
   `tests/fixtures/make_store.py` when Kartograf ships it.
3. **CI proof.** The first CI run needs the push: check the Chromium step of `ci.yml` and the
   weekly `live.yml`.
4. v0.3 "Actions": spec and plan to be approved before implementation (`docs/SPEC.md` 12 and
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
- The Kartograf pin is `8a36e977`, the head of the unpushed `feature/data-output`; GitHub
  has no such commit, so a pushed Archiwista has no green CI until Kartograf is pushed
  (HUB-5.2). Pin the pushed head after the push?
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
