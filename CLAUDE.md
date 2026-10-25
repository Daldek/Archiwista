# Archiwista: instructions for agents developing the project

Archiwista is a web application (locally: one person on `localhost`; later a
team on a local network) for working with the spatial data stores that
Kartograf writes: browsing and search, a map with previews, availability and
freshness checks, downloads and projects through the producer's API, and
preparing data for merging. Profile `app` (DEV-1.1; `ecosystem.yaml` is
authoritative). Introduction: [README.md](README.md); specification:
[docs/SPEC.md](docs/SPEC.md). The Nogat standard 2.1 is in
[standards/](https://github.com/Daldek/Nogat/tree/main/standards)
(DEVELOPMENT_STANDARDS, DOCUMENTATION_STANDARDS, AGENT_INTERFACE, ERROR_REGISTRY).

## Critical rules

- Work on a topic branch `<type>/<topic>` from `develop`; Conventional Commits in
  English (DEV-4.1); author `Daldek <git@debever.pl>` set per repository (DEV-4.2);
  no AI attribution in messages (DEV-4.3). Without the author's approval in the
  session never merge, tag, publish or rewrite shared history (DEV-3.3); pushing the
  topic branch is allowed.
- Run `scripts/gate.sh` before every commit and do not commit while it fails (DEV-7.6).
- Order of work: specification, then plan, then implementation. A change of a public
  interface or across modules starts with a plan in `docs/plans/YYYY-MM-DD-slug.md`
  (DEV-17.4) that the author approves (`Approved:` line); decisions with alternatives
  are ADRs (DEV-17.2).
- Kartograf is a dependency, public API only (`kartograf.__all__`). Archiwista has no
  downloading or processing of its own; a missing function is a requirement for the
  producer (SPEC section 12), reported as a GitHub issue labelled `request` in the
  producer's repository (DEV-17.5), never a workaround here. Only the Kartograf
  adapter (`src/archiwista/adapter/kartograf/`) imports `kartograf` (a contract test checks it).
- The producer's store is read-only for Archiwista: writes only through the producer's
  API. No SQLite or Archiwista files on a network share or in the store; the index,
  the preview cache and the job history are local and rebuildable. The one exception
  is user data written on the user's command in the project folder (own-data
  snapshots, area files, sets; A-ADR-027): an open format, readable without Archiwista.
- Overriding product principle: layout, interface and API are simple, clear and
  convenient for people.
- Data downloaded while working goes outside the repository and outside `/tmp`, into
  an explicit directory; documents write data paths as `<data-dir>`.
- Python only from `.venv`, through `uv` (DEV-6.2). `uv.lock` is committed; install
  with `uv sync --locked` (DEV-6.3). Kartograf is pinned by commit in `pyproject.toml`
  until its release (REL-5.3); the release pull request replaces the commit with the tag.
- Code, identifiers, comments, docstrings, logs, commit messages, ADRs, plans and
  documents are English (DEV-2.1). Every text for a person has an English and a Polish
  variant in the catalog `src/archiwista/messages/` (one module per area, key
  `<area>.<name>`, rendered with `message`; `tests/unit/test_messages.py` checks every
  call and that no other module holds such a text) and in `web/src/labels/` (DEV-2.3).
  Several documents under `docs/` are still Polish; `docs/PROGRESS.md` lists them. New
  and edited documents are English.
- A change that users see ships with its `docs/CHANGELOG.md` entry in the same commit
  (DOC-7.2); `docs/PROGRESS.md` is updated before the last commit of a session
  (DEV-17.3).

## Environment and commands

```bash
uv sync --locked                       # environment in .venv (DEV-6.2, DEV-6.3)
uv run playwright install chromium     # once, for the interface tests
scripts/gate.sh                        # ruff format, ruff check, mypy, pytest + coverage, commits
uv run pytest tests/unit -q           # a part of the tests (coverage is measured by the gate)
uv run archiwista doctor               # checks the installation
uv run archiwista serve                # the server (prints a one-time address)
```

