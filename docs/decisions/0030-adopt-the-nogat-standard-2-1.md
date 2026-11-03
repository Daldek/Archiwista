# ADR-030: Adopt the Nogat standard 2.1

**Date:** 2026-10-25
**Status:** proposed (done on the topic branch `chore/nogat-2.1`; accepted when the author approves and merges it)

**Context:** Archiwista was built before the Nogat standard 2.1 (the standards of
the ecosystem: development, documentation, agent interface, error registry). It
had its own Polish coding standards, a flat package, a pip installation from a
sibling checkout of Kartograf, no gate script and Polish documents. Every other
tool of the ecosystem follows the standard, so a person or an agent who works
across them meets the same names, the same gate and the same errors. The author
approved the standard (ECO-005, ECO-011) and the adoption plan; where the standard
leaves a choice to an `app`, this ADR records it.

**Options:**
- A) Keep the own standards and layout; adopt only what is cheap.
- B) Adopt the standard in full as far as an agent can without the author (no
  history rewrite, GitHub settings, tags, pushes, licence text), and record every
  deviation in `CLAUDE.md`.

**Decision:** B, in these points.

1. **Rules.** The Nogat standard replaces `docs/DEVELOPMENT_STANDARDS.md`. What is
   specific to Archiwista is the section "Project rules" of `CLAUDE.md`; the
   deviations are the section "Deviations" of `CLAUDE.md`, one line each with the
   requirement identifier (DEV-1.2, DEV-1.3, DOC-3.1).
2. **Layout.** The package is `src/archiwista` (DEV-5.1 lets an `app` keep its
   layout; it moves like the other tools, ECO-011); `uv sync` installs it editable.
3. **Environment.** uv and the committed `uv.lock` (DEV-6.2, DEV-6.3); the
   development tools are the dependency group `dev`. Kartograf, untagged, is pinned
   by commit in `pyproject.toml`; the release pull request replaces the commit with
   the tag `v0.8.0` (REL-5.3).
4. **Gate.** `scripts/gate.sh` runs ruff format, ruff check, mypy, one pytest call
   with coverage (floor 80%) and `scripts/check-commits.sh` (DEV-7.6). The gate
   also leaves out the markers `perf` and `smb`, which need a store of 50,000 slots
   and a real SMB share (deviation DEV-10.1).
5. **CI.** GitHub Actions on Linux only, with Chromium for the interface tests, and
   a weekly run of the `live` tests (DEV-7.7, DEV-10.3); the Windows and macOS
   port is planned for v1.0. Nothing has run yet: nothing is pushed.
6. **Errors and texts.** The vendored registry of the Nogat errors
   (`schemas/nogat/`), codes in the HTTP problems, the command line and the jobs;
   every text for a person in a catalog with an English and a Polish variant, the
   texts of the API following `Accept-Language` (ERR-1 to ERR-6, AGI-6.3, AGI-6.4,
   AGI-9.2).
7. **Documents.** English, in the places and sizes of the standard: README in the
   order of DOC-2.1, `docs/plans/` for the plans (DEV-17.4), ADRs of the standard's
   kind in `docs/decisions/` with the index in `docs/DECISIONS.md` (DOC-8.2).

**Consequences:**
- The gate takes 25 to 40 minutes because the interface tests drive Chromium; a
  quiet machine is needed for it to be reliable (the limits of the timing-sensitive
  tests were widened for this).
- Deviations stay visible in one place and are reviewed with the standard:
  `tests/e2e` and `tests/perf` beside the standard tree (DEV-5.2), Linux-only CI,
  about 650 lines of JavaScript over 100 columns without a formatter (DEV-15.1,
  A-ADR-028), the CLA signed by a comment (DEV-16.5), the OpenAPI path and the
  absence of a command catalog (AGI-6.2), no `schema` member and no result envelope
  (AGI-3.2, AGI-4.1, AGI-4.2), outcome statuses of jobs instead of an error
  document (ERR-4), the texts stored in Polish (AGI-6.4), profile `tool` only for
  DEV-18 and DEV-19.
- The author still has to decide the points in "Open questions" of
  `docs/PROGRESS.md` (the `src/` move among them), push the branch and apply the
  GitHub settings; until then the ADR is `proposed`.
