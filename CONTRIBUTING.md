# Contributing to Archiwista

Thanks for your interest in Archiwista! Bug reports, feedback on the
specification, fixes, features, and documentation are welcome.

## Project status

Archiwista is currently in the specification phase; there is no application
code yet. Feedback on these documents is especially useful:

- [`docs/PRD.md`](docs/PRD.md) — product requirements;
- [`docs/SCOPE.md`](docs/SCOPE.md) — scope and milestones;
- [`docs/SPEC.md`](docs/SPEC.md) — detailed specification;
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — architecture decisions.

Implementation starts only after the specification and plan have been
approved: specification → plan → implementation.

## Contribution guidelines

- **Project boundaries.** Archiwista does not download or process source
  data itself: it delegates these tasks to store producers (Kartograf,
  IMGWTools) through their public APIs. If a producer lacks a function,
  document a requirement for that producer (`docs/SPEC.md`, section 12)
  instead of working around it in Archiwista. The Kartograf store is read-only
  to Archiwista; writes to that store go through Kartograf's public API.
- **Language.** Code, identifiers, docstrings, comments, logs, tests, and
  contributor-facing files are in English. Project documentation and UI text
  are in Polish.
- **Commits.** Use [Conventional Commits](https://www.conventionalcommits.org/)
  with descriptions in Polish, for example
  `docs(spec): doprecyzowanie etykiet pokrycia`.
- **Branches.** Open pull requests against `develop`; address one concern
  per pull request.
- **Data.** Do not put downloaded data in the repository or `/tmp`; use an
  explicit directory elsewhere. In documentation, write data paths as
  `<katalog-danych>`.
- **Python environment.** Use the repository-local `.venv` for Python. Once
  application code is available, follow
  [`docs/DEVELOPMENT_STANDARDS.md`](docs/DEVELOPMENT_STANDARDS.md) for the
  applicable `pytest`, `ruff`, and `mypy` checks before opening a pull request.

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