Python 3.12 or newer. The default run and the gate leave out the markers `live` (real
network services and stores), `perf` (the synthetic store of 50,000 slots) and `smb`
(a real SMB share); each needs its own setup (`.env.example`). `db` and `slow` are
registered (DEV-10.1) and not used yet. Coverage floor 80% (`fail_under` of
`[tool.coverage.report]`; the gate passes `--cov`). Run tests with `TMPDIR` on a local
disk: a network share breaks SQLite and hard links. The full gate takes about 25 minutes
(the interface tests drive Chromium).

## Code map

```
src/archiwista/
├── app.py cli.py server.py config.py doctor.py   # application, CLI entry, server, settings
├── api/            # HTTP routes /api/v1, models, problems (errors.py), OpenAPI (docs.py)
├── adapter/kartograf/  # the Kartograf source plugin: the only importer of kartograf
├── sources/        # plugin protocol, registry, shared types (archiwista.sources entry points)
├── index/          # local SQLite index: schema, scanner, writer, queries
├── jobs/           # background jobs: supervisor, worker processes, scheduler
├── previews/       # render pool, renderers per file kind, content-addressed cache, tiles
├── owndata/        # own project data: scan, reader, snapshots
├── services/ auth/ state/   # services shared by API and CLI, permissions, local state database
├── commands/ reader.py admin.py   # CLI commands
├── errors.py messages/   # exceptions, the message catalog (English and Polish texts)
└── web/            # the build-free interface: Preact + htm modules, vendor/ libraries
tests/{unit,integration,contract,e2e,perf,fixtures}
```

## Project rules

- **Tests** (DEV §10): `unit` (the fixture `index` is an empty index over a generated
  store), `integration` (real worker processes and HTTP: scanner, jobs, CLI equal to
  API, agent flow), `contract` (public API of the producers, the import boundary, the
  error registry, README examples), `e2e` (a real `archiwista serve` and Chromium),
  `perf`, and `fixtures` (`make_store.py` generates a Kartograf store, also of 50,000
  slots from the command line). Markers: `live` (network and real services; a real
  store in `ARCHIWISTA_LIVE_STORE`), `perf` (the synthetic store of 50,000 slots on an
  SSD in `ARCHIWISTA_PERF_STORE`), `smb` (that store on a real SMB 3 share in
  `ARCHIWISTA_SMB_STORE`, the local index directory in `ARCHIWISTA_SMB_WORK`); `perf`
  and `smb` run with `--no-cov`. Names `test_<module>_<function>_<scenario>`; arrange,
  act, assert; a change in `src/archiwista/web/` runs `tests/e2e` too.
- **Public surface**: Archiwista is an application, not a library. Public are the HTTP
  API `/api/v1` (SPEC 9), the `archiwista` command and the source interface for
  plugins (entry-point group `archiwista.sources`, A-ADR-024; `archiwista.sources`
  `__all__`). Plugins and the layers above import that interface; the adapter imports
  `kartograf.__all__` and never an internal module of a producer (A-ADR-014).
- **Errors** (DEV §11): every error is an `ArchiwistaError` of `errors.py` with a code
  of the Nogat registry, a reason, details and a hint; the API, the CLI and the jobs
  describe it through `error_document.describe`. Producer exceptions are caught only in
  the adapter and become `ProducerError` (package, exception, message): the producer's
  text reaches the person unchanged (PRD N1.3). The plugin registry raises
  `SourceUnavailableError` or `SourceIncompatibleError` with the state of the source.
  Validate at the boundary: a path from outside is resolved and must lie inside a
  configured root (`PathOutsideRootError`, SPEC 10.1).
- **Before a commit** run `scripts/gate.sh`; the change also updates the documents it
  makes untrue (SPEC, DECISIONS, CHANGELOG, PROGRESS). Code, comments and docstrings
  are English (NumPy docstrings, enforced by ruff `D`); texts for people are in the
  catalogs only.

