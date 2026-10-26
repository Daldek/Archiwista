# Contributing to Archiwista

Thanks for your interest in Archiwista! Bug reports, feedback on the
specification, fixes, features, and documentation are welcome.

## Getting started

```bash
# Install the locked development environment with the optional sources
# (uv: https://docs.astral.sh/uv/)
uv sync --locked --all-extras

# Chromium and Firefox for the interface tests (once)
uv run playwright install chromium firefox

# Run the gate before opening a pull request: ruff, mypy, tests with coverage and the
# commit check (contributors keep their own identity, so skip the author check)
GATE_CHECK_AUTHOR=0 scripts/gate.sh
```

Archiwista 0.2 is released; the next version is planned in
[`docs/SPEC.md`](docs/SPEC.md) section 13. A feature or a change of a public
interface starts with a plan in `docs/plans/` that the maintainer approves:
specification → plan → implementation. Feedback on these documents is especially
useful:

- [`docs/PRD.md`](docs/PRD.md) — product requirements;
- [`docs/SCOPE.md`](docs/SCOPE.md) — scope and milestones;
- [`docs/SPEC.md`](docs/SPEC.md) — detailed specification;
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — architecture decisions.

[`CLAUDE.md`](CLAUDE.md) lists the rules of the project for people and agents who
develop it.

## Contribution guidelines

- **Project boundaries.** Archiwista does not download or process source
  data itself: it delegates these tasks to store producers (Kartograf,
  IMGWTools) through their public APIs. If a producer lacks a function,
  document a requirement for that producer (`docs/SPEC.md`, section 12)
  instead of working around it in Archiwista. The Kartograf store is read-only
  to Archiwista; writes to that store go through Kartograf's public API.
- **Language.** Code, identifiers, docstrings, comments, logs, tests,
  documentation, commit messages and contributor-facing files are in English.
  Every text for a person has an English and a Polish variant in the message
  catalog (`src/archiwista/messages/`) or, for the interface, in
  `src/archiwista/web/src/labels/`; no other module holds such a text. Some
  documents under `docs/` are still Polish and are being translated.
- **Commits.** Use [Conventional Commits](https://www.conventionalcommits.org/)
  in English, for example `docs(spec): clarify the coverage labels`. Messages
  carry no AI attribution.
- **Branches.** Open pull requests against `develop`; address one concern
  per pull request.
- **Data.** Do not put downloaded data in the repository or `/tmp`; use an
  explicit directory elsewhere. In documentation, write data paths as
  `<data-dir>`.
- **Python environment.** Use the repository-local `.venv` through `uv`; the
  gate runs `ruff format --check`, `ruff check`, `mypy` and `pytest` with a
  coverage floor of 80%.

## Contributor License Agreement (CLA)

Before your first contribution can be merged, please sign our **Contributor
License Agreement**. In plain terms:

- **What it is.** A short agreement confirming that you wrote your
  contribution (or have the right to submit it) and granting the rights needed
  to use and redistribute it. The full text is in
  [`docs/CLA.md`](docs/CLA.md).
- **Why it is required.** It provides a sound basis for the project's
  licensing and preserves the option to relicense in the future.
- **Your contribution stays MIT.** Signing the CLA does **not** change the
  license: the project and your contribution remain under the
  [MIT License](LICENSE).
- **Signing is one comment — the process is manual.** There is no bot or
  form. When your pull request is ready, comment with exactly:

  > I have read the CLA document and hereby sign it.

  On merging your pull request, the maintainer records your GitHub handle,
  the date, and the pull-request number in
  [`CONTRIBUTORS.md`](CONTRIBUTORS.md). You only sign once; it also covers
  future contributions.

Please also tick the CLA box in the pull-request template.

## Reporting issues

Found a bug or have a feature idea? Open a GitHub issue with steps to
reproduce, expected and actual behavior, and your environment (OS and
Archiwista, Kartograf, and IMGWTools versions, where applicable).

Security problems are not reported as public issues: see
[`SECURITY.md`](SECURITY.md).