## Documentation map

| For | Read |
|---|---|
| Current state, next steps | [docs/PROGRESS.md](docs/PROGRESS.md) |
| Product requirements, scope and stages | [docs/PRD.md](docs/PRD.md), [docs/SCOPE.md](docs/SCOPE.md) |
| Details, use cases, API, requirements for the producers | [docs/SPEC.md](docs/SPEC.md) (13: scope and acceptance of each version; 12: producers) |
| Code architecture | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Decisions | [docs/DECISIONS.md](docs/DECISIONS.md) (A-ADR-001 to 029; from 030 in [docs/decisions/](docs/decisions/)) |
| Views for users; API and CLI for scripts and agents | [docs/USAGE.md](docs/USAGE.md), [docs/AGENT_API.md](docs/AGENT_API.md) |
| Plans (v0.1 and v0.2 executed) | [docs/plans/](docs/plans/) |
| Measurements and acceptance | [docs/reports/](docs/reports/) |
| Changes for users | [docs/CHANGELOG.md](docs/CHANGELOG.md) |
| Formats on disk (sidecar, `data/`, manifest, plan) | Kartograf, not Archiwista: its `docs/ARCHITECTURE.md` 3.1 to 3.5 |

## Session workflow

Start (DEV-17.1): read this file and `docs/PROGRESS.md`, run `git status` and
`git log --oneline -10`, confirm the branch, list the open GitHub issues labelled
`request`. End (DEV-17.3): update `docs/PROGRESS.md` (Status, Next, Open questions)
before the last commit. Change only this repository (DEV-17.5).

## Cross-project context

Registry entry:
[ecosystem.yaml](https://github.com/Daldek/Nogat/blob/main/ecosystem.yaml)
(Archiwista). Kartograf is a runtime dependency (library and store read API,
contract KA-1 to KA-8, SPEC 12); IMGWTools is an optional producer, planned for v0.5
(`archiwista[imgw]`).

## Deviations

- DEV-5.2: `tests/e2e` (browser tests; one Chromium per package, so they cannot move
  under `tests/integration`) and `tests/perf` (measurements on explicit stores) stand
  beside the standard tree.
- DEV-7.7: CI runs on Linux only; the Windows and macOS port is planned for v1.0 and an
  `app` MAY run the platform matrix.
- DEV-10.1: the gate leaves out two markers more than the standard, `perf` (the synthetic
  store of 50,000 slots) and `smb` (a real SMB share), besides `live`.
- DEV-15.1: about 650 lines of the build-free JavaScript exceed 100 columns (templates
  and long Polish texts); there is no formatter (A-ADR-028). New lines keep the limit.
- DEV-16.5: the CLA is signed by a comment on the pull request, as the author's
  `docs/CLA.md` says; the template also carries the checkbox.
- AGI-6.2: the OpenAPI document is `/api/v1/openapi.json` (behind the session, like every
  `/api` route) and `operationId` is the route function name; there is no command catalog.
- DEV-18, DEV-19: profile `tool` only; Archiwista keeps its own `config.toml` and writes no
  data files except snapshots.
- ERR-4: a job that does not succeed, `reindex` and `archiwista doctor` end with the
  outcome statuses 10, 11 and 130 and print no error document; every other refusal ends
  standard error with the `archiwista-error/1` document.
- AGI-3.2, AGI-4.1, AGI-4.2: `--json` output and API responses are the routes' models,
  with no `schema` member and no result envelope; the error document alone is
  `archiwista-error/1`.
- AGI-6.4, AGI-9.2: the texts that are stored when they happen stay Polish whatever
  `Accept-Language` says: the `detail` of a store's status (the `stores.detail` column
  of the index), and the `message` of a job's notices, with the texts inside a job's
  `result` and `error.details` (a job's `detail` and `hint` keep their key and values
  and follow the header). Every other text of the API follows it, English by default.
